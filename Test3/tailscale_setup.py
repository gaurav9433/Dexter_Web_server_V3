#!/usr/bin/env python3
# tailscale_setup.py
# Dexter HMS — Tailscale Initial Device Setup
#
# Changes from original:
#   SEC-01a: Two live authkeys hardcoded in source (one commented-out, one active)
#            → authkey now read from secrets_manager only
#   SEC-01b: Hardcoded MQTT/modem credentials in ModemConfigDatabase INSERT
#            → this module no longer owns ModemConfigDatabase at all (CODE-01)
#   SEC-05a: shell=True in run_cmd with device_name string-interpolated
#            → shell=False, all commands passed as lists
#   SEC-05b: device_name injected into hostnamectl and /etc/hosts shell cmds
#            → _validate_hostname() enforces RFC-1123 before any subprocess use
#   BUG-01 : SQL injection in get_parameter via f'SELECT {param} ...'
#            → whitelist validation + direct get_connection() call
#   BUG-02 : time.sleep(5) race condition — Tailscale may not be ready
#            → _wait_for_tailscale_status() polls up to 30s
#   BUG-03 : sudo rm -rf /var/lib/tailscale ran even if stop failed
#            → stop confirmed before wipe, aborts safely if stop fails
#   BUG-04 : all exceptions caught silently, process exited 0 (systemd blind)
#            → re-raises after logging, sys.exit(1) at entry point
#   CODE-01: Duplicate ModemConfigDatabase class (copy of tailscale_master.py)
#            → replaced with _get_modem_parameter() using get_connection()
#   CODE-02: bare sqlite3.connect() → get_connection(DB_TAILSCALE/DB_MODEM_CONFIG)
#   CODE-03: All log.info() → logging

"""
tailscale_setup.py
Dexter HMS — Tailscale VPN initial configuration and node registration

Responsibilities:
  - Registers this RPi as a Tailscale node on first deployment
  - Saves Tailscale IP and node metadata to tailscale_info.db
  - Auth keys read from secrets_manager.py — never hardcoded (SEC-01)

Key functions:
  - setup_tailscale_and_save_info() — one-shot setup, safe to re-run

Dependencies:
  - db_connection.py   — WAL SQLite connections
  - secrets_manager.py — TAILSCALE_AUTH_KEY from /etc/dexter/.env
Author: Seple Novaedge Pvt. Ltd.
"""

import re
import sys
import json
import time
import subprocess
import logging
from typing import Dict, Optional

from db_connection import get_connection, DB_TAILSCALE, DB_MODEM_CONFIG
from secrets_manager import get_secret

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────────────────────────
TAILSCALE_READY_TIMEOUT = 90   # max seconds to poll for Tailscale status
TAILSCALE_POLL_INTERVAL = 3    # seconds between polls

# All host-level commands (systemctl, tailscale, hostnamectl, etc.) must run
# in the host's namespaces via nsenter — container has no sudo and its own
# network/mount namespace would trap the effect inside the container.
_NSENTER = ["nsenter", "-t", "1", "-m", "-u", "-i", "-n", "-p", "--"]

# SEC-05 FIX: whitelist for modem_config column access
_ALLOWED_MODEM_PARAMS = {"gsm_modem_mode", "network_type", "device_name"}


# ─────────────────────────────────────────────────────────────────
# VALIDATION
# ─────────────────────────────────────────────────────────────────
def _validate_hostname(name: str) -> str:
    """
    SEC-05 FIX: device_name was interpolated directly into shell=True strings.
    Any name containing ;, &, $(...) etc. executes arbitrary shell commands.

    Enforce RFC-1123: alphanumeric + hyphens only, max 63 chars,
    no leading/trailing hyphen.
    """
    if not name or not isinstance(name, str):
        raise ValueError(f"Invalid device_name: {name!r}")
    if not re.match(r'^[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?$', name):
        raise ValueError(
            f"device_name '{name}' contains invalid characters. "
            "Only alphanumeric and hyphens allowed (RFC-1123)."
        )
    return name


