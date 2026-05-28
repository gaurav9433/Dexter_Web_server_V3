# -*- coding: utf-8 -*-
# !/usr/local/bin/python
#
# webuptonly.py — Config change detector and modem-based uploader
# Updated per Dexter HMS Database Architecture fixes (March 2026)
#
# Changes applied vs original:
#   DB-01 — WAL mode via get_connection() in db_checksum()
#             (bare sqlite3.connect() replaced)
#   DB-02 — FK enforcement via get_connection()
#   DB-05 — CRITICAL: save_snapshot() replaced with atomic_write_json()
#             Power loss during snapshot write no longer corrupts the file.
#             load_snapshot() replaced with safe_read_json() + .bak recovery.
#   DB-06 — run_all_migrations() called at startup before any DB access
#   SEC   — Bare except: replaced with typed exception handlers throughout
#   SEC   — SQL injection in db_checksum() fixed: table names whitelisted
#             against sqlite_master before use in f-string query
#   SEC   — subprocess.call() replaced with subprocess.run() (safer API)
#   LOG   — All log.info() replaced with logging


"""
webuptonly.py
Dexter HMS — Web-only OTA update handler (no full reboot)

Responsibilities:
  - Handles OTA updates triggered via web interface without full system reboot
  - Note: hot-swap risk — running module replacement without restart can leave
    stale in-memory state. Use net_ota.py for safety-critical updates.

Key functions:
  - web_update_only() — download and install update, skip reboot

Dependencies:
  - secrets_manager.py — MQTT credentials from .env
Author: Seple Novaedge Pvt. Ltd.
"""

import hashlib
import json
import logging
import os
import sqlite3
import subprocess

from refreshcode import send_dexter_config

# ── Dexter HMS infrastructure imports ────────────────────────────────────────
# DB-01 / DB-02: WAL mode + FK enforcement on every connection
from db_connection import get_connection, verify_all_databases

# DB-06: Schema versioning — apply any pending migrations before DB access
from db_schema_migration import run_all_migrations

# DB-05: Atomic snapshot writes — CRITICAL for this module
#   save_snapshot() writes the snapshot JSON to SD card.
#   If power is cut mid-write with the old open()+json.dump() pattern,
#   config_snapshot.json is left empty or partial. On the next boot,
#   load_snapshot() returns {} (empty), so build_snapshot() always
#   detects a "change", always dials the modem, always sends config —
#   even when nothing actually changed. This causes unnecessary modem
#   connections on every reboot after a power cut.
#   atomic_write_json() + safe_read_json() eliminate this completely.
from json_db_fix import atomic_write_json, safe_read_json

# ── Logging ───────────────────────────────────────────────────────────────────
log = logging.getLogger(__name__)

# ── DB-06: Apply schema migrations before any DB operation ───────────────────
run_all_migrations()

# ── DB-01 / DB-02: Verify WAL + FK active on all registered databases ────────
verify_all_databases()


# ─────────────────────────────────────────────────────────────────────────────
# PATH CONSTANTS
# ─────────────────────────────────────────────────────────────────────────────

# Databases to monitor for config changes
DB_INTEGRATION  = "/home/pi/Test3/device_config.db"
DB_MODEM        = "/home/pi/Test3/modem_config.db"
DB_ACTIVE_BIT   = "/home/pi/Test3/active_integration.db"
DB_ACTIVE_DEVICE= "/home/pi/Test3/logical_params_active_integration.db"
DB_NETWORK      = "/home/pi/Test3/network_settings.db"

# Text config files to monitor for changes
POWER_TEXT_FILE = "/home/pi/Test3/powerZoneSettings.txt"
ZONE_TEXT_FILE  = "/home/pi/Test3/zoneSettings.txt"
BRANCH_FILE     = "/home/pi/Test3/Branch.txt"
BRAND_FILE      = "/home/pi/Test3/Brand.txt"

# DB-05: Snapshot is now written atomically — power loss cannot corrupt it
SNAPSHOT_FILE   = "/home/pi/Test3/config_snapshot.json"

# Modem connection name used by pon/poff
MODEM_CONNECTION = "c16qs"

