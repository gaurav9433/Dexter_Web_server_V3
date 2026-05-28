#!/usr/bin/env python3
# Configure_Network_7.py
# Dexter HMS — Network Configuration Manager
#
# Changes from original:
#   BUG-01 : validate_ip(None) crashes with TypeError — now returns False safely
#   BUG-02 : NetworkSettings kept self.conn open forever — connection leak
#   BUG-03 : Module-level DB queries ran at import time — side effects on every import
#   BUG-05 : apply_static_settings/switch_to_dhcp wrote dhcpcd.conf directly —
#            power loss mid-write corrupts the file → device can't boot
#   SEC-05 : subprocess.call() deprecated, errors not captured
#   DB-01  : bare sqlite3.connect() → get_connection(DB_NETWORK_SETTINGS) + WAL
#   CODE-01: main_old() and restart_dhcpcd_old() dead code removed
#   CODE-02: backup_dhcpcd() only backed up once ever → now timestamped versioned
#   CODE-03: All log.info() → logging, import logging added
#
# NOTE: No automatic rollback on network loss — intentional design decision.
#       If static IP config is wrong, physical access is required to fix it.

"""
Configure_Network_7.py
Dexter HMS — Static IP configuration for Ethernet interface

Responsibilities:
  - Writes static IP settings to /etc/dhcpcd.conf
  - Reads IP/gateway/DNS from network_settings.db
  - Called via direct import from Lan_setting.py (not subprocess)
  - TODO: add rollback if network becomes unreachable after change

Dependencies:
  - db_connection.py — WAL SQLite connections
Author: Seple Novaedge Pvt. Ltd.
"""

from __future__ import annotations

import os
import re
import subprocess
import logging
import threading
from datetime import datetime
from typing import Dict, List, Optional

from db_connection import get_connection, DB_NETWORK_SETTINGS

log   = logging.getLogger(__name__)
_lock = threading.Lock()

# ─────────────────────────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────────────────────────
DHCPCD_CONF_PATH = "/etc/dhcpcd.conf"
BACKUP_DIR       = "/etc/dexter/network_backups"
WLAN_STATIC_IP   = "192.168.5.1"
WLAN_STATIC_MASK = "255.255.255.0"


# ─────────────────────────────────────────────────────────────────
# NETWORK SETTINGS DATABASE
# ─────────────────────────────────────────────────────────────────
class NetworkSettings:
    """
    Manages network configuration settings in network_settings.db.

    BUG-02 FIX: original stored self.conn as a persistent attribute —
    the connection was opened in __init__ and never explicitly closed.
    Any crash left the file handle open permanently.
    Fixed: connection opened and closed per operation via get_connection().
    """

    def __init__(self, db_path: str = DB_NETWORK_SETTINGS):
        self.db_path = db_path
        self._create_database()

    def _create_database(self) -> None:
        with _lock:
            conn = get_connection(self.db_path)   # DB-01: WAL + PRAGMAs
            try:
                conn.execute('''
                    CREATE TABLE IF NOT EXISTS Settings (
                        id            INTEGER PRIMARY KEY,
                        setting_name  TEXT UNIQUE,
                        setting_value TEXT
                    )
                ''')
                defaults = [
                    ("preferred_dns_server", "8.8.8.8"),
                    ("alternate_dns_server",  "8.8.4.4"),
                    ("reset_to_dhcp",         "True"),
                ]
                for name, value in defaults:
                    conn.execute(
                        "INSERT OR IGNORE INTO Settings "
                        "(setting_name, setting_value) VALUES (?,?)",
                        (name, value)
                    )
                conn.commit()
                log.info("NetworkSettings: DB ready at %s", self.db_path)
            except Exception as e:
                conn.rollback()
                log.error("NetworkSettings: _create_database failed — %s", e)
                raise
            finally:
                conn.close()   # BUG-02 FIX: always closed

    def update_setting(self, setting_name: str, setting_value: str) -> bool:
        with _lock:
            conn = get_connection(self.db_path)
            try:
                conn.execute(
                    "INSERT OR REPLACE INTO Settings "
                    "(setting_name, setting_value) VALUES (?,?)",
                    (setting_name, setting_value)
                )
                conn.commit()
                log.info("NetworkSettings: '%s' updated to '%s'",
                         setting_name, setting_value)
                return True
            except Exception as e:
                conn.rollback()
                log.error("NetworkSettings: update_setting('%s') failed — %s",
                          setting_name, e)
                return False
            finally:
                conn.close()

    def get_setting(self, setting_name: str) -> Optional[str]:
        with _lock:
            conn = get_connection(self.db_path)
            try:
                row = conn.execute(
                    "SELECT setting_value FROM Settings WHERE setting_name=?",
                    (setting_name,)
                ).fetchone()
                return row["setting_value"] if row else None
            except Exception as e:
                log.error("NetworkSettings: get_setting('%s') failed — %s",
                          setting_name, e)
                return None
            finally:
                conn.close()


