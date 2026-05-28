# cavlidata.py
# Dexter HMS — Cavli Modem Connectivity Heartbeat
# Sends a 'cavlidata_ontime' telemetry timestamp to ThingsBoard
# to confirm the Cavli modem/eSIM link is alive.
#
# Changes from previous version:
#   CAV-FIX-1: Wrong MQTT auth type — module used ACCESS_TOKEN auth
#              (client.username_pw_set(username=access_token)) but this device
#              is provisioned with MQTT_BASIC (clientId + userName + password).
#              access_token is empty in modem_config.db by design — not needed
#              for MQTT_BASIC. Fixed: read client_id, user_name, password from
#              DB (already Fernet-encrypted there) and use MQTT_BASIC auth.
#   CAV-FIX-2: Wrong MQTT broker host — read 'swatch_mqtt_host' column which
#              does not exist in modem_config.db, fell back to .env MQTT_BROKER
#              (not set), then hardcoded 'mqtt.thingsboard.cloud' (wrong host).
#              Fixed: use 'thingsboard.cloud' directly (same host as all other
#              modules). The swatch_host column is the admin REST host, not the
#              MQTT broker — they are the same domain here.
#   CAV-FIX-3: Inline _read_modem_field() had no column whitelist and no
#              Fernet decryption. Replaced with _get_modem_cred() which
#              validates against whitelist and decrypts credential fields.
#   CAV-FIX-4: _get_modem_parameter() was defined but never called — dead code.
#              Removed. All DB access now via _get_modem_cred().
#   CAV-FIX-5: Misleading comment said "credentials from secrets_manager" but
#              code read from DB. Comment corrected.
#
# Prior fixes retained (BUG-02..04, SEC-07, CODE-01..03, ERR-01)

import ssl
import json
import time
import logging
import threading
from datetime import datetime

import paho.mqtt.client as mqtt

from db_connection import get_connection, DB_MODEM_CONFIG
from secrets_manager import decrypt_value, get_secret

log   = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────────────────────────
_PUBLISH_TIMEOUT  = 10    # max seconds to wait for publish confirm
_CONNECT_RETRIES  = 3     # attempts before giving up
_CONNECT_DELAY    = 5     # seconds between retries

# CAV-FIX-2: correct MQTT broker host — same as all other modules
THINGSBOARD_HOST = "www.dexterhms.com"

# CAV-FIX-3: whitelist covers credential fields needed for MQTT_BASIC auth
# and non-credential fields. Fernet decryption applied to credential fields.
_ALLOWED_MODEM_PARAMS    = {"client_id", "user_name", "password", "device_name", "network_type"}
_MODEM_CREDENTIAL_FIELDS = {"client_id", "user_name", "password"}


# ─────────────────────────────────────────────────────────────────
# MODEM CONFIG READER
# ─────────────────────────────────────────────────────────────────
def _get_modem_cred(param: str) -> str:
    """
    Read one field from modem_parameters and decrypt if it is a
    credential field (client_id, user_name, password).

    CAV-FIX-3: replaces the old inline _read_modem_field() which had
    no whitelist and no Fernet decryption, and the dead _get_modem_parameter()
    which had a whitelist but was never called.

    Returns empty string if the column is missing, the row is missing,
    or decryption fails — never raises.
    """
    if param not in _ALLOWED_MODEM_PARAMS:
        log.error("_get_modem_cred: '%s' not in allowed list", param)
        return ""

    conn = get_connection(DB_MODEM_CONFIG)
    try:
        row = conn.execute(
            f"SELECT {param} FROM modem_parameters WHERE id = 1"
        ).fetchone()
        raw = (row[0] or "").strip() if row else ""
    except Exception as e:
        log.warning("cavlidata: DB read failed for %s: %s", param, e)
        return ""
    finally:
        conn.close()

    if not raw:
        return ""

    # CAV-FIX-3: decrypt credential fields — they are Fernet-encrypted at rest
    if param in _MODEM_CREDENTIAL_FIELDS:
        try:
            return decrypt_value(raw)
        except Exception:
            return raw   # plaintext fallback (pre-encryption legacy row)

    return raw


