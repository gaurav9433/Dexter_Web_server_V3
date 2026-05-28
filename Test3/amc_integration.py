#!/usr/bin/env python3
"""
amc_integration.py — AMC X412B Active Integration for Dexter HMS
SIA-DCS + ADM-CID Protocol Parser

Changes from original:
  DEXTER-01 : Active integration guard — exits cleanly if flag is 0 in DB
  DEXTER-02 : dexter_event_hook() — maps AMC events to Dexter HMS sendData2TB payloads
  DEXTER-03 : dexter_state_hook() — updates logical_params with AMC panel online/offline
  DEXTER-04 : Uses db_connection.get_connection() instead of bare sqlite3
  DEXTER-05 : Uses logical_params_module for active integration flag check
  DEXTER-06 : Heartbeat_BAS online/offline fired on supervision state change
  DEXTER-07 : Logging via standard logger (not basicConfig) for journalctl
"""

import socket
import threading
import time
import re
import json
import logging
import sys
import os
from datetime import datetime
from typing import Dict, List, Optional, Tuple

# ── systemd watchdog notify (stdlib only — no pip install needed) ────────────
def _sd_notify_watchdog():
    """Send WATCHDOG=1 to systemd via NOTIFY_SOCKET. Safe outside systemd."""
    ns = os.environ.get('NOTIFY_SOCKET')
    if not ns:
        return
    try:
        if ns.startswith('@'):
            ns = '\x00' + ns[1:]
        s = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        s.connect(ns)
        s.sendall(b'WATCHDOG=1')
        s.close()
    except Exception as _e:
        log.debug('[sd_notify] watchdog ping failed: %s', _e)

# ── Dexter HMS imports ────────────────────────────────────────────────────────
sys.path.insert(0, '/home/pi/Test3')

# DEXTER-01: Active integration guard
# If active_integration_amc_bas == 0 in DB, exit cleanly.
# systemd RestartPreventExitStatus=0 1 ensures no restart on clean exit.
try:
    import logical_params_module
    _flag = logical_params_module.get_parameter("active_integration_amc_bas")
    if _flag != 1:
        logging.info("[AMC] active_integration_amc_bas=0 — integration disabled. Exiting.")
        sys.exit(0)
except Exception as _e:
    logging.warning("[AMC] Could not read active_integration_amc_bas flag: %s — continuing.", _e)

# DEXTER-04: payload insert with cap
try:
    from payload_manager import insert_with_cap
    _HAS_PAYLOAD_MANAGER = True
except ImportError:
    insert_with_cap = None
    _HAS_PAYLOAD_MANAGER = False

# DEXTER-06: heartbeat insert into buffer.db
try:
    from buffer_manager import insert_json_to_db
    _HAS_BUFFER_MANAGER = True
except ImportError:
    insert_json_to_db = None
    _HAS_BUFFER_MANAGER = False

# RTC for timestamps (same as sendData2TB in main)
try:
    import SDL_DS1307
    _ds1307 = SDL_DS1307.SDL_DS1307(1, 0x68)
    _HAS_RTC = True
except Exception:
    _HAS_RTC = False

# ── CONFIG ────────────────────────────────────────────────────────────────────
HOST               = "0.0.0.0"
PORT               = 5000
PANEL_MODEL        = "AMC_X412V"
SUPERVISION_TIMEOUT  = 600   # 10 min
SUPERVISION_INTERVAL = 30

# ── DEXTER-07: Logger ─────────────────────────────────────────────────────────
log = logging.getLogger("dexter-amc-bas")

