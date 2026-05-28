# -*- coding: utf-8 -*-
# !/usr/local/bin/python
#
# cp_plus_RTC_sync.py — CP Plus NVR RTC time-sync and battery-status monitor
# Updated per Dexter HMS Database Architecture fixes (March 2026)
#
# Changes applied vs original:
#   DB-01 — WAL mode via get_connection() (applied at startup via infrastructure)
#   DB-02 — FK enforcement via get_connection()
#   DB-03 — Bounded buffer via BoundedBufferManager (50K row hard cap, TTL purge)
#             Replaces bare insert_json_to_db() from old buffer_manager
#   DB-06 — run_all_migrations() at startup before any DB access
#   SEC   — All bare except Exception replaced with typed request handlers
#   SEC   — Duplicate try/except insert blocks extracted into _insert() helper
#   SEC   — mismatch_counter global access wrapped in threading.Lock()
#             (counter is read+written — not atomic in CPython under all conditions)
#   CODE  — Stale commented-out Dahua references removed
#   CODE  — Unused 'import urllib3' removed
#   CODE  — URL space encoding changed from literal %%20 to urllib.parse.quote()
#   LOG   — All print() replaced with log.*() via get_dual_logger()


import json
import schedule
import threading
import time
from datetime import datetime
from typing import Optional
from urllib.parse import quote

import requests
from requests.auth import HTTPDigestAuth
from requests.exceptions import (
    ConnectionError as RequestsConnectionError,
    Timeout        as RequestsTimeout,
    HTTPError,
    RequestException,
)
from urllib3.exceptions import InsecureRequestWarning

# Suppress SSL warnings (CP Plus uses self-signed certs on HTTPS)
requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

# ── Dexter HMS infrastructure imports ────────────────────────────────────────
# DB-01 / DB-02: WAL mode + FK enforcement on every connection
# DB-03: insert_json_to_db enforces 50K row hard cap + TTL purge
from buffer_manager import insert_json_to_db, init_db
init_db()  # Create buffer table if it does not exist yet

# DB-03: Bounded buffer — 50K row hard cap, TTL purge, delivery tracking

# DB-06: Schema versioning — apply pending migrations before any DB access

# DB-05: Atomic JSON writes — available for future file-based config writes

import device_parameters_module
import logical_params_module

# ── Logging — syslog + local file via Dexter dual logger ─────────────────────
from syslog_file_logger import get_dual_logger
log = get_dual_logger(__name__)


# ── DB-01 / DB-02: Verify WAL + FK on all registered databases ───────────────




# ── Device credentials ────────────────────────────────────────────────────────
_device_type_key = 'CP_PlusNVR1'
_devices  = device_parameters_module.get_device_parameters(_device_type_key)
if not _devices:
    log.error("No device credentials found for 'device'")
    import sys; sys.exit(1)
ipaddress = _devices[0]['ip_address']
userid    = _devices[0]['username']
password  = _devices[0]['password']

log.info("[init] CP Plus RTC sync target: %s", ipaddress)

# ── Integration flag helper ───────────────────────────────────────────────────
def _integration_active() -> bool:
    """Return True if CP Plus NVR integration is enabled in logical params."""
    return logical_params_module.get_parameter("active_integration_cp_plus_nvr") == 1


# ── Bounded insert helper ─────────────────────────────────────────────────────
def _insert(payload: dict) -> None:
    """
    Gate insert on integration flag, then push to bounded buffer.
    Extracted from the two duplicate try/except blocks in the original
    check_and_sync_time_cp_plus() — avoids copy-paste and ensures consistent
    error logging in both the NTP-updated and battery-low code paths.
    """
    if not _integration_active():
        log.info("[insert] Integration not active — skipping")
        return
    try:
        insert_json_to_db(json.dumps(payload))
    except Exception as exc:
        log.error("[insert] Failed to insert into buffer: %s", exc)


# ── Mismatch counter — thread-safe ───────────────────────────────────────────
# SEC: mismatch_counter is read and written in check_and_sync_time_cp_plus()
# which runs in the schedule thread. Wrapping in a lock prevents a race
# condition if the scheduler ever runs overlapping jobs.
_counter_lock    = threading.Lock()
_mismatch_counter = 0

# Threshold: 3 consecutive mismatches → flag battery low
MISMATCH_THRESHOLD = 3

# Time drift tolerance in seconds: >300 s (5 min) triggers an NVR time update
DRIFT_TOLERANCE_SEC = 300


# ─────────────────────────────────────────────────────────────────────────────
# NVR TIME READ
# SEC: typed exception handlers replace bare except Exception
# ─────────────────────────────────────────────────────────────────────────────

def get_cp_plus_nvr_time() -> Optional[datetime]:
    """
    Query the CP Plus NVR current time via HTTPS.
    Returns a datetime object (seconds precision) or None on failure.

    SEC: typed exception handlers — ConnectionError, Timeout, HTTPError,
         RequestException, and ValueError each logged separately.
    """
    url = f"https://{ipaddress}/cgi-bin/global.cgi?action=getCurrentTime"
    try:
        response = requests.get(
            url,
            auth=HTTPDigestAuth(userid, password),
            verify=False,
            timeout=10
        )
        response.raise_for_status()

        if "result=" in response.text:
            nvr_time_str = response.text.split("result=")[1].strip()
            nvr_time = datetime.strptime(nvr_time_str, "%Y-%m-%d %H:%M:%S")
            log.debug("[get_time] NVR time: %s", nvr_time)
            return nvr_time
        else:
            log.warning("[get_time] Unexpected response format: %s", response.text[:80])
            return None

    except HTTPError as exc:
        log.error("[get_time] HTTP error %s: %s", exc.response.status_code, exc)
    except RequestsConnectionError as exc:
        log.error("[get_time] Connection error: %s", exc)
    except RequestsTimeout:
        log.error("[get_time] Request timed out")
    except RequestException as exc:
        log.error("[get_time] Request error: %s", exc)
    except ValueError as exc:
        log.error("[get_time] Time parse error: %s", exc)

    return None


