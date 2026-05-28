# -*- coding: utf-8 -*-
# !/usr/local/bin/python
"""
panel_network — Network interface probe helpers

Extracted from TLChronosProMAIN_391.py as part of Sprint C decomposition.
These functions had zero dependency on hardware globals (lcd, keypad,
shiftRegister buffers, zoneSettings) and could be safely moved.

Public functions:
#   send_tailscale_info()
#   get_ip_address()
#   get_mac_address()
#   get_default_gateway()
#   get_dns_servers()

Sprint C: Option C — safe partial extraction of stand-alone utility functions.
          Full PanelController decomposition deferred to Sprint C2 (requires
          unit tests first — see OPEN-01).
"""
import sqlite3
import subprocess
import socket
import logging

from syslog_file_logger import get_dual_logger
from db_connection import DB_TAILSCALE
log = get_dual_logger(__name__)


def send_tailscale_info() -> None:
    """Read latest Tailscale hostname and IP from DB and publish to ThingsBoard."""
    from panel_telemetry import sendData2TB  # local import avoids circular dependency
    try:
        conn = sqlite3.connect(DB_TAILSCALE)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT tailscale_hostname, tailscale_ip FROM device_info "            "ORDER BY timestamp DESC LIMIT 1"
        )
        row = cursor.fetchone()
        conn.close()

        if row:
            tailscale_hostname, tailscale_ip = row
            log_data = {
                "tailscale_data": [{
                    "tailscale_hostname": tailscale_hostname,
                    "tailscale_ip":       tailscale_ip
                }]
            }
            sendData2TB(log_data)
        else:
            log.debug("[send_tailscale_info] No Tailscale data in DB yet")

    except Exception as ex:
        # Fix: was logger.error (undefined) with comma-style args — now log.error with %s
        log.error("[send_tailscale_info] %s", ex)



def get_ip_address():
    """
    Retrieves the IP address of the LAN interface.

    Returns:
        str: The IP address or 'N/A' if not found.
    """
    try:
        ifconfig_output = subprocess.check_output(['ifconfig', 'eth0'], stderr=subprocess.STDOUT)
        ifconfig_output = ifconfig_output.decode('utf-8')   # Decode bytes to string (python 3)
        for line in ifconfig_output.splitlines():
            if 'inet ' in line:
                return line.split()[1]
    except subprocess.CalledProcessError as exc:
        # ERR-01: was silent pass — log so network diagnostic failures are visible
        log.debug("[network_info] ifconfig/ip command failed: %s", exc)
    return 'N/A'


def get_mac_address():
    """
    Retrieves the MAC address of the LAN interface.

    Returns:
        str: The MAC address or 'N/A' if not found.
    """
    try:
        ifconfig_output = subprocess.check_output(['ifconfig', 'eth0'], stderr=subprocess.STDOUT)
        ifconfig_output = ifconfig_output.decode('utf-8')  # Decode bytes to string (python 3)
        for line in ifconfig_output.splitlines():
            if 'ether ' in line:
                return line.split()[1]
    except subprocess.CalledProcessError as exc:
        # ERR-01: was silent pass — log so network diagnostic failures are visible
        log.debug("[network_info] ifconfig/ip command failed: %s", exc)
    return 'N/A'


def get_default_gateway():
    """
    Retrieves the default gateway.

    Returns:
        str: The default gateway or 'N/A' if not found.
    """
    try:
        route_output = subprocess.check_output(['ip', 'route', 'show'], stderr=subprocess.STDOUT)
        route_output = route_output.decode('utf-8')  # Decode bytes to string (python 3)
        for line in route_output.splitlines():
            if 'default via' in line:
                return line.split()[2]
    except subprocess.CalledProcessError as exc:
        # ERR-01: was silent pass — log so network diagnostic failures are visible
        log.debug("[network_info] ifconfig/ip command failed: %s", exc)
    return 'N/A'


def get_dns_servers():
    """
    Retrieves the DNS servers.

    Returns:
        list: A list of DNS server addresses or ['N/A'] if none are found.
    """
    try:
        dns_servers = []
        with open('/etc/resolv.conf', 'r') as resolv_file:
            for line in resolv_file:
                if line.startswith('nameserver'):
                    dns_servers.append(line.split()[1])
        if dns_servers:
            return dns_servers
    except IOError as exc:
        # ERR-01: was silent pass — log so DNS config read failures are visible
        log.debug("[network_info] /etc/resolv.conf read failed: %s", exc)
    return ['N/A']




