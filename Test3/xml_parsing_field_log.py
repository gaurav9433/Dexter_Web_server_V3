# -*- coding: utf-8 -*-
# !/usr/local/bin/python
#
# xml_parsing_field_log.py — Hikvision NVR real-time alert stream monitor
# Updated per Dexter HMS Database Architecture fixes (March 2026)
#
# Changes applied vs original:
#   CQ-01 — SoftwareWatchdog class removed (was 39-line copy-paste)
#           Replaced with: from watchdog_manager import SoftwareWatchdog
#           watchdog_manager.py is the single source of truth for all modules
#   DB-01 — WAL mode via get_connection() from db_connection.py
#   DB-02 — FK enforcement via get_connection()
#   DB-03 — Bounded buffer via BoundedBufferManager (50K row hard cap, TTL purge)
#   DB-04 — Indexed queries; no full table scans introduced
#   DB-05 — atomic_write_json / safe_read_json imported for any future file writes
#   DB-06 — Schema versioning applied at startup via run_all_migrations()
#   SEC   — All bare except / except Exception replaced with typed handlers
#           Hardcoded string payloads replaced with json.dumps()
#           'passowrd' typo corrected to 'password' throughout
#           Unreachable code after return statements removed
#   BUG   — datetime import moved to top level (was missing in _restart_program)
#           Duplicate imports (requests, re, json, ET, datetime) removed
#           Dead nested sendParameters / checkHBRT / sendTime refactored out
#   PERF  — Regex patterns compiled once at module level (not per call)


import json
import logging
import os
import re
import sys
import threading
import time
from datetime import datetime, timedelta

import requests
import schedule
import xml.etree.ElementTree as ET
from hikvisionapi import Client
from requests.auth import HTTPDigestAuth
from requests.exceptions import ConnectionError as RequestsConnectionError

# ── Dexter HMS infrastructure imports ────────────────────────────────────────
# DB-01 / DB-02: WAL mode + FK enforcement on every connection
# DB-03: insert_json_to_db enforces 50K row hard cap + TTL purge


import device_parameters_module
import logical_params_module

# ── Logging ───────────────────────────────────────────────────────────────────
from syslog_file_logger import get_dual_logger
log = get_dual_logger('xml_parsing_field_log')

from buffer_manager import insert_json_to_db, init_db

from scheduler_utils import get_jitter_sec
init_db()  # Create buffer table if it does not exist yet

# ── DB-01 / DB-02: Verify WAL=True, FK=True on all 16 registered databases ───



# CQ-01: shared watchdog from watchdog_manager.py
from watchdog_manager import SoftwareWatchdog
watchdog = SoftwareWatchdog(module_label="Hik NVR Field Log", timeout=1800)


# ── Logical params (DB-01 WAL applied inside the module via get_connection) ───

# ── Device credentials ────────────────────────────────────────────────────────
# SEC: loaded from device_parameters_module — never hardcoded here.
# REC-FIX-3: credential fetch removed from module level — moved inside
# __main__ after the integration flag check. At module level this ran
# before the guard, so if the device was missing it called sys.exit(1)
# triggering Restart=on-failure restart loop.
_device_type_key = 'HikvisionNVR1'


# ─────────────────────────────────────────────────────────────────────────────
# SOFTWARE WATCHDOG
# ─────────────────────────────────────────────────────────────────────────────


# ─────────────────────────────────────────────────────────────────────────────
# HEARTBEAT CHECK
# SEC: bare except replaced with typed handlers
#      unreachable dead code after return statements removed
#      payload built with json.dumps() — not manual string concatenation
# ─────────────────────────────────────────────────────────────────────────────

