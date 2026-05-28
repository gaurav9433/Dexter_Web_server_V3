# json_db_module.py
# Dexter HMS — Hardened JSON Configuration DB Module
# Fixes: DB-01 (WAL), DB-02 (FK), DB-04 (Index),
#        Error Handling, Thread Safety, log.error() → logging,
#        Missing CRUD functions, Connection leak

"""
json_db_module.py
Dexter HMS — JSON configuration store (SQLite-backed)

Responsibilities:
  - Stores and retrieves named JSON configuration blobs in nvr_dvr_bacs_integration.db
  - Fully refactored from file-based JSON to SQLite — atomic writes by design
  - Thread-safe via threading.Lock() on all operations

Key functions:
  - init_db()            — create table and index, safe to call on every boot
  - save_json(name, data) — upsert a JSON config by name
  - get_json(name)        — retrieve a config; returns None if not found

Dependencies:
  - db_connection.py — WAL SQLite connections
Author: Seple Novaedge Pvt. Ltd.
"""

import json
import sqlite3
import threading
import logging
from typing import Dict, Optional, Union

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────
DB_PATH = "/home/pi/Test3/nvr_dvr_bacs_integration.db"

# ─────────────────────────────────────────────
# MODULE-LEVEL LOCK — thread safety
# ─────────────────────────────────────────────
_lock = threading.Lock()


# ─────────────────────────────────────────────
# INTERNAL — WAL + PRAGMAs on every connection
# ─────────────────────────────────────────────
def _get_connection(db_path: str = DB_PATH) -> sqlite3.Connection:
    """
    Single factory for all DB connections.
    Applies WAL mode and safety PRAGMAs on every open.
    Replaces bare sqlite3.connect().
    """
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")    # DB-01: readers never block writers
    conn.execute("PRAGMA foreign_keys=ON;")     # DB-02: FK enforcement
    conn.execute("PRAGMA synchronous=NORMAL;")  # Safe + faster with WAL
    conn.execute("PRAGMA cache_size=-8000;")    # 8 MB page cache
    conn.execute("PRAGMA busy_timeout=5000;")   # Wait 5s on lock before error
    return conn


# ─────────────────────────────────────────────
# INIT — create table + index
# ─────────────────────────────────────────────
def init_db(db_path: str = DB_PATH) -> None:
    """
    Creates json_configurations table and index.
    Safe to call on every startup — uses IF NOT EXISTS.
    """
    with _lock:
        conn = _get_connection(db_path)
        try:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS json_configurations (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    config_name TEXT    NOT NULL UNIQUE,
                    json_string TEXT    NOT NULL,
                    created_at  INTEGER NOT NULL DEFAULT (strftime('%s','now')),
                    updated_at  INTEGER NOT NULL DEFAULT (strftime('%s','now'))
                )
            ''')
            # DB-04: Index on config_name — fast lookup by name
            conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_json_config_name
                ON json_configurations (config_name)
            ''')
            conn.commit()
            log.info("json_db_module: DB initialised at %s", db_path)
        except Exception as e:
            conn.rollback()
            log.error("json_db_module: init_db failed — %s", e)
            raise
        finally:
            conn.close()


# ─────────────────────────────────────────────
# CRUD — INSERT
# ─────────────────────────────────────────────
def insert_json_config(config_name: str,
                       json_data: Union[dict, str],
                       db_path: str = DB_PATH) -> bool:
    """
    Insert a new JSON configuration by name.
    Accepts a dict or a JSON string.
    Returns True on success, False on failure.
    """
    # Normalise — accept dict or string
    if isinstance(json_data, dict):
        json_string = json.dumps(json_data)
    else:
        if not json_data or not json_data.strip():
            log.error("json_db_module: insert — empty json_data for '%s'", config_name)
            return False
        try:
            json.loads(json_data)  # validate it parses
            json_string = json_data
        except (ValueError, TypeError) as e:
            log.error("json_db_module: insert — invalid JSON for '%s' — %s",
                      config_name, e)
            return False

    with _lock:
        conn = _get_connection(db_path)
        try:
            conn.execute(
                "INSERT INTO json_configurations (config_name, json_string) VALUES (?, ?)",
                (config_name, json_string)
            )
            conn.commit()
            log.info("json_db_module: inserted config '%s'", config_name)
            return True
        except sqlite3.IntegrityError:
            log.warning("json_db_module: config '%s' already exists. Use update.", config_name)
            return False
        except Exception as e:
            conn.rollback()
            log.error("json_db_module: insert failed for '%s' — %s", config_name, e)
            return False
        finally:
            conn.close()


# ─────────────────────────────────────────────
# CRUD — UPDATE (upsert)
# ─────────────────────────────────────────────
def upsert_json_config(config_name: str,
                       json_data: Union[dict, str],
                       db_path: str = DB_PATH) -> bool:
    """
    Insert or update a JSON configuration by name.
    If the config_name exists, its json_string is updated.
    Returns True on success, False on failure.
    """
    if isinstance(json_data, dict):
        json_string = json.dumps(json_data)
    else:
        if not json_data or not json_data.strip():
            log.error("json_db_module: upsert — empty json_data for '%s'", config_name)
            return False
        try:
            json.loads(json_data)
            json_string = json_data
        except (ValueError, TypeError) as e:
            log.error("json_db_module: upsert — invalid JSON for '%s' — %s",
                      config_name, e)
            return False

    with _lock:
        conn = _get_connection(db_path)
        try:
            conn.execute('''
                INSERT INTO json_configurations (config_name, json_string)
                VALUES (?, ?)
                ON CONFLICT(config_name) DO UPDATE SET
                    json_string = excluded.json_string,
                    updated_at  = strftime('%s','now')
            ''', (config_name, json_string))
            conn.commit()
            log.info("json_db_module: upserted config '%s'", config_name)
            return True
        except Exception as e:
            conn.rollback()
            log.error("json_db_module: upsert failed for '%s' — %s", config_name, e)
            return False
        finally:
            conn.close()


