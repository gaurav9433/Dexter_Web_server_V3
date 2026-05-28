# db_schema_migration.py
# Dexter HMS — Schema Version Tracker & Migration Runner
# Fixes: DB-06 — No schema versioning
#
# Tracks applied migrations in a schema_migrations table per database.
# Each migration runs exactly once, in order, and is never re-applied.
# Safe to call at every startup.
#
# Add to TLChronosProMAIN_391.py startup (before any DB operations):
#   from db_schema_migration import run_all_migrations
#   from db_connection import verify_all_databases
#   run_all_migrations()
#   verify_all_databases()
#
# Changes from previous version:
#   FIX-01 : DB_MODEM_CONFIG was missing from run_all_migrations() plan.
#            DeviceProvisioning_Module.py comment stated modem_config.db is
#            "owned by db_schema_migration.py" but modem_parameters table was
#            never created here. On a fresh device every _get_modem_parameter()
#            call returned None, device_name was None, and form_basic() returned
#            False before connecting to ThingsBoard.
#            → MODEM_CONFIG_MIGRATIONS added; DB_MODEM_CONFIG added to plan[].
#            Schema matches actual 19-column modem_config.db:
#              id, access_token, client_id, user_name, password,
#              gsm_modem_mode, network_type, device_name,
#              batch_number, panel_number,
#              swatch_mqtt_host, swatch_host, swatch_username, swatch_password
#            Note: active_integration_* columns are NOT in modem_config.db;
#            their authoritative values live in logical_params_active_integration.db.

