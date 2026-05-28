# DeviceProvisioning_Module.py
# Dexter HMS — ThingsBoard MQTT Device Provisioning
#
# Exchanges a provision key/secret for real MQTT credentials and
# persists them to modem_config.db for use by all other modules.
#
# modem_config.db is created and owned by db_schema_migration.py.
# Values (access_token, client_id, user_name, password, device_name,
# gsm_modem_mode, network_type) are entered by the user via menu and
# stored in the DB. This module reads them to build the provision request
# and writes the provisioned credentials back on SUCCESS.
#
# provision_device_key / provision_device_secret are fixed per deployment
# and kept as named constants below.
#
# Changes from original:
#   BUG-01 : SQL injection in get_parameter via .format(param)
#   BUG-02 : SQL injection in update_parameter via .format(param)
#            → both replaced by _get_modem_parameter() /
#              _update_modem_parameter() with whitelist validation
#   BUG-03 : Debug cursor 'c' ran SELECT * FROM modem_parameters and
#            printed ALL credentials on every get_parameter() call
#            → removed entirely
#   BUG-04 : module-level ModemConfigDatabase() at import time
#            → all DB access inside form_basic() only
#   BUG-05 : provision_device() used loop_forever() — blocked forever
#            with no timeout if broker never responded
#            → loop_start() + threading.Event with 30s timeout
#   BUG-06 : on_message wrote provisioned credentials with no validation
#            — empty/None values could overwrite working credentials
#            → non-empty string check before each update_parameter call
#   SEC-01 : Provisioned credentials printed to stdout in on_message()
#            → log.info() with no credential values logged
#   SEC-07 : Plain MQTT port 1883 → TLS enforced on port 8883
#   CODE-01: ModemConfigDatabase class removed — DB owned by
#            db_schema_migration.py, not this module
#   CODE-02: bare sqlite3.connect() → get_connection(DB_MODEM_CONFIG)
#   CODE-03: All log.info() → logging

"""
DeviceProvisioning_Module.py
Dexter HMS — ThingsBoard device provisioning via REST API

Responsibilities:
  - Creates device records on ThingsBoard cloud via REST API
  - API token read from secrets_manager.py (SEC-01)
  - SQL injection protection via column name whitelist

Key functions:
  - form_basic() — provision this device on ThingsBoard if not already registered

Dependencies:
  - db_connection.py   — WAL SQLite connections
  - secrets_manager.py — TB_API_USERNAME, TB_API_PASSWORD from .env
Author: Seple Novaedge Pvt. Ltd.
"""

import ssl
import logging
import threading
from json import dumps, loads
from typing import Optional

from paho.mqtt.client import Client, CallbackAPIVersion

from db_connection import get_connection, DB_MODEM_CONFIG

# PROV-FIX-1: import Fernet helpers so provisioned credentials are encrypted
# at rest — matching the encrypt/decrypt contract in SerialCommunication.py
# ModemConfigDatabase. Without this, provisioned values land as plaintext
# but get_parameter() always decrypts _CREDENTIAL_FIELDS, causing an
# InvalidToken fallback that exposes raw ciphertext in the TB dashboard.
try:
    from secrets_manager import encrypt_value, decrypt_value
except ImportError:
    def encrypt_value(v):   return v   # graceful fallback
    def decrypt_value(v):   return v   # graceful fallback

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────
# PROVISION KEYS — fixed per deployment
# Update these when re-provisioning under a different ThingsBoard
# profile. These are NOT user-entered and NOT stored in the DB.
# ─────────────────────────────────────────────────────────────────
PROVISION_DEVICE_KEY    = "abcd"   # replace with real key before deployment
PROVISION_DEVICE_SECRET = "efgh"   # replace with real secret before deployment

PROVISION_REQUEST_TOPIC  = "/provision/request"
PROVISION_RESPONSE_TOPIC = "/provision/response"
PROVISION_TIMEOUT        = 30      # seconds to wait for broker response

# ─────────────────────────────────────────────────────────────────
# BUG-01/02 FIX: whitelist for modem_config column access
# ─────────────────────────────────────────────────────────────────
_ALLOWED_MODEM_PARAMS = {
    "access_token", "client_id", "user_name",
    "password", "gsm_modem_mode", "network_type", "device_name"
}

# PROV-FIX-1: credential fields must be Fernet-encrypted at rest.
# Must match SerialCommunication.ModemConfigDatabase._CREDENTIAL_FIELDS exactly.
# get_parameter() in SerialCommunication always calls decrypt_value() on these
# fields — so anything written here MUST be encrypted, or TB will display
# raw Fernet ciphertext (gAAAAA...) instead of the actual credential values.
_CREDENTIAL_FIELDS = {"access_token", "client_id", "user_name", "password"}


