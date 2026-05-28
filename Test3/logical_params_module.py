# logical_params_module.py
# Dexter HMS — Integration Feature Flags
#
# Controls which NVR/biometric/panel integrations are active.
# All values are binary: 0 (disabled) or 1 (enabled).
#
# Changes from original:
#   DB-01  : bare sqlite3.connect() → get_connection(DB_LOGICAL_PARAMS) + WAL
#   CODE-01: All log.info() → logging, import logging added
#   CODE-02: No thread safety → threading.Lock() added
#   CODE-03: set_parameter() returned None silently on unknown param name —
#            callers had no way to know the update was ignored
#   CODE-04: No param_name whitelist — any string accepted as a parameter name,
#            making typos silently no-ops and enabling unexpected writes
#   CODE-05: get_parameter() printed error on unknown name — now returns None
#            with log.warning so callers can handle it without parsing stdout

"""
logical_params_module.py
Dexter HMS — Active integration flag manager

Responsibilities:
  - Tracks which subsystems (NVR, BACS, panel) are currently active
  - Reads/writes boolean flags in logical_params_active_integration.db
  - Thread-safe field access via whitelist and threading.Lock()

Key functions:
  - initialize_database()       — create flags table if absent
  - get_parameter(field)        — read an integration flag (1/0)
  - set_parameter(field, value) — write an integration flag

Dependencies:
  - db_connection.py — WAL SQLite connections
Author: Seple Novaedge Pvt. Ltd.
"""

import threading
import logging
from typing import Dict, Optional

from db_connection import get_connection, DB_LOGICAL_PARAMS

log   = logging.getLogger(__name__)
_lock = threading.Lock()

# ─────────────────────────────────────────────────────────────────
# CODE-04 FIX: Whitelist of valid parameter names
# Original accepted any string — a typo like "active_hikvision_nvrr"
# would silently succeed (rowcount=0) with no error to the caller.
# Adding a new integration? Add its name here.
# ─────────────────────────────────────────────────────────────────
VALID_PARAMS = {
    "active_integration_hikvision_nvr",
    "active_integration_hikvision_biometric",
    "active_integration_dahua_nvr",
    "active_integration_cp_plus_nvr",
    "active_integration_texecom_bas",
    "active_integration_amc_bas",
    "active_integration_dsc_neo_bas",
    "active_integration_hik_bas",
}


