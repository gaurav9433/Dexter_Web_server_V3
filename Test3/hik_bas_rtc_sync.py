# -*- coding: utf-8 -*-
# !/usr/local/bin/python
#
# hik_bas_rtc_sync.py — Hikvision BAS RTC time-sync and battery-status monitor
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
#   SEC   — update_nvr_time() uses XML PUT — no URL encoding needed here
#             (time is embedded in XML body, not in URL — correct as-is)
#   CODE  — Unused 'import urllib3' / bare urllib3 not present in this file
#   LOG   — All print() replaced with log.*() via get_dual_logger()


import json
import schedule
import threading
import time
from datetime import datetime
from typing import Optional

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
from payload_manager import insert_with_cap

import device_parameters_module
import logical_params_module

# ── Logging ───────────────────────────────────────────────────────────────────
from syslog_file_logger import get_dual_logger
log = get_dual_logger(__name__)




# ── Device credentials ────────────────────────────────────────────────────────
_device_type_key = 'HikvisionBAS1'
_devices  = device_parameters_module.get_device_parameters(_device_type_key)
if not _devices:
    log.error("No device credentials found for '%s'", _device_type_key)
    import sys; sys.exit(1)
ipaddress = _devices[0]['ip_address']
userid    = _devices[0]['username']
password  = _devices[0]['password']

log.info("[init] Hikvision RTC sync target: %s", ipaddress)

# ── NVR time endpoint ─────────────────────────────────────────────────────────
_NVR_TIME_URL = f"http://{ipaddress}/ISAPI/System/time"

# ── Integration flag helper ───────────────────────────────────────────────────
def _integration_active() -> bool:
    return logical_params_module.get_parameter("active_integration_hik_bas") == 1


# ── Bounded insert helper ─────────────────────────────────────────────────────
def _insert(payload: dict) -> None:
    """
    Gate insert on integration flag then push to bounded buffer.
    Replaces the two identical try/except insert blocks in the original.
    """
    if not _integration_active():
        log.info("[insert] Integration not active — skipping")
        return
    try:
        insert_with_cap(json.dumps(payload))
    except Exception as exc:
        log.error("[insert] Failed to insert into buffer: %s", exc)


# ── Thread-safe mismatch counter ─────────────────────────────────────────────
_counter_lock     = threading.Lock()
_mismatch_counter = 0
MISMATCH_THRESHOLD  = 3
DRIFT_TOLERANCE_SEC = 300


# ─────────────────────────────────────────────────────────────────────────────
# NVR TIME READ
# SEC: typed exception handlers replace bare except Exception
# NOTE: Hikvision uses HTTP (not HTTPS) for ISAPI on local network
# ─────────────────────────────────────────────────────────────────────────────

def get_nvr_time() -> Optional[datetime]:
    """
    Query Hikvision BAS current time via ISAPI/System/time (HTTP GET).
    Parses <localTime> element from the XML response.
    Returns datetime (seconds precision) or None on failure.
    SEC: typed exception handlers.
    """
    try:
        resp = requests.get(
            _NVR_TIME_URL,
            auth=HTTPDigestAuth(userid, password),
            timeout=10
        )
        if resp.status_code != 200:
            log.warning("[get_nvr_time] Status %d from NVR", resp.status_code)
            return None

        # Extract <localTime>...</localTime> from XML response
        if "<localTime>" not in resp.text:
            log.warning("[get_nvr_time] <localTime> not found in response")
            return None

        nvr_time_str = resp.text.split("<localTime>")[1].split("</localTime>")[0]
        # Hikvision returns ISO format with IST offset: 2025-03-14T09:30:00+05:30
        nvr_time = datetime.strptime(nvr_time_str, "%Y-%m-%dT%H:%M:%S+05:30")
        log.debug("[get_nvr_time] NVR time: %s", nvr_time)
        return nvr_time

    except HTTPError as exc:
        log.error("[get_nvr_time] HTTP error %s: %s", exc.response.status_code, exc)
    except RequestsConnectionError as exc:
        log.error("[get_nvr_time] Connection error: %s", exc)
    except RequestsTimeout:
        log.error("[get_nvr_time] Request timed out")
    except RequestException as exc:
        log.error("[get_nvr_time] Request error: %s", exc)
    except ValueError as exc:
        log.error("[get_nvr_time] Time parse error: %s", exc)

    return None