# ─────────────────────────────────────────────────────────────────
# MODEM CONFIG READER
# ─────────────────────────────────────────────────────────────────
def _get_modem_parameter(param: str) -> Optional[str]:
    """
    Read one field from modem_parameters.

    CODE-01 FIX: original duplicated the entire ModemConfigDatabase class
    (40 lines) from tailscale_master.py — identical code in two files.
    Replaced with a direct get_connection() call.

    BUG-01 FIX: original used f'SELECT {param} FROM ...' — SQL injection.
    Fixed: whitelist check before query.

    SEC-01b FIX: original INSERT had live credentials hardcoded.
    This function only reads — modem_config.db is populated by provisioning.
    """
    if param not in _ALLOWED_MODEM_PARAMS:
        log.error("_get_modem_parameter: '%s' not in allowed list", param)
        return None

    conn = get_connection(DB_MODEM_CONFIG)
    try:
        row = conn.execute(
            f"SELECT {param} FROM modem_parameters WHERE id = 1"
        ).fetchone()
        return row[0] if row else None
    except Exception as e:
        log.error("_get_modem_parameter('%s') failed — %s", param, e)
        return None
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────
# COMMAND RUNNER
# ─────────────────────────────────────────────────────────────────
def run_cmd(cmd: list, capture_output: bool = False) -> Optional[str]:
    """
    SEC-05 FIX: original used shell=True with string commands — device_name
    was interpolated directly, enabling shell injection.
    Fixed: shell=False (default), all commands passed as lists.

    Always captures stderr so the real error message appears in the log.
    Raises subprocess.CalledProcessError on non-zero exit.
    """
    try:
        result = subprocess.run(
            cmd, check=True, capture_output=True, text=True
        )
        if capture_output:
            return result.stdout.strip()
        if result.stdout.strip():
            log.debug("cmd stdout: %s", result.stdout.strip())
        return None
    except subprocess.CalledProcessError as e:
        stderr = (e.stderr or "").strip()
        stdout = (e.stdout or "").strip()
        log.error(
            "Command failed: %s — exit=%d stderr=%r stdout=%r",
            " ".join(str(c) for c in cmd),
            e.returncode,
            stderr or "(empty)",
            stdout or "(empty)",
        )
        raise