# ─────────────────────────────────────────────────────────────────
# INITIALISE DATABASE
# ─────────────────────────────────────────────────────────────────
def initialize_database() -> None:
    """
    Create parameters table and insert default values if empty.
    Safe to call at every startup — uses IF NOT EXISTS and INSERT OR IGNORE.
    DB-01 FIX: get_connection() applies WAL mode and PRAGMAs.
    """
    with _lock:
        conn = get_connection(DB_LOGICAL_PARAMS)
        try:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS parameters (
                    id    INTEGER PRIMARY KEY AUTOINCREMENT,
                    name  TEXT    UNIQUE NOT NULL,
                    value INTEGER NOT NULL CHECK (value IN (0, 1))
                )
            ''')

            count = conn.execute("SELECT COUNT(*) FROM parameters").fetchone()[0]
            if count == 0:
                conn.executemany(
                    "INSERT INTO parameters (name, value) VALUES (?, ?)",
                    [(name, 0) for name in VALID_PARAMS]
                )
                log.info("logical_params: default rows inserted")

            conn.commit()
            log.info("logical_params: DB ready at %s", DB_LOGICAL_PARAMS)
        except Exception as e:
            conn.rollback()
            log.error("logical_params: initialize_database failed — %s", e)
            raise
        finally:
            conn.close()


# ─────────────────────────────────────────────────────────────────
# SET PARAMETER
# ─────────────────────────────────────────────────────────────────
def set_parameter(param_name: str, param_value: int) -> bool:
    """
    Set an integration flag to 0 (disabled) or 1 (enabled).

    CODE-03 FIX: original returned None silently if param_name didn't exist
    (rowcount == 0). Callers had no way to know the write was ignored.
    Fixed: returns True on success, False on any failure — callers can check.

    CODE-04 FIX: param_name validated against VALID_PARAMS whitelist.
    Typos and unknown names are rejected with log.error before any DB call.

    Returns True on success, False on failure.
    """
    if param_name not in VALID_PARAMS:
        log.error(
            "set_parameter: unknown param '%s' — not in VALID_PARAMS", param_name
        )
        return False

    if param_value not in (0, 1):
        log.error(
            "set_parameter: value must be 0 or 1, got %r for '%s'",
            param_value, param_name
        )
        return False

    with _lock:
        conn = get_connection(DB_LOGICAL_PARAMS)
        try:
            result = conn.execute(
                "UPDATE parameters SET value = ? WHERE name = ?",
                (param_value, param_name)
            )
            conn.commit()

            if result.rowcount == 0:
                # Row missing — insert it (handles DB populated before this module)
                conn.execute(
                    "INSERT INTO parameters (name, value) VALUES (?, ?)",
                    (param_name, param_value)
                )
                conn.commit()
                log.info("logical_params: '%s' inserted as %d", param_name, param_value)
            else:
                log.info("logical_params: '%s' set to %d", param_name, param_value)

            return True
        except Exception as e:
            conn.rollback()
            log.error("logical_params: set_parameter('%s') failed — %s",
                      param_name, e)
            return False
        finally:
            conn.close()


# ─────────────────────────────────────────────────────────────────
# GET PARAMETER
# ─────────────────────────────────────────────────────────────────
def get_parameter(param_name: str) -> Optional[int]:
    """
    Read an integration flag. Returns 0, 1, or None if not found.

    CODE-04 FIX: param_name validated against whitelist.
    CODE-05 FIX: unknown name now returns None with log.warning instead
    of printing to stdout — callers handle None, not parse print output.
    """
    if param_name not in VALID_PARAMS:
        log.error(
            "get_parameter: unknown param '%s' — not in VALID_PARAMS", param_name
        )
        return None

    with _lock:
        conn = get_connection(DB_LOGICAL_PARAMS)
        try:
            row = conn.execute(
                "SELECT value FROM parameters WHERE name = ?",
                (param_name,)
            ).fetchone()

            if row is None:
                log.warning(
                    "logical_params: '%s' not found in DB — "
                    "run initialize_database() first", param_name
                )
                return None

            return row[0]
        except Exception as e:
            log.error("logical_params: get_parameter('%s') failed — %s",
                      param_name, e)
            return None
        finally:
            conn.close()


# ─────────────────────────────────────────────────────────────────
# CONVENIENCE: GET ALL FLAGS AT ONCE
# ─────────────────────────────────────────────────────────────────
def get_all_parameters() -> Dict[str, Optional[int]]:
    """
    Return all integration flags as a dict {name: value}.
    Useful at startup to load the full config in one DB call
    instead of calling get_parameter() once per flag.

    Example:
        flags = get_all_parameters()
        if flags.get("active_integration_hikvision_nvr"):
            start_hikvision_poller()
    """
    with _lock:
        conn = get_connection(DB_LOGICAL_PARAMS)
        try:
            rows = conn.execute(
                "SELECT name, value FROM parameters"
            ).fetchall()
            return {row["name"]: row["value"] for row in rows}
        except Exception as e:
            log.error("logical_params: get_all_parameters failed — %s", e)
            return {}
        finally:
            conn.close()


# ─────────────────────────────────────────────────────────────────
# MAIN — example usage / manual test
# ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s"
    )

    initialize_database()

    # Set flags
    set_parameter("active_integration_hikvision_nvr",      1)
    set_parameter("active_integration_hikvision_biometric", 0)
    set_parameter("active_integration_dahua_nvr",           0)
    set_parameter("active_integration_cp_plus_nvr",         0)
    set_parameter("active_integration_texecom_bas",         0)
    set_parameter("active_integration_amc_bas",         0)
    set_parameter("active_integration_dsc_neo_bas",     0)
    set_parameter("active_integration_hik_bas",          0)

    # Read all back at once
    flags = get_all_parameters()
    for name, value in flags.items():
        log.info("  %s: %s", name, value)