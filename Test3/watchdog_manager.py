# -*- coding: utf-8 -*-
# !/usr/local/bin/python
"""
watchdog_manager.py — Shared Software Watchdog for Dexter HMS

Responsibilities:
  - Provides the SoftwareWatchdog class used by all Dexter polling modules.
  - Runs a daemon thread that calls os.execl() to restart the host process
    if reset() is not called within the configured timeout.
  - Writes a watchdog_log telemetry event to the bounded buffer before restart.
  - Calls logging.shutdown() before os.execl() so RotatingFileHandler and
    SysLogHandler buffers are fully flushed (ERR-03 fix).

Key classes:
  SoftwareWatchdog — instantiate once per module; call reset() in the main loop.

Dependencies:
  buffer_manager_fix.BoundedBufferManager — for watchdog_log telemetry insert.
  syslog_file_logger.get_dual_logger      — for structured log output.

Author: Seple Novaedge Pvt. Ltd.

CQ-01 FIX: This class was copy-pasted verbatim into 10 separate modules
  (CP_Plus_SD_Card_HDD_Recording, Dahua_SD_Card_HDD_Recording, Extract_Logs_CP_Plus_42,
  Extract_Logs_Dahua_41, Hik_SD_Card, cp_plus_nvr_dvr_information,
  dahua_nvr_dvr_information, hikvision1_biometric_14, xml_parsing3,
  xml_parsing_field_log) — approximately 390 lines of identical code.
  Centralising here means: one place to fix a bug, one place to add a feature,
  zero risk of the copies diverging silently.

  Migration: replace the inline class definition in each module with:
      from watchdog_manager import SoftwareWatchdog
  The interface (timeout parameter, reset(), stop()) is identical.
"""

import json
import logging
import os
import sys
import threading
import time
from datetime import datetime

from syslog_file_logger import get_dual_logger

log = get_dual_logger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# OPTIONAL BUFFER INSERT
# The watchdog tries to log a telemetry event before restarting.
# Import is deferred and guarded so watchdog_manager has no hard dependency
# on buffer_manager_fix — modules that do not use the buffer (e.g. simple
# scripts) can still use SoftwareWatchdog safely.
# ─────────────────────────────────────────────────────────────────────────────

def _try_insert_watchdog_log(module_label: str) -> None:
    """
    Write a watchdog_log telemetry record to the bounded buffer if available.
    Silently skips if BoundedBufferManager is not importable (e.g. in tests).
    """
    try:
        from buffer_manager_fix import BoundedBufferManager
        _bm = BoundedBufferManager()
        payload = json.dumps({
            "watchdog_log": {
                "Module Reboot": module_label,
                "timestamp":     datetime.now().strftime("%d-%m-%y %H:%M:%S"),
            }
        })
        _bm.enqueue(json.loads(payload))
        log.info("[Watchdog] Reboot telemetry written for '%s'", module_label)
    except Exception as exc:
        log.error("[Watchdog] Failed to write reboot telemetry: %s", exc)


# ─────────────────────────────────────────────────────────────────────────────
# SOFTWAREWATCHDOG
# ─────────────────────────────────────────────────────────────────────────────

class SoftwareWatchdog:
    """
    Daemon-thread software watchdog for Dexter HMS polling modules.

    Starts a background thread that monitors whether reset() has been called
    within `timeout` seconds. If not, it logs the timeout, writes a
    watchdog_log telemetry event, flushes all logging handlers, and calls
    os.execl() to restart the current process.

    Usage:
        watchdog = SoftwareWatchdog(module_label="CP Plus Info", timeout=3600)

        while True:
            do_work()
            watchdog.reset()   # call every loop iteration
            time.sleep(interval)

    Parameters:
        module_label: Human-readable name logged in watchdog_log telemetry.
                      Appears on the ThingsBoard dashboard as the reboot source.
        timeout:      Seconds without a reset() call before restart is triggered.
                      Default: 3600 (1 hour). xml_parsing_field_log uses 1800.
        on_before_restart: Optional callable invoked just before os.execl().
                           Use for resource cleanup (e.g. closing a serial port).
                           Must complete quickly — it blocks the restart.

    CQ-01: Replaces identical copy-pasted class in 10 modules.
    ERR-03: logging.shutdown() called before os.execl() — log buffers flushed.
    """

    def __init__(
        self,
        module_label:      str  = "Dexter Module",
        timeout:           int  = 3600,
        on_before_restart: object = None,
    ) -> None:
        self.module_label      = module_label
        self.timeout           = timeout
        self.on_before_restart = on_before_restart

        self.last_reset = time.time()
        self._running   = True
        self._thread    = threading.Thread(
            target=self._watchdog_loop,
            daemon=True,
            name=f"Watchdog-{module_label[:20]}"
        )
        self._thread.start()
        log.info("[Watchdog] Started for '%s' with timeout=%ds",
                 module_label, timeout)

    # ── Public API ────────────────────────────────────────────────────────────

    def reset(self) -> None:
        """Call from the main loop to prevent the watchdog from triggering."""
        self.last_reset = time.time()

    def stop(self) -> None:
        """Cleanly stop the watchdog thread (call on graceful shutdown)."""
        self._running = False
        self._thread.join(timeout=5)
        log.info("[Watchdog] Stopped for '%s'", self.module_label)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _watchdog_loop(self) -> None:
        """Daemon loop — checks for timeout every second."""
        while self._running:
            if time.time() - self.last_reset > self.timeout:
                log.warning(
                    "[Watchdog] Timeout after %ds — restarting '%s'",
                    self.timeout, self.module_label
                )
                self._restart_program()
            time.sleep(1)

    def _restart_program(self) -> None:
        """
        1. Stop the watchdog loop.
        2. Run any caller-supplied pre-restart cleanup (e.g. serial port close).
        3. Write watchdog_log telemetry to the bounded buffer.
        4. Flush all logging handlers (ERR-03 fix).
        5. Replace the process with a fresh copy via os.execl().
        """
        self._running = False

        # Caller-supplied cleanup (e.g. close serial port in serial_data_logger)
        if callable(self.on_before_restart):
            try:
                self.on_before_restart()
            except Exception as exc:
                log.error("[Watchdog] Pre-restart cleanup error: %s", exc)

        # Telemetry — best-effort
        _try_insert_watchdog_log(self.module_label)

        # ERR-03: flush RotatingFileHandler and SysLogHandler before execl
        log.warning("[Watchdog] Flushing logs before process restart")
        logging.shutdown()

        # Restart
        python = sys.executable or "/usr/bin/python3"
        os.execl(python, python, *sys.argv)
