# RPi_Task_Manager.py
# Dexter HMS — Raspberry Pi System Health Monitor
# pip install psutil schedule
#
# CQ-01 — SoftwareWatchdog class removed (was inline copy-paste)
#         Replaced with: from watchdog_manager import SoftwareWatchdog
#
# Changes from original:
#   BUG-01 : import sys missing → sys.executable crash on watchdog restart
#   BUG-02 : import watchdog (library) immediately overwritten by
#            watchdog = SoftwareWatchdog() → confusing + import error on some envs
#   BUG-03 : bare except: in get_cpu_temp() masks all errors silently
#   BUG-04 : no try/except in log_stats() DB write → crash loses entire log cycle
#   BUG-05 : watchdog restart logs "Hik NVR Info" — wrong module name hardcoded
#   DB-01  : bare sqlite3.connect() → get_connection(DB_TASK_MANAGER) with WAL
#   CODE-01: import logging missing — no logging used anywhere
#   CODE-02: log_stats() and send_current_stats() duplicate all psutil calls →
#            extracted into _collect_stats() helper
#   CODE-03: DB_PATH = "task_manager.db" relative path → absolute DB_TASK_MANAGER
#   CODE-04: TEMP_THRESHOLD 70°C is too low — RPi throttles at 80°C, alarm at 75°C
#   CODE-05: all print() → logging

import sys
import os
import json
import time
import threading
import logging
import subprocess
from datetime import datetime
from typing import Dict, Optional

import psutil
import schedule

from buffer_manager import insert_json_to_db, init_db
init_db()
from db_connection import get_connection, DB_TASK_MANAGER

from watchdog_manager import SoftwareWatchdog
log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────────────────────────
INTERVAL_SECONDS  = 60      # Log stats every 60 seconds
CLEANUP_DAYS      = 60      # Delete records older than 60 days

# Alert thresholds — tune for your deployment
CPU_THRESHOLD     = 90.0    # %
MEMORY_THRESHOLD  = 90.0    # %
DISK_THRESHOLD    = 85.0    # % — lowered from 90: disk at 76% already, early warning
FREQ_THRESHOLD    = 1900.0  # MHz
# PERF-04 FIX: psutil.cpu_percent(interval=1) blocked the calling thread
#   for 1 full second on every 60-second stats cycle. Replaced with
#   interval=None (non-blocking — uses last measurement) primed at
#   startup with a single interval=0.1 call to seed the counter.
#   Impact: removes the guaranteed 1-second stall from every stats cycle.
# CODE-04 FIX: was 70.0°C — RPi 4 throttles at 80°C, sustained 70°C is normal.
# 75°C is a meaningful warning that thermal issues are developing.
TEMP_THRESHOLD    = 75.0    # °C — raised from 70 to reduce false alerts on RPi 4

WATCHDOG_TIMEOUT  = 3600    # seconds — restart if main loop stalls


# ─────────────────────────────────────────────────────────────────
# SOFTWARE WATCHDOG
# ─────────────────────────────────────────────────────────────────
# BUG-02 FIX: original did:
#   import watchdog          ← imports the watchdog library (if installed)
#   watchdog = SoftwareWatchdog(...)  ← immediately overwrites the import
# This causes an ImportError on systems where the watchdog package IS installed,
# and is confusing code regardless. Removed the unused library import entirely.


