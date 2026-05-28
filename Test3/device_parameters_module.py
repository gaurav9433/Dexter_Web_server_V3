#!/usr/bin/env python3
# device_parameters_module.py
# Dexter HMS — Device Configuration & Credential Store
#
# Changes from original:
#   BUG-01 : Python 2 shebang (#!/usr/bin/python2) on a Python 3 codebase
#   BUG-02 : SQL injection in modify_device_field() — .format(field) in query
#   BUG-03 : SQL injection in modify_device_field_by_type() — .format(field)
#            AND the whitelist validation was commented out entirely
#   BUG-04 : No try/finally anywhere — connection leaks on every exception
#   BUG-05 : get_device_parameters_old() — dead code left in production module
#   DB-01  : All bare sqlite3.connect() → get_connection(DB_DEVICE_CONFIG) + WAL
#   SEC-04 : Plaintext passwords stored and returned in clear — Fernet encryption
#            applied to password field via secrets_manager
#   CODE-01: No error handling on any of the 10 functions
#   CODE-02: No logging — import logging missing
#   CODE-03: No thread safety — threading.Lock() added
#   CODE-04: All functions return raw tuples — callers must know column positions.
#            get_device_parameters() and list_devices() now return list of dicts.
#   CODE-05: print() in get_camera_ips_by_type → log.error()

import json
import threading
import logging

from db_connection import get_connection, DB_DEVICE_CONFIG
from secrets_manager import encrypt_value, decrypt_value

log  = logging.getLogger(__name__)
_lock = threading.Lock()

# ─────────────────────────────────────────────────────────────────
# BUG-02 / BUG-03 FIX: Whitelist for dynamic field names
# Original used .format(field) to build UPDATE queries — any string
# passed as `field` becomes raw SQL.
# Example exploit: field = "password='hacked' WHERE 1=1; --"
# The whitelist was present in modify_device_field() but COMMENTED OUT
# in modify_device_field_by_type() — the most-called function.
# ─────────────────────────────────────────────────────────────────
_ALLOWED_FIELDS = {
    "device_type",
    "ip_address",
    "username",
    "password",
    "port",
    "camera_ip",
}


# ─────────────────────────────────────────────────────────────────
# INTERNAL HELPERS
# ─────────────────────────────────────────────────────────────────
def _encrypt_camera_list(camera_ip_list: list) -> str:
    """Serialize camera list to JSON, encrypting each camera's password."""
    encrypted = []
    for cam in camera_ip_list:
        c = dict(cam)
        if c.get("password"):
            c["password"] = encrypt_value(c["password"])
        encrypted.append(c)
    return json.dumps(encrypted)


def _row_to_dict(row) -> dict:
    """
    Convert a sqlite3.Row to a plain dict and decrypt the password field.
    SEC-04: password is stored encrypted — decrypt before returning to caller.
    Returns None if row is None.
    """
    if row is None:
        return None

    d = dict(row)

    # Decrypt password — if decryption fails (e.g. legacy plaintext row),
    # return the raw value and log a warning so the issue is visible
    if d.get("password"):
        try:
            d["password"] = decrypt_value(d["password"])
        except ValueError:
            log.warning(
                "device_parameters: password for device_type='%s' id=%s "
                "is not encrypted — run migrate_plaintext_passwords(). "
                "Returning raw value.",
                d.get("device_type"), d.get("id")
            )

    # Parse camera_ip JSON string back to list, decrypting each camera password
    if d.get("camera_ip"):
        try:
            cams = json.loads(d["camera_ip"])
            if isinstance(cams, list):
                for cam in cams:
                    if cam.get("password"):
                        try:
                            cam["password"] = decrypt_value(cam["password"])
                        except (ValueError, Exception):
                            pass  # already plaintext (legacy row)
            d["camera_ip"] = cams
        except (ValueError, TypeError):
            d["camera_ip"] = []

    return d


# ─────────────────────────────────────────────────────────────────
# TABLE CREATION
# ─────────────────────────────────────────────────────────────────
def create_table() -> None:
    """
    Create device_parameters table if it doesn't exist.
    Safe to call on every startup.
    """
    with _lock:
        conn = get_connection(DB_DEVICE_CONFIG)
        try:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS device_parameters (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    device_type TEXT    NOT NULL,
                    ip_address  TEXT    NOT NULL,
                    username    TEXT    NOT NULL,
                    password    TEXT    NOT NULL,
                    port        INTEGER NOT NULL,
                    camera_ip   TEXT
                )
            ''')
            conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_device_params_type
                ON device_parameters (device_type)
            ''')
            conn.commit()
            log.info("device_parameters: table ready at %s", DB_DEVICE_CONFIG)
        except Exception as e:
            conn.rollback()
            log.error("device_parameters: create_table failed — %s", e)
            raise
        finally:
            conn.close()


