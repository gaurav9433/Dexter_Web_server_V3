# db_connection.py
# Dexter HMS — Central SQLite Connection Factory
# Fixes: DB-01 (WAL Mode), DB-02 (FK Enforcement),
#        Consistent PRAGMAs across all 12 databases

import sqlite3
import logging
import threading
from contextlib import contextmanager

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────
# ALL DEXTER DATABASE PATHS — your actual files on RPi
# Change DB_BASE_PATH if you move the project folder
# ─────────────────────────────────────────────────────────────────
DB_BASE_PATH = "/home/pi/Test3"

# Core operational databases
DB_BUFFER               = f"{DB_BASE_PATH}/buffer.db"
DB_PAYLOADS             = f"{DB_BASE_PATH}/payloads.db"
DB_DEVICE_CONFIG        = f"{DB_BASE_PATH}/device_config.db"
DB_NVR_BACS             = f"{DB_BASE_PATH}/nvr_dvr_bacs_integration.db"
DB_TASK_MANAGER         = f"{DB_BASE_PATH}/task_manager.db"
DB_SYSTEM_SETTINGS      = f"{DB_BASE_PATH}/system_settings.db"    # SystemSettingsDB — was data.db in original

# Network & connectivity databases
DB_NETWORK_SETTINGS     = f"{DB_BASE_PATH}/network_settings.db"
DB_MODEM_CONFIG         = f"{DB_BASE_PATH}/modem_config.db"
DB_TAILSCALE            = f"{DB_BASE_PATH}/tailscale_info.db"

# Device parameter databases
DB_LOGICAL_PARAMS       = f"{DB_BASE_PATH}/logical_params_active_integration.db"
DB_CAVLI_RUNNING        = f"{DB_BASE_PATH}/cavliRunningParam.db"
DB_CAVLI_POSITION       = f"{DB_BASE_PATH}/cavliPositionParameter.db"

# Panel / intrusion database
DB_PANEL                = f"{DB_BASE_PATH}/dexterpanel2.db"

# Additional databases — added from module review session
DB_NETWORK_INFO         = f"{DB_BASE_PATH}/network_info.db"         # network_info.py
DB_OPERATOR             = f"{DB_BASE_PATH}/operator_codes.db"        # operator_db.py
DB_CONTROLLER_PARAMS    = f"{DB_BASE_PATH}/parameters.db"            # serial_data_logger.py
DB_ACTIVE_BIT           = f"{DB_BASE_PATH}/active_integration.db"    # updatecode.py / refreshcode.py

# All databases — used by verify_all_databases()
ALL_DATABASES = [
    DB_BUFFER,
    DB_PAYLOADS,
    DB_DEVICE_CONFIG,
    DB_NVR_BACS,
    DB_TASK_MANAGER,
    DB_NETWORK_SETTINGS,
    DB_MODEM_CONFIG,
    DB_TAILSCALE,
    DB_LOGICAL_PARAMS,
    DB_CAVLI_RUNNING,
    DB_CAVLI_POSITION,
    DB_PANEL,
    DB_NETWORK_INFO,
    DB_OPERATOR,
    DB_CONTROLLER_PARAMS,
    DB_ACTIVE_BIT,
]


# ─────────────────────────────────────────────────────────────────
# PRAGMA APPLICATION — called once on every new connection
# ─────────────────────────────────────────────────────────────────
def _apply_pragmas(conn: sqlite3.Connection, db_path: str) -> None:
    """
    Apply full set of production SQLite PRAGMAs.
    Called automatically by get_connection() — never call directly.
    """
    pragmas = [
        # DB-01: WAL mode — readers never block writers
        # Critical: buffer_manager writes and NVR pollers read simultaneously
        "PRAGMA journal_mode=WAL;",

        # DB-02: Foreign key enforcement — off by default in SQLite
        "PRAGMA foreign_keys=ON;",

        # Checkpoint WAL at ~4MB — prevents WAL from growing forever on RPi SD
        "PRAGMA wal_autocheckpoint=1000;",

        # NORMAL is safe with WAL and much faster than FULL on SD card
        "PRAGMA synchronous=NORMAL;",

        # 8MB page cache per connection — reduces repeated SD card reads
        "PRAGMA cache_size=-8000;",

        # 64MB memory-mapped I/O — speeds up read-heavy queries (AI cycle, dashboard)
        "PRAGMA mmap_size=67108864;",

        # Wait 5 seconds on locked DB before raising OperationalError
        # Prevents "database is locked" crash during concurrent writes
        "PRAGMA busy_timeout=5000;",
    ]

    for pragma in pragmas:
        conn.execute(pragma)

    # Verify WAL actually activated (can fail on read-only filesystem)
    result = conn.execute("PRAGMA journal_mode;").fetchone()
    if result and result[0].lower() != 'wal':
        log.warning(
            "WAL mode not active on %s — got '%s'. "
            "Check SD card filesystem permissions.", db_path, result[0]
        )