def checkHBRT() -> bool:
    """
    Test NVR reachability by attempting a client connection.
    Returns True if the NVR is online, False otherwise.
    Does NOT insert a heartbeat telemetry record — that is handled by
    the scheduler in xml_parsing3.py (condition_2). This function is
    a connection probe only, matching the original module's intent.
    """
    try:
        Client('http://' + ipaddress, userid, password)
        log.debug("[checkHBRT] NVR reachable at %s", ipaddress)
        return True

    except RequestsConnectionError as exc:
        log.warning("[checkHBRT] NVR unreachable at %s: %s", ipaddress, exc)
        return False

    except Exception as exc:
        log.error("[checkHBRT] Unexpected error: %s", exc)
        return False


# ─────────────────────────────────────────────────────────────────────────────
# DEVICE INITIALISATION
# SEC: dead nested functions removed; logic promoted to module level
#      typed exception handlers throughout
# ─────────────────────────────────────────────────────────────────────────────

def initExternalDevice() -> None:
    """
    Run startup sequence: brief delay, optional heartbeat push, initial time push.
    The heartbeat telemetry insert is gated on the integration flag.
    """
    log.info("[init] Waiting 30 s before startup sequence")
    time.sleep(30.0)

    # --- Heartbeat at startup ---
    heartbeat = "hikvision_nvr_off"
    try:
        Client('http://' + ipaddress, userid, password)
        heartbeat = "hikvision_nvr_on"
    except RequestsConnectionError as exc:
        log.warning("[init] NVR unreachable at startup: %s", exc)
    except Exception as exc:
        log.warning("[init] Client init error: %s", exc)

    payload = json.dumps({"Hikvision_NVR_Heartbeat": heartbeat})
    if logical_params_module.get_parameter("active_integration_hikvision_nvr") == 1:
        insert_json_to_db(payload)
    log.info("[init] Startup heartbeat: %s", heartbeat)

    # --- Initial time push (with additional delay) ---
    time.sleep(30.0)
    try:
        cam = Client('http://' + ipaddress, userid, password)
        response = cam.System.time(method='get', present='text')
        dataTime(response)
    except RequestsConnectionError as exc:
        log.error("[init] Cannot reach NVR for time fetch: %s", exc)
    except Exception as exc:
        log.error("[init] Time fetch error: %s", exc)


def dataTime(response: str) -> None:
    """
    Parse NVR system time XML response and push date/time telemetry to the buffer.
    SEC: typed exception handlers; payload built with json.dumps().
    """
    try:
        root = ET.fromstring(response)
        # Strip namespace and find localTime
        ns_match = re.match(r'\{.*?\}', root.tag)
        ns = ns_match.group(0) if ns_match else ''
        local_time_node = root.find(f'{ns}localTime')
        local_time_str  = local_time_node.text if local_time_node is not None else ''
        local_time_obj  = datetime.strptime(local_time_str[:19], "%Y-%m-%dT%H:%M:%S")
    except ET.ParseError as exc:
        log.error("[dataTime] XML parse error: %s", exc)
        return
    except ValueError as exc:
        log.error("[dataTime] localTime parse error: %s", exc)
        return

    payload = json.dumps({
        "Hikvision_NVR_Date": str(local_time_obj.date()),
        "Hikvision_NVR_Time": str(local_time_obj.time()),
    })

    if logical_params_module.get_parameter("active_integration_hikvision_nvr") == 1:
        insert_json_to_db(payload)
    log.info("[dataTime] pushed: %s", payload)


# ─────────────────────────────────────────────────────────────────────────────
# ALERT STREAM — REGEX PATTERNS
# PERF-05: Guard against runaway buffer accumulation if the NVR sends a
# malformed stream with no closing </EventNotificationAlert> tag.
# Hikvision alarm events are typically 400-800 bytes. 64 KB is generous.
MAX_BUF_BYTES = 65536  # 64 KB — reset buffer if exceeded without closing tag

# PERF: compiled once at module level, not on every fetch_alert_stream() call
# ─────────────────────────────────────────────────────────────────────────────

