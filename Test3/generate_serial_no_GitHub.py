"""
generate_serial_no_GitHub.py
Dexter HMS — Device serial number generator and ThingsBoard publisher.

Reads panel_number and batch_number from securelink.db (set via autorun4.py
menu option 14), generates the device serial number, and publishes it once
to ThingsBoard telemetry.

GitHub pull removed — panel/batch are now entered locally via autorun4.py.
Called once from autorun4.py after the user saves panel/batch via the menu.
"""

import sys
import datetime
import sqlite3
import logging
import ssl
import json
import threading
import paho.mqtt.client as mqtt

log = logging.getLogger(__name__)

SECURELINK_DB    = "/home/pi/Test3/securelink.db"
MODEM_DB         = "/home/pi/Test3/modem_config.db"
THINGSBOARD_HOST = "mqtt.thingsboard.cloud"
MQTT_PORT        = 8883
PUBLISH_TIMEOUT  = 15


def _read_modem(col: str) -> str:
    try:
        conn = sqlite3.connect(MODEM_DB)
        row = conn.execute(
            f"SELECT {col} FROM modem_parameters WHERE id=1"
        ).fetchone()
        conn.close()
        return (row[0] or "").strip() if row else ""
    except Exception as e:
        log.warning("generate_serial: DB read failed for %s: %s", col, e)
        return ""


def _dec(val: str) -> str:
    if not val:
        return val
    try:
        sys.path.insert(0, "/home/pi/Test3")
        from secrets_manager import decrypt_value
        return decrypt_value(val)
    except Exception:
        return val


def _get_panel_batch() -> tuple:
    try:
        conn = sqlite3.connect(SECURELINK_DB)
        row = conn.execute(
            "SELECT panel_number, batch_number FROM device_info LIMIT 1"
        ).fetchone()
        conn.close()
        if row and row[0] and row[1]:
            return str(row[0]), str(row[1])
    except Exception as e:
        log.warning("generate_serial: securelink.db read failed: %s", e)
    return "XX", "BNXXX"


def _get_rpi_model() -> str:
    try:
        with open('/proc/device-tree/model') as f:
            m = f.read()
        if 'Raspberry Pi 4' in m:
            return 'R4'
        if 'Raspberry Pi 5' in m:
            return 'R5'
        if 'Raspberry Pi 3' in m:
            return 'R3'
    except Exception:
        pass
    return 'R?'


def generate_serial() -> str:
    year   = datetime.datetime.now().year
    prefix = f"SL{str(year)[-2:]}"
    rpi    = _get_rpi_model()
    pyv    = f"P{sys.version_info.major}"
    panel, batch = _get_panel_batch()
    return f"{prefix}{rpi}{pyv}{panel}{batch}"


def send_serial_to_tb(serial: str) -> bool:
    """Publish serial number once to ThingsBoard telemetry. Returns True on success."""
    client_id = _dec(_read_modem("client_id"))
    user_name = _dec(_read_modem("user_name"))
    password  = _dec(_read_modem("password"))

    if not client_id or not user_name:
        log.error("generate_serial: MQTT credentials not set in modem_config.db")
        return False

    published = threading.Event()
    success   = [False]

    def on_connect(client, userdata, flags, rc):
        if rc == 0:
            result = client.publish(
                "v1/devices/me/telemetry",
                json.dumps({"serial_number": serial}),
                qos=1
            )
            if result.rc != mqtt.MQTT_ERR_SUCCESS:
                log.error("generate_serial: publish call failed — rc=%s", result.rc)
                published.set()
        else:
            log.error("generate_serial: MQTT connect rejected — rc=%s", rc)
            published.set()

    def on_publish(client, userdata, mid):
        log.info("generate_serial: serial_number published — mid=%s", mid)
        success[0] = True
        published.set()

    ctx = ssl.create_default_context()
    ctx.check_hostname  = True
    ctx.verify_mode     = ssl.CERT_REQUIRED
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2

    client = mqtt.Client(
        client_id=client_id,
        callback_api_version=mqtt.CallbackAPIVersion.VERSION1,
    )
    client.username_pw_set(user_name, password=password)
    client.tls_set_context(ctx)
    client.on_connect = on_connect
    client.on_publish = on_publish

    try:
        client.connect(THINGSBOARD_HOST, MQTT_PORT, keepalive=60)
        client.loop_start()
        published.wait(timeout=PUBLISH_TIMEOUT)
    except Exception as e:
        log.error("generate_serial: connection error — %s", e)
    finally:
        client.loop_stop()
        client.disconnect()

    return success[0]


def run_once() -> bool:
    """
    Generate serial from securelink.db and publish to ThingsBoard once.
    Called from autorun4.py after panel/batch are saved via menu option 14.
    Returns True if published successfully.
    """
    panel, batch = _get_panel_batch()
    if panel == "XX" and batch == "BNXXX":
        log.error(
            "generate_serial: panel_number/batch_number not set in securelink.db — "
            "use autorun4.py menu option 14 to set them first."
        )
        return False

    serial = generate_serial()
    log.info("generate_serial: serial = %s", serial)
    ok = send_serial_to_tb(serial)
    if ok:
        log.info("generate_serial: published to ThingsBoard — done.")
    else:
        log.error("generate_serial: failed to publish to ThingsBoard.")
    return ok


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s"
    )
    result = run_once()
    print("Serial published to TB:", result)
    sys.exit(0 if result else 1)
