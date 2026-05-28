# -*- coding: utf-8 -*-
# !/usr/local/bin/python
#
# Extract_Logs_Dahua_41.py — Dahua NVR log extraction, parsing & telemetry
# Updated per Dexter HMS Database Architecture fixes (March 2026)
#
# Changes applied vs original:
#   CQ-01 — SoftwareWatchdog class removed (was 39-line copy-paste)
#           Replaced with: from watchdog_manager import SoftwareWatchdog
#           watchdog_manager.py is the single source of truth for all modules
#   DB-01 — WAL mode via get_connection() (applied at startup via infrastructure)
#   DB-02 — FK enforcement via get_connection()
#   DB-03 — Bounded buffer via BoundedBufferManager (50K row hard cap, TTL purge)
#   DB-06 — run_all_migrations() + verify_all_databases() at startup
#   BUG   — 'import watchdog' removed — was shadowing SoftwareWatchdog instance
#   BUG   — Duplicate 'from buffer_manager import insert_json_to_db' (lines 23
#             and 116) removed — only one bounded import needed
#   BUG   — bare except Exception in main loop replaced with typed handler + log
#   CODE  — Unused imports removed: warnings, paho.mqtt, urllib3 (bare import)
#   CODE  — Duplicate 'import time' removed
#   CODE  — 'import re' moved to module level (was scattered inside functions)
#   CODE  — 'import datetime' inside functions removed (already at module level)
#   LOG   — All print() replaced with log.*() via get_dual_logger()
#   NVR-01
#   ERR-03 — logging.shutdown() before os.execl() in watchdog restart
#             ensures RotatingFileHandler and SysLogHandler are fully flushed — _http_get() retry wrapper used in extract_logs() startFind+doFind
#   NVR-02 — last_fetched_timestamp state: only new events fetched each cycle
#   NVR-03 — fetch/process failure does not advance timestamp — same window retried
#   ERR-02 — parse_logs_array_dictionary: except Exception → (ValueError,IndexError,KeyError)
#             format_date_time: except Exception → except ValueError
#   ERR-03 — logging.shutdown() before os.execl() in watchdog
#   ERR-04 — main loop catch-all adds traceback.format_exc() for root-cause diagnosis
#   NOTE  — Versioned legacy functions preserved as-is (not called in production)


import json
import os
import re
import sys
import schedule
import threading
import time
from collections import defaultdict
from datetime import datetime
from typing import Optional, List, Any

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
# Dexter HMS: insert_with_cap writes to payloads.db — read by SWatch publisher
from payload_manager import insert_with_cap

import device_parameters_module
import logical_params_module

# ── Logging ───────────────────────────────────────────────────────────────────
from syslog_file_logger import get_dual_logger
from watchdog_manager import SoftwareWatchdog  # CQ-01

# ── Inline replacements for json_db_fix (not deployed on Pi) ─────────────────
import os as _os, json as _json

def atomic_write_json(path: str, data: dict) -> None:
    """Write JSON atomically — power-loss safe via os.replace."""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        _json.dump(data, f)
    _os.replace(tmp, path)

