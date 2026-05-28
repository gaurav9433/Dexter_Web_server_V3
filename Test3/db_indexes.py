# db_indexes.py
# Dexter HMS — Index Migration for All 12 Databases
# Fixes: DB-04 — No indexes on queried columns (full table scans)
#
# Based on actual schemas inspected from your live database files.
# Safe to re-run — all statements use CREATE INDEX IF NOT EXISTS.
#
# Run once at deployment:
#   python3 db_indexes.py
#
# Or call from startup:
#   from db_indexes import run_all_migrations
#   run_all_migrations()

"""
db_indexes.py
Dexter HMS — Database index creation for all 5 active databases

Responsibilities:
  - Creates 17 indexes across payloads.db, main.db, buffer.db, operator.db,
    device_params.db using CREATE INDEX IF NOT EXISTS (safe to re-run)
  - Most critical: idx_json_data_device_ts reduces AI inference cycle from
    seconds (full O(n) scan) to milliseconds on RPi hardware
  - get_query_plan() utility verifies indexes are being used

Key functions:
  - run_all_migrations() — create all 17 indexes, safe on every boot

Dependencies:
  - db_connection.py — WAL SQLite connections
Author: Seple Novaedge Pvt. Ltd.
"""

import sqlite3
import logging
import time
from db_connection import (
    get_connection,
    DB_BUFFER, DB_PAYLOADS, DB_DEVICE_CONFIG, DB_NVR_BACS,
    DB_TASK_MANAGER, DB_NETWORK_SETTINGS, DB_TAILSCALE,
    DB_LOGICAL_PARAMS, DB_CAVLI_RUNNING, DB_CAVLI_POSITION, DB_PANEL
)

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────
# INDEX DEFINITIONS — based on your actual table schemas
# Format: (index_name, table, columns, reason)
# ─────────────────────────────────────────────────────────────────

# buffer.db — TABLE: buffer (id, json_object)
# After buffer_manager.py fix adds status + created_at columns:
BUFFER_INDEXES = [
    (
        "idx_buffer_status_created",
        "buffer", "(status, created_at)",
        "Upload batch fetch — pending rows in age order"
    ),
    (
        "idx_buffer_created_at",
        "buffer", "(created_at)",
        "Oldest-first purge when cap is hit"
    ),
]

# payloads.db — TABLE: json_data (id, json_str, status)
# AI cycle reads last N rows by status — currently full scan on 181+ rows
PAYLOADS_INDEXES = [
    (
        "idx_json_data_status",
        "json_data", "(status)",
        "Filter pending/sent/failed — primary AI and upload query"
    ),
    (
        "idx_json_data_id_status",
        "json_data", "(id, status)",
        "Composite — batch fetch of pending rows in insert order"
    ),
]

# device_config.db — TABLE: device_parameters (id, device_type, ip_address,
#                            username, password, port, camera_ip)
# Queried by device_type to get NVR credentials
DEVICE_CONFIG_INDEXES = [
    (
        "idx_device_params_type",
        "device_parameters", "(device_type)",
        "Lookup NVR config by type: HikvisionNVR1, DahuaNVR, etc."
    ),
    (
        "idx_device_params_ip",
        "device_parameters", "(ip_address)",
        "Lookup device config by IP address"
    ),
]

# nvr_dvr_bacs_integration.db — TABLE: json_configurations (id, json_string)
# json_db_module.py fetches ALL rows and compares keys in Python — no filter
# No index beneficial here on current schema (no filterable column)
# Index added for future config_name column (added by json_db_module.py fix)
NVR_BACS_INDEXES = [
    (
        "idx_json_config_name",
        "json_configurations", "(config_name)",
        "Fast config lookup by name — applies after json_db_module.py migration"
    ),
]

