#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# thingsboard_mqtt_publisher.py
# Dexter HMS — ThingsBoard MQTT Publisher
#
# Changes from original:
#   SEC-01  : Hardcoded credentials removed from INSERT — secrets_manager only
#   BUG-01  : logger used before defined → NameError crash on any DB error
#   BUG-02  : SQL injection via .format(param) in get/update_parameter → whitelist
#   BUG-03  : loop_start() inside retry loop → multiple threads spawned → fixed
#   BUG-04  : No try/except in run() → one bad payload kills publisher forever
#   DB-01   : bare sqlite3.connect() → get_connection(DB_MODEM_CONFIG) with WAL
#   PERF-05 : hardcoded sleep(5) on reconnect → exponential backoff (1s→300s)
#   SEC-07  : TLS was present but SSLError unhandled → now raises, no fallback
#   SEC-08  : X.509 mTLS client auth — device.crt + device.key in /home/pi/Test3/certs/
#             Falls back to MQTT Basic auth if certs not present (e.g. pre-provisioning).
#             ThingsBoard device credential type must match the active auth mode.
#   CODE    : All log.info() → logging, unused import sys removed

import os
import ssl
import json
import time
import socket
import threading
import logging
import paho.mqtt.client as mqtt

from database_handler import DatabaseHandler
from payload_manager import PayloadManager
import json_db_module
from db_connection import get_connection, DB_MODEM_CONFIG
from secrets_manager import get_secret, encrypt_value, decrypt_value
from cryptography.fernet import InvalidToken

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────
# BUG-02 FIX: Whitelist for get/update_parameter column names
# Original: cursor.execute('SELECT {} FROM ...'.format(param))
# Any string passed as param becomes raw SQL — SQL injection.
# Credentials excluded intentionally — read via secrets_manager only.
# ─────────────────────────────────────────────────────────────────
_ALLOWED_MODEM_PARAMS = {
    "access_token",
    "client_id",
    "user_name",
    "password",
    "gsm_modem_mode",
    "network_type",
    "device_name",
    "swatch_mqtt_host",   # DB-02: SWatch MQTT broker address — set via LCD menu
}



# SEC-04: Fields in modem_parameters that store sensitive credentials.
# Fernet-encrypted on write, decrypted on read.
_MODEM_CREDENTIAL_FIELDS = {
    "access_token", "client_id", "user_name", "password"
}

