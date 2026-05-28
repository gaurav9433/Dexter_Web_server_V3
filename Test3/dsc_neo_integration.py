#!/usr/bin/env python3
"""
dsc_neo_integration.py — DSC PowerSeries Neo HS2032 Active Integration
SIA-DCS + ADM-CID Protocol Receiver

STANDALONE TEST VERSION
=======================
Run this directly on the panel to verify TL280 communication before
integrating with the rest of Dexter HMS.

Usage:
    sudo python3 dsc_neo_integration.py

What it does:
    - Listens on TCP port 5001 for events from the TL280
    - Parses SIA-DCS and ADM-CID frames
    - Prints every received event to the console in a readable format
    - Sends correct ACK responses back to the TL280
    - Logs raw frames and parsed results to dsc_neo_test.log

TL280 Programming required (ask installer):
    [300][011]  Receiver IP  : Dexter HMS IP address
    [300][012]  Receiver port: 5002
    [300][013]  Protocol     : 03 = Contact ID   OR   04 = SIA
    [300][001]  Route        : 01 or 02

No Dexter HMS modules required — runs standalone.
Press Ctrl+C to stop.
"""

import socket
import threading
import time
import re
import logging
import sys
from datetime import datetime
from typing import Optional

# ── CONFIG ────────────────────────────────────────────────────────────────────
HOST     = "0.0.0.0"
PORT     = 5002
LOG_FILE = "dsc_neo_test.log"

# ── Logging: console + file ───────────────────────────────────────────────────
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
    ]
)
log = logging.getLogger("dsc-neo-test")

# ── Colour helpers ────────────────────────────────────────────────────────────
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

def _c(text, colour): return f"{colour}{text}{RESET}"
def ok(t):   return _c(t, GREEN)
def err(t):  return _c(t, RED)
def warn(t): return _c(t, YELLOW)
def info(t): return _c(t, CYAN)

# ── SIA-DCS Event Map ─────────────────────────────────────────────────────────
SIA_EVENT_MAP = {
    "BA": ("BURGLARY_ALARM",              "CRITICAL"),
    "BR": ("BURGLARY_RESTORE",            "INFO"),
    "BV": ("BURGLARY_VERIFIED",           "CRITICAL"),
    "BI": ("BURGLARY_CANCEL",             "INFO"),
    "IA": ("INTERIOR_ALARM",              "CRITICAL"),
    "IR": ("INTERIOR_RESTORE",            "INFO"),
    "PA": ("PANIC_ALARM",                 "CRITICAL"),
    "PR": ("PANIC_RESTORE",               "INFO"),
    "FA": ("FIRE_ALARM",                  "CRITICAL"),
    "FR": ("FIRE_RESTORE",                "INFO"),
    "FI": ("FIRE_CANCEL",                 "INFO"),
    "SA": ("SMOKE_ALARM",                 "CRITICAL"),
    "SR": ("SMOKE_RESTORE",               "INFO"),
    "MA": ("MEDICAL_ALARM",               "CRITICAL"),
    "MR": ("MEDICAL_RESTORE",             "INFO"),
    "UA": ("24H_AUXILIARY_ALARM",         "CRITICAL"),
    "UR": ("24H_AUXILIARY_RESTORE",       "INFO"),
    "HA": ("DURESS_ALARM",                "CRITICAL"),
    "HR": ("DURESS_RESTORE",              "INFO"),
    "TA": ("TAMPER_ALARM",                "WARNING"),
    "TR": ("TAMPER_RESTORE",              "INFO"),
    "ES": ("TAMPER_PERIPHERAL",           "WARNING"),
    "EJ": ("TAMPER_PERIPHERAL_RESTORE",   "INFO"),
    "XS": ("RF_DEVICE_TAMPER",            "WARNING"),
    "XJ": ("RF_DEVICE_TAMPER_RESTORE",    "INFO"),
    "AT": ("SYSTEM_AC_LOSS",              "WARNING"),
    "AR": ("SYSTEM_AC_RESTORE",           "INFO"),
    "YT": ("SYSTEM_LOW_BATTERY",          "WARNING"),
    "YR": ("SYSTEM_LOW_BATTERY_RESTORE",  "INFO"),
    "XT": ("RF_DEVICE_LOW_BATTERY",       "WARNING"),
    "XR": ("RF_DEVICE_BATTERY_RESTORE",   "INFO"),
    "XQ": ("RF_JAM",                      "WARNING"),
    "XH": ("RF_JAM_RESTORE",              "INFO"),
    "US": ("RF_NO_SUPERVISION",           "WARNING"),
    "UF": ("RF_SUPERVISION_RESTORE",      "INFO"),
    "OG": ("ARMED_AWAY",                  "INFO"),
    "CG": ("DISARMED",                    "INFO"),
    "OA": ("ARMED_STAY",                  "INFO"),
    "CA": ("AUTO_DISARMED",               "INFO"),
    "OS": ("ARMED_STAY",                  "INFO"),
    "CS": ("DISARMED",                    "INFO"),
    "BB": ("ZONE_BYPASS",                 "INFO"),
    "BU": ("ZONE_BYPASS_RESTORE",         "INFO"),
    "UT": ("INPUT_FAILURE",               "WARNING"),
    "UJ": ("INPUT_FAILURE_RESTORE",       "INFO"),
    "ET": ("FAIL_PERIPHERAL",             "WARNING"),
    "ER": ("FAIL_PERIPHERAL_RESTORE",     "INFO"),
    "RR": ("SYSTEM_RESET",                "INFO"),
    "DD": ("WRONG_CODE",                  "WARNING"),
    "LB": ("PROGRAMMING_START",           "INFO"),
    "LS": ("PROGRAMMING_END",             "INFO"),
    "LT": ("PSTN_FAILURE",                "WARNING"),
    "LR": ("PSTN_RESTORE",                "INFO"),
    "WA": ("WATER_LEAK_ALARM",            "WARNING"),
    "WR": ("WATER_LEAK_RESTORE",          "INFO"),
    "RP": ("SUPERVISORY_TEST",            "INFO"),
    "RT": ("PERIODIC_TEST",               "INFO"),
}