# ── AMC → Dexter HMS log_type mapping ────────────────────────────────────────
# Maps AMC event names to Dexter HMS sendData2TB log_type strings.
# Events not in this map are sent with log_type = amc_<event_lower>
_DEXTER_EVENT_MAP = {
    # Intrusion / Burglary
    "BURGLARY_ALARM":                "intrusion_alarm_system_activate",
    "BURGLARY_RESTORE":              "intrusion_alarm_system_activation_restored",
    "INTERIOR_ALARM":                "intrusion_alarm_system_activate",
    "PERIMETER_ALARM":               "intrusion_alarm_system_activate",
    "CONFIRMED_ALARM":               "intrusion_alarm_system_activate",
    "SILENT_ALARM":                  "intrusion_alarm_system_activate",
    "PANIC_ALARM":                   "intrusion_alarm_system_activate",
    "PANIC_RESTORE":                 "intrusion_alarm_system_activation_restored",
    "COERCION_ALARM":                "intrusion_alarm_system_activate",
    "COERCION_RESTORE":              "intrusion_alarm_system_activation_restored",

    # Fire
    "FIRE_ALARM":                    "fire_alarm_system_activate",
    "SMOKE_ALARM":                   "fire_alarm_system_activate",
    "FIRE_RESTORE":                  "fire_alarm_system_activation_restored",

    # Tamper
    "TAMPER_ALARM":                  "intrusion_alarm_system_fault",
    "TAMPER_RESTORE":                "intrusion_alarm_system_fault_condition_restored",
    "TAMPER_PERIPHERAL":             "intrusion_alarm_system_fault",
    "TAMPER_PERIPHERAL_RESTORE":     "intrusion_alarm_system_fault_condition_restored",
    "RF_DEVICE_TAMPER":              "intrusion_alarm_system_fault",
    "RF_DEVICE_TAMPER_RESTORE":      "intrusion_alarm_system_fault_condition_restored",

    # Power / AC
    "SYSTEM_AC_LOSS":                "amc_battery_on",
    "SYSTEM_AC_RESTORE":             "amc_mains_on",
    "SYSTEM_LOW_BATTERY":            "amc_battery_low",
    "SYSTEM_LOW_BATTERY_RESTORE":    "amc_battery_low_restore",

    # System
    "SYSTEM_RESTART":                "amc_system_restart",
    "SYSTEM_RESET":                  "amc_system_reset",
    "ARMING_FAILED":                 "intrusion_alarm_system_fault",
    "ARMING_FAILED_RESTORE":         "intrusion_alarm_system_fault_condition_restored",

    # Arm / Disarm → map to system on/off
    #"SYSTEM_OPEN":                   "intrusion_alarm_system_off",
    "SYSTEM_OPEN":                   "intrusion_alarm_system_disarm",
    #"SYSTEM_CLOSE":                  "intrusion_alarm_system_on",
    "SYSTEM_CLOSE":                  "intrusion_alarm_system_arm",
    "AUTO_OPEN":                     "intrusion_alarm_system_off",
    "AUTO_CLOSE":                    "intrusion_alarm_system_on",
    "DISARMED":                      "intrusion_alarm_system_off",
    "DISARMED_GROUP":                "intrusion_alarm_system_off",

    # RF
    "RF_JAM":                        "intrusion_alarm_system_fault",
    "RF_JAM_RESTORE":                "intrusion_alarm_system_fault_condition_restored",
    "RF_NO_SUPERVISION":             "intrusion_alarm_system_fault",
    "RF_SUPERVISION_RESTORE":        "intrusion_alarm_system_fault_condition_restored",

    # Supervision (panel alive test)
    "SUPERVISORY_TEST":              "heartbeat_BAS",
    "PERIODIC_TEST":                 "heartbeat_BAS",

    # Supervision — panel offline/online
    "PANEL_OFFLINE":                 "heartbeat_BAS_offline",
    #"MISSED_ALARM":                  "intrusion_alarm_system_activate",
}


def _get_rtc_datetime() -> Tuple[str, str, str, str, str]:
    """Read RTC timestamp. Falls back to system time if RTC unavailable."""
    if _HAS_RTC:
        try:
            return (
                str(_ds1307._read_date()).zfill(2),
                str(_ds1307._read_month()).zfill(2),
                str(_ds1307._read_year()).zfill(2),
                str(_ds1307._read_hours()).zfill(2),
                str(_ds1307._read_minutes()).zfill(2),
            )
        except Exception:
            pass
    now = datetime.now()
    return (
        str(now.day).zfill(2),
        str(now.month).zfill(2),
        str(now.year % 100).zfill(2),
        str(now.hour).zfill(2),
        str(now.minute).zfill(2),
    )