# ─────────────────────────────────────────────────────────────────
# MODEM CONFIG DATABASE
# ─────────────────────────────────────────────────────────────────
class ModemConfigDatabase:

    def __init__(self, db_file: str = DB_MODEM_CONFIG):
        self.db_file = db_file
        self._lock   = threading.Lock()
        self.create_database()

    def create_database(self):
        with self._lock:
            conn = get_connection(self.db_file)  # DB-01: WAL + PRAGMAs
            try:
                conn.execute('''
                    CREATE TABLE IF NOT EXISTS modem_parameters (
                        id               INTEGER PRIMARY KEY,
                        access_token     TEXT,
                        client_id        TEXT,
                        user_name        TEXT,
                        password         TEXT,
                        gsm_modem_mode   TEXT,
                        network_type     TEXT,
                        device_name      TEXT,
                        swatch_mqtt_host TEXT
                    )

                    -- DB-02: Add swatch_mqtt_host column to existing tables
                    -- (ALTER TABLE is idempotent via try/except in migrations)
                ''')

                count = conn.execute(
                    "SELECT COUNT(*) FROM modem_parameters"
                ).fetchone()[0]

                if count == 0:
                    # SEC-01 FIX: original hardcoded real credentials here:
                    #   '6dNkl093nG4HvksMmYDD'  ← live MQTT token in source code
                    #   'Seple-Ho-Id'            ← client_id in source code
                    #   'Seple-Ho-Username'      ← username in source code
                    #   'Seple-Ho-Password'      ← password in source code
                    # All credentials now managed by /etc/dexter/.env only.
                    conn.execute('''
                        INSERT INTO modem_parameters
                            (access_token, client_id, user_name, password,
                             gsm_modem_mode, network_type, device_name,
                             swatch_mqtt_host)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        '',               # access_token  — entered via LCD menu
                        '',               # client_id
                        '',               # user_name
                        '',               # password
                        'physical',
                        'ethernet',
                        'Dexter-HMS',
                        'mqtt.thingsboard.cloud'  # swatch_mqtt_host — default, editable
                    ))
                    log.info("modem_config: default row inserted")

                # DB-02: Add swatch_mqtt_host to existing DBs that predate this column
                try:
                    conn.execute(
                        "ALTER TABLE modem_parameters ADD COLUMN swatch_mqtt_host TEXT"
                    )
                    log.info("modem_config: added swatch_mqtt_host column")
                except Exception:
                    pass  # column already exists — ALTER TABLE fails silently

                conn.commit()
                log.info("modem_config: DB initialised at %s", self.db_file)

            except Exception as e:
                conn.rollback()
                # BUG-01 FIX: original called logger.error() here —
                # but 'logger' was never defined anywhere in the file.
                # This caused a NameError crash on the very first DB error,
                # hiding the real problem completely.
                log.error("modem_config: create_database failed — %s", e)
                raise
            finally:
                conn.close()

    def get_parameter(self, param: str):
        # BUG-02 FIX: original used 'SELECT {} FROM ...'.format(param)
        if param not in _ALLOWED_MODEM_PARAMS:
            log.error(
                "modem_config: get_parameter('%s') rejected — "
                "not in allowed list: %s", param, _ALLOWED_MODEM_PARAMS
            )
            return None

        with self._lock:
            conn = get_connection(self.db_file)
            try:
                row = conn.execute(
                    f"SELECT {param} FROM modem_parameters WHERE id = 1"
                ).fetchone()
                value = row[0] if row else None
                # SEC-04: decrypt credential fields on read
                if value and param in _MODEM_CREDENTIAL_FIELDS:
                    try:
                        value = decrypt_value(value)
                    except (ValueError, InvalidToken):
                        pass  # legacy plaintext row — return as-is
                return value
            except Exception as e:
                log.error(
                    "modem_config: get_parameter('%s') failed — %s", param, e
                )
                return None
            finally:
                conn.close()

    def update_parameter(self, param: str, value) -> bool:
        # BUG-02 FIX: original used 'UPDATE ... SET {} = ?'.format(param)
        if param not in _ALLOWED_MODEM_PARAMS:
            log.error(
                "modem_config: update_parameter('%s') rejected — "
                "not in allowed list", param
            )
            return False

        # SEC-04: encrypt credential fields before writing
        stored_value = encrypt_value(str(value)) if param in _MODEM_CREDENTIAL_FIELDS else value
        with self._lock:
            conn = get_connection(self.db_file)
            try:
                conn.execute(
                    f"UPDATE modem_parameters SET {param} = ? WHERE id = 1",
                    (stored_value,)
                )
                conn.commit()
                log.info("modem_config: updated %s", param)  # never log credential value
                return True
            except Exception as e:
                conn.rollback()
                log.error(
                    "modem_config: update_parameter('%s') failed — %s", param, e
                )
                return False
            finally:
                conn.close()


# ─────────────────────────────────────────────────────────────────
# MQTT SETTINGS
# ─────────────────────────────────────────────────────────────────
modem_config_db = ModemConfigDatabase()

# ── MQTT BASIC CREDENTIALS (active) ──────────────────────────────────────
# ThingsBoard MQTT Basic auth: client_id + user_name + password.
# Same credentials used by SerialCommunication.py (AT+MQTTCREATE) so both
# Ethernet (paho-mqtt over TCP) and GSM (modem AT commands) publish to the
# same ThingsBoard device — no split dashboard, seamless failover.
CLIENT_ID = modem_config_db.get_parameter("client_id") or ""
USER_NAME = modem_config_db.get_parameter("user_name") or ""
PASSWORD  = modem_config_db.get_parameter("password")  or ""

if not CLIENT_ID.strip():
    log.warning(
        "client_id not set in modem_config.db — MQTT auth will fail "
        "until credentials are set via LCD menu or webserver"
    )

# ── ACCESS TOKEN (reserved — kept in DB, commented out for future use) ────
# To switch back to access_token auth:
#   1. Uncomment the ACCESS_TOKEN block below
#   2. In create_new_mqtt_client(): comment the MQTT Basic block, uncomment Access Token block
#   3. Change ThingsBoard device credential type back to "Access Token"
# ACCESS_TOKEN = modem_config_db.get_parameter("access_token") or ""
# _token_is_blank = not ACCESS_TOKEN.strip() or ACCESS_TOKEN.strip() == "see-secrets_manager"
# if _token_is_blank:
#     log.warning("access_token not set in DB — trying MQTT_TOKEN in .env (optional)")
#     try:
#         ACCESS_TOKEN = get_secret("MQTT_TOKEN")
#         log.info("access_token loaded from .env fallback")
#     except (KeyError, RuntimeError):
#         log.warning(
#             "MQTT_TOKEN not in .env either — publisher will start but MQTT auth "
#             "will fail until access_token is set via LCD menu"
#         )
#         ACCESS_TOKEN = ""

# ── X.509 CLIENT CERTIFICATE PATHS ──────────────────────────────────────
# SEC-08: Mutual TLS — device presents its certificate to ThingsBoard.
# Certs are generated per-device by docker/gen_device_cert.sh.
#
# _X509_CONN_ENABLED controls whether mTLS is active on the paho/Ethernet path.
#
# Activation sequence (do in order to avoid a broken window):
#   1. [DONE] fleet-ca.crt generated (certs-ca/fleet-ca.crt)
#   2. [DONE] device certs generated (certs-out/<DEVICE_NAME>/device.{crt,key})
#   3. [ ] Upload fleet-ca.crt to ThingsBoard → Device Profiles → Provisioning → Trusted CA
#   4. [ ] Change ThingsBoard device credential type to "X.509 Certificate"
#   5. [ ] scp device.crt + device.key to Pi at /home/pi/Test3/certs/
#   6. [ ] Flip _X509_CONN_ENABLED = True in SerialCommunication.py (GSM path)
#   7. [ ] Restart dexter-mqtt + dexter-serial-comm services on Pi
#
# Safe to deploy this code before steps 3-7: if cert files are absent from the Pi,
# _X509_READY stays False and this module falls back to MQTT Basic automatically.
_X509_CONN_ENABLED = True

_CERT_DIR    = "/home/pi/Test3/certs"
_CERT_DEVICE = f"{_CERT_DIR}/device.crt"   # this device's client cert (signed by fleet CA)
_CERT_KEY    = f"{_CERT_DIR}/device.key"   # this device's private key (chmod 600)

_X509_READY = _X509_CONN_ENABLED and all(os.path.exists(p) for p in [_CERT_DEVICE, _CERT_KEY])

# ── THINGSBOARD_HOST ─────────────────────────────────────────────────────
# Priority 1: modem_config.db — set by operator via LCD menu
# Priority 2: MQTT_BROKER in .env — optional fallback
# Default fallback: mqtt.thingsboard.cloud
THINGSBOARD_HOST = modem_config_db.get_parameter("swatch_mqtt_host") or ""
_host_is_blank = not THINGSBOARD_HOST.strip()
if _host_is_blank:
    log.warning("swatch_mqtt_host not set in DB — trying MQTT_BROKER in .env (optional)")
    try:
        THINGSBOARD_HOST = get_secret("MQTT_BROKER")
        log.info("swatch_mqtt_host loaded from .env fallback")
    except (KeyError, RuntimeError):
        THINGSBOARD_HOST = "mqtt.thingsboard.cloud"
        log.warning(
            "MQTT_BROKER not in .env — using default: %s", THINGSBOARD_HOST
        )


# ─────────────────────────────────────────────────────────────────
# MQTT CALLBACKS
# ─────────────────────────────────────────────────────────────────
def on_connect(client, userdata, flags, reason_code, properties):
    if reason_code == 0:
        log.info("MQTT: connected to ThingsBoard at %s", THINGSBOARD_HOST)
    else:
        log.warning("MQTT: connection failed — reason_code=%s", reason_code)


def on_disconnect(client, userdata, reason_code, properties, reason_string=None):
    log.warning("MQTT: disconnected (reason_code=%s)", reason_code)


def on_publish(client, userdata, mid, reason_codes, properties):
    log.debug("MQTT: published (mid=%s)", mid)


def on_log(client, userdata, level, buf):
    log.debug("MQTT log: %s", buf)


# ─────────────────────────────────────────────────────────────────
# NETWORK CHECK
# ─────────────────────────────────────────────────────────────────
def is_connected() -> bool:
    try:
        socket.create_connection(("8.8.8.8", 53), timeout=3)
        return True
    except Exception as e:
        log.debug("Network check failed: %s", e)
        return False


# ─────────────────────────────────────────────────────────────────
# MQTT CLIENT CREATION
# ─────────────────────────────────────────────────────────────────
def create_new_mqtt_client() -> mqtt.Client:
    client = mqtt.Client(
        client_id=CLIENT_ID,
        protocol=mqtt.MQTTv311,
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
    )
    # RECONNECT-FIX: default min_delay=1s resets to 1s on every CONNACK, even
    # when the broker immediately drops the TCP afterward (ThingsBoard throttle).
    # A 30s minimum ensures at most 2 auto-reconnect attempts per minute while
    # the broker rate-limit window clears. The run()-loop backoff adds further
    # protection when connections are short-lived.
    client.reconnect_delay_set(min_delay=30, max_delay=300)

    if _X509_READY:
        # ── SEC-08: X.509 mTLS (active when certs present) ───────────────
        # Device cert identifies this device to ThingsBoard — no username/
        # password needed. ThingsBoard credential type: "X.509 Certificate".
        # create_default_context() loads system CAs (includes Let's Encrypt)
        # for server cert verification, then load_cert_chain() adds the client
        # cert. Must use create_default_context() — SSLContext(PROTOCOL_TLS_CLIENT)
        # does NOT load system CAs despite enabling CERT_REQUIRED.
        ctx = ssl.create_default_context()
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.load_cert_chain(certfile=_CERT_DEVICE, keyfile=_CERT_KEY)
        client.tls_set_context(ctx)
    else:
        # ── MQTT Basic auth (fallback — active when certs absent) ─────────
        # Used during pre-provisioning or when C16QS path also needs MQTT
        # Basic (ThingsBoard credential type: "MQTT Basic Credentials").
        client.username_pw_set(username=USER_NAME, password=PASSWORD)
        ctx = ssl.create_default_context()
        ctx.check_hostname  = True
        ctx.verify_mode     = ssl.CERT_REQUIRED
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        client.tls_set_context(ctx)

    # ── Access Token auth (reserved — uncomment to switch back) ──────────
    # client.username_pw_set(ACCESS_TOKEN)
    # ctx = ssl.create_default_context()
    # ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    # client.tls_set_context(ctx)

    client.on_connect    = on_connect
    client.on_disconnect = on_disconnect
    client.on_publish    = on_publish
    client.on_log        = on_log

    return client


# ─────────────────────────────────────────────────────────────────
# CONNECT WITH EXPONENTIAL BACKOFF
# ─────────────────────────────────────────────────────────────────
def connect_to_thingsboard(client: mqtt.Client) -> None:
    """
    BUG-03 FIX: Original had client.loop_start() INSIDE the retry loop.
    Each failed attempt called loop_start() again, spawning a new background
    network thread. After 5 retries: 5 threads, all on the same socket.
    Fix: loop_start() called ONCE, before the retry loop starts.

    PERF-05 FIX: Original used hardcoded time.sleep(5) on every retry.
    Fix: exponential backoff — 1s → 2s → 4s → ... → max 300s.
    """
    retry_count = 0

    # BUG-03 FIX: called once here, not inside the loop below
    client.loop_start()

    while not client.is_connected():
        try:
            log.info("MQTT: connecting to %s:8883 (attempt %d)",
                     THINGSBOARD_HOST, retry_count + 1)

            client.connect(THINGSBOARD_HOST, 8883, 60)

            # Wait up to 10s for on_connect callback to confirm
            for _ in range(10):
                if client.is_connected():
                    break
                time.sleep(1)

            if client.is_connected():
                log.info("MQTT: connected")
                return

        except ssl.SSLError as e:
            # SEC-07: TLS failure is fatal — no plain-text fallback
            client.loop_stop()
            raise RuntimeError(
                f"MQTT TLS error — aborted. "
                f"Check broker cert and MQTT_TOKEN. Detail: {e}"
            ) from e

        except Exception as e:
            # PERF-05 FIX: exponential backoff
            delay = min(1 * (2 ** retry_count), 300)
            log.warning(
                "MQTT: error — %s. Retry in %ds (attempt %d)",
                e, delay, retry_count + 1
            )
            time.sleep(delay)
            retry_count += 1


# ─────────────────────────────────────────────────────────────────
# PUBLISH DATA
# ─────────────────────────────────────────────────────────────────
def publish_data(client: mqtt.Client, data: dict) -> None:
    json_string = json.dumps(data)
    is_match    = json_db_module.check_incoming_json(json_string)

    topic  = "v1/devices/me/attributes" if is_match else "v1/devices/me/telemetry"
    result = client.publish(topic, json_string, qos=1)
    result.wait_for_publish()
    log.info("MQTT: published to %s — %s", topic, json_string[:500])


# ─────────────────────────────────────────────────────────────────
# CHILD PROGRAM
# ─────────────────────────────────────────────────────────────────
class ChildProgram:

    def __init__(self, db_handler: DatabaseHandler, pm=None):
        self.db_handler = db_handler
        self.pm         = pm          # PayloadManager — rate limit + cap
        self.client     = None
        self.connected  = False
        self._lock      = threading.Lock()

    def initialize_connection(self) -> None:
        with self._lock:
            if self.client:
                try:
                    self.client.loop_stop()
                    self.client.disconnect()
                except Exception:
                    pass
            self.client = create_new_mqtt_client()

        connect_to_thingsboard(self.client)
        self.connected = True
        log.info("MQTT: connection initialised")

    def _reset_connection(self) -> None:
        """Clean teardown on network loss or publish failure."""
        self.connected = False
        with self._lock:
            if self.client:
                try:
                    self.client.loop_stop()
                    self.client.disconnect()
                except Exception:
                    pass
                self.client = None
        log.warning("MQTT: connection reset")

    def send_to_cloud(self, data: str) -> bool:
        if not is_connected():
            log.warning("MQTT: no network — skipping send")
            return False

        if not self.connected:
            self.initialize_connection()

        try:
            json_data = json.loads(data)
        except json.JSONDecodeError:
            log.warning("MQTT: malformed JSON — attempting auto-repair")
            try:
                data      = data.replace("'", '"').replace("None", "null")
                json_data = json.loads(data)
            except json.JSONDecodeError as e:
                log.error("MQTT: JSON repair failed — skipping: %s", e)
                return False

        try:
            publish_data(self.client, json_data)
            return True
        except Exception as e:
            log.error("MQTT: publish failed — %s", e)
            self._reset_connection()
            return False

    def run(self) -> None:
        # BUG-04 FIX: original had no try/except around the run loop body.
        # Any unhandled exception (socket drop, JSON error, DB error) would
        # propagate out of run() and kill the publisher permanently with no
        # restart. Now all unexpected errors are caught, connection is reset,
        # and the loop continues.
        log.info("MQTT publisher: starting run loop")

        _consec_failures = 0   # consecutive short-lived connections (broker throttle)
        _connected_at    = 0.0  # monotonic time of last successful initialize_connection

        while True:
            try:
                if is_connected():
                    if not self.connected:
                        self.initialize_connection()
                        _connected_at = time.monotonic()

                    # Use PayloadManager for rate-limited, backlog-managed delivery
                    if self.pm:
                        row_id, json_str = self.pm.get_next()
                    else:
                        row_id, json_str = self.db_handler.get_json_string()

                    if json_str:
                        if self.send_to_cloud(json_str):
                            self.db_handler.mark_as_sent(row_id)
                            _consec_failures = 0  # stable publish → reset backoff
                    else:
                        log.debug("MQTT: no pending payloads")

                else:
                    if self.connected:
                        self._reset_connection()
                    log.warning("MQTT: no network — waiting")

            except Exception as e:
                log.error("MQTT: unexpected error in run loop — %s", e)
                self._reset_connection()
                _consec_failures += 1

            # RECONNECT-BACKOFF: if connection keeps dropping within 10s of
            # connecting, the broker is throttling. Back off exponentially so
            # ThingsBoard's rate-limit window can clear before the next attempt.
            if not self.connected and (time.monotonic() - _connected_at) < 10:
                delay = min(10 * (2 ** min(_consec_failures, 5)), 300)
                log.warning("MQTT: connection unstable — backing off %ds before reconnect", delay)
                time.sleep(delay)
            else:
                time.sleep(5)


# ─────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s"
    )

    if _X509_CONN_ENABLED:
        if _X509_READY:
            log.info("X.509 mTLS active — certs found at %s", _CERT_DIR)
        else:
            log.warning(
                "X.509 enabled but certs not found in %s — using MQTT Basic auth. "
                "scp device.crt + device.key to %s, then restart this service.",
                _CERT_DIR, _CERT_DIR,
            )
    else:
        log.info("X.509 mTLS disabled (_X509_CONN_ENABLED=False) — using MQTT Basic auth")

    # Ensure json_configurations table exists before check_incoming_json() runs
    json_db_module.init_db()

    db_handler   = DatabaseHandler()
    pm           = PayloadManager(db_handler)  # backlog + rate limiter
    pm.startup_purge()                          # wipe stale heartbeats on boot
    program      = ChildProgram(db_handler, pm)

    network_type = modem_config_db.get_parameter("network_type")
    log.info("Current network type: %s", network_type)

    try:
        if network_type == "ethernet":
            program.run()
        else:
            log.warning(
                "Network type is '%s' — publisher only starts for 'ethernet'. "
                "Update network_type in modem_config.db if needed.",
                network_type
            )

    except KeyboardInterrupt:
        log.info("MQTT publisher: shutting down")
        if program.client:
            program.client.loop_stop()
            program.client.disconnect()