# ── ADM-CID (Contact ID) Event Map ───────────────────────────────────────────
CID_EVENT_MAP = {
    "100": ("FIRE_ALARM",              "CRITICAL"),
    "101": ("SMOKE_ALARM",             "CRITICAL"),
    "110": ("FIRE_ALARM",              "CRITICAL"),
    "111": ("SMOKE_ALARM",             "CRITICAL"),
    "120": ("PANIC_ALARM",             "CRITICAL"),
    "121": ("DURESS_ALARM",            "CRITICAL"),
    "122": ("SILENT_ALARM",            "CRITICAL"),
    "130": ("BURGLARY_ALARM",          "CRITICAL"),
    "131": ("PERIMETER_ALARM",         "CRITICAL"),
    "132": ("INTERIOR_ALARM",          "CRITICAL"),
    "133": ("24H_AUXILIARY_ALARM",     "CRITICAL"),
    "134": ("SILENT_ALARM",            "CRITICAL"),
    "135": ("DURESS_ALARM",            "CRITICAL"),
    "136": ("CONFIRMED_ALARM",         "CRITICAL"),
    "137": ("TAMPER_ALARM",            "WARNING"),
    "139": ("CONFIRMED_ALARM",         "CRITICAL"),
    "146": ("SILENT_ALARM",            "CRITICAL"),
    "150": ("24H_AUXILIARY_ALARM",     "CRITICAL"),
    "154": ("WATER_LEAK_ALARM",        "WARNING"),
    "300": ("SYSTEM_TROUBLE",          "WARNING"),
    "301": ("SYSTEM_AC_LOSS",          "WARNING"),
    "302": ("SYSTEM_LOW_BATTERY",      "WARNING"),
    "305": ("SYSTEM_RESET",            "INFO"),
    "306": ("PROGRAMMING_CHANGE",      "INFO"),
    "333": ("TAMPER_ALARM",            "WARNING"),
    "334": ("TAMPER_PERIPHERAL",       "WARNING"),
    "381": ("RF_NO_SUPERVISION",       "WARNING"),
    "383": ("RF_DEVICE_TAMPER",        "WARNING"),
    "384": ("RF_JAM",                  "WARNING"),
    "400": ("DISARMED",                "INFO"),
    "401": ("DISARMED",                "INFO"),
    "402": ("DISARMED",                "INFO"),
    "403": ("AUTO_DISARMED",           "INFO"),
    "407": ("REMOTE_ARM_DISARM",       "INFO"),
    "408": ("QUICK_ARM",               "INFO"),
    "409": ("KEYSWITCH_ARM_DISARM",    "INFO"),
    "441": ("ARMED_STAY",              "INFO"),
    "442": ("ARMED_AWAY",              "INFO"),
    "570": ("ZONE_BYPASS",             "INFO"),
    "573": ("ZONE_BYPASS",             "INFO"),
    "601": ("SUPERVISORY_TEST",        "INFO"),
    "602": ("PERIODIC_TEST",           "INFO"),
    "606": ("PROGRAMMING_START",       "INFO"),
    "607": ("PROGRAMMING_END",         "INFO"),
    "625": ("DATE_TIME_CHANGED",       "INFO"),
    "627": ("PROGRAMMING_CHANGE",      "INFO"),
}


