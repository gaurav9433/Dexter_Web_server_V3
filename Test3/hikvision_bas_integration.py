#!/usr/bin/env python3
"""
hikvision_bas_integration.py — Hikvision DS-PHA64-LP(B) Active Integration
ISAPI/SecurityCP Protocol — Dexter HMS BAS Integration

Dexter HMS design constraints:
  DEXTER-01 : Active integration guard — exits if flag=0 in DB
  DEXTER-02 : dexter_event_hook() — maps events to Dexter HMS payloads
  DEXTER-03 : dexter_state_hook() — panel online/offline tracking
  DEXTER-04 : Uses payload_manager.insert_with_cap()
  DEXTER-05 : Uses logical_params_module for active_integration flag check
  DEXTER-06 : Heartbeat as dedicated JSON key {"hikvision_bas_heartbeat": {...}}
  DEXTER-07 : Logging via standard logger for journalctl

Design philosophy — RAW DATA, NO ANALYTICS:
  This module pulls raw alarm data from the panel and sends it to SWatch/TB.
  All analytics (deduplication, state tracking, alarm correlation) are done
  on the cloud/dashboard side — NOT in this module.

  The only deduplication done here is a 3-second burst filter on cidEvent —
  the panel sends 7-10 identical cidEvents per second; we fire exactly ONE
  per alarm event. Beyond that, every event is sent as-is.

  Supervision poll only sends:
    - heartbeat (panel online/offline)
    - SysFault events (battery, power, tamper faults)
  Supervision does NOT send alarm activate/restore — cidEvent is authoritative.

Panel:    Hikvision DS-PHA64-LP(B) / DS-PHA64-M / DS-PHA48-EP
Protocol: ISAPI/SecurityCP via HTTP Digest Auth
Stream:   Persistent GET /ISAPI/Event/notification/alertStream

Key ISAPI endpoints:
  GET  /ISAPI/System/deviceInfo                   — connectivity + model info
  GET  /ISAPI/Event/notification/alertStream      — live event stream
  GET  /ISAPI/SecurityCP/status/subSystems        — heartbeat + SysFault
  GET  /ISAPI/SecurityCP/status/host              — zone list with alarm+area
  GET  /ISAPI/SecurityCP/status/zones             — fallback zone list
  PUT  /ISAPI/SecurityCP/control/arm              — arm away
  PUT  /ISAPI/SecurityCP/control/armHome          — arm stay
  PUT  /ISAPI/SecurityCP/control/disarm           — disarm
  PUT  /ISAPI/SecurityCP/control/clearAlarm       — clear alarm
  PUT  /ISAPI/SecurityCP/control/bypass/<zoneID>  — bypass zone

ISAPI doc notes (AX HYBRID PRO V1 Series):
  - Zone IDs start at 0 (range 0-95); zone_no=0 is valid, NOT null
  - Partition (area/subSys) IDs start at 1 (range 1-64)
  - alertStream eventState: "active"=alarm on, "inactive"=alarm cleared
  - SysFault present in subSystems response on DS-PHA64 firmware
  - status/host ZoneList: id, alarm(bool), subSystemNo, status
"""

from __future__ import annotations

import sys, os, re, json, time, socket, logging, threading
from datetime import datetime
from typing import Optional, Dict, Any, List, Tuple

# ── systemd watchdog ──────────────────────────────────────────────────────────
def _sd_notify_watchdog():
    ns = os.environ.get('NOTIFY_SOCKET')
    if not ns:
        return
    try:
        if ns.startswith('@'):
            ns = '\x00' + ns[1:]
        s = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        s.connect(ns); s.sendall(b'WATCHDOG=1'); s.close()
    except Exception:
        pass

# ── Dexter HMS path ───────────────────────────────────────────────────────────
sys.path.insert(0, '/home/pi/Test3')

# ── DEXTER-07: Logger ─────────────────────────────────────────────────────────
log = logging.getLogger("dexter-hik-bas")
if not log.handlers:
    _h = logging.StreamHandler(sys.stdout)
    _h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s",
                                       datefmt="%Y-%m-%d %H:%M:%S"))
    log.addHandler(_h)
    log.setLevel(logging.DEBUG)

# ── DEXTER-01: Active integration guard ──────────────────────────────────────
# Checked at startup AND on every _insert/_send_hik_heartbeat call.
# Disabling from LCD menu takes effect immediately without service restart.
try:
    import logical_params_module
    logical_params_module.initialize_database()
    _flag = logical_params_module.get_parameter("active_integration_hik_bas")
    if _flag != 1:
        log.info("[HIK] active_integration_hik_bas=0 — disabled. Exiting.")
        sys.exit(0)
except SystemExit:
    raise
except Exception as _e:
    log.warning("[HIK] Could not read flag: %s — continuing.", _e)

# ── DEXTER-04: Payload manager — writes to payloads.db, read by TB MQTT publisher ─
# thingsboard_mqtt_publisher reads ONLY from payloads.db via PayloadManager.
# buffer_manager.insert_json_to_db goes to buffer.db (hardware events only).
try:
    from payload_manager import insert_with_cap
    _HAS_PAYLOAD_MANAGER = True
except ImportError:
    insert_with_cap = None
    _HAS_PAYLOAD_MANAGER = False
    log.warning("[HIK] payload_manager unavailable — events will not be stored")

# ── RTC ───────────────────────────────────────────────────────────────────────
try:
    import SDL_DS1307
    _ds1307 = SDL_DS1307.SDL_DS1307(1, 0x68)
    _HAS_RTC = True
except Exception:
    _HAS_RTC = False

# ── requests ──────────────────────────────────────────────────────────────────
try:
    import requests
    from requests.auth import HTTPDigestAuth
except ImportError:
    requests = None
    HTTPDigestAuth = None
    log.error("[HIK] requests missing. pip3 install requests --break-system-packages")
    sys.exit(1)

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG — credentials loaded from device_config.db
# ─────────────────────────────────────────────────────────────────────────────
PANEL_IP   = ""
PANEL_PORT = 80
PANEL_USER = ""
PANEL_PASS = ""
try:
    import device_parameters_module as _dpm
    _devices = _dpm.get_device_parameters("HikvisionBAS1")
    if not _devices:
        log.error("[HIK] No credentials for 'HikvisionBAS1' in device_config.db")
        sys.exit(1)
    _d         = _devices[0]
    PANEL_IP   = _d["ip_address"]
    PANEL_USER = _d["username"]
    PANEL_PASS = _d["password"]
    PANEL_PORT = int(_d.get("port", 80))
except Exception as _e:
    log.error("[HIK] Failed to load credentials: %s", _e)
    sys.exit(1)

