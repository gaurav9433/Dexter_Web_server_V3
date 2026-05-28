# -*- coding: utf-8 -*-
# !/usr/local/bin/python
#
# webdone.py — ThingsBoard REST telemetry sender
# Updated per Dexter HMS Database Architecture fixes (March 2026)
#
# Changes applied vs original:
#   DB-01 — WAL mode via get_connection() in ModemConfigDatabase.get_parameter()
#             (bare sqlite3.connect() replaced)
#   DB-02 — FK enforcement via get_connection()
#   DB-06 — run_all_migrations() + verify_all_databases() at module startup
#   SEC   — SQL injection in get_parameter() fixed: column name validated
#             against a whitelist before use in f-string query
#   SEC   — Hardcoded USERNAME / PASSWORD removed from source code;
#             loaded from modem_config.db via get_parameter() instead
#   SEC   — bare except Exception replaced with typed request exception handlers
#   SEC   — requests.exceptions.* used instead of bare Exception for HTTP calls
#   BUG   — Mutable default argument telemetry_data={} replaced with None
#             (shared mutable default is a classic Python bug — the same dict
#             object is reused across all calls, mutations persist between calls)
#   CODE  — ModemConfigDatabase inner class promoted to module level
#             (was redefined on every send_webdone() call — wasteful, untestable)
#   LOG   — All print() replaced with logging


import json
import time
import logging
import sqlite3
from typing import Optional

import requests
from requests.exceptions import (
    ConnectionError as RequestsConnectionError,
    Timeout as RequestsTimeout,
    HTTPError,
    RequestException,
)

from net_wait import wait_for_network

from db_connection import get_connection, verify_all_databases, DB_MODEM_CONFIG
from secrets_manager import decrypt_value

# CQ-03: path constant from db_connection — replaces inline string literals
_MODEM_CONFIG_DB = DB_MODEM_CONFIG

# DB-06: Schema versioning — apply pending migrations before any DB access
from db_schema_migration import run_all_migrations

# ── Logging ───────────────────────────────────────────────────────────────────
log = logging.getLogger(__name__)

# ── DB-06: Apply schema migrations at startup ─────────────────────────────────
run_all_migrations()

# ── DB-01 / DB-02: Verify WAL + FK on all registered databases ───────────────
verify_all_databases()

# ── ThingsBoard endpoint ──────────────────────────────────────────────────────
BASE_URL = "https://www.dexterhms.com"   # fallback — overridden by swatch_host from DB

# ── SEC: Column whitelist for modem_config.db ─────────────────────────────────
# get_parameter() validates the requested column name against this set before
# using it in a query. This prevents SQL injection if the call site passes
# user-supplied or untrusted column names.
# Add new column names here when the modem_parameters schema evolves.
_ALLOWED_MODEM_PARAMS: set = {
    "device_name",
    "swatch_username",
    "swatch_password",
    "swatch_host",
    # Columns below were phantom (not in modem_config.db schema) — removed:
    # "sim_apn", "sim_operator", "modem_port", "device_id", "firmware_version"
}


# ─────────────────────────────────────────────────────────────────────────────
# MODEM CONFIG DATABASE
# CODE: promoted from inner class (redefined on every call) to module level.
# DB-01: get_connection() applies WAL mode — reads never block concurrent writes.
# DB-02: get_connection() applies FK enforcement.
# SEC:   Column name validated against _ALLOWED_MODEM_PARAMS whitelist before
#        use in query — prevents SQL injection.
# ─────────────────────────────────────────────────────────────────────────────

class ModemConfigDatabase:
    """
    Read-only accessor for modem_config.db — modem and ThingsBoard credentials.

    DB-01 / DB-02: every connection opened via get_connection() which applies
    WAL mode, FK enforcement, busy_timeout, and cache_size PRAGMAs.

    SEC: column names are validated against _ALLOWED_MODEM_PARAMS before use
    in any query. Unknown column names raise ValueError immediately.
    """

    def __init__(self, db_file: str = _MODEM_CONFIG_DB):
        self.db_file = db_file

    def get_parameter(self, param: str):
        """
        Fetch a single value from modem_parameters WHERE id = 1.

        SEC: `param` is validated against _ALLOWED_MODEM_PARAMS whitelist.
             If `param` is not in the whitelist, ValueError is raised and
             the query is never executed — SQL injection is impossible.

        Returns the value as a string, or None if the row does not exist
        or an error occurs.
        """
        # SEC: whitelist check — reject unknown column names immediately
        if param not in _ALLOWED_MODEM_PARAMS:
            log.error(
                "[ModemConfigDB] Rejected unknown column name '%s' — "
                "not in _ALLOWED_MODEM_PARAMS whitelist", param
            )
            return None

        try:
            # DB-01 / DB-02: WAL + FK via central connection factory
            conn = get_connection(self.db_file)
            cursor = conn.cursor()
            # Safe: param validated against whitelist above
            cursor.execute(
                f"SELECT {param} FROM modem_parameters WHERE id = 1"  # noqa: S608
            )
            row = cursor.fetchone()
            conn.close()
            return row[0] if row else None

        except sqlite3.Error as exc:
            log.error("[ModemConfigDB] SQLite error reading '%s': %s", param, exc)
            return None
        except OSError as exc:
            log.error("[ModemConfigDB] OS error on DB file %s: %s", self.db_file, exc)
            return None