# ─────────────────────────────────────────────────────────────────
# DB READ
# ─────────────────────────────────────────────────────────────────
def read_network_settings_from_db() -> Dict[str, Optional[str]]:
    """
    Read all network-relevant settings from DB in one pass.
    DB-01 FIX: uses get_connection() instead of bare sqlite3.connect().
    """
    keys = [
        "Set IP Address", "Subnet mask", "Gateway",
        "preferred_dns_server", "alternate_dns_server",
        "reset_to_dhcp", "Enable/Disable Static/dynamic"
    ]
    settings = {k: None for k in keys}

    with _lock:
        conn = get_connection(DB_NETWORK_SETTINGS)
        try:
            for key in keys:
                row = conn.execute(
                    "SELECT setting_value FROM Settings WHERE setting_name=?",
                    (key,)
                ).fetchone()
                if row and row["setting_value"]:
                    settings[key] = row["setting_value"].strip()
        except Exception as e:
            log.error("read_network_settings_from_db failed — %s", e)
        finally:
            conn.close()

    return settings


# ─────────────────────────────────────────────────────────────────
# VALIDATION
# ─────────────────────────────────────────────────────────────────
def validate_ip(ip) -> bool:
    """
    Validate an IPv4 address string.

    BUG-01 FIX: original crashed with TypeError when ip=None.
    validate_ip(gateway) where gateway was None (no gateway in DB)
    raised TypeError on every boot. Fixed: None/type check first.
    """
    if not ip or not isinstance(ip, str):
        return False
    pattern = r"^(?:[0-9]{1,3}\.){3}[0-9]{1,3}$"
    if not re.match(pattern, ip):
        return False
    return all(0 <= int(part) <= 255 for part in ip.split("."))


def subnet_mask_to_cidr(mask: str) -> int:
    return sum(bin(int(x)).count('1') for x in mask.split('.'))


# ─────────────────────────────────────────────────────────────────
# DHCPCD.CONF HELPERS
# ─────────────────────────────────────────────────────────────────
def backup_dhcpcd() -> Optional[str]:
    """
    Create a timestamped backup of dhcpcd.conf before any changes.

    CODE-02 FIX: original backed up only once to a fixed path —
    meaning the very first config was kept forever as the backup.
    Every subsequent change had no individual backup.
    Fixed: timestamped backup per change in BACKUP_DIR.

    Returns backup path on success, None on failure.
    """
    os.makedirs(BACKUP_DIR, exist_ok=True)
    timestamp   = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = os.path.join(BACKUP_DIR, f"dhcpcd.conf.{timestamp}")

    try:
        subprocess.run(
            ["sudo", "cp", DHCPCD_CONF_PATH, backup_path],
            check=True, capture_output=True, text=True
        )
        log.info("dhcpcd backup created: %s", backup_path)
        return backup_path
    except subprocess.CalledProcessError as e:
        log.error("backup_dhcpcd failed — %s", e.stderr)
        return None


