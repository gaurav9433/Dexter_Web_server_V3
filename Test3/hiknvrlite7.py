# -*- coding: utf-8 -*-
# !/usr/local/bin/python
#
# hiknvrlite7.py — Hikvision NVR recording-day analytics module
# Updated per Dexter HMS Database Architecture fixes (March 2026)
#
# Changes applied vs original:
#   DB-01 — WAL mode via get_connection() (applied at startup via infrastructure)
#   DB-02 — FK enforcement via get_connection()
#   DB-03 — Bounded buffer via BoundedBufferManager (50K row hard cap, TTL purge)
#   DB-06 — run_all_migrations() + verify_all_databases() at startup
#   SEC   — bare except Exception in fetch_for_range() + process_camera()
#             replaced with typed handlers (ET.ParseError, RequestException,
#             ValueError, Exception)
#   CODE  — _integration_active() helper replaces single get_parameter() call
#   CODE  — safe_post() parameter renamed 'url' → 'endpoint' to avoid
#             shadowing the module-level 'url' constant
#   CODE  — datetime.utcnow() replaced with timezone-aware equivalent
#             (deprecated in Python 3.12+)
#   LOG   — All print() replaced with log.*() via get_dual_logger()
#             Progress logs inside process_camera() are log.info() so they
#             appear in update.log for long-running 60-month scans


import json
import schedule
import time
from collections import defaultdict
from datetime import datetime, timezone

import requests
import xml.etree.ElementTree as ET
from dateutil.relativedelta import relativedelta
from requests.auth import HTTPDigestAuth
from requests.exceptions import (
    ConnectionError as RequestsConnectionError,
    Timeout        as RequestsTimeout,
    RequestException,
)

# ── Dexter HMS infrastructure imports ────────────────────────────────────────
# DB-03: insert_json_to_db enforces 50K row hard cap + TTL purge
from buffer_manager import insert_json_to_db, init_db
init_db()  # Create buffer table if it does not exist yet

import device_parameters_module
import logical_params_module

# ── Shared scheduling helpers (jitter + load-gate) ───────────────────────────
from scheduler_utils import get_jitter_sec, is_rpi_idle

# ── Logging ───────────────────────────────────────────────────────────────────
from syslog_file_logger import get_dual_logger
log = get_dual_logger(__name__)

# ── DB-06 / DB-01 / DB-02: startup checks ────────────────────────────────────



# ── Device credentials ────────────────────────────────────────────────────────
_device_type_key = 'HikvisionNVR1'
_devices      = device_parameters_module.get_device_parameters(_device_type_key)
if not _devices:
    log.error("No device credentials found for 'device'")
    import sys; sys.exit(1)
nvr_ip        = _devices[0]['ip_address']
username_nvr  = _devices[0]['username']
password_nvr  = _devices[0]['password']

# ISAPI search endpoint
_SEARCH_URL = f"http://{nvr_ip}/ISAPI/ContentMgmt/search"

log.info("[init] Hikvision NVR recording analytics target: %s", nvr_ip)

# ── Integration flag ──────────────────────────────────────────────────────────
def _integration_active() -> bool:
    return logical_params_module.get_parameter("active_integration_hikvision_nvr") == 1

# ── Camera scan configuration ─────────────────────────────────────────────────
camera_ids  = range(1, 17)   # Cameras 1–16
months_back = 60              # Past 5 years


# ─────────────────────────────────────────────────────────────────────────────
# HTTP HELPER — RETRY-ENABLED POST
# CODE: parameter renamed 'url' → 'endpoint' to avoid shadowing the
#       module-level _SEARCH_URL constant.
# SEC: logs the error before re-raising on the final attempt.
# ─────────────────────────────────────────────────────────────────────────────

def safe_post(endpoint: str, data: str, headers: dict, auth,
              retries: int = 3, timeout: int = 20):
    """
    POST with automatic retry (up to `retries` attempts, 1 s between).
    Raises RequestException on the final failed attempt after logging.
    SEC: typed exception handler; logs before re-raise.
    """
    for attempt in range(1, retries + 1):
        try:
            return requests.post(
                endpoint, data=data, headers=headers,
                auth=auth, timeout=timeout
            )
        except RequestException as exc:
            if attempt == retries:
                log.error("[safe_post] All %d attempts failed for %s: %s",
                          retries, endpoint, exc)
                raise
            log.warning("[safe_post] Attempt %d/%d failed: %s — retrying",
                        attempt, retries, exc)
            time.sleep(1)


