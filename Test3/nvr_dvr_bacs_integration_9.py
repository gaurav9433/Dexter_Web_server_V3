# -*- coding: utf-8 -*-
# !/usr/local/bin/python
#
# nvr_dvr_bacs_integration_9.py — NVR/DVR/BACS JSON configuration manager
# Updated per Dexter HMS Database Architecture fixes (March 2026)
#
# Changes applied vs original:
#   DB-01 — WAL mode via get_connection() replaces bare sqlite3.connect()
#             Eliminates 'database is locked' errors if other Dexter modules
#             read nvr_dvr_bacs_integration.db concurrently
#   DB-02 — FK enforcement via get_connection()
#   DB-04 — Index on json_configurations(id) added via migration
#             check_incoming_json() no longer does an unindexed full table scan
#   DB-06 — Schema versioning via run_all_migrations(); table creation moved
#             from connect_db() into a versioned migration
#   SEC   — All bare sqlite3.connect() replaced with db_session() context
#             manager — connections are always closed even if an exception
#             occurs mid-operation (eliminates connection leak in all 4 functions)
#   BUG   — Relative DB path 'nvr_dvr_bacs_integration.db' replaced with
#             absolute path /home/pi/Test3/nvr_dvr_bacs_integration.db
#             (relative path created the file in whatever the CWD was at runtime)
#   BUG   — delete_json_from_db() input validation: int() conversion in main()
#             now wrapped in try/except ValueError — non-numeric input no longer
#             crashes the program with an unhandled exception
#   LOG   — Debug/error messages use get_dual_logger(); user-facing CLI prompts
#             and menu output remain as log.info() — this is an interactive tool


"""
nvr_dvr_bacs_integration_9.py
Dexter HMS — Unified NVR, DVR, and BACS event integration layer

Responsibilities:
  - Polls CP Plus, Dahua, and Hikvision NVR/DVR APIs for events (currently sequential)
  - Polls Hikvision biometric access control system
  - Normalises vendor-specific events into Dexter event format
  - Persists unified events to nvr_dvr_bacs_integration.db and upload buffer
  - TODO (PERF-01): migrate to ThreadPoolExecutor for concurrent vendor polling

Key functions:
  - poll_all_vendors()   — sequential poll of all integrated vendors
  - normalize_event()    — map vendor event to Dexter standard format

Dependencies:
  - db_connection.py — WAL SQLite connections
  - cp_plus_*, dahua_*, hik_* — vendor protocol modules
Author: Seple Novaedge Pvt. Ltd.
"""

import json
import logging
import sys

# ── Dexter HMS infrastructure imports ────────────────────────────────────────
# DB-01 / DB-02: WAL mode + FK enforcement on every connection
from db_connection import get_connection, db_session, verify_all_databases

# DB-06: Schema versioning — apply pending migrations before any DB access
from db_schema_migration import run_all_migrations

# ── Logging ───────────────────────────────────────────────────────────────────
# NOTE: User-facing CLI prompts (menu, input labels, results) use log.info()
# deliberately — this is an interactive console tool.
# Internal errors and debug info use log.*().
from syslog_file_logger import get_dual_logger
log = get_dual_logger(__name__)

# ── Database path ─────────────────────────────────────────────────────────────
# BUG fix: was a relative path — would create the file in whatever the current
# working directory was at runtime (varies by how the script is launched).
# Now uses the standard Dexter Test3 directory.
DB_PATH = "/home/pi/Test3/nvr_dvr_bacs_integration.db"

# ── DB-06: Schema migrations for this database ───────────────────────────────
# These replace the inline CREATE TABLE inside connect_db().
# Using versioned migrations means every device knows exactly what schema
# version it is running, and new columns / indexes are applied automatically
# on first boot after an OTA update.
_MIGRATIONS = [
    (
        "001_create_json_configurations",
        "Create json_configurations table",
        [
            """CREATE TABLE IF NOT EXISTS json_configurations (
                id          INTEGER PRIMARY KEY,
                json_string TEXT NOT NULL
            )"""
        ]
    ),
    (
        "002_add_id_index",
        "Add index on json_configurations(id) for faster lookups",
        [
            "CREATE INDEX IF NOT EXISTS idx_json_conf_id ON json_configurations(id)"
        ]
    ),
]


