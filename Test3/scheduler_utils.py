# -*- coding: utf-8 -*-
"""
scheduler_utils.py — Shared scheduling utilities for Dexter HMS active integration modules

Provides two tools that solve the thundering herd problem at 5,000 panels:

  1. get_jitter_sec(window_sec)
     Deterministic per-panel startup delay derived from the RPi hostname.
     Same panel → same delay every reboot.
     Different panels → different delays.
     Use for: interval tasks (heartbeat, time sync, work status).

  2. is_rpi_idle()
     Reads the latest CPU and RAM metrics from task_manager.db
     (written every 60s by RPi_Task_Manager.py).
     Returns True if both are below threshold — safe to run a daily task.
     Use for: daily bulk-data tasks (camera info, HDD info, system snapshot).

Usage
-----
    from scheduler_utils import get_jitter_sec, is_rpi_idle

    # At module startup — before scheduler loop:
    jitter = get_jitter_sec(window_sec=300)
    log.info("[startup] jitter delay = %ds", jitter)
    time.sleep(jitter)

    # In the daily send function:
    def maybe_send_daily():
        global _daily_sent_date
        today = datetime.date.today()
        if _daily_sent_date == today:
            return
        if not is_rpi_idle():
            log.debug("[daily] RPi busy — deferring")
            return
        # send all daily tasks here
        _daily_sent_date = today

Author: Seple Novaedge Pvt. Ltd.
"""

import datetime
import hashlib
import logging
import socket
import sqlite3

log = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────
_DB_TASK_MANAGER   = "/home/pi/Test3/task_manager.db"
CPU_GATE_THRESHOLD = 75.0   # % — above this the RPi is considered busy
RAM_GATE_THRESHOLD = 75.0   # % — above this the RPi is considered busy


# ── Jitter ────────────────────────────────────────────────────────────────────

def get_jitter_sec(window_sec: int = 300) -> int:
    """
    Return a deterministic per-panel startup delay in seconds.

    The delay is derived from the RPi hostname using MD5 so it is:
      - Always the same for this panel across reboots (deterministic)
      - Different for every panel (unique per device)
      - In the range [0, window_sec)

    Parameters
    ----------
    window_sec : int
        Spread window in seconds. Default 300 (5 minutes).
        5,000 panels × 300s window → ~17 panels fire per second
        instead of 5,000 at once.

    Returns
    -------
    int : seconds to sleep before starting the scheduler loop.
    """
    try:
        panel_id = socket.gethostname()
    except Exception:
        panel_id = "dexter-default"

    h = int(hashlib.md5(panel_id.encode()).hexdigest(), 16)
    jitter = h % window_sec
    log.info("[scheduler_utils] panel_id=%s  jitter=%ds  window=%ds",
             panel_id, jitter, window_sec)
    return jitter


# ── Load gate ─────────────────────────────────────────────────────────────────

def is_rpi_idle(
    cpu_threshold: float = CPU_GATE_THRESHOLD,
    ram_threshold: float = RAM_GATE_THRESHOLD,
) -> bool:
    """
    Return True if the RPi is currently idle enough to run a daily bulk task.

    Reads the latest row from task_manager.db (written every 60s by
    RPi_Task_Manager.py). If cpu_percent < cpu_threshold AND
    memory_percent < ram_threshold, the panel is considered idle.

    On any error (DB not found, no rows yet) returns True so that the
    task is not deferred indefinitely on a freshly booted panel.

    Parameters
    ----------
    cpu_threshold : float  CPU % ceiling. Default 70.0.
    ram_threshold : float  RAM % ceiling. Default 75.0.
    """
    try:
        conn = sqlite3.connect(_DB_TASK_MANAGER, timeout=5)
        row  = conn.execute(
            "SELECT cpu_percent, memory_percent "
            "FROM system_stats ORDER BY timestamp DESC LIMIT 1"
        ).fetchone()
        conn.close()

        if row is None:
            log.debug("[scheduler_utils] task_manager.db has no rows yet — allowing")
            return True

        cpu, ram = row
        idle = (cpu is not None and cpu < cpu_threshold and
                ram is not None and ram < ram_threshold)

        log.debug(
            "[scheduler_utils] RPi load — CPU=%.1f%% RAM=%.1f%% "
            "thresholds=CPU<%.0f%% RAM<%.0f%% idle=%s",
            cpu or 0, ram or 0, cpu_threshold, ram_threshold, idle
        )
        return idle

    except Exception as exc:
        log.warning("[scheduler_utils] is_rpi_idle DB error — allowing: %s", exc)
        return True
