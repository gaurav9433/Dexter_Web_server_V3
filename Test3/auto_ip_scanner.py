#!/usr/bin/env python3
"""
auto_ip_scanner.py — Dexter HMS Network Device Auto-Scanner
Seple Novaedge Pvt. Ltd.

Scans the local network for connected security devices and auto-populates
device_config.db so service engineers never need to type IPs manually.

Supported devices:
  NVR:             Hikvision NVR, Dahua NVR, CP Plus NVR
  Access Control:  Hikvision ACS (biometric)
  Burglar Alarm:   Hikvision DS-PHA64 (BAS panel)
  Intrusion BAS:   Texecom (UDL TCP protocol on port 10001)

Usage — interactive (terminal):
  python3 auto_ip_scanner.py

Usage — non-interactive (called from seple.py webserver):
  python3 auto_ip_scanner.py \
      --device nvr --brand hikvision \
      --user admin --pass admin123 \
      --cidr 192.168.1.0/24 \
      --status-file /home/pi/Test3/scan_status.json

DB writes:
  All credentials go through device_parameters_module which handles
  Fernet password encryption (SEC-04). Never writes raw passwords to DB.

Device type mapping (device_config.db → device_parameters.device_type):
  HikvisionNVR1       — Hikvision NVR
  DahuaNVR1           — Dahua NVR
  CP_PlusNVR1         — CP Plus NVR
  HikvisionBioMetric1 — Hikvision Access Control
  HikvisionBAS1       — Hikvision Burglar Alarm Panel (DS-PHA64)
  TexecomBAS1         — Texecom Intrusion Panel (UDL port 10001)
"""

import asyncio
import ipaddress
import socket
import sys
import os
import json
import re
import threading
import time
import argparse
import struct
import xml.etree.ElementTree as ET
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

import hashlib
import time as _time

import requests
import urllib3
from requests.auth import HTTPDigestAuth

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Dexter HMS path
sys.path.insert(0, '/home/pi/Test3')

import device_parameters_module as _dpm

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────
PING_CONCURRENCY   = 150
PROBE_WORKERS      = 20
CONNECT_TIMEOUT    = 5
READ_TIMEOUT       = 15
CAM_READ_TIMEOUT   = 20
MAX_RESPONSE_BYTES = 500_000   # 500 KB

TEX_PORT           = 10001     # Texecom UDL TCP port
TEX_USERNAME       = "TAXICOM" # Fixed — not user-configurable
TEX_TIMEOUT        = 5         # TCP connect timeout for Texecom probe

# ─────────────────────────────────────────────────────────────────────────────
# Status file — written during scan so seple.py can poll progress
# ─────────────────────────────────────────────────────────────────────────────
_status_file  = None   # set from --status-file arg or None (interactive)
_status_lock  = threading.Lock()
_tex_tcp_ips  = set()  # IPs confirmed to have port 10001 open via TCP sweep


