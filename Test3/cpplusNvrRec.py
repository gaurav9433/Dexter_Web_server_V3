import sys
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
log = get_dual_logger('cpplusNvrRec')
# Disable SSL warnings
urllib3.disable_warnings(InsecureRequestWarning)
requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

# Initialize the database
logical_params_module.initialize_database()

# ----------------------------- Global Variables -----------------------------
# REC-FIX-3: credential variables initialised as empty placeholders here.
# Actual values are set in __main__ after the integration flag is confirmed ON.
# This avoids module-level device lookups that ran before the guard and
# crashed with NameError (sys not imported) → restart loop.
ipaddress = ""
userid    = ""
password  = ""
session   = requests.Session()
session.verify = False

start_time = "2021-01-01 00:00:00"
end_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

# ----------------------------- Helper Functions -----------------------------
def recreate_session():
    """Recreate HTTP session and re-authenticate."""
    global session
    session = requests.Session()
    session.auth = HTTPDigestAuth(userid, password)
    session.verify = False
    try:
        session.get(f"http://{ipaddress}/cgi-bin/storageDevice.cgi?action=getDeviceAllInfo", timeout=10)
        print("Session re-authenticated")
    except Exception as e:
        log.error(f"Session re-auth failed: {e}")


def get_object_id():
    """Request a new object_id for media file queries."""
    try:
        res = session.get(f"http://{ipaddress}/cgi-bin/mediaFileFind.cgi?action=factory.create", timeout=10)
        if res.ok:
            match = re.search(r'result=(\d+)', res.text)
            if match:
                return match.group(1)
    except Exception as e:
        log.error("get_object_id error:", e)
    return None


def query_month(channel, disk_paths, month_start, month_end, retries=5):
    """Query recordings in a month range and return set of recording dates."""
    days = set()
    
    for attempt in range(retries):
        recreate_session()
        time.sleep(1)
        
        object_id = get_object_id()
        if not object_id:
            print(f"Could not get object_id, attempt {attempt+1}")
            continue

        params_find = {
            "action": "findFile",
            "object": object_id,
            "condition.Channel": channel,
            "condition.Types[0]": "dav",
            "condition.Events[0]": "AlarmLocal",
            "condition.Events[1]": "VideoMotion",
            "condition.StartTime": month_start,
            "condition.EndTime": month_end,
            "condition.VideoStream": "Main"
        }

        # Optional: include disk paths (commented if causing errors)
        for i, disk in enumerate(disk_paths):
            params_find[f"condition.Dirs[{i}]"] = disk

        try:
            res = session.get(f"http://{ipaddress}/cgi-bin/mediaFileFind.cgi", params=params_find, timeout=10)
            if not res.ok or "Invalid session" in res.text or "Error" in res.text:
                print(f"findFile failed for {month_start[:7]}, attempt {attempt+1}")
                time.sleep(2)
                continue
        except Exception as e:
            log.error(f" findFile exception: {e}")
            time.sleep(2)
            continue

        # Paginate results
        page = 0
        consecutive_empty = 0
        while page < 200:
            page += 1
            try:
                next_res = session.get(
                    f"http://{ipaddress}/cgi-bin/mediaFileFind.cgi",
                    params={"action": "findNextFile", "object": object_id, "count": 100},
                    timeout=15
                )
                if not next_res.ok or "Invalid session" in next_res.text:
                    log.error(f"Session lost during pagination page {page}")
                    break

                new_days = set(re.findall(r"(\d{4}-\d{2}-\d{2})", next_res.text))
                if not new_days:
                    consecutive_empty += 1
                    if consecutive_empty >= 3:
                        break
                    continue

                consecutive_empty = 0
                days.update(new_days)

            except Exception as e:
                log.error(f"findNextFile exception: {e}")
                break

        # Exit retry loop if any data retrieved
        if days or consecutive_empty >= 3:
            break

    return days


def get_recording_days_reverse(channel, disk_paths):
    """Scan recordings backward from today to earliest available."""
    days = set()
    first_recording_date = None
    last_recording_date = None

    current_end = datetime.now()
    while True:
        current_start = current_end - timedelta(days=7)  # scan in 7-day chunks
        print(f"Scanning {current_start.date()} → {current_end.date()}")

        month_days = query_month(
            channel, disk_paths,
            current_start.strftime("%Y-%m-%d %H:%M:%S"),
            current_end.strftime("%Y-%m-%d %H:%M:%S")
        )

        if not month_days:
            break

        days.update(month_days)
        earliest = min(month_days)
        latest = max(month_days)

        if not first_recording_date or earliest < first_recording_date:
            first_recording_date = earliest
        if not last_recording_date or latest > last_recording_date:
            last_recording_date = latest

        current_end = current_start
        time.sleep(1)

    return days, first_recording_date, last_recording_date


