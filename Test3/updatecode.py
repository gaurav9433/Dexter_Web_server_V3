# updatecode.py
# Dexter HMS — Pull & Apply Device Config from ThingsBoard
#
# Subscribes to the 'dexter_config' shared attribute, receives a JSON
# blob, and applies each section to the appropriate local DB / file.
#
# MQTT credentials (client_id, user_name, password) come from modem_config.db.
# Companion: refreshcode.py pushes local state back to ThingsBoard.
#
# Changes from original:
#   SEC-07 : Plain MQTT port 1883 → TLS port 8883
#   SEC-04 : update_from_telemetry wrote device passwords to DB in plaintext
#            → encrypt_value() applied before storage
#   BUG-01 : SQL injection in ModemConfigDatabase.get_parameter via f-string
#            → class removed; _get_modem_parameter() with whitelist used
#   BUG-02 : bare except: in get_parameter swallowed ALL exceptions silently
#            → specific Exception handling with logging
#   BUG-03 : loop_forever() — no timeout if broker never responds
#            → loop_start() + threading.Event with 30s timeout
#   BUG-04 : write_powerzone_to_file / write_zone_to_file: IndexError if
#            data string had fewer than 48 numbers (16 rows × 3 cols)
#            → bounds check before loop
#   BUG-05 : set_rtc_from_timestamp had no try/except — any RTC/I2C error
#            raised inside on_message and silently killed remaining sections
#            → wrapped in try/except, error logged, processing continues
#   BUG-06 : No try/finally in update_config_table and others → conn leaked
#            → try/finally throughout
#   CODE-01 : ModemConfigDatabase class duplicated (6th copy in codebase)
#             → _get_modem_parameter() with get_connection() + whitelist
#   CODE-02 : All bare sqlite3.connect() → get_connection() + WAL
#   CODE-03 : ROW_OFFSET magic constant → named ZONE_ROWS
#   CODE-04 : All print() → logging

from __future__ import annotations

import json
import ssl
import threading
import datetime
import logging
from typing import Optional, List

import paho.mqtt.client as mqtt
from SDL_DS1307 import SDL_DS1307

from db_connection import (
    get_connection,
    DB_MODEM_CONFIG, DB_DEVICE_CONFIG, DB_LOGICAL_PARAMS,
    DB_NETWORK_SETTINGS,
)
from device_parameters_module import encrypt_value
from secrets_manager import decrypt_value

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────────────────────────
MQTT_BROKER  = "www.dexterhms.com"
MQTT_PORT    = 8883   # SEC-07 FIX: TLS port (was 1883)

POWER_FILE  = "/home/pi/Test3/powerZoneSettings.txt"
ZONE_FILE   = "/home/pi/Test3/zoneSettings.txt"
BRANCH_FILE = "/home/pi/Test3/Branch.txt"
BRAND_FILE  = "/home/pi/Test3/Brand.txt"

ZONE_ROWS        = 16
COLS_PER_ROW     = 3
REQUIRED_NUMBERS = ZONE_ROWS * COLS_PER_ROW   # 48

MQTT_CONNECT_TIMEOUT = 30   # BUG-03: seconds before giving up

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
    BUG-01 FIX: original used f'SELECT {param}' — SQL injection.
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
# FILE WRITERS
# ─────────────────────────────────────────────────────────────────
# noinspection PyTypeHints
def _parse_numbers(data_string: str) -> Optional[List[int]]:
    """
    BUG-04 FIX: parse and validate number count before any file write.
    Original looped directly — if fewer than 48 numbers, IndexError on
    numbers[i+2] left a partially written file.
    """
    try:
        cleaned = data_string.strip().lstrip("{").rstrip("}")
        numbers = [int(x) for x in cleaned.strip().split()]
        if len(numbers) < REQUIRED_NUMBERS:
            log.error(
                "_parse_numbers: expected %d numbers, got %d — aborting write",
                REQUIRED_NUMBERS, len(numbers)
            )
            return None
        return numbers
    except (ValueError, AttributeError) as e:
        log.error("_parse_numbers failed — %s", e)
        return None


def write_powerzone_to_file(data_string: str) -> bool:
    numbers = _parse_numbers(data_string)
    if numbers is None:
        return False
    try:
        with open(POWER_FILE, "w") as f:
            for x in range(ZONE_ROWS):
                i = x * COLS_PER_ROW
                f.write(f"{numbers[i]} {numbers[i+1]} {numbers[i+2]}\n")
        log.info("Power zone settings written")
        return True
    except Exception as e:
        log.error("write_powerzone_to_file failed — %s", e)
        return False