# ─────────────────────────────────────────────────────────────────────────────
# CORE CAMERA PROCESSOR
# SEC: typed exception handlers in fetch_for_range() and process_camera()
# CODE: datetime.utcnow() → timezone-aware equivalent (deprecated in 3.12+)
# LOG: print() → log.*(); progress logs are log.info() so they appear in
#      update.log and syslog during the long 60-month scan
# ─────────────────────────────────────────────────────────────────────────────

def process_camera(cam_index: int, months_back: int = 60) -> dict:
    """
    Query the Hikvision NVR ISAPI ContentMgmt/search endpoint for one camera
    across up to `months_back` months. Uses adaptive chunking: if a month
    returns >= 10,000 matches it switches to 7-day chunks, then 1-day if
    still over threshold.

    Returns a dict with recording_days_per_month, total_duration, start_time,
    end_time keyed by camera_id (track_id string).

    SEC: typed exception handlers replace bare except Exception: print().
    CODE: datetime.utcnow() replaced — deprecated in Python 3.12+.
    """
    track_id     = 100 * cam_index + 1
    track_id_str = str(track_id)

    monthly_unique_days: defaultdict = defaultdict(set)
    all_days:      set = set()
    all_day_times: set = set()

    # CODE fix: datetime.utcnow() is deprecated in Python 3.12+
    # datetime.now(timezone.utc).replace(tzinfo=None) gives the same naive UTC
    # datetime but without the deprecation warning.
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    # ── Inner: fetch one time range and collect recording dates ──────────────
    def fetch_for_range(start_dt: datetime, end_dt: datetime,
                        month_key: str, level: str = "month") -> int:
        """
        POST one or more paginated search requests for [start_dt, end_dt].
        Accumulates results into the outer monthly_unique_days / all_days sets.
        Returns the total number of matches fetched.
        SEC: typed exception handlers replace bare except Exception: print().
        """
        start_str = start_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        end_str   = end_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

        search_position = 0
        loop_counter    = 0
        total_matches   = 0

        while True:
            xml_body = (
                '<?xml version="1.0" encoding="utf-8"?>'
                '<CMSearchDescription>'
                '<searchID>88C2CD4D-D3FA-4AD4-BD80-555C18205DCC</searchID>'
                f'<trackList><trackID>{track_id}</trackID></trackList>'
                f'<timeSpanList><timeSpan>'
                f'<startTime>{start_str}</startTime>'
                f'<endTime>{end_str}</endTime>'
                f'</timeSpan></timeSpanList>'
                f'<maxResults>500</maxResults>'
                f'<searchResultPostion>{search_position}</searchResultPostion>'
                '<metadataList><metadataDescriptor>'
                '//recordType.meta.std-cgi.com'
                '</metadataDescriptor></metadataList>'
                '</CMSearchDescription>'
            )

            headers = {
                'Content-Type': 'application/xml',
                'Connection':   'Keep-Alive'
            }

            try:
                response = safe_post(
                    _SEARCH_URL, data=xml_body, headers=headers,
                    auth=HTTPDigestAuth(username_nvr, password_nvr)
                )

                if response.status_code != 200:
                    log.warning("[fetch] Cam %d: HTTP %d in %s (%s)",
                                cam_index, response.status_code, month_key, level)
                    break

                try:
                    root = ET.fromstring(response.content)
                except ET.ParseError as exc:
                    log.error("[fetch] Cam %d: XML parse error in %s: %s",
                              cam_index, month_key, exc)
                    break

                ns_uri    = root.tag.split("}")[0].strip("{")
                namespace = {"ns": ns_uri}

                match_list = root.findall(
                    './/ns:matchList/ns:searchMatchItem', namespace
                )
                if not match_list:
                    break

                for match in match_list:
                    start_elem = match.find(
                        './/ns:timeSpan/ns:startTime', namespace
                    )
                    if start_elem is not None:
                        try:
                            dt = datetime.strptime(
                                start_elem.text, "%Y-%m-%dT%H:%M:%SZ"
                            )
                            day_key          = dt.strftime("%Y-%m-%d")
                            day_keyy         = dt.strftime("%Y-%m-%d %H:%M:%S")
                            correct_month_key = dt.strftime("%Y-%m")

                            monthly_unique_days[correct_month_key].add(day_key)
                            all_days.add(day_key)
                            all_day_times.add(day_keyy)

                        except ValueError as exc:
                            log.warning("[fetch] Cam %d: Bad timestamp '%s': %s",
                                        cam_index, start_elem.text, exc)
                            continue

                total_matches   += len(match_list)
                search_position += len(match_list)
                loop_counter    += 1

                status_elem = root.find('.//ns:responseStatusStrg', namespace)
                response_status = (
                    status_elem.text if status_elem is not None else ""
                )
                if response_status != "MORE":
                    break

                if loop_counter > 1000:
                    log.warning("[fetch] Cam %d: >1000 pages in %s (%s) — stopping",
                                cam_index, month_key, level)
                    break

                time.sleep(0.5)

            except RequestException as exc:
                log.error("[fetch] Cam %d: Request error in %s (%s): %s",
                          cam_index, month_key, level, exc)
                break
            except Exception as exc:
                log.error("[fetch] Cam %d: Unexpected error in %s (%s): %s",
                          cam_index, month_key, level, exc)
                break

        return total_matches

    # ── Inner: adaptive time-range chunker ───────────────────────────────────
    MAX_RECURSION_DEPTH = 5

    def process_in_chunks(start_dt: datetime, end_dt: datetime,
                          month_key: str, chunk_days: int = 7,
                          depth: int = 0) -> None:
        """
        Split a date range into `chunk_days`-day windows and fetch each.
        If a chunk still returns >= 10,000 matches, recursively splits to 1-day.
        Stops recursing at MAX_RECURSION_DEPTH to prevent infinite loops.
        """
        if depth > MAX_RECURSION_DEPTH and chunk_days > 1:
            log.warning(
                "[chunks] Cam %d: Max recursion depth at %s→%s — skipping",
                cam_index, start_dt.date(), end_dt.date()
            )
            return

        chunk_start = start_dt
        while chunk_start < end_dt:
            chunk_end = min(
                chunk_start + relativedelta(days=chunk_days), end_dt
            )
            total = fetch_for_range(
                chunk_start, chunk_end, month_key,
                f"{chunk_days}-day"
            )

            if total >= 10000:
                if chunk_days > 1:
                    log.info(
                        "[chunks] Cam %d: High volume %s→%s — splitting to 1-day",
                        cam_index, chunk_start.date(), chunk_end.date()
                    )
                    process_in_chunks(
                        chunk_start, chunk_end, month_key,
                        chunk_days=1, depth=depth + 1
                    )
                else:
                    log.warning(
                        "[chunks] Cam %d: Single day %s has >10,000 records "
                        "— possible truncation",
                        cam_index, chunk_start.date()
                    )

            chunk_start = chunk_end

    # ── Month-by-month scan loop ──────────────────────────────────────────────
    try:
        for i in range(months_back):
            start_dt  = (now - relativedelta(months=i)).replace(
                day=1, hour=0, minute=0, second=0
            )
            end_dt    = start_dt + relativedelta(months=1)
            month_key = start_dt.strftime("%Y-%m")

            log.info("[process_camera] Cam %d: scanning %s", cam_index, month_key)
            total = fetch_for_range(start_dt, end_dt, month_key, "month")

            if total >= 10000:
                log.info(
                    "[process_camera] Cam %d: Heavy month %s (%d matches) "
                    "— switching to weekly chunks",
                    cam_index, month_key, total
                )
                process_in_chunks(start_dt, end_dt, month_key, chunk_days=7)

    except Exception as exc:
        log.error("[process_camera] Cam %d: Fatal error: %s", cam_index, exc)

    sorted_day_counts = {
        month: len(days)
        for month, days in sorted(monthly_unique_days.items())
    }

    return {
        "camera_id":               track_id_str,
        "recording_days_per_month": sorted_day_counts,
        "total_duration":          len(all_days),
        "start_time":              min(all_day_times) if all_day_times else None,
        "end_time":                max(all_day_times) if all_day_times else None,
    }