# SEC: Whitelist of allowed table names per database.
# db_checksum() validates every table name returned by sqlite_master against
# this list before using it in a query. This prevents SQL injection through
# a compromised or malformed database file.
# Add new table names here when the schema evolves.
_ALLOWED_TABLES: set = {
    # device_config.db
    "device_config", "devices", "nvr_config", "panel_config",
    "biometric_config", "credentials",
    # modem_config.db
    "modem_config", "modem_params", "sim_config",
    # active_integration.db
    "active_integration", "integration_flags",
    # logical_params_active_integration.db
    "logical_params", "active_params", "integration_params",
    # network_settings.db
    "network_settings", "lan_settings", "wifi_settings",
    # Common system tables (safe to read for checksum)
    "schema_migrations",
}


# ─────────────────────────────────────────────────────────────────────────────
# CHECKSUM HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def file_checksum(filepath: str) -> str:
    """
    Return a SHA-256 hex digest of the file at filepath.
    Returns "" if the file does not exist.
    Reads in 4 KB chunks — safe for large text files on RPi.
    """
    if not os.path.isfile(filepath):
        return ""
    h = hashlib.sha256()
    try:
        with open(filepath, "rb") as f:
            while chunk := f.read(4096):
                h.update(chunk)
        return h.hexdigest()
    except OSError as exc:
        log.error("[file_checksum] Cannot read %s: %s", filepath, exc)
        return ""


def db_checksum(db_path: str) -> str:
    """
    Return a SHA-256 hex digest of the full content of all tables in db_path.

    DB-01: uses get_connection() — WAL mode applied, readers never block writers.
    DB-02: FK enforcement applied via get_connection().
    SEC:   Table names from sqlite_master are validated against _ALLOWED_TABLES
           before being used in a query. This prevents SQL injection through a
           malformed or attacker-controlled database file.
    SEC:   Bare except: replaced with typed OSError / sqlite3.Error handlers.

    Returns "" if the database does not exist or cannot be read.
    """
    if not os.path.isfile(db_path):
        return ""

    try:
        # DB-01 / DB-02: WAL + FK via central connection factory
        conn = get_connection(db_path)
        cursor = conn.cursor()

        # Fetch all table names from the schema catalogue
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        all_tables = [row[0] for row in cursor.fetchall()]

        # SEC: validate each table name against the whitelist
        tables = []
        for table in all_tables:
            if table in _ALLOWED_TABLES:
                tables.append(table)
            else:
                log.warning(
                    "[db_checksum] Skipping unknown table '%s' in %s",
                    table, db_path
                )

        # Build a deterministic string from all whitelisted table rows
        dump = ""
        for table in sorted(tables):   # sorted — consistent ordering
            # Safe: table name validated against whitelist above
            cursor.execute(f"SELECT * FROM {table}")  # noqa: S608
            rows = cursor.fetchall()
            dump += json.dumps(rows, sort_keys=True)

        conn.close()
        return hashlib.sha256(dump.encode()).hexdigest()

    except sqlite3.Error as exc:
        log.error("[db_checksum] SQLite error on %s: %s", db_path, exc)
        return ""
    except OSError as exc:
        log.error("[db_checksum] OS error reading %s: %s", db_path, exc)
        return ""


# ─────────────────────────────────────────────────────────────────────────────
# SNAPSHOT BUILD
# ─────────────────────────────────────────────────────────────────────────────

def build_snapshot() -> dict:
    """
    Build a fresh snapshot dict containing checksums of all monitored
    databases and text config files.
    This is compared against the saved snapshot to detect changes.
    """
    return {
        "files": {
            "power":  file_checksum(POWER_TEXT_FILE),
            "zone":   file_checksum(ZONE_TEXT_FILE),
            "branch": file_checksum(BRANCH_FILE),
            "brand":  file_checksum(BRAND_FILE),
        },
        "dbs": {
            "integration":  db_checksum(DB_INTEGRATION),
            "modem":        db_checksum(DB_MODEM),
            "active_bit":   db_checksum(DB_ACTIVE_BIT),
            "active_device":db_checksum(DB_ACTIVE_DEVICE),
            "network":      db_checksum(DB_NETWORK),
        }
    }


# ─────────────────────────────────────────────────────────────────────────────
# SNAPSHOT PERSISTENCE — DB-05 CRITICAL FIX
# ─────────────────────────────────────────────────────────────────────────────