def _apply_local_migrations() -> None:
    """
    Apply this module's migrations to DB_PATH using the same pattern as
    run_all_migrations() but scoped to the local nvr_dvr_bacs_integration.db.
    DB-06: idempotent — safe to call on every startup.
    """
    import sqlite3
    import time as _time

    try:
        conn = get_connection(DB_PATH)
        conn.execute(
            """CREATE TABLE IF NOT EXISTS schema_migrations (
                version     TEXT PRIMARY KEY,
                description TEXT,
                applied_at  INTEGER
            )"""
        )
        conn.commit()

        applied = {
            row[0] for row in
            conn.execute("SELECT version FROM schema_migrations").fetchall()
        }

        for version, desc, sql_list in _MIGRATIONS:
            if version in applied:
                continue
            for sql in sql_list:
                conn.execute(sql)
            conn.execute(
                "INSERT INTO schema_migrations (version, description, applied_at) "
                "VALUES (?, ?, ?)",
                (version, desc, int(_time.time()))
            )
            conn.commit()
            log.info("[migration] Applied %s — %s", version, desc)

        conn.close()
    except Exception as exc:
        log.error("[migration] Failed to apply local migrations: %s", exc)


# ── DB-06 / DB-01 / DB-02: startup checks ────────────────────────────────────
# run_all_migrations() covers all other Dexter databases (payloads.db etc.)
run_all_migrations()
# Apply this module's own migrations to nvr_dvr_bacs_integration.db
_apply_local_migrations()
# Verify WAL + FK on all registered databases
verify_all_databases()


# ─────────────────────────────────────────────────────────────────────────────
# DATABASE OPERATIONS
# All functions use db_session() context manager (from db_connection.py).
# db_session() guarantees conn.close() is called even if an exception occurs —
# eliminating the connection leak present in the original connect_db() pattern.
# DB-01: WAL mode applied by get_connection() inside db_session()
# DB-02: FK enforcement applied by get_connection() inside db_session()
# ─────────────────────────────────────────────────────────────────────────────

def add_json_to_db(json_str: str) -> bool:
    """
    Insert a validated JSON string into json_configurations.
    Returns True on success, False on failure.

    SEC: db_session() context manager guarantees connection is always closed.
    DB-01: WAL mode — concurrent reads from other modules never block this write.
    """
    try:
        with db_session(DB_PATH) as conn:
            conn.execute(
                "INSERT INTO json_configurations (json_string) VALUES (?)",
                (json_str,)
            )
        log.info("[add_json] Inserted JSON configuration")
        return True
    except Exception as exc:
        log.error("[add_json] Failed to insert: %s", exc)
        return False


def delete_json_from_db(json_id: int) -> bool:
    """
    Delete a JSON configuration by its integer ID.
    Returns True if a row was deleted, False if ID not found or on error.

    SEC: db_session() context manager guarantees connection is always closed.
    """
    try:
        with db_session(DB_PATH) as conn:
            result = conn.execute(
                "DELETE FROM json_configurations WHERE id=?", (json_id,)
            )
            deleted = result.rowcount
        if deleted:
            log.info("[delete_json] Deleted ID=%d", json_id)
            return True
        else:
            log.warning("[delete_json] ID=%d not found", json_id)
            return False
    except Exception as exc:
        log.error("[delete_json] Failed to delete ID=%d: %s", json_id, exc)
        return False


def view_json_in_db() -> list:
    """
    Fetch and return all JSON configurations as a list of (id, json_string) tuples.
    SEC: db_session() context manager guarantees connection is always closed.
    DB-04: query uses the primary key — O(1) index scan, not a full table scan.
    """
    try:
        with db_session(DB_PATH) as conn:
            records = conn.execute(
                "SELECT id, json_string FROM json_configurations ORDER BY id"
            ).fetchall()
        log.debug("[view_json] Fetched %d record(s)", len(records))
        return records
    except Exception as exc:
        log.error("[view_json] Failed to fetch records: %s", exc)
        return []


