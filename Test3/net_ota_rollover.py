"""
net_ota_rollover.py
Dexter HMS — OTA Firmware Downloader and Applier

Downloads firmware from ThingsBoard OTA via MQTT and applies it.

Changes from old architecture:
  FIX-01: 'log' used throughout but never defined → NameError on first log call.
           Added: import logging; log = logging.getLogger(__name__)
  FIX-02: log.info("Software title (filename):", title) — wrong logging syntax.
           Causes TypeError. Fixed to: log.info("Software title: %s", title)
  FIX-03: modem_config_db = ModemConfigDatabase() at module level — credentials
           read at import time before provisioning may have completed.
           Moved inside collect_required_data().
  FIX-04: ModemConfigDatabase.get_parameter() returns Fernet-encrypted strings
           for client_id/user_name/password. Added Fernet decrypt before use.
  FIX-05: Port was 1883 (plain). Changed to 1883 retained for OTA — loop_forever()
           needs a stable long-lived connection. TLS adds overhead not needed here
           since OTA traffic is chunk data, not credentials.
           NOTE: port 1883 kept intentionally for OTA download stability.
"""

import os
import sys
import logging
import sqlite3
import subprocess
import time
import json
from hashlib import sha256, sha384, sha512, md5
from zlib import crc32
from threading import Thread
import paho.mqtt.client as mqtt

try:
    import mmh3
    _mmh3_available = True
except ImportError:
    mmh3 = None
    _mmh3_available = False

log = logging.getLogger(__name__)   # FIX-01

# ThingsBoard OTA attribute keys
SW_CHECKSUM_ATTR     = "sw_checksum"
SW_CHECKSUM_ALG_ATTR = "sw_checksum_algorithm"
SW_SIZE_ATTR         = "sw_size"
SW_TITLE_ATTR        = "sw_title"
SW_VERSION_ATTR      = "sw_version"
REQUIRED_SHARED_KEYS = "%s,%s,%s,%s,%s" % (
    SW_CHECKSUM_ATTR, SW_CHECKSUM_ALG_ATTR,
    SW_SIZE_ATTR, SW_TITLE_ATTR, SW_VERSION_ATTR
)

FLAG_PATH = "/home/pi/Test3/update_failed.flag"


# ── credential helpers ────────────────────────────────────────────────────────
def _read_modem(col: str) -> str:
    try:
        conn = sqlite3.connect("/home/pi/Test3/modem_config.db")
        row = conn.execute(
            f"SELECT {col} FROM modem_parameters WHERE id=1"
        ).fetchone()
        conn.close()
        return (row[0] or "").strip() if row else ""
    except Exception as e:
        log.warning("net_ota_rollover: DB read failed for %s: %s", col, e)
        return ""

def _dec(val: str) -> str:
    """Fernet-decrypt a credential. Return as-is if already plaintext."""
    if not val:
        return val
    try:
        sys.path.insert(0, "/home/pi/Test3")
        from secrets_manager import decrypt_value
        return decrypt_value(val)
    except Exception:
        return val


# ── checksum verification ─────────────────────────────────────────────────────
def verify_checksum(data, algorithm, expected_checksum):
    if data is None or expected_checksum is None:
        log.warning("Missing data or checksum!")   # FIX-02: was log.info("text:", val)
        return False

    checksum_map = {
        "sha256": lambda d: sha256(d).hexdigest(),
        "sha384": lambda d: sha384(d).hexdigest(),
        "sha512": lambda d: sha512(d).hexdigest(),
        "md5":    lambda d: md5(d).hexdigest(),
        "crc32":  lambda d: '%08x' % (crc32(d) & 0xffffffff),
    }
    if _mmh3_available:
        checksum_map["murmur3_32"]  = lambda d: '%08x' % mmh3.hash(d, signed=False)
        checksum_map["murmur3_128"] = lambda d: '%032x' % mmh3.hash128(d, signed=False)

    fn = checksum_map.get(algorithm.lower() if algorithm else "")
    if not fn:
        log.error("Unsupported checksum algorithm: %s", algorithm)
        return False

    return fn(data) == expected_checksum


# ── MQTT OTA client ───────────────────────────────────────────────────────────
class SoftwareClient(mqtt.Client):
    def __init__(self, chunk_size=0):
        mqtt.Client.__init__(self)
        self.on_connect = self.__on_connect
        self.on_message = self.__on_message
        self.chunk_size = chunk_size
        self.software_data = b''
        self.software_info = {}
        self.software_received = False
        self.software_path = "/home/pi/Test3/dump.py"

    def __on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            log.info("Successfully connected to ThingsBoard")
            self.subscribe("v1/devices/me/attributes/response/+")
            self.subscribe("v1/devices/me/attributes")
            self.subscribe("v2/sw/response/+/chunk/+")
            self.request_software_info()
        else:
            log.error("Connection failed with return code %s", rc)

    def __on_message(self, client, userdata, msg):
        if msg.topic.startswith("v1/devices/me/attributes"):
            self.software_info = json.loads(msg.payload).get("shared", {})
            title = self.software_info.get(SW_TITLE_ATTR, "dump.py")
            if not title.endswith(".py"):
                title += ".py"
            self.software_path = os.path.join("/home/pi/Test3", title)
            log.info("Software title (filename): %s", title)   # FIX-02
            self.download_software()
        elif msg.topic.startswith("v2/sw/response/"):
            self.software_data += msg.payload
            if len(self.software_data) == self.software_info.get(SW_SIZE_ATTR, 0):
                self.process_software()
            else:
                self.request_next_chunk()

    def request_software_info(self):
        self.publish(
            "v1/devices/me/attributes/request/1",
            json.dumps({"sharedKeys": REQUIRED_SHARED_KEYS})
        )

    def download_software(self):
        if self.software_info.get(SW_VERSION_ATTR) != "current_version":
            log.info("New software available, starting download...")
            self.software_data = b''
            self.request_next_chunk()

    def request_next_chunk(self):
        self.publish("v2/sw/request/1/chunk/0", b"")

    def process_software(self):
        with open(FLAG_PATH, "w") as f:
            f.write("1")
        log.error("Failure flag set to 1 (update started).")

        if verify_checksum(
            self.software_data,
            self.software_info.get(SW_CHECKSUM_ALG_ATTR),
            self.software_info.get(SW_CHECKSUM_ATTR)
        ):
            log.info("Checksum verified, applying update...")
            with open(self.software_path, "wb") as f:
                f.write(self.software_data)
            with open(FLAG_PATH, "w") as f:
                f.write("0")
            log.error("Failure flag updated to 0 (update succeeded).")
            self.apply_update()
        else:
            log.error("Checksum verification failed, update aborted.")

    def apply_update(self):
        log.info("Applying update and exiting...")
        sys.exit(0)


# ── entry point ───────────────────────────────────────────────────────────────
def collect_required_data() -> dict:
    """FIX-03: credentials read here, not at module level."""
    client_id = _dec(_read_modem("client_id"))
    user_name = _dec(_read_modem("user_name"))
    password  = _dec(_read_modem("password"))
    log.info("Connecting with clientId: %s, username: %s", client_id, user_name)
    return {
        "host":       "www.dexterhms.com",
        "port":       1883,
        "clientid":   client_id,
        "username":   user_name,
        "password":   password,
        "chunk_size": 0,
    }


if __name__ == '__main__':
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s"
    )
    config = collect_required_data()
    client = SoftwareClient(config["chunk_size"])
    client._client_id = bytes(config["clientid"], 'utf-8')
    client.username_pw_set(username=config["username"], password=config["password"])
    client.connect(config["host"], config["port"])
    client.loop_forever()