USE_HTTPS            = False
PANEL_MODEL          = "HIK_PHA64"
HEARTBEAT_TIMEOUT    = 90     # alertStream reconnect on no data (seconds)
SUPERVISION_INTERVAL = 30     # supervision poll interval (seconds)
SUPERVISION_TIMEOUT  = 600    # offline threshold (seconds)
WATCHDOG_INTERVAL    = 25     # systemd watchdog ping interval (seconds)
HEARTBEAT_INTERVAL   = 600    # min seconds between periodic heartbeat sends
CID_BURST_WINDOW     = 3      # seconds — suppress duplicate cidEvents in same burst

# ─────────────────────────────────────────────────────────────────────────────
# ISAPI eventType → Dexter HMS log_type
# ─────────────────────────────────────────────────────────────────────────────
_DEXTER_EVENT_MAP = {
    "IO":                 "intrusion_alarm_system_activate",
    "IO_restored":        "intrusion_alarm_system_activation_restored",
    "fielddetection":     "intrusion_alarm_system_activate",
    "PIR":                "intrusion_alarm_system_activate",
    "VMD":                "intrusion_alarm_system_activate",
    "linedetection":      "intrusion_alarm_system_activate",
    "shelterAlarm":       "intrusion_alarm_system_fault",
    "tamperDetection":    "intrusion_alarm_system_fault",
    "faultAlarm":         "intrusion_alarm_system_fault",
    "illAccess":          "intrusion_alarm_system_fault",
    "diskfull":           "intrusion_alarm_system_fault",
    "diskerror":          "intrusion_alarm_system_fault",
    "fireDetection":      "fire_alarm_system_activate",
    "gasDetection":       "fire_alarm_system_activate",
    "emergencyAlarm":     "intrusion_alarm_system_activate",
    "medicalAlarm":       "intrusion_alarm_system_activate",
    "waterLeakDetection": "intrusion_alarm_system_fault",
    "armStatus":          "intrusion_alarm_system_arm",
}

_ARM_STATE_MAP = {
    "armed":     "intrusion_alarm_system_arm",
    "away":      "intrusion_alarm_system_arm",
    "stay":      "intrusion_alarm_system_arm",
    "arming":    "intrusion_alarm_system_arm",
    "disarmed":  "intrusion_alarm_system_disarm",
    "disarm":    "intrusion_alarm_system_disarm",
    "armFailed": "intrusion_alarm_system_fault",
}

# SysFault info strings from status/subSystems SysFault.FaultList[].Fault.info
_SYS_FAULT_MAP = {
    "ACLoss":                         "hik_bas_mains_off",
    "lowBatteryVoltage":              "hik_bas_battery_low",
    "batteryMiss":                    "hik_bas_battery_missing",
    "devRemove":                      "intrusion_alarm_system_fault",
    "wirelessKeypadTamperEvident":    "intrusion_alarm_system_fault",
    "wirelessSirenTamperEvident":     "intrusion_alarm_system_fault",
    "wirelessRepeaterTamperEvident":  "intrusion_alarm_system_fault",
    "wirelessCardReaderTamperEvident":"intrusion_alarm_system_fault",
    "wirelessOutputModTamperEvident": "intrusion_alarm_system_fault",
    "wirelessKeypadOffline":          "intrusion_alarm_system_fault",
    "wirelessSirenOffline":           "intrusion_alarm_system_fault",
    "wirelessRepeaterOffline":        "intrusion_alarm_system_fault",
    "wirelessCardReaderOffline":      "intrusion_alarm_system_fault",
    "wirelessOutputModOffline":       "intrusion_alarm_system_fault",
    "wiredNetAbnormal":               "intrusion_alarm_system_fault",
    "GPRSAbnormal":                   "intrusion_alarm_system_fault",
    "wifiAbnormal":                   "intrusion_alarm_system_fault",
    "SIMCardAbnormal":                "intrusion_alarm_system_fault",
    "RFAbnormal":                     "intrusion_alarm_system_fault",
    "ipcDisconnect":                  "intrusion_alarm_system_fault",
    "IPCIPconflict":                  "intrusion_alarm_system_fault",
}

# ─────────────────────────────────────────────────────────────────────────────
# Minimal shared state
# _cid_last_event : {(zone_no, event_state)} -> timestamp  — burst filter only
# _active_faults  : set of SysFault info strings currently active
# _last_hb_sent   : timestamp of last heartbeat send
# _zone_area_map  : {zone_no: area} — stored at activate, used at restore
# ─────────────────────────────────────────────────────────────────────────────
_cid_last_event: Dict[Any, float] = {}
_active_faults:  set              = set()
_last_hb_sent:   float            = 0.0
_zone_area_map:  Dict[Any, Any]   = {}
_state_lock = threading.Lock()

# status/host capability — checked once at startup
_STATUS_HOST_SUPPORTED = None
_cap_lock = threading.Lock()

# ─────────────────────────────────────────────────────────────────────────────
# HTTP session + helpers
# ─────────────────────────────────────────────────────────────────────────────
_SCHEME   = "https" if USE_HTTPS else "http"
_BASE_URL = f"{_SCHEME}://{PANEL_IP}:{PANEL_PORT}"
_AUTH     = HTTPDigestAuth(PANEL_USER, PANEL_PASS)
_SESSION  = requests.Session()
_SESSION.verify = False


def _api_get(path, timeout=10):
    try:
        r = _SESSION.get(_BASE_URL + path, auth=_AUTH, timeout=timeout)
        return r if r.status_code == 200 else None
    except Exception:
        return None


def _api_get_raw(path, timeout=10):
    try:
        return _SESSION.get(_BASE_URL + path, auth=_AUTH, timeout=timeout)
    except Exception:
        return None


def _api_put(path, payload, timeout=10):
    try:
        return _SESSION.put(_BASE_URL + path, auth=_AUTH, json=payload,
                            headers={"Content-Type": "application/json"},
                            timeout=timeout)
    except Exception:
        return None


def _api_post(path, payload, timeout=10):
    """POST with JSON body — returns response if HTTP 200, else None."""
    try:
        r = _SESSION.post(_BASE_URL + path, auth=_AUTH, json=payload,
                          headers={"Content-Type": "application/json"},
                          timeout=timeout)
        return r if r.status_code == 200 else None
    except Exception:
        return None