def write_zone_to_file(data_string: str) -> bool:
    numbers = _parse_numbers(data_string)
    if numbers is None:
        return False
    try:
        with open(ZONE_FILE, "w") as f:
            for x in range(ZONE_ROWS):
                i = x * COLS_PER_ROW
                f.write(f"{numbers[i]} {numbers[i+1]} {numbers[i+2]}\n")
        log.info("Zone settings written")
        return True
    except Exception as e:
        log.error("write_zone_to_file failed — %s", e)
        return False


def write_brand_to_file(brand_name: str) -> bool:
    try:
        with open(BRAND_FILE, "w") as f:
            f.write(brand_name)
        log.info("Brand name written: %s", brand_name)
        return True
    except Exception as e:
        log.error("write_brand_to_file failed — %s", e)
        return False


def write_branch_to_file(branch_name: str) -> bool:
    try:
        with open(BRANCH_FILE, "w") as f:
            f.write(branch_name)
        log.info("Branch name written: %s", branch_name)
        return True
    except Exception as e:
        log.error("write_branch_to_file failed — %s", e)
        return False


# ─────────────────────────────────────────────────────────────────
# DB UPDATE FUNCTIONS
# ─────────────────────────────────────────────────────────────────
def update_config_table(modem_param: dict) -> bool:
    """
    BUG-06 FIX: original had no try/finally — conn leaked on exception.
    CODE-02 FIX: get_connection() replaces bare sqlite3.connect().
    """
    conn = get_connection(DB_MODEM_CONFIG)
    try:
        conn.execute("""
            UPDATE modem_parameters
            SET access_token=?, client_id=?, user_name=?,
                password=?, gsm_modem_mode=?, network_type=?, device_name=?
            WHERE rowid=1
        """, (
            modem_param.get("access_token", ""),
            modem_param.get("client_id", ""),
            modem_param.get("user_name", ""),
            modem_param.get("password", ""),
            modem_param.get("gsm_modem_mode", ""),
            modem_param.get("network_type", ""),
            modem_param.get("device_name", ""),
        ))
        conn.commit()
        log.info("Modem config updated")
        return True
    except Exception as e:
        conn.rollback()
        log.error("update_config_table failed — %s", e)
        return False
    finally:
        conn.close()


