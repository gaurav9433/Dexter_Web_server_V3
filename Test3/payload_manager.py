#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
payload_manager.py — Dexter HMS Payload Backlog Manager
v2 — Updated to use db_connection.get_connection() and precise
     heartbeat classification matching heartbeat_manager.py payloads.

Solves the "huge data flood after 2+ days offline" problem.

THREE mechanisms:
  1. STARTUP PURGE   — Delete all heartbeat/status rows from payloads.db
                       on publisher boot. Stale heartbeats are useless —
                       ThingsBoard only needs the latest per device type.

  2. OFFLINE CAP     — While network is down, cap payloads.db at MAX_PENDING
                       rows. When cap is reached, evict the oldest heartbeat
                       row first. If no heartbeats remain, evict oldest event.
                       Keeps payloads.db small during long outages.

  3. RECONNECT RATE  — On reconnect, publisher sends at MAX_SEND_PER_MIN
                       messages/minute instead of full speed. Protects
                       ThingsBoard from flood.

Heartbeat classification — matches heartbeat_manager.py exactly:
  DISCARD (stale):
    - Dict with any "heartbeat*" key  → periodic burst / startup / online / offline
    - Dict with system_on/battery_voltage etc as KEY (no log_type) → sendData2TBSystemStatus
    - log_type == "NA"                → startup placeholder
    - log_type starts with "heartbeat"→ sendData2TB individual heartbeat

  KEEP (real events):
    - log_type == "system_on"         → panel power-on event
    - log_type == "mains_on"          → mains power event
    - log_type == "battery_on"        → battery event
    - log_type == any alarm/fault/zone→ zone events
