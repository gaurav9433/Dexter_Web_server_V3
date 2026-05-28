import requests
from requests.auth import HTTPDigestAuth
from urllib3.exceptions import InsecureRequestWarning
import urllib3
import json
import time
import re
from datetime import datetime, timedelta

# DB-03: insert_json_to_db enforces 50K row hard cap + TTL purge
from buffer_manager import insert_json_to_db, init_db
init_db()  # Create buffer table if it does not exist yet
import device_parameters_module
import logical_params_module
import schedule
from scheduler_utils import get_jitter_sec, is_rpi_idle
from datetime import date

from syslog_file_logger import get_dual_logger
log = get_dual_logger('dahua_nvr_rec7')

urllib3.disable_warnings(InsecureRequestWarning)
requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

logical_params_module.initialize_database()

# REC-FIX-3: credential fetch removed from module level — moved inside
# __main__ after the integration flag check. At module level this ran
# before the guard — exit(0) or crash triggered restart loop.
device_type = 'DahuaNVR1'
ipaddress = ""
userid    = ""
password  = ""


# ----------------------------- Constants -----------------------------
MAX_RETRIES   = 15
RETRY_DELAY   = 10   # base seconds between retries
PAGE_TIMEOUT  = 20
QUERY_TIMEOUT = 15


# ----------------------------- Session Helpers -----------------------------

def make_fresh_session():
    """
    Create a brand-new requests.Session, warm it up with a real authenticated
    request so the NVR registers the session cookie, then return it.

    CRITICAL: on Dahua devices the object_id returned by factory.create is
    tied to the NVR-side session that was active when factory.create was called.
    Never recreate the session between factory.create and findFile/findNextFile.
    """
    s = requests.Session()
    s.auth   = HTTPDigestAuth(userid, password)
    s.verify = False

    # Warm-up: forces digest handshake and sets the NVR session cookie
    for attempt in range(4):
        try:
            r = s.get(
                f"http://{ipaddress}/cgi-bin/storageDevice.cgi?action=getDeviceAllInfo",
                timeout=10
            )
            if r.ok:
                print(f"  ✅ Session warmed up (attempt {attempt+1})")
                time.sleep(1)   # give NVR 1 s to settle after auth
                return s
            print(f"  ⚠ Warm-up HTTP {r.status_code}, attempt {attempt+1}/4")
        except Exception as e:
            log.error(f"  ⚠ Warm-up error attempt {attempt+1}/4: {e}")
        time.sleep(4)

    log.error("  ❌ Could not warm up session after 4 attempts")
    return s   # return anyway; caller will detect failure via bad responses


def destroy_object(s, object_id):
    """Best-effort release of NVR media-find handle."""
    if not object_id:
        return
    try:
        s.get(
            f"http://{ipaddress}/cgi-bin/mediaFileFind.cgi",
            params={"action": "destroy", "object": object_id},
            timeout=8
        )
    except Exception:
        pass


def _is_session_error(text: str) -> bool:
    """True if the NVR is rejecting the session (NOT a legitimate empty result)."""
    lowered = text.lower()
    return any(kw in lowered for kw in ("invalid session", "no session", "session"))


# ----------------------------- Core Query Logic -----------------------------