def _build_payload(log_type: str, zone_no=None, area=None) -> str:
    """
    Build Dexter HMS Telemetry Format Spec v1.0 payload.
    {"log_type":"<event>","zone_no":<zone>,"area":<area>,"date":"DD:MM:YY","time":"HH:MM"}
    """
    dd, mm, yy, hh, mi = _get_rtc_datetime()
    date_str = f"{dd}:{mm}:{yy}"
    time_str = f"{hh}:{mi}"

    if isinstance(log_type, (dict, list)):
        log_type_t = json.dumps(log_type)
    else:
        log_type_t = f'"{log_type}"'

    zone_val = str(zone_no) if zone_no is not None and zone_no != 0 else "null"
    area_val = str(area) if area is not None and area != 0 else "null"

    return (
        '{"log_type":' + log_type_t +
        ',"zone_no":'  + zone_val   +
        ',"area":'     + area_val   +
        ',"date":"'    + date_str   + '"' +
        ',"time":"'    + time_str   + '"}'
    )


# ── SIA / CID event maps (unchanged from original) ────────────────────────────
SIA_EVENT_MAP = {
    "BA": ("BURGLARY_ALARM",              "CRITICAL"),
    "BR": ("BURGLARY_RESTORE",            "INFO"),
    "FA": ("FIRE_ALARM",                  "CRITICAL"),
    "FR": ("FIRE_RESTORE",                "INFO"),
    "TA": ("TAMPER_ALARM",               "WARNING"),
    "TR": ("TAMPER_RESTORE",             "INFO"),
    "AT": ("SYSTEM_AC_LOSS",             "WARNING"),
    "AR": ("SYSTEM_AC_RESTORE",          "INFO"),
    "YT": ("SYSTEM_LOW_BATTERY",         "WARNING"),
    "YR": ("SYSTEM_LOW_BATTERY_RESTORE", "INFO"),
    "OG": ("SYSTEM_OPEN",               "INFO"),
    "CG": ("SYSTEM_CLOSE",              "INFO"),
    "OA": ("AUTO_OPEN",                 "INFO"),
    "CA": ("AUTO_CLOSE",                "INFO"),
    "XQ": ("RF_JAM",                    "WARNING"),
    "XH": ("RF_JAM_RESTORE",            "INFO"),
    "XT": ("RF_DEVICE_LOW_BATTERY",     "WARNING"),
    "XR": ("RF_DEVICE_BATTERY_RESTORE", "INFO"),
    "US": ("RF_NO_SUPERVISION",         "WARNING"),
    "UR": ("RF_SUPERVISION_RESTORE",    "INFO"),
    "XS": ("RF_DEVICE_TAMPER",          "WARNING"),
    "XJ": ("RF_DEVICE_TAMPER_RESTORE",  "INFO"),
    "ES": ("TAMPER_PERIPHERAL",         "WARNING"),
    "EJ": ("TAMPER_PERIPHERAL_RESTORE", "INFO"),
    "ET": ("FAIL_PERIPHERAL",           "WARNING"),
    "ER": ("FAIL_PERIPHERAL_RESTORE",   "INFO"),
    "LB": ("PROGRAMMING_START",         "INFO"),
    "LS": ("PROGRAMMING_END",           "INFO"),
    "RR": ("SYSTEM_RESTART",            "INFO"),
    "DD": ("WRONG_CODE",                "WARNING"),
    "BB": ("ZONE_BYPASS",               "INFO"),
    "BU": ("ZONE_BYPASS_RESTORE",       "INFO"),
    "UT": ("INPUT_FAILURE",             "WARNING"),
    "UJ": ("INPUT_FAILURE_RESTORE",     "INFO"),
    "UA": ("TECHNOLOGICAL_INPUT",       "INFO"),
    "HA": ("COERCION_ALARM",            "CRITICAL"),
    "HR": ("COERCION_RESTORE",          "INFO"),
    "PA": ("PANIC_ALARM",               "CRITICAL"),
    "PR": ("PANIC_RESTORE",             "INFO"),
    "CI": ("ARMING_FAILED",             "WARNING"),
    "OI": ("ARMING_FAILED_RESTORE",     "INFO"),
    "LT": ("PSTN_FAILURE",              "WARNING"),
    "LR": ("PSTN_RESTORE",              "INFO"),
    "RP": ("SUPERVISORY_TEST",          "INFO"),
}

