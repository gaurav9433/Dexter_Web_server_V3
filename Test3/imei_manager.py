#!/usr/bin/env python3
"""
imei_manager.py — Dexter HMS IMEI Scheduled Sender
Seple Novaedge Pvt. Ltd.

Sends the device IMEI to ThingsBoard twice a day (every 12 hours).
Replaces the logTypeSysParam==12 block in scheduleSystemStatusUpload()
which previously sent IMEI once per full cycle (~25 min cycle).

Logic:
  ON STARTUP:
    1. Send IMEI immediately to TB.
    2. Schedule repeat every 12 hours forever.

  PAYLOAD (unchanged from original):
    {"imei_id": "<15-digit IMEI string>"}

  INTEGRATION IN TLChronosProMAIN:

    At startup (after cavli_database initialised):
        import imei_manager
        def _send_imei_to_tb():
            send_imei_id(cavli_database.get_IMEI())
        imei_manager.start(_send_imei_to_tb)

    In scheduleSystemStatusUpload() logTypeSysParam==12 block, replace:
        OLD:
            send_imei_id(cavli_database.get_IMEI())
        NEW:
            pass  (or remove the block body entirely — imei_manager handles it)

    On shutdown:
        imei_manager.stop()
"""

import threading
import time
import logging

log = logging.getLogger("dexter-imei")

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────
IMEI_SEND_INTERVAL = 43200     # 12 hours (seconds) — sends twice a day

# ─────────────────────────────────────────────────────────────────────────────
# State
# ─────────────────────────────────────────────────────────────────────────────
_send_fn    = None             # injected callable — sends IMEI to TB
_timer      = None             # active threading.Timer
_lock       = threading.Lock()
_last_sent  = 0.0


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────
def _cancel_timer():
    global _timer
    with _lock:
        if _timer is not None:
            _timer.cancel()
            _timer = None


def _schedule_next():
    global _timer
    _cancel_timer()
    with _lock:
        _timer = threading.Timer(IMEI_SEND_INTERVAL, _on_send)
        _timer.daemon = True
        _timer.name   = "imei-timer"
        _timer.start()


def _on_send():
    """Called at startup and every 12 hours."""
    global _last_sent
    try:
        if _send_fn:
            _send_fn()
        _last_sent = time.time()
        log.info("[IMEI] Sent IMEI to TB")
    except Exception as exc:
        log.error("[IMEI] Send failed: %s", exc)
    # Schedule next send in 12 hours
    _schedule_next()


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────
def start(send_imei_fn):
    """
    Initialise IMEI manager. Call once at system startup.

    Args:
        send_imei_fn: callable() — calls send_imei_id(cavli_database.get_IMEI())
                      No arguments — the caller closes over cavli_database.
    """
    global _send_fn
    _send_fn = send_imei_fn
    log.info("[IMEI] Manager starting — sends every %d hours", IMEI_SEND_INTERVAL // 3600)
    # Send immediately at startup, then schedule repeat
    t = threading.Thread(target=_on_send, daemon=True, name="imei-init")
    t.start()


def stop():
    """Cancel pending timer. Call on clean system shutdown."""
    _cancel_timer()
    log.info("[IMEI] Manager stopped.")