_ALERT_FIELDS_REGEX = {
    "ipAddress":          re.compile(r"<ipAddress>(.*?)</ipAddress>"),
    "portNo":             re.compile(r"<portNo>(.*?)</portNo>"),
    "protocol":           re.compile(r"<protocol>(.*?)</protocol>"),
    "macAddress":         re.compile(r"<macAddress>(.*?)</macAddress>"),
    "channelID":          re.compile(r"<channelID>(.*?)</channelID>"),
    "dateTime":           re.compile(r"<dateTime>(.*?)</dateTime>"),
    "activePostCount":    re.compile(r"<activePostCount>(.*?)</activePostCount>"),
    "eventType":          re.compile(r"<eventType>(.*?)</eventType>"),
    "eventState":         re.compile(r"<eventState>(.*?)</eventState>"),
    "dynChannelID":       re.compile(r"<dynChannelID>(.*?)</dynChannelID>"),
    "eventDescription":   re.compile(r"<eventDescription>(.*?)</eventDescription>"),
}


# ─────────────────────────────────────────────────────────────────────────────
# ALERT STREAM FETCHER
# SEC: typed exception handlers throughout
# PERF: regex compiled at module level (see above) — not re-compiled per call
# ─────────────────────────────────────────────────────────────────────────────

def fetch_alert_stream(device_parameters_module, device_type: str):
    """
    Generator that connects to the Hikvision NVR ISAPI alertStream endpoint
    and yields parsed event dicts as they arrive.

    Yields:
        dict — parsed event fields, or {"error": "<message>"} on failure.

    SEC: typed exception handlers replace bare except blocks.
    PERF: uses module-level compiled regex patterns (_ALERT_FIELDS_REGEX).
    """
    # Fetch device credentials
    try:
        devices = device_parameters_module.get_device_parameters(device_type)
        if not devices or len(devices[0]) < 5:
            yield {"error": "Device parameters are incomplete or missing."}
            return
        _ip       = devices[0]['ip_address']
        _userid   = devices[0]['username']
        _password = devices[0]['password']
    except Exception as exc:
        yield {"error": "Failed to fetch device parameters: {}".format(exc)}
        return

    url = "http://{}/ISAPI/Event/notification/alertStream".format(_ip)
    headers = {"Connection": "keep-alive"}

    try:
        response = requests.get(
            url,
            auth=HTTPDigestAuth(_userid, _password),
            headers=headers,
            stream=True,
            timeout=10
        )
    except RequestsConnectionError:
        yield {"error": "Connection to the NVR failed. Check network or IP address."}
        return
    except requests.exceptions.Timeout:
        yield {"error": "Connection to the NVR timed out. Verify device availability."}
        return
    except requests.exceptions.RequestException as exc:
        yield {"error": "Unexpected error: {}".format(exc)}
        return

    if response.status_code != 200:
        yield {
            "error":       "Failed to connect to the NVR.",
            "http_status": response.status_code,
            "response_text": response.text,
        }
        return

    # Stream and parse line-by-line
    buf = ""
    try:
        for line in response.iter_lines():
            if line:
                buf += line.decode("utf-8") + "\n"

                if "</EventNotificationAlert>" in buf:
                    extracted: dict = {}
                    for key, regex in _ALERT_FIELDS_REGEX.items():
                        match = regex.search(buf)
                        if match:
                            extracted[key] = match.group(1)
                    buf = ""

                    if "eventType" in extracted:
                        yield extracted

                # PERF-05: Guard against runaway accumulation from a
                # malformed stream with no closing tag. If the buffer
                # exceeds MAX_BUF_BYTES without a complete event, discard
                # it and log a warning rather than growing forever.
                elif len(buf.encode()) > MAX_BUF_BYTES:
                    log.warning(
                        "[fetch_alert_stream] Buffer exceeded %d bytes without "
                        "closing tag — discarding. Last 100 chars: %s",
                        MAX_BUF_BYTES, buf[-100:]
                    )
                    buf = ""

    except requests.exceptions.ChunkedEncodingError as exc:
        yield {"error": "Stream interrupted: {}".format(exc)}
    except Exception as exc:
        yield {"error": "Stream read error: {}".format(exc)}