# ─────────────────────────────────────────────
# CRUD — GET by name
# ─────────────────────────────────────────────
def get_json_config(config_name: str,
                    db_path: str = DB_PATH) -> Optional[dict]:
    """
    Retrieve a stored JSON configuration by name.
    Returns a Python dict, or None if not found.
    """
    with _lock:
        conn = _get_connection(db_path)
        try:
            row = conn.execute(
                "SELECT json_string FROM json_configurations WHERE config_name = ?",
                (config_name,)
            ).fetchone()

            if row:
                return json.loads(row["json_string"])
            log.warning("json_db_module: config '%s' not found", config_name)
            return None
        except Exception as e:
            log.error("json_db_module: get failed for '%s' — %s", config_name, e)
            return None
        finally:
            conn.close()


# ─────────────────────────────────────────────
# CRUD — GET all
# ─────────────────────────────────────────────
def get_all_configs(db_path: str = DB_PATH) -> Dict[str, object]:
    """
    Retrieve all stored configurations.
    Returns dict of {config_name: parsed_dict}.
    """
    with _lock:
        conn = _get_connection(db_path)
        try:
            rows = conn.execute(
                "SELECT config_name, json_string FROM json_configurations"
            ).fetchall()
            result = {}
            for row in rows:
                try:
                    result[row["config_name"]] = json.loads(row["json_string"])
                except ValueError as e:
                    log.error("json_db_module: corrupt JSON for '%s' — %s",
                              row["config_name"], e)
            return result
        except Exception as e:
            log.error("json_db_module: get_all_configs failed — %s", e)
            return {}
        finally:
            conn.close()


# ─────────────────────────────────────────────
# CRUD — DELETE
# ─────────────────────────────────────────────
def delete_json_config(config_name: str,
                       db_path: str = DB_PATH) -> bool:
    """
    Delete a JSON configuration by name.
    Returns True if a row was deleted, False otherwise.
    """
    with _lock:
        conn = _get_connection(db_path)
        try:
            result = conn.execute(
                "DELETE FROM json_configurations WHERE config_name = ?",
                (config_name,)
            )
            conn.commit()
            if result.rowcount:
                log.info("json_db_module: deleted config '%s'", config_name)
                return True
            log.warning("json_db_module: delete — '%s' not found", config_name)
            return False
        except Exception as e:
            conn.rollback()
            log.error("json_db_module: delete failed for '%s' — %s", config_name, e)
            return False
        finally:
            conn.close()


# ─────────────────────────────────────────────
# ORIGINAL FUNCTION — hardened
# ─────────────────────────────────────────────
def check_incoming_json(incoming_json: str,
                        db_path: str = DB_PATH) -> bool:
    """
    Check if the incoming JSON (object or array of objects)
    has the same keys as any stored JSON configuration.

    Returns True if a key-set match is found, False otherwise.

    Changes from original:
    - log.error() replaced with log.error / log.warning / log.debug
    - Connection always closed in finally (was closed inline — leaked on exception)
    - Parameterised DB path (was hardcoded filename)
    - WAL + PRAGMAs applied via _get_connection()
    - Thread-safe via _lock
    """
    # ── Parse incoming JSON ───────────────────
    try:
        incoming_json_obj = json.loads(incoming_json)
        if isinstance(incoming_json_obj, dict):
            incoming_json_obj = [incoming_json_obj]
        elif not isinstance(incoming_json_obj, list):
            log.warning("json_db_module: check — incoming JSON is not a dict or list")
            return False
    except (ValueError, TypeError) as e:
        log.error("json_db_module: check — invalid incoming JSON — %s", e)
        return False

    incoming_keys_list = [set(obj.keys()) for obj in incoming_json_obj if isinstance(obj, dict)]
    if not incoming_keys_list:
        log.warning("json_db_module: check — no dict objects found in incoming JSON")
        return False

    # ── Fetch all stored configs and compare ─
    with _lock:
        conn = _get_connection(db_path)
        try:
            rows = conn.execute(
                "SELECT json_string FROM json_configurations"
            ).fetchall()
        except Exception as e:
            log.error("json_db_module: check — DB fetch failed — %s", e)
            return False
        finally:
            conn.close()

    for row in rows:
        stored_json = row["json_string"]
        if not stored_json or not stored_json.strip():
            log.debug("json_db_module: check — skipping blank json_string row")
            continue
        try:
            stored_obj = json.loads(stored_json)
            if isinstance(stored_obj, dict):
                stored_obj = [stored_obj]
            elif not isinstance(stored_obj, list):
                continue

            stored_keys_list = [set(obj.keys()) for obj in stored_obj if isinstance(obj, dict)]

            for inc_keys in incoming_keys_list:
                for sto_keys in stored_keys_list:
                    if inc_keys == sto_keys:
                        log.debug("json_db_module: key match found — %s", stored_json)
                        return True

        except (ValueError, TypeError) as e:
            log.warning("json_db_module: check — skipping corrupt stored JSON — %s", e)
            # Continue checking remaining rows, don't abort

    log.debug("json_db_module: check — no matching config found for incoming keys")
    return False