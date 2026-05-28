"""
net_reboot.py
Dexter HMS — Rate-limited remote reboot handler

Matches old architecture: pon → sleep → net_reboot_done → poff → reboot.
dexter-serial-comm is NOT stopped.

Changes from old architecture:
  FIX-01: Rate limiter with try/except fallback.
  FIX-02: Fernet-decrypted credentials via net_reboot_done.main().
  FIX-03: poff before reboot — releases /dev/ttyS0 cleanly.
  FIX-04: import logging; log defined.
"""

import subprocess
import time
import logging

import net_reboot_done

log = logging.getLogger(__name__)

try:
    from rate_limiter import reboot_limiter
    _rate_limiter_available = True
except ImportError:
    reboot_limiter = None
    log.warning("net_reboot: rate_limiter not available")
    _rate_limiter_available = False


def main():
    """Rate-limited reboot — max 3 per hour (SEC-08)."""
    if _rate_limiter_available and not reboot_limiter.allow():
        log.info("Reboot rate limit exceeded — max 3 per hour. Ignored.")
        return

    log.info("net_reboot: starting reboot sequence")

    subprocess.call(["sudo", "pon", "c16qs"])
    time.sleep(10)   # wait for PPP + DNS

    # ppp0 is now the only default internet route — no route manipulation needed.
    time.sleep(3)

    net_reboot_done.main()
    time.sleep(5)

    # Drop modem before reboot — releases /dev/ttyS0
    subprocess.call(["sudo", "poff", "c16qs"])
    time.sleep(3)

    log.info("net_reboot: rebooting")
    subprocess.call(["sudo", "reboot"])


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s — %(message)s")
    main()