CID_EVENT_MAP = {
    "100": ("FIRE_ALARM",              "CRITICAL"),
    "101": ("SMOKE_ALARM",             "CRITICAL"),
    "110": ("FIRE_ALARM",              "CRITICAL"),
    "120": ("PANIC_ALARM",             "CRITICAL"),
    "130": ("BURGLARY_ALARM",          "CRITICAL"),
    "131": ("PERIMETER_ALARM",         "CRITICAL"),
    "132": ("INTERIOR_ALARM",          "CRITICAL"),
    "137": ("TAMPER_ALARM",            "WARNING"),
    "139": ("CONFIRMED_ALARM",         "CRITICAL"),
    "146": ("SILENT_ALARM",            "CRITICAL"),
    "150": ("24H_AUXILIARY_ALARM",     "CRITICAL"),
    "154": ("WATER_LEAK_ALARM",        "WARNING"),
    "300": ("SYSTEM_TROUBLE",          "WARNING"),
    "301": ("AC_LOSS",                 "WARNING"),
    "302": ("LOW_BATTERY",             "WARNING"),
    "305": ("SYSTEM_RESET",            "INFO"),
    "306": ("PROGRAMMING_CHANGE",      "INFO"),
    "333": ("TAMPER",                  "WARNING"),
    "381": ("RF_SUPERVISION_TROUBLE",  "WARNING"),
    "383": ("RF_SENSOR_TAMPER",        "WARNING"),
    "401": ("DISARMED",                "INFO"),
    "402": ("DISARMED_GROUP",          "INFO"),
    "403": ("AUTO_DISARMED",           "INFO"),
    "407": ("REMOTE_ARM_DISARM",       "INFO"),
    "408": ("QUICK_ARM",               "INFO"),
    "409": ("KEYSWITCH_ARM_DISARM",    "INFO"),
    "570": ("ZONE_BYPASS",             "INFO"),
    "602": ("PERIODIC_TEST",           "INFO"),
    "625": ("DATE_TIME_CHANGED",       "INFO"),
    "627": ("PROGRAM_MODE_ENTRY",      "INFO"),
}


# ── CRC-16 (unchanged) ────────────────────────────────────────────────────────
def crc16(data: bytes) -> int:
    crc = 0
    for byte in data:
        temp = byte
        for _ in range(8):
            temp ^= crc & 1
            crc >>= 1
            if temp & 1:
                crc ^= 0xA001
            temp >>= 1
    return crc


def validate_crc(raw_line: str) -> bool:
    try:
        if len(raw_line) < 8:
            return False
        expected_crc = int(raw_line[:4], 16)
        body = raw_line[4:]
        computed = crc16(body.encode("ascii", errors="ignore"))
        return computed == expected_crc
    except Exception:
        return False


# ── Parsers (unchanged) ───────────────────────────────────────────────────────
def parse_sia_frame(raw: str) -> Optional[dict]:
    if '"SIA-DCS"' not in raw:
        return None
    seq_m = re.search(r'"SIA-DCS"(\d{4})', raw)
    seq = int(seq_m.group(1)) if seq_m else None
    acct_m = re.search(r'#(\w+)\|', raw)
    account = acct_m.group(1) if acct_m else "UNKNOWN"
    payload_m = re.search(r'\[([^\]]+)\]', raw)
    if not payload_m:
        return None
    payload = payload_m.group(1)
    event_m = re.search(r'\|[NR]ri(\d{2})/([A-Za-z]{2})(\d{2})', payload)
    if not event_m:
        event_m2 = re.search(r'\|[NR]([A-Za-z]{2})(\d{2})', payload)
        if event_m2:
            area = 0
            code = event_m2.group(1).upper()
            zone = int(event_m2.group(2))
        else:
            log.warning("SIA payload unrecognised: %s", payload)
            return None
    else:
        area = int(event_m.group(1))
        code = event_m.group(2).upper()
        zone = int(event_m.group(3))
    qualifier_m = re.search(r'\|([NR])', payload)
    qualifier = qualifier_m.group(1) if qualifier_m else "N"
    event_name, severity = SIA_EVENT_MAP.get(code, ("UNKNOWN_" + code, "WARNING"))
    return {
        "protocol": "SIA-DCS", "panel": PANEL_MODEL, "account": account,
        "sequence": seq, "qualifier": qualifier, "area": area, "zone": zone,
        "code": code, "event": event_name, "severity": severity,
        "timestamp": datetime.utcnow().isoformat() + "Z", "raw": raw,
    }