def _poll_system_fault():
    """
    POST /ISAPI/SecurityCP/status/systemFault — the correct endpoint for
    battery/power/tamper fault data on DS-PHA64 firmware.
    Confirmed working in production: returns ArmFault.SysFault.FaultList
    with entries like {"Fault": {"info": "batteryMiss"}}.
    Also checks HostStatus.batteryStatus and HostStatus.ACStatus from
    POST /ISAPI/SecurityCP/status/host for power/battery state.
    """
    fault_names = []

    # ── Source 1: systemFault endpoint ───────────────────────────────────────
    body = {"SubSysList": [{"SubSys": {"id": 1}}], "operationStatus": "disArm"}
    r = _api_post("/ISAPI/SecurityCP/status/systemFault?format=json", body, timeout=10)
    if r:
        try:
            arm_fault  = r.json().get("ArmFault", {})
            sys_fault  = arm_fault.get("SysFault", {})
            fault_list = sys_fault.get("FaultList", [])
            for item in fault_list:
                f    = item.get("Fault", item)
                info = f.get("info", "")
                if info:
                    fault_names.append(info)
            if fault_names:
                log.debug("[HIK-FAULT-POLL] systemFault faults: %s", fault_names)
        except Exception as exc:
            log.debug("[HIK-FAULT-POLL] systemFault parse error: %s", exc)

    # ── Source 2: HostStatus battery/AC from status/host ─────────────────────
    body2 = {"AlarmHostStatusCond": {"hostStatus": True, "zoneStatus": False, "subSys": False}}
    r2 = _api_post("/ISAPI/SecurityCP/status/host?format=json", body2, timeout=10)
    if r2:
        try:
            host = r2.json().get("AlarmHostStatus", {}).get("HostStatus", {})
            ac   = host.get("ACStatus", host.get("acStatus", ""))
            if ac and ac.lower() not in ("normal", ""):
                if "ACLoss" not in fault_names:
                    fault_names.append("ACLoss")
            batt = host.get("batteryStatus", "")
            if batt == "miss":
                if "batteryMiss" not in fault_names:
                    fault_names.append("batteryMiss")
            charge = host.get("charge", host.get("batteryVoltage", ""))
            if charge and charge.lower() == "lowpower":
                if "lowBatteryVoltage" not in fault_names:
                    fault_names.append("lowBatteryVoltage")
        except Exception as exc:
            log.debug("[HIK-FAULT-POLL] host power parse error: %s", exc)

    _process_sys_faults(fault_names)


# ─────────────────────────────────────────────────────────────────────────────
# Extended status polls — health/telemetry data from panel peripherals
# Polled every STATUS_POLL_INTERVAL (5 min) — not alarm-critical.
#
# Change-detection strategy:
#   _STATUS_CACHE  : dict keyed by TB payload key, value = last sent JSON string
#   On startup     : _poll_all_status(force=True)  → always sends, fills cache
#   Every 5 min    : _poll_all_status(force=False) → sends only if data changed
#
# Comparison is done on the full JSON string of the data dict.
# If the panel returns no data (endpoint not supported), cache stays untouched.
# ─────────────────────────────────────────────────────────────────────────────
STATUS_POLL_INTERVAL = 300   # seconds — 5 minutes

_STATUS_CACHE      : Dict[str, str] = {}   # {tb_key: last_sent_json_string}
_STATUS_CACHE_LOCK = threading.Lock()


def _send_if_changed(tb_key: str, data, force: bool) -> bool:
    """
    Serialize data to JSON and compare with last sent value for tb_key.
    Sends to TB and updates cache only if data changed or force=True.
    Returns True if payload was sent.
    """
    if data is None:
        return False
    try:
        current_json = json.dumps(data, sort_keys=True)
    except Exception:
        return False

    with _STATUS_CACHE_LOCK:
        last_json = _STATUS_CACHE.get(tb_key)
        if not force and current_json == last_json:
            log.debug("[HIK-STATUS] %s unchanged — skipped", tb_key)
            return False
        _STATUS_CACHE[tb_key] = current_json

    _insert(json.dumps({tb_key: data}))
    log.info("[HIK-STATUS] %s sent (changed=%s)", tb_key, not force)
    return True


def _poll_batteries(force: bool = False):
    """
    GET /ISAPI/SecurityCP/status/batteries
    Fields: id, status (normal/miss), percent (%), voltage (V)
    """
    r = _api_get("/ISAPI/SecurityCP/status/batteries?format=json", timeout=8)
    if not r:
        return
    try:
        batteries = []
        for item in r.json().get("BatteryList", []):
            b = item.get("Battery", item)
            batteries.append({
                "id":      b.get("id"),
                "status":  b.get("status"),
                "percent": b.get("percent"),
                "voltage": b.get("voltage"),
            })
        if batteries:
            _send_if_changed("hik_bas_batteries", batteries, force)
    except Exception as exc:
        log.debug("[HIK-STATUS] batteries error: %s", exc)


def _poll_communication(force: bool = False):
    """
    GET /ISAPI/SecurityCP/status/communication
    Fields: wired, wifi, wifiSignal, mobile, mobileSignal, flow, cloud
    """
    r = _api_get("/ISAPI/SecurityCP/status/communication?format=json", timeout=8)
    if not r:
        return
    try:
        cs = r.json().get("CommuniStatus", {})
        data = {
            "wired":         cs.get("wired"),
            "wifi":          cs.get("wifi"),
            "wifi_signal":   cs.get("wifiSignal"),
            "mobile":        cs.get("mobile"),
            "mobile_signal": cs.get("mobileSignal"),
            "flow_mb":       cs.get("flow"),
            "cloud":         cs.get("cloud"),
        }
        _send_if_changed("hik_bas_communication", data, force)
    except Exception as exc:
        log.debug("[HIK-STATUS] communication error: %s", exc)


def _poll_ex_dev_status(force: bool = False):
    """
    GET /ISAPI/SecurityCP/status/exDevStatus
    Fields per output module: id, status, tamperEvident, voltValue, currentValue,
    powerLoad, charge, chargeValue, temperature, signal
    """
    r = _api_get("/ISAPI/SecurityCP/status/exDevStatus?format=json", timeout=8)
    if not r:
        return
    try:
        modules = []
        ex = r.json().get("ExDevStatus", {})
        for item in ex.get("OutputModList", []):
            m = item.get("OutputMod", item)
            modules.append({
                "id":          m.get("id"),
                "status":      m.get("status"),
                "tamper":      m.get("tamperEvident"),
                "voltage_v":   m.get("voltValue"),
                "current_ma":  m.get("currentValue"),
                "power_w":     m.get("powerLoad"),
                "charge":      m.get("charge"),
                "charge_pct":  m.get("chargeValue"),
                "temperature": m.get("temperature"),
                "signal":      m.get("signal"),
            })
        if modules:
            _send_if_changed("hik_bas_output_modules", modules, force)
    except Exception as exc:
        log.debug("[HIK-STATUS] exDevStatus error: %s", exc)