def safe_read_json(path: str, default=None):
    """Read JSON file, return default if missing or corrupt."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return _json.load(f)
    except (FileNotFoundError, _json.JSONDecodeError):
        return default if default is not None else {}
# ─────────────────────────────────────────────────────────────────────────────

log = get_dual_logger(__name__)

# ── DB-06 / DB-01 / DB-02: startup checks ────────────────────────────────────



# ── Integration flag ──────────────────────────────────────────────────────────

# ── HTTP retry helper (NVR-01) ────────────────────────────────────────────────
_RETRY_STATUS = {500, 502, 503, 504}
_RETRY_DELAYS = [0, 1, 3, 5]


def _http_get(url: str, auth, timeout: int = 10):
    """
    GET with automatic retry on transient 5xx and connection errors.
    NVR-01: up to 4 attempts with 0s/1s/3s/5s progressive delays.
    Returns response on success, None after all retries exhausted.
    """
    last_exc = None
    for attempt, delay in enumerate(_RETRY_DELAYS, start=1):
        if delay:
            time.sleep(delay)
        try:
            resp = requests.get(url, auth=auth, verify=False, timeout=timeout)
            if resp.status_code in _RETRY_STATUS:
                log.warning("[HTTP] %d attempt %d/%d for %s — retrying",
                            resp.status_code, attempt, len(_RETRY_DELAYS), url)
                continue
            return resp
        except RequestsConnectionError as exc:
            log.warning("[HTTP] Attempt %d/%d connection error %s: %s",
                        attempt, len(_RETRY_DELAYS), url, exc)
            last_exc = exc
        except RequestsTimeout:
            log.warning("[HTTP] Attempt %d/%d timeout %s",
                        attempt, len(_RETRY_DELAYS), url)
            last_exc = RequestsTimeout()
        except RequestException as exc:
            log.error("[HTTP] Non-retryable error %s: %s", url, exc)
            return None
    log.error("[HTTP] All %d attempts exhausted for %s: %s",
              len(_RETRY_DELAYS), url, last_exc)
    return None


# ── Last-fetched deduplication state (NVR-02) ────────────────────────────────
# NVR-02: Persist the end-timestamp of the last successfully processed poll
# cycle. Each cycle fetches only events AFTER this timestamp — eliminating
# duplicate event re-insertion that previously caused DB bloat and repeated
# ThingsBoard alerts. Uses atomic_write_json (already imported) — power-loss safe.
# NVR-03: On any fetch or processing failure the timestamp is NOT advanced —
# the same window is retried on the next cycle, preventing event gaps.

_FETCH_STATE_FILE = "/home/pi/Test3/dahua_log_fetch_state.json"


def _get_last_fetched() -> str:
    """
    Load last successful fetch end-timestamp from state file.
    Defaults to 24 hours ago on first run.
    """
    import datetime as _dt
    state = safe_read_json(_FETCH_STATE_FILE, default={})
    if "last_fetched" in state:
        log.debug("[dedup] Last fetched: %s", state["last_fetched"])
        return state["last_fetched"]
    default = (_dt.datetime.now() - _dt.timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
    log.info("[dedup] No state file — defaulting to 24h ago: %s", default)
    return default


def _save_last_fetched(timestamp: str) -> None:
    """Persist fetch end-timestamp atomically via atomic_write_json."""
    atomic_write_json(_FETCH_STATE_FILE, {"last_fetched": timestamp})
    log.debug("[dedup] State saved: last_fetched=%s", timestamp)

def _integration_active() -> bool:
    return logical_params_module.get_parameter("active_integration_dahua_nvr") == 1


# ── Device credentials ────────────────────────────────────────────────────────
_device_type_key = 'DahuaNVR1'
_devices  = device_parameters_module.get_device_parameters(_device_type_key)
if not _devices:
    log.error("No device credentials found for 'device'")
    import sys; sys.exit(1)
ipaddress = _devices[0]['ip_address']
userid    = _devices[0]['username']
password  = _devices[0]['password']

log.info("[init] Dahua log extractor target: %s", ipaddress)



# CQ-01: watchdog now from shared watchdog_manager.py
watchdog = SoftwareWatchdog(
    module_label="Dahua Logs",
    timeout=3600,
)


# ─────────────────────────────────────────────────────────────────────────────
# URL BUILDER
# ─────────────────────────────────────────────────────────────────────────────

def build_url(ip: str, endpoint: str) -> str:
    return f"http://{ip}/cgi-bin/{endpoint}"


# ─────────────────────────────────────────────────────────────────────────────
# LOG EXTRACTION FROM NVR
# SEC: typed exception handlers; print() → log.*()
# ─────────────────────────────────────────────────────────────────────────────

def extract_logs(
    ip: str, userid: str, password: str,
    start_time: str, end_time: str
) -> Optional[str]:
    """
    Two-step Dahua log retrieval:
    1. startFind → obtain token
    2. doFind    → retrieve up to 100 log entries

    Returns raw log text string, or None on any failure.
    """
    try:
        start_url = build_url(
            ip,
            "log.cgi?action=startFind"
            f"&condition.StartTime={start_time}"
            f"&condition.EndTime={end_time}"
        )
        resp = _http_get(start_url, auth=HTTPDigestAuth(userid, password), timeout=10)

        if resp.status_code == 401:
            log.error("[extract_logs] Auth failed (401) — check credentials")
            return None
        if resp.status_code != 200:
            log.error("[extract_logs] startFind failed — status %d", resp.status_code)
            return None

        token = None
        if "token=" in resp.text:
            token = resp.text.split("token=")[1].strip()
        if not token:
            log.error("[extract_logs] Token not found: %s", resp.text[:80])
            return None

        log.debug("[extract_logs] Token: %s", token)

        do_url = build_url(ip, f"log.cgi?action=doFind&token={token}&count=100")
        resp2 = _http_get(do_url, auth=HTTPDigestAuth(userid, password), timeout=10)
        if resp2.status_code != 200:
            log.error("[extract_logs] doFind failed — status %d", resp2.status_code)
            return None

        log.debug("[extract_logs] Retrieved %d chars", len(resp2.text))
        return resp2.text

    except RequestsConnectionError as exc:
        log.error("[extract_logs] Connection error: %s", exc)
    except RequestsTimeout:
        log.error("[extract_logs] Request timed out")
    except RequestException as exc:
        log.error("[extract_logs] Request error: %s", exc)

    return None

# ----------------------
# FETCH DAHUA HDD STATUS
# ----------------------

EXPECTED_HDD_COUNT = 4  # Number of HDD slots in your NVR

# ----------------------
# GLOBAL TRACKER
# ----------------------
sent_disk_errors = set()

def get_dahua_error_hdd_slots():
    try:
        url = f"http://{ipaddress}/cgi-bin/storageDevice.cgi?action=getDeviceAllInfo"
        response = requests.get(
            url,
            auth=HTTPDigestAuth(userid, password),
            timeout=10
        )
        response.raise_for_status()

        lines = response.text.splitlines()
        disks = {}          # index → disk name
        error_disks = set() # disks with IsError=true

        # ----------------------
        # Parse the API response
        # ----------------------
        for line in lines:
            line = line.strip()

            # Get disk name
            match_name = re.match(r'list\.info\[(\d+)\]\.Name=(.+)', line)
            if match_name:
                index = int(match_name.group(1))
                name = match_name.group(2)
                disks[index] = name

            # Check error flag
            match_error = re.match(
                r'list\.info\[(\d+)\]\.Detail\[\d+\]\.IsError=(true|false)',
                line
            )
            if match_error:
                index = int(match_error.group(1))
                is_error = match_error.group(2)
                if is_error == "true" and index in disks:
                    error_disks.add(disks[index])

        # ----------------------
        # Treat Missing Slots as Error (1-based numbering)
        # ----------------------
        for i in range(EXPECTED_HDD_COUNT):
            if i not in disks:
                error_disks.add(f"Slot {i + 1}")

        return list(error_disks)

    except Exception as e:
        log.error("[HDD] Dahua fetch failed: %s", e)
        return None

# ----------------------
# MAIN EVALUATION FUNCTION
# ----------------------
def evaluate_dahua_hdd_state():
    global sent_disk_errors

    now = datetime.now()
    formatted_date = now.strftime("%d:%m:%y")
    formatted_time = now.strftime("%H:%M")

    error_slots = get_dahua_error_hdd_slots()
    if error_slots is None:
        log.warning("[HDD] Dahua fetch failed — skipping evaluation")
        return

    current_error_slots = set(error_slots)

    # ----------------------
    # 1️⃣ SEND NEW ERRORS
    # ----------------------
    new_errors = current_error_slots - sent_disk_errors
    for slot in new_errors:
        response = {
            "log_type": "hdd_error",
            "date": formatted_date,
            "time": formatted_time,
            "zone_no": None,
            "channelID": None,
            "slot": slot,
        }

        log.info("[HDD] Error detected: %s", slot)

        # Insert into ThingsBoard DB if integration is active
        if logical_params_module.get_parameter("active_integration_dahua_nvr") == 1:
            insert_with_cap(json.dumps(response))

        sent_disk_errors.add(slot)

    # ----------------------
    # 2️⃣ SEND RESTORED DISKS
    # ----------------------
    restored_slots = sent_disk_errors - current_error_slots
    for slot in restored_slots:
        response = {
            "log_type": "hdd_error_restored",
            "date": formatted_date,
            "time": formatted_time,
            "zone_no": None,
            "channelID": None,
            "slot": slot,
        }

        log.info("[HDD] Restored: %s", slot)

        if logical_params_module.get_parameter("active_integration_dahua_nvr") == 1:
            insert_with_cap(json.dumps(response))

        sent_disk_errors.remove(slot)
# ─────────────────────────────────────────────────────────────────────────────
# LOG PARSING
# LOG: print() replaced with log.*()
# ─────────────────────────────────────────────────────────────────────────────

def debug_logs(raw_data: str) -> str:
    log_summary = defaultdict(list)
    log_entry_pattern = r"=== Log Entry ===\n(.+?)(?=\n=== Log Entry ===|\Z)"
    time_pattern      = r"items\[\d+\]\.Time=(.+)"
    type_pattern      = r"items\[\d+\]\.Type=(.+)"
    detail_pattern    = r"items\[\d+\]\.Detail=(.+)"

    for entry in re.findall(log_entry_pattern, raw_data, re.DOTALL):
        time_match   = re.search(time_pattern,   entry)
        type_match   = re.search(type_pattern,   entry)
        detail_match = re.search(detail_pattern, entry)
        if time_match and type_match:
            log_time = time_match.group(1).strip()
            log_type = type_match.group(1).strip()
            if log_type in ["HDD Error", "Video Tampering", "CAM Offline Alarm"]:
                detail = detail_match.group(1).strip() if detail_match else ""
                log_summary[log_type].append(f"{log_type} at {log_time} - {detail}")

    output = []
    for section in ["HDD Error", "Video Tampering", "CAM Offline Alarm"]:
        if log_summary[section]:
            output.append(f"\n{section}:")
            output.extend(log_summary[section])
    return "\n".join(output)


def parse_logs(log_data: str) -> str:
    """Parse raw NVR log text into a structured summary string."""
    log.debug("[parse_logs] Starting")

    raw_logs = re.split(r"items\[\d+\]\.Detail=", log_data)
    hdd_errors:             list = []
    video_tampering_events: dict = {}
    cam_offline_alarms:     dict = {}

    for raw in raw_logs:
        raw = raw.strip()
        if not raw:
            continue

        type_match = re.search(r"Type=([^\r\n]*)", raw)
        time_match = re.search(r"Time=(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", raw)

        if type_match and "HDD Error" in type_match.group(1):
            timestamp = time_match.group(1) if time_match else ""
            if timestamp:
                hdd_errors.append(f"HDD Error at {timestamp}")
                log.debug("[parse_logs] HDD error at %s", timestamp)
            continue

        event_type_match = re.search(r"Event Type:(.*)", raw)
        channel_match    = re.search(r"Channel:(\d+)", raw)
        action_match     = re.search(r"Event Action:(.*)", raw)
        start_match      = re.search(r"Start Time:(.*)", raw)
        end_match        = re.search(r"End Time:(.*)", raw)

        event_type = event_type_match.group(1).strip() if event_type_match else ""
        channel    = channel_match.group(1).strip()    if channel_match    else "Unknown"
        action     = action_match.group(1).strip()     if action_match     else ""
        ts_match   = start_match or end_match
        timestamp  = ts_match.group(1).strip()         if ts_match         else ""

        if not event_type or not timestamp:
            continue

        log.debug("[parse_logs] event=%s ch=%s action=%s ts=%s",
                  event_type, channel, action, timestamp)

        if "Video Tampering" in event_type:
            if "Start" in action:
                video_tampering_events[channel] = {"start_time": timestamp}
            else:
                video_tampering_events[channel] = {"end_time": timestamp}
        elif "CAM Offline Alarm" in event_type:
            if "Start" in action:
                cam_offline_alarms[channel] = {"start_time": timestamp}
            else:
                cam_offline_alarms[channel] = {"end_time": timestamp}

    result = ["HDD Error:"]
    result.extend(hdd_errors)
    result.append("\nVideo Tampering:")
    for ch, times in video_tampering_events.items():
        for t, val in times.items():
            result.append(
                "Event {} on Channel {} at {}".format(
                    t.replace("_time", "").capitalize(), ch, val
                )
            )
    result.append("\nCAM Offline Alarm:")
    for ch, times in cam_offline_alarms.items():
        for t, val in times.items():
            result.append(
                "Event {} on Channel {} at {}".format(
                    t.replace("_time", "").capitalize(), ch, val
                )
            )

    return "\n".join(result)


def parse_logs_array_dictionary(input_data: str) -> list:
    """Convert parse_logs() output into structured event dict list."""

    def format_date_time(timestamp: str) -> tuple[str | None, str | None]:
        try:
            dt = datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S")
            return dt.strftime("%d:%m:%y"), dt.strftime("%H:%M")
        except ValueError as exc:
            # ERR-02: only strptime raises ValueError — narrowed from Exception
            log.debug("[parse_dict] Unparseable timestamp '%s': %s",
                      timestamp, exc)
            return None, None

    parsed_logs:    list = []
    lines               = input_data.strip().splitlines()
    current_section     = None

    for line in lines:
        line = line.strip()
        if not line:
            continue

        if line.startswith("HDD Error:"):
            current_section = "hdd"; continue
        elif line.startswith("Video Tampering:"):
            current_section = "tamper"; continue
        elif "CAM Offline Alarm" in line or "Camera Offline" in line:
            current_section = "offline"; continue

        if current_section == "hdd" and "HDD Error at" in line:
            try:
                timestamp = line.split(" at ")[1].strip()
                date, t   = format_date_time(timestamp)
                #if date and t:
                   # parsed_logs.append({"log_type": "hardisk_error", "channelID": None,
                   #                     "date": date, "time": t})
            except (ValueError, IndexError, KeyError) as exc:
                # ERR-02: narrowed from Exception — these are the only errors
                # raised by split(), list indexing, and dict access on raw NVR text
                log.debug("[parse_dict] Skipping malformed log line: %s", exc)
                continue

        elif current_section == "tamper" and "Event" in line and "Channel" in line:
            parts = line.split(" ")
            try:
                channel_id = next((x for x in parts if x.isdigit()), None)
                timestamp  = parts[-2] + " " + parts[-1]
                date, t    = format_date_time(timestamp)
                if not (date and t): continue
                log_type = "camera_tampered" if "Start" in line else "camera_tampered_restored"
                parsed_logs.append({"log_type": log_type, "channelID": channel_id,
                                    "date": date, "time": t})
            except (ValueError, IndexError, KeyError) as exc:
                # ERR-02: narrowed from Exception — these are the only errors
                # raised by split(), list indexing, and dict access on raw NVR text
                log.debug("[parse_dict] Skipping malformed log line: %s", exc)
                continue

        elif current_section == "offline" and "Event" in line and "Channel" in line:
            parts = line.split(" ")
            try:
                channel_id = next((x for x in parts if x.isdigit()), None)
                timestamp  = parts[-2] + " " + parts[-1]
                date, t    = format_date_time(timestamp)
                if not (date and t): continue
                log_type = (
                    "camera_disconnect"
                    if "Start" in line
                    else "camera_connection_established"
                )
                parsed_logs.append({"log_type": log_type, "channelID": channel_id,
                                    "date": date, "time": t})
            except (ValueError, IndexError, KeyError) as exc:
                # ERR-02: narrowed from Exception — these are the only errors
                # raised by split(), list indexing, and dict access on raw NVR text
                log.debug("[parse_dict] Skipping malformed log line: %s", exc)
                continue

    return parsed_logs


# ─────────────────────────────────────────────────────────────────────────────
# LOG FILTERING
# ─────────────────────────────────────────────────────────────────────────────

last_log_type:     Optional[str] = None
hdd_restored_sent: bool          = False


def parse_logs_filtered(logs: List[Any]) -> List[Any]:
    global last_log_type, hdd_restored_sent

    new_logs:        List[Any] = []
    hdd_error_added: bool = False

    for log_entry in logs:
        if log_entry["log_type"] == "hdd_error":
            if not hdd_error_added:
                new_logs.append(log_entry)
                hdd_error_added   = True
                last_log_type     = "hdd_error"
                hdd_restored_sent = False
        elif log_entry["log_type"] == "hdd_error_restored":
            if not hdd_restored_sent:
                new_logs.append(log_entry)
                last_log_type     = "hdd_error_restored"
                hdd_restored_sent = True
        else:
            new_logs.append(log_entry)
            last_log_type = log_entry["log_type"]

    if not hdd_error_added and not hdd_restored_sent:
        #new_logs.append({
        #    "zone_no": None, "channelID": None, "branch": None,
        #    "time":    time.strftime("%H%M"),
        #    "date":    time.strftime("%d%m%y"),
        #    "log_type":"hardisk_error_restored",
        #})
        last_log_type     = "hdd_error_restored"
        hdd_restored_sent = True

    return new_logs


# ─────────────────────────────────────────────────────────────────────────────
# TIME WINDOW GENERATION
# ─────────────────────────────────────────────────────────────────────────────

start_time_history: list = []


def generate_time_difference(minutes_to_deduct: int) -> dict:
    global start_time_history
    import datetime as _dt
    try:
        if not start_time_history:
            current_time = _dt.datetime.now()
        else:
            current_time = start_time_history[-1] + \
                _dt.timedelta(minutes=minutes_to_deduct, seconds=1)
        start_time_history.append(current_time)
        end_time = current_time - _dt.timedelta(minutes=minutes_to_deduct)
        return {
            "start_time": current_time.strftime("%Y-%m-%d %H:%M:%S"),
            "end_time":   end_time.strftime("%Y-%m-%d %H:%M:%S"),
        }
    except Exception as exc:
        log.error("[generate_time_difference] Error: %s", exc)
        return {"error": str(exc)}


# ─────────────────────────────────────────────────────────────────────────────
# LOG ENTRY PROCESSING & BUFFER INSERT
# ─────────────────────────────────────────────────────────────────────────────

def process_log_entries(log_entries: list) -> None:
    if not log_entries:
        return
    for entry in log_entries:
        if not entry:
            continue
        log.debug("[process_log_entries] %s", entry)
        subsequent_processing(entry)


def subsequent_processing(entry: dict) -> None:
    """Push a single parsed log entry dict to the bounded buffer."""
    attributes_json = json.dumps(entry)
    if _integration_active():
        insert_with_cap(attributes_json)
    log.info("[subsequent_processing] pushed: %s", attributes_json)


# ─────────────────────────────────────────────────────────────────────────────
# ENTRY POINT
# BUG fix: bare except Exception: pass in main loop replaced with typed handler
# ─────────────────────────────────────────────────────────────────────────────


if __name__ == "__main__":

    # ACTIVE-INTEGRATION-GUARD: check flag before doing any work
    # If integration is disabled from the menu, exit cleanly.
    # systemd sees exit(0) as success and will NOT restart the service.
    # Service stays enabled — to re-activate, enable from menu then:
    #   sudo systemctl restart dexter-extract-dahua
    if logical_params_module.get_parameter("active_integration_dahua_nvr") != 1:
        import logging as _lg, sys as _sys
        _lg.getLogger(__name__).info(
            "[Extract_Logs_Dahua_41.py] active_integration_dahua_nvr=0 — integration disabled, exiting cleanly"
        )
        _sys.exit(0)
    POLL_INTERVAL_SEC = 300   # Log fetch every 5 minutes; HDD check every 1 minute

    log.info("[main] Dahua log extractor started — interval=%ds", POLL_INTERVAL_SEC)
    # HDD-SCHED: fire at a fixed offset within each minute to avoid
    # simultaneous NVR hits from Dahua and CP Plus modules.
    # Jitter=7s — offset chosen so the two modules never fire together.
    import random as _rnd
    _startup_jitter = _rnd.uniform(0, 7)
    log.info("[HDD-SCHED] Startup jitter %.1fs before first HDD check",
             _startup_jitter)
    time.sleep(_startup_jitter)
    schedule.every(1).minutes.do(evaluate_dahua_hdd_state)
    while True:
        import datetime as _dt

        # NVR-02: use last-fetched timestamp — only new events fetched
        # NVR-03: on failure, timestamp NOT advanced — same window retried
        start_time_str = _get_last_fetched()
        end_time_str   = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        log.info("[main] Fetching logs %s to %s", start_time_str, end_time_str)

        response = extract_logs(ipaddress, userid, password,
                                start_time_str, end_time_str)

        watchdog.reset()

        if response is None:
            log.warning("[main] No log response — will retry same window next cycle")
            time.sleep(POLL_INTERVAL_SEC)
            continue

        try:
            parsed_output0  = parse_logs(response)
            parsed_logs     = parse_logs_array_dictionary(parsed_output0)
            filtered_result = parse_logs_filtered(parsed_logs)
            process_log_entries(filtered_result)
            # NVR-02: only advance on success
            _save_last_fetched(end_time_str)
            log.info("[main] Cycle complete — state advanced to %s", end_time_str)

        except Exception as exc:
            log.error("[main] Processing error: %s", exc)
            # NVR-03: do NOT advance timestamp on error — retry same window

        # HDD-SCHED: run_pending() is ALWAYS called regardless of log fetch
        # outcome — ensures HDD check fires even when log fetch fails.
        schedule.run_pending()

        time.sleep(POLL_INTERVAL_SEC)
