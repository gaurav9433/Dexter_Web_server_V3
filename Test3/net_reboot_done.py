"""
net_reboot_done.py
Dexter HMS — Post-reboot 'care=done' REST notification to ThingsBoard

Sends {"care":"done"} to the device's SERVER_SCOPE attributes via TB REST API.
Called by net_reboot.py after reboot RPC is received.

Changes from old architecture:
  FIX-01: Hardcoded credentials replaced with Fernet-decrypted values
          from modem_config.db (swatch_username/password).
  FIX-02: Module-level execution removed. Wrapped in main() function.
  FIX-03: exit() replaced with return False.
  FIX-04: Added logging throughout.
"""

import logging
import time
import sqlite3
import requests
from requests.exceptions import HTTPError, RequestException

log = logging.getLogger(__name__)

BASE_URL = "https://www.dexterhms.com"


def _read_modem(col: str) -> str:
    try:
        conn = sqlite3.connect("/home/pi/Test3/modem_config.db")
        row = conn.execute(
            f"SELECT {col} FROM modem_parameters WHERE id=1"
        ).fetchone()
        conn.close()
        return (row[0] or "").strip() if row else ""
    except Exception as e:
        log.warning("net_reboot_done: DB read failed for %s: %s", col, e)
        return ""


def _dec(val: str) -> str:
    if not val:
        return val
    try:
        import sys
        sys.path.insert(0, "/home/pi/Test3")
        from secrets_manager import decrypt_value
        return decrypt_value(val)
    except Exception:
        return val


def main() -> bool:
    """
    Login to ThingsBoard, find the device by name, send {"care":"done"}.
    Returns True on success, False on any failure.
    Retries up to 5 times on DNS/connection failures.
    """
    device_name = _read_modem("device_name")
    username    = _dec(_read_modem("swatch_username"))
    password    = _dec(_read_modem("swatch_password"))

    if not device_name:
        log.error("net_reboot_done: device_name not set in modem_config.db")
        return False
    if not username or not password:
        log.error("net_reboot_done: swatch_username/password not set")
        return False

    log.info("net_reboot_done: starting for device '%s'", device_name)

    for _attempt in range(5):
        try:
            resp = requests.post(
                f"{BASE_URL}/api/auth/login",
                json={"username": username, "password": password},
                timeout=10
            )
            resp.raise_for_status()
            jwt_token = resp.json()["token"]
            headers = {"X-Authorization": f"Bearer {jwt_token}"}
            log.info("net_reboot_done: authenticated successfully")

            device_id = None
            page = 0
            while True:
                r = requests.get(
                    f"{BASE_URL}/api/tenant/devices?pageSize=100&page={page}",
                    headers=headers, timeout=10
                )
                r.raise_for_status()
                data = r.json()
                for device in data.get("data", []):
                    if device["name"] == device_name:
                        device_id = device["id"]["id"]
                        break
                if device_id or not data.get("hasNext"):
                    break
                page += 1

            if not device_id:
                log.error("net_reboot_done: device '%s' not found", device_name)
                return False

            r = requests.post(
                f"{BASE_URL}/api/plugins/telemetry/DEVICE/{device_id}/SERVER_SCOPE",
                headers={**headers, "Content-Type": "application/json"},
                json={"care": "done"},
                timeout=10
            )
            r.raise_for_status()
            log.info("net_reboot_done: care=done sent to '%s'", device_name)
            return True

        except (RequestException, OSError) as e:
            if _attempt < 4:
                log.warning("net_reboot_done: attempt %d/5 failed — retrying in 5s (%s)",
                            _attempt + 1, e)
                time.sleep(5)
            else:
                log.error("net_reboot_done: all 5 attempts failed — %s", e)
                return False
        except HTTPError as e:
            log.error("net_reboot_done: HTTP error %s — %s", e.response.status_code, e)
            return False
        except Exception as e:
            log.error("net_reboot_done: unexpected error — %s", e)
            return False

    return False


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s — %(message)s")
    sys.exit(0 if main() else 1)