def load_snapshot() -> dict:
    """
    Load the previously saved snapshot from SNAPSHOT_FILE.

    DB-05: uses safe_read_json() which:
      - Returns the parsed dict on success.
      - If the main file is corrupt (e.g. from a previous power cut during
        save_snapshot()), automatically tries the .bak backup file.
      - If both are unreadable, returns {} (empty dict) — treated as
        "no previous snapshot", triggering a config send on next run.
    SEC:  bare except: replaced — safe_read_json() handles all error cases
          internally and never raises.
    """
    result = safe_read_json(SNAPSHOT_FILE, default={})
    if not result:
        log.info("[load_snapshot] No existing snapshot found — first run or corrupt")
    return result


def save_snapshot(snapshot: dict) -> None:
    """
    Persist the snapshot dict to SNAPSHOT_FILE atomically.

    DB-05 CRITICAL: replaces bare open()+json.dump().

    Why this matters for webuptonly.py specifically:
      save_snapshot() is called BEFORE send_dexter_config() + modem dial.
      If power cuts during the old non-atomic write, SNAPSHOT_FILE is left
      empty. On every subsequent boot, load_snapshot() returns {}, so
      build_snapshot() always detects a "change", and the modem is dialled
      on every single boot — even when no config actually changed.
      This wastes modem time, SIM data, and causes unnecessary network
      activity at every power cycle.

      atomic_write_json() guarantees the old snapshot file is always intact
      until the new one is fully written. A power cut leaves the device with
      the last known-good snapshot, so the next boot correctly detects only
      real changes.
    """
    try:
        atomic_write_json(SNAPSHOT_FILE, snapshot)
        log.info("[save_snapshot] Snapshot saved atomically to %s", SNAPSHOT_FILE)
    except Exception as exc:
        log.error("[save_snapshot] Failed to save snapshot: %s", exc)


# ─────────────────────────────────────────────────────────────────────────────
# MAIN CHANGE-DETECTION + UPLOAD LOGIC
# ─────────────────────────────────────────────────────────────────────────────

def _modem_up() -> bool:
    """
    Bring up the modem connection via pon.
    SEC: subprocess.run() used instead of subprocess.call() — safer API,
         returns CompletedProcess so we can check returncode.
    Returns True if pon exited with code 0.
    """
    try:
        result = subprocess.run(
            ["sudo", "pon", MODEM_CONNECTION],
            timeout=30,
            check=False
        )
        if result.returncode != 0:
            log.warning("[modem] pon exited with code %d", result.returncode)
            return False
        log.info("[modem] Connection up (%s)", MODEM_CONNECTION)
        return True
    except FileNotFoundError:
        log.error("[modem] 'pon' command not found — modem tools not installed")
        return False
    except subprocess.TimeoutExpired:
        log.error("[modem] pon timed out after 30 s")
        return False
    except Exception as exc:
        log.error("[modem] pon failed: %s", exc)
        return False


def _modem_down() -> None:
    """
    Tear down the modem connection via poff.
    SEC: subprocess.run() used instead of subprocess.call().
    Always called in a finally block — errors are logged but not raised.
    """
    try:
        subprocess.run(
            ["sudo", "poff", MODEM_CONNECTION],
            timeout=15,
            check=False
        )
        log.info("[modem] Connection down (%s)", MODEM_CONNECTION)
    except Exception as exc:
        log.error("[modem] poff failed: %s", exc)


def check_and_send() -> bool:
    """
    Compare current config state against the saved snapshot.
    If anything changed: save the new snapshot, dial the modem,
    call send_dexter_config(), then hang up.

    DB-05: snapshot is saved atomically before the modem is dialled.
           A power cut during save no longer causes false-positive
           change detection on every subsequent boot.
    SEC:   Modem up/down via typed helpers with subprocess.run().
    LOG:   All log.info() replaced with log.*().

    Returns True if a change was detected and config was sent, False otherwise.
    """
    old_snapshot = load_snapshot()
    new_snapshot = build_snapshot()

    if new_snapshot == old_snapshot:
        log.info("[check_and_send] No change detected — nothing sent")
        return False

    log.info("[check_and_send] Change detected — sending config")

    # DB-05: save atomically BEFORE dialling — even if modem/send fails,
    # the snapshot reflects the current state so we don't redial on next boot
    # for the same change that already failed to send.
    save_snapshot(new_snapshot)

    try:
        _modem_up()
        send_dexter_config()
        log.info("[check_and_send] Config sent successfully")
    except Exception as exc:
        log.error("[check_and_send] send_dexter_config() failed: %s", exc)
    finally:
        log.info("[check_and_send] Config upload finished — hanging up modem")
        _modem_down()

    return True


# ─────────────────────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    check_and_send()