def _poll_siren_status(force: bool = False):
    """
    GET /ISAPI/SecurityCP/status/sirenStatus
    Fields per siren: id, name, status, tamperEvident, charge, chargeValue,
    signal, temperature
    """
    r = _api_get("/ISAPI/SecurityCP/status/sirenStatus?format=json", timeout=8)
    if not r:
        return
    try:
        sirens = []
        for item in r.json().get("SirenList", []):
            s = item.get("Siren", item)
            sirens.append({
                "id":          s.get("id"),
                "name":        s.get("name"),
                "status":      s.get("status"),
                "tamper":      s.get("tamperEvident"),
                "charge":      s.get("charge"),
                "charge_pct":  s.get("chargeValue"),
                "signal":      s.get("signal"),
                "temperature": s.get("temperature"),
            })
        if sirens:
            _send_if_changed("hik_bas_sirens", sirens, force)
    except Exception as exc:
        log.debug("[HIK-STATUS] sirenStatus error: %s", exc)


def _poll_output_mod_status(force: bool = False):
    """
    GET /ISAPI/SecurityCP/status/outputModStatus
    Fields per module: id, status, tamperEvident, charge, chargeValue,
    signal, voltValue, currentValue, powerLoad, energySumVaule, temperature
    """
    r = _api_get("/ISAPI/SecurityCP/status/outputModStatus?format=json", timeout=8)
    if not r:
        return
    try:
        modules = []
        for item in r.json().get("OutputModList", []):
            m = item.get("OutputMod", item)
            modules.append({
                "id":          m.get("id"),
                "status":      m.get("status"),
                "tamper":      m.get("tamperEvident"),
                "charge":      m.get("charge"),
                "charge_pct":  m.get("chargeValue"),
                "signal":      m.get("signal"),
                "voltage_v":   m.get("voltValueV20", m.get("voltValue")),
                "current_ma":  m.get("currentValue"),
                "power_w":     m.get("powerLoad"),
                "energy_wh":   m.get("energySumVaule"),
                "temperature": m.get("temperature"),
            })
        if modules:
            _send_if_changed("hik_bas_output_mod_status", modules, force)
    except Exception as exc:
        log.debug("[HIK-STATUS] outputModStatus error: %s", exc)


def _poll_zones_detail(force: bool = False):
    """
    GET /ISAPI/SecurityCP/status/zones
    Extended zone fields beyond alarm status:
    tamperEvident, bypassed, armed, charge, chargeValue (%), signal,
    temperature, humidity, detectorType, zoneType, healthStatus
    Sends as a zone health snapshot — not alarm events.
    """
    r = _api_get("/ISAPI/SecurityCP/status/zones?format=json", timeout=8)
    if not r:
        return
    try:
        zones = []
        for item in r.json().get("ZoneList", []):
            z = item.get("Zone", item)
            zid = z.get("id")
            if zid is None:
                continue
            zones.append({
                "id":            zid + 1,
                "armed":         z.get("armed"),
                "tamper":        z.get("tamperEvident"),
                "bypassed":      z.get("bypassed"),
                "charge":        z.get("charge"),
                "charge_pct":    z.get("chargeValue"),
                "signal":        z.get("signal"),
                "temperature":   z.get("temperature"),
                "humidity":      z.get("humidity"),
                "detector_type": z.get("detectorType"),
                "zone_type":     z.get("zoneType"),
                "health":        z.get("healthStatus"),
            })
        if zones:
            _send_if_changed("hik_bas_zones_detail", zones, force)
    except Exception as exc:
        log.debug("[HIK-STATUS] zones detail error: %s", exc)


def _poll_host_detail(force: bool = False):
    """
    POST /ISAPI/SecurityCP/status/host — HostStatus fields:
    tamperEvident (panel tamper), ACConnect (bool), faultNum,
    communicationFrequency, EzvizNetwork.
    Sends as panel health snapshot — not alarm events.
    """
    body = {"AlarmHostStatusCond": {"hostStatus": True, "zoneStatus": False, "subSys": False}}
    r = _api_post("/ISAPI/SecurityCP/status/host?format=json", body, timeout=8)
    if not r:
        return
    try:
        host = r.json().get("AlarmHostStatus", {}).get("HostStatus", {})
        data = {
            "tamper":       host.get("tamperEvident"),
            "ac_connected": host.get("ACConnect"),
            "fault_count":  host.get("faultNum"),
            "rf_frequency": host.get("communicationFrequency"),
            "network":      host.get("EzvizNetwork"),
        }
        _send_if_changed("hik_bas_host_status", data, force)
    except Exception as exc:
        log.debug("[HIK-STATUS] host detail error: %s", exc)


def _poll_all_status(force: bool = False):
    """
    Run all extended status polls.
    force=True  → always send to TB (used at startup — fills cache with baseline)
    force=False → send only if data changed since last send (used by 5-min timer)
    """
    _poll_batteries(force)
    _poll_communication(force)
    _poll_ex_dev_status(force)
    _poll_siren_status(force)
    _poll_output_mod_status(force)
    _poll_zones_detail(force)
    _poll_host_detail(force)

# ADDED  from GPT ////////////////////////////////////////////////////////////////////////////////
def _xml_val(tag, text):
    """Extract value from XML tag."""
    try:
        m = re.search(rf"<{tag}[^>]*>([^<]+)</{tag}>", text)
        return m.group(1).strip() if m else None
    except Exception:
        return None
#/////////////////////////////////////////////////////////////////////////////////////////////////

def _json_field(key, text):
    m = re.search(rf'"{key}"\s*:\s*"?([^",\}}\]]+)"?', text)
    return m.group(1).strip() if m else None

# ─────────────────────────────────────────────────────────────────────────────
# Timestamp / payload builder
# ─────────────────────────────────────────────────────────────────────────────
def _get_rtc_datetime() -> Tuple[str, str, str, str, str]:
    if _HAS_RTC:
        try:
            return (str(_ds1307._read_date()).zfill(2),
                    str(_ds1307._read_month()).zfill(2),
                    str(_ds1307._read_year()).zfill(2),
                    str(_ds1307._read_hours()).zfill(2),
                    str(_ds1307._read_minutes()).zfill(2))
        except Exception:
            pass
    n = datetime.now()
    return (str(n.day).zfill(2), str(n.month).zfill(2),
            str(n.year % 100).zfill(2), str(n.hour).zfill(2),
            str(n.minute).zfill(2))