def remove_interface_config(content: List[str], interface: str) -> List[str]:
    """Remove existing static block for an interface from dhcpcd.conf lines."""
    cleaned = []
    skip    = False
    for line in content:
        if line.strip().startswith(f"interface {interface}"):
            skip = True
        if not skip:
            cleaned.append(line)
        if skip and line.strip() == "":
            skip = False
    return cleaned


# noinspection PyTypeHints
def generate_static_block(interface: str, ip: str, mask: str,
                           gateway: Optional[str] = None,
                           dns_list: Optional[List[str]] = None) -> List[str]:
    cidr  = subnet_mask_to_cidr(mask)
    block = [f"interface {interface}"]
    if interface == "wlan0":
        block.append("nohook wpa_supplicant")
    block.append(f"static ip_address={ip}/{cidr}")
    if gateway:
        block.append(f"static routers={gateway}")
    if dns_list:
        block.append(f"static domain_name_servers={' '.join(dns_list)}")
    block.append("")
    return block


def _write_dhcpcd_atomic(lines: List[str]) -> bool:
    """
    BUG-05 FIX: original wrote directly to DHCPCD_CONF_PATH.
    Power loss or crash mid-write → empty/corrupt dhcpcd.conf →
    RPi cannot get a network address on next boot.

    Fixed: write to .tmp, fsync, then os.replace() which is atomic
    on Linux. Either old file intact or new file intact — never partial.
    """
    tmp_path = DHCPCD_CONF_PATH + ".tmp"
    try:
        content = [
            line if line.endswith("\n") else line + "\n"
            for line in lines
        ]
        with open(tmp_path, "w") as f:
            f.writelines(content)
            f.flush()
            os.fsync(f.fileno())              # flush to SD card

        os.replace(tmp_path, DHCPCD_CONF_PATH)   # atomic on Linux
        return True
    except Exception as e:
        log.error("_write_dhcpcd_atomic failed — %s", e)
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        return False


# /etc/network/interfaces path — used when dhcpcd and NM both ignore eth0
INTERFACES_PATH = "/etc/network/interfaces"


def _apply_interfaces_static(ip: str, mask: str, gateway: str = None) -> bool:
    """
    Write static config to /etc/network/interfaces.
    Used when eth0 is unmanaged by both dhcpcd and NetworkManager.
    """
    lines = []
    try:
        with open(INTERFACES_PATH, "r") as f:
            lines = f.readlines()
    except Exception:
        lines = ["# /etc/network/interfaces\n", "source /etc/network/interfaces.d/*\n"]

    # Remove existing eth0 block
    cleaned = []
    skip = False
    for line in lines:
        if line.strip().startswith("iface eth0") or line.strip().startswith("auto eth0") or            line.strip().startswith("allow-hotplug eth0"):
            skip = True
        if not skip:
            cleaned.append(line)
        if skip and line.strip() == "":
            skip = False

    # Add new static block
    cleaned.append("\n")
    cleaned.append("auto eth0\n")
    cleaned.append("iface eth0 inet static\n")
    cleaned.append(f"    address {ip}\n")
    cleaned.append(f"    netmask {mask}\n")
    if gateway:
        cleaned.append(f"    gateway {gateway}\n")
    cleaned.append("\n")

    tmp = INTERFACES_PATH + ".tmp"
    try:
        with open(tmp, "w") as f:
            f.writelines(cleaned)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, INTERFACES_PATH)
        return True
    except Exception as e:
        log.error("_apply_interfaces_static failed — %s", e)
        return False


def _apply_interfaces_dhcp() -> bool:
    """Switch eth0 back to DHCP in /etc/network/interfaces."""
    lines = []
    try:
        with open(INTERFACES_PATH, "r") as f:
            lines = f.readlines()
    except Exception:
        lines = []

    cleaned = []
    skip = False
    for line in lines:
        if line.strip().startswith("iface eth0") or line.strip().startswith("auto eth0") or            line.strip().startswith("allow-hotplug eth0"):
            skip = True
        if not skip:
            cleaned.append(line)
        if skip and line.strip() == "":
            skip = False

    cleaned.append("\n")
    cleaned.append("auto eth0\n")
    cleaned.append("iface eth0 inet dhcp\n")
    cleaned.append("\n")

    tmp = INTERFACES_PATH + ".tmp"
    try:
        with open(tmp, "w") as f:
            f.writelines(cleaned)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, INTERFACES_PATH)
        return True
    except Exception as e:
        log.error("_apply_interfaces_dhcp failed — %s", e)
        return False


