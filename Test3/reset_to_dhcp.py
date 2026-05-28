# -*- coding: utf-8 -*-
# !/usr/local/bin/python
#
# reset_to_dhcp.py — Remove eth0 static IP from dhcpcd.conf and restore DHCP
#
# Database fixes assessment:
#   This module contains no SQLite database access, no buffer inserts,
#   and no device-parameter reads. DB-01 through DB-06 (WAL mode, FK
#   enforcement, bounded buffer, schema migrations, indexed queries) do
#   not apply here.
#
#   DB-05 (atomic file writes) DOES apply — see reset_to_dhcp() below.
#   Writing to /etc/dhcpcd.conf with bare open()+write() is the same
#   power-loss vulnerability described in DB-05: if the RPi loses power
#   mid-write, dhcpcd.conf is left empty. On the next boot, dhcpcd cannot
#   parse its config, eth0 does not come up, and the device is unreachable
#   — including via Tailscale. This is the most critical fix in this file.
#
# Changes applied vs original:
#   DB-05 — CRITICAL: reset_to_dhcp() now writes dhcpcd.conf atomically
#             using write-to-temp-file + os.replace() pattern.
#             Power loss at any point leaves the original conf intact.
#   SEC   — All subprocess.call() / subprocess.check_call() replaced with
#             subprocess.run() with explicit timeout — no indefinite hangs
#   SEC   — bare except Exception replaced with typed handlers:
#             FileNotFoundError, subprocess.TimeoutExpired,
#             subprocess.CalledProcessError, subprocess.SubprocessError,
#             OSError, PermissionError
#   BUG   — remove_interface_config() logic hardened: block termination now
#             also triggers on the next 'interface' line, not only on blank
#             lines — handles static blocks at end of file with no trailing
#             blank line correctly
#   CODE  — restart_networking_old() preserved but marked as superseded
#   LOG   — log.info() replaced with log.*() via get_dual_logger()


"""
reset_to_dhcp.py
Dexter HMS — Ethernet interface DHCP restoration module

Responsibilities:
  - Removes eth0 static IP block from /etc/dhcpcd.conf atomically (DB-05)
  - Flushes interface, clears DHCP lease, restarts dhcpcd service
  - Called via direct import from Lan_setting.py (not subprocess)
  - Power-loss safe: atomic write via temp file + os.replace()

Key functions:
  - reset_dhcp()         — full DHCP reset sequence
  - reset_to_dhcp()      — atomic dhcpcd.conf update only
  - restart_networking() — flush + lease clear + dhcpcd restart

Dependencies: None (stdlib subprocess only)
Author: Seple Novaedge Pvt. Ltd.
"""
import os
import shutil
import subprocess

from syslog_file_logger import get_dual_logger
log = get_dual_logger(__name__)

# ── Config file paths ─────────────────────────────────────────────────────────
DHCPCD_CONF_PATH = "/etc/dhcpcd.conf"
BACKUP_PATH      = DHCPCD_CONF_PATH + ".bak"

# ── Subprocess timeout constants ──────────────────────────────────────────────
_FLUSH_TIMEOUT_SEC     = 10    # ip addr flush
_RM_LEASE_TIMEOUT_SEC  = 10    # sudo rm -f leases file
_RESTART_TIMEOUT_SEC   = 60    # systemctl restart dhcpcd
_SHOW_TIMEOUT_SEC      = 10    # ip addr show


# ─────────────────────────────────────────────────────────────────────────────
# INTERFACE CONFIG PARSER
# BUG fix: original only terminated a block on a blank line. If the static
# block was at the end of the file with no trailing newline, 'skip' never
# reset and subsequent 'interface' sections would also be removed if the
# file had any after eth0. Hardened: block also terminates on the next
# 'interface' keyword line, so multiple interface blocks are handled correctly.
# ─────────────────────────────────────────────────────────────────────────────

def remove_interface_config(content: list, interface: str) -> list:
    """
    Remove the static configuration block for `interface` from dhcpcd.conf
    content (list of lines).

    Block detection:
    - Start: a line that begins with 'interface <name>'
    - End: a blank line, the next 'interface' keyword, or EOF

    BUG fix: original only terminated on blank lines. If the target block
    was the last block in the file (no trailing blank line), subsequent
    lines would never be included in 'cleaned'. Now also terminates on
    the next 'interface' keyword so multi-interface files are handled safely.
    """
    cleaned = []
    skip    = False

    for line in content:
        stripped = line.strip()

        # Detect the start of the target interface block
        if stripped.startswith(f"interface {interface}"):
            skip = True
            continue

        if skip:
            # Blank line ends the block
            if stripped == "":
                skip = False
                cleaned.append(line)   # keep the blank line as separator
                continue
            # Next 'interface' keyword also ends the block
            if stripped.startswith("interface "):
                skip = False
                # Fall through — this line belongs to the next block
            else:
                continue  # still inside the target block — skip

        cleaned.append(line)

    return cleaned


