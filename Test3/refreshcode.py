# refreshcode.py
# Dexter HMS — Push Local Device Config to ThingsBoard
#
# Reads local state from all DBs and config files, assembles it into
# the 'dexter_config' shared attribute, and publishes to ThingsBoard.
#
# MQTT credentials (client_id, user_name, password) come from modem_config.db.
# Companion: updatecode.py pulls and applies config from ThingsBoard.
#
# Changes from original:
#   SEC-07 : Plain MQTT port 1883 → TLS port 8883
#   SEC-04 : get_devices_info returned plaintext passwords → decrypt_value()
#   BUG-01 : SQL injection in ModemConfigDatabase.get_parameter via .format()
#            → class removed; _get_modem_parameter() with whitelist used
#   BUG-02 : bare except: swallowed all DB errors in 5 functions
#            → specific Exception handling with logging
#   BUG-03 : get_modem_info selected device_name twice (columns 0 and 7)
#            → named columns in SELECT, dict built by column name
#   BUG-04 : published = {"done": False} dict + manual sleep/poll —
#            shared mutable dict accessed from two threads with no lock
#            → threading.Event, on_publish signals it cleanly
#   BUG-05 : batt hardcoded as "67" stale placeholder
#            → BATT_PLACEHOLDER constant, clearly marked
#   CODE-01 : ModemConfigDatabase class duplicated → _get_modem_parameter()
#   CODE-02 : All bare sqlite3.connect() → get_connection() + WAL
#   CODE-03 : No try/finally in DB readers → added throughout
#   CODE-04 : All print() → logging
#   ERR-05  — Fernet fallback now logs warning with device id and remediation hint
#             Previously: silent except Exception swallowed key-mismatch errors

import json
import ssl
import threading
import logging
import os
from datetime import datetime
from typing import Dict, List, Optional

import paho.mqtt.client as mqtt

from db_connection import (
    get_connection,
    DB_MODEM_CONFIG, DB_DEVICE_CONFIG, DB_LOGICAL_PARAMS,
    DB_NETWORK_SETTINGS,
)
from device_parameters_module import decrypt_value
from cryptography.fernet import InvalidToken

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────────────────────────
THINGSBOARD_HOST     = "www.dexterhms.com"
MQTT_PORT            = 8883   # SEC-07 FIX: TLS port (was 1883)
MQTT_PUBLISH_TIMEOUT = 10     # seconds to wait for PUBACK

#POWER_TEXT_FILE = "/home/pi/TLChronosPro/powerZoneSettings.txt"
#ZONE_TEXT_FILE  = "/home/pi/TLChronosPro/zoneSettings.txt"
#BRANCH_FILE     = "/home/pi/TLChronosPro/Branch.txt"
#BRAND_FILE      = "/home/pi/TLChronosPro/Brand.txt"

POWER_TEXT_FILE = "/home/pi/Test3/powerZoneSettings.txt"
ZONE_TEXT_FILE  = "/home/pi/Test3/zoneSettings.txt"
BRANCH_FILE     = "/home/pi/Test3/Branch.txt"
BRAND_FILE      = "/home/pi/Test3/Brand.txt"

# BUG-05 FIX: was hardcoded "67" — stale placeholder never wired to
# real battery reading. Replace with ControllerDatabaseManager.get_battery_voltage()
# when available.
BATT_PLACEHOLDER = "67"

# Written by device_provisioning() on success; cleared after first send.
PROVISIONING_FLAG = "/home/pi/Test3/.provisioning_done"

# Whitelist for modem_config column access
_ALLOWED_MODEM_PARAMS = {
    "access_token", "client_id", "user_name",
    "password", "gsm_modem_mode", "network_type", "device_name"
}


# ─────────────────────────────────────────────────────────────────
# MODEM CONFIG READER
# ─────────────────────────────────────────────────────────────────
def _get_modem_parameter(param: str) -> Optional[str]:
    """
    CODE-01 FIX: replaces the duplicated ModemConfigDatabase class.
    BUG-01 FIX: original used .format(param) — SQL injection.
    BUG-02 FIX: original had bare except: — all errors swallowed silently.
    """
    if param not in _ALLOWED_MODEM_PARAMS:
        log.error("_get_modem_parameter: '%s' not in allowed list", param)
        return None
    conn = get_connection(DB_MODEM_CONFIG)
    try:
        row = conn.execute(
            f"SELECT {param} FROM modem_parameters WHERE id = 1"
        ).fetchone()
        if not row or row[0] is None:
            return None
        raw = row[0]
        # SEC-04: values are Fernet-encrypted in DB — decrypt before returning.
        # If the value is not encrypted (plaintext legacy), return as-is.
        if isinstance(raw, str) and raw.startswith('gAAAAA'):
            try:
                return decrypt_value(raw)
            except Exception as _dec_err:
                log.error("_get_modem_parameter('%s') decrypt failed — %s",
                          param, _dec_err)
                return None
        return raw
    except Exception as e:
        log.error("_get_modem_parameter('%s') failed — %s", param, e)
        return None
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────
# FILE READERS
# ─────────────────────────────────────────────────────────────────
def read_powerzone_string() -> str:
    try:
        with open(POWER_TEXT_FILE, "r") as f:
            values = [p for line in f for p in line.strip().split()]
        return "{" + " ".join(values) + "}"
    except Exception as e:
        log.error("read_powerzone_string failed — %s", e)
        return "{}"


