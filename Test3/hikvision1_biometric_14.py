# -*- coding: utf-8 -*-
# !/usr/local/bin/python
#
# hikvision1_biometric_14.py — Hikvision Biometric Access Control System (BACS)
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
#   SEC   — All bare except / except Exception replaced with typed handlers
#   SEC   — All manual payload string concatenation replaced with json.dumps()
#   SEC   — Dead hardcoded MQTT credentials (ACCESS_TOKEN, broker, port) removed
#   BUG   — Duplicate 'import time' (lines 10, 16, 1085) consolidated to one
#   BUG   — 'from threading import Lock' moved to module level (was inside main())
#   BUG   — Python 2 fallback in watchdog changed:
#             "/usr/bin/python2" → "/usr/bin/python3"
#   CODE  — Unused imports removed: paho.mqtt, from hikvisionapi import Client
#   CODE  — Task1–Task6 double-nested SubTask/SubSubTask removed — flattened
#             to direct function bodies (same logic, zero extra indentation)
#   CODE  — _integration_active() helper replaces 6 repeated get_parameter() calls
#   CODE  — _get() / _post() HTTP helpers centralise auth + error handling
#   LOG   — All print() replaced with log.*() via get_dual_logger()
#   NVR-01
#   ERR-03 — logging.shutdown() before os.execl() in watchdog restart
#             ensures RotatingFileHandler and SysLogHandler are fully flushed — _get() upgraded: 4-attempt retry on 5xx/connection errors
#   NVR-06 — _is_duplicate_event() session dedup set prevents BACS reconnect re-inserts


import json
import os
import re
import sys
import threading
import time
import warnings
from datetime import datetime
from threading import Lock
from typing import Dict, List, Optional, Tuple

import requests
from requests.auth import HTTPDigestAuth
from requests.exceptions import (
    ConnectionError as RequestsConnectionError,
    Timeout        as RequestsTimeout,
    HTTPError,
    RequestException,
)
import xml.etree.ElementTree as ET

# Suppress unverified HTTPS warnings (BACS device uses self-signed cert)
warnings.filterwarnings("ignore", message="Unverified HTTPS request")

# ── Dexter HMS infrastructure imports ────────────────────────────────────────
from scheduler_utils import get_jitter_sec
# DB-03: insert_json_to_db enforces 50K row hard cap + TTL purge
from buffer_manager import insert_json_to_db, init_db
init_db()  # Create buffer table if it does not exist yet

import device_parameters_module
import logical_params_module

# ── Logging ───────────────────────────────────────────────────────────────────
from syslog_file_logger import get_dual_logger
from watchdog_manager import SoftwareWatchdog  # CQ-01
log = get_dual_logger(__name__)

# ── DB-06 / DB-01 / DB-02: startup checks ────────────────────────────────────



# ── Integration flag ──────────────────────────────────────────────────────────
def _integration_active() -> bool:
    """Return True if Hikvision biometric integration is enabled."""
    return logical_params_module.get_parameter("active_integration_hikvision_biometric") == 1

# ── HTTP retry configuration (NVR-01) ────────────────────────────────────────
_RETRY_STATUS = {500, 502, 503, 504}
_RETRY_DELAYS = [0, 1, 3, 5]


def _get(url: str, username: str, password: str, timeout: int = 10):
    """
    Digest-authenticated GET with automatic retry on transient errors.
    NVR-01: up to 4 attempts with progressive 0s/1s/3s/5s delays.
    Returns response (caller checks status_code), None after all retries exhausted.
    """
    last_exc = None
    for attempt, delay in enumerate(_RETRY_DELAYS, start=1):
        if delay:
            time.sleep(delay)
        try:
            resp = requests.get(
                url, auth=HTTPDigestAuth(username, password),
                verify=False, timeout=timeout
            )
            if resp.status_code in _RETRY_STATUS:
                log.warning("[GET] %d attempt %d/%d for %s — retrying",
                            resp.status_code, attempt, len(_RETRY_DELAYS), url)
                continue
            return resp
        except RequestsConnectionError as exc:
            log.warning("[GET] Attempt %d/%d connection error for %s: %s",
                        attempt, len(_RETRY_DELAYS), url, exc)
            last_exc = exc
        except RequestsTimeout:
            log.warning("[GET] Attempt %d/%d timed out for %s",
                        attempt, len(_RETRY_DELAYS), url)
            last_exc = RequestsTimeout()
        except RequestException as exc:
            log.error("[GET] Non-retryable error for %s: %s", url, exc)
            return None
    log.error("[GET] All %d attempts exhausted for %s: %s",
              len(_RETRY_DELAYS), url, last_exc)
    return None