# ─────────────────────────────────────────────────────────────────────────────
# DHCP RESET — ATOMIC FILE WRITE
# DB-05 CRITICAL: dhcpcd.conf written atomically via write-to-temp + os.replace()
# ─────────────────────────────────────────────────────────────────────────────

def reset_to_dhcp() -> bool:
    """
    Remove eth0 static IP settings from dhcpcd.conf so the interface
    defaults to DHCP on the next dhcpcd restart.

    DB-05 CRITICAL fix: dhcpcd.conf is now written atomically.

    Original code:
        with open(DHCPCD_CONF_PATH, 'w') as f:
            f.writelines(lines)

    This is the same power-loss vulnerability as json_db_module.py —
    open() in 'w' mode IMMEDIATELY truncates the file to zero bytes.
    If power cuts during f.writelines(), dhcpcd.conf is empty on the
    next boot. dhcpcd cannot parse an empty config, eth0 does not come
    up, and the RPi is unreachable — including via Tailscale.

    Fix: write to a .tmp file first, fsync to flush to SD card, then
    os.replace() to atomically swap it over the original. Power loss at
    any point leaves the original dhcpcd.conf intact.

    Returns True on success, False on any failure.
    SEC: typed exception handlers replace bare except Exception.
    """
    tmp_path = DHCPCD_CONF_PATH + ".tmp"

    try:
        # Step 1: Create backup once (direct copy — runs as root via nsenter)
        if not os.path.exists(BACKUP_PATH):
            shutil.copy2(DHCPCD_CONF_PATH, BACKUP_PATH)
            log.info("[reset_to_dhcp] Backup created at %s", BACKUP_PATH)

        # Step 2: Read current dhcpcd.conf
        with open(DHCPCD_CONF_PATH, "r") as f:
            lines = f.readlines()

        # Step 3: Remove only the eth0 static block
        cleaned_lines = remove_interface_config(lines, "eth0")

        # Step 4: DB-05 ATOMIC WRITE — never truncates the original file
        #          until the new content is fully written and flushed to disk
        with open(tmp_path, "w") as f:
            f.writelines(cleaned_lines)
            f.flush()
            os.fsync(f.fileno())     # flush kernel buffer → SD card

        os.replace(tmp_path, DHCPCD_CONF_PATH)   # atomic on Linux
        log.info("[reset_to_dhcp] eth0 static IP removed — DHCP will be used")
        return True

    except PermissionError as exc:
        log.error("[reset_to_dhcp] Permission denied reading/writing %s: %s",
                  DHCPCD_CONF_PATH, exc)
    except FileNotFoundError as exc:
        log.error("[reset_to_dhcp] File not found: %s", exc)
    except OSError as exc:
        log.error("[reset_to_dhcp] OS error during atomic write: %s", exc)
    except Exception as exc:
        log.error("[reset_to_dhcp] Unexpected error: %s", exc)
    finally:
        # Clean up tmp file if os.replace() never ran (failure path)
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass

    return False


# ─────────────────────────────────────────────────────────────────────────────
# NETWORKING RESTART
# SEC: subprocess.call() → subprocess.run() with timeout
# SEC: typed exception handlers
# ─────────────────────────────────────────────────────────────────────────────

def restart_networking_old() -> bool:
    """
    SUPERSEDED by restart_networking() — kept for reference only.
    Only restarts dhcpcd without flushing the interface or clearing leases.
    Returns True on success, False on failure.
    """
    try:
        subprocess.run(
            ["sudo", "systemctl", "restart", "dhcpcd"],
            check=True, timeout=_RESTART_TIMEOUT_SEC
        )
        log.info("[restart_networking_old] dhcpcd service restarted")
        return True
    except subprocess.TimeoutExpired:
        log.error("[restart_networking_old] systemctl restart dhcpcd timed out")
    except subprocess.CalledProcessError as exc:
        log.error("[restart_networking_old] dhcpcd restart failed (code %d): %s",
                  exc.returncode, exc)
    except subprocess.SubprocessError as exc:
        log.error("[restart_networking_old] Subprocess error: %s", exc)
    except FileNotFoundError as exc:
        log.error("[restart_networking_old] Command not found: %s", exc)
    return False