def parse_cid_frame(raw: str) -> Optional[dict]:
    if '"ADM-CID"' not in raw:
        return None
    seq_m = re.search(r'"ADM-CID"(\d{4})', raw)
    seq = int(seq_m.group(1)) if seq_m else None
    acct_m = re.search(r'#(\w+)\|', raw)
    account = acct_m.group(1) if acct_m else "UNKNOWN"
    payload_m = re.search(r'\[([^\]]+)\]', raw)
    if not payload_m:
        return None
    payload = payload_m.group(1)
    cid_m = re.search(r'\|(\d)(\d{3})\s+(\d{2})\s+(\d{3})', payload)
    if not cid_m:
        return None
    qualifier  = int(cid_m.group(1))
    code       = cid_m.group(2)
    partition  = int(cid_m.group(3))
    zone_user  = int(cid_m.group(4))
    is_restore = (qualifier == 3)
    event_name, severity = CID_EVENT_MAP.get(code, ("UNKNOWN_" + code, "WARNING"))
    if is_restore and not event_name.endswith("RESTORE"):
        event_name += "_RESTORE"
        severity = "INFO"
    return {
        "protocol": "ADM-CID", "panel": PANEL_MODEL, "account": account,
        "sequence": seq, "qualifier": qualifier, "partition": partition,
        "zone": zone_user, "code": code, "event": event_name, "severity": severity,
        "timestamp": datetime.utcnow().isoformat() + "Z", "raw": raw,
    }


def parse_frame(raw: str) -> Optional[dict]:
    if '"SIA-DCS"' in raw:
        return parse_sia_frame(raw)
    elif '"ADM-CID"' in raw:
        return parse_cid_frame(raw)
    elif '"NULL"' in raw:
        acct_m = re.search(r'#(\w+)', raw)
        account = acct_m.group(1) if acct_m else "UNKNOWN"
        log.debug("NULL heartbeat from account=%s", account)
        with integration._lock:
            if account in integration._panels:
                integration._panels[account].last_seen = time.time()
                integration._panels[account].online = True
        return None
    return None


def build_ack(raw: str) -> bytes:
    try:
        seq_m   = re.search(r'"(?:SIA-DCS|ADM-CID|NULL)"(\d{4})', raw)
        acct_m  = re.search(r'#(\w+)', raw)
        seq     = seq_m.group(1)  if seq_m  else "0000"
        account = acct_m.group(1) if acct_m else "0000"
        body         = f'"ACK"{seq}L0#{account}[]'
        length_hex   = f"{len(body):04X}"
        full_body    = length_hex + body
        crc_val      = crc16(full_body.encode("ascii"))
        crc_hex      = f"{crc_val:04X}"
        return f"\n{crc_hex}{full_body}\r".encode("ascii")
    except Exception as e:
        log.error("ACK build error: %s", e)
        return b""