def _build_payload(log_type: str, zone_no=None, area=None) -> str:
    """
    Dexter HMS Telemetry Format Spec v1.0
    {"log_type":"<event>","zone_no":<zone>,"area":<area>,"date":"DD:MM:YY","time":"HH:MM"}
    zone_no: Hikvision panel is 0-indexed (zone 0 = physical zone 1).
             +1 applied here so TB always shows physical zone number.
    area: starts at 1. 0 and None both -> null.
    """
    dd, mm, yy, hh, mi = _get_rtc_datetime()
    lt = json.dumps(log_type) if isinstance(log_type, (dict, list)) else f'"{log_type}"'
    # Hikvision DS-PHA64 zone IDs are 0-indexed internally.
    # Add 1 to show the physical zone number in TB/SWatch.
    # Panel zone 0 = physical zone 1, zone 1 = physical zone 2, etc.
    zv = str(zone_no + 1) if zone_no is not None else "null"
    av = str(area)    if (area is not None and area != 0) else "null"
    return (f'{{"log_type":{lt},'
            f'"zone_no":{zv},'
            f'"area":{av},'
            f'"date":"{dd}:{mm}:{yy}",'
            f'"time":"{hh}:{mi}"}}')


def _is_integration_active() -> bool:
    """
    Check active_integration_hik_bas flag on every call.
    Returns False immediately when disabled from LCD menu —
    matching the pattern used by texecom, AMC and other integrations.
    """
    try:
        return logical_params_module.get_parameter("active_integration_hik_bas") == 1
    except Exception:
        return True  # if DB unreachable, allow — fail open


def _insert(payload_str: str):
    """Insert telemetry payload into payloads.db for TB MQTT publisher.
    Checks active integration flag on every call — disabling from LCD
    stops all output immediately without restarting the service."""
    if not _HAS_PAYLOAD_MANAGER:
        return
    if not _is_integration_active():
        log.debug("[HIK] integration disabled — payload dropped")
        return
    insert_with_cap(payload_str)