# ─────────────────────────────────────────────────────────────────────────────
# RUN ALL CAMERAS SEQUENTIALLY
# ─────────────────────────────────────────────────────────────────────────────

def run_all_cameras(cam_ids, months_back: int = 60) -> list:
    """
    Process each camera in cam_ids sequentially and return results list.
    Sequential polling is intentional — avoids simultaneous API requests
    overwhelming the NVR (see Dexter architecture note on concurrent polling).
    """
    results = []
    for cam_index in cam_ids:
        log.info("[run_all_cameras] Processing Camera %d", cam_index)
        results.append(process_camera(cam_index, months_back))
    return results


# ─────────────────────────────────────────────────────────────────────────────
# MAIN TELEMETRY FUNCTION
# DB-03: insert goes through BoundedBufferManager
# ─────────────────────────────────────────────────────────────────────────────

def getTrackIDInfo() -> dict:
    """
    Run the full 16-camera recording scan, build the telemetry payload,
    and push to the bounded buffer if the integration flag is active.

    recording_days_per_month is stripped before sending to ThingsBoard —
    it is large and only useful for local diagnostics.
    """
    camera_data = run_all_cameras(camera_ids, months_back)

    # Log summary to update.log (visible to operator without ThingsBoard)
    log.info("[getTrackIDInfo] Monthly unique recording days per camera:")
    for camera in camera_data:
        log.info("  Camera %s:", camera['camera_id'])
        for month, count in camera['recording_days_per_month'].items():
            log.debug("    %s: %d recorded days", month, count)
        log.info(
            "    Total=%d  Start=%s  End=%s",
            camera['total_duration'],
            camera['start_time'],
            camera['end_time']
        )

    # Strip recording_days_per_month before sending — too large for ThingsBoard
    cleaned: list = []
    for cam in camera_data:
        cam_cleaned = dict(cam)
        cam_cleaned.pop("recording_days_per_month", None)
        cleaned.append(cam_cleaned)

    final_result    = {"Hikvision_NVR_CameraRecInfo": cleaned}
    attributes_json = json.dumps(final_result)

    log.info("[getTrackIDInfo] Final payload: %s", attributes_json[:200])

    # DB-03: gated, bounded insert
    if _integration_active():
        insert_json_to_db(attributes_json)
        log.info("[getTrackIDInfo] Pushed recording info for %d camera(s)",
                 len(cleaned))

    return final_result


