# -*- coding: utf-8 -*-
# !/usr/local/bin/python
"""
panel_utils — Panel startup and operational utilities

Extracted from TLChronosProMAIN_391.py as part of Sprint C decomposition.

Fixes applied in this revision:
  BUG-01: logger not defined — log variable was named 'log', all logger.* -> log.*
  BUG-02: time module never imported — time.sleep(30) caused NameError on failure path
  BUG-03: timedatectl fails when NTP is active — added set-ntp false/true wrapper
  BUG-04: remaining print() calls in except blocks -> log.error/log.warning
"""
import subprocess
import json
import time
import logging
from datetime import datetime

from syslog_file_logger import get_dual_logger
from buffer_manager import get_and_delete_json_from_db

log = get_dual_logger(__name__)

# ── Injected at startup ───────────────────────────────────────────────────────
_msg_queue_buffer = None
_device_serial_db = None

def set_msg_queue_buffer(buf) -> None:
    """Inject the MsgQueueBuffer instance. Call once at startup."""
    global _msg_queue_buffer
    _msg_queue_buffer = buf

def set_device_serial_db(db) -> None:
    """Inject the DeviceSerialNoInfoDB instance. Call once at startup."""
    global _device_serial_db
    _device_serial_db = db


def consume_json() -> None:
    """Consume the oldest JSON object from the buffer queue."""
    json_data = get_and_delete_json_from_db()

    if json_data:
        log.debug("[consume_json] Consumed: %s", json_data)
        incoming_json_obj = json_data
        if _msg_queue_buffer is not None:
            _msg_queue_buffer.add(incoming_json_obj)
        else:
            log.warning("[consume_json] _msg_queue_buffer not injected — call set_msg_queue_buffer() at startup")
    else:
        log.debug("[consume_json] No pending JSON in buffer")


def set_date_time(year: int, month: int, day: int,
                  hour: int, minute: int, second: int) -> None:
    """
    Set the system date and time using timedatectl.

    BUG-03 FIX: timedatectl refuses to set time while NTP sync is active
    (exits with status 1). We temporarily disable NTP, set the time,
    then re-enable NTP.

    BUG-02 FIX: time module is now imported at the top of this file.
    BUG-01 FIX: log.error used instead of undefined logger.error.
    """
    date_time_str = "{0:04d}-{1:02d}-{2:02d} {3:02d}:{4:02d}:{5:02d}".format(
        year, month, day, hour, minute, second
    )

    try:
        # BUG-03 FIX: disable NTP sync before manual time set
        subprocess.check_call(["sudo", "timedatectl", "set-ntp", "false"])

        subprocess.check_call(["sudo", "timedatectl", "set-time", date_time_str])
        log.info("[set_date_time] System time set to %s", date_time_str)

    except subprocess.CalledProcessError as e:
        # BUG-01 FIX: was logger.error (undefined) — now log.error
        log.error("[set_date_time] Failed to set time to %s: %s", date_time_str, e)

    except Exception as e:
        log.error("[set_date_time] Unexpected error: %s", e)

    finally:
        # Always re-enable NTP so the clock stays in sync
        try:
            subprocess.check_call(["sudo", "timedatectl", "set-ntp", "true"])
        except Exception as e:
            log.warning("[set_date_time] Could not re-enable NTP: %s", e)


def panelSlno() -> None:
    """Read device serial and batch number from DB and publish to ThingsBoard."""
    # Import here to avoid circular import — these are injected by TLChronosProMAIN
    from panel_telemetry import sendData2TB

    if _device_serial_db is None:
        log.error("[panelSlno] _device_serial_db not injected — call set_device_serial_db() at startup")
        return

    try:
        panel, batch = _device_serial_db.fetch_device_info()
        log_data = {
            "panel_sl_no": [{"Serial_No": panel, "Batch_No": batch}]
        }
        sendData2TB(log_data)

    except Exception as e:
        # BUG-01 FIX: was logger.error (undefined) — now log.error
        log.error("[panelSlno] Failed to send serial number data: %s", e)


def Versionno() -> None:
    """Publish firmware version string to ThingsBoard."""
    # Import here to avoid circular import
    from panel_telemetry import sendData2TB

    log_data = {"s_health_fw_ver": "V-2.1"}

    try:
        sendData2TB(log_data)
        log.info("[Versionno] Firmware version sent")

    except Exception as e:
        log.error("[Versionno] Failed to send version data: %s", e)