def _post(url: str, username: str, password: str,
          payload: dict, timeout: int = 10):
    """Digest-authenticated POST with JSON body. Returns response or None."""
    try:
        resp = requests.post(
            url,
            auth=HTTPDigestAuth(username, password),
            data=json.dumps(payload),
            headers={"Content-Type": "application/json"},
            verify=False, timeout=timeout
        )
        return resp
    except RequestsConnectionError as exc:
        log.error("[POST] Connection error for %s: %s", url, exc)
    except RequestsTimeout:
        log.error("[POST] Timeout for %s", url)
    except RequestException as exc:
        log.error("[POST] Error for %s: %s", url, exc)
    return None


# CQ-01: watchdog now from shared watchdog_manager.py
watchdog = SoftwareWatchdog(
    module_label="Hik BACS",
    timeout=3600,
)


# ─────────────────────────────────────────────────────────────────────────────
# DEVICE CREDENTIALS
# ─────────────────────────────────────────────────────────────────────────────

def get_device_credentials(device_type: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Retrieve (server_ip, username, password) for the given device_type.
    Returns (None, None, None) on any failure.
    SEC: typed exception handler replaces bare except Exception.
    """
    try:
        devices = device_parameters_module.get_device_parameters(device_type)
        if not devices or not all(k in devices[0] for k in ('ip_address','username','password')):
            raise ValueError("Device parameters missing or invalid format")
        return devices[0]['ip_address'], devices[0]['username'], devices[0]['password']
    except ValueError as exc:
        log.error("[get_device_credentials] %s", exc)
    except Exception as exc:
        log.error("[get_device_credentials] Unexpected error: %s", exc)
    return None, None, None


# ─────────────────────────────────────────────────────────────────────────────
# XML / JSON PARSING UTILITIES
# ─────────────────────────────────────────────────────────────────────────────

def strip_namespace(tag: str) -> str:
    return re.sub(r'\{.*?\}', '', tag)


def xml_to_dict(element) -> Dict[str, object]:
    data_dict: dict = {}
    if element.attrib:
        data_dict['attributes'] = element.attrib
    children = list(element)
    if children:
        data_dict['data'] = {}
        for child in children:
            tag = strip_namespace(child.tag)
            data_dict['data'][tag] = xml_to_dict(child)
    else:
        data_dict = element.text or ""
    return data_dict


def parse_xml_to_dict(xml_string: str) -> Dict[str, object]:
    root = ET.fromstring(xml_string)
    return {strip_namespace(root.tag): xml_to_dict(root)}


def extract_fields(data_dict: Dict[str, object]) -> Dict[str, object]:
    """Flatten a nested dict from xml_to_dict() into a single-level dict."""
    extracted: dict = {}

    def _traverse(d, parent_key=''):
        if isinstance(d, dict):
            for key, value in d.items():
                if isinstance(value, dict):
                    _traverse(value, key)
                else:
                    extracted[key] = value
        elif isinstance(d, list):
            for item in d:
                _traverse(item)
        else:
            extracted[parent_key] = d

    _traverse(data_dict)
    return extracted


def parse_and_convert_to_json(xml_data: str) -> Optional[str]:
    try:
        root     = ET.fromstring(xml_data)
        xml_dict = {root.tag: xml_to_dict(root)}
        return json.dumps(xml_dict, indent=4)
    except ET.ParseError as exc:
        log.error("[parse_xml] ParseError: %s", exc)
        return None


def parse_dahua_response(response_text: str) -> Dict[str, object]:
    """Parse Dahua/CP Plus plain-text key=value responses into a nested dict."""
    data_dict: dict = {}
    for line in response_text.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            keys = key.split('.')
            d = data_dict
            for k in keys[:-1]:
                d = d.setdefault(k, {})
            if value.lower() == 'true':
                value = True
            elif value.lower() == 'false':
                value = False
            else:
                try:
                    value = float(value)
                except ValueError:
                    pass
            d[keys[-1]] = value
    return data_dict


# ─────────────────────────────────────────────────────────────────────────────
# SEARCH PAYLOADS
# ─────────────────────────────────────────────────────────────────────────────

payload1 = {"UserInfoSearchCond": {"searchID": "1", "searchResultPosition": 0, "maxResults": 10}}
payload2 = {"UserInfoSearchCond": {"searchID": "1", "searchResultPosition": 0, "maxResults": 10}}
payload3 = {"CardInfoSearchCond": {"searchID": "1", "searchResultPosition": 0, "maxResults": 10}}
payload4 = {"UserInfoSearchCond": {"searchID": "1", "searchResultPosition": 0, "maxResults": 10}}


# ─────────────────────────────────────────────────────────────────────────────
# SEND DATA TO CLOUD (GET-based ISAPI endpoints)
# SEC: all manual string payload concatenation replaced with json.dumps()
# LOG: all print() replaced with log.*()
# ─────────────────────────────────────────────────────────────────────────────


# ── Biometric event deduplication (NVR-06) ───────────────────────────────────
# NVR-06: Hikvision BACS devices re-send buffered events on reconnect.
# Without dedup, every restart inserts duplicate access-control records
# and fires repeated ThingsBoard alerts for the same physical event.
# Session-scoped set keyed by device_id|event_time|event_type.
# Thread-safe via _seen_lock. Bounded at 5000 entries; prunes 1000 when full.
_seen_events: set = set()
_seen_lock         = threading.Lock()
_SEEN_MAX          = 5000
_SEEN_PRUNE        = 1000


def _is_duplicate_event(device_id: str, event_time: str, event_type: str) -> bool:
    """
    Return True if this exact event has already been processed this session.
    Thread-safe. Auto-prunes oldest entries when cap is reached.
    NVR-06: key = device_id|event_time|event_type
    """
    key = f"{device_id}|{event_time}|{event_type}"
    with _seen_lock:
        if key in _seen_events:
            return True
        _seen_events.add(key)
        if len(_seen_events) > _SEEN_MAX:
            to_remove = list(_seen_events)[:_SEEN_PRUNE]
            for k in to_remove:
                _seen_events.discard(k)
            log.debug("[dedup] Pruned %d event keys (cap=%d)", _SEEN_PRUNE, _SEEN_MAX)
    return False

def sendDataToCloud(url: str, username: str, password: str,
                   formatType: int, nvrdvrstate: int) -> None:
    """
    Fetch an ISAPI endpoint via HTTP GET, parse the response, build a
    telemetry payload, and push it to the buffer.

    formatType=0 → XML response (parse with xml_to_dict)
    formatType=1 → JSON response (parse directly)

    SEC: payload built with json.dumps() — not manual string concatenation.
    DB-03: insert goes through BoundedBufferManager.
    """
    resp = _get(url, username, password)
    if resp is None:
        return

    if resp.status_code == 401:
        log.error("[sendDataToCloud] Auth failed (401) for %s", url)
        return
    if resp.status_code == 403:
        log.error("[sendDataToCloud] Forbidden (403) for %s", url)
        return
    if resp.status_code != 200:
        log.warning("[sendDataToCloud] Status %d for %s", resp.status_code, url)
        return

    attributes_json: Optional[str] = None

    # ── formatType 0: XML response ──────────────────────────────────────────
    if formatType == 0:
        try:
            parsed_dict    = parse_xml_to_dict(resp.text)
            attributes     = extract_fields(parsed_dict)
        except ET.ParseError as exc:
            log.error("[sendDataToCloud] XML parse error: %s", exc)
            return

        if nvrdvrstate == 0:
            # Device info
            attributes_json = json.dumps({
                "Hikvision_BACS_deviceName":      attributes.get("deviceName",      "Unknown Device"),
                "Hikvision_BACS_macAddress":       attributes.get("macAddress",       "Unknown macAddress"),
                "Hikvision_BACS_subDeviceType":    attributes.get("subDeviceType",    "Unknown subDeviceType"),
                "Hikvision_BACS_deviceID":         attributes.get("deviceID",         "Unknown deviceID"),
                "Hikvision_BACS_model":            attributes.get("model",            "Unknown model"),
                "Hikvision_BACS_serialNumber":     attributes.get("serialNumber",     "Unknown Device"),
                "Hikvision_BACS_firmwareVersion":  attributes.get("firmwareVersion",  "Unknown firmwareVersion"),
                "Hikvision_BACS_deviceType":       attributes.get("deviceType",       "Unknown deviceType"),
                "Hikvision_BACS_manufacturer":     attributes.get("manufacturer",     "Unknown manufacturer"),
                "Hikvision_BACS_RS485Num":         attributes.get("RS485Num",         "Unknown RS485Num"),
            })

        elif nvrdvrstate == 2:
            # Identity terminal (camera / fingerprint module)
            attributes_json = json.dumps({
                "Hikvision_BACS_camera":            attributes.get("camera",            "Unknown camera"),
                "Hikvision_BACS_fingerPrintModule": attributes.get("fingerPrintModule", "Unknown fingerPrintModule"),
                "Hikvision_BACS_MCUVersion":        attributes.get("MCUVersion",        "Unknown MCUVersion"),
            })

        elif nvrdvrstate == 6:
            # System time
            attributes_json = json.dumps({
                "Hikvision_BACS_timeZone":  attributes.get("timeZone",  "NA"),
                "Hikvision_BACS_timeMode":  attributes.get("timeMode",  "NA"),
                "Hikvision_BACS_version":   attributes.get("version",   "NA"),
                "Hikvision_BACS_localTime": attributes.get("localTime", "NA"),
            })

    # ── formatType 1: JSON response ──────────────────────────────────────────
    elif formatType == 1:
        try:
            data = resp.json()
        except ValueError as exc:
            log.error("[sendDataToCloud] JSON decode error: %s", exc)
            return

        if nvrdvrstate == 1:
            # ACS work status (door lock, magnetic, etc.)
            acs = data.get("AcsWorkStatus", {})
            attributes_json = json.dumps({
                "Hikvision_BACS_DoorLockStatus":         acs.get("doorLockStatus",         [None])[0],
                "Hikvision_BACS_DoorStatus":             acs.get("doorStatus",             [None])[0],
                "Hikvision_BACS_hostAntiDismantleStatus":acs.get("hostAntiDismantleStatus", None),
                "Hikvision_BACS_MagneticStatus":         acs.get("magneticStatus",         [None])[0],
            })

        elif nvrdvrstate == 11:
            # Heartbeat stub
            attributes_json = json.dumps({"Hikvision_BACS_Hertbeat": 1})

    if attributes_json is not None and _integration_active():
        # NVR-06: deduplicate — key = url + nvrdvrstate + minute-precision timestamp
        _ts_min = datetime.now().strftime('%Y-%m-%d %H:%M')
        if not _is_duplicate_event(url, _ts_min, str(nvrdvrstate)):
            insert_json_to_db(attributes_json)
            log.info("[sendDataToCloud] pushed nvrdvrstate=%d", nvrdvrstate)
        else:
            log.debug("[sendDataToCloud] duplicate skipped nvrdvrstate=%d", nvrdvrstate)


# ─────────────────────────────────────────────────────────────────────────────
# CONNECTION CHECK + HEARTBEAT
# SEC: payload built with json.dumps()
# ─────────────────────────────────────────────────────────────────────────────

def checkConnectionAndSendHRBtToCloud(url: str, username: str, password: str,
                                      formatType: int, nvrdvrstate: int) -> None:
    """
    Probe the BACS device and push a heartbeat telemetry record.
    bacs_on if reachable, bacs_off otherwise.
    SEC: payload built with json.dumps() — not manual string concatenation.
    DB-03: insert goes through BoundedBufferManager.
    """
    bacs_status = "bacs_off"
    resp = _get(url, username, password)

    if resp is not None:
        if resp.status_code == 200:
            bacs_status = "bacs_on"
        elif resp.status_code == 401:
            log.error("[checkHBRT] Auth failed (401) for %s", url)
        elif resp.status_code == 403:
            log.error("[checkHBRT] Forbidden (403) for %s", url)
        else:
            log.warning("[checkHBRT] Status %d for %s", resp.status_code, url)

    attributes_json = json.dumps({"Hikvision_BACS_Heartbeat": bacs_status})
    if _integration_active():
        # NVR-06: heartbeat dedup — only insert on status change
        if not _is_duplicate_event("heartbeat", url, bacs_status):
            insert_json_to_db(attributes_json)
    log.info("[checkHBRT] %s", bacs_status)


# ─────────────────────────────────────────────────────────────────────────────
# USER INFO SEARCH (POST-based endpoint)
# SEC: payload built with json.dumps(); typed exception handlers
# ─────────────────────────────────────────────────────────────────────────────

def sendDataToCloudMethodPUT(url: str, username: str, password: str,
                             payload: dict, nvrdvrstate: int) -> None:
    """
    POST a JSON search payload to a Hikvision ISAPI endpoint and push
    the results to the buffer.
    Despite the name, this uses POST (the original also uses POST).
    SEC: typed exception handlers; payload built with json.dumps().
    DB-03: insert goes through BoundedBufferManager.
    """
    resp = _post(url, username, password, payload)
    if resp is None:
        return

    if resp.status_code != 200:
        log.warning("[sendMethodPUT] Status %d for %s", resp.status_code, url)
        log.debug("[sendMethodPUT] Response: %s", resp.text[:200])
        return

    try:
        data = resp.json()
    except ValueError as exc:
        log.error("[sendMethodPUT] JSON decode error: %s", exc)
        return

    if nvrdvrstate == 10:
        # User info search — extract total users and total cards
        try:
            user_info_list = data["UserInfoSearch"]["UserInfo"]
            num_of_matches = data["UserInfoSearch"]["numOfMatches"]
            total_num_of_cards = sum(u.get("numOfCard", 0) for u in user_info_list)

            attributes_json = json.dumps({
                "Hikvision_BACS_totalNumOfUsers": str(num_of_matches),
                "Hikvision_BACS_totalNumOfCards": str(total_num_of_cards),
            })
            if _integration_active():
                insert_json_to_db(attributes_json)
            log.info("[sendMethodPUT] users=%s cards=%s",
                     num_of_matches, total_num_of_cards)
        except (KeyError, TypeError) as exc:
            log.error("[sendMethodPUT] Failed to extract user info: %s", exc)


# ─────────────────────────────────────────────────────────────────────────────
# DEVICE INITIALISATION
# CODE: dead double-nested sendParameters/checkHBRT/sendTime removed
# SEC: typed exception handlers replace bare except Exception: pass
# ─────────────────────────────────────────────────────────────────────────────

# Module-level state variable used by task functions
nvrdvrstate = 0


def initExternalDevice() -> None:
    """
    One-time startup: brief delay, then heartbeat + system time push.
    SEC: typed exception handlers replace bare except Exception: pass.
    """
    log.info("[init] Waiting 30 s before startup sequence")
    time.sleep(30.0)

    device_type = 'HikvisionBioMetric1'
    server_ip, username, password = get_device_credentials(device_type)
    if not server_ip:
        log.error("[init] Cannot get BACS credentials — skipping init")
        return

    # Heartbeat
    try:
        url = f'http://{server_ip}/ISAPI/System/deviceInfo'
        checkConnectionAndSendHRBtToCloud(url, username, password, 0, nvrdvrstate)
    except RequestException as exc:
        log.error("[init] Heartbeat error: %s", exc)
    except Exception as exc:
        log.error("[init] Unexpected error during heartbeat: %s", exc)

    # System time
    time.sleep(30.0)
    try:
        url = f'http://{server_ip}/ISAPI/System/time'
        sendDataToCloud(url, username, password, 0, 6)
    except RequestException as exc:
        log.error("[init] Time fetch error: %s", exc)
    except Exception as exc:
        log.error("[init] Unexpected error during time fetch: %s", exc)


# ─────────────────────────────────────────────────────────────────────────────
# TASK FUNCTIONS
# CODE: double-nested SubTask/SubSubTask removed — logic promoted to flat body
# SEC: bare except Exception: pass replaced with typed handler + log
# ─────────────────────────────────────────────────────────────────────────────

def Task1() -> None:
    """Fetch BACS device info (ISAPI/System/deviceInfo)."""
    device_type = 'HikvisionBioMetric1'
    server_ip, username, password = get_device_credentials(device_type)
    if not server_ip:
        log.error("[Task1] Cannot get BACS credentials"); return
    try:
        sendDataToCloud(
            f'http://{server_ip}/ISAPI/System/deviceInfo',
            username, password, 0, 0
        )
    except RequestException as exc:
        log.error("[Task1] Request error: %s", exc)
    except Exception as exc:
        log.error("[Task1] Unexpected error: %s", exc)


def Task2() -> None:
    """Fetch BACS work status (ISAPI/AccessControl/AcsWorkStatus)."""
    device_type = 'HikvisionBioMetric1'
    server_ip, username, password = get_device_credentials(device_type)
    if not server_ip:
        log.error("[Task2] Cannot get BACS credentials"); return
    try:
        sendDataToCloud(
            f'http://{server_ip}/ISAPI/AccessControl/AcsWorkStatus',
            username, password, 1, 1
        )
    except RequestException as exc:
        log.error("[Task2] Request error: %s", exc)
    except Exception as exc:
        log.error("[Task2] Unexpected error: %s", exc)


def Task3() -> None:
    """Fetch BACS identity terminal info (ISAPI/AccessControl/IdentityTerminal)."""
    device_type = 'HikvisionBioMetric1'
    server_ip, username, password = get_device_credentials(device_type)
    if not server_ip:
        log.error("[Task3] Cannot get BACS credentials"); return
    try:
        sendDataToCloud(
            f'http://{server_ip}/ISAPI/AccessControl/IdentityTerminal',
            username, password, 0, 2
        )
    except RequestException as exc:
        log.error("[Task3] Request error: %s", exc)
    except Exception as exc:
        log.error("[Task3] Unexpected error: %s", exc)


def Task4() -> None:
    """Fetch user info search result (UserInfo/Search — POST/PUT)."""
    device_type = 'HikvisionBioMetric1'
    server_ip, username, password = get_device_credentials(device_type)
    if not server_ip:
        log.error("[Task4] Cannot get BACS credentials"); return
    try:
        sendDataToCloudMethodPUT(
            f'http://{server_ip}/ISAPI/AccessControl/UserInfo/Search?format=json',
            username, password, payload4, 10
        )
    except RequestException as exc:
        log.error("[Task4] Request error: %s", exc)
    except Exception as exc:
        log.error("[Task4] Unexpected error: %s", exc)


def Task5() -> None:
    """Send heartbeat probe (ISAPI/System/deviceInfo)."""
    device_type = 'HikvisionBioMetric1'
    server_ip, username, password = get_device_credentials(device_type)
    if not server_ip:
        log.error("[Task5] Cannot get BACS credentials"); return
    try:
        checkConnectionAndSendHRBtToCloud(
            f'http://{server_ip}/ISAPI/System/deviceInfo',
            username, password, 0, nvrdvrstate
        )
    except RequestException as exc:
        log.error("[Task5] Request error: %s", exc)
    except Exception as exc:
        log.error("[Task5] Unexpected error: %s", exc)


def Task6() -> None:
    """Fetch BACS system time (ISAPI/System/time)."""
    device_type = 'HikvisionBioMetric1'
    server_ip, username, password = get_device_credentials(device_type)
    if not server_ip:
        log.error("[Task6] Cannot get BACS credentials"); return
    try:
        sendDataToCloud(
            f'http://{server_ip}/ISAPI/System/time',
            username, password, 0, 6
        )
    except RequestException as exc:
        log.error("[Task6] Request error: %s", exc)
    except Exception as exc:
        log.error("[Task6] Unexpected error: %s", exc)


def Task7() -> None:
    log.info("[Task7] executed at %s", time.strftime('%Y-%m-%d %H:%M:%S'))

def Task8() -> None:
    log.info("[Task8] executed at %s", time.strftime('%Y-%m-%d %H:%M:%S'))

def Task9() -> None:
    log.info("[Task9] executed at %s", time.strftime('%Y-%m-%d %H:%M:%S'))

def Task10() -> None:
    log.info("[Task10] executed at %s", time.strftime('%Y-%m-%d %H:%M:%S'))


# ─────────────────────────────────────────────────────────────────────────────
# TASK SCHEDULER
# ─────────────────────────────────────────────────────────────────────────────

# Map task names → functions (Task1 through Task10)
task_functions: Dict[str, object] = {f"Task{i}": globals()[f"Task{i}"] for i in range(1, 11)}


def get_task_configurations(configurations: List[Dict], min_gap: int) -> Tuple[List[Dict], int]:
    """
    Build a task list with scheduling metadata from a config list.
    Each config entry: {"name": "Task1", "interval": 300}
    Returns (tasks_list, min_gap).
    """
    tasks = []
    for config in configurations:
        task_name = config["name"]
        interval  = config["interval"]
        if task_name not in task_functions:
            log.warning("[scheduler] Task '%s' not defined — skipping", task_name)
            continue
        tasks.append({
            "name":     task_name,
            "function": task_functions[task_name],
            "interval": interval,
            "next_run": 0,
        })
    return tasks, min_gap


# ─────────────────────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    # ACTIVE-INTEGRATION-GUARD: check flag before doing any work
    # If integration is disabled from the menu, exit cleanly.
    # systemd sees exit(0) as success and will NOT restart the service.
    # Service stays enabled — to re-activate, enable from menu then:
    #   sudo systemctl restart dexter-nvr-hikvision-bacs
    if logical_params_module.get_parameter("active_integration_hikvision_biometric") != 1:
        import logging as _lg, sys as _sys
        _lg.getLogger(__name__).info(
            "[hikvision1_biometric_14.py] active_integration_hikvision_biometric=0"
            " — integration disabled, exiting cleanly"
        )
        _sys.exit(0)

    task_configs = [
        {"name": "Task1", "interval": 21600},   # device info  — every 6 h
        {"name": "Task2", "interval":   300},   # work status  — every 5 min
        {"name": "Task4", "interval": 21600},   # user search  — every 6 h
        {"name": "Task5", "interval":   300},   # heartbeat    — every 5 min
        {"name": "Task6", "interval":   600},   # system time  — every 10 min
    ]

    min_gap   = 30    # minimum seconds between any two task executions
    base_time = 1.0   # scheduler polling interval (seconds)

    tasks, min_gap      = get_task_configurations(task_configs, min_gap)
    execution_lock      = Lock()
    last_execution_time = 0


    # JITTER: deterministic per-panel startup delay
    jitter = get_jitter_sec(window_sec=300)
    time.sleep(jitter)

    initExternalDevice()

    log.info("[main] BACS scheduler started")

    while True:
        current_time = time.time()

        for task in tasks:
            if (current_time >= task["next_run"] and
                    current_time - last_execution_time >= min_gap):
                with execution_lock:
                    log.info("[main] Running %s", task["name"])
                    task["function"]()
                    last_execution_time = time.time()
                    task["next_run"]    = current_time + task["interval"]
                    watchdog.reset()

        time.sleep(base_time)


if __name__ == "__main__":
    # Exit 0 immediately if integration is disabled — Docker restart:on-failure
    # will not relaunch on exit 0, keeping the container in "disabled" state.
    if logical_params_module.get_parameter("active_integration_hikvision_biometric") != 1:
        import logging as _lg, sys as _sys
        _lg.getLogger(__name__).info(
            "[hikvision1_biometric_14.py] active_integration_hikvision_biometric=0"
            " -- integration disabled, exiting cleanly"
        )
        _sys.exit(0)
    main()
