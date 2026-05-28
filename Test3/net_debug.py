"""
net_debug.py
Dexter HMS — Remote debug mode activator

Matches old architecture: pon → sleep → run → poff.
dexter-serial-comm is NOT stopped — it will auto-restart if [Errno 16]
occurs when pppd grabs /dev/ttyS0. This is identical to old arch behaviour.

Changes from old architecture:
  FIX-01: Credentials from modem_config.db with Fernet decrypt (not hardcoded).
  FIX-02: Direct function calls (net_ota_done.main, debugip.main) instead of
          subprocess to python scripts — cleaner, same effect.
  FIX-03: poff after completion — old arch did not poff in net_debug,
          but we add it to release ttyS0 for dexter-serial-comm restart.
  FIX-04: net_ota_done runs AFTER poff (over ethernet) — avoids carrier
          blocking HTTPS on PPP. debugip runs BEFORE poff (MQTT over PPP).
"""

import subprocess
import time
import logging

log = logging.getLogger(__name__)

import net_ota_done
import debugip


def _is_ppp_up() -> bool:
    """Return True if ppp0 interface is up with a valid IP."""
    try:
        result = subprocess.run(
            ["ip", "addr", "show", "ppp0"],
            capture_output=True, text=True, timeout=5
        )
        return result.returncode == 0 and "inet " in result.stdout
    except Exception:
        return False


def execute_commands():
    # Enable SSH
    subprocess.call(["sudo", "systemctl", "enable", "ssh"])
    subprocess.call(["sudo", "systemctl", "start", "ssh"])
    log.info("SSH enabled.")

    # Bring modem up — dexter-serial-comm stays running (old arch behaviour).
    # pppd will wait for ttyS0 lock to be released between AT commands.
    subprocess.call(["sudo", "pon", "c16qs"])

    # Wait for ppp0 to actually come up — variable time depending on when
    # dexter-serial-comm releases ttyS0. Poll instead of fixed sleep.
    log.info("net_debug: waiting for ppp0...")
    ppp_up = False
    for _ in range(40):   # 40 * 3s = 120s max
        if _is_ppp_up():
            ppp_up = True
            log.info("net_debug: ppp0 is up")
            break
        time.sleep(3)

    if not ppp_up:
        log.error("net_debug: ppp0 did not come up within 120s — aborting")
        subprocess.call(["sudo", "poff", "c16qs"])
        return

    # ppp0 is now the only default internet route — eth0 has no gateway
    # (removed from /etc/network/interfaces permanently). No route manipulation needed.
    time.sleep(5)

    # Publish Tailscale IP via MQTT (port 8883) over ppp0
    debugip.main()
    time.sleep(5)

    # Send care=done via HTTPS over ppp0 (before poff — ppp0 is internet)
    net_ota_done.main()
    time.sleep(2)

    # SSH WINDOW: keep ppp0 up for 3 minutes after publishing Tailscale IP.
    # This gives enough time to SSH in via Tailscale for remote debugging.
    # To extend the window further, run 'sudo pon c16qs' immediately after SSH in.
    log.info("net_debug: SSH window open — 3 minutes to connect via Tailscale")
    log.info("net_debug: Tailscale IP is 100.97.13.127 (check ThingsBoard attributes)")
    time.sleep(180)
    log.info("net_debug: SSH window closing — dropping modem")

    subprocess.call(["sudo", "poff", "c16qs"])
    time.sleep(3)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s"
    )
    execute_commands()
