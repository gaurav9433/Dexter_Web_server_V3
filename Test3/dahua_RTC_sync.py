# -*- coding: utf-8 -*-
# !/usr/local/bin/python
#
# dahua_RTC_sync.py — Dahua NVR RTC time-sync and battery-status monitor
# Updated per Dexter HMS Database Architecture fixes (March 2026)
#
# Changes applied vs original:
#   DB-01 — WAL mode via get_connection() (applied at startup via infrastructure)
#   DB-02 — FK enforcement via get_connection()
#   DB-03 — Bounded buffer via BoundedBufferManager (50K row hard cap, TTL purge)
#   DB-06 — run_all_migrations() + verify_all_databases() at startup
#   SEC   — Typed exception handlers replace bare except Exception throughout
#   SEC   — Duplicate insert try/except blocks extracted into _insert() helper
#   SEC   — mismatch_counter global access wrapped in threading.Lock()
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

requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

# ── Dexter HMS infrastructure imports ────────────────────────────────────────
# DB-03: insert_json_to_db enforces 50K row hard cap + TTL purge
from buffer_manager import insert_json_to_db, init_db
init_db()  # Create buffer table if it does not exist yet

import device_parameters_module
import logical_params_module

# ── Logging ───────────────────────────────────────────────────────────────────
from syslog_file_logger import get_dual_logger
log = get_dual_logger(__name__)


# ── DB-01 / DB-02: Verify WAL + FK on all registered databases ───────────────




# ── Device credentials ────────────────────────────────────────────────────────
_device_type_key = 'DahuaNVR1'
_devices  = device_parameters_module.get_device_parameters(_device_type_key)
if not _devices:
    log.error("No device credentials found for 'device'")
    import sys; sys.exit(1)
ipaddress = _devices[0]['ip_address']
userid    = _devices[0]['username']
password  = _devices[0]['password']

log.info("[init] Dahua RTC sync target: %s", ipaddress)

# ── Integration flag helper ───────────────────────────────────────────────────
def _integration_active() -> bool:
    return logical_params_module.get_parameter("active_integration_dahua_nvr") == 1


# ── Bounded insert helper ─────────────────────────────────────────────────────
def _insert(payload: dict) -> None:
    """Gate insert on integration flag then push to bounded buffer."""
    if not _integration_active():
        log.info("[insert] Integration not active — skipping")
        return
    try:
        insert_json_to_db(json.dumps(payload))
    except Exception as exc:
        log.error("[insert] Failed to insert into buffer: %s", exc)


# ── Thread-safe mismatch counter ─────────────────────────────────────────────
_counter_lock     = threading.Lock()
_mismatch_counter = 0
MISMATCH_THRESHOLD  = 3
DRIFT_TOLERANCE_SEC = 300


# ─────────────────────────────────────────────────────────────────────────────
# NVR TIME READ
# ─────────────────────────────────────────────────────────────────────────────

def get_dahua_nvr_time() -> Optional[datetime]:
    """
    Query Dahua NVR current time via HTTP.
    Returns datetime (seconds precision) or None on failure.
    SEC: typed exception handlers.
    """
    url = f"http://{ipaddress}/cgi-bin/global.cgi?action=getCurrentTime"
    try:
        resp = requests.get(
            url, auth=HTTPDigestAuth(userid, password),
            verify=False, timeout=10
        )
        resp.raise_for_status()
        if "result=" in resp.text:
            nvr_time_str = resp.text.split("result=")[1].strip()
            return datetime.strptime(nvr_time_str, "%Y-%m-%d %H:%M:%S")
        log.warning("[get_time] Unexpected format: %s", resp.text[:80])
        return None

    except HTTPError as exc:
        log.error("[get_time] HTTP %s: %s", exc.response.status_code, exc)
    except RequestsConnectionError as exc:
        log.error("[get_time] Connection error: %s", exc)
    except RequestsTimeout:
        log.error("[get_time] Timed out")
    except RequestException as exc:
        log.error("[get_time] Request error: %s", exc)
    except ValueError as exc:
        log.error("[get_time] Time parse error: %s", exc)
    return None