def query_range(channel, disk_paths, range_start, range_end):
    """
    Query recordings between range_start and range_end.
    Each attempt uses a completely fresh session.
    factory.create, findFile, and findNextFile all run on the SAME session.
    """
    days = set()

    for attempt in range(1, MAX_RETRIES + 1):
        s         = None
        object_id = None

        try:
            # ── 1. Fresh session (warm-up already included) ──────────────────
            s = make_fresh_session()

            # ── 2. factory.create — SAME session, no recreation after this ───
            res_create = s.get(
                f"http://{ipaddress}/cgi-bin/mediaFileFind.cgi?action=factory.create",
                timeout=QUERY_TIMEOUT
            )
            if not res_create.ok:
                print(f"    ⚠ factory.create HTTP {res_create.status_code}, attempt {attempt}/{MAX_RETRIES}")
                continue

            match = re.search(r'result=(\d+)', res_create.text)
            if not match:
                print(f"    ⚠ factory.create bad body: {res_create.text[:120]}, attempt {attempt}/{MAX_RETRIES}")
                continue

            object_id = match.group(1)
            print(f"    ℹ object_id={object_id}")

            # ── 3. findFile — SAME session ────────────────────────────────────
            # IMPORTANT: Dahua CGI requires spaces in datetimes encoded as %20,
            # not + (form-encoding default). Build URL string manually.
            def _t(v):
                return str(v).replace(" ", "%20").replace(":", "%3A")

            param_parts = [
                "action=findFile",
                f"object={object_id}",
                f"condition.Channel={channel}",
                "condition.Types[0]=dav",
                "condition.Events[0]=AlarmLocal",
                "condition.Events[1]=VideoMotion",
                f"condition.StartTime={_t(range_start)}",
                f"condition.EndTime={_t(range_end)}",
                "condition.VideoStream=Main",
            ]
            for i, disk in enumerate(disk_paths):
                param_parts.append(f"condition.Dirs[{i}]={disk}")

            find_url = f"http://{ipaddress}/cgi-bin/mediaFileFind.cgi?" + "&".join(param_parts)
            res_find = s.get(find_url, timeout=QUERY_TIMEOUT)

            if not res_find.ok:
                #print(f"    ⚠ findFile HTTP {res_find.status_code}, attempt {attempt}/{MAX_RETRIES}")
                continue

            if _is_session_error(res_find.text):
                #print(f"    ⚠ findFile session error: {res_find.text[:120]}, attempt {attempt}/{MAX_RETRIES}")
                continue

            # Legitimate empty result — no recordings in this window
            if "found=0" in res_find.text or "totalCount=0" in res_find.text:
                print(f"    ℹ No recordings {range_start[:10]} → {range_end[:10]}")
                return days

            print(f"    ✅ findFile OK | {res_find.text[:80]}")

            # ── 4. Paginate — SAME session ─────────────────────────────────────
            consecutive_empty = 0
            for page in range(1, 500):
                try:
                    res_next = s.get(
                        f"http://{ipaddress}/cgi-bin/mediaFileFind.cgi",
                        params={"action": "findNextFile", "object": object_id, "count": 100},
                        timeout=PAGE_TIMEOUT
                    )
                except Exception as e:
                    log.error(f"    ❌ findNextFile exception page {page}: {e}")
                    break

                if not res_next.ok or _is_session_error(res_next.text):
                    log.error(f"    ⚠ Session lost at page {page}: {res_next.text[:80]}")
                    break

                new_days = set(re.findall(r"(\d{4}-\d{2}-\d{2})", res_next.text))

                if not new_days:
                    consecutive_empty += 1
                    if consecutive_empty >= 3:
                        break
                    continue

                consecutive_empty = 0
                days.update(new_days)

            # ── 5. Success ─────────────────────────────────────────────────────
            return days

        except Exception as e:
            log.error(f"    ❌ Unexpected error attempt {attempt}/{MAX_RETRIES}: {e}")

        finally:
            if s and object_id:
                destroy_object(s, object_id)

        backoff = min(RETRY_DELAY * attempt, 40)
        log.error(f"    ↩ Retrying in {backoff}s …")
        time.sleep(backoff)

    log.error(f"    ⚠ Gave up on {range_start[:10]} → {range_end[:10]} after {MAX_RETRIES} attempts")
    return days


def get_recording_days_reverse(channel, disk_paths):
    """Scan backwards from today in 7-day windows until no data is found."""
    all_days           = set()
    first_recording    = None
    last_recording     = None
    consecutive_misses = 0
    MAX_MISSES         = 3   # stop after 3 consecutive empty windows

    current_end = datetime.now()

    while True:
        current_start = current_end - timedelta(days=7)
        print(f"  Scanning {current_start.date()} → {current_end.date()}")

        window_days = query_range(
            channel, disk_paths,
            current_start.strftime("%Y-%m-%d %H:%M:%S"),
            current_end.strftime("%Y-%m-%d %H:%M:%S")
        )

        if window_days:
            consecutive_misses = 0
            all_days.update(window_days)

            earliest = min(window_days)
            latest   = max(window_days)

            if not first_recording or earliest < first_recording:
                first_recording = earliest
            if not last_recording or latest > last_recording:
                last_recording = latest
        else:
            consecutive_misses += 1
            print(f"  ℹ Empty window ({consecutive_misses}/{MAX_MISSES})")
            if consecutive_misses >= MAX_MISSES:
                print(f"  🔚 No data in last {MAX_MISSES} windows — stopping scan for channel {channel}")
                break

        current_end = current_start
        time.sleep(3)

    return all_days, first_recording, last_recording


# ----------------------------- Output -----------------------------