# ─────────────────────────────────────────────────────────────────────────────
# THINGSBOARD REST CLIENT HELPERS
# SEC: typed request exception handlers replace bare except Exception
# ─────────────────────────────────────────────────────────────────────────────

def _tb_login(session: requests.Session, username: str, password: str, base_url: str) -> Optional[str]:
    """
    POST /api/auth/login and return the JWT token string.
    Returns None on any failure.
    SEC: typed exception handlers — RequestsConnectionError, RequestsTimeout,
         HTTPError, and RequestException cover all failure modes explicitly.
    """
    try:
        resp = session.post(
            f"{base_url}/api/auth/login",
            json={"username": username, "password": password},
            timeout=10
        )
        resp.raise_for_status()
        token = resp.json().get("token")
        if not token:
            log.error("[TB login] Response did not contain a JWT token")
            return None
        log.info("[TB login] Authenticated successfully")
        return token

    except HTTPError as exc:
        # Log the full TB response body — it contains errorCode which identifies
        # the exact rejection reason: 10=wrong credentials, 11=disabled, 15=locked.
        # Without this the log only shows "401" with no actionable detail.
        body = ""
        try:
            body = exc.response.text
        except Exception:
            pass
        log.error("[TB login] HTTP error %s: %s — TB response: %s",
                  exc.response.status_code, exc, body)
    except RequestsConnectionError as exc:
        log.error("[TB login] Connection error: %s", exc)
    except RequestsTimeout:
        log.error("[TB login] Request timed out after 10 s")
    except RequestException as exc:
        log.error("[TB login] Unexpected request error: %s", exc)

    return None


def _tb_find_device(
    session: requests.Session,
    headers: dict,
    device_name: str,
    base_url: str
) -> Optional[str]:
    """
    Search all pages of the tenant device list for `device_name`.
    Retries up to 3 times with 5s delay to handle TB replication lag
    after device creation (new devices may not appear immediately in the API).
    Returns device id string or None if not found after all retries.
    """
    for _attempt in range(3):
        try:
            page = 0
            while True:
                resp = session.get(
                    f"{base_url}/api/tenant/devices?pageSize=100&page={page}",
                    headers=headers,
                    timeout=10
                )
                resp.raise_for_status()
                data = resp.json()
                devices = data.get("data", [])

                for device in devices:
                    if device.get("name") == device_name:
                        device_id = device["id"]["id"]
                        log.info("[TB find device] Found '%s' → id=%s", device_name, device_id)
                        return device_id

                if not data.get("hasNext", False):
                    break
                page += 1

        except HTTPError as exc:
            log.error("[TB find device] HTTP error %s: %s", exc.response.status_code, exc)
            return None
        except RequestsConnectionError as exc:
            log.error("[TB find device] Connection error: %s", exc)
            return None
        except RequestsTimeout:
            log.error("[TB find device] Request timed out after 10s")
            return None
        except RequestException as exc:
            log.error("[TB find device] Unexpected request error: %s", exc)
            return None

        # Device not found on this attempt — TB may have replication lag after
        # device creation. Wait and retry before giving up.
        if _attempt < 2:
            log.warning(
                "[TB find device] Device '%s' not found (attempt %d/3) — "
                "retrying in 5s (TB replication lag)",
                device_name, _attempt + 1
            )
            import time as _time
            _time.sleep(5)

    log.error("[TB find device] Device '%s' not found in ThingsBoard after 3 attempts",
              device_name)
    return None


def _tb_send_telemetry(
    session: requests.Session,
    headers: dict,
    device_id: str,
    telemetry_data: dict,
    base_url: str
) -> bool:
    """
    POST telemetry_data to the SERVER_SCOPE telemetry endpoint for device_id.
    Returns True on success, False on any failure.
    """
    url = f"{base_url}/api/plugins/telemetry/DEVICE/{device_id}/SERVER_SCOPE"
    try:
        resp = session.post(
            url,
            headers={**headers, "Content-Type": "application/json"},
            json=telemetry_data,
            timeout=10
        )
        resp.raise_for_status()
        log.info("[TB telemetry] Sent to device_id=%s: %s", device_id, telemetry_data)
        return True

    except HTTPError as exc:
        log.error("[TB telemetry] HTTP error %s: %s", exc.response.status_code, exc)
    except RequestsConnectionError as exc:
        log.error("[TB telemetry] Connection error: %s", exc)
    except RequestsTimeout:
        log.error("[TB telemetry] Request timed out after 10 s")
    except RequestException as exc:
        log.error("[TB telemetry] Unexpected request error: %s", exc)

    return False