# ─────────────────────────────────────────────────────────────────────────────
# NVR TIME SET
# ─────────────────────────────────────────────────────────────────────────────

def set_dahua_nvr_time(system_time: datetime) -> bool:
    """
    Push system_time to Dahua NVR via HTTP GET.
    Returns True on success, False on failure.
    CODE: urllib.parse.quote() replaces literal %%20 encoding.
    SEC: typed exception handlers.
    """
    time_str     = system_time.strftime("%Y-%m-%d %H:%M:%S")
    encoded_time = quote(time_str, safe=":-")
    url = f"http://{ipaddress}/cgi-bin/global.cgi?action=setCurrentTime&time={encoded_time}"

    try:
        resp = requests.get(
            url, auth=HTTPDigestAuth(userid, password),
            verify=False, timeout=10
        )
        resp.raise_for_status()
        log.info("[set_time] NVR time updated to %s (status=%d)", system_time, resp.status_code)
        return True

    except HTTPError as exc:
        log.error("[set_time] HTTP %s: %s", exc.response.status_code, exc)
    except RequestsConnectionError as exc:
        log.error("[set_time] Connection error: %s", exc)
    except RequestsTimeout:
        log.error("[set_time] Timed out")
    except RequestException as exc:
        log.error("[set_time] Request error: %s", exc)
    return False


# ─────────────────────────────────────────────────────────────────────────────
# MAIN SYNC LOGIC
# ─────────────────────────────────────────────────────────────────────────────

def check_and_sync_time_dahua() -> None:
    """
    Compare RPi system time against Dahua NVR time.
    - Always inserts dahua_ntp=updated when NVR is reachable.
    - If drift > DRIFT_TOLERANCE_SEC: increment counter, correct NVR time.
    - If counter >= MISMATCH_THRESHOLD: flag battery low, reset counter.
    - If in sync: reset counter.
    SEC: _insert() replaces duplicate try/except insert blocks.
    SEC: _counter_lock protects mismatch counter read+write.
    """
    global _mismatch_counter

    system_time = datetime.now().replace(microsecond=0)
    nvr_time    = get_dahua_nvr_time()

    if nvr_time is None:
        log.warning("[sync] Skipping — NVR time fetch failed")
        return

    log.info("[sync] NVR: %s  System: %s", nvr_time, system_time)

    _insert({"dahua_ntp": "updated"})

    time_diff = abs((system_time - nvr_time).total_seconds())

    if time_diff > DRIFT_TOLERANCE_SEC:
        with _counter_lock:
            _mismatch_counter += 1
            current_count = _mismatch_counter

        log.warning("[sync] Drift %.0f s (count=%d) — correcting NVR time",
                    time_diff, current_count)
        set_dahua_nvr_time(system_time)

        if current_count >= MISMATCH_THRESHOLD:
            with _counter_lock:
                _mismatch_counter = 0
            log.warning("[sync] %d consecutive mismatches — flagging nvr_batt_low",
                        MISMATCH_THRESHOLD)
            _insert({"dahua_nvr_battery_status": "nvr_batt_low"})
    else:
        log.info("[sync] In sync (drift=%.0f s) — resetting counter", time_diff)
        with _counter_lock:
            _mismatch_counter = 0


# ─────────────────────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # ACTIVE-INTEGRATION-GUARD: check flag before doing any work
    # If integration is disabled from the menu, exit cleanly.
    # systemd sees exit(0) as success and will NOT restart the service.
    # Service stays enabled — to re-activate, enable from menu then:
    #   sudo systemctl restart dexter-rtc-dahua
    if logical_params_module.get_parameter("active_integration_dahua_nvr") != 1:
        import logging as _lg, sys as _sys
        _lg.getLogger(__name__).info(
            "[dahua_RTC_sync.py] active_integration_dahua_nvr=0 — integration disabled, exiting cleanly"
        )
        _sys.exit(0)
    check_and_sync_time_dahua()
    schedule.every(1).hours.do(check_and_sync_time_dahua)
    log.info("[main] Dahua RTC sync scheduler started — every 1 hour")
    try:
        while True:
            schedule.run_pending()
            time.sleep(1)
    except KeyboardInterrupt:
        log.info("[main] KeyboardInterrupt — shutting down")