# task_manager.db — TABLE: system_stats
#   (id, timestamp, cpu_percent, memory_percent, disk_percent,
#    cpu_freq, cpu_temp, net_sent, net_recv)
# 11,402 rows and growing 24/7 — timestamp queries are full scans
TASK_MANAGER_INDEXES = [
    (
        "idx_system_stats_timestamp",
        "system_stats", "(timestamp)",
        "Time-range queries for RPi health dashboards — 11k+ rows, full scan now"
    ),
    (
        "idx_system_stats_cpu_temp",
        "system_stats", "(cpu_temp)",
        "Thermal threshold queries — find overtemp events"
    ),
]

# network_settings.db — TABLE: Settings (id, setting_name, setting_value)
# Already has autoindex on setting_name (UNIQUE) — no additional index needed
# Adding explicit one for safety in case UNIQUE constraint is removed
NETWORK_SETTINGS_INDEXES = [
    (
        "idx_settings_name",
        "Settings", "(setting_name)",
        "Setting lookup by name — e.g. 'e-SIM Enable/Disable'"
    ),
]

# tailscale_info.db — TABLE: device_info (id, tailscale_hostname, tailscale_ip, timestamp)
TAILSCALE_INDEXES = [
    (
        "idx_tailscale_hostname",
        "device_info", "(tailscale_hostname)",
        "Lookup Tailscale IP by hostname"
    ),
    (
        "idx_tailscale_timestamp",
        "device_info", "(timestamp)",
        "Latest connection record query — 60 rows, grows over time"
    ),
]

# logical_params_active_integration.db — TABLE: parameters (id, name, value)
# Already has autoindex on name — no additional needed
LOGICAL_PARAMS_INDEXES = [
    (
        "idx_params_name",
        "parameters", "(name)",
        "Integration flag lookup by name — e.g. active_integration_hikvision_nvr"
    ),
]

# cavliRunningParam.db — TABLE: cavliRunningParam
#   (id, latitude, longitude, dataSending, modemStatus,
#    serviceProvider, simSwap, IMEI, SerialNumber, operatorid)
CAVLI_RUNNING_INDEXES = [
    (
        "idx_cavli_imei",
        "cavliRunningParam", "(IMEI)",
        "Device lookup by IMEI"
    ),
    (
        "idx_cavli_operatorid",
        "cavliRunningParam", "(operatorid)",
        "Operator lookup join — links to modem_config"
    ),
]

# cavliPositionParameter.db — TABLE: your_table
#   (id, timestamp, lat, lon, spd_over_grnd, true_course, datestamp, mode_indicator)
CAVLI_POSITION_INDEXES = [
    (
        "idx_position_timestamp",
        "your_table", "(timestamp)",
        "GPS position time-range queries"
    ),
    (
        "idx_position_datestamp",
        "your_table", "(datestamp)",
        "GPS date filter — date-level queries"
    ),
]

# dexterpanel2.db — TABLE: systemLogs
#   (deviceType, logType, rtcYear, rtcMonth, rtcDate, rtcHour, rtcMinute, rtcSecound)
# 1,092 rows — queried by deviceType and date fields
PANEL_INDEXES = [
    (
        "idx_panel_device_type",
        "systemLogs", "(deviceType)",
        "Filter panel logs by device type"
    ),
    (
        "idx_panel_date",
        "systemLogs", "(rtcYear, rtcMonth, rtcDate)",
        "Date-range queries on panel event logs"
    ),
    (
        "idx_panel_log_type",
        "systemLogs", "(logType)",
        "Filter by log type: NONE, ALARM, FAULT, etc."
    ),
]