def update_from_telemetry(telemetry: list) -> bool:
    """
    Upsert devices into device_config.db from ThingsBoard payload.

    SEC-04 FIX: passwords received from ThingsBoard stored encrypted —
    consistent with device_parameters_module.py which encrypts on write.
    """
    conn = get_connection(DB_DEVICE_CONFIG)
    try:
        for device in telemetry:
            device_id   = device["id"]
            device_type = device["device_type"]
            ip_address  = device["ip_address"]
            username    = device["username"]
            password    = encrypt_value(device["password"])  # SEC-04 FIX
            port        = device["port"]
            camera_ip   = json.dumps(device["camera_ip"]) \
                          if isinstance(device.get("camera_ip"), list) else None

            result = conn.execute("""
                UPDATE device_parameters
                SET device_type=?, ip_address=?, username=?,
                    password=?, port=?, camera_ip=?
                WHERE id=?
            """, (device_type, ip_address, username,
                  password, port, camera_ip, device_id))

            if result.rowcount == 0:
                conn.execute("""
                    INSERT INTO device_parameters
                        (id, device_type, ip_address, username,
                         password, port, camera_ip)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (device_id, device_type, ip_address,
                      username, password, port, camera_ip))

        conn.commit()
        log.info("Telemetry synced into device_config.db (%d devices)",
                 len(telemetry))
        return True
    except Exception as e:
        conn.rollback()
        log.error("update_from_telemetry failed — %s", e)
        return False
    finally:
        conn.close()


def update_active_device_table(active_param: dict) -> bool:
    conn = get_connection(DB_LOGICAL_PARAMS)
    try:
        for key, value in active_param.items():
            conn.execute(
                "UPDATE parameters SET value = ? WHERE name = ?",
                (value, key)
            )
        conn.commit()
        log.info("Active device parameters updated")
        return True
    except Exception as e:
        conn.rollback()
        log.error("update_active_device_table failed — %s", e)
        return False
    finally:
        conn.close()


def update_network_config(network_param: dict) -> bool:
    conn = get_connection(DB_NETWORK_SETTINGS)
    try:
        for key, value in network_param.items():
            conn.execute(
                "UPDATE Settings SET setting_value = ? WHERE setting_name = ?",
                (value, key)
            )
        conn.commit()
        log.info("Network parameters updated")
        return True
    except Exception as e:
        conn.rollback()
        log.error("update_network_config failed — %s", e)
        return False
    finally:
        conn.close()


def set_rtc_from_timestamp(timestamp: str) -> bool:
    """
    BUG-05 FIX: original had no try/except. An I2C failure or malformed
    timestamp raised inside on_message, killed the callback, and left
    all subsequent config sections unapplied with no log entry.
    """
    try:
        if timestamp.endswith("Z"):
            timestamp = timestamp[:-1]
        dt  = datetime.datetime.fromisoformat(timestamp)
        rtc = SDL_DS1307()
        rtc.write_all(
            seconds=dt.second, minutes=dt.minute, hours=dt.hour,
            day=dt.isoweekday(), date=dt.day,
            month=dt.month, year=dt.year % 100,
            save_as_24h=True
        )
        rtc.write_now()
        log.info("RTC updated to %s", timestamp)
        return True
    except Exception as e:
        log.error("set_rtc_from_timestamp failed — %s", e)
        return False


# ─────────────────────────────────────────────────────────────────
# MAIN — FETCH AND APPLY CONFIG
# ─────────────────────────────────────────────────────────────────
def fetch_and_update_dexter_config() -> bool:
    """
    Connect to ThingsBoard using credentials from modem_config.db,
    request the dexter_config shared attribute, and apply each section.

    SEC-07 FIX: TLS port 8883.
    BUG-03 FIX: loop_start() + threading.Event — not loop_forever().
    Credentials: client_id, user_name, password from modem_config.db.
    """
    MQTT_CLIENT_ID = str(_get_modem_parameter("client_id") or "")
    MQTT_USERNAME  = str(_get_modem_parameter("user_name") or "")
    MQTT_PASSWORD  = str(_get_modem_parameter("password") or "")

    if not MQTT_CLIENT_ID or not MQTT_USERNAME:
        log.error("fetch_and_update_dexter_config: missing MQTT credentials in modem_config.db")
        return False

    done = threading.Event()

    def on_connect(client, userdata, flags: dict, rc: int, props=None) -> None:  # type: ignore[override]
        if rc == 0:
            client.subscribe("v1/devices/me/attributes/response/+")
            client.publish(
                "v1/devices/me/attributes/request/1",
                '{"sharedKeys":"dexter_config"}',
                qos=1
            )
            log.info("updatecode: connected, config request sent")
        else:
            log.error("updatecode: broker rejected connection rc=%s", rc)
            done.set()

    def on_message(client, userdata, msg) -> None:  # type: ignore[override]
        try:
            data = json.loads(msg.payload.decode())
            if "shared" not in data:
                log.warning("updatecode: response has no 'shared' key")
                return

            raw = data["shared"].get("dexter_config", "{}")
            cfg = json.loads(raw) if isinstance(raw, str) else raw

            if cfg.get("powerzone"):
                write_powerzone_to_file(cfg["powerzone"])
            if cfg.get("zone"):
                write_zone_to_file(cfg["zone"])
            if cfg.get("brand"):
                write_brand_to_file(cfg["brand"])
            if cfg.get("branch"):
                write_branch_to_file(cfg["branch"])
            if cfg.get("integration"):
                update_from_telemetry(cfg["integration"])
            if cfg.get("modem_parameter"):
                update_config_table(cfg["modem_parameter"])
            if cfg.get("active_device_parameter"):
                update_active_device_table(cfg["active_device_parameter"])
            if cfg.get("network_parameter"):
                update_network_config(cfg["network_parameter"])
            if cfg.get("timestamp"):
                set_rtc_from_timestamp(cfg["timestamp"])

        except Exception as e:
            log.error("updatecode: on_message error — %s", e)
        finally:
            client.disconnect()
            done.set()

    # SEC-07 FIX: TLS context
    ctx = ssl.create_default_context()
    ctx.check_hostname  = True
    ctx.verify_mode     = ssl.CERT_REQUIRED
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2

    client = mqtt.Client(
        client_id=MQTT_CLIENT_ID,
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        clean_session=True
    )
    client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
    client.tls_set_context(ctx)
    client.on_connect = on_connect
    client.on_message = on_message

    try:
        client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
        client.loop_start()
        if not done.wait(timeout=MQTT_CONNECT_TIMEOUT):
            log.error("updatecode: no response within %ds", MQTT_CONNECT_TIMEOUT)
            return False
        return True
    except Exception as e:
        log.error("updatecode: connection failed — %s", e)
        return False
    finally:
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    import sys
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s"
    )
    sys.exit(0 if fetch_and_update_dexter_config() else 1)