def _write_status(status: str, message: str, found: list = None, error: str = None):
    """Write scan progress to JSON file for seple.py to poll."""
    if _status_file is None:
        return
    payload = {
        "status":    status,    # "running" | "done" | "error"
        "message":   message,
        "found":     found or [],
        "error":     error or "",
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    with _status_lock:
        try:
            with open(_status_file, "w") as f:
                json.dump(payload, f)
        except Exception as e:
            print(f"[WARN] Could not write status file: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Auto subnet detection
# ─────────────────────────────────────────────────────────────────────────────
def detect_cidr() -> str:
    try:
        import netifaces
        for iface in netifaces.interfaces():
            if iface.startswith("lo"):
                continue
            addrs = netifaces.ifaddresses(iface)
            if netifaces.AF_INET in addrs:
                info    = addrs[netifaces.AF_INET][0]
                ip      = info["addr"]
                netmask = info.get("netmask", "255.255.255.0")
                return str(ipaddress.IPv4Network(f"{ip}/{netmask}", strict=False))
    except Exception:
        pass
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ".".join(ip.split(".")[:3]) + ".0/24"
    except Exception:
        return "192.168.1.0/24"


# ─────────────────────────────────────────────────────────────────────────────
# Async ping sweep
# ─────────────────────────────────────────────────────────────────────────────
async def _ping(ip: str, sem: asyncio.Semaphore):
    async with sem:
        proc = await asyncio.create_subprocess_exec(
            "ping", "-c", "1", "-W", "1", ip,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()
        return ip if proc.returncode == 0 else None


async def ping_sweep(cidr: str) -> list:
    network  = ipaddress.ip_network(cidr, strict=False)
    sem      = asyncio.Semaphore(PING_CONCURRENCY)
    tasks    = [_ping(str(ip), sem) for ip in network.hosts()]
    results  = await asyncio.gather(*tasks)
    return [ip for ip in results if ip]


async def _tcp_connect(ip: str, port: int, timeout: float,
                       sem: asyncio.Semaphore):
    async with sem:
        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(ip, port), timeout=timeout
            )
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
            return ip
        except Exception:
            return None


async def tcp_port_sweep(cidr: str, port: int, timeout: float = 1.5) -> list:
    """Find hosts with a specific TCP port open — used for devices that block ping."""
    network = ipaddress.ip_network(cidr, strict=False)
    sem     = asyncio.Semaphore(PING_CONCURRENCY)
    tasks   = [_tcp_connect(str(ip), port, timeout, sem) for ip in network.hosts()]
    results = await asyncio.gather(*tasks)
    return [ip for ip in results if ip]


# ─────────────────────────────────────────────────────────────────────────────
# Safe HTTP helper
# ─────────────────────────────────────────────────────────────────────────────
def safe_get(url: str, user: str, pwd: str,
             read_timeout=READ_TIMEOUT, verify=True):
    try:
        r = requests.get(
            url,
            auth=HTTPDigestAuth(user, pwd),
            timeout=(CONNECT_TIMEOUT, read_timeout),
            verify=verify,
        )
        if r.status_code != 200:
            return None
        if len(r.content) > MAX_RESPONSE_BYTES:
            print(f"[WARN] Response too large from {url} — skipping")
            return None
        return r.text
    except requests.exceptions.Timeout:
        return None
    except requests.exceptions.ConnectionError:
        return None
    except Exception as e:
        print(f"[WARN] HTTP error {url}: {e}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Hikvision — detection
# ─────────────────────────────────────────────────────────────────────────────
def _parse_hik_xml(xml_data: str):
    """
    Parse Hikvision deviceInfo XML robustly.
    Returns (root_element, get_field_fn) or (None, None) on failure.
    """
    try:
        xml_data = xml_data.strip()
        xml_data = xml_data[xml_data.find("<"):]
        xml_data = re.sub(r'<\?xml[^?]*\?>', '', xml_data).strip()
        xml_data = re.sub(r'&(?!amp;|lt;|gt;|quot;|apos;)([^;]{0,10})',
                          r'&amp;\1', xml_data)
        container = ET.fromstring("<_root_>" + xml_data + "</_root_>")
        root = list(container)[0]
    except Exception as e:
        print(f"[WARN] Hikvision XML parse: {e}")
        return None, None

    nss = [
        {"ns": "http://www.hikvision.com/ver20/XMLSchema"},
        {"ns": "http://www.isapi.org/ver20/XMLSchema"},
    ]

    def get_field(tag):
        for ns in nss:
            val = root.findtext(f"ns:{tag}", namespaces=ns)
            if val:
                return val
        return root.findtext(tag)

    return root, get_field


def _hik_session_get(ip: str, port: int, scheme: str,
                     user: str, pwd: str, path: str,
                     read_timeout=READ_TIMEOUT) -> Optional[str]:
    """
    Authenticate via Hikvision ISAPI session login (firmware 2022+).
    Newer NVRs reject HTTP Digest and count those attempts as failed logins,
    triggering lockout.  This method uses the proper session flow:
      1. GET /ISAPI/Security/sessionLogin/capabilities?username=<user>
      2. key = SHA256(username + salt + password)
      3. key = SHA256(key + challenge)
      4. Repeat SHA256 for (iterations-2) more rounds  (matches NVR utils.js encodePwd)
      5. POST /ISAPI/Security/sessionLogin?timeStamp=<epoch_ms> with XML body
      6. Use returned session cookie for subsequent requests
    Returns response text on success, None on failure (wrong creds / unreachable).
    """
    base = f"{scheme}://{ip}:{port}"
    try:
        s = requests.Session()
        s.verify = False
        cap_r = s.get(
            f"{base}/ISAPI/Security/sessionLogin/capabilities?username={user}",
            timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
        )
        if cap_r.status_code != 200:
            return None

        cap_xml = ET.fromstring(cap_r.text)
        nss = [
            {"h": "http://www.hikvision.com/ver20/XMLSchema"},
            {"h": "http://www.isapi.org/ver20/XMLSchema"},
        ]
        def _cap(tag):
            for ns in nss:
                v = cap_xml.findtext(f"h:{tag}", namespaces=ns)
                if v:
                    return v
            return cap_xml.findtext(tag)

        session_id = _cap("sessionID") or ""
        challenge   = _cap("challenge") or ""
        iterations  = int(_cap("iterations") or 100)
        salt        = _cap("salt") or ""

        # Hikvision iterated SHA256 (from utils.js encodePwd, isIrreversible=true):
        #   step1 = SHA256(username + salt + password)
        #   step2 = SHA256(step1 + challenge)
        #   repeat SHA256 for remaining (iterations-2) rounds
        key = hashlib.sha256((user + salt + pwd).encode()).hexdigest()
        key = hashlib.sha256((key + challenge).encode()).hexdigest()
        for _ in range(2, iterations):
            key = hashlib.sha256(key.encode()).hexdigest()
        final = key

        login_body = (
            f"<SessionLogin>"
            f"<userName>{user}</userName>"
            f"<password>{final}</password>"
            f"<sessionID>{session_id}</sessionID>"
            f"<isSessionIDValidLongTerm>false</isSessionIDValidLongTerm>"
            f"<sessionIDVersion>2</sessionIDVersion>"
            f"</SessionLogin>"
        )
        ts = int(_time.time() * 1000)
        login_r = s.post(
            f"{base}/ISAPI/Security/sessionLogin?timeStamp={ts}",
            data=login_body,
            headers={"Content-Type": "application/xml"},
            timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
        )
        if login_r.status_code != 200:
            return None

        data_r = s.get(
            f"{base}{path}",
            timeout=(CONNECT_TIMEOUT, read_timeout),
        )
        if data_r.status_code == 200 and len(data_r.content) <= MAX_RESPONSE_BYTES:
            return data_r.text
        return None

    except Exception:
        return None


def get_hik_device_info(ip: str, user: str, pwd: str):
    # Try session auth (newer firmware) then digest (older firmware), both on
    # port 8080 first (NVR default) then port 80, then HTTPS 443.
    candidates = [
        (ip, 8080, "http"),
        (ip, 80,   "http"),
        (ip, 443,  "https"),
    ]
    path = "/ISAPI/System/deviceInfo"
    for _ip, port, scheme in candidates:
        result = _hik_session_get(_ip, port, scheme, user, pwd, path)
        if result:
            return result
        # Digest fallback for older firmware
        url = f"{scheme}://{_ip}:{port}{path}"
        result = safe_get(url, user, pwd, verify=False)
        if result:
            return result
    return None


def detect_hik_nvr(xml_data: str) -> bool:
    # Fast path: plain string match (most common firmware format)
    if "<deviceType>NVR</deviceType>" in xml_data:
        return True
    # Robust path: namespace-aware XML parsing
    _, get_field = _parse_hik_xml(xml_data)
    if get_field is None:
        return False
    device_type = (get_field("deviceType") or "").upper()
    hr_type     = (get_field("hrDeviceType") or "").upper()
    model       = (get_field("model") or "").upper()
    if "NVR" in device_type or "NVR" in hr_type:
        return True
    # Hikvision NVR model numbers: DS-7xxx / DS-9xxx / DS-Exxx series
    if re.match(r"DS-[79E]\d", model):
        return True
    return False


def detect_hik_access(xml_data: str) -> bool:
    _, get_field = _parse_hik_xml(xml_data)
    if get_field is None:
        return False
    device_type = get_field("deviceType")
    sub_type    = get_field("subDeviceType")
    if device_type == "ACS":
        return True
    if sub_type and "access" in sub_type.lower():
        return True
    return False


def detect_hik_burglar(xml_data: str) -> bool:
    """
    Detect Hikvision DS-PHA64 burglar alarm panel.
    deviceType == "PHA" per ISAPI doc.
    Fallback: check model string for DS-PHA prefix.
    """
    _, get_field = _parse_hik_xml(xml_data)
    if get_field is None:
        return False
    device_type = get_field("deviceType")
    if device_type == "PHA":
        return True
    # Fallback: model string (some firmware variants)
    model = get_field("model") or ""
    if "PHA" in model.upper() or "DS-PHA" in model.upper():
        return True
    return False


# ─────────────────────────────────────────────────────────────────────────────
# Hikvision — camera list from NVR
# ─────────────────────────────────────────────────────────────────────────────
def get_hik_cameras(ip: str, user: str, pwd: str) -> list:
    cam_path = "/ISAPI/ContentMgmt/InputProxy/channels"
    text = (_hik_session_get(ip, 8080, "http", user, pwd, cam_path, CAM_READ_TIMEOUT)
            or _hik_session_get(ip, 80,   "http", user, pwd, cam_path, CAM_READ_TIMEOUT)
            or safe_get(f"http://{ip}:8080{cam_path}", user, pwd, CAM_READ_TIMEOUT)
            or safe_get(f"http://{ip}{cam_path}",      user, pwd, CAM_READ_TIMEOUT)
            or safe_get(f"https://{ip}{cam_path}",     user, pwd, CAM_READ_TIMEOUT, verify=False))
    if not text:
        return []
    try:
        root = ET.fromstring(text)
        ns   = {"ns": "http://www.hikvision.com/ver20/XMLSchema"}
        cams = []
        for ch in root.findall("ns:InputProxyChannel", ns):
            desc = ch.find("ns:sourceInputPortDescriptor", ns)
            if desc is None:
                continue
            ip_elem = desc.find("ns:ipAddress", ns)
            if ip_elem is None or not ip_elem.text:
                continue
            cam_ip = ip_elem.text.strip()
            if cam_ip and cam_ip != "0.0.0.0":
                cams.append({"ip_address": cam_ip, "username": user, "password": pwd})
        return list({c["ip_address"]: c for c in cams}.values())
    except Exception as e:
        print(f"[WARN] Hikvision camera parse {ip}: {e}")
        return []


# ─────────────────────────────────────────────────────────────────────────────
# Dahua — detection + cameras
# ─────────────────────────────────────────────────────────────────────────────
def detect_dahua_nvr(ip: str, user: str, pwd: str) -> bool:
    text = safe_get(
        f"http://{ip}/cgi-bin/magicBox.cgi?action=getDeviceType",
        user, pwd,
    )
    if not text:
        return False
    upper = text.upper()
    match = re.search(r"TYPE\s*=\s*(.+)", upper)
    model = match.group(1) if match else upper
    return "DHI-NVR" in model or "NVR" in model


def get_dahua_cameras(ip: str, user: str, pwd: str) -> list:
    text = safe_get(
        f"http://{ip}/cgi-bin/LogicDeviceManager.cgi?action=getCameraAll",
        user, pwd, read_timeout=CAM_READ_TIMEOUT,
    )
    if not text:
        return []
    try:
        cams = {}
        for line in text.splitlines():
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            m = re.match(r"camera\[(\d+)\]\.(.+)", key)
            if m:
                cams.setdefault(int(m.group(1)), {})[m.group(2)] = value
        ip_list = []
        for cam in cams.values():
            cam_ip = cam.get("DeviceInfo.Address")
            if cam_ip:
                ip_list.append({"ip_address": cam_ip,
                                "username": user, "password": pwd})
        return list({c["ip_address"]: c for c in ip_list}.values())
    except Exception as e:
        print(f"[WARN] Dahua camera parse {ip}: {e}")
        return []


# ─────────────────────────────────────────────────────────────────────────────
# CP Plus — detection + cameras
# ─────────────────────────────────────────────────────────────────────────────
def detect_cpplus_nvr(ip: str, user: str, pwd: str) -> bool:
    text = safe_get(
        f"http://{ip}/cgi-bin/magicBox.cgi?action=getDeviceType",
        user, pwd, verify=False,
    )
    if not text:
        return False
    upper = text.upper()
    return any(x in upper for x in ["CP-UNR", "CP-UVR", "UNR", "UVR"])


def get_cpplus_cameras(ip: str, user: str, pwd: str) -> list:
    text = safe_get(
        f"http://{ip}/cgi-bin/LogicDeviceManager.cgi?action=getCameraAll",
        user, pwd, read_timeout=CAM_READ_TIMEOUT, verify=False,
    )
    if not text:
        return []
    try:
        cams = {}
        for line in text.splitlines():
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            m = re.match(r"camera\[(\d+)\]\.(.+)", key)
            if m:
                cams.setdefault(int(m.group(1)), {})[m.group(2)] = value
        ip_list = []
        for cam in cams.values():
            cam_ip = cam.get("DeviceInfo.Address")
            if cam_ip:
                ip_list.append({"ip_address": cam_ip,
                                "username": user, "password": pwd})
        return list({c["ip_address"]: c for c in ip_list}.values())
    except Exception as e:
        print(f"[WARN] CP Plus camera parse {ip}: {e}")
        return []


# ─────────────────────────────────────────────────────────────────────────────
# Texecom — UDL TCP probe on port 10001
#
# Protocol: Texecom Wintex UDL
#   Frame:  [0x74('t'), 0x43('C'), length, seq, cmd_byte, ...body..., crc8]
#   CRC8:   poly=0x185, initCrc=0xFF, no reverse
#   LOGIN:  cmd=0x01, body=udl_password.encode('utf-8')
#   ACK:    response[0]=0x74, response[1]=0x52('R'), payload[0]=0x06
#   NAK:    response payload[0]=0x00 or 0x15 — wrong password BUT IS Texecom
#
# Detection strategy:
#   ACK (0x06) → confirmed Texecom + correct password → save to DB
#   NAK (wrong password) → IS a Texecom panel → save IP with placeholder password
#     (engineer will update password via LCD/webserver)
#   No response / wrong frame → not Texecom
# ─────────────────────────────────────────────────────────────────────────────
def _crc8(data: bytes) -> int:
    """CRC8 with poly=0x85 (Texecom UDL variant: x^8+x^7+x^2+x+1 = 0x185)."""
    crc = 0xFF
    for b in data:
        crc ^= b
        for _ in range(8):
            if crc & 0x80:
                crc = (crc << 1) ^ 0x85
            else:
                crc <<= 1
            crc &= 0xFF
    return crc


def _build_udl_login_frame(udl_password: str, seq: int = 0) -> bytes:
    """
    Build a Texecom UDL LOGIN command frame.
    Header: [0x74, 0x43, length, seq]
    Body:   [0x01] + password bytes
    Trailer: [crc8]
    length = len(body) + 5  (header=4 + crc=1)
    """
    body   = bytes([0x01]) + udl_password.encode('utf-8')
    length = (len(body) + 5) & 0xFF
    header = bytes([0x74, 0x43, length, seq & 0xFF])
    frame_no_crc = header + body
    crc = _crc8(frame_no_crc)
    return frame_no_crc + bytes([crc])


def detect_texecom(ip: str, udl_password: str) -> tuple:
    """
    Try to detect a Texecom panel on ip:10001 using UDL LOGIN.

    Returns:
        ("confirmed", ip)   — panel found, password correct
        ("wrong_pass", ip)  — panel found, password wrong (still save IP)
        ("port_open", ip)   — port 10001 open but UDL handshake blocked
                              (panel busy with another connection, e.g. texecomConnect.py)
        (None, None)        — not a Texecom panel
    """
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(TEX_TIMEOUT)
        s.connect((ip, TEX_PORT))

        # Texecom requires 500ms delay before first command
        time.sleep(0.5)

        frame = _build_udl_login_frame(udl_password, seq=0)
        s.sendall(frame)

        # Read response — minimum 5 bytes (header + crc)
        resp = b""
        deadline = time.time() + TEX_TIMEOUT
        while len(resp) < 5 and time.time() < deadline:
            try:
                chunk = s.recv(64)
                if not chunk:
                    break
                resp += chunk
            except socket.timeout:
                break

        s.close()

        if len(resp) < 5:
            # TCP connected but panel didn't respond — busy with another UDL session
            if ip in _tex_tcp_ips:
                return "port_open", ip
            return None, None

        # Valid Texecom response frame starts with 0x74 ('t') + 0x52 ('R')
        if resp[0] != 0x74 or resp[1] != 0x52:
            if ip in _tex_tcp_ips:
                return "port_open", ip
            return None, None

        payload_byte = resp[4] if len(resp) > 4 else 0x00

        if payload_byte == 0x06:   # ACK — correct password
            return "confirmed", ip
        else:
            # NAK or unexpected — it IS Texecom but password is wrong
            return "wrong_pass", ip

    except (socket.timeout, ConnectionRefusedError, OSError):
        # Connection failed — only report as found if TCP sweep confirmed port exists
        if ip in _tex_tcp_ips:
            return "port_open", ip
        return None, None
    except Exception as e:
        print(f"[WARN] Texecom probe {ip}: {e}")
        if ip in _tex_tcp_ips:
            return "port_open", ip
        return None, None


# ─────────────────────────────────────────────────────────────────────────────
# Database writes — use device_parameters_module for all writes
# This ensures SEC-04 (Fernet password encryption) is always applied.
# Never write directly to SQLite — encryption happens inside the module.
# ─────────────────────────────────────────────────────────────────────────────
def _upsert_device(device_type: str, ip: str, username: str,
                   password: str, port: int, cams: list = None) -> bool:
    """
    Save or update a device in device_config.db via device_parameters_module.
    Uses modify_device_field_by_type() for existing records (updates each
    field individually, encryption handled by the module).
    Uses add_device() for new records.
    Returns True on success.
    """
    try:
        existing = _dpm.get_device_parameters(device_type)

        if existing:
            # Update all fields for existing record
            _dpm.modify_device_field_by_type(device_type, "ip_address", ip)
            _dpm.modify_device_field_by_type(device_type, "username",   username)
            _dpm.modify_device_field_by_type(device_type, "password",   password)
            _dpm.modify_device_field_by_type(device_type, "port",       str(port))
            if cams is not None:
                _dpm.modify_device_field_by_type(device_type, "camera_ip", cams)
            print(f"[DB] Updated {device_type} @ {ip}")
        else:
            # Insert new record — add_device() encrypts password automatically
            _dpm.add_device(device_type, ip, username, password, port, cams)
            print(f"[DB] Inserted {device_type} @ {ip}")

        return True

    except Exception as e:
        print(f"[ERROR] DB write failed for {device_type} @ {ip}: {e}")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Per-brand save wrappers
# ─────────────────────────────────────────────────────────────────────────────
def save_hik_nvr(ip, user, pwd, cams):
    return _upsert_device("HikvisionNVR1", ip, user, pwd, 8080, cams)

def save_hik_access(ip, user, pwd):
    return _upsert_device("HikvisionBioMetric1", ip, user, pwd, 8080, None)

def save_hik_burglar(ip, user, pwd):
    # HikvisionBAS1 — used by hikvision_bas_integration.py
    return _upsert_device("HikvisionBAS1", ip, user, pwd, 80, None)

def save_dahua_nvr(ip, user, pwd, cams):
    return _upsert_device("DahuaNVR1", ip, user, pwd, 8080, cams)

def save_cpplus_nvr(ip, user, pwd, cams):
    return _upsert_device("CP_PlusNVR1", ip, user, pwd, 8080, cams)

def save_texecom(ip, udl_password):
    # username is always "TAXICOM" for Texecom UDL — not user-configurable
    return _upsert_device("TexecomBAS1", ip, TEX_USERNAME, udl_password,
                          TEX_PORT, None)


# ─────────────────────────────────────────────────────────────────────────────
# Single host probe (runs inside thread pool)
# ─────────────────────────────────────────────────────────────────────────────
def probe_device(ip: str, device_type: str,
                 scan_hik: bool, scan_dahua: bool, scan_cpplus: bool,
                 scan_texecom: bool,
                 user: str, pwd: str,
                 tex_pass: str,
                 found_list: list, found_lock: threading.Lock):
    """
    Try all selected brands/protocols on one IP.
    Returns immediately after first match — no redundant probing.
    Appends result dict to found_list (thread-safe via found_lock).
    """
    result = None

    # ── Hikvision ─────────────────────────────────────────────────────────────
    if scan_hik:
        xml_data = get_hik_device_info(ip, user, pwd)
        if xml_data:
            if device_type == "nvr" and detect_hik_nvr(xml_data):
                print(f"\n[HIK NVR] {ip}")
                cams = get_hik_cameras(ip, user, pwd)
                print(f"  Cameras: {len(cams)}")
                for i, c in enumerate(cams, 1):
                    print(f"    {i}. {c['ip_address']}")
                save_hik_nvr(ip, user, pwd, cams)
                result = {"brand": "Hikvision", "type": "NVR",
                          "ip": ip, "cameras": [c["ip_address"] for c in cams]}

            elif device_type == "access" and detect_hik_access(xml_data):
                print(f"\n[HIK ACCESS] {ip}")
                save_hik_access(ip, user, pwd)
                result = {"brand": "Hikvision", "type": "Access Control",
                          "ip": ip, "cameras": []}

            elif device_type == "burglar" and detect_hik_burglar(xml_data):
                print(f"\n[HIK BURGLAR] {ip}")
                save_hik_burglar(ip, user, pwd)
                result = {"brand": "Hikvision", "type": "Burglar Panel (BAS)",
                          "ip": ip, "cameras": []}

    if result:
        with found_lock:
            found_list.append(result)
        return

    # ── Dahua ─────────────────────────────────────────────────────────────────
    if scan_dahua and device_type == "nvr":
        if detect_dahua_nvr(ip, user, pwd):
            print(f"\n[DAHUA NVR] {ip}")
            cams = get_dahua_cameras(ip, user, pwd)
            print(f"  Cameras: {len(cams)}")
            save_dahua_nvr(ip, user, pwd, cams)
            result = {"brand": "Dahua", "type": "NVR",
                      "ip": ip, "cameras": [c["ip_address"] for c in cams]}
            with found_lock:
                found_list.append(result)
            return

    # ── CP Plus ───────────────────────────────────────────────────────────────
    if scan_cpplus and device_type == "nvr":
        if detect_cpplus_nvr(ip, user, pwd):
            print(f"\n[CPPLUS NVR] {ip}")
            cams = get_cpplus_cameras(ip, user, pwd)
            print(f"  Cameras: {len(cams)}")
            save_cpplus_nvr(ip, user, pwd, cams)
            result = {"brand": "CP Plus", "type": "NVR",
                      "ip": ip, "cameras": [c["ip_address"] for c in cams]}
            with found_lock:
                found_list.append(result)
            return

    # ── Texecom ───────────────────────────────────────────────────────────────
    if scan_texecom and device_type == "texecom":
        status, confirmed_ip = detect_texecom(ip, tex_pass)
        if status == "confirmed":
            print(f"\n[TEXECOM BAS] {ip} (password OK)")
            save_texecom(ip, tex_pass)
            result = {"brand": "Texecom", "type": "BAS Panel",
                      "ip": ip, "cameras": [], "password_ok": True}
        elif status == "wrong_pass":
            print(f"\n[TEXECOM BAS] {ip} (found — wrong UDL password, IP saved)")
            save_texecom(ip, tex_pass)
            result = {"brand": "Texecom", "type": "BAS Panel",
                      "ip": ip, "cameras": [], "password_ok": False,
                      "note": "Wrong UDL password — update via LCD menu"}
        elif status == "port_open":
            # Panel is on port 10001 but busy (texecomConnect.py already connected).
            # Save the IP so the webserver can populate the field.
            print(f"\n[TEXECOM BAS] {ip} (port 10001 open — panel busy, IP saved)")
            save_texecom(ip, tex_pass)
            result = {"brand": "Texecom", "type": "BAS Panel",
                      "ip": ip, "cameras": [], "password_ok": False,
                      "note": "Panel active on port 10001 — already connected to another session"}
        if result:
            with found_lock:
                found_list.append(result)


# ─────────────────────────────────────────────────────────────────────────────
# Interactive prompts (terminal mode only)
# ─────────────────────────────────────────────────────────────────────────────
def _interactive_args() -> argparse.Namespace:
    print("\n=== Dexter HMS Device Scanner ===\n")
    print("Select device type:")
    print("  1. NVR / DVR")
    print("  2. Access Control (Biometric)")
    print("  3. Burglar Alarm Panel (Hikvision BAS)")
    print("  4. Intrusion Panel (Texecom BAS)")
    choice = input("Enter choice (1/2/3/4): ").strip()

    device_map = {"1": "nvr", "2": "access", "3": "burglar", "4": "texecom"}
    if choice not in device_map:
        print("Invalid choice."); sys.exit(1)
    device_type = device_map[choice]

    brand = "all"
    user  = ""
    pwd   = ""
    tex_pass = "12345"

    if device_type == "nvr":
        print("\nSelect brand:")
        print("  1. Hikvision  2. Dahua  3. CP Plus  4. All")
        b = input("Enter choice (1/2/3/4): ").strip()
        brand_map = {"1": "hikvision", "2": "dahua", "3": "cpplus", "4": "all"}
        brand = brand_map.get(b, "all")
        user  = input("Username: ").strip()
        pwd   = input("Password: ").strip()

    elif device_type in ("access", "burglar"):
        user = input("Username: ").strip()
        pwd  = input("Password: ").strip()

    elif device_type == "texecom":
        tex_pass = input("UDL Password (default 12345): ").strip() or "12345"
        print(f"  Note: username is fixed as '{TEX_USERNAME}' — no input needed")

    ns = argparse.Namespace(
        device=device_type,
        brand=brand,
        user=user,
        password=pwd,
        tex_pass=tex_pass,
        cidr=None,
        status_file=None,
    )
    return ns


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────
def main():
    global _status_file

    parser = argparse.ArgumentParser(
        description="Dexter HMS — Network Device Auto-Scanner"
    )
    parser.add_argument("--device",      choices=["nvr","access","burglar","texecom"],
                        help="Device type to scan for")
    parser.add_argument("--brand",       choices=["hikvision","dahua","cpplus","all","texecom"],
                        default="all",   help="Brand (NVR only; ignored for texecom device)")
    parser.add_argument("--user",        default="",     help="Device username")
    parser.add_argument("--pass",        dest="password", default="",
                        help="Device password (HTTP devices)")
    parser.add_argument("--tex-pass",    default="12345",
                        help="Texecom UDL password (default: 12345)")
    parser.add_argument("--cidr",        default=None,
                        help="Network CIDR (auto-detected if omitted)")
    parser.add_argument("--status-file", default=None,
                        help="JSON file path for progress updates (seple.py polling)")

    args = parser.parse_args()

    # If --device not supplied → interactive mode
    if args.device is None:
        args = _interactive_args()

    _status_file = (args.
                    status_file)

    cidr = args.cidr or detect_cidr()

    scan_hik     = args.device in ("access", "burglar") or \
                   (args.device == "nvr" and args.brand in ("hikvision", "all"))
    scan_dahua   = args.device == "nvr" and args.brand in ("dahua",  "all")
    scan_cpplus  = args.device == "nvr" and args.brand in ("cpplus", "all")
    scan_texecom = args.device == "texecom"

    print(f"\nScanning {cidr}...")
    _write_status("running", f"Pinging {cidr}...")

    # ── Ping sweep ────────────────────────────────────────────────────────────
    live_ips  = asyncio.run(ping_sweep(cidr))
    _saved_ip = ""   # populated below for Texecom saved-IP fallback
    print(f"Live hosts (ping): {len(live_ips)}")

    # Hikvision devices often block ICMP — supplement with TCP sweep on port 8080
    if scan_hik:
        _write_status("running", "Scanning port 8080 for Hikvision devices...")
        hik_tcp_ips = set(asyncio.run(tcp_port_sweep(cidr, 8080, timeout=1.0)))
        before   = len(live_ips)
        live_ips = list(set(live_ips) | hik_tcp_ips)
        added    = len(live_ips) - before
        print(f"Hikvision TCP sweep port 8080: {len(hik_tcp_ips)} found"
              + (f" ({added} new IPs added)" if added else ""))

    # Texecom panels often block ICMP — supplement with direct TCP port scan
    if scan_texecom:
        global _tex_tcp_ips
        _write_status("running", f"Scanning port {TEX_PORT} for Texecom panels...")
        tex_ips      = asyncio.run(tcp_port_sweep(cidr, TEX_PORT))
        _tex_tcp_ips = set(tex_ips)
        before   = len(live_ips)
        live_ips = list(set(live_ips) | _tex_tcp_ips)
        added    = len(live_ips) - before
        print(f"Texecom TCP sweep on port {TEX_PORT}: {len(tex_ips)} found"
              + (f" ({added} new IPs added)" if added else
                 (" (none found)" if not tex_ips else " (all already in ping list)")))

        # Read the previously-saved Texecom IP so we can use it as a fallback
        # after probing if the panel is busy and blocks all new connections.
        _saved_ip = ""
        try:
            _saved_records = _dpm.get_device_parameters("TexecomBAS1")
            if _saved_records:
                _rec = _saved_records[0] if isinstance(_saved_records, list) \
                       else _saved_records
                try:
                    _saved_ip = str(_rec.get("ip_address") or "").strip()
                except AttributeError:
                    try:
                        _saved_ip = str(_rec["ip_address"] or "").strip()
                    except (KeyError, TypeError, IndexError):
                        _saved_ip = ""
            if _saved_ip and _saved_ip not in live_ips:
                live_ips.append(_saved_ip)
                print(f"[Texecom] Saved IP {_saved_ip} added to candidate list")
        except Exception as _e:
            print(f"[Texecom] Could not read saved IP from DB: {_e}")

    _write_status("running", f"Found {len(live_ips)} candidate host(s). Probing devices...")

    # ── Concurrent device probing ─────────────────────────────────────────────
    found_list = []
    found_lock = threading.Lock()

    with ThreadPoolExecutor(max_workers=PROBE_WORKERS) as executor:
        futures = {
            executor.submit(
                probe_device,
                ip, args.device,
                scan_hik, scan_dahua, scan_cpplus, scan_texecom,
                args.user, args.password,
                args.tex_pass,
                found_list, found_lock,
            ): ip
            for ip in live_ips
        }
        completed = 0
        for future in as_completed(futures):
            ip = futures[future]
            completed += 1
            try:
                future.result()
            except Exception as e:
                print(f"[ERROR] Unhandled exception probing {ip}: {e}")
            if completed % 10 == 0:
                _write_status("running",
                    f"Probed {completed}/{len(live_ips)} hosts, "
                    f"found {len(found_list)} device(s)...",
                    found=found_list)

    # Saved IP fallback: if the known Texecom IP wasn't found (panel refused all
    # new TCP connections while texecomConnect.py is active), report it explicitly.
    if scan_texecom and _saved_ip and not any(d["ip"] == _saved_ip for d in found_list):
        save_texecom(_saved_ip, args.tex_pass)
        found_list.append({
            "brand": "Texecom", "type": "BAS Panel",
            "ip": _saved_ip, "cameras": [], "password_ok": False,
            "note": "Panel active — already connected to another session",
        })
        print(f"\n[TEXECOM BAS] {_saved_ip} (saved IP — panel busy, reported as found)")

    # ── Done ──────────────────────────────────────────────────────────────────
    print(f"\nScan complete. Found {len(found_list)} device(s).")
    for d in found_list:
        print(f"  [{d['brand']}] {d['type']} @ {d['ip']}"
              + (f" ({len(d['cameras'])} cameras)" if d.get('cameras') else ""))

    _write_status("done",
        f"Scan complete. Found {len(found_list)} device(s).",
        found=found_list)


if __name__ == "__main__":
    main()