def apply_static_settings(eth_config: dict, wlan_config: dict) -> bool:
    """
    Apply static IP to eth0.
    Strategy: write to BOTH dhcpcd.conf AND /etc/network/interfaces
    then apply immediately using ip commands.
    Works regardless of whether dhcpcd, NetworkManager, or ifupdown is active.
    """
    ip      = eth_config["ip"]
    mask    = eth_config["mask"]
    gateway = eth_config.get("gateway")
    dns_list= eth_config.get("dns_list") or []
    cidr    = subnet_mask_to_cidr(mask)

    # 1. Write dhcpcd.conf (for dhcpcd-managed systems)
    try:
        with open(DHCPCD_CONF_PATH, "r") as f:
            lines = f.readlines()
        lines = remove_interface_config(lines, "eth0")
        lines += generate_static_block("eth0", **eth_config)
        _write_dhcpcd_atomic(lines)
        log.info("dhcpcd.conf updated")
    except Exception as e:
        log.warning("dhcpcd.conf write failed (non-fatal) — %s", e)

    # 2. Write /etc/network/interfaces (for ifupdown/unmanaged systems)
    _apply_interfaces_static(ip, mask, gateway)
    log.info("interfaces file updated")

    # 3. Apply immediately using ip command (works on any system)
    try:
        subprocess.run(["sudo", "ip", "addr", "flush", "dev", "eth0"],
                       capture_output=True, timeout=10)
        subprocess.run(["sudo", "ip", "addr", "add", f"{ip}/{cidr}", "dev", "eth0"],
                       check=True, capture_output=True, text=True, timeout=10)
        subprocess.run(["sudo", "ip", "link", "set", "eth0", "up"],
                       check=True, capture_output=True, text=True, timeout=10)
        if gateway:
            subprocess.run(["sudo", "ip", "route", "add", "default", "via", gateway, "dev", "eth0"],
                           capture_output=True, timeout=10)
        log.info("Static IP applied immediately — %s/%s gw=%s", ip, cidr, gateway)
        return True
    except subprocess.CalledProcessError as e:
        log.error("ip command failed — %s", e.stderr)
        return False
    except Exception as e:
        log.error("apply_static_settings failed — %s", e)
        return False


def switch_to_dhcp() -> bool:
    """Switch eth0 back to DHCP."""
    # 1. Update dhcpcd.conf
    try:
        with open(DHCPCD_CONF_PATH, "r") as f:
            lines = f.readlines()
        lines = remove_interface_config(lines, "eth0")
        _write_dhcpcd_atomic(lines)
    except Exception as e:
        log.warning("dhcpcd.conf DHCP write failed (non-fatal) — %s", e)

    # 2. Update /etc/network/interfaces
    _apply_interfaces_dhcp()

    # 3. Apply immediately
    try:
        subprocess.run(["sudo", "ip", "addr", "flush", "dev", "eth0"],
                       capture_output=True, timeout=10)
        subprocess.run(["sudo", "dhclient", "eth0"],
                       capture_output=True, timeout=30)
        log.info("DHCP requested on eth0")
        return True
    except Exception as e:
        log.error("switch_to_dhcp failed — %s", e)
        return False


def restart_dhcpcd() -> bool:
    """
    Apply network config — works regardless of network manager.
    eth0 is unmanaged by both dhcpcd and NetworkManager on this Pi,
    so we use ifup/ifdown with /etc/network/interfaces.
    """
    try:
        subprocess.run(["sudo", "ifdown", "eth0"],
                       capture_output=True, timeout=10)
        subprocess.run(["sudo", "ifup", "eth0"],
                       capture_output=True, timeout=15)
        log.info("eth0 brought down and up via ifupdown")
        return True
    except Exception as e:
        log.warning("ifup/ifdown failed — %s", e)

    # Fallback: just restart networking service
    try:
        subprocess.run(["sudo", "systemctl", "restart", "networking"],
                       capture_output=True, timeout=15)
        log.info("networking service restarted")
        return True
    except Exception as e:
        log.error("restart networking failed — %s", e)
        return False