# ─────────────────────────────────────────────────────────────────
# ENSURE DEFAULT DEVICES
# ─────────────────────────────────────────────────────────────────
# DEFAULT_DEVICES: list of (device_type, ip_address, username, password, port)
# Used to seed device_config.db on a fresh panel where no devices exist yet.
# IP / password / port are placeholder defaults — operator updates via LCD menu.
# Adding a new integration device? Add its row here.
# SEC-04: passwords are encrypted by add_device() before storage.
_DEFAULT_DEVICES = [
    ("HikvisionNVR1",       "192.168.1.23",  "hikvision", "hik@1234",   8080),
    ("DahuaNVR1",           "192.168.0.102", "admin",     "Sepl@1984",  8080),
    ("HikvisionBioMetric1", "192.168.0.27",  "sepl",      "sepl1984",   8082),
    ("CP_PlusNVR1",         "192.168.0.102", "admin",     "Sepl@1984",  8080),
    ("TexecomBAS1",         "192.168.0.242", "TAXICOM",   "12345",     10001),
    ("HikvisionBAS1",       "192.168.0.213", "admin",     "Fusion@2026",     80),
]


def ensure_default_devices() -> None:
    """
    Insert default device rows if the table is completely empty.

    Called once at startup alongside create_table(). Safe to call multiple
    times — only inserts when table has zero rows, so manual changes made
    via the LCD menu are never overwritten.

    To add Texecom (or any new device) to an existing deployment where the
    table already has rows, use add_device() once, or insert via the LCD menu.
    """
    with _lock:
        conn = get_connection(DB_DEVICE_CONFIG)
        try:
            count = conn.execute(
                "SELECT COUNT(*) FROM device_parameters"
            ).fetchone()[0]

            if count == 0:
                log.info("device_parameters: empty table — seeding default devices")
                for device_type, ip, username, password, port in _DEFAULT_DEVICES:
                    encrypted_password = encrypt_value(password)
                    conn.execute(
                        "INSERT INTO device_parameters "
                        "(device_type, ip_address, username, password, port, camera_ip) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (device_type, ip, username, encrypted_password, port, None)
                    )
                    log.info(
                        "device_parameters: inserted default device_type='%s' ip=%s",
                        device_type, ip
                    )
                conn.commit()
                log.info("device_parameters: %d default devices inserted",
                         len(_DEFAULT_DEVICES))
            else:
                # Table already has rows.
                # Only insert TexecomBAS1 if it is missing (upgrade path for
                # existing panels deployed before Texecom was added).
                existing_types = {
                    row[0] for row in
                    conn.execute(
                        "SELECT device_type FROM device_parameters"
                    ).fetchall()
                }
                for device_type, ip, username, password, port in _DEFAULT_DEVICES:
                    if device_type not in existing_types:
                        encrypted_password = encrypt_value(password)
                        conn.execute(
                            "INSERT INTO device_parameters "
                            "(device_type, ip_address, username, password, port, camera_ip) "
                            "VALUES (?, ?, ?, ?, ?, ?)",
                            (device_type, ip, username, encrypted_password, port, None)
                        )
                        log.info(
                            "device_parameters: inserted missing device_type='%s'",
                            device_type
                        )
                conn.commit()

        except Exception as e:
            conn.rollback()
            log.error("device_parameters: ensure_default_devices failed — %s", e)
        finally:
            conn.close()