def subsequent_processing(Dahua_NVR_CameraRecInfo):
    """Process and print/send the final telemetry JSON."""
    attributes_json = json.dumps(Dahua_NVR_CameraRecInfo, indent=2)
    print(attributes_json)
    if logical_params_module.get_parameter("active_integration_cp_plus_nvr") == 1:        
        insert_json_to_db(attributes_json)
        print("Please check LATEST TELEMETRY field of NVR Record Info")
        #print(attributes_json)

# ----------------------------- Main Function -----------------------------
def main_NVR_Record_Info():
    Dahua_NVR_CameraRecInfo = {"CP_Plus_NVR_CameraRecInfo": []}

    # Detect mounted disks dynamically
    disk_paths = []
    try:
        res = session.get(f"http://{ipaddress}/cgi-bin/storageDevice.cgi?action=getDeviceAllInfo",
                          auth=HTTPDigestAuth(userid, password), verify=False, timeout=10)
        raw_text = res.text
        dev_paths = re.findall(r"Path=(/dev/sd[a-d][0-3])", raw_text)
        for p in dev_paths:
            disk_paths.append(p.replace("/dev", "/mnt/dvr"))
    except Exception as e:
        log.error("Failed to get disks:", e)

    if not disk_paths:
        disk_paths = ["/mnt/dvr/sda0", "/mnt/dvr/sdb0", "/mnt/dvr/sdc0", "/mnt/dvr/sdd0"]
    disk_paths = list(set(disk_paths))
    log.info("Detected partitions: %s", disk_paths)

    # Scan channels
    for ch in range(1, 17):
        log.info(f"Checking Channel {ch}...")
        time.sleep(1)

        days, first_recording_date, last_recording_date = get_recording_days_reverse(ch, disk_paths)

        channel_info = {
            "channel": ch,
            "start_date": first_recording_date if first_recording_date else start_time,
            "end_date": last_recording_date if last_recording_date else end_time,
            "total_recording_days": len(days)
        }

        if channel_info["total_recording_days"] > 0:
            Dahua_NVR_CameraRecInfo["CP_Plus_NVR_CameraRecInfo"].append(channel_info)

    subsequent_processing(Dahua_NVR_CameraRecInfo)


# ----------------------------- Run Script -----------------------------
if __name__ == "__main__":

    # REC-FIX-2: ACTIVE-INTEGRATION-GUARD — must be the very first thing in
    # __main__ before any device lookups or network activity.
    if logical_params_module.get_parameter("active_integration_cp_plus_nvr") != 1:
        log.info(
            "[cpplusNvrRec.py] active_integration_cp_plus_nvr=0 "
            "— integration disabled, exiting cleanly"
        )
        sys.exit(0)

    # REC-FIX-3: credentials fetched here, after integration flag confirmed ON.
    device_type = 'CP_PlusNVR1'
    devices = device_parameters_module.get_device_parameters(device_type)
    if not devices:
        log.error(
            "[cpplusNvrRec.py] No CP_PlusNVR1 entry in device_config.db "
            "— add via LCD menu. Exiting cleanly."
        )
        sys.exit(0)

    # No 'global' needed — ipaddress/userid/password/session are module-level
    # variables already defined as placeholders above.
    ipaddress = devices[0]['ip_address']
    userid    = devices[0]['username']
    password  = devices[0]['password']
    # Initialise session with real credentials now that they are loaded
    session.auth = HTTPDigestAuth(userid, password)
    log.info("[init] CP Plus NVR target: %s", ipaddress)

    # SL-01: Deterministic per-panel startup jitter — spreads 5,000 panels
    # across a 300s window so they do not all fire at the same time.
    jitter = get_jitter_sec(window_sec=300)
    log.info("[startup] jitter delay = %ds", jitter)
    time.sleep(jitter)

    # Run once at startup
    main_NVR_Record_Info()

    # SL-02: Daily gate — fires every 60s but only executes once per day
    # when the RPi is idle (CPU < 70%, RAM < 75%).
    # Replaces fixed schedule.every().day.at("10:10") — avoids thundering herd.
    _daily_sent_date_cpnvrrec = [None]

    def maybe_send_daily_cpnvrrec():
        today = date.today()
        if _daily_sent_date_cpnvrrec[0] == today:
            return
        if not is_rpi_idle():
            log.debug("[daily] RPi busy — deferring NVR record info")
            return
        main_NVR_Record_Info()
        _daily_sent_date_cpnvrrec[0] = today

    schedule.every(60).seconds.do(maybe_send_daily_cpnvrrec)

    try:
        while True:
            time.sleep(10)
            schedule.run_pending()

    except KeyboardInterrupt:
        log.error("\nExiting program...")
    