# ─────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────
def main() -> None:
    """
    Read network settings from DB and apply static IP or DHCP config.

    BUG-03 FIX: original ran 10+ DB queries and log.info() statements at
    module import level — every import triggered DB access and stdout output.
    All DB access now inside main() only.
    """
    settings = read_network_settings_from_db()

    # PRIMARY decision: "Enable/Disable Static/dynamic" set by LCD toggle
    # SECONDARY: reset_to_dhcp — only use if Static/dynamic not set in DB
    # IMPORTANT: reset_to_dhcp defaults to "True" and is never cleared after
    # LCD sets static IP — so it CANNOT be the sole trigger for DHCP switch.
    # Only switch to DHCP if engineer explicitly set Static/dynamic = "dynamic".
    static_dynamic = settings.get("Enable/Disable Static/dynamic")
    reset_flag     = settings.get("reset_to_dhcp", "False")

    if static_dynamic == "dynamic":
        log.info("Enable/Disable Static/dynamic=dynamic — enabling DHCP")
        if switch_to_dhcp():
            restart_dhcpcd()
        return

    # If Static/dynamic not set in DB yet (new device) AND reset_to_dhcp is
    # explicitly "True" → also switch to DHCP
    if static_dynamic is None and reset_flag == "True":
        log.info("No Static/dynamic setting found, reset_to_dhcp=True — enabling DHCP")
        if switch_to_dhcp():
            restart_dhcpcd()
        return

    # Otherwise → apply static IP (Static/dynamic = "Static" or not set but
    # reset_to_dhcp = "False" meaning engineer has configured static)

    ip_eth  = settings.get("Set IP Address")
    mask    = settings.get("Subnet mask")
    gateway = settings.get("Gateway")
    dns1    = settings.get("preferred_dns_server")
    dns2    = settings.get("alternate_dns_server")

    # BUG-01 FIX: validate_ip(None) was a TypeError crash in original
    if not validate_ip(ip_eth):
        log.error("Invalid or missing IP address: '%s' — aborting", ip_eth)
        return
    if not validate_ip(mask):
        log.error("Invalid or missing subnet mask: '%s' — aborting", mask)
        return

    # DNS is optional — local LAN without internet should leave DNS empty
    # so dhcpcd.conf doesn't add unreachable DNS servers (8.8.8.8 etc.)
    dns_list = []
    if validate_ip(dns1) and dns1 not in ("0.0.0.0", ""):
        dns_list.append(dns1)
    if validate_ip(dns2) and dns2 not in ("0.0.0.0", ""):
        dns_list.append(dns2)
    # If both DNS are defaults (8.8.8.8 / 8.8.4.4) and gateway is None
    # (pure local LAN), skip DNS entries — they will time out
    if not validate_ip(gateway) and dns_list == ["8.8.8.8", "8.8.4.4"]:
        log.info("No gateway set — skipping default DNS entries for local LAN")
        dns_list = []

    eth_config = {
        "ip":       ip_eth,
        "mask":     mask,
        "gateway":  gateway if validate_ip(gateway) else None,
        "dns_list": dns_list if dns_list else None,
    }
    wlan_config = {
        "ip":       WLAN_STATIC_IP,
        "mask":     WLAN_STATIC_MASK,
        "gateway":  None,
        "dns_list": None,
    }

    backup_dhcpcd()

    if apply_static_settings(eth_config, wlan_config):
        restart_dhcpcd()
        log.info(
            "Static IP applied — IP=%s mask=%s gw=%s dns=%s",
            ip_eth, mask, gateway, dns_list
        )
    else:
        log.error("apply_static_settings failed — dhcpcd not restarted")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s"
    )
    main()