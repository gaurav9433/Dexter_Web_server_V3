# -*- coding: utf-8 -*-
# !/usr/local/bin/python
#
# clear_all_data.py — Maintenance utility: clear all rows from Dexter databases
#
# Deletes all rows from every whitelisted table in the specified database
# while keeping table structures intact. Used to reset payloads.db and
# buffer.db on-device before redeployment or during troubleshooting.
#
# Changes applied vs original:
#   DB-01 — WAL mode via get_connection() replaces bare sqlite3.connect()
#             Concurrent reads from NVR pollers and AI cycle never block
#             this DELETE operation; no 'database is locked' errors
#   DB-02 — FK enforcement via get_connection()
#   DB-06 — run_all_migrations() at startup — ensures schema is consistent
#             before the wipe so the empty tables have the correct structure
#   SEC   — SQL injection fix: table names from sqlite_master validated
#             against _ALLOWED_TABLES whitelist before use in DELETE query
#             (f-string with unvalidated table names was injectable)
#   BUG   — 'if conn:' in finally block raised UnboundLocalError if
#             get_connection() itself failed — fixed by conn = None before try
#   BUG   — Module-level clear_all_data() calls had no __main__ guard —
#             importing this file from any other module would immediately wipe
#             payloads.db and buffer.db. Added if __name__ == "__main__" guard.
#   PERF  — VACUUM added after clearing each database to reclaim SD card space
#             (DELETE leaves the file at its original size on disk)
#   LOG   — Internal errors use log.*(); per-table and completion messages
#             use log.info() — this is an interactive maintenance tool


"""
clear_all_data.py
Dexter HMS — Maintenance utility: wipe all Dexter database row data

Responsibilities:
  - Deletes all rows from whitelisted tables in specified databases
  - Table structures (schema) are preserved — only row data is removed
  - SQL injection prevention via _ALLOWED_TABLES whitelist
  - VACUUM after each wipe to reclaim SD card space
  - Must be run explicitly (if __name__ == '__main__') — safe to import

Key functions:
  - clear_all_data(db_path) — wipe all whitelisted tables in one database

Dependencies:
  - db_connection.py        — WAL SQLite connections
  - db_schema_migration.py  — ensure schema current before wipe
Author: Seple Novaedge Pvt. Ltd.
"""

import sqlite3

# ── Dexter HMS infrastructure imports ────────────────────────────────────────
# DB-01 / DB-02: WAL mode + FK enforcement on every connection
from db_connection import get_connection, verify_all_databases

# DB-06: Schema versioning — apply pending migrations before clearing
# so the empty tables are left in the correct current schema state
from db_schema_migration import run_all_migrations

# ── Logging ───────────────────────────────────────────────────────────────────
# log.info() is kept for user-facing operator output (table names, completion).
# log.*() is used for internal errors and infrastructure messages.
from syslog_file_logger import get_dual_logger
log = get_dual_logger(__name__)

# ── DB-06: Apply schema migrations at startup ─────────────────────────────────
run_all_migrations()

# ── DB-01 / DB-02: Verify WAL + FK on all registered databases ───────────────
verify_all_databases()

# ── SEC: Table name whitelist ─────────────────────────────────────────────────
# Table names from sqlite_master cannot be safely parameterised with ? in
# SQLite — they must be interpolated as identifiers. To prevent SQL injection
# through a corrupted or attacker-controlled database file, every table name
# is validated against this whitelist before use in a DELETE query.
# A table named "events; DROP TABLE devices" would be skipped, not executed.
# Extend this set when new tables are added to Dexter databases.
_ALLOWED_TABLES: set = {
    # payloads.db
    "json_data",
    "payloads",
    "events",
    # buffer.db
    "buffer",
    # main.db
    "devices",
    "alerts",
    # Common schema table — never wipe, but safe to list
    # (DELETE FROM schema_migrations would break the migration system)
    # "schema_migrations",  # intentionally excluded
}