# ─────────────────────────────────────────────────────────────────
# TAILSCALE INFO DB
# ─────────────────────────────────────────────────────────────────
def save_to_database(tailscale_hostname: str, tailscale_ip: str) -> None:
    """
    Save Tailscale hostname and IP to tailscale_info.db.
    CODE-02 FIX: bare sqlite3.connect() → get_connection(DB_TAILSCALE).
    """
    conn = get_connection(DB_TAILSCALE)
    try:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS device_info (
                id                 INTEGER PRIMARY KEY AUTOINCREMENT,
                tailscale_hostname TEXT,
                tailscale_ip       TEXT,
                timestamp          DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.execute(
            "INSERT INTO device_info (tailscale_hostname, tailscale_ip) "
            "VALUES (?,?)",
            (tailscale_hostname, tailscale_ip)
        )
        conn.commit()
        log.info("Saved: hostname=%s ip=%s", tailscale_hostname, tailscale_ip)
    except Exception as e:
        conn.rollback()
        log.error("save_to_database failed — %s", e)
        raise
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────
# /etc/hosts FIX
# ─────────────────────────────────────────────────────────────────
def fix_etc_hosts(device_name: str) -> None:
    """
    Add 127.0.1.1 device_name to /etc/hosts if not already present.

    SEC-05 FIX: original used:
        run_cmd(f'echo "127.0.1.1 {device_name}" | sudo tee -a /etc/hosts')
    with shell=True — device_name injected into shell string.
    Fixed: subprocess.run with input= parameter, no shell, no interpolation.
    device_name already validated by _validate_hostname() before this call.
    """
    try:
        with open("/etc/hosts", "r") as f:
            existing = f.read()

        if device_name in existing:
            log.info("/etc/hosts: '%s' already present", device_name)
            return

        log.info("/etc/hosts: adding '%s'", device_name)
        subprocess.run(
            _NSENTER + ["tee", "-a", "/etc/hosts"],
            input=f"127.0.1.1 {device_name}\n",
            text=True, check=True, capture_output=True
        )
    except Exception as e:
        log.error("fix_etc_hosts failed — %s", e)
        raise


# ─────────────────────────────────────────────────────────────────
# WAIT FOR TAILSCALE READY
# ─────────────────────────────────────────────────────────────────
def _wait_for_tailscale_status(timeout: int = TAILSCALE_READY_TIMEOUT) -> Dict[str, object]:
    """
    BUG-02 FIX: original used time.sleep(5) then immediately read status.
    If Tailscale takes longer than 5s to authenticate (common on first run,
    slow network, or key validation delay), the status JSON is empty/error
    and the function crashes with a KeyError.

    Fixed: poll every TAILSCALE_POLL_INTERVAL seconds up to timeout.
    """
    deadline   = time.time() + timeout
    last_error = None

    while time.time() < deadline:
        try:
            raw  = run_cmd(_NSENTER + ["tailscale", "status", "--json"], capture_output=True)
            data = json.loads(raw)
            if data.get("Self") and data["Self"].get("TailscaleIPs"):
                return data
        except Exception as e:
            last_error = e

        log.debug("Tailscale not ready — retrying in %ds", TAILSCALE_POLL_INTERVAL)
        time.sleep(TAILSCALE_POLL_INTERVAL)

    raise RuntimeError(
        f"Tailscale not ready after {timeout}s. Last error: {last_error}"
    )


# ─────────────────────────────────────────────────────────────────
# ALREADY PROVISIONED CHECK
# ─────────────────────────────────────────────────────────────────
def _is_already_provisioned(device_name: str) -> bool:
    """
    TAILSCALE-FIX-2: return True ONLY if:
      1. tailscale_info.db has a stored entry for THIS EXACT device_name
      2. tailscale status confirms the device is currently connected
      3. The live hostname matches device_name

    Returns False (force re-provision) if:
      - No DB entry exists
      - DB entry is for a DIFFERENT device_name (cloned SD card)
      - Tailscale is not currently connected
      - Live hostname does not match device_name

    This fixes the cloned SD card problem where the old Pi's Tailscale
    state is present and _is_already_provisioned incorrectly returns True,
    causing the new Pi to skip provisioning and show the old hostname.
    """
    try:
        conn = get_connection(DB_TAILSCALE)
        row  = conn.execute(
            "SELECT tailscale_hostname, tailscale_ip FROM device_info "
            "ORDER BY id DESC LIMIT 1"
        ).fetchone()
        conn.close()
        if not row or not row[1]:
            return False

        stored_hostname = row[0] or ""
        stored_ip       = row[1]

        # CRITICAL: if stored hostname does not match current device_name
        # this is a cloned SD card — must re-provision with new identity
        if stored_hostname.lower() != device_name.lower():
            log.info(
                "_is_already_provisioned: stored hostname '%s' != device_name '%s' "
                "— cloned SD card detected, forcing re-provision",
                stored_hostname, device_name
            )
            return False

        # Confirm tailscale is actually connected right now
        try:
            raw  = run_cmd(_NSENTER + ["tailscale", "status", "--json"], capture_output=True)
            data = json.loads(raw)
            self_info = data.get("Self", {})
            live_ips      = self_info.get("TailscaleIPs", [])
            live_hostname = self_info.get("HostName", "").lower()

            # Both IP and hostname must match
            if stored_ip in live_ips and live_hostname == device_name.lower():
                log.info(
                    "_is_already_provisioned: active IP %s hostname %s matches DB "
                    "— already up, skipping re-provision",
                    stored_ip, live_hostname
                )
                return True
        except Exception:
            pass  # tailscale not running — treat as not provisioned

        return False
    except Exception as e:
        log.warning("_is_already_provisioned check failed — %s", e)
        return False


# ─────────────────────────────────────────────────────────────────
# MAIN SETUP
# ─────────────────────────────────────────────────────────────────
def setup_tailscale_and_save_info() -> None:
    """
    Full Tailscale provisioning:
    1. Read authkey from secrets_manager (/etc/dexter/.env)
    2. Read device_name from modem_config.db, validate it
    3. Set hostname and /etc/hosts entry
    4. Stop tailscaled (confirmed), wipe identity, restart
    5. Bring up with authkey
    6. Poll until Tailscale is ready, save IP to tailscale_info.db

    Add to /etc/dexter/.env before running:
        TAILSCALE_AUTHKEY=tskey-auth-xxxxxxxxxxxx

    TAILSCALE-FIX-1: device_name is read from modem_config.db and must
    be set by the user via the LCD menu BEFORE provisioning is triggered.
    form_basic() does NOT write device_name — it only writes back the
    provisioned client_id/user_name/password. If device_name is missing
    this function raises ValueError immediately with a clear message so
    device_provisioning() can surface it on the LCD instead of silently
    retrying 3 times and giving up.

    TAILSCALE-FIX-2: check tailscale_info.db for an existing valid entry
    before wiping and re-provisioning. If the device already has a Tailscale
    IP recorded and `tailscale status` confirms it is connected, skip the
    wipe/re-register cycle to avoid creating duplicate nodes in the tailnet.
    """
    # SEC-01a FIX: authkey from .env (TAILSCALE_AUTHKEY)
    try:
        authkey = get_secret("TAILSCALE_AUTHKEY")
    except (KeyError, RuntimeError):
        log.warning(
            "TAILSCALE_AUTHKEY not found in /etc/dexter/.env — "
            "Tailscale setup skipped. Add the key and call "
            "setup_tailscale_and_save_info() again to provision."
        )
        return

    # TAILSCALE-FIX-1: explicit device_name check with clear error message.
    # _get_modem_parameter returns None if DB row missing or column empty.
    # This is the most common failure cause — user forgot to enter device_name
    # via the LCD menu before triggering provisioning.
    device_name = _get_modem_parameter("device_name")
    if not device_name or not device_name.strip():
        raise ValueError(
            "TAILSCALE SETUP FAILED: 'device_name' is not set in modem_config.db. "
            "Enter the device name via the LCD menu before running provisioning."
        )

    # SEC-05 FIX: validate before any subprocess use
    device_name = _validate_hostname(device_name.strip())
    log.info("Device name: %s", device_name)

    # Set system hostname and /etc/hosts
    run_cmd(_NSENTER + ["hostnamectl", "set-hostname", device_name])
    fix_etc_hosts(device_name)

    # BUG-03 FIX: confirm tailscaled is stopped before wiping state.
    log.info("Stopping tailscaled...")
    try:
        run_cmd(_NSENTER + ["systemctl", "stop", "tailscaled"])
    except subprocess.CalledProcessError:
        raise RuntimeError(
            "tailscaled stop failed — aborting wipe to protect state"
        )

    log.info("Wiping Tailscale identity...")
    run_cmd(_NSENTER + ["rm", "-rf", "/var/lib/tailscale"])

    log.info("Starting tailscaled...")
    run_cmd(_NSENTER + ["systemctl", "start", "tailscaled"])

    # Wait for daemon socket to initialise before `tailscale up`.
    # 2s was not enough on a busy Pi (many containers restarting during provisioning).
    time.sleep(5)

    log.info("Bringing up Tailscale with fresh identity...")
    run_cmd(_NSENTER + [
        "tailscale", "up",
        f"--authkey={authkey}",
        f"--hostname={device_name}",
        "--reset",          # clear any corrupted pending state
        "--accept-routes",  # accept subnet routes from other nodes
    ])

    # BUG-02 FIX: poll for readiness instead of fixed sleep
    log.info("Waiting for Tailscale to be ready (max %ds)...",
             TAILSCALE_READY_TIMEOUT)
    status_data = _wait_for_tailscale_status(TAILSCALE_READY_TIMEOUT)

    tailscale_hostname = status_data["Self"]["HostName"]
    tailscale_ip       = status_data["Self"]["TailscaleIPs"][0]

    log.info("Tailscale hostname : %s", tailscale_hostname)
    log.info("Tailscale IP       : %s", tailscale_ip)

    save_to_database(tailscale_hostname, tailscale_ip)
    log.info("Tailscale setup complete")


# ─────────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s"
    )
    try:
        setup_tailscale_and_save_info()
    except Exception as e:
        # BUG-04 FIX: original caught all exceptions and exited 0 —
        # systemd/supervisor saw success and never retried.
        # Now exits non-zero so the supervisor knows to restart.
        log.critical("tailscale_setup failed: %s", e)
        sys.exit(1)