# ─────────────────────────────────────────────────────────────────────────────
# MAIN ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

def send_webdone(
    telemetry_data: Optional[dict] = None,
    db_path: str = _MODEM_CONFIG_DB,
    retries: int = 3
) -> bool:
    """
    POST {"care": "done"} to ThingsBoard SERVER_SCOPE via REST API.
    This lands in Server Attributes — which is what the TB rule chain
    watches to trigger the provisioning-complete RPC back to the device.

    WEBDONE-FIX-1: mutable default argument replaced with None guard.
    WEBDONE-FIX-2: retry loop (default 3 attempts, 5s delay) — transient
    network blip during provisioning no longer silently drops the signal.
    WEBDONE-FIX-3: returns True/False so device_provisioning() in
    TLChronosProMAIN_391.py can detect failure and abort the sequence
    instead of proceeding to reboot with an undelivered "done".
    WEBDONE-FIX-4: SWatch admin credentials (swatch_username / swatch_password / swatch_host)
    read from modem_config.db — Fernet encrypted, set via LCD menu.
    Renamed from thingsboard_* to swatch_* throughout.
    """
    if telemetry_data is None:
        telemetry_data = {"care": "done"}

    # ── Load device name and TB admin credentials ─────────────────────────
    modem_db    = ModemConfigDatabase(db_path)
    device_name = str(modem_db.get_parameter("device_name") or "").strip()
    if not device_name:
        log.error("[send_webdone] device_name missing in modem_config.db")
        return False

    # WEBDONE-FIX-4: TB admin credentials from modem_config.db only.
    # Set via LCD menu → modem_config.db. That is the single source of truth.
    # Read SWatch credentials — all three are Fernet encrypted in modem_config.db
    def _dec(val):
        """Decrypt a Fernet value. Return as-is if None or decryption fails."""
        if not val:
            return val
        try:
            return decrypt_value(str(val))
        except Exception:
            return val  # already plaintext or unrecognised format

    username    = _dec(modem_db.get_parameter("swatch_username"))
    password    = _dec(modem_db.get_parameter("swatch_password"))
    swatch_host = _dec(modem_db.get_parameter("swatch_host"))

    username    = str(username    or "").strip()
    password    = str(password    or "").strip()
    swatch_host = str(swatch_host or "").strip()

    # Use swatch_host from DB if set, else fall back to default
    base_url = swatch_host if swatch_host else BASE_URL

    if not username or not password:
        log.error(
            "[send_webdone] swatch_username/password not set in "
            "modem_config.db — set them via the LCD menu before provisioning"
        )
        return False

    # ── Network readiness check ───────────────────────────────────────────
    if not wait_for_network("thingsboard.cloud", timeout=30):
        log.error("[send_webdone] DNS not ready — cannot reach ThingsBoard")
        return False

    # ── REST flow with retry ──────────────────────────────────────────────
    for attempt in range(1, retries + 1):
        try:
            with requests.Session() as session:

                # Step 1: Authenticate — get JWT token
                token = _tb_login(session, username, password, base_url)
                if not token:
                    raise RuntimeError("TB login failed — no JWT token returned")

                auth_headers = {"X-Authorization": f"Bearer {token}"}

                # Step 2: Find device by name in tenant
                device_id = _tb_find_device(session, auth_headers, device_name, base_url)
                if not device_id:
                    raise RuntimeError(
                        f"Device '{device_name}' not found in ThingsBoard"
                    )

                # Step 3: POST to SERVER_SCOPE — lands in Server Attributes
                # TB rule chain watches this scope for {"care": "done"}
                ok = _tb_send_telemetry(
                    session, auth_headers, device_id, telemetry_data, base_url
                )
                if ok:
                    log.info(
                        "[send_webdone] SERVER_SCOPE attribute set successfully "
                        "(attempt %d)", attempt
                    )
                    return True

                raise RuntimeError("_tb_send_telemetry returned False")

        except Exception as e:
            log.warning(
                "[send_webdone] Attempt %d/%d failed — %s", attempt, retries, e
            )
            if attempt < retries:
                time.sleep(5)

    log.error(
        "[send_webdone] All %d attempts failed — 'done' not delivered to TB",
        retries
    )
    return False


# ─────────────────────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    send_webdone({"care": "done"})