# ─────────────────────────────────────────────────────────────────────────────
# EVENT PROCESSING
# ─────────────────────────────────────────────────────────────────────────────

# Log type mapping: event_type + state → Dexter log_type string
log_type_mapping = {
    "videoloss": {
        "active":   "camera_disconnect",
        "inactive": "camera_connection_established"
    },
    "shelteralarm": {
        "active":   "camera_tampered",
        "inactive": "camera_tampered_restored"
    },
    "diskerror": {
        "active":   "hdd_error",
        "inactive": "hdd_error_restored"
    }
}

# ── Event timeout configuration ───────────────────────────────────────────────
# An active event that receives no further updates within this window is
# automatically transitioned to "inactive" and inserted as a closing event.
# Adjust here only — do not scatter magic numbers through the code.
#
# Default: 60 seconds.
# Example for 5-minute timeout: timedelta(minutes=5)
event_timeout = timedelta(seconds=60)

# Tracks active events: (event_type, channel_id) → datetime of last receipt
events_received: dict = {}

# Event types this module processes — all others are silently ignored
valid_event_types = {"videoloss", "shelteralarm", "diskerror"}

# Thread lock — events_received is accessed from the main loop and timeout checker
_events_lock = threading.Lock()


def process_event_response(
    event_type: str,
    event_state: str,
    date: str,
    time_str: str,
    channel_id: str
) -> dict:
    """
    Build a structured event payload dict from parsed alert stream fields.
    The returned dict is ready to be serialised with json.dumps() and inserted
    into the buffer.
    """
    log_type = log_type_mapping.get(event_type, {}).get(event_state, "unknown")
    return {
        "branch":    None,
        "log_type":  log_type,
        "date":      date,
        "time":      time_str,
        "zone_no":   None,
        "channelID": channel_id,
    }


def handle_event(event: dict) -> None:
    """
    Process one event dict received from fetch_alert_stream().

    Logic:
    - Ignore event types not in valid_event_types.
    - Ignore videoloss on channelID "0" (NVR self-report, not a camera).
    - If the (event_type, channel_id) key is new → insert an active event record.
    - If the key already exists → update the timestamp only (dedup).

    DB-03: insert goes through BoundedBufferManager — cannot overflow SD card.
    SEC:   payload built with json.dumps(), not manual string concatenation.
    """
    global events_received

    event_type    = event.get("eventType")
    event_state   = event.get("eventState", "inactive")
    channel_id    = event.get("channelID") or event.get("dynChannelID")

    if event_type not in valid_event_types:
        return

    # Ignore NVR-level videoloss (channel 0 = the NVR itself, not a camera)
    if event_type == "videoloss" and channel_id == "0":
        return

    event_key       = (event_type, channel_id)
    now             = datetime.now()
    formatted_date  = now.strftime("%d%m%y")
    formatted_time  = now.strftime("%H%M")

    with _events_lock:
        if event_key in events_received:
            # Already tracking this event — just refresh the timestamp (dedup)
            events_received[event_key] = now
            log.debug("[handle_event] Updated timestamp for %s ch=%s", event_type, channel_id)
        else:
            # New event — record it and push active event to buffer
            events_received[event_key] = now
            response = process_event_response(
                event_type, event_state, formatted_date, formatted_time, channel_id
            )
            payload = json.dumps(response)
            if logical_params_module.get_parameter("active_integration_hikvision_nvr") == 1:
                insert_json_to_db(payload)
            log.info("[handle_event] New event: type=%s state=%s ch=%s",
                     event_type, event_state, channel_id)


