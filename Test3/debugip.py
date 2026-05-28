"""
debugip.py
Dexter HMS — Tailscale IP/hostname publisher to ThingsBoard attributes

Publishes tailscale_hostname and tailscale_ip to ThingsBoard device attributes
via MQTT so the device can be reached remotely via Tailscale.

Changes from old architecture:
  FIX-01: log.info("text:", var) — wrong logging syntax on 3 lines.
           Caused TypeError crash in on_connect — attributes never published.
           Fixed: log.info("text: %s", var)
  FIX-02: modem_config_db at module level — credentials cached at import time.
           Moved inside main() only.
  FIX-03: mqtt.Client() without CallbackAPIVersion — fails on paho >= 2.0.
           Added CallbackAPIVersion.VERSION1 to keep 4-arg on_connect signature.
  FIX-04: time.sleep(2) race — PUBACK may not arrive before disconnect.
           Replaced with threading.Event + on_publish callback.
  FIX-05: port 1883 plain → port 8883 TLS (security upgrade).
  FIX-06: Credentials from modem_config.db with Fernet decrypt.
"""

import ssl
import json
import time
import threading
import subprocess
import logging
import sqlite3
import paho.mqtt.client as mqtt

log = logging.getLogger(__name__)

THINGSBOARD_HOST = "www.dexterhms.com"
MQTT_PORT        = 8883
PUBLISH_TIMEOUT  = 10


def _read_modem(col: str) -> str:
    try:
        conn = sqlite3.connect("/home/pi/Test3/modem_config.db")
        row = conn.execute(
            f"SELECT {col} FROM modem_parameters WHERE id=1"
        ).fetchone()
        conn.close()
        return (row[0] or "").strip() if row else ""
    except Exception as e:
        log.warning("debugip: DB read failed for %s: %s", col, e)
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

def _read_saved_tailscale_ip() -> tuple:
    """
    Read the Tailscale IP saved to tailscale_info.db during provisioning.
    Used as fallback when live status has no IP (coordination server
    unreachable — e.g. eth0 is LAN-only and PPP not yet routing for Tailscale).
    """
    try:
        import sys
        sys.path.insert(0, "/home/pi/Test3")
        from db_connection import get_connection, DB_TAILSCALE
        conn = get_connection(DB_TAILSCALE)
        row = conn.execute(
            "SELECT tailscale_hostname, tailscale_ip "
            "FROM device_info ORDER BY id DESC LIMIT 1"
        ).fetchone()
        conn.close()
        if row and row[0] and row[1]:
            log.info("Saved Tailscale info: %s %s", row[0], row[1])
            return str(row[0]), str(row[1])
    except Exception as e:
        log.warning("debugip: could not read saved Tailscale IP: %s", e)
    return "unknown", ""


def get_tailscale_info() -> tuple:
    """
    Get Tailscale hostname and IP.

    eth0 is LAN-only in field deployments so Tailscale must use ppp0
    for the coordination server. ppp0 comes up AFTER Tailscale daemon
    starts, so Tailscale needs a nudge to re-evaluate routes.

    Sequence:
    1. Run `tailscale up --accept-routes` to force route re-evaluation
       after PPP interface comes up (same command used during provisioning)
    2. Wait up to 60s for live IP (matches old architecture behaviour)
    3. Fall back to saved IP from tailscale_info.db if still no IP
    """
    # Force Tailscale to re-evaluate routes now that ppp0 is up.
    # Without this, Tailscale keeps trying eth0 (LAN-only) and never
    # reaches the coordination server to get its IP.
    try:
        log.info("debugip: triggering tailscale route re-evaluation")
        # Read device_name from DB to pass as --hostname, matching provisioning.
        # Must repeat all non-default flags or use --reset to avoid error:
        # "requires mentioning all non-default flags"
        import sqlite3 as _sqlite3
        _device_name = ""
        try:
            _conn = _sqlite3.connect("/home/pi/Test3/modem_config.db")
            _row = _conn.execute(
                "SELECT device_name FROM modem_parameters WHERE id=1"
            ).fetchone()
            _conn.close()
            _device_name = (_row[0] or "").strip() if _row else ""
        except Exception:
            pass
        _ts_cmd = ["sudo", "tailscale", "up", "--accept-routes"]
        if _device_name:
            _ts_cmd += [f"--hostname={_device_name}"]
        else:
            _ts_cmd += ["--reset"]
        # Run in background — tailscale up blocks waiting for coordination
        # server which may take 30-60s when PPP is the only internet route.
        # Running non-blocking lets the IP wait loop run in parallel.
        import threading as _threading
        _ts_thread = _threading.Thread(
            target=subprocess.call, args=(_ts_cmd,), daemon=True
        )
        _ts_thread.start()
        time.sleep(3)
    except Exception as e:
        log.warning("debugip: tailscale up failed: %s", e)

    # Try live status for up to 60s (20 x 3s)
    for _ in range(20):
        try:
            ts_status = subprocess.check_output(
                ["tailscale", "status", "--json"], timeout=5
            )
            status_data = json.loads(ts_status)
            if status_data and status_data.get("Self"):
                hostname = status_data["Self"].get("HostName", "unknown")
                ips      = status_data["Self"].get("TailscaleIPs", [])
                ip       = ips[0] if ips else ""
                if ip:
                    log.info("Tailscale live: %s %s", hostname, ip)
                    return hostname, ip
                else:
                    log.info("Tailscale connected but no IP yet — waiting...")
        except Exception as e:
            log.info("Waiting for Tailscale... (%s)", e)
        time.sleep(3)

    # Fallback to saved IP from provisioning
    hostname_saved, ip_saved = _read_saved_tailscale_ip()
    if ip_saved:
        log.warning(
            "Tailscale live IP not available after 60s — using saved: %s %s",
            hostname_saved, ip_saved
        )
        return hostname_saved, ip_saved

    log.warning("Tailscale not ready and no saved IP — publishing N/A")
    return hostname_saved or "unknown", "N/A"