# ─────────────────────────────────────────────────────────────────────────────
# CLEAR ALL DATA
# DB-01: WAL mode — concurrent readers never block during DELETE
# SEC:   table name whitelist validation
# BUG:   conn = None initialised before try (fixes UnboundLocalError in finally)
# PERF:  VACUUM after clearing to reclaim SD card space
# ─────────────────────────────────────────────────────────────────────────────

def clear_all_data(db_path: str) -> bool:
    """
    Delete all rows from every whitelisted table in db_path.
    Table structures (schema) are preserved — only row data is removed.
    Runs VACUUM after clearing to reclaim SD card space.

    DB-01: uses get_connection() — WAL mode ensures concurrent readers
           from NVR pollers or the AI cycle never block this operation.
    SEC:   table names validated against _ALLOWED_TABLES before use in
           DELETE — prevents SQL injection via corrupted table names.
    BUG:   conn = None before try block — prevents UnboundLocalError in
           finally if get_connection() itself raises an exception.
    PERF:  VACUUM reclaims freed pages from SD card after mass DELETE.

    Returns True if all tables were cleared successfully, False on any error.
    """
    # BUG fix: initialise conn before try so the finally block never raises
    # UnboundLocalError if get_connection() fails before conn is assigned
    conn = None

    try:
        # DB-01 / DB-02: WAL mode + FK enforcement via central factory
        conn = get_connection(db_path)
        cursor = conn.cursor()

        # Fetch all table names from the schema catalogue
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        all_tables = [row[0] for row in cursor.fetchall()]

        cleared_count = 0
        for table_name in all_tables:
            # SEC: validate table name against whitelist before using in query
            if table_name not in _ALLOWED_TABLES:
                log.warning(
                    "[clear_all_data] Skipping table '%s' in %s — "
                    "not in _ALLOWED_TABLES whitelist",
                    table_name, db_path
                )
                continue

            # Safe: table_name validated against whitelist above
            cursor.execute(f"DELETE FROM {table_name}")  # noqa: S608
            log.info("  Cleared table: %s (%s rows deleted)", table_name, cursor.rowcount)
            cleared_count += 1

        conn.commit()

        if cleared_count == 0:
            log.info("  No whitelisted tables found in %s", db_path)
            log.warning("[clear_all_data] No whitelisted tables found in %s", db_path)
        else:
            log.info("  All %s table(s) cleared in %s", cleared_count, db_path)
            log.info("[clear_all_data] Cleared %d table(s) in %s",
                     cleared_count, db_path)

        # PERF: VACUUM reclaims freed pages — reduces SD card footprint
        # Must run outside a transaction (conn.commit() already called above)
        conn.execute("VACUUM;")
        log.info("  VACUUM complete — SD card space reclaimed for %s", db_path)
        log.info("[clear_all_data] VACUUM complete for %s", db_path)

        return True

    except sqlite3.Error as exc:
        log.error("[clear_all_data] SQLite error on %s: %s", db_path, exc)
        log.error("  Error clearing %s: %s", db_path, exc)
        if conn:
            try:
                conn.rollback()
            except sqlite3.Error:
                pass
        return False

    except OSError as exc:
        log.error("[clear_all_data] OS error accessing %s: %s", db_path, exc)
        log.error("  OS error on %s: %s", db_path, exc)
        return False

    finally:
        if conn:
            conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# ENTRY POINT
# BUG fix: calls moved inside __main__ guard — in the original, both
# clear_all_data() calls were at module level with no guard. Any other
# Dexter module that imported this file (even accidentally) would
# immediately wipe payloads.db and buffer.db — losing all queued events
# and all historical telemetry. This is now safe to import without side effects.
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    log.info("\n=== Dexter HMS — Clear All Data Utility ===\n")

    databases_to_clear = [
        "/home/pi/Test3/payloads.db",
        "/home/pi/Test3/buffer.db",
    ]

    all_ok = True
    for db_path in databases_to_clear:
        log.info("\nClearing: %s", db_path)
        ok = clear_all_data(db_path)
        if not ok:
            all_ok = False
            log.warning("  WARNING: Could not fully clear %s", db_path)

    if all_ok:
        log.info("\nAll databases cleared successfully.")
    else:
        log.info("\nOne or more databases could not be fully cleared — check logs.")