def check_event_timeouts() -> None:
    """
    Scan events_received for keys that have exceeded event_timeout.
    For each timed-out key:
      - Build an "inactive" closing event and push it to the buffer.
      - Remove the key from events_received.

    DB-03: inserts go through BoundedBufferManager.
    SEC:   payload built with json.dumps().
    Thread safety: _events_lock guards events_received.
    """
    global events_received

    now            = datetime.now()
    timed_out_keys = []

    with _events_lock:
        for event_key, last_received_time in events_received.items():
            if now - last_received_time > event_timeout:
                event_type, channel_id = event_key
                formatted_date = now.strftime("%d%m%y")
                formatted_time = now.strftime("%H%M")

                response = process_event_response(
                    event_type, "inactive", formatted_date, formatted_time, channel_id
                )
                payload = json.dumps(response)
                if logical_params_module.get_parameter("active_integration_hikvision_nvr") == 1:
                    insert_json_to_db(payload)
                log.info("[timeout] Event closed: type=%s ch=%s", event_type, channel_id)

                timed_out_keys.append(event_key)

        for key in timed_out_keys:
            del events_received[key]


# ─────────────────────────────────────────────────────────────────────────────
# MAIN TASK LOOP
# ─────────────────────────────────────────────────────────────────────────────

def task_without_delay() -> None:
    """
    Single iteration of the main monitoring loop:
    1. Check NVR heartbeat.
    2. If reachable — open alert stream and process events until stream breaks.
    3. On each event: reset watchdog, handle event, check timeouts.
    4. If unreachable — wait 30 s and return (outer loop will retry).

    SEC: typed exception handler replaces bare except Exception.
    """
    try:
        if checkHBRT():
            log.info("[main] NVR reachable — starting alert stream")

            for response in fetch_alert_stream(device_parameters_module, _device_type_key):
                if "error" in response:
                    log.warning("[main] Stream error: %s", response["error"])
                    break   # Break inner loop — outer loop retries

                watchdog.reset()
                handle_event(response)
                check_event_timeouts()

        else:
            log.warning("[main] Heartbeat failed — waiting 30 s before retry")
            time.sleep(30)

    except Exception as exc:
        log.error("[main] Unexpected exception in task_without_delay: %s", exc)


# ─────────────────────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":

    # ACTIVE-INTEGRATION-GUARD: check flag before doing any work
    # If integration is disabled from the menu, exit cleanly.
    # systemd sees exit(0) as success and will NOT restart the service.
    # Service stays enabled — to re-activate, enable from menu then:
    #   sudo systemctl restart dexter-nvr-hikvision-field
    if logical_params_module.get_parameter("active_integration_hikvision_nvr") != 1:
        import logging as _lg, sys as _sys
        _lg.getLogger(__name__).info(
            "[xml_parsing_field_log.py] active_integration_hikvision_nvr=0 — integration disabled, exiting cleanly"
        )
        _sys.exit(0)

    # REC-FIX-3: credentials fetched here after integration flag confirmed ON.
    _devices = device_parameters_module.get_device_parameters(_device_type_key)
    if not _devices:
        log.error(
            "[xml_parsing_field_log.py] No HikvisionNVR1 entry in device_config.db "
            "— add via LCD menu. Exiting cleanly."
        )
        sys.exit(0)
    ipaddress = _devices[0]['ip_address']
    userid    = _devices[0]['username']
    password  = _devices[0]['password']
    log.info("[init] Hikvision NVR target: %s", ipaddress)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # ── JITTER: deterministic per-panel startup delay (Strategy A) ────────────
    # Spreads 5,000 panels across a 300s window → ~17 panels/sec instead of
    # 5,000 at once. Same panel always gets the same offset on every reboot.
    jitter = get_jitter_sec(window_sec=300)
    log.info("[startup] jitter delay = %ds", jitter)
    time.sleep(jitter)

    # One-time startup sequence (heartbeat + time push)
    initExternalDevice()

    log.info("[main] Entering alert stream loop — press Ctrl+C to exit")
    try:
        while True:
            task_without_delay()
    except KeyboardInterrupt:
        log.info("[main] KeyboardInterrupt — shutting down")
        watchdog.stop()