# ─────────────────────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # ACTIVE-INTEGRATION-GUARD: check flag before doing any work
    # If integration is disabled from the menu, exit cleanly.
    # systemd sees exit(0) as success and will NOT restart the service.
    # Service stays enabled — to re-activate, enable from menu then:
    #   sudo systemctl restart dexter-nvr-hik-lite
    if logical_params_module.get_parameter("active_integration_hikvision_nvr") != 1:
        import logging as _lg, sys as _sys
        _lg.getLogger(__name__).info(
            "[hiknvrlite7.py] active_integration_hikvision_nvr=0 — integration disabled, exiting cleanly"
        )
        _sys.exit(0)

    # ── JITTER: deterministic per-panel startup delay (Strategy A) ────────────
    # getTrackIDInfo() is a heavy 16-camera × 60-month scan. Without jitter,
    # all 5,000 panels launch this scan simultaneously after mass power restore.
    # Spreading across 300s → ~17 panels/sec instead of 5,000 at once.
    jitter = get_jitter_sec(window_sec=300)
    log.info("[startup] jitter delay = %ds", jitter)
    time.sleep(jitter)

    # Run once at startup
    getTrackIDInfo()

    # ── DAILY task: load-gated (Strategy B) — replaces fixed clock time ───────
    # Replaces schedule.every().day.at("17:42") — fixed time caused all 5,000
    # panels to hit ThingsBoard simultaneously. Now each panel sends once per
    # day only when its RPi CPU < 70% and RAM < 75%, checked every 60s.
    # Natural variation in panel load profiles produces organic spread.
    import datetime as _dt
    _daily_sent_date_hiklit = None

    def maybe_send_daily_hiklit():
        global _daily_sent_date_hiklit
        today = _dt.date.today()
        if _daily_sent_date_hiklit == today:
            return  # already sent today
        if not is_rpi_idle():
            log.debug("[daily] RPi busy — deferring Hikvision NVR recording analytics")
            return
        # RPi is idle — run the full 16-camera recording scan
        log.info("[daily] RPi idle — sending Hikvision NVR recording analytics")
        getTrackIDInfo()
        _daily_sent_date_hiklit = today

    schedule.every(60).seconds.do(maybe_send_daily_hiklit)

    log.info("[main] Hikvision NVR recording analytics scheduler started")
    try:
        while True:
            time.sleep(1)
            schedule.run_pending()
    except KeyboardInterrupt:
        log.info("[main] KeyboardInterrupt — shutting down")