def main():
    # FIX-02: credentials read here, not at module level
    client_id = _dec(_read_modem("client_id"))
    user_name = _dec(_read_modem("user_name"))
    password  = _dec(_read_modem("password"))

    tailscale_hostname, tailscale_ip = get_tailscale_info()

    ctx = ssl.create_default_context()
    ctx.check_hostname  = True
    ctx.verify_mode     = ssl.CERT_REQUIRED
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2

    # FIX-04: threading.Event to wait for PUBACK
    published = threading.Event()

    # FIX-01: correct log syntax; FIX-03: CallbackAPIVersion.VERSION1
    def on_connect(client, userdata, flags, rc):
        log.info("Connected with result code: %s", rc)   # FIX-01
        if rc == 0:
            payload = json.dumps({
                "tailscale_hostname": tailscale_hostname,
                "tailscale_ip":       tailscale_ip,
            })
            log.debug("Sending payload: %s", payload)    # FIX-01
            client.publish("v1/devices/me/attributes", payload, qos=1)
        else:
            log.error("on_connect: broker rejected — rc=%s", rc)
            published.set()

    def on_publish(client, userdata, mid):
        log.info("Attribute sent. mid = %s", mid)        # FIX-01
        published.set()   # FIX-04

    # FIX-03: CallbackAPIVersion.VERSION1 matches 4-arg on_connect
    client = mqtt.Client(
        client_id=client_id or "debugip",
        callback_api_version=mqtt.CallbackAPIVersion.VERSION1,
    )
    client.username_pw_set(user_name, password=password)
    client.tls_set_context(ctx)   # FIX-05: TLS on 8883
    client.on_connect = on_connect
    client.on_publish = on_publish

    # DNS-FIX: retry connect on [Errno -2/-3] DNS failure — same pattern as
    # provision_device(). systemd-resolved is briefly unstable after PPP connects.
    _connect_retries = 10
    for _attempt in range(_connect_retries):
        try:
            client.connect(THINGSBOARD_HOST, MQTT_PORT, 60)
            break
        except OSError as e:
            if e.errno in (-2, -3):
                if _attempt < _connect_retries - 1:
                    log.warning("debugip: DNS not ready (attempt %d/%d) — retrying in 3s",
                                _attempt + 1, _connect_retries)
                    time.sleep(3)
                else:
                    log.error("debugip: DNS not ready after %d attempts — giving up",
                              _connect_retries)
                    return   # exhausted retries — return gracefully, no traceback
            else:
                log.error("debugip: connect failed — %s", e)
                return
    client.loop_start()

    # FIX-04: wait for PUBACK, not fixed sleep
    if not published.wait(timeout=PUBLISH_TIMEOUT):
        log.warning("debugip: publish not confirmed within %ds", PUBLISH_TIMEOUT)

    client.loop_stop()
    client.disconnect()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s"
    )
    main()