# ── PanelState (unchanged) ────────────────────────────────────────────────────
class PanelState:
    def __init__(self, account: str):
        self.account      = account
        self.online       = True
        self.last_seen    = time.time()
        self.connected_at = time.time()
        self.zones        = {}
        self.areas        = {}
        self.flags = {"ac_loss": False, "low_battery": False, "tamper": False, "rf_jam": False}

    def update(self, event: dict):
        self.online    = True
        self.last_seen = time.time()
        ev   = event["event"]
        zone = event.get("zone")
        area = event.get("area", 0)
        if zone is not None and zone != 0:
            self.zones.setdefault(zone, {"state": "NORMAL", "last_event": None, "alarm_seen": False})
            if "ALARM" in ev:
                self.zones[zone]["state"]      = "ALARM"
                self.zones[zone]["alarm_seen"] = True
            elif "RESTORE" in ev:
                self.zones[zone]["state"]      = "NORMAL"
                self.zones[zone]["alarm_seen"] = False
            elif "BYPASS" in ev and "RESTORE" not in ev:
                self.zones[zone]["state"] = "BYPASSED"
            elif "TAMPER" in ev and "RESTORE" not in ev:
                self.zones[zone]["state"] = "TAMPER"
            self.zones[zone]["last_event"] = ev
        if area is not None:
            self.areas.setdefault(area, {"armed": False})
            if "CLOSE" in ev:
                self.areas[area]["armed"] = True
            elif "OPEN" in ev or "DISARMED" in ev:
                self.areas[area]["armed"] = False
        self.flags["ac_loss"]     = ev == "SYSTEM_AC_LOSS"     or (self.flags["ac_loss"]     and ev != "SYSTEM_AC_RESTORE")
        self.flags["low_battery"] = ev == "SYSTEM_LOW_BATTERY" or (self.flags["low_battery"] and ev != "SYSTEM_LOW_BATTERY_RESTORE")
        self.flags["rf_jam"]      = ev == "RF_JAM"             or (self.flags["rf_jam"]      and ev != "RF_JAM_RESTORE")
        self.flags["tamper"]      = (ev in ("TAMPER_ALARM","TAMPER_PERIPHERAL","RF_DEVICE_TAMPER")) or \
                                    (self.flags["tamper"] and "TAMPER_RESTORE" not in ev)

    def to_dict(self):
        return {
            "account": self.account, "panel": PANEL_MODEL, "online": self.online,
            "last_seen":    datetime.utcfromtimestamp(self.last_seen).isoformat() + "Z",
            "connected_at": datetime.utcfromtimestamp(self.connected_at).isoformat() + "Z",
            "flags": self.flags, "areas": self.areas,
            "zones": {k: {fk: fv for fk, fv in v.items() if fk != "alarm_seen"} for k, v in self.zones.items()},
        }


# ── AMCIntegration (unchanged core, Dexter hooks added) ───────────────────────
class AMCIntegration:
    def __init__(self):
        self._panels: Dict[str, PanelState] = {}
        self._lock = threading.Lock()
        self._event_callbacks = []
        self._state_callbacks  = []

    def on_event(self, fn):
        self._event_callbacks.append(fn)
        return fn

    def on_state_change(self, fn):
        self._state_callbacks.append(fn)
        return fn

    def process_raw(self, raw: str):
        if not raw.strip():
            return
        if not validate_crc(raw):
            log.debug("CRC mismatch: %s", raw[:40])
        event = parse_frame(raw)
        if not event:
            if '"NULL"' not in raw:
                log.warning("Unparsed frame: %s", raw)
            return
        log.info("[%s] %s | zone=%s area=%s severity=%s",
                 event["protocol"], event["event"],
                 event.get("zone"), event.get("area"), event["severity"])
        account = event["account"]
        with self._lock:
            if account not in self._panels:
                self._panels[account] = PanelState(account)
                log.info("New panel registered | account=%s", account)
            panel = self._panels[account]
            seq = event.get("sequence")
            if seq is not None:
                last_seq = getattr(panel, "_last_seq", None)
                if last_seq is not None:
                    expected = (last_seq % 9999) + 1
                    if seq != expected and seq != 1:
                        gap = seq - last_seq if seq > last_seq else (9999 - last_seq + seq)
                        log.warning("SEQUENCE GAP | account=%s expected=%d got=%d gap=%d", account, expected, seq, gap)
                panel._last_seq = seq
            panel.update(event)
            state_snapshot = panel.to_dict()
        for cb in self._event_callbacks:
            try: cb(event)
            except Exception as e: log.error("Event callback error: %s", e)
        for cb in self._state_callbacks:
            try: cb(state_snapshot)
            except Exception as e: log.error("State callback error: %s", e)

    def get_panel_state(self, account: str) -> Optional[dict]:
        with self._lock:
            p = self._panels.get(account)
            return p.to_dict() if p else None

    def get_all_states(self) -> List[Dict]:
        with self._lock:
            return [p.to_dict() for p in self._panels.values()]

    def start_supervision(self):
        def _loop():
            while True:
                time.sleep(SUPERVISION_INTERVAL)
                now = time.time()
                with self._lock:
                    for acc, panel in self._panels.items():
                        if panel.online and now - panel.last_seen > SUPERVISION_TIMEOUT:
                            panel.online = False
                            silence_mins = int((now - panel.last_seen) / 60)
                            log.warning("[OFFLINE] Panel account=%s — silent for %d min", acc, silence_mins)
                            if _HAS_BUFFER_MANAGER:
                                insert_json_to_db(json.dumps({"heartbeat_BAS_offline": "LinkFail"}))
                                log.info("[AMC] heartbeat_BAS_offline → LinkFail")
                            offline_event = {
                                "protocol": "SUPERVISION", "panel": PANEL_MODEL, "account": acc,
                                "event": "PANEL_OFFLINE", "severity": "CRITICAL",
                                "silence_mins": silence_mins,
                                "timestamp": datetime.utcnow().isoformat() + "Z", "raw": "",
                            }
                            for cb in self._event_callbacks:
                                try: cb(offline_event)
                                except Exception: pass
        threading.Thread(target=_loop, daemon=True).start()