def subsequent_processing(payload):
    """Serialize and optionally push to the integration buffer."""
    attributes_json = json.dumps(payload, indent=2)
    print(attributes_json)
    if logical_params_module.get_parameter("active_integration_dahua_nvr") == 1:
        insert_json_to_db(attributes_json)


# ----------------------------- Main -----------------------------

def main_NVR_Record_Info():
    Dahua_NVR_CameraRecInfo = {"Dahua_NVR_CameraRecInfo": []}
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # --- Detect mounted disks ---
    disk_paths = []
    try:
        res = session.get(
            f"http://{ipaddress}/cgi-bin/storageDevice.cgi?action=getDeviceAllInfo",
            auth=HTTPDigestAuth(userid, password),
            verify=False,
            timeout=10
        )
        dev_paths = re.findall(r"Path=(/dev/sd[a-d][0-3])", res.text)
        disk_paths = list({p.replace("/dev", "/mnt/dvr") for p in dev_paths})
    except Exception as e:
        log.error(f"❌ Failed to get disks: {e}")

    if not disk_paths:
        disk_paths = ["/mnt/dvr/sda0", "/mnt/dvr/sdb0", "/mnt/dvr/sdc0", "/mnt/dvr/sdd0"]

    log.error(f"✅ Detected partitions: {disk_paths}")

    # --- Scan channels 1–16 ---
    for ch in range(1, 17):
        log.info(f"\n{'='*40}")
        log.info(f"Checking Channel {ch}…")

        days, first_rec, last_rec = get_recording_days_reverse(ch, disk_paths)

        if days:
            channel_info = {
                "channel":               ch,
                "start_date":            first_rec,
                "end_date":              last_rec,
                "total_recording_days":  len(days),
            }
            Dahua_NVR_CameraRecInfo["Dahua_NVR_CameraRecInfo"].append(channel_info)
        else:
            log.info(f"  ℹ Channel {ch}: no recordings found.")

        time.sleep(2)

    # Send all channels in a single payload after scanning all 16
    subsequent_processing(Dahua_NVR_CameraRecInfo)


# ----------------------------- Entry Point -----------------------------

if __name__ == "__main__":

    # REC-FIX-2: ACTIVE-INTEGRATION-GUARD missing from original.
    # Without this, the service runs even when integration is OFF from the
    # LCD menu — causing it to appear as "failed" in autorun4.py status
    # because it tries to connect to the NVR when it should not be running.
    # systemd sees exit(0) as success and will NOT restart the service.
    if logical_params_module.get_parameter("active_integration_dahua_nvr") != 1:
        import logging as _lg, sys as _sys
        _lg.getLogger(__name__).info(
            "[dahua_nvr_rec7.py] active_integration_dahua_nvr=0 "
            "— integration disabled, exiting cleanly"
        )
        _sys.exit(0)

    # REC-FIX-3: credentials fetched here after integration flag confirmed ON
    # No 'global' needed — ipaddress/userid/password are module-level variables
    # already defined as "" above. Assigning here updates them in-place.
    _devices = device_parameters_module.get_device_parameters(device_type)
    if not _devices:
        import sys as _sys2
        log.error(
            "[dahua_nvr_rec7.py] No DahuaNVR1 entry in device_config.db "
            "— add via LCD menu. Exiting cleanly."
        )
        _sys2.exit(0)
    ipaddress = _devices[0]['ip_address']
    userid    = _devices[0]['username']
    password  = _devices[0]['password']
    log.info("[init] Dahua NVR Recording target: %s", ipaddress)

    # SL-01: Deterministic per-panel startup jitter
    jitter = get_jitter_sec(window_sec=300)
    log.info("[startup] jitter delay = %ds", jitter)
    time.sleep(jitter)

    # Run once at startup
    main_NVR_Record_Info()

    # SL-02: Daily gate — replaces fixed schedule.every().day.at("10:10")
    _daily_sent_date_dahuanvrrec = [None]

    def maybe_send_daily_dahuanvrrec():
        today = date.today()
        if _daily_sent_date_dahuanvrrec[0] == today:
            return
        if not is_rpi_idle():
            log.debug("[daily] RPi busy — deferring Dahua NVR record info")
            return
        main_NVR_Record_Info()
        _daily_sent_date_dahuanvrrec[0] = today

    schedule.every(60).seconds.do(maybe_send_daily_dahuanvrrec)

    try:
        while True:
            schedule.run_pending()
            time.sleep(10)
    except KeyboardInterrupt:
        log.error("\nExiting program…")