# ─────────────────────────────────────────────────────────────────
# ADD DEVICE
# ─────────────────────────────────────────────────────────────────
def add_device(device_type: str,
               ip_address:  str,
               username:    str,
               password:    str,
               port:        int,
               camera_ip_list: list = None) -> bool:
    """
    Add a new device to the database.
    SEC-04: password is Fernet-encrypted before storage.
    Returns True on success, False on failure.
    """
    camera_ip_json    = _encrypt_camera_list(camera_ip_list) if camera_ip_list else None
    encrypted_password = encrypt_value(password)

    with _lock:
        conn = get_connection(DB_DEVICE_CONFIG)
        try:
            conn.execute('''
                INSERT INTO device_parameters
                    (device_type, ip_address, username, password, port, camera_ip)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (device_type, ip_address, username,
                  encrypted_password, port, camera_ip_json))
            conn.commit()
            log.info("device_parameters: added device_type='%s' ip=%s",
                     device_type, ip_address)
            return True
        except Exception as e:
            conn.rollback()
            log.error("device_parameters: add_device failed — %s", e)
            return False
        finally:
            conn.close()


# ─────────────────────────────────────────────────────────────────
# GET DEVICE PARAMETERS (primary query used by NVR modules)
# ─────────────────────────────────────────────────────────────────
def get_device_parameters(device_type: str) -> list[dict]:
    """
    Retrieve all devices of a specific type as a list of dicts.

    CODE-04 FIX: original returned raw tuples — every caller had to
    remember column positions (device[3] = password, device[5] = port).
    Now returns list of dicts: device['password'], device['port'], etc.

    SEC-04: passwords are decrypted before returning.

    Example return:
        [{'id': 1, 'device_type': 'HikvisionNVR1', 'ip_address': '192.168.1.23',
          'username': 'hikvision', 'password': 'hik@1234', 'port': 8080,
          'camera_ip': [{'ip_address': '192.168.1.69', ...}]}]
    """
    with _lock:
        conn = get_connection(DB_DEVICE_CONFIG)
        try:
            rows = conn.execute(
                "SELECT * FROM device_parameters WHERE device_type=?",
                (device_type,)
            ).fetchall()
            return [_row_to_dict(r) for r in rows]
        except Exception as e:
            log.error(
                "device_parameters: get_device_parameters('%s') failed — %s",
                device_type, e
            )
            return []
        finally:
            conn.close()


# ─────────────────────────────────────────────────────────────────
# LIST ALL DEVICES
# ─────────────────────────────────────────────────────────────────
def list_devices() -> list[dict]:
    """
    Return all devices as a list of dicts (passwords decrypted).
    CODE-04 FIX: was returning raw tuples.
    """
    with _lock:
        conn = get_connection(DB_DEVICE_CONFIG)
        try:
            rows = conn.execute(
                "SELECT * FROM device_parameters"
            ).fetchall()
            return [_row_to_dict(r) for r in rows]
        except Exception as e:
            log.error("device_parameters: list_devices failed — %s", e)
            return []
        finally:
            conn.close()


# ─────────────────────────────────────────────────────────────────
# GET / UPDATE CAMERA IPs
# ─────────────────────────────────────────────────────────────────
def get_camera_ips_by_type(device_type: str) -> list:
    """
    Retrieve the stored camera IP list for a given device type.
    Returns a list of dicts (parsed from JSON), or [] if not found.
    """
    with _lock:
        conn = get_connection(DB_DEVICE_CONFIG)
        try:
            row = conn.execute(
                "SELECT camera_ip FROM device_parameters WHERE device_type=?",
                (device_type,)
            ).fetchone()

            if row and row["camera_ip"]:
                try:
                    cams = json.loads(row["camera_ip"])
                    if isinstance(cams, list):
                        for cam in cams:
                            if cam.get("password"):
                                try:
                                    cam["password"] = decrypt_value(cam["password"])
                                except (ValueError, Exception):
                                    pass  # already plaintext (legacy row)
                    return cams
                except (ValueError, TypeError) as e:
                    # CODE-05 FIX: was print() — now log.error()
                    log.error(
                        "device_parameters: failed to parse camera_ip JSON "
                        "for '%s' — %s", device_type, e
                    )
            return []
        except Exception as e:
            log.error(
                "device_parameters: get_camera_ips_by_type('%s') failed — %s",
                device_type, e
            )
            return []
        finally:
            conn.close()


def update_camera_ips_by_type(device_type: str,
                               camera_ip_list: list) -> bool:
    """
    Update the camera_ip field for all entries of the given device type.
    Returns True on success, False on failure.
    """
    camera_ip_json = _encrypt_camera_list(camera_ip_list)
    with _lock:
        conn = get_connection(DB_DEVICE_CONFIG)
        try:
            conn.execute(
                "UPDATE device_parameters SET camera_ip=? WHERE device_type=?",
                (camera_ip_json, device_type)
            )
            conn.commit()
            log.info("device_parameters: camera_ips updated for '%s'", device_type)
            return True
        except Exception as e:
            conn.rollback()
            log.error(
                "device_parameters: update_camera_ips_by_type('%s') failed — %s",
                device_type, e
            )
            return False
        finally:
            conn.close()


# ─────────────────────────────────────────────────────────────────
# DELETE DEVICE
# ─────────────────────────────────────────────────────────────────
def delete_device(device_id: int) -> bool:
    """
    Delete a device by ID.
    Returns True if a row was deleted, False otherwise.
    """
    with _lock:
        conn = get_connection(DB_DEVICE_CONFIG)
        try:
            result = conn.execute(
                "DELETE FROM device_parameters WHERE id=?", (device_id,)
            )
            conn.commit()
            if result.rowcount:
                log.info("device_parameters: deleted id=%d", device_id)
                return True
            log.warning("device_parameters: delete — id=%d not found", device_id)
            return False
        except Exception as e:
            conn.rollback()
            log.error("device_parameters: delete_device(%d) failed — %s",
                      device_id, e)
            return False
        finally:
            conn.close()


# ─────────────────────────────────────────────────────────────────
# MODIFY FULL DEVICE RECORD
# ─────────────────────────────────────────────────────────────────
def modify_device(device_id:      int,
                  device_type:    str,
                  ip_address:     str,
                  username:       str,
                  password:       str,
                  port:           int,
                  camera_ip_list: list = None) -> bool:
    """
    Update all fields of an existing device record.
    SEC-04: password is re-encrypted before storage.
    Returns True on success, False on failure.
    """
    camera_ip_json     = _encrypt_camera_list(camera_ip_list) if camera_ip_list else None
    encrypted_password = encrypt_value(password)

    with _lock:
        conn = get_connection(DB_DEVICE_CONFIG)
        try:
            conn.execute('''
                UPDATE device_parameters
                SET device_type=?, ip_address=?, username=?,
                    password=?, port=?, camera_ip=?
                WHERE id=?
            ''', (device_type, ip_address, username,
                  encrypted_password, port, camera_ip_json, device_id))
            conn.commit()
            log.info("device_parameters: modified id=%d", device_id)
            return True
        except Exception as e:
            conn.rollback()
            log.error("device_parameters: modify_device(%d) failed — %s",
                      device_id, e)
            return False
        finally:
            conn.close()


# ─────────────────────────────────────────────────────────────────
# MODIFY SINGLE FIELD BY ID
# ─────────────────────────────────────────────────────────────────
def modify_device_field(device_id: int, field: str, new_value: str) -> bool:
    """
    Update a single field of a device record by ID.

    BUG-02 FIX: original used .format(field) — SQL injection.
    Fix: whitelist validation before query construction.
    SEC-04: if field is 'password', value is encrypted before storage.
    Returns True on success, False on failure.
    """
    if field not in _ALLOWED_FIELDS:
        log.error(
            "device_parameters: modify_device_field — "
            "field '%s' not in allowed list %s", field, _ALLOWED_FIELDS
        )
        return False

    if field == "camera_ip" and isinstance(new_value, list):
        new_value = json.dumps(new_value)
    elif field == "password":
        new_value = encrypt_value(new_value)  # SEC-04

    with _lock:
        conn = get_connection(DB_DEVICE_CONFIG)
        try:
            conn.execute(
                f"UPDATE device_parameters SET {field} = ? WHERE id = ?",
                (new_value, device_id)
            )
            conn.commit()
            log.info("device_parameters: field '%s' updated for id=%d",
                     field, device_id)
            return True
        except Exception as e:
            conn.rollback()
            log.error(
                "device_parameters: modify_device_field('%s', id=%d) "
                "failed — %s", field, device_id, e
            )
            return False
        finally:
            conn.close()


# ─────────────────────────────────────────────────────────────────
# MODIFY SINGLE FIELD BY DEVICE TYPE
# ─────────────────────────────────────────────────────────────────
def modify_device_field_by_type(device_type: str,
                                field:       str,
                                new_value:   str) -> bool:
    """
    Update a single field for all devices of a given type.

    BUG-03 FIX: original had .format(field) in the query AND the
    whitelist validation was COMMENTED OUT — double vulnerability.
    Both fixes applied: whitelist enforced, no .format() bypass possible.
    SEC-04: if field is 'password', value is encrypted before storage.
    Returns True on success, False on failure.
    """
    # BUG-03 FIX: whitelist was present but commented out in original
    if field not in _ALLOWED_FIELDS:
        log.error(
            "device_parameters: modify_device_field_by_type — "
            "field '%s' not in allowed list %s", field, _ALLOWED_FIELDS
        )
        return False

    if field == "camera_ip" and isinstance(new_value, list):
        new_value = json.dumps(new_value)
    elif field == "password":
        new_value = encrypt_value(new_value)  # SEC-04

    with _lock:
        conn = get_connection(DB_DEVICE_CONFIG)
        try:
            conn.execute(
                f"UPDATE device_parameters SET {field} = ? WHERE device_type = ?",
                (new_value, device_type)
            )
            conn.commit()
            log.info(
                "device_parameters: field '%s' updated for device_type='%s'",
                field, device_type
            )
            return True
        except Exception as e:
            conn.rollback()
            log.error(
                "device_parameters: modify_device_field_by_type('%s','%s') "
                "failed — %s", device_type, field, e
            )
            return False
        finally:
            conn.close()


# ─────────────────────────────────────────────────────────────────
# ONE-TIME MIGRATION — encrypt existing plaintext passwords
# ─────────────────────────────────────────────────────────────────
def migrate_plaintext_passwords() -> None:
    """
    One-time migration: reads all rows, checks if password is plaintext,
    and re-writes it as Fernet-encrypted.

    Run ONCE after deploying this file to an existing system:
        python3 -c "from device_parameters_module import migrate_plaintext_passwords; migrate_plaintext_passwords()"

    Safe to run multiple times — already-encrypted rows are skipped.
    """
    from secrets_manager import decrypt_value as _dv
    from cryptography.fernet import InvalidToken

    with _lock:
        conn = get_connection(DB_DEVICE_CONFIG)
        try:
            rows = conn.execute(
                "SELECT id, password FROM device_parameters"
            ).fetchall()

            encrypted = 0
            skipped   = 0

            for row in rows:
                try:
                    _dv(row["password"])   # already encrypted — skip
                    skipped += 1
                except (ValueError, InvalidToken):
                    # plaintext — encrypt it now
                    conn.execute(
                        "UPDATE device_parameters SET password=? WHERE id=?",
                        (encrypt_value(row["password"]), row["id"])
                    )
                    encrypted += 1

            conn.commit()
            log.info(
                "migrate_plaintext_passwords: %d encrypted, %d already done",
                encrypted, skipped
            )
        except Exception as e:
            conn.rollback()
            log.error("migrate_plaintext_passwords failed — %s", e)
            raise
        finally:
            conn.close()


# ─────────────────────────────────────────────────────────────────
# ONE-TIME MIGRATION — encrypt plaintext camera passwords in JSON
# ─────────────────────────────────────────────────────────────────
def migrate_plaintext_camera_passwords() -> None:
    """
    One-time migration: reads all camera_ip JSON blobs, checks if each
    camera's password is plaintext, and re-writes it as Fernet-encrypted.

    Run ONCE on an existing system after deploying this file:
        python3 -c "from device_parameters_module import migrate_plaintext_camera_passwords; migrate_plaintext_camera_passwords()"

    Safe to run multiple times — already-encrypted camera passwords are skipped.
    """
    from secrets_manager import decrypt_value as _dv
    from cryptography.fernet import InvalidToken

    with _lock:
        conn = get_connection(DB_DEVICE_CONFIG)
        try:
            rows = conn.execute(
                "SELECT id, camera_ip FROM device_parameters WHERE camera_ip IS NOT NULL"
            ).fetchall()

            rows_updated = 0

            for row in rows:
                try:
                    cams = json.loads(row["camera_ip"])
                except (ValueError, TypeError):
                    continue
                if not isinstance(cams, list):
                    continue

                changed = False
                for cam in cams:
                    pwd = cam.get("password", "")
                    if not pwd:
                        continue
                    try:
                        _dv(pwd)  # already encrypted — skip
                    except (ValueError, InvalidToken):
                        cam["password"] = encrypt_value(pwd)
                        changed = True

                if changed:
                    conn.execute(
                        "UPDATE device_parameters SET camera_ip=? WHERE id=?",
                        (json.dumps(cams), row["id"])
                    )
                    rows_updated += 1

            conn.commit()
            log.info("migrate_plaintext_camera_passwords: %d rows updated", rows_updated)
        except Exception as e:
            conn.rollback()
            log.error("migrate_plaintext_camera_passwords failed — %s", e)
            raise
        finally:
            conn.close()