integration = AMCIntegration()


# ── TCP SERVER (unchanged) ────────────────────────────────────────────────────
def handle_client(conn: socket.socket, addr):
    log.info("AMC panel connected from %s:%s", addr[0], addr[1])
    conn.settimeout(5.0)
    buffer = b""
    try:
        while True:
            try:
                data = conn.recv(4096)
            except socket.timeout:
                break
            if not data:
                break
            buffer += data
            while True:
                for delim in (b"\r\n", b"\n", b"\r"):
                    if delim in buffer:
                        line, buffer = buffer.split(delim, 1)
                        text = line.decode("ascii", errors="ignore").strip()
                        if text:
                            ack = build_ack(text)
                            if ack:
                                try:
                                    conn.sendall(ack)
                                except Exception as e:
                                    log.error("ACK send failed: %s", e)
                            integration.process_raw(text)
                        break
                else:
                    break
    except (ConnectionResetError, socket.timeout):
        pass
    except Exception as e:
        log.error("Client error: %s", e)
    finally:
        conn.close()
        log.info("AMC panel disconnected %s:%s", addr[0], addr[1])


def start_server():
    integration.start_supervision()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as srv:
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind((HOST, PORT))
        srv.listen(10)
        # Set accept timeout so the watchdog ping loop runs even when
        # no AMC panel is connected — prevents WatchdogSec expiry on idle.
        srv.settimeout(60.0)
        log.info("AMC X412B server listening on %s:%d", HOST, PORT)
        while True:
            # Feed systemd watchdog on every iteration — resets
            # WatchdogSec=1800 countdown. If server hangs beyond 30 min
            # without accepting or timing out, systemd kills the service.
            _sd_notify_watchdog()
            try:
                conn, addr = srv.accept()
                threading.Thread(target=handle_client, args=(conn, addr), daemon=True).start()
            except socket.timeout:
                continue  # no connection — loop back and ping watchdog again


# ── DEXTER-02: EVENT HOOK ─────────────────────────────────────────────────────

# AMC-DEDUP-FIX: Track active alarm keys so repeated ALARM events for the
# same zone/area are suppressed until a RESTORE clears them.
# The AMC panel sends the same alarm event repeatedly at intervals while the
# zone is still active. We only want to send the FIRST activation to SWatch.
# Key format: (amc_event_name, zone_no, area)
# A RESTORE event for the same zone/area clears the key so the next real
# alarm can fire again.
_active_alarm_keys: set = set()
_active_alarm_lock = __import__("threading").Lock()

# Events that can repeat while a zone is active — send only the first
_REPEATING_ALARM_EVENTS = {
    "BURGLARY_ALARM", "INTERIOR_ALARM", "PERIMETER_ALARM", "CONFIRMED_ALARM",
    "SILENT_ALARM", "PANIC_ALARM", "COERCION_ALARM",
    "FIRE_ALARM", "SMOKE_ALARM",
    "TAMPER_ALARM", "TAMPER_PERIPHERAL", "RF_DEVICE_TAMPER",
}

# Corresponding RESTORE events that clear the dedup key
_RESTORE_EVENTS = {
    "BURGLARY_RESTORE", "PANIC_RESTORE", "COERCION_RESTORE",
    "FIRE_RESTORE",
    "TAMPER_RESTORE", "TAMPER_PERIPHERAL_RESTORE", "RF_DEVICE_TAMPER_RESTORE",
}