def read_zone_string() -> str:
    try:
        with open(ZONE_TEXT_FILE, "r") as f:
            values = [p for line in f for p in line.strip().split()]
        return "{" + " ".join(values) + "}"
    except Exception as e:
        log.error("read_zone_string failed — %s", e)
        return "{}"


def read_branch_name() -> str:
    try:
        with open(BRANCH_FILE, "r") as f:
            return f.readline().strip()
    except Exception as e:
        log.error("read_branch_name failed — %s", e)
        return "Unknown"


def read_brand_name() -> str:
    try:
        with open(BRAND_FILE, "r") as f:
            return f.readline().strip()
    except Exception as e:
        log.error("read_brand_name failed — %s", e)
        return "Unknown"


# ─────────────────────────────────────────────────────────────────
# DB READERS
# ─────────────────────────────────────────────────────────────────

def _mask_camera_ip(camera_ip: object) -> object:
    if not isinstance(camera_ip, list):
        return camera_ip
    masked = []
    for cam in camera_ip:
        c = dict(cam)
        if "password" in c:
            c["password"] = "NA"
        if "username" in c:
            c["username"] = "NA"
        masked.append(c)
    return masked


def get_devices_info(mask_credentials: bool = False) -> List[Dict]:
    """
    Fetch all devices from device_parameters.

    SEC-04 FIX: passwords stored encrypted by device_parameters_module.
    decrypt_value() applied before returning in payload.
    CODE-02/03 FIX: get_connection() + try/finally.
    """
    conn = get_connection(DB_DEVICE_CONFIG)
    try:
        rows = conn.execute(
            "SELECT id, device_type, ip_address, username, "
            "password, port, camera_ip FROM device_parameters"
        ).fetchall()

        devices = []
        for row in rows:
            camera_ip = None
            if row["camera_ip"]:
                try:
                    cams = json.loads(row["camera_ip"])
                    if isinstance(cams, list):
                        for cam in cams:
                            if cam.get("password"):
                                try:
                                    cam["password"] = decrypt_value(cam["password"])
                                except (InvalidToken, Exception):
                                    pass  # already plaintext (legacy row)
                    camera_ip = cams
                except (ValueError, TypeError):
                    camera_ip = row["camera_ip"]

            try:
                password = decrypt_value(row["password"])
            except InvalidToken:
                # ERR-05: Fernet key mismatch or pre-migration plaintext value.
                # Log so operator knows to re-run migrate_plaintext_credentials()
                # if the key was recently rotated.
                log.warning(
                    "[get_devices_info] Fernet decryption failed for device id=%s "
                    "— using raw value. Re-run migrate_plaintext_credentials() "
                    "if the Fernet key was recently rotated.",
                    row.get("id")
                )
                password = row["password"]

            devices.append({
                "id":          row["id"],
                "device_type": row["device_type"],
                "ip_address":  row["ip_address"],
                "username":    "NA" if mask_credentials else row["username"],
                "password":    "NA" if mask_credentials else password,
                "port":        row["port"],
                "camera_ip":   _mask_camera_ip(camera_ip) if mask_credentials else camera_ip,
            })
        return devices
    except Exception as e:
        log.error("get_devices_info failed — %s", e)
        return []
    finally:
        conn.close()


def get_modem_info() -> Dict[str, Optional[str]]:
    """
    BUG-03 FIX: original SELECT had device_name as both column 0 and 7.
    row[0] was silently discarded; row[7] used as device_name. Fixed:
    named columns, dict built by column name — no positional guessing.
    """
    conn = get_connection(DB_MODEM_CONFIG)
    try:
        row = conn.execute("""
            SELECT access_token, client_id, user_name, password,
                   gsm_modem_mode, network_type, device_name
            FROM modem_parameters WHERE id = 1
        """).fetchone()
        if row is None:
            return {}
        return {
            "access_token":   row["access_token"],
            "client_id":      row["client_id"],
            "user_name":      row["user_name"],
            "password":       row["password"],
            "gsm_modem_mode": row["gsm_modem_mode"],
            "network_type":   row["network_type"],
            "device_name":    row["device_name"],
        }
    except Exception as e:
        log.error("get_modem_info failed — %s", e)
        return {}
    finally:
        conn.close()