# ─────────────────────────────────────────────────────────────────────────────
# DEXTER-06: Heartbeat — {"hikvision_bas_heartbeat": {...}}
# Matches texecom_heartbeat pattern. Rate-limited to HEARTBEAT_INTERVAL.
# force=True bypasses rate limit (used on state change and startup).
# ─────────────────────────────────────────────────────────────────────────────
def _send_hik_heartbeat(status: str, force: bool = False):
    global _last_hb_sent
    if not _HAS_PAYLOAD_MANAGER:
        return
    if not _is_integration_active():
        return
    now = time.time()
    if not force and (now - _last_hb_sent) < HEARTBEAT_INTERVAL:
        return
    try:
        payload = {
            "hikvision_bas_heartbeat": {
                "status":    status,
                "panel_ip":  PANEL_IP,
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
        }
        insert_with_cap(json.dumps(payload))
        _last_hb_sent = now
        log.info("[HIK->Dexter] hikvision_bas_heartbeat status=%s", status)
    except Exception as exc:
        log.warning("[HIK] heartbeat send error: %s", exc)

# ─────────────────────────────────────────────────────────────────────────────
# DEXTER-03: Panel online/offline state hook
# ─────────────────────────────────────────────────────────────────────────────
_panel_was_online = True


def dexter_state_hook(online: bool):
    global _panel_was_online
    if online == _panel_was_online:
        return
    _panel_was_online = online
    status = "online" if online else "LinkFail"
    _send_hik_heartbeat(status, force=True)
    log.info("[HIK] Panel %s", status.upper())

# ─────────────────────────────────────────────────────────────────────────────
# status/host capability check — once at startup
# ─────────────────────────────────────────────────────────────────────────────
def _check_status_host_capability():
    global _STATUS_HOST_SUPPORTED
    log.info("[HIK] Checking status/host capability...")
    r = _api_get_raw("/ISAPI/SecurityCP/status/host?format=json", timeout=8)
    with _cap_lock:
        if r is None:
            _STATUS_HOST_SUPPORTED = False
            log.warning("[HIK] status/host: no response — unsupported")
        elif r.status_code == 200:
            _STATUS_HOST_SUPPORTED = True
            log.info("[HIK] status/host: supported")
        else:
            _STATUS_HOST_SUPPORTED = False
            log.info("[HIK] status/host: HTTP %d — unsupported, using status/zones",
                     r.status_code)

# ─────────────────────────────────────────────────────────────────────────────
# Zone lookup — called once per cidEvent activate burst
# Returns list of (zone_no, area) for all currently alarmed zones.
# ─────────────────────────────────────────────────────────────────────────────
def _get_alarmed_area() -> Optional[int]:
    """
    Poll status/subSystems to find the partition currently in alarm (alarm=True).
    DS-PHA64 does not populate subSystemNo per zone in status/host, so area
    must be retrieved from partition level separately.
    Returns partition ID (int) or None.
    """
    r = _api_get("/ISAPI/SecurityCP/status/subSystems?format=json", timeout=5)
    if not r:
        return None
    try:
        data = r.json()
        for item in data.get("SubSysList", data.get("List", [])):
            sub = item.get("SubSys", item)
            if sub.get("alarm"):
                return sub.get("id")
    except Exception:
        pass
    return None


def _get_alarmed_zones() -> List[Tuple[Any, Any]]:
    """
    Query panel for zones currently in alarm state.
    Returns list of (zone_no, area) tuples where zone_no is not None.
    Returns [] if no alarmed zone found — caller skips the activate entirely.
    Never returns (None, None) — that creates blank rows in TB.

    Strategy:
      1. Poll status/subSystems -> get area from alarmed partition (alarm=True).
      2. Poll status/host (preferred) or status/zones (fallback) -> get zone IDs.
      3. Merge: zone area = subSystemNo from zone (if present) else area from step 1.
    """
    area = _get_alarmed_area()

    with _cap_lock:
        host_ok = _STATUS_HOST_SUPPORTED

    if host_ok:
        r = _api_get("/ISAPI/SecurityCP/status/host?format=json", timeout=8)
        if r:
            try:
                data = r.json()
                zone_list = data.get("AlarmHostStatus", {}).get("ZoneList", [])
                results = []
                for z in zone_list:
                    zd = z.get("Zone", z)
                    if zd.get("alarm"):
                        z_no = zd.get("id")
                        a_no = zd.get("subSystemNo") or area
                        if z_no is not None:
                            results.append((z_no, a_no))
                if results:
                    log.info("[HIK] status/host -> %d alarmed: %s", len(results), results)
                    return results
                log.debug("[HIK] status/host: no alarmed zones")
                return []
            except Exception as exc:
                log.debug("[HIK] status/host parse error: %s", exc)

    r = _api_get("/ISAPI/SecurityCP/status/zones?format=json", timeout=8)
    if r:
        try:
            data = r.json()
            results = []
            for z in data.get("ZoneList", []):
                zd = z.get("Zone", z)
                if zd.get("status") == "trigger" or zd.get("alarm"):
                    z_no = zd.get("id")
                    a_no = zd.get("subSystemNo") or area
                    if z_no is not None:
                        results.append((z_no, a_no))
            if results:
                log.info("[HIK] status/zones -> %d alarmed: %s", len(results), results)
                return results
            log.debug("[HIK] status/zones: no triggered zone")
        except Exception as exc:
            log.debug("[HIK] status/zones parse error: %s", exc)
    else:
        log.debug("[HIK] status/zones poll failed")

    return []


def _is_zone_still_alarming(zone_no) -> bool:
    """
    Poll status/host (or status/zones) to check if a specific zone is still
    in alarm state. Used at restore time to confirm the zone has truly cleared
    before sending intrusion_alarm_system_activate_restored.

    Returns True  → zone is still alarming → suppress restore
    Returns False → zone is clear OR poll failed → allow restore to fire
    (If poll fails we allow the restore — safer than never restoring)
    """
    with _cap_lock:
        host_ok = _STATUS_HOST_SUPPORTED

    if host_ok:
        r = _api_get("/ISAPI/SecurityCP/status/host?format=json", timeout=5)
        if r:
            try:
                data = r.json()
                zone_list = data.get("AlarmHostStatus", {}).get("ZoneList", [])
                for item in zone_list:
                    z = item.get("Zone", item)
                    if z.get("id") == zone_no and z.get("alarm"):
                        return True   # zone still alarming
                return False          # zone not found alarming
            except Exception:
                pass

    # Fallback: status/zones
    r = _api_get("/ISAPI/SecurityCP/status/zones?format=json", timeout=5)
    if r:
        try:
            data = r.json()
            for item in data.get("ZoneList", []):
                z = item.get("Zone", item)
                if z.get("id") == zone_no:
                    if z.get("status") == "trigger" or z.get("alarm"):
                        return True
                    return False
        except Exception:
            pass

    return False  # poll failed — allow restore
def _process_sys_faults(fault_names: list, partition_id=None):
    """
    Compare fault_names (plain string list: ["batteryMiss", "ACLoss"...])
    against _active_faults. New fault -> activate. Gone fault -> restored.
    """
    global _active_faults
    current_faults = set(fault_names)  # already strings from _poll_system_fault

    with _state_lock:
        new_faults     = current_faults - _active_faults
        cleared_faults = _active_faults - current_faults
        _active_faults = current_faults

    for fault in new_faults:
        log_type = _SYS_FAULT_MAP.get(fault, "hik_bas_" + fault.lower())
        _insert(_build_payload(log_type, area=partition_id))
        log.warning("[HIK-FAULT] New: %s -> %s", fault, log_type)

    for fault in cleared_faults:
        base = _SYS_FAULT_MAP.get(fault, "hik_bas_" + fault.lower())
        _insert(_build_payload(base + "_restored", area=partition_id))
        log.info("[HIK-FAULT] Cleared: %s -> %s_restored", fault, base)

# ─────────────────────────────────────────────────────────────────────────────
# alertStream event block parser
# ─────────────────────────────────────────────────────────────────────────────
# noinspection PyTypeHints
def _parse_event_block(block_text: str) -> Optional[Dict[str, Any]]:
    """
    Parse one multipart block from alertStream.
    ISAPI alertStream XML: <eventState>active</eventState> = alarm on/off.
    armStatus XML: <arming>armed|disarmed|...</arming>
    Partition field: <subSysID> in SecurityCP events, fallback <partitionID>
    """
    is_json = "application/json" in block_text or block_text.lstrip().startswith("{")

    if is_json:
        js = block_text.find("{")
        if js < 0:
            return None
        try:
            d = json.loads(block_text[js:])
        except Exception:
            d = {}
        return {
            "eventType":  d.get("eventType")  or _json_field("eventType",  block_text) or "unknown",
            "channelID":  d.get("channelID"),
            "partitionID":(d.get("partitionID") or d.get("subSysID")
                           or _json_field("partitionID", block_text)),
            "zoneID":     d.get("zoneID")     or _json_field("zoneID",     block_text),
            "dateTime":   d.get("dateTime")   or _json_field("dateTime",   block_text),
            "ipAddress":  d.get("ipAddress",  PANEL_IP),
            "armState":   d.get("arming",     "") or d.get("armingStatus", ""),
            "eventState": d.get("eventState", "") or _json_field("eventState", block_text) or "",
        }
    else:
        return {
            "eventType":  _xml_val("eventType",  block_text) or "unknown",
            "channelID":  _xml_val("channelID",  block_text),
            "partitionID":(_xml_val("subSysID",  block_text) or
                           _xml_val("partitionID", block_text)),
            "zoneID":     _xml_val("zoneID",     block_text),
            "dateTime":   _xml_val("dateTime",   block_text),
            "ipAddress":  _xml_val("ipAddress",  block_text) or PANEL_IP,
            "armState":   _xml_val("arming",     block_text) or "",
            "eventState": _xml_val("eventState", block_text) or "",
        }

# ─────────────────────────────────────────────────────────────────────────────
# DEXTER-02: Event hook — raw data, minimal processing
# ─────────────────────────────────────────────────────────────────────────────
def dexter_event_hook(event: dict):
    """
    Maps ISAPI event to Dexter HMS payload and inserts to payloads.db.

    cidEvent handling (raw + burst-filter only):
      - eventState="active"   -> poll status/host for zone+area, send activate
      - eventState="inactive" -> send restore with zone+area from stored map
      - Burst filter: suppress identical (zone, state) within CID_BURST_WINDOW seconds
        This absorbs the panel's 7-10 identical cidEvents per second.
        After burst window, new events pass through — no state machine.

    All other events: sent as-is with whatever zone/area the stream provides.
    No activate/restore tracking. No deduplication beyond the burst window.
    SWatch/TB handles analytics.
    """
    ev_type = event.get("eventType", "unknown")

    def _to_int(v):
        try:
            return int(v) if v is not None else None
        except (ValueError, TypeError):
            return None

    zone_no = _to_int(event.get("zoneID"))
    area    = _to_int(event.get("partitionID"))

    # heartBeat: silently skip
    if ev_type == "heartBeat":
        return

    # ── cidEvent ─────────────────────────────────────────────────────────────
    if ev_type == "cidEvent":
        ev_state   = event.get("eventState", "").lower().strip()
        is_restore = ev_state in ("inactive", "restore", "normal")
        now = time.time()

        if not is_restore:
            # Activate path.
            # Deduplication strategy:
            #   - _zone_area_map tracks which zones are currently active.
            #     A zone already in the map is suppressed (panel re-sends active
            #     bursts every ~27s while alarm is ongoing).
            #   - Rate limit: poll status/host at most once per second to avoid
            #     flooding the panel with 7-10 requests per cidEvent burst.
            #     But do NOT use a 3s gate — that would miss a second zone
            #     triggering within 3s of the first.
            with _state_lock:
                last_poll = _cid_last_event.get("_poll_active", 0)
                if now - last_poll < 1.0:
                    return  # panel already polled within last 1s — skip
                _cid_last_event["_poll_active"] = now

            # Poll panel for all currently alarmed zones
            alarmed = _get_alarmed_zones()

            if not alarmed:
                # No zone found at poll time (cleared before poll, e.g. disarm).
                log.debug("[HIK-CID] activate: no zone found at poll — skipped")
                return

            for z_no, a_no in alarmed:
                with _state_lock:
                    # Already active — suppress (ongoing alarm re-sends burst every ~27s)
                    if z_no in _zone_area_map:
                        log.debug("[HIK-CID] zone=%s already active — suppressed", z_no)
                        continue
                    _zone_area_map[z_no] = a_no  # store zone->area for restore

                _insert(_build_payload("intrusion_alarm_system_activate", z_no, a_no))
                log.info("[HIK->Dexter] cidEvent activate -> zone=%s area=%s", z_no, a_no)

        else:
            # Restore — only fire if a previous activate exists in this session.
            # If _zone_area_map is empty, panel is in normal condition — drop entirely.
            with _state_lock:
                if not _zone_area_map:
                    log.debug("[HIK-CID] restore suppressed — no active alarm in session")
                    return
                # Burst gate: process restore only once per CID_BURST_WINDOW
                last_poll = _cid_last_event.get("_poll_inactive", 0)
                if now - last_poll < CID_BURST_WINDOW:
                    return
                _cid_last_event["_poll_inactive"] = now
                restore_pairs = list(_zone_area_map.items())

            # For each active zone, poll to confirm it has actually cleared.
            # A zone that is still alarming stays in _zone_area_map.
            # Only zones confirmed clear get a restore payload.
            cleared_pairs = []
            still_active  = {}
            for z_no, a_no in restore_pairs:
                if _is_zone_still_alarming(z_no):
                    log.debug("[HIK-CID] zone=%s still alarming — restore suppressed", z_no)
                    still_active[z_no] = a_no
                else:
                    cleared_pairs.append((z_no, a_no))

            with _state_lock:
                # Rebuild map with only zones still alarming
                _zone_area_map.clear()
                _zone_area_map.update(still_active)

            for z_no, a_no in cleared_pairs:
                _insert(_build_payload("intrusion_alarm_system_activate_restored", z_no, a_no))
                log.info("[HIK->Dexter] cidEvent restore -> zone=%s area=%s", z_no, a_no)

        return

    # ── armStatus ─────────────────────────────────────────────────────────────
    if ev_type == "armStatus":
        log_type = _ARM_STATE_MAP.get(event.get("armState", ""), "intrusion_alarm_system_arm")
        _insert(_build_payload(log_type, zone_no, area))
        log.info("[HIK->Dexter] armStatus(%s) -> %s", event.get("armState", "?"), log_type)
        return

    # ── All other events ──────────────────────────────────────────────────────
    log_type = _DEXTER_EVENT_MAP.get(ev_type) or ("hik_" + ev_type.lower())
    _insert(_build_payload(log_type, zone_no, area))
    log.info("[HIK->Dexter] %s -> %s zone=%s area=%s", ev_type, log_type, zone_no, area)

# ─────────────────────────────────────────────────────────────────────────────
# Arm / Disarm control
# ─────────────────────────────────────────────────────────────────────────────
def _part_payload(pids, code=""):
    return {"SubSysList": [{"SubSys": {"id": p, **({"moduleOperateCode": code} if code else {})}}
                            for p in pids]}

def arm_away(partition_ids, operate_code=""):
    r = _api_put("/ISAPI/SecurityCP/control/arm?format=json",
                 _part_payload(partition_ids, operate_code))
    ok = r is not None and r.status_code == 200
    log.info("[HIK] arm_away %s -> %s", partition_ids, "OK" if ok else "FAIL"); return ok

def arm_stay(partition_ids, operate_code=""):
    r = _api_put("/ISAPI/SecurityCP/control/armHome?format=json",
                 _part_payload(partition_ids, operate_code))
    ok = r is not None and r.status_code == 200
    log.info("[HIK] arm_stay %s -> %s", partition_ids, "OK" if ok else "FAIL"); return ok

def disarm(partition_ids, operate_code=""):
    r = _api_put("/ISAPI/SecurityCP/control/disarm?format=json",
                 _part_payload(partition_ids, operate_code))
    ok = r is not None and r.status_code == 200
    log.info("[HIK] disarm %s -> %s", partition_ids, "OK" if ok else "FAIL"); return ok

def clear_alarm(partition_ids, operate_code=""):
    r = _api_put("/ISAPI/SecurityCP/control/clearAlarm?format=json",
                 _part_payload(partition_ids, operate_code))
    ok = r is not None and r.status_code == 200
    log.info("[HIK] clear_alarm %s -> %s", partition_ids, "OK" if ok else "FAIL"); return ok

def bypass_zone(zone_id, dev_index=""):
    try:
        params = {"format": "json"}
        if dev_index:
            params["devIndex"] = dev_index
        r = _SESSION.put(_BASE_URL + f"/ISAPI/SecurityCP/control/bypass/{zone_id}",
                         auth=_AUTH, params=params, timeout=10)
        ok = r.status_code == 200
        log.info("[HIK] bypass_zone %s -> %s", zone_id, "OK" if ok else "FAIL"); return ok
    except Exception as e:
        log.warning("[HIK] bypass_zone %s failed: %s", zone_id, e); return False

# ─────────────────────────────────────────────────────────────────────────────
# Alert stream thread
# ─────────────────────────────────────────────────────────────────────────────
def _stream_alert(stop_event: threading.Event):
    url = _BASE_URL + "/ISAPI/Event/notification/alertStream"
    reconnects = 0
    while not stop_event.is_set():
        log.info("[HIK] alertStream connect (attempt %d)", reconnects + 1)
        try:
            resp = _SESSION.get(url, auth=_AUTH,
                                headers={"Connection": "keep-alive"},
                                stream=True, timeout=(10, HEARTBEAT_TIMEOUT))
            if resp.status_code != 200:
                log.warning("[HIK] alertStream HTTP %d — retry 5s", resp.status_code)
                time.sleep(5); reconnects += 1; continue

            ct = resp.headers.get("Content-Type", "")
            bm = re.search(r"boundary=(\S+)", ct)
            boundary = bm.group(1).encode() if bm else b"AaB03x"
            log.info("[HIK] alertStream connected. boundary=%s", boundary.decode())
            dexter_state_hook(True)

            buf = b""; last_data = time.time()
            for chunk in resp.iter_content(chunk_size=4096):
                if stop_event.is_set():
                    break
                if not chunk:
                    continue
                last_data = time.time()
                buf += chunk
                while b"--" + boundary in buf:
                    parts = buf.split(b"--" + boundary, 1)
                    block_raw, buf = parts[0], parts[1]
                    body = (block_raw.split(b"\r\n\r\n", 1)[1]
                            if b"\r\n\r\n" in block_raw else block_raw)
                    text = body.decode("utf-8", errors="ignore").strip()
                    if not text or text == "--":
                        continue
                    event = _parse_event_block(text)
                    if event:
                        ev = event.get("eventType", "?")
                        if ev == "heartBeat":
                            log.debug("[HIK] heartbeat")
                        else:
                            log.info("[HIK] Event: %s zone=%s partition=%s eventState=%s",
                                     ev, event.get("zoneID"),
                                     event.get("partitionID"),
                                     event.get("eventState", ""))
                        dexter_event_hook(event)
                if time.time() - last_data > HEARTBEAT_TIMEOUT:
                    log.warning("[HIK] Heartbeat timeout — reconnecting")
                    break

        except requests.exceptions.Timeout:
            log.warning("[HIK] alertStream timeout")
        except requests.exceptions.ConnectionError as e:
            log.warning("[HIK] alertStream conn error: %s", e)
        except Exception as e:
            log.error("[HIK] alertStream error: %s", e)

        if not stop_event.is_set():
            dexter_state_hook(False)
            reconnects += 1
            log.info("[HIK] Reconnecting in 5s...")
            time.sleep(5)

# ─────────────────────────────────────────────────────────────────────────────
# Supervision poll thread — heartbeat + fault detection every 30s
# ─────────────────────────────────────────────────────────────────────────────
def _supervision_loop(stop_event: threading.Event):
    last_ok = time.time()
    while not stop_event.is_set():
        time.sleep(SUPERVISION_INTERVAL)
        if stop_event.is_set():
            break

        r = _api_get("/ISAPI/SecurityCP/status/subSystems?format=json", timeout=8)
        if r:
            last_ok = time.time()
            dexter_state_hook(True)
            _send_hik_heartbeat("online", force=False)
            # Poll systemFault + HostStatus for battery/power/tamper faults
            _poll_system_fault()
        else:
            if time.time() - last_ok > SUPERVISION_TIMEOUT:
                log.warning("[HIK] Panel unreachable — firing offline")
                dexter_state_hook(False)


# ─────────────────────────────────────────────────────────────────────────────
# Status poll thread — extended health/telemetry every STATUS_POLL_INTERVAL
# Polls: batteries, communication, exDevStatus, sirenStatus,
#        outputModStatus, zones detail, host detail
# ─────────────────────────────────────────────────────────────────────────────
def _status_poll_loop(stop_event: threading.Event):
    # Stagger start by 60s so it doesn't clash with startup supervision poll
    time.sleep(60)
    while not stop_event.is_set():
        if _is_integration_active():
            _poll_all_status(force=False)   # send only if data changed
        time.sleep(STATUS_POLL_INTERVAL)
        if stop_event.is_set():
            break

# ─────────────────────────────────────────────────────────────────────────────
# Watchdog thread
# ─────────────────────────────────────────────────────────────────────────────
def _watchdog_loop(stop_event: threading.Event):
    while not stop_event.is_set():
        _sd_notify_watchdog()
        time.sleep(WATCHDOG_INTERVAL)

# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────
def main():
    log.info("[HIK] Hikvision DS-PHA64-LP(B) — Dexter HMS BAS Integration")
    log.info("[HIK] Panel: %s:%d  Model: %s", PANEL_IP, PANEL_PORT, PANEL_MODEL)

    for attempt in range(1, 6):
        r = _api_get("/ISAPI/System/deviceInfo", timeout=8)
        if r:
            log.info("[HIK] Panel reachable: model=%s serial=%s firmware=%s",
                     _xml_val("model", r.text),
                     _xml_val("serialNumber", r.text),
                     _xml_val("firmwareVersion", r.text))
            break
        log.warning("[HIK] Not reachable (attempt %d/5) — retry in 10s...", attempt)
        time.sleep(10)
    else:
        log.error("[HIK] Cannot reach panel. Exiting.")
        sys.exit(1)

    _check_status_host_capability()
    _send_hik_heartbeat("online", force=True)
    _poll_system_fault()   # check battery/power faults immediately at startup
    _poll_all_status(force=True)     # initial full status snapshot — always send

    stop_event = threading.Event()
    threads = [
        threading.Thread(target=_stream_alert,     args=(stop_event,),
                         name="alertStream",  daemon=True),
        threading.Thread(target=_supervision_loop, args=(stop_event,),
                         name="supervision",  daemon=True),
        threading.Thread(target=_status_poll_loop, args=(stop_event,),
                         name="statusPoll",   daemon=True),
        threading.Thread(target=_watchdog_loop,    args=(stop_event,),
                         name="watchdog",     daemon=True),
    ]
    for t in threads:
        t.start()
    log.info("[HIK] Threads started: %s", [t.name for t in threads])

    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        pass
    finally:
        log.info("[HIK] Shutting down...")
        stop_event.set()
        for t in threads:
            t.join(timeout=5)
        log.info("[HIK] Stopped.")


if __name__ == "__main__":
    # Exit 0 immediately if integration is disabled — Docker restart:on-failure
    # will not relaunch on exit 0, keeping the container in "disabled" state.
    import logical_params_module as _lpm
    _lpm.initialize_database()
    if _lpm.get_parameter("active_integration_hik_bas") != 1:
        import logging as _lg, sys as _sys
        _lg.getLogger(__name__).info(
            "[hikvision_bas_integration.py] active_integration_hik_bas=0"
            " -- integration disabled, exiting cleanly"
        )
        _sys.exit(0)
    main()