# ── CRC-16 ────────────────────────────────────────────────────────────────────
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
        expected = int(raw_line[:4], 16)
        body     = raw_line[4:]
        computed = crc16(body.encode("ascii", errors="ignore"))
        return computed == expected
    except Exception:
        return False


# ── SIA Frame Parser ──────────────────────────────────────────────────────────
def parse_sia_frame(raw: str) -> Optional[dict]:
    if '"SIA-DCS"' not in raw:
        return None
    seq_m   = re.search(r'"SIA-DCS"(\d{4})', raw)
    seq     = int(seq_m.group(1)) if seq_m else None
    acct_m  = re.search(r'#(\w+)\|', raw)
    account = acct_m.group(1) if acct_m else "UNKNOWN"
    pm      = re.search(r'\[([^\]]+)\]', raw)
    if not pm:
        return None
    payload = pm.group(1)

    em = re.search(r'\|[NR]ri(\d+)/([A-Za-z]{2})(\d+)', payload)
    if em:
        area = int(em.group(1))
        code = em.group(2).upper()
        zone = int(em.group(3))
    else:
        em2 = re.search(r'\|[NR]([A-Za-z]{2})(\d+)', payload)
        if em2:
            area = 0
            code = em2.group(1).upper()
            zone = int(em2.group(2))
        else:
            return None

    qm        = re.search(r'\|([NR])', payload)
    qualifier = qm.group(1) if qm else "N"
    event_name, severity = SIA_EVENT_MAP.get(code, ("UNKNOWN_" + code, "WARNING"))
    if qualifier == "R" and not event_name.endswith("RESTORE"):
        event_name += "_RESTORE"
        severity    = "INFO"

    return {
        "protocol": "SIA-DCS",  "account": account,   "sequence": seq,
        "qualifier": qualifier,  "area": area,          "zone": zone,
        "code": code,            "event": event_name,   "severity": severity,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


# ── CID Frame Parser ──────────────────────────────────────────────────────────
def parse_cid_frame(raw: str) -> Optional[dict]:
    if '"ADM-CID"' not in raw:
        return None
    seq_m   = re.search(r'"ADM-CID"(\d{4})', raw)
    seq     = int(seq_m.group(1)) if seq_m else None
    acct_m  = re.search(r'#(\w+)\|', raw)
    account = acct_m.group(1) if acct_m else "UNKNOWN"
    pm      = re.search(r'\[([^\]]+)\]', raw)
    if not pm:
        return None
    payload = pm.group(1)

    cm = re.search(r'\|(\d)(\d{3})\s+(\d{2})\s+(\d{3})', payload)
    if not cm:
        return None

    qualifier  = int(cm.group(1))
    code       = cm.group(2)
    partition  = int(cm.group(3))
    zone_user  = int(cm.group(4))
    is_restore = (qualifier == 3)
    event_name, severity = CID_EVENT_MAP.get(code, ("UNKNOWN_" + code, "WARNING"))
    if is_restore and not event_name.endswith("RESTORE"):
        event_name += "_RESTORE"
        severity    = "INFO"

    return {
        "protocol": "ADM-CID",  "account": account,   "sequence": seq,
        "qualifier": qualifier,  "partition": partition, "zone": zone_user,
        "code": code,            "event": event_name,   "severity": severity,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def parse_frame(raw: str) -> Optional[dict]:
    if '"SIA-DCS"' in raw:
        return parse_sia_frame(raw)
    elif '"ADM-CID"' in raw:
        return parse_cid_frame(raw)
    elif '"NULL"' in raw:
        acct_m  = re.search(r'#(\w+)', raw)
        account = acct_m.group(1) if acct_m else "UNKNOWN"
        log.debug("NULL keepalive | account=%s", account)
        return None
    return None


# ── ACK Builder ───────────────────────────────────────────────────────────────
def build_ack(raw: str) -> bytes:
    try:
        seq_m   = re.search(r'"(?:SIA-DCS|ADM-CID|NULL)"(\d{4})', raw)
        acct_m  = re.search(r'#(\w+)', raw)
        seq     = seq_m.group(1)  if seq_m  else "0000"
        account = acct_m.group(1) if acct_m else "0000"
        body       = f'"ACK"{seq}L0#{account}[]'
        length_hex = f"{len(body):04X}"
        full_body  = length_hex + body
        crc_val    = crc16(full_body.encode("ascii"))
        crc_hex    = f"{crc_val:04X}"
        return f"\n{crc_hex}{full_body}\r".encode("ascii")
    except Exception as e:
        log.error("ACK build error: %s", e)
        return b""


# ── Event printer ─────────────────────────────────────────────────────────────
def print_event(event: dict):
    severity = event.get("severity", "INFO")
    colour   = RED if severity == "CRITICAL" else (YELLOW if severity == "WARNING" else GREEN)
    sep      = "─" * 60

    print(f"\n{BOLD}{sep}{RESET}")
    print(f"  {BOLD}EVENT  {RESET}[{event['timestamp']}]")
    print(f"  Protocol  : {info(event['protocol'])}")
    print(f"  Account   : {event['account']}")
    print(f"  Event     : {_c(event['event'], colour)}  [{severity}]")

    if event["protocol"] == "SIA-DCS":
        print(f"  SIA Code  : {event.get('code', '-')}")
        print(f"  Zone      : {event.get('zone', '-')}")
        print(f"  Area      : {event.get('area', '-')}")
        print(f"  Qualifier : {event.get('qualifier', '-')}  (N=New, R=Restore)")
    else:
        print(f"  CID Code  : {event.get('code', '-')}")
        print(f"  Zone/User : {event.get('zone', '-')}")
        print(f"  Partition : {event.get('partition', '-')}")
        print(f"  Qualifier : {event.get('qualifier', '-')}  (1=New, 3=Restore)")

    print(f"  Sequence  : {event.get('sequence', '-')}")
    print(f"{BOLD}{sep}{RESET}\n")


# ── Statistics ────────────────────────────────────────────────────────────────
_stats = {"connections": 0, "frames": 0, "parsed": 0,
          "crc_errors": 0, "by_event": {}}
_stats_lock = threading.Lock()

def _update_stats(event, crc_ok):
    with _stats_lock:
        _stats["frames"] += 1
        if not crc_ok:
            _stats["crc_errors"] += 1
        if event:
            _stats["parsed"] += 1
            ev = event.get("event", "UNKNOWN")
            _stats["by_event"][ev] = _stats["by_event"].get(ev, 0) + 1

def _print_stats():
    with _stats_lock:
        print(f"\n{BOLD}{'─'*60}{RESET}")
        print(f"  {BOLD}STATISTICS{RESET}")
        print(f"  Connections : {_stats['connections']}")
        print(f"  Frames      : {_stats['frames']}  |  Parsed: {_stats['parsed']}  |  CRC errors: {_stats['crc_errors']}")
        if _stats["by_event"]:
            print(f"  Events:")
            for ev, cnt in sorted(_stats["by_event"].items()):
                print(f"    {ev:<42} {cnt}")
        print(f"{BOLD}{'─'*60}{RESET}\n")

def _stats_loop():
    while True:
        time.sleep(60)
        _print_stats()


# ── Client handler ────────────────────────────────────────────────────────────
def handle_client(conn: socket.socket, addr):
    with _stats_lock:
        _stats["connections"] += 1
    log.info(ok(f"TL280 connected  {addr[0]}:{addr[1]}"))
    conn.settimeout(5.0)
    buf = b""
    try:
        while True:
            try:
                data = conn.recv(4096)
            except socket.timeout:
                break
            if not data:
                break
            buf += data
            while True:
                for delim in (b"\r\n", b"\n", b"\r"):
                    if delim in buf:
                        line, buf = buf.split(delim, 1)
                        text = line.decode("ascii", errors="ignore").strip()
                        if not text:
                            break
                        crc_ok = validate_crc(text)
                        if not crc_ok:
                            log.warning(warn(f"CRC mismatch: {text[:60]}"))
                        log.debug("RAW ← %s", text)
                        ack = build_ack(text)
                        if ack:
                            try:
                                conn.sendall(ack)
                                log.debug("ACK → sent")
                            except Exception as e:
                                log.error("ACK send failed: %s", e)
                        event = parse_frame(text)
                        _update_stats(event, crc_ok)
                        if event:
                            print_event(event)
                        elif '"NULL"' not in text:
                            log.warning(warn(f"Unparsed frame: {text[:80]}"))
                        break
                else:
                    break
    except (ConnectionResetError, socket.timeout):
        pass
    except Exception as e:
        log.error("Client error: %s", e)
    finally:
        conn.close()
        log.info(warn(f"TL280 disconnected  {addr[0]}:{addr[1]}"))


# ── Entry point ───────────────────────────────────────────────────────────────
def main():
    threading.Thread(target=_stats_loop, daemon=True).start()

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as srv:
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind((HOST, PORT))
        srv.listen(10)
        srv.settimeout(30.0)

        print(f"\n{BOLD}{'='*60}{RESET}")
        print(f"  {BOLD}DSC Neo HS2032 — Integration Test{RESET}")
        print(f"{'='*60}")
        print(f"  Listening : {HOST}:{PORT}")
        print(f"  Log file  : {LOG_FILE}")
        print(f"  Protocols : SIA-DCS  and  ADM-CID (Contact ID)")
        print(f"  Ctrl+C    : stop")
        print(f"{'─'*60}")
        print(f"  TL280 Programming:")
        print(f"    [300][011]  Receiver IP   : <this Dexter IP>")
        print(f"    [300][012]  Receiver port : {PORT}")
        print(f"    [300][013]  Protocol      : 03=CID  or  04=SIA")
        print(f"    [300][001]  Route         : 01 or 02")
        print(f"{'='*60}\n")
        print(f"  Waiting for TL280 connection...\n")

        while True:
            try:
                conn, addr = srv.accept()
                threading.Thread(
                    target=handle_client, args=(conn, addr), daemon=True
                ).start()
            except socket.timeout:
                continue
            except KeyboardInterrupt:
                break


if __name__ == "__main__":
    # Exit cleanly if integration is disabled in DB — Docker restart:on-failure
    # will not relaunch on exit 0, keeping the container in "disabled" state.
    try:
        import logical_params_module as _lpm
        if _lpm.get_parameter("active_integration_dsc_neo_bas") != 1:
            logging.info(
                "[dsc_neo_integration.py] active_integration_dsc_neo_bas=0"
                " — integration disabled, exiting cleanly"
            )
            sys.exit(0)
    except Exception as _e:
        logging.warning("[dsc_neo_integration.py] could not read DB flag: %s — continuing", _e)

    try:
        main()
    except KeyboardInterrupt:
        print(f"\n{warn('Stopped.')}")
        _print_stats()
        sys.exit(0)