# Map each RESTORE back to the ALARM event it clears (same zone/area key)
_RESTORE_TO_ALARM = {
    "BURGLARY_RESTORE":          "BURGLARY_ALARM",
    "PANIC_RESTORE":             "PANIC_ALARM",
    "COERCION_RESTORE":          "COERCION_ALARM",
    "FIRE_RESTORE":              "FIRE_ALARM",
    "TAMPER_RESTORE":            "TAMPER_ALARM",
    "TAMPER_PERIPHERAL_RESTORE": "TAMPER_PERIPHERAL",
    "RF_DEVICE_TAMPER_RESTORE":  "RF_DEVICE_TAMPER",
}


@integration.on_event
def dexter_event_hook(event: dict):
    """
    DEXTER-02: Map every AMC event to a Dexter HMS telemetry payload
    and insert into payloads.db via insert_with_cap().

    AMC-DEDUP-FIX: Repeating ALARM events (same event + zone + area) are
    suppressed after the first send. The dedup key is cleared when the
    corresponding RESTORE event arrives, allowing the next real alarm to fire.

    Priority mapping:
      1. _DEXTER_EVENT_MAP — known AMC events → standard Dexter log_type
      2. Unknown events    → "amc_<event_lower>" so nothing is lost
    """
    if not _HAS_PAYLOAD_MANAGER:
        log.warning("[AMC] payload_manager not available — event not stored: %s", event["event"])
        return

    amc_event = event.get("event", "UNKNOWN")
    zone_no   = event.get("zone")
    area      = event.get("area")

    # ── RESTORE: clear dedup key so next alarm fires ─────────────────────────
    if amc_event in _RESTORE_EVENTS:
        alarm_event = _RESTORE_TO_ALARM.get(amc_event)
        if alarm_event:
            key = (alarm_event, zone_no, area)
            with _active_alarm_lock:
                _active_alarm_keys.discard(key)
            log.debug("[AMC-DEDUP] RESTORE cleared key %s", key)

    # ── ALARM: suppress repeat, send only first occurrence ───────────────────
    if amc_event in _REPEATING_ALARM_EVENTS:
        key = (amc_event, zone_no, area)
        with _active_alarm_lock:
            if key in _active_alarm_keys:
                log.debug("[AMC-DEDUP] Suppressed repeat: %s zone=%s area=%s",
                          amc_event, zone_no, area)
                return          # already sent — do not send again until RESTORE
            _active_alarm_keys.add(key)
            log.info("[AMC-DEDUP] First occurrence — sending: %s zone=%s area=%s",
                     amc_event, zone_no, area)

    # Map to Dexter log_type
    log_type = _DEXTER_EVENT_MAP.get(amc_event)
    if log_type is None:
        # Unknown event — prefix with amc_ so it appears in SWatch
        log_type = "amc_" + amc_event.lower()

    payload = _build_payload(log_type, zone_no, area)
    insert_with_cap(payload)

    log.info("[AMC→Dexter] %s → log_type=%s zone=%s area=%s",
             amc_event, log_type, zone_no, area)


# ── DEXTER-03: STATE HOOK ─────────────────────────────────────────────────────
@integration.on_state_change
def dexter_state_hook(state: dict):
    """DEXTER-03: Online/offline tracked in-memory. No DB write needed."""
    pass


# ── PUBLIC STATUS FUNCTION (used by heartbeat_manager) ────────────────────────────
def check_amc_bas() -> str:
    """
    Returns 'Online' if at least one AMC panel is connected and recently seen.
    Returns 'Offline' otherwise.
    Called by heartbeat_manager check_amc_bas_fn.
    Same interface as check_texecom_bas() — no TCP probe needed;
    AMC panel pushes events to us so online/offline is tracked in memory.
    """
    states = integration.get_all_states()
    if not states:
        return "LinkFail"
    return "Online" if any(s["online"] for s in states) else "LinkFail"


# ── ENTRY POINT ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s -- %(message)s",
        handlers=[logging.StreamHandler()]
    )
    sys.stdout.reconfigure(encoding="utf-8")
    # Exit 0 immediately if integration is disabled — Docker restart:on-failure
    # will not relaunch on exit 0, keeping the container in "disabled" state.
    import logical_params_module as _lpm
    _lpm.initialize_database()
    if _lpm.get_parameter("active_integration_amc_bas") != 1:
        logging.getLogger(__name__).info(
            "[amc_integration.py] active_integration_amc_bas=0"
            " -- integration disabled, exiting cleanly"
        )
        sys.exit(0)
    start_server()
