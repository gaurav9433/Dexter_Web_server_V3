"""
net_ota.py
Dexter HMS — OTA Update Orchestrator

Runs the full OTA sequence:
  pon → net_ota_rollover (download+apply) → net_ota_done (care=done) → poff → reboot

Changes from old architecture:
  FIX-01: 'log' variable used but never defined → NameError on rate limit.
           Added: import logging; log = logging.getLogger(__name__)
  FIX-02: rate_limiter import wrapped in try/except — if rate_limiter.py
           is missing, OTA proceeds without rate limiting (with a warning).
"""

import subprocess
import time
import logging

log = logging.getLogger(__name__)

try:
    from rate_limiter import ota_limiter
    _rate_limiter_available = True
except ImportError:
    ota_limiter = None
    log.warning("net_ota: rate_limiter not available — proceeding without rate limiting")
    _rate_limiter_available = False



def execute_commands():
    # Rate limit check: max 1 OTA per hour
    if _rate_limiter_available and not ota_limiter.allow():
        log.info("OTA rate limit exceeded — max 1 update per hour. Request ignored.")
        return

    log.info("net_ota: starting OTA sequence")

    subprocess.call(["sudo", "pon", "c16qs"])
    time.sleep(5)

    try:
        subprocess.check_call(["python3", "/home/pi/Test3/net_ota_rollover.py"])
    except subprocess.CalledProcessError as e:
        log.error("net_ota: net_ota_rollover failed — %s", e)
        subprocess.call(["sudo", "poff", "c16qs"])
        return

    time.sleep(20)

    try:
        subprocess.check_call(["python3", "/home/pi/Test3/net_ota_done.py"])
    except subprocess.CalledProcessError as e:
        log.error("net_ota: net_ota_done failed — %s", e)

    time.sleep(10)
    subprocess.call(["sudo", "poff", "c16qs"])
    time.sleep(5)
    subprocess.call(["sudo", "reboot"])


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s")
    execute_commands()