import sqlite3
import logging
from db_connection import (
    get_connection,
    DB_BUFFER, DB_PAYLOADS, DB_DEVICE_CONFIG, DB_NVR_BACS,
    DB_TASK_MANAGER, DB_NETWORK_SETTINGS, DB_TAILSCALE,
    DB_LOGICAL_PARAMS, DB_CAVLI_RUNNING, DB_CAVLI_POSITION, DB_PANEL,
    DB_MODEM_CONFIG,   # FIX-01: added
)

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────
# MIGRATION TABLE — created in every database to track versions
# ─────────────────────────────────────────────────────────────────
MIGRATION_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    version     TEXT    NOT NULL UNIQUE,
    description TEXT    NOT NULL,
    applied_at  INTEGER NOT NULL DEFAULT (strftime('%s','now'))
);
"""

# ─────────────────────────────────────────────────────────────────
# MIGRATIONS PER DATABASE
# Each entry: (version_string, description, [sql_statements])
# Once a version is applied it is NEVER run again.
# ─────────────────────────────────────────────────────────────────

# ── buffer.db ────────────────────────────────────────────────────
BUFFER_MIGRATIONS = [
    (
        "001_wal_mode",
        "Enable WAL journal mode",
        ["PRAGMA journal_mode=WAL;"]
    ),
    (
        "002_add_status_column",
        "Add status column for upload delivery tracking (pending/sent/failed)",
        ["ALTER TABLE buffer ADD COLUMN status TEXT NOT NULL DEFAULT 'pending';"]
    ),
    (
        "003_add_retry_count",
        "Add retry_count to track failed upload attempts per event",
        ["ALTER TABLE buffer ADD COLUMN retry_count INTEGER NOT NULL DEFAULT 0;"]
    ),
    (
        "004_add_created_at",
        "Add created_at for TTL purge and oldest-first ordering",
        ["ALTER TABLE buffer ADD COLUMN created_at INTEGER NOT NULL DEFAULT (strftime('%s','now'));"]
    ),
    (
        "005_add_sent_at",
        "Add sent_at timestamp for delivery audit trail",
        ["ALTER TABLE buffer ADD COLUMN sent_at INTEGER;"]
    ),
    (
        "006_add_buffer_indexes",
        "Add indexes for upload batch fetch and cap purge",
        [
            "CREATE INDEX IF NOT EXISTS idx_buffer_status_created ON buffer(status, created_at);",
            "CREATE INDEX IF NOT EXISTS idx_buffer_created_at     ON buffer(created_at);",
        ]
    ),
]

# ── payloads.db ───────────────────────────────────────────────────
PAYLOADS_MIGRATIONS = [
    (
        "001_wal_mode",
        "Enable WAL mode on payloads database",
        ["PRAGMA journal_mode=WAL;"]
    ),
    (
        "002_add_payload_indexes",
        "Add indexes on status and id for AI cycle and upload queries",
        [
            "CREATE INDEX IF NOT EXISTS idx_json_data_status    ON json_data(status);",
            "CREATE INDEX IF NOT EXISTS idx_json_data_id_status ON json_data(id, status);",
        ]
    ),
]

# ── device_config.db ─────────────────────────────────────────────
DEVICE_CONFIG_MIGRATIONS = [
    (
        "001_wal_mode",
        "Enable WAL mode on device_config database",
        ["PRAGMA journal_mode=WAL;"]
    ),
    (
        "002_add_device_indexes",
        "Add indexes for NVR config lookup by type and IP",
        [
            "CREATE INDEX IF NOT EXISTS idx_device_params_type ON device_parameters(device_type);",
            "CREATE INDEX IF NOT EXISTS idx_device_params_ip   ON device_parameters(ip_address);",
        ]
    ),
    (
        "003_add_credential_hash_column",
        "Add column to store hashed/encrypted credential reference (SEC-04 prep)",
        ["ALTER TABLE device_parameters ADD COLUMN credential_ref TEXT;"]
    ),
]

# ── nvr_dvr_bacs_integration.db ──────────────────────────────────
NVR_BACS_MIGRATIONS = [
    (
        "001_wal_mode",
        "Enable WAL mode on nvr_dvr_bacs_integration database",
        ["PRAGMA journal_mode=WAL;"]
    ),
    (
        "002_add_config_name_column",
        "Add config_name for named config storage and lookup",
        ["ALTER TABLE json_configurations ADD COLUMN config_name TEXT;"]
    ),
    (
        "003_add_timestamps",
        "Add created_at and updated_at audit columns",
        [
            "ALTER TABLE json_configurations ADD COLUMN created_at INTEGER DEFAULT 0;",
            "ALTER TABLE json_configurations ADD COLUMN updated_at INTEGER DEFAULT 0;",
        ]
    ),
    (
        "004_add_config_name_index",
        "Add index on config_name for fast named lookup",
        ["CREATE INDEX IF NOT EXISTS idx_json_config_name ON json_configurations(config_name);"]
    ),
]

# ── task_manager.db ───────────────────────────────────────────────
TASK_MANAGER_MIGRATIONS = [
    (
        "001_wal_mode",
        "Enable WAL mode on task_manager database",
        ["PRAGMA journal_mode=WAL;"]
    ),
    (
        "002_add_stats_indexes",
        "Add indexes on timestamp and cpu_temp for health monitoring queries",
        [
            "CREATE INDEX IF NOT EXISTS idx_system_stats_timestamp ON system_stats(timestamp);",
            "CREATE INDEX IF NOT EXISTS idx_system_stats_cpu_temp  ON system_stats(cpu_temp);",
        ]
    ),
]

# ── network_settings.db ───────────────────────────────────────────
NETWORK_SETTINGS_MIGRATIONS = [
    (
        "001_wal_mode",
        "Enable WAL mode on network_settings database",
        ["PRAGMA journal_mode=WAL;"]
    ),
]

# ── tailscale_info.db ────────────────────────────────────────────
TAILSCALE_MIGRATIONS = [
    (
        "001_wal_mode",
        "Enable WAL mode on tailscale_info database",
        ["PRAGMA journal_mode=WAL;"]
    ),
]

# ── logical_params_active_integration.db ─────────────────────────
LOGICAL_PARAMS_MIGRATIONS = [
    (
        "001_wal_mode",
        "Enable WAL mode on logical_params database",
        ["PRAGMA journal_mode=WAL;"]
    ),
]

# ── cavliRunningParam.db ──────────────────────────────────────────
CAVLI_RUNNING_MIGRATIONS = [
    (
        "001_wal_mode",
        "Enable WAL mode on cavliRunningParam database",
        ["PRAGMA journal_mode=WAL;"]
    ),
    (
        "002_add_cavli_indexes",
        "Add indexes for IMEI and operator lookup",
        [
            "CREATE INDEX IF NOT EXISTS idx_cavli_imei       ON cavliRunningParam(IMEI);",
            "CREATE INDEX IF NOT EXISTS idx_cavli_operatorid ON cavliRunningParam(operatorid);",
        ]
    ),
]

# ── cavliPositionParameter.db ─────────────────────────────────────
CAVLI_POSITION_MIGRATIONS = [
    (
        "001_wal_mode",
        "Enable WAL mode on cavliPositionParameter database",
        ["PRAGMA journal_mode=WAL;"]
    ),
]

# ── dexterpanel2.db ───────────────────────────────────────────────
PANEL_MIGRATIONS = [
    (
        "001_wal_mode",
        "Enable WAL mode on dexterpanel2 database",
        ["PRAGMA journal_mode=WAL;"]
    ),
    (
        "002_add_panel_indexes",
        "Add indexes for panel log queries by device, date, and type",
        [
            "CREATE INDEX IF NOT EXISTS idx_panel_device_type ON systemLogs(deviceType);",
            "CREATE INDEX IF NOT EXISTS idx_panel_date        ON systemLogs(rtcYear, rtcMonth, rtcDate);",
            "CREATE INDEX IF NOT EXISTS idx_panel_log_type    ON systemLogs(logType);",
        ]
    ),
]

# ── modem_config.db ───────────────────────────────────────────────
# Canonical 17-column schema. Unused columns removed by 005_final_schema_cleanup:
#   thingsboard_host, thingsboard_username, thingsboard_password
#     → superseded by swatch_host / swatch_username / swatch_password / swatch_mqtt_host
#   active_integration_hikvision_nvr / dahua_nvr / cp_plus_nvr / hikvision_biometric
#     → authoritative values live in logical_params_active_integration.db, never here
MODEM_CONFIG_MIGRATIONS = [
    (
        "001_create_modem_parameters",
        "Create modem_parameters table (17-column canonical schema) and seed row id=1",
        [
            """CREATE TABLE IF NOT EXISTS modem_parameters (
                id                      INTEGER PRIMARY KEY,
                access_token            TEXT,
                client_id               TEXT,
                user_name               TEXT,
                password                TEXT,
                gsm_modem_mode          TEXT,
                network_type            TEXT,
                device_name             TEXT,
                batch_number            TEXT,
                panel_number            TEXT,
                swatch_mqtt_host        TEXT,
                swatch_host             TEXT,
                swatch_username         TEXT,
                swatch_password         TEXT,
                provision_device_key    TEXT,
                provision_device_secret TEXT,
                failover_active         TEXT DEFAULT '0'
            )""",
            """INSERT OR IGNORE INTO modem_parameters (id, gsm_modem_mode, network_type)
               VALUES (1, 'esim', 'ethernet')""",
        ]
    ),
    (
        "002_wal_mode",
        "Enable WAL mode on modem_config database",
        ["PRAGMA journal_mode=WAL;"]
    ),
    (
        "003_remove_unused_columns",
        "Version marker only — existing devices have this version applied with "
        "different SQL bodies; skipped on those devices. Cleanup is performed by "
        "005_final_schema_cleanup. On a fresh device (running 001 first) this "
        "migration is a no-op.",
        ["SELECT 1"],
    ),
    (
        "004_failover_active_flag",
        "Add failover_active column to persist auto-failover state across container restarts",
        [
            # ALTER TABLE fails silently as duplicate-column if 001 already added it — OK.
            "ALTER TABLE modem_parameters ADD COLUMN failover_active TEXT DEFAULT '0'",
        ]
    ),
    (
        "005_final_schema_cleanup",
        "Remove 7 confirmed-unused columns from modem_parameters via rename-copy-drop. "
        "Removed: thingsboard_host, thingsboard_username, thingsboard_password "
        "(superseded by swatch_host/username/password + swatch_mqtt_host), "
        "active_integration_hikvision_nvr, active_integration_dahua_nvr, "
        "active_integration_cp_plus_nvr, active_integration_hikvision_biometric "
        "(authoritative source is logical_params_active_integration.db). "
        "Final schema: 17 columns. Works on SQLite < 3.35.0 (no DROP COLUMN support).",
        [
            "ALTER TABLE modem_parameters RENAME TO modem_parameters_old",

            """CREATE TABLE modem_parameters (
                id                      INTEGER PRIMARY KEY,
                access_token            TEXT,
                client_id               TEXT,
                user_name               TEXT,
                password                TEXT,
                gsm_modem_mode          TEXT,
                network_type            TEXT,
                device_name             TEXT,
                batch_number            TEXT,
                panel_number            TEXT,
                swatch_mqtt_host        TEXT,
                swatch_host             TEXT,
                swatch_username         TEXT,
                swatch_password         TEXT,
                provision_device_key    TEXT,
                provision_device_secret TEXT,
                failover_active         TEXT DEFAULT '0'
            )""",

            """INSERT INTO modem_parameters (
                id, access_token, client_id, user_name, password,
                gsm_modem_mode, network_type, device_name,
                batch_number, panel_number,
                swatch_mqtt_host, swatch_host, swatch_username, swatch_password,
                provision_device_key, provision_device_secret, failover_active
            )
            SELECT
                id, access_token, client_id, user_name, password,
                gsm_modem_mode, network_type, device_name,
                batch_number, panel_number,
                swatch_mqtt_host, swatch_host, swatch_username, swatch_password,
                provision_device_key, provision_device_secret, failover_active
            FROM modem_parameters_old""",

            "DROP TABLE modem_parameters_old",
        ]
    ),
]


# ─────────────────────────────────────────────────────────────────
# MIGRATION RUNNER ENGINE
# ─────────────────────────────────────────────────────────────────
def _ensure_migration_table(conn: sqlite3.Connection) -> None:
    conn.executescript(MIGRATION_TABLE_SQL)
    conn.commit()


def _get_applied_versions(conn: sqlite3.Connection) -> set:
    try:
        rows = conn.execute(
            "SELECT version FROM schema_migrations"
        ).fetchall()
        return {row[0] for row in rows}
    except sqlite3.OperationalError:
        return set()


def run_migrations(db_path: str, migrations: list) -> dict:
    """
    Apply pending migrations to one database.
    Already-applied versions are skipped.
    ALTER TABLE failures from duplicate columns are warned, not fatal.
    """
    results = {'applied': 0, 'skipped': 0, 'failed': 0}

    conn = get_connection(db_path)
    _ensure_migration_table(conn)
    applied = _get_applied_versions(conn)

    for (version, description, sql_list) in migrations:
        if version in applied:
            results['skipped'] += 1
            continue

        log.info("  Applying %s: %s", version, description)
        try:
            # Explicit BEGIN so all statements in this migration (including
            # multi-step rename-copy-drop) are atomic. A crash mid-way
            # rolls back to the original state — no half-renamed tables.
            conn.execute("BEGIN")
            for sql in sql_list:
                try:
                    conn.execute(sql)
                except sqlite3.OperationalError as e:
                    if "duplicate column" in str(e).lower():
                        log.warning("    Column exists already — skipping: %s", sql[:80])
                    else:
                        raise

            conn.execute(
                "INSERT INTO schema_migrations (version, description) VALUES (?,?)",
                (version, description)
            )
            conn.execute("COMMIT")
            results['applied'] += 1
            log.info("  Applied  %s OK", version)

        except sqlite3.Error as e:
            try:
                conn.execute("ROLLBACK")
            except Exception:
                pass
            if "no such table" in str(e).lower():
                log.warning("  DEFERRED %s: table not yet created (%s)", version, e)
                results['skipped'] += 1
            else:
                results['failed'] += 1
                log.error("  FAILED   %s: %s", version, e)

    conn.close()
    return results


def _sync_network_type_from_env() -> None:
    """
    If NETWORK_TYPE is set in .env and the DB value is empty/null, write the
    env value as the factory default (first-boot only).

    Migration 001 seeds network_type='ethernet'. For fresh GSM devices that
    cannot reach the LCD before first boot, NETWORK_TYPE=gsm in .env sets
    the correct default on first startup only.

    If the DB already has a valid value ('ethernet' or 'gsm') — meaning the
    LCD or webserver has been used — the env var is ignored so that user
    changes survive container restarts.
    """
    try:
        from secrets_manager import get_secret
        env_val = get_secret("NETWORK_TYPE").strip().lower()
    except (KeyError, RuntimeError, ImportError):
        return   # NETWORK_TYPE not in .env — nothing to do

    if env_val not in ("ethernet", "gsm"):
        log.warning(
            "[migration] NETWORK_TYPE='%s' invalid — must be 'ethernet' or 'gsm'. Ignored.",
            env_val
        )
        return

    conn = get_connection(DB_MODEM_CONFIG)
    try:
        row = conn.execute(
            "SELECT network_type FROM modem_parameters WHERE id = 1"
        ).fetchone()
        if not row:
            return
        db_val = (row[0] or "").strip()
        # Treat any valid DB value as user-set — env is a factory default only.
        if db_val in ("ethernet", "gsm"):
            return
        conn.execute(
            "UPDATE modem_parameters SET network_type = ? WHERE id = 1",
            (env_val,)
        )
        conn.commit()
        log.info(
            "[migration] network_type set to '%s' from NETWORK_TYPE env var (first-boot default)",
            env_val
        )
    except Exception as exc:
        log.warning("[migration] network_type env sync failed — %s", exc)
        try:
            conn.rollback()
        except Exception:
            pass
    finally:
        conn.close()


def run_all_migrations() -> None:
    """
    Run all pending migrations across all Dexter databases.
    Call at TLChronosProMAIN_391.py startup before any DB operations.
    """
    plan = [
        (DB_BUFFER,           BUFFER_MIGRATIONS,           "buffer.db"),
        (DB_PAYLOADS,         PAYLOADS_MIGRATIONS,         "payloads.db"),
        (DB_DEVICE_CONFIG,    DEVICE_CONFIG_MIGRATIONS,    "device_config.db"),
        (DB_NVR_BACS,         NVR_BACS_MIGRATIONS,         "nvr_dvr_bacs_integration.db"),
        (DB_TASK_MANAGER,     TASK_MANAGER_MIGRATIONS,     "task_manager.db"),
        (DB_NETWORK_SETTINGS, NETWORK_SETTINGS_MIGRATIONS, "network_settings.db"),
        (DB_TAILSCALE,        TAILSCALE_MIGRATIONS,        "tailscale_info.db"),
        (DB_LOGICAL_PARAMS,   LOGICAL_PARAMS_MIGRATIONS,   "logical_params_active_integration.db"),
        (DB_CAVLI_RUNNING,    CAVLI_RUNNING_MIGRATIONS,    "cavliRunningParam.db"),
        (DB_CAVLI_POSITION,   CAVLI_POSITION_MIGRATIONS,   "cavliPositionParameter.db"),
        (DB_PANEL,            PANEL_MIGRATIONS,            "dexterpanel2.db"),
        (DB_MODEM_CONFIG,     MODEM_CONFIG_MIGRATIONS,     "modem_config.db"),   # FIX-01
    ]

    log.info("Dexter HMS — running schema migrations")
    total = {'applied': 0, 'skipped': 0, 'failed': 0}

    for db_path, migrations, label in plan:
        log.info("[%s]", label)
        r = run_migrations(db_path, migrations)
        for k in total:
            total[k] += r[k]
        log.info("  → %d applied, %d skipped, %d failed",
                 r['applied'], r['skipped'], r['failed'])

    log.info("Migrations complete — %d applied, %d skipped, %d failed",
             total['applied'], total['skipped'], total['failed'])

    if total['failed'] > 0:
        log.error(
            'Migrations: %d failed (non-table errors). Check logs.',
            total['failed']
        )

    # Sync network_type from NETWORK_TYPE env var if set.
    # Handles fresh Docker GSM devices where the migration seed default ('ethernet')
    # does not match the actual network mode.
    _sync_network_type_from_env()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
    run_all_migrations()