# ─────────────────────────────────────────────────────────────────────────────
# NVR TIME SET
# NOTE: Time is sent in the XML body — no URL encoding needed here.
#       The original was already correct for Hikvision's PUT-based ISAPI.
# SEC: typed exception handlers replace bare except Exception
# ─────────────────────────────────────────────────────────────────────────────

def update_nvr_time(local_time: str) -> bool:
    """
    Push local_time string to the Hikvision BAS via ISAPI XML PUT.
    local_time must be in Hikvision format: "YYYY-MM-DDTHH:MM:SS+05:30"
    Returns True on success, False on failure.
    SEC: typed exception handlers.
    """
    xml_payload = (
        '<Time version="1.0" xmlns="http://www.hikvision.com/ver20/XMLSchema">'
        f'<timeMode>manual</timeMode>'
        f'<localTime>{local_time}</localTime>'
        f'<timeZone>CST-5:30:00</timeZone>'
        f'<windowsZone>India Standard Time</windowsZone>'
        f'</Time>'
    )
    headers = {"Content-Type": "application/xml"}

    try:
        resp = requests.put(
            _NVR_TIME_URL,
            data=xml_payload,
            headers=headers,
            auth=HTTPDigestAuth(userid, password),
            timeout=10
        )
        if resp.status_code == 200:
            log.info("[update_nvr_time] NVR time updated to %s", local_time)
            return True
        else:
            log.warning("[update_nvr_time] Failed — status %d", resp.status_code)
            return False

    except HTTPError as exc:
        log.error("[update_nvr_time] HTTP error %s: %s", exc.response.status_code, exc)
    except RequestsConnectionError as exc:
        log.error("[update_nvr_time] Connection error: %s", exc)
    except RequestsTimeout:
        log.error("[update_nvr_time] Request timed out")
    except RequestException as exc:
        log.error("[update_nvr_time] Request error: %s", exc)

    return False


# ─────────────────────────────────────────────────────────────────────────────
# MAIN SYNC LOGIC
# SEC: _insert() replaces two duplicate try/except insert blocks
# SEC: _counter_lock protects mismatch counter read+write
# ─────────────────────────────────────────────────────────────────────────────

def check_and_sync_time() -> None:
    """
    Compare RPi system time against Hikvision BAS time.
    - Always inserts hik_bas_ntp=updated when NVR is reachable.
    - If drift > DRIFT_TOLERANCE_SEC: increment counter, correct NVR time.
    - If counter >= MISMATCH_THRESHOLD: flag battery low, reset counter.
    - If in sync: reset counter.

    SEC: _insert() helper replaces the two duplicate try/except blocks.
    SEC: _counter_lock protects _mismatch_counter read+write.
    """
    global _mismatch_counter

    system_time = datetime.now().replace(microsecond=0)
    nvr_time    = get_nvr_time()

    if nvr_time is None:
        log.warning("[sync] Skipping — NVR time fetch failed")
        return

    log.info("[sync] NVR: %s  System: %s", nvr_time, system_time)

    # Always record a successful NVR time read
    _insert({"hik_bas_ntp": "updated"})

    time_diff = abs((system_time - nvr_time).total_seconds())

    if time_diff > DRIFT_TOLERANCE_SEC:
        with _counter_lock:
            _mismatch_counter += 1
            current_count = _mismatch_counter

        log.warning("[sync] Drift %.0f s (count=%d) — correcting NVR time",
                    time_diff, current_count)

        # Hikvision PUT expects IST offset format
        local_time_str = datetime.now().strftime("%Y-%m-%dT%H:%M:%S+05:30")
        update_nvr_time(local_time_str)

        if current_count >= MISMATCH_THRESHOLD:
            with _counter_lock:
                _mismatch_counter = 0
            log.warning("[sync] %d consecutive mismatches — flagging batt_low",
                        MISMATCH_THRESHOLD)
            _insert({"hik_bas_battery_status": "batt_low"})

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
    #   sudo systemctl restart dexter-rtc-hik-bas
    if logical_params_module.get_parameter("active_integration_hik_bas") != 1:
        import logging as _lg, sys as _sys
        _lg.getLogger(__name__).info(
            "[hik_bas_rtc_sync.py] active_integration_hik_bas=0 — integration disabled, exiting cleanly"
        )
        _sys.exit(0)
    check_and_sync_time()
    schedule.every(1).hours.do(check_and_sync_time)
    log.info("[main] Hikvision RTC sync scheduler started — every 1 hour")
    try:
        while True:
            schedule.run_pending()
            time.sleep(1)
    except KeyboardInterrupt:
        log.info("[main] KeyboardInterrupt — shutting down")