# ─────────────────────────────────────────────────────────────────
# DATABASE INIT
# ─────────────────────────────────────────────────────────────────
def initialize_database() -> None:
    """
    Create system_stats table if it doesn't exist.
    DB-01 FIX: uses get_connection(DB_TASK_MANAGER) — WAL + PRAGMAs applied.
    CODE-03 FIX: DB_TASK_MANAGER is an absolute path from db_connection.py,
    not the relative "task_manager.db" string that breaks when the script
    is launched from a different working directory.
    """
    conn = get_connection(DB_TASK_MANAGER)
    try:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS system_stats (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp      DATETIME DEFAULT CURRENT_TIMESTAMP,
                cpu_percent    REAL,
                memory_percent REAL,
                disk_percent   REAL,
                cpu_freq       REAL,
                cpu_temp       REAL,
                net_sent       REAL,
                net_recv       REAL
            )
        ''')
        # DB-04: index on timestamp for time-range queries
        conn.execute('''
            CREATE INDEX IF NOT EXISTS idx_system_stats_timestamp
            ON system_stats (timestamp)
        ''')
        conn.commit()
        log.info("task_manager: DB initialised at %s", DB_TASK_MANAGER)
    except Exception as e:
        conn.rollback()
        log.error("task_manager: initialize_database failed — %s", e)
        raise
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────
# STATS COLLECTION — extracted helper (CODE-02 FIX)
# ─────────────────────────────────────────────────────────────────
def get_cpu_temp() -> Optional[float]:
    """
    Read CPU temperature from RPi thermal zone.
    BUG-03 FIX: original used bare except: — caught KeyboardInterrupt,
    SystemExit, and every other exception silently. The only expected
    error is IOError/OSError if the file doesn't exist (non-RPi hardware).
    """
    try:
        with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
            return int(f.read()) / 1000.0
    except (OSError, IOError, ValueError) as e:
        log.debug("get_cpu_temp: not available — %s", e)
        return None


def _get_network_status() -> Dict[str, str]:
    """
    Return the active WAN interface and IPs for eth0 / ppp0.
    Runs in host network namespace via nsenter so Docker isolation is bypassed.
    """
    status = {"active_interface": "unknown", "eth0_ip": "none", "ppp0_ip": "none"}
    _nsenter = ["nsenter", "-t", "1", "-m", "-n", "--"]

    try:
        out = subprocess.run(
            _nsenter + ["ip", "route", "show", "default"],
            capture_output=True, text=True, timeout=5
        ).stdout
        words = out.split()
        if "dev" in words:
            status["active_interface"] = words[words.index("dev") + 1]
    except Exception:
        pass

    for iface in "eth0", "ppp0":
        try:
            out = subprocess.run(
                _nsenter + ["ip", "-4", "addr", "show", iface],
                capture_output=True, text=True, timeout=5
            ).stdout
            for raw in out.splitlines():
                stripped = raw.strip()
                if stripped.startswith("inet "):
                    status[f"{iface}_ip"] = stripped.split()[1].split("/")[0]
                    break
        except Exception:
            pass

    return status


def _collect_stats() -> Dict[str, object]:
    """
    CODE-02 FIX: log_stats() and send_current_stats() originally both
    contained identical psutil calls — 14 duplicated lines.
    Extracted into one helper. Both functions call this instead.

    Returns a dict with all current RPi metrics.
    """
    # PERF-04: interval=None — non-blocking, uses last sample taken by the OS.
    # Replaces interval=1 which blocked this thread for 1 full second every call.
    # The psutil CPU counter is primed at startup so this always returns a valid value.
    cpu    = psutil.cpu_percent(interval=None)
    memory = psutil.virtual_memory().percent
    disk   = psutil.disk_usage('/').percent

    freq     = psutil.cpu_freq()
    cpu_freq = freq.current if freq else None
    cpu_temp = get_cpu_temp()

    net_io   = psutil.net_io_counters()
    net_sent = net_io.bytes_sent / (1024 * 1024)   # MB
    net_recv = net_io.bytes_recv / (1024 * 1024)   # MB

    net_st = _get_network_status()

    return {
        "timestamp":          datetime.now(),
        "cpu":                cpu,
        "memory":             memory,
        "disk":               disk,
        "cpu_freq":           cpu_freq,
        "cpu_temp":           cpu_temp,
        "net_sent":           net_sent,
        "net_recv":           net_recv,
        "active_interface":   net_st["active_interface"],
        "eth0_ip":            net_st["eth0_ip"],
        "ppp0_ip":            net_st["ppp0_ip"],
    }


# ─────────────────────────────────────────────────────────────────
# LOG STATS — every 60 seconds
# ─────────────────────────────────────────────────────────────────
def log_stats() -> None:
    """
    Collect system stats, write to task_manager.db, and send
    an immediate ThingsBoard alert if any threshold is exceeded.

    BUG-04 FIX: original had no try/except around the DB write inside
    `with sqlite3.connect(DB_PATH) as conn:`. A locked DB or disk-full
    condition would raise an unhandled exception and crash the entire
    60-second log cycle, propagating up to the main loop.
    """
    s = _collect_stats()

    # ── Write to local DB ────────────────────────────────────────
    conn = get_connection(DB_TASK_MANAGER)
    try:
        conn.execute('''
            INSERT INTO system_stats (
                timestamp, cpu_percent, memory_percent, disk_percent,
                cpu_freq, cpu_temp, net_sent, net_recv
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            s["timestamp"], s["cpu"], s["memory"], s["disk"],
            s["cpu_freq"], s["cpu_temp"], s["net_sent"], s["net_recv"]
        ))
        conn.commit()
        log.debug(
            "stats: CPU=%.1f%% MEM=%.1f%% DISK=%.1f%% "
            "FREQ=%.0fMHz TEMP=%s°C",
            s["cpu"], s["memory"], s["disk"],
            s["cpu_freq"] or 0,
            f"{s['cpu_temp']:.1f}" if s["cpu_temp"] else "N/A"
        )
    except Exception as e:
        conn.rollback()
        log.error("log_stats: DB write failed — %s", e)
    finally:
        conn.close()

    # ── Threshold alert ──────────────────────────────────────────
    exceeded = (
        s["cpu"]    >= CPU_THRESHOLD    or
        s["memory"] >= MEMORY_THRESHOLD or
        s["disk"]   >= DISK_THRESHOLD   or
        # frequency removed: 2400 MHz is normal RPi 4 speed, not an alert.
        # High freq = healthy. Low freq = throttled due to heat.
        # Temperature already covers this concern.
        (s["cpu_temp"] and s["cpu_temp"] >= TEMP_THRESHOLD)
    )

    if exceeded:
        warning_data = {
            "rpi_alert": {
                "timestamp":         s["timestamp"].isoformat(),
                "CPU":               s["cpu"],
                "Memory":            s["memory"],
                "Disk":              s["disk"],
                "Frequency":         s["cpu_freq"],
                "Temperature":       s["cpu_temp"],
                "Net_Sent_MB":       s["net_sent"],
                "Net_Recv_MB":       s["net_recv"],
                "Active_Interface":  s["active_interface"],
                "eth0_IP":           s["eth0_ip"],
                "ppp0_IP":           s["ppp0_ip"],
            }
        }
        try:
            insert_json_to_db(json.dumps(warning_data))
            log.warning(
                "rpi_alert sent: CPU=%.1f%% MEM=%.1f%% DISK=%.1f%% TEMP=%s°C",
                s["cpu"], s["memory"], s["disk"],
                f"{s['cpu_temp']:.1f}" if s["cpu_temp"] else "N/A"
            )
        except Exception as e:
            log.error("log_stats: alert send failed — %s", e)