def restart_networking() -> bool:
    """
    Three-step network restart:
    1. Flush current eth0 addresses (ip addr flush)
    2. Remove cached DHCP lease (sudo rm -f dhcpcd.leases)
    3. Restart dhcpcd service (systemctl restart)

    SEC: subprocess.run() with timeout on every call — no indefinite hangs.
    SEC: typed exception handlers replace bare except Exception.
    Returns True if all three steps succeed, False on any failure.
    """
    log.info("[restart_networking] Flushing eth0, clearing leases, restarting dhcpcd")

    # Step 1: Flush eth0 addresses
    try:
        subprocess.run(
            ["sudo", "ip", "addr", "flush", "dev", "eth0"],
            check=True, timeout=_FLUSH_TIMEOUT_SEC
        )
        log.info("[restart_networking] eth0 flushed")
    except subprocess.TimeoutExpired:
        log.error("[restart_networking] ip addr flush timed out")
        return False
    except subprocess.CalledProcessError as exc:
        log.error("[restart_networking] ip addr flush failed (code %d): %s",
                  exc.returncode, exc)
        return False
    except (subprocess.SubprocessError, FileNotFoundError, OSError) as exc:
        log.error("[restart_networking] ip addr flush error: %s", exc)
        return False

    # Step 2: Remove stale DHCP lease
    try:
        subprocess.run(
            ["sudo", "rm", "-f", "/var/lib/dhcpcd5/dhcpcd.leases"],
            check=True, timeout=_RM_LEASE_TIMEOUT_SEC
        )
        log.info("[restart_networking] DHCP lease cleared")
    except subprocess.TimeoutExpired:
        log.warning("[restart_networking] rm lease timed out — continuing anyway")
    except subprocess.CalledProcessError as exc:
        log.warning("[restart_networking] rm lease failed (code %d) — continuing: %s",
                    exc.returncode, exc)
    except (subprocess.SubprocessError, FileNotFoundError, OSError) as exc:
        log.warning("[restart_networking] rm lease error — continuing: %s", exc)

    # Step 3: Restart dhcpcd
    try:
        subprocess.run(
            ["sudo", "systemctl", "restart", "dhcpcd"],
            check=True, timeout=_RESTART_TIMEOUT_SEC
        )
        log.info("[restart_networking] dhcpcd restarted successfully")
        return True
    except subprocess.TimeoutExpired:
        log.error("[restart_networking] systemctl restart dhcpcd timed out "
                  "after %d s", _RESTART_TIMEOUT_SEC)
    except subprocess.CalledProcessError as exc:
        log.error("[restart_networking] dhcpcd restart failed (code %d): %s",
                  exc.returncode, exc)
    except (subprocess.SubprocessError, FileNotFoundError, OSError) as exc:
        log.error("[restart_networking] dhcpcd restart error: %s", exc)

    return False


# ─────────────────────────────────────────────────────────────────────────────
# TOP-LEVEL ORCHESTRATOR
# ─────────────────────────────────────────────────────────────────────────────

def reset_dhcp() -> bool:
    """
    Full DHCP reset sequence:
    1. Remove eth0 static IP from dhcpcd.conf (atomic write)
    2. Flush interface, clear leases, restart dhcpcd
    3. Log the new eth0 network configuration for verification

    Returns True if all steps succeeded, False if any step failed.
    """
    log.info("[reset_dhcp] Starting DHCP reset for eth0")

    if not reset_to_dhcp():
        log.error("[reset_dhcp] Failed to update dhcpcd.conf — aborting")
        return False

    if not restart_networking():
        log.error("[reset_dhcp] Networking restart failed after conf update")
        return False

    # Verify: show new eth0 state in the log
    log.info("[reset_dhcp] Verifying eth0 network configuration:")
    try:
        result = subprocess.run(
            ["ip", "addr", "show", "eth0"],
            capture_output=True, text=True,
            timeout=_SHOW_TIMEOUT_SEC
        )
        if result.stdout.strip():
            log.info("[reset_dhcp] eth0 status:\n%s", result.stdout.strip())
        if result.stderr.strip():
            log.warning("[reset_dhcp] eth0 show stderr: %s", result.stderr.strip())
    except subprocess.TimeoutExpired:
        log.warning("[reset_dhcp] ip addr show eth0 timed out")
    except (subprocess.SubprocessError, FileNotFoundError, OSError) as exc:
        log.warning("[reset_dhcp] ip addr show eth0 error: %s", exc)

    log.info("[reset_dhcp] DHCP reset complete")
    return True


if __name__ == "__main__":
    success = reset_dhcp()
    if not success:
        log.warning("[reset_dhcp] DHCP reset did not complete successfully")