"""

import json
import time
import logging
import threading

from db_connection import get_connection, DB_PAYLOADS

log = logging.getLogger(__name__)

# ── Configuration ──────────────────────────────────────────────────────────
# Max pending rows in payloads.db while offline.
# 2 days × ~100 real events/day = 200 rows needed.
# 500 gives comfortable headroom while staying small.
MAX_PENDING = 500

# Rate limit after reconnect — messages per minute sent to ThingsBoard.
# 500-row backlog at 60/min → clears in ~8 minutes. Acceptable.
MAX_SEND_PER_MIN = 60

# ── Heartbeat classifiers (derived from heartbeat_manager.py) ─────────────
# Keys used by raw_send_fn (periodic burst, startup, online/offline HB)
_HEARTBEAT_DICT_KEYS = {
    "heartbeat",
    "heartbeat_BAS",            "heartbeat_BAS_offline",
    "heartbeat_FAS",            "heartbeat_FAS_offline",
    "heartbeat_CCTV",           "heartbeat_CCTV_offline",
    "heartbeat_IAS",            "heartbeat_IAS_offline",
    "heartbeat_time_lock",      "heartbeat_time_lock_offline",
    "heartbeat_access_control", "heartbeat_access_control_offline",
}

# Keys used ONLY in sendData2TBSystemStatus (no log_type key present).
# TEL-FIX-4: corrected key names to match the flat statusbox_* payload produced
# by the fixed sendData2TBSystemStatus(). The old set used bare names like
# "system_on", "battery_voltage" which never appeared as top-level keys —
# they were nested under "system_status" wrapper (now removed). With the flat
# fix, the actual top-level keys are "statusbox_system_on" etc., so _is_heartbeat()
# Case 2 now correctly identifies and discards stale system-status payloads.
_SYSTEM_STATUS_KEYS = {
    "statusbox_system_on", "statusbox_system_healthy", "statusbox_mains_on",
    "statusbox_battery_reverse", "statusbox_battery_low", "statusbox_sos_status",
    "statusbox_network", "statusbox_no_of_connected_device",
    # flat voltage/current keys from sendData2TBbattery_voltage / smps_voltage / system_current
    "battery_voltage", "ac_voltage", "system_current",
}

# log_type values that are heartbeat or placeholder — DISCARD
# Note: "system_on", "mains_on", "battery_on" as log_type are REAL EVENTS — keep them
_HEARTBEAT_LOG_TYPES = {
    "NA",
    "heartbeat_BAS",            "heartbeat_BAS_offline",
    "heartbeat_FAS",            "heartbeat_FAS_offline",
    "heartbeat_CCTV",           "heartbeat_CCTV_offline",
    "heartbeat_IAS",            "heartbeat_IAS_offline",
    "heartbeat_time_lock",      "heartbeat_time_lock_offline",
    "heartbeat_access_control", "heartbeat_access_control_offline",
    "heartbeat_IBAS",
}


def _is_heartbeat(json_str: str) -> bool:
    """
    Return True if this payload is a heartbeat or system-status row
    that can safely be discarded when the backlog is too large.

    Three cases matched (see module docstring for full reasoning):
      1. Dict containing any heartbeat* key (raw_send_fn path)
      2. Dict with system_on/battery_voltage etc as keys, no log_type
         (sendData2TBSystemStatus path)
      3. log_type field starts with "heartbeat" or equals "NA"
         (sendData2TB individual path)

    Returns False (KEEP) for real events:
      log_type = system_on / mains_on / battery_on / intrusion_* / fire_* etc.
    """
    try:
        d = json.loads(json_str)

        # Case 1: heartbeat dict key present (periodic burst / startup / on/offline)
        if any(k in _HEARTBEAT_DICT_KEYS for k in d):
            return True

        log_type = d.get("log_type")

        # Case 2: sendData2TBSystemStatus — has status keys but NO log_type
        if log_type is None and any(k in _SYSTEM_STATUS_KEYS for k in d):
            return True

        # Case 3: log_type is a known heartbeat value or NA placeholder
        if isinstance(log_type, str) and log_type in _HEARTBEAT_LOG_TYPES:
            return True

        return False

    except (json.JSONDecodeError, TypeError, AttributeError):
        return False   # unknown format — keep it


# ── Shared insert lock (used by insert_with_cap across processes) ──────────
_insert_lock = threading.Lock()


def insert_with_cap(json_str: str) -> None:
    """
    Standalone function — use in TLChronosProMAIN_391.py:send_json_to_child()
    instead of db_handler.insert_json().

    Enforces MAX_PENDING cap. Eviction order:
      1. Oldest heartbeat/status row (expendable)
      2. Oldest event row (only if no heartbeats remain)

    Uses db_connection.get_connection(DB_PAYLOADS) for WAL + PRAGMAs.
    """
    with _insert_lock:
        try:
            conn = get_connection(DB_PAYLOADS)
            try:
                count = conn.execute(
                    "SELECT COUNT(*) FROM json_data WHERE status = 'pending'"
                ).fetchone()[0]

                if count >= MAX_PENDING:
                    # Scan oldest 50 rows — find first heartbeat to evict
                    rows = conn.execute(
                        "SELECT id, json_str FROM json_data "
                        "WHERE status = 'pending' ORDER BY id ASC LIMIT 50"
                    ).fetchall()

                    evicted = False
                    for row in rows:
                        row_id = row[0]
                        js     = row[1]
                        if _is_heartbeat(js):
                            conn.execute(
                                "DELETE FROM json_data WHERE id = ?", (row_id,)
                            )
                            conn.commit()
                            evicted = True
                            log.debug(
                                "[PayloadManager] cap=%d — evicted heartbeat id=%d",
                                MAX_PENDING, row_id
                            )
                            break

                    if not evicted:
                        # No heartbeats to evict — drop oldest event row
                        row = conn.execute(
                            "SELECT id FROM json_data "
                            "WHERE status = 'pending' ORDER BY id ASC LIMIT 1"
                        ).fetchone()
                        if row:
                            conn.execute(
                                "DELETE FROM json_data WHERE id = ?", (row[0],)
                            )
                            conn.commit()
                            log.warning(
                                "[PayloadManager] cap=%d, no heartbeats — "
                                "evicted oldest event id=%d", MAX_PENDING, row[0]
                            )

                conn.execute(
                    "INSERT INTO json_data (json_str, status) VALUES (?, 'pending')",
                    (json_str,)
                )
                conn.commit()

            finally:
                conn.close()

        except Exception as e:
            log.error("[PayloadManager] insert_with_cap failed: %s", e)


# ── PayloadManager class — used in thingsboard_mqtt_publisher.py ───────────
class PayloadManager:
    """
    Wraps DatabaseHandler in the publisher process.
    Adds startup purge and rate-limited get_next().
    """

    def __init__(self, db_handler):
        self._db         = db_handler
        self._send_times = []           # monotonic timestamps of recent sends
        self._lock       = threading.Lock()

    # Heartbeat rows younger than this (seconds) are kept on startup purge.
    # Protects rows generated during a GSM failover window from being wiped
    # when dexter-mqtt restarts for ethernet switchover.
    _PURGE_AGE_THRESHOLD = 300   # 5 minutes

    def startup_purge(self) -> int:
        """
        Delete stale heartbeat/system-status rows from payloads.db.
        Only rows older than _PURGE_AGE_THRESHOLD seconds are deleted — rows
        generated during a recent GSM failover are preserved and sent normally.
        Call ONCE at publisher startup, before the run loop.
        Returns number of rows deleted.
        """
        deleted = 0
        try:
            conn = get_connection(DB_PAYLOADS)
            try:
                cutoff = int(time.time()) - self._PURGE_AGE_THRESHOLD
                # created_at column added by schema migration 004. Fall back to
                # purging all pending heartbeats if the column doesn't exist yet.
                try:
                    rows = conn.execute(
                        "SELECT id, json_str FROM json_data "
                        "WHERE status = 'pending' AND created_at < ?",
                        (cutoff,)
                    ).fetchall()
                except Exception:
                    rows = conn.execute(
                        "SELECT id, json_str FROM json_data WHERE status = 'pending'"
                    ).fetchall()

                ids_to_delete = [row[0] for row in rows if _is_heartbeat(row[1])]

                if ids_to_delete:
                    conn.execute(
                        "DELETE FROM json_data WHERE id IN ({})".format(
                            ",".join("?" * len(ids_to_delete))
                        ),
                        ids_to_delete
                    )
                    conn.commit()
                    deleted = len(ids_to_delete)
                    log.info(
                        "[PayloadManager] startup_purge: deleted %d stale "
                        "heartbeat/status rows older than %ds from payloads.db",
                        deleted, self._PURGE_AGE_THRESHOLD
                    )
                else:
                    log.info(
                        "[PayloadManager] startup_purge: payloads.db clean — "
                        "no stale heartbeat rows older than %ds",
                        self._PURGE_AGE_THRESHOLD
                    )
            finally:
                conn.close()
        except Exception as e:
            log.error("[PayloadManager] startup_purge failed: %s", e)
        return deleted

    def get_next(self):
        """
        Rate-limited replacement for db_handler.get_json_string().
        Returns (row_id, json_str) or (None, None).
        Blocks briefly if MAX_SEND_PER_MIN is exceeded.
        """
        self._enforce_rate_limit()
        row_id, json_str = self._db.get_json_string()
        if json_str is not None:
            with self._lock:
                self._send_times.append(time.monotonic())
        return row_id, json_str

    def _enforce_rate_limit(self) -> None:
        """Sleep until sends in the last 60s are below MAX_SEND_PER_MIN."""
        while True:
            now    = time.monotonic()
            cutoff = now - 60.0
            with self._lock:
                self._send_times = [t for t in self._send_times if t > cutoff]
                count = len(self._send_times)

            if count < MAX_SEND_PER_MIN:
                return

            # Oldest send in window — wait until it drops out
            with self._lock:
                oldest = self._send_times[0] if self._send_times else now
            sleep_for = 60.0 - (now - oldest) + 0.1
            log.info(
                "[PayloadManager] rate limit %d/min — waiting %.1fs",
                MAX_SEND_PER_MIN, sleep_for
            )
            time.sleep(max(0.1, sleep_for))

    def pending_count(self) -> int:
        """Return number of pending rows in payloads.db."""
        try:
            conn = get_connection(DB_PAYLOADS)
            try:
                return conn.execute(
                    "SELECT COUNT(*) FROM json_data WHERE status = 'pending'"
                ).fetchone()[0]
            finally:
                conn.close()
        except Exception:
            return -1