# ─────────────────────────────────────────────────────────────────
# SEND CURRENT STATS — every hour
# ─────────────────────────────────────────────────────────────────
def send_current_stats() -> None:
    """
    Send a full RPi health snapshot to ThingsBoard once per hour.
    Uses _collect_stats() — no duplicated psutil calls (CODE-02 fix).
    """
    s = _collect_stats()

    log_data = {
        "rpi_usage": [{
            "timestamp":         s["timestamp"].isoformat(),
            "CPU":               s["cpu"],
            "Memory":            s["memory"],
            "Disk":              s["disk"],
            "Frequency":         s["cpu_freq"],
            "Temperature":       s["cpu_temp"],
            "Net_Sent_MB":       s["net_sent"],
            "Net_Recv_MB":       s["net_recv"],
            "Active_Interface":  s["active_interface"],
            "eth0_IP":           s["eth0_ip"],
            "ppp0_IP":           s["ppp0_ip"],
        }]
    }

    try:
        insert_json_to_db(json.dumps(log_data))
        log.info("send_current_stats: snapshot sent to ThingsBoard")
    except Exception as e:
        log.error("send_current_stats: failed — %s", e)


# ─────────────────────────────────────────────────────────────────
# CLEANUP OLD DATA
# ─────────────────────────────────────────────────────────────────
def cleanup_old_data(days: int = CLEANUP_DAYS) -> None:
    """
    Delete system_stats rows older than `days` days.
    Keeps task_manager.db from growing indefinitely on 24/7 RPi.
    Uses parameterised query — days value is safely bound, not interpolated.
    """
    conn = get_connection(DB_TASK_MANAGER)
    try:
        result = conn.execute(
            "DELETE FROM system_stats WHERE timestamp < datetime('now', ? || ' days')",
            (f"-{days}",)
        )
        conn.commit()
        log.info("cleanup: deleted %d records older than %d days",
                 result.rowcount, days)
    except Exception as e:
        conn.rollback()
        log.error("cleanup_old_data: failed — %s", e)
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s"
    )

    initialize_database()

    # PERF-04: Prime psutil CPU counter so the first interval=None call
    # returns a real value instead of 0.0. The 0.1s sleep here at startup
    # is far better than blocking 1s on every subsequent stats cycle.
    psutil.cpu_percent(interval=0.1)
    log.debug("psutil CPU counter primed")

    # Start watchdog — must be after DB init
    # CQ-01: shared watchdog from watchdog_manager.py
    watchdog_timer = SoftwareWatchdog(
        module_label="RPi_Task_Manager",
        timeout=WATCHDOG_TIMEOUT,
    )

    # Schedule periodic tasks
    schedule.every(1).hours.do(send_current_stats)
    schedule.every(CLEANUP_DAYS).days.do(cleanup_old_data)

    log.info("RPi Task Manager started — logging every %ds", INTERVAL_SECONDS)

    try:
        while True:
            start_time = time.time()

            log_stats()
            schedule.run_pending()
            watchdog_timer.reset()

            elapsed = time.time() - start_time
            sleep_time = max(0, INTERVAL_SECONDS - elapsed)
            time.sleep(sleep_time)

    except KeyboardInterrupt:
        log.info("RPi Task Manager: shutting down")
        watchdog_timer.stop()