def get_active_device_info() -> Dict[str, object]:
    conn = get_connection(DB_LOGICAL_PARAMS)
    try:
        rows = conn.execute(
            "SELECT name, value FROM parameters ORDER BY id ASC"
        ).fetchall()
        return {row["name"]: row["value"] for row in rows}
    except Exception as e:
        log.error("get_active_device_info failed — %s", e)
        return {}
    finally:
        conn.close()


def get_network_info() -> Dict[str, Optional[str]]:
    conn = get_connection(DB_NETWORK_SETTINGS)
    try:
        rows = conn.execute(
            "SELECT setting_name, setting_value FROM Settings ORDER BY id ASC"
        ).fetchall()
        return {row["setting_name"]: row["setting_value"] for row in rows}
    except Exception as e:
        log.error("get_network_info failed — %s", e)
        return {}
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────
# MAIN — BUILD AND SEND CONFIG
# ─────────────────────────────────────────────────────────────────
def send_dexter_config(max_retries: int = 3, retry_delay: int = 5) -> bool:
    """
    Assemble local state and publish as 'dexter_config' attribute.

    Credentials: client_id, user_name, password from modem_config.db —
    same pattern as the original module.
    SEC-07 FIX: TLS port 8883.
    BUG-04 FIX: threading.Event replaces fragile published={} dict + sleep loop.
    """
    CLIENT_ID = str(_get_modem_parameter("client_id") or "")
    USERNAME  = str(_get_modem_parameter("user_name") or "")
    PASSWORD  = str(_get_modem_parameter("password") or "")

    if not CLIENT_ID or not USERNAME:
        log.error("send_dexter_config: missing MQTT credentials in modem_config.db")
        return False

    mask_credentials = os.path.exists(PROVISIONING_FLAG)
    if mask_credentials:
        log.info("send_dexter_config: provisioning flag detected — masking credentials in dexter_config")
        try:
            os.remove(PROVISIONING_FLAG)
        except OSError as _e:
            log.warning("send_dexter_config: could not remove provisioning flag — %s", _e)

    dexter_config = {
        "powerzone":               read_powerzone_string(),
        "zone":                    read_zone_string(),
        "brand":                   read_brand_name(),
        "branch":                  read_branch_name(),
        "modem_parameter":         get_modem_info(),
        "integration":             get_devices_info(mask_credentials=mask_credentials),
        "active_device_parameter": get_active_device_info(),
        "network_parameter":       get_network_info(),
        "batt":                    BATT_PLACEHOLDER,
        "timestamp":               datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
    }
    payload = json.dumps({"dexter_config": dexter_config})

    # SEC-07 FIX: TLS context
    ctx = ssl.create_default_context()
    ctx.check_hostname  = True
    ctx.verify_mode     = ssl.CERT_REQUIRED
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2

    for attempt in range(1, max_retries + 1):
        # BUG-04 FIX: Event — thread-safe, no shared mutable dict + sleep poll
        published = threading.Event()

        def on_connect(client, userdata, flags: dict, rc: int, props=None) -> None:  # type: ignore[override]
            if rc == 0:
                log.info("refreshcode: connected, publishing config...")
                client.publish("v1/devices/me/attributes", payload, qos=1)
            else:
                log.error("refreshcode: broker rejected rc=%s", rc)
                published.set()

        def on_publish(client, userdata, mid: int, rc=None, props=None) -> None:
            log.info("refreshcode: publish confirmed mid=%s", mid)
            published.set()

        client = mqtt.Client(
            client_id=CLIENT_ID,
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            clean_session=True
        )
        client.username_pw_set(USERNAME, PASSWORD)
        client.tls_set_context(ctx)
        client.on_connect = on_connect
        client.on_publish = on_publish

        try:
            client.connect(THINGSBOARD_HOST, MQTT_PORT, keepalive=60)
            client.loop_start()

            if published.wait(timeout=MQTT_PUBLISH_TIMEOUT):
                log.info("refreshcode: config sent successfully (attempt %d)",
                         attempt)
                return True

            log.warning("refreshcode: publish timeout on attempt %d", attempt)
            raise TimeoutError("Publish not confirmed")

        except Exception as e:
            log.error("refreshcode: attempt %d/%d failed — %s",
                      attempt, max_retries, e)
            if attempt < max_retries:
                import time
                log.info("refreshcode: retrying in %ds...", retry_delay)
                time.sleep(retry_delay)
                retry_delay *= 2
        finally:
            client.loop_stop()
            client.disconnect()

    log.error("refreshcode: all %d attempts failed", max_retries)
    return False


if __name__ == "__main__":
    import sys
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s"
    )
    sys.exit(0 if send_dexter_config() else 1)