# ─────────────────────────────────────────────────────────────────
# CAVLI STATUS HEARTBEAT
# ─────────────────────────────────────────────────────────────────
def send_cavlidata_status() -> None:
    """
    Publish a 'cavlidata_ontime' timestamp to ThingsBoard to confirm
    the Cavli eSIM modem is online and routing traffic.

    CAV-FIX-1: uses MQTT_BASIC auth (client_id + user_name + password)
    read from modem_config.db. The original used ACCESS_TOKEN auth
    (access_token field) which is empty — device uses MQTT_BASIC.

    CAV-FIX-2: broker host is thingsboard.cloud. Original tried to read
    non-existent 'swatch_mqtt_host' column → fell back to wrong host.

    SEC-07 FIX: TLS on port 8883 retained.
    BUG-02 FIX: wait_for_publish() retained.
    BUG-03 FIX: loop_stop/disconnect in finally retained.
    BUG-04 FIX: connect retry loop retained.
    """
    # Gate on network_type — this module is GSM/Cavli only.
    # The correct decision source is the network_type field in modem_config.db,
    # not whether credential fields happen to be blank.
    network_type = _get_modem_cred("network_type")
    if network_type != "gsm":
        log.info(
            "cavlidata: network_type is '%s' — skipping heartbeat (GSM only)",
            network_type
        )
        return

    # CAV-FIX-1: read MQTT_BASIC credentials from DB (Fernet-decrypted)
    # Fallback to .env if DB fields are empty (Docker / fresh device)
    client_id = _get_modem_cred("client_id")
    user_name = _get_modem_cred("user_name")
    password  = _get_modem_cred("password")

    if not client_id:
        try:
            client_id = get_secret("MQTT_CLIENT_ID")
            log.info("cavlidata: client_id loaded from .env fallback")
        except (KeyError, RuntimeError):
            pass

    if not user_name:
        try:
            user_name = get_secret("MQTT_USER_NAME")
            log.info("cavlidata: user_name loaded from .env fallback")
        except (KeyError, RuntimeError):
            pass

    if not password:
        try:
            password = get_secret("MQTT_PASSWORD")
            log.info("cavlidata: password loaded from .env fallback")
        except (KeyError, RuntimeError):
            pass

    if not user_name or not password:
        log.warning(
            "cavlidata: user_name/password not set in DB or .env — "
            "run Device Provisioning or set MQTT_USER_NAME/MQTT_PASSWORD in .env"
        )
        return

    timestamp = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    payload   = json.dumps({"cavlidata_ontime": timestamp})

    # SEC-07 FIX: TLS context — CERT_REQUIRED, TLS 1.2 minimum
    ctx = ssl.create_default_context()
    ctx.check_hostname  = True
    ctx.verify_mode     = ssl.CERT_REQUIRED
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2

    # CAV-FIX-1: MQTT_BASIC — client_id in Client(), user_name+password in username_pw_set()
    client = mqtt.Client(
        client_id=client_id or "cavlidata_heartbeat",
        clean_session=True,
        protocol=mqtt.MQTTv311,
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2
    )
    client.username_pw_set(username=user_name, password=password)
    client.tls_set_context(ctx)

    # BUG-03 FIX: always clean up client regardless of what fails below
    try:
        # BUG-04 FIX: retry connect on transient failures
        connected = False
        for attempt in range(1, _CONNECT_RETRIES + 1):
            try:
                # CAV-FIX-2 + SEC-07: correct host, TLS port 8883
                client.connect(THINGSBOARD_HOST, 8883, keepalive=60)
                client.loop_start()
                connected = True
                log.info("cavlidata: connected to %s:8883 (attempt %d)",
                         THINGSBOARD_HOST, attempt)
                break
            except Exception as e:
                log.warning(
                    "cavlidata: connect attempt %d/%d failed — %s",
                    attempt, _CONNECT_RETRIES, e
                )
                if attempt < _CONNECT_RETRIES:
                    time.sleep(_CONNECT_DELAY)

        if not connected:
            raise RuntimeError(
                f"cavlidata: could not connect after {_CONNECT_RETRIES} attempts"
            )

        # BUG-02 FIX: wait for publish ACK instead of fixed sleep(2)
        msg_info = client.publish(
            "v1/devices/me/telemetry", payload, qos=1
        )
        msg_info.wait_for_publish(timeout=_PUBLISH_TIMEOUT)

        if msg_info.is_published():
            log.info("cavlidata: telemetry sent — %s", payload)
        else:
            log.warning("cavlidata: publish not confirmed within %ds",
                        _PUBLISH_TIMEOUT)

    finally:
        # BUG-03 FIX: always stop loop and disconnect
        try:
            client.loop_stop()
            client.disconnect()
        except Exception as exc:
            log.debug("[cavlidata] MQTT cleanup error (non-critical): %s", exc)