# ─────────────────────────────────────────────────────────────────
# PRIMARY API — use this everywhere instead of sqlite3.connect()
# ─────────────────────────────────────────────────────────────────
def get_connection(db_path: str,
                   row_factory: bool = True) -> sqlite3.Connection:
    """
    Open a SQLite connection with all production PRAGMAs applied.

    Replaces every bare sqlite3.connect() call across all modules.
    One-line change per module — all query code stays identical.

    Args:
        db_path:     Path to the .db file (use DB_* constants above)
        row_factory: If True, rows accessible by column name (row['column'])
                     Default True — recommended for all modules

    Returns:
        sqlite3.Connection ready for queries

    BEFORE (in each module):
        import sqlite3
        conn = sqlite3.connect('/home/pi/Test3/buffer.db')

    AFTER (one-line change):
        from db_connection import get_connection, DB_BUFFER
        conn = get_connection(DB_BUFFER)
    """
    try:
        conn = sqlite3.connect(db_path, check_same_thread=False)
        if row_factory:
            conn.row_factory = sqlite3.Row
        _apply_pragmas(conn, db_path)
        return conn
    except sqlite3.Error as e:
        log.error("Failed to open database %s: %s", db_path, e)
        raise


# ─────────────────────────────────────────────────────────────────
# CONTEXT MANAGER — for auto commit/rollback
# ─────────────────────────────────────────────────────────────────
@contextmanager
def db_session(db_path: str):
    """
    Context manager: auto-commit on success, auto-rollback on exception.

    Usage:
        with db_session(DB_BUFFER) as conn:
            conn.execute("INSERT INTO buffer (json_object) VALUES (?)", (data,))
        # committed automatically

        with db_session(DB_PAYLOADS) as conn:
            conn.execute("UPDATE json_data SET status='sent' WHERE id=?", (row_id,))
        # rolled back automatically if exception occurs
    """
    conn = get_connection(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────
# STARTUP VERIFICATION — call from TLChronosProMAIN_391.py
# ─────────────────────────────────────────────────────────────────
def verify_all_databases() -> dict:
    """
    Verify WAL mode and FK enforcement are active on all 12 databases.
    Applies WAL if not already set.
    Call at startup in TLChronosProMAIN_391.py after run_all_migrations().

    Returns:
        Dict mapping db_name -> {'wal': bool, 'fk': bool}

    Example startup log output:
        DB check [OK]   buffer.db              WAL=True  FK=True
        DB check [OK]   payloads.db            WAL=True  FK=True
        DB check [WARN] device_config.db       WAL=False FK=True  ← investigate
    """
    results = {}
    for db_path in ALL_DATABASES:
        db_name = db_path.split("/")[-1]
        try:
            conn = sqlite3.connect(db_path)
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA foreign_keys=ON;")
            wal = conn.execute("PRAGMA journal_mode;").fetchone()[0].lower() == 'wal'
            fk  = conn.execute("PRAGMA foreign_keys;").fetchone()[0] == 1
            conn.close()
            results[db_name] = {'wal': wal, 'fk': fk}
            status = "OK  " if wal and fk else "WARN"
            log.info("DB check [%s] %-40s WAL=%-5s FK=%s",
                     status, db_name, wal, fk)
        except sqlite3.Error as e:
            results[db_name] = {'wal': False, 'fk': False, 'error': str(e)}
            log.error("DB check [FAIL] %s: %s", db_name, e)

    return results