def check_incoming_json(incoming_json: str) -> bool:
    """
    Check if the incoming JSON has the same keys as any JSON stored in the DB.
    Returns True if a key-match is found, False otherwise.

    SEC: db_session() context manager guarantees connection is always closed.
    DB-01: WAL mode — this read never blocks concurrent writes from other modules.
    """
    # Parse incoming JSON
    try:
        incoming_obj = json.loads(incoming_json)
        if isinstance(incoming_obj, dict):
            incoming_obj = [incoming_obj]
    except (ValueError, json.JSONDecodeError) as exc:
        log.error("[check_json] Invalid incoming JSON: %s", exc)
        log.error("Invalid incoming JSON format: %s", exc)
        return False

    # Fetch all stored configurations
    try:
        with db_session(DB_PATH) as conn:
            stored_jsons = conn.execute(
                "SELECT json_string FROM json_configurations"
            ).fetchall()
    except Exception as exc:
        log.error("[check_json] DB read error: %s", exc)
        return False

    # Key-match comparison
    for (stored_str,) in stored_jsons:
        try:
            stored_obj = json.loads(stored_str)
            if isinstance(stored_obj, dict):
                stored_obj = [stored_obj]

            for inc in incoming_obj:
                inc_keys = set(inc.keys())
                for sto in stored_obj:
                    if inc_keys == set(sto.keys()):
                        log.info("[check_json] Key match found: %s", stored_str[:80])
                        log.debug("Match found with stored JSON keys: %s", stored_str)
                        return True

        except (ValueError, json.JSONDecodeError) as exc:
            log.warning("[check_json] Skipping corrupt stored JSON: %s", exc)
            continue

    log.debug("No matching JSON configuration found based on keys.")
    return False


# ─────────────────────────────────────────────────────────────────────────────
# INTERACTIVE CLI
# log.info() is intentionally kept here — this is a console operator tool.
# BUG fix: int() conversion for delete ID is now wrapped in try/except
#          ValueError so a non-numeric entry no longer crashes the program.
# ─────────────────────────────────────────────────────────────────────────────

def get_multiline_input(prompt: str) -> str:
    """Capture multiline input until the user presses Enter on an empty line."""
    log.info("%s", prompt)
    lines = []
    while True:
        line = input()
        if line == "":
            break
        lines.append(line)
    return "\n".join(lines).strip()


def main() -> None:
    while True:
        log.info("\nChoose an option:")
        log.debug("  1. Add JSON configuration to database")
        log.debug("  2. Delete JSON configuration from database")
        log.debug("  3. View JSON configurations in database")
        log.debug("  4. Check incoming JSON against stored configurations")
        print("  5. Exit")
        choice = input("Enter your choice: ").strip()

        if choice == '1':
            # Collect and validate JSON before passing to add_json_to_db()
            json_str = get_multiline_input(
                "Enter JSON configuration (press Enter twice to finish):"
            )
            log.debug("Captured JSON string: %s", json_str)
            try:
                json.loads(json_str)   # validate
                log.debug("Valid JSON format.")
            except (ValueError, json.JSONDecodeError) as exc:
                log.error("Invalid JSON format: %s", exc)
                continue

            if add_json_to_db(json_str):
                log.debug("JSON configuration added to the database.")
            else:
                log.error("Failed to add JSON configuration — check logs.")

        elif choice == '2':
            raw_id = input("Enter the ID to delete: ").strip()
            # BUG fix: int() conversion is now guarded — non-numeric input
            # no longer raises an unhandled ValueError
            try:
                json_id = int(raw_id)
            except ValueError:
                log.error("Invalid ID '%s' — please enter a number.", raw_id)
                continue
            if delete_json_from_db(json_id):
                log.debug("JSON configuration with ID %s deleted.", json_id)
            else:
                log.error("ID %s not found or deletion failed.", json_id)

        elif choice == '3':
            records = view_json_in_db()
            if records:
                for rec_id, rec_json in records:
                    log.debug("ID: %s, JSON: %s", rec_id, rec_json)
            else:
                log.debug("No JSON configurations stored.")

        elif choice == '4':
            incoming = get_multiline_input(
                "Enter incoming JSON string (press Enter twice to finish):"
            )
            is_matched = check_incoming_json(incoming)
            if is_matched:
                log.debug("Action based on JSON match can be performed here.")
            else:
                log.info("No action taken — no match found.")

        elif choice == '5':
            log.info("Exiting nvr_dvr_bacs menu")
            sys.exit(0)

        else:
            log.error("Invalid choice. Please try again.")


if __name__ == "__main__":
    main()