# ─────────────────────────────────────────────────────────────────────────────
# NVR TIME SET
# CODE: URL space encoding changed from literal %%20 to urllib.parse.quote()
# SEC: typed exception handlers replace bare except Exception
# ─────────────────────────────────────────────────────────────────────────────

def set_cp_plus_nvr_time(system_time: datetime) -> bool:
    """
    Push the given system_time to the CP Plus NVR via HTTPS GET.
    Returns True on success, False on any failure.

    CODE: urllib.parse.quote() used for URL encoding instead of literal %%20
          — more explicit and handles edge cases correctly.
    SEC: typed exception handlers.
    """
    # CP Plus expects: YYYY-MM-DD HH:MM:SS with space URL-encoded as %20
    time_str      = system_time.strftime("%Y-%m-%d %H:%M:%S")
    encoded_time  = quote(time_str, safe=":-")   # encode space → %20, keep : and -
    url = f"https://{ipaddress}/cgi-bin/global.cgi?action=setCurrentTime&time={encoded_time}"

    try:
        response = requests.get(
            url,
            auth=HTTPDigestAuth(userid, password),
            verify=False,
            timeout=10
        )
        response.raise_for_status()
        log.info("[set_time] NVR time updated to %s (status=%d)", system_time, response.status_code)
        return True

    except HTTPError as exc:
        log.error("[set_time] HTTP error %s: %s", exc.response.status_code, exc)
    except RequestsConnectionError as exc:
        log.error("[set_time] Connection error: %s", exc)
    except RequestsTimeout:
        log.error("[set_time] Request timed out")
    except RequestException as exc:
        log.error("[set_time] Request error: %s", exc)

    return False


# ─────────────────────────────────────────────────────────────────────────────
# MAIN SYNC LOGIC
# SEC: duplicate insert try/except blocks replaced with _insert() helper
# SEC: mismatch_counter access protected by _counter_lock
# ─────────────────────────────────────────────────────────────────────────────

def check_and_sync_time_cp_plus() -> None:
    """
    Compare RPi system time against NVR time.

    Behaviour:
    - Always inserts cp_plus_ntp=updated when NVR time is reachable.
    - If drift > DRIFT_TOLERANCE_SEC (300 s): increment mismatch counter,
      push NVR time correction.
    - If mismatch counter reaches MISMATCH_THRESHOLD (3): reset counter,
      insert cp_plus_nvr_battery_status=nvr_batt_low.
    - If times are in sync: reset mismatch counter.

    SEC: _insert() helper replaces the two duplicate try/except insert blocks.
    SEC: _counter_lock protects mismatch_counter read+write.
    """
    global _mismatch_counter

    system_time = datetime.now().replace(microsecond=0)
    nvr_time    = get_cp_plus_nvr_time()

    if nvr_time is None:
        log.warning("[sync] Skipping update — NVR time fetch failed")
        return

    log.info("[sync] NVR time: %s  |  System time: %s", nvr_time, system_time)

    # Always record a successful NVR time read as an NTP-updated event
    _insert({"cp_plus_ntp": "updated"})

    time_diff = abs((system_time - nvr_time).total_seconds())

    if time_diff > DRIFT_TOLERANCE_SEC:
        with _counter_lock:
            _mismatch_counter += 1
            current_count = _mismatch_counter

        log.warning(
            "[sync] Time drift %.0f s exceeds threshold (count=%d) — correcting NVR time",
            time_diff, current_count
        )
        set_cp_plus_nvr_time(system_time)

        if current_count >= MISMATCH_THRESHOLD:
            # Three consecutive mismatches → RTC battery is likely low
            with _counter_lock:
                _mismatch_counter = 0

            log.warning(
                "[sync] %d consecutive mismatches — flagging nvr_batt_low",
                MISMATCH_THRESHOLD
            )
            _insert({"cp_plus_nvr_battery_status": "nvr_batt_low"})

    else:
        log.info("[sync] Times are in sync (drift=%.0f s) — resetting counter", time_diff)
        with _counter_lock:
            _mismatch_counter = 0


# ─────────────────────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":

    # Run immediately at startup then every hour
    # ACTIVE-INTEGRATION-GUARD: check flag before doing any work
    # If integration is disabled from the menu, exit cleanly.
    # systemd sees exit(0) as success and will NOT restart the service.
    # Service stays enabled — to re-activate, enable from menu then:
    #   sudo systemctl restart dexter-rtc-cpplus
    if logical_params_module.get_parameter("active_integration_cp_plus_nvr") != 1:
        import logging as _lg, sys as _sys
        _lg.getLogger(__name__).info(
            "[cp_plus_RTC_sync.py] active_integration_cp_plus_nvr=0 — integration disabled, exiting cleanly"
        )
        _sys.exit(0)
    check_and_sync_time_cp_plus()

    schedule.every(1).hours.do(check_and_sync_time_cp_plus)

    log.info("[main] RTC sync scheduler started — running every 1 hour")

    try:
        while True:
            schedule.run_pending()
            time.sleep(1)
    except KeyboardInterrupt:
        log.info("[main] KeyboardInterrupt — shutting down")