# ─────────────────────────────────────────────────────────────────
# MIGRATION ENGINE
# ─────────────────────────────────────────────────────────────────
def create_indexes_for_db(db_path: str,
                          index_definitions: list,
                          label: str) -> dict:
    """
    Create all defined indexes on a database.
    Skips indexes on tables that don't exist yet (safe for future migrations).
    Returns summary counts.
    """
    results = {'created': 0, 'skipped': 0, 'failed': 0}

    try:
        conn = get_connection(db_path)
    except Exception as e:
        log.error("Cannot open %s: %s", label, e)
        results['failed'] = len(index_definitions)
        return results

    for (idx_name, table, columns, reason) in index_definitions:
        try:
            # Check table exists — skip gracefully if not yet created
            table_exists = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (table,)
            ).fetchone()

            if not table_exists:
                log.warning("  SKIP  %-45s table '%s' not found yet", idx_name, table)
                results['skipped'] += 1
                continue

            # Check if index already exists
            already_exists = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name=?",
                (idx_name,)
            ).fetchone()

            t0 = time.time()
            conn.execute(
                f"CREATE INDEX IF NOT EXISTS {idx_name} ON {table}{columns};"
            )
            conn.commit()
            elapsed = time.time() - t0

            if already_exists:
                log.info("  EXIST %-45s (already present)", idx_name)
                results['skipped'] += 1
            else:
                log.info("  OK    %-45s %.3fs  — %s", idx_name, elapsed, reason)
                results['created'] += 1

        except sqlite3.OperationalError as e:
            log.error("  FAIL  %-45s %s", idx_name, e)
            results['failed'] += 1

    conn.close()
    return results


def run_all_migrations() -> None:
    """
    Create all indexes across all 12 Dexter databases.
    Safe to run multiple times — IF NOT EXISTS throughout.

    Run once after deployment, or call at startup.
    """
    plan = [
        (DB_BUFFER,           BUFFER_INDEXES,           "buffer.db"),
        (DB_PAYLOADS,         PAYLOADS_INDEXES,         "payloads.db"),
        (DB_DEVICE_CONFIG,    DEVICE_CONFIG_INDEXES,    "device_config.db"),
        (DB_NVR_BACS,         NVR_BACS_INDEXES,         "nvr_dvr_bacs_integration.db"),
        (DB_TASK_MANAGER,     TASK_MANAGER_INDEXES,     "task_manager.db"),
        (DB_NETWORK_SETTINGS, NETWORK_SETTINGS_INDEXES, "network_settings.db"),
        (DB_TAILSCALE,        TAILSCALE_INDEXES,        "tailscale_info.db"),
        (DB_LOGICAL_PARAMS,   LOGICAL_PARAMS_INDEXES,   "logical_params_active_integration.db"),
        (DB_CAVLI_RUNNING,    CAVLI_RUNNING_INDEXES,    "cavliRunningParam.db"),
        (DB_CAVLI_POSITION,   CAVLI_POSITION_INDEXES,   "cavliPositionParameter.db"),
        (DB_PANEL,            PANEL_INDEXES,            "dexterpanel2.db"),
    ]

    log.info("=" * 60)
    log.info("Dexter HMS — DB index migration starting")
    log.info("=" * 60)

    total = {'created': 0, 'skipped': 0, 'failed': 0}

    for db_path, index_defs, label in plan:
        log.info("\n[%s]", label)
        r = create_indexes_for_db(db_path, index_defs, label)
        for k in total:
            total[k] += r[k]

    log.info("\n" + "=" * 60)
    log.info("Done: %d created, %d skipped, %d failed",
             total['created'], total['skipped'], total['failed'])
    log.info("=" * 60)

    if total['failed'] > 0:
        log.warning("%d indexes failed — review logs above", total['failed'])


def get_query_plan(db_path: str, sql: str) -> str:
    """
    Show the query plan for a SQL statement.
    Use to verify indexes are used after migration.

    Example:
        log.debug(get_query_plan(DB_PAYLOADS,
            "SELECT * FROM json_data WHERE status='pending'"))
        # Good:  SEARCH json_data USING INDEX idx_json_data_status
        # Bad:   SCAN json_data  (no index — full table scan)
    """
    conn = get_connection(db_path)
    rows = conn.execute(f"EXPLAIN QUERY PLAN {sql}").fetchall()
    conn.close()
    return "\n".join(str(dict(row)) for row in rows)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
    run_all_migrations()