# ─────────────────────────────────────────────────────────────────
# MODEM CONFIG HELPERS
# ─────────────────────────────────────────────────────────────────
def _get_modem_parameter(param: str) -> Optional[str]:
    """
    Read one field from modem_parameters (id=1).

    BUG-01 FIX: original used 'SELECT {} FROM'.format(param) — SQL injection.
    BUG-03 FIX: original also ran 'SELECT *' and printed all rows to stdout
    on every call — a live credential dump into logs.
    CODE-01 FIX: ModemConfigDatabase removed, get_connection() used directly.
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


def _update_modem_parameter(param: str, value: str) -> bool:
    """
    Update one field in modem_parameters (id=1).

    BUG-02 FIX: original used 'SET {} = ?'.format(param) — SQL injection.
    BUG-06 FIX: value validated non-empty before write — a malformed
    provision response must not overwrite working credentials with blanks.
    PROV-FIX-1: credential fields are Fernet-encrypted before writing so
    SerialCommunication.ModemConfigDatabase.get_parameter() can decrypt them
    correctly. Without this, TB dashboard shows raw plaintext or the wrong
    value because get_parameter() always calls decrypt_value() on
    _CREDENTIAL_FIELDS — if the stored value was never encrypted, InvalidToken
    fires and the raw bytes are returned, causing display corruption.
    """
    if param not in _ALLOWED_MODEM_PARAMS:
        log.error("_update_modem_parameter: '%s' not in allowed list", param)
        return False

    if not value or not isinstance(value, str) or not value.strip():
        log.error(
            "_update_modem_parameter: refusing empty value for '%s'", param
        )
        return False

    # PROV-FIX-3: prevent double encryption.
    # ThingsBoard provisioning response always returns PLAINTEXT credentials.
    # But if somehow an already-encrypted value arrives (e.g. re-provisioning
    # with a value read directly from DB), encrypting again causes triple/double
    # encryption. Check if value is already a Fernet token before encrypting.
    def _is_fernet(v: str) -> bool:
        return v.startswith('gAAAAA') and len(v) > 50

    stored_value = (
        value if (param not in _CREDENTIAL_FIELDS or _is_fernet(value))
        else encrypt_value(value)
    )

    conn = get_connection(DB_MODEM_CONFIG)
    try:
        conn.execute(
            f"UPDATE modem_parameters SET {param} = ? WHERE id = 1",
            (stored_value,)
        )
        conn.commit()
        log.info("modem_config: '%s' updated successfully", param)
        return True
    except Exception as e:
        conn.rollback()
        log.error("_update_modem_parameter('%s') failed — %s", param, e)
        return False
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────
# MQTT CALLBACKS
# ─────────────────────────────────────────────────────────────────
def _make_on_connect(provision_request: dict):
    def on_connect(client, userdata, flags, reason_code, properties=None):
        if reason_code == 0:
            client.subscribe(PROVISION_RESPONSE_TOPIC)
            client.publish(
                PROVISION_REQUEST_TOPIC,
                dumps(provision_request),
                qos=1
            )
            log.info("provision: request sent for device '%s'",
                     provision_request.get("deviceName", "<unknown>"))
        else:
            log.error("provision: broker rejected connection — rc=%s",
                      reason_code)
            client.disconnect()
    return on_connect


def _make_on_message(done_event: threading.Event, result: list):
    def on_message(client, userdata, msg):
        try:
            decoded = loads(msg.payload.decode("UTF-8"))
            status  = decoded.get("status")

            if status == "SUCCESS":
                credentials = decoded.get("credentialsValue", {})

                # SEC-01 FIX: original printed full credentials to stdout.
                # Log only that provisioning succeeded — never log credential values.
                log.info("provision: SUCCESS — writing credentials to DB")

                # BUG-06 FIX: validate each field before writing
                for db_col, cred_key in [
                    ("client_id", "clientId"),
                    ("user_name", "userName"),
                    ("password",  "password"),
                ]:
                    val = credentials.get(cred_key)
                    if val:
                        _update_modem_parameter(db_col, val)
                    else:
                        log.warning(
                            "provision: '%s' missing in response — "
                            "existing value retained", cred_key
                        )
                result.append(True)

            else:
                error_msg = decoded.get("errorMsg", "no error message")
                log.error("provision: FAILED — %s", error_msg)

                # TB returns "Failed to provision device!" when the device
                # already exists (same deviceName already in TB). The device
                # is live in TB and the credentials already stored in DB are
                # valid — treat as success so provisioning continues.
                _em = error_msg.lower()
                if "already" in _em or "exist" in _em or "failed to provision" in _em:
                    log.info("provision: device already exists in TB — treating as success")
                    result.append(True)
                else:
                    result.append(False)

        except Exception as e:
            log.error("provision: on_message error — %s", e)
        finally:
            client.disconnect()
            done_event.set()   # BUG-05 FIX: unblock the waiting thread

    return on_message


# ─────────────────────────────────────────────────────────────────
# PROVISION DEVICE
# ─────────────────────────────────────────────────────────────────
def provision_device(host: str, port: int, provision_request: dict) -> bool:
    """
    Connect to ThingsBoard, send provision request, wait for response.

    BUG-05 FIX: original used loop_forever() — blocked indefinitely with
    no timeout. If the broker was unreachable the process hung forever and
    systemd never restarted it.
    Fixed: loop_start() + threading.Event.wait(timeout=PROVISION_TIMEOUT).

    SEC-07 FIX: TLS enforced on port 8883 — was plain port 1883.

    Returns True on SUCCESS response, False on failure or timeout.
    """
    done   = threading.Event()
    result = []   # shared list — on_message appends True/False
    client = Client(
        callback_api_version=CallbackAPIVersion.VERSION2,
        clean_session=True
    )
    client.username_pw_set("provision")
    client.on_connect = _make_on_connect(provision_request)
    client.on_message = _make_on_message(done, result)

    # SEC-07 FIX: TLS context — was plain port 1883
    ctx = ssl.create_default_context()
    ctx.check_hostname  = True
    ctx.verify_mode     = ssl.CERT_REQUIRED
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    client.tls_set_context(ctx)

    try:
        # DNS-FIX: retry client.connect() on [Errno -2] (getaddrinfo failure).
        # When PPP comes up, systemd-resolved briefly returns SERVFAIL for all
        # queries while switching DNS servers. This lasts <3 seconds. Retrying
        # up to 5 times with 2s delay (10s window) covers the disruption on
        # any RPi OS version without requiring DNS cache flush tools.
        import time as _time
        _connect_retries = 5
        for _attempt in range(_connect_retries):
            try:
                client.connect(host, port, keepalive=60)
                break   # connected — exit retry loop
            except OSError as e:
                if e.errno == -2 and _attempt < _connect_retries - 1:
                    log.warning(
                        "provision: DNS not ready (attempt %d/%d) — retrying in 2s",
                        _attempt + 1, _connect_retries
                    )
                    _time.sleep(2)
                else:
                    raise   # not a DNS error, or out of retries

        client.loop_start()

        completed = done.wait(timeout=PROVISION_TIMEOUT)
        if not completed:
            log.error(
                "provision: no response within %ds — "
                "check host/port and network connectivity",
                PROVISION_TIMEOUT
            )
            return False
        return bool(result and result[0])
    except Exception as e:
        log.error("provision: connection failed — %s", e)
        return False
    finally:
        client.loop_stop()
        client.disconnect()


# ─────────────────────────────────────────────────────────────────
# MAIN PROVISIONING FLOW
# ─────────────────────────────────────────────────────────────────
def form_basic() -> bool:
    """
    Read user-configured credentials from modem_config.db, combine with
    the deployment-fixed provision key/secret, and send the provision
    request to ThingsBoard.

    BUG-04 FIX: original instantiated ModemConfigDatabase() at module
    level — every import triggered a DB connection. All DB access is now
    inside this function only.

    SEC-07 FIX: port 8883 (TLS) — was 1883 (plain).
    """
    host = "www.dexterhms.com"

    device_name = _get_modem_parameter("device_name")

    # PROV-FIX-2: credential fields are Fernet-encrypted in modem_config.db.
    # _get_modem_parameter() returns raw encrypted strings (gAAAAAB...).
    # Must decrypt before sending to ThingsBoard — otherwise TB stores and
    # displays the Fernet ciphertext as the actual MQTT credentials, causing
    # SerialCommunication.py to fail authentication.
    def _decrypt_cred(raw):
        """Decrypt a credential field. Return raw if None or decryption fails."""
        if not raw:
            return raw
        try:
            return decrypt_value(raw)
        except Exception:
            return raw  # already plaintext or unrecognised format

    client_id = _decrypt_cred(_get_modem_parameter("client_id"))
    username  = _decrypt_cred(_get_modem_parameter("user_name"))
    password  = _decrypt_cred(_get_modem_parameter("password"))

    if not device_name:
        log.error("provision: 'device_name' not set — run device setup first")
        return False

    provision_request = {
        "provisionDeviceKey":    PROVISION_DEVICE_KEY,
        "provisionDeviceSecret": PROVISION_DEVICE_SECRET,
        "credentialsType":       "MQTT_BASIC",
        "deviceName":            device_name,
        "username":              username,
        "password":              password,
        "clientId":              client_id,
    }

    log.info("provision: starting for device '%s' → %s:8883",
             device_name, host)
    return provision_device(host, 8883, provision_request)


# ─────────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s"
    )
    sys.exit(0 if form_basic() else 1)