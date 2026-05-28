# database_handler.py
# Dexter HMS — Payload Queue (payloads.db / json_data table)
#
# Changes from original:
#   BUG-01 : File contained 3 classes (DatabaseHandler,
#            DatabaseHandlerOperationalError,
#            DatabaseHandlerOperationalErrorDatabaseClose) — three iterative
#            drafts all left live in one file. Callers importing
#            'DatabaseHandler' silently used the broken first draft, not the
#            latest. Consolidated into one class: DatabaseHandler.
#   BUG-02 : self.connect() called INSIDE 'with self.conn:' blocks in
#            DatabaseHandlerOperationalError and
#            DatabaseHandlerOperationalErrorDatabaseClose.
#            Every call to insert_json/mark_as_sent/etc opened a SECOND
#            connection while the first was still inside its context manager —
#            leaked one file handle per call. On an RPi with hundreds of
#            events/hour this exhausts OS file handles silently.
#   BUG-03 : 'raise' followed by unreachable 'pass' in every except block
#            of DatabaseHandler — dead code throughout.
#   BUG-04 : 'except sqlite3.Error' followed by 'except sqlite3.OperationalError'
#            in same try block — OperationalError is a subclass of Error, so
#            the second except is unreachable. Always caught by the first.
#   BUG-05 : persistent self.conn — connection stored as instance attribute.
#            Any exception between connect() and close() leaves handle open.
#   BUG-06 : is_child_ready() returned True when no pending rows exist
#            (i.e. True = "nothing to do"). Semantics were inverted —
#            callers checking 'if db.is_child_ready(): process()' would
#            never process anything. Renamed to has_pending() → True means
#            work exists.
#   BUG-07 : backup_database() used shutil.copyfile() on a live database
#            with no WAL checkpoint — could copy mid-write and produce a
#            corrupt backup.
#   DB-01  : self.connect() rolled its own WAL PRAGMA instead of using
#            get_connection() — inconsistent connection settings across
#            the codebase. All connections now via get_connection(DB_PAYLOADS).
#   CODE-01: Relative default path 'payloads.db' → DB_PAYLOADS absolute path.
#   CODE-02: No threading.Lock() on a DB accessed by multiple threads.

import os
import time
import shutil
import logging
import threading

from db_connection import get_connection, DB_PAYLOADS

log   = logging.getLogger(__name__)
_lock = threading.Lock()


class DatabaseHandler:
    """
    Payload queue backed by payloads.db / json_data table.

    Stores outbound JSON payloads with a status of 'pending', 'sent', or
    'failed'. The MQTT publisher reads pending rows, publishes them, then
    marks them sent or failed.

    DB-01 / BUG-05 FIX: no persistent self.conn. Every method opens a
    fresh connection via get_connection(), uses it, and closes it in
    finally. This is safe for multi-threaded access and immune to
    connection-leak crashes.
    """

    def __init__(self, db_path: str = DB_PAYLOADS):
        # CODE-01 FIX: absolute path from db_connection constants
        self.db_path = db_path
        self._ensure_table()

    # ─────────────────────────────────────────────────────────────
    # TABLE INIT
    # ─────────────────────────────────────────────────────────────
    def _ensure_table(self) -> None:
        """Create json_data table if it doesn't exist. Safe to call at startup."""
        with _lock:
            conn = get_connection(self.db_path)
            try:
                conn.execute('''
                    CREATE TABLE IF NOT EXISTS json_data (
                        id       INTEGER PRIMARY KEY AUTOINCREMENT,
                        json_str TEXT    NOT NULL,
                        status   TEXT    NOT NULL DEFAULT "pending"
                    )
                ''')
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_json_data_status "
                    "ON json_data (status)"
                )
                conn.commit()
                log.info("DatabaseHandler: table ready at %s", self.db_path)
            except Exception as e:
                conn.rollback()
                log.error("DatabaseHandler: _ensure_table failed — %s", e)
                raise
            finally:
                conn.close()   # BUG-05 FIX: always closed

    # ─────────────────────────────────────────────────────────────
    # STARTUP CLEANUP
    # ─────────────────────────────────────────────────────────────
    # Zone hardware event log_types — these are preserved across restarts.
    # All other pending rows (heartbeats, system_on, NA etc.) are discarded.
    ZONE_EVENT_LOG_TYPES: set = {
        # BAS/IAS/FAS intrusion
        "intrusion_alarm_system_activate",    "intrusion_alarm_system_activation_restored",
        "intrusion_alarm_system_on",          "intrusion_alarm_system_off",
        "intrusion_alarm_system_fault",       "intrusion_alarm_system_fault_condition_restored",
        # FAS fire
        "fire_alarm_system_activate",         "fire_alarm_system_activation_restored",
        "fire_alarm_system_on",               "fire_alarm_system_off",
        "fire_alarm_system_fault",            "fire_alarm_system_fault_condition_restored",
        # IAS integrated
        "integrated_alarm_system_activate",   "integrated_alarm_system_activation_restored",
        "integrated_alarm_system_on",         "integrated_alarm_system_off",
        "integrated_alarm_system_fault",      "integrated_alarm_system_fault_condition_restored",
        # BACS access control
        "access_control_door_open",           "access_control_door_close",
        "access_control_system_on",           "access_control_system_off",
        "access_control_system_tamper",       "access_control_system_tamper_restored",
        # TIME_LOCK
        "time_lock_door_open",                "time_lock_door_close",
        "time_lock_system_on",                "time_lock_system_off",
        "time_lock_tamper",                   "time_lock_tamper_restored",
        # CCTV
        "camera_connection_established",      "camera_disconnect",
        "camera_tampered",                    "camera_tampered_restored",
        "dvr_nvr_on",                         "dvr_nvr_off",
        "hdd_error",                          "hdd_error_restored",
        # Power / mains hardware
        "mains_on",    "battery_on",    "battery_reverse", "battery_reverse_restore",
        "battery_low", "battery_low_restore", "power_off", "power_cut",
    }

    def startup_cleanup(self) -> int:
        """
        Selectively expire stale pending rows at boot time.

        KEPT   — zone/hardware event rows (mux state changes, alarms, power).
                 These represent real physical events that happened while
                 the network was down and must still reach ThingsBoard.
        EXPIRED — everything else: heartbeats, system_on, NA, system_status,
                 panel_sl_no, firmware version, etc.
                 These are stale startup/periodic data from the previous
                 session and would appear as duplicates.

        Call ONCE at startup before inserting any new events.
        Returns: number of rows marked as expired.
        """
        import json as _json
        expired = 0
        kept    = 0

        with _lock:
            conn = get_connection(self.db_path)
            try:
                rows = conn.execute(
                    "SELECT id, json_str FROM json_data WHERE status = 'pending'"
                ).fetchall()

                for row in rows:
                    row_id   = row["id"]
                    json_str = row["json_str"]
                    keep     = False

                    try:
                        data     = _json.loads(json_str)
                        log_type = data.get("log_type", "")

                        # log_type may itself be a JSON string (dict payload)
                        if isinstance(log_type, str):
                            keep = log_type in self.ZONE_EVENT_LOG_TYPES
                        # dict/list payloads (system_status, panel_sl_no) → discard
                    except Exception:
                        keep = False   # malformed JSON → discard

                    if not keep:
                        conn.execute(
                            "UPDATE json_data SET status = 'expired' WHERE id = ?",
                            (row_id,)
                        )
                        expired += 1
                    else:
                        kept += 1

                conn.commit()
                log.info(
                    "[startup_cleanup] kept %d zone events | "
                    "expired %d stale rows (heartbeats/status/startup)",
                    kept, expired
                )
                return expired

            except Exception as e:
                conn.rollback()
                log.error("DatabaseHandler: startup_cleanup failed — %s", e)
                return 0
            finally:
                conn.close()

    # ─────────────────────────────────────────────────────────────
    # INSERT
    # ─────────────────────────────────────────────────────────────
    def insert_json(self, json_str: str) -> bool:
        """
        Insert a JSON payload with status='pending'.

        BUG-02 FIX: original called self.connect() inside 'with self.conn:'
        — opened a second connection while the first was inside its context
        manager. Leaked one file handle per insert.
        Fixed: get_connection() opens a fresh connection, used and closed here.

        Returns True on success, False on failure.
        """
        with _lock:
            conn = get_connection(self.db_path)
            try:
                conn.execute(
                    "INSERT INTO json_data (json_str, status) VALUES (?, ?)",
                    (json_str, "pending")
                )
                conn.commit()
                return True
            except Exception as e:
                conn.rollback()
                log.error("DatabaseHandler: insert_json failed — %s", e)
                return False
            finally:
                conn.close()

    # ─────────────────────────────────────────────────────────────
    # QUERY
    # ─────────────────────────────────────────────────────────────
    def has_pending(self) -> bool:
        """
        Return True if at least one pending payload exists, False otherwise.

        BUG-06 FIX: original method was named is_child_ready() and returned
        True when NO pending rows existed (row is None). The semantics were
        inverted — callers doing 'if db.is_child_ready(): process_next()'
        would process nothing because is_child_ready() returned True only
        when the queue was empty.
        Renamed to has_pending(): True = work exists, False = queue empty.
        """
        with _lock:
            conn = get_connection(self.db_path)
            try:
                row = conn.execute(
                    "SELECT id FROM json_data WHERE status = 'pending' LIMIT 1"
                ).fetchone()
                return row is not None
            except Exception as e:
                log.error("DatabaseHandler: has_pending failed — %s", e)
                return False
            finally:
                conn.close()

    # ── Backward-compatibility aliases ───────────────────────────────────
    # DB fix package renamed is_child_ready() -> has_pending() and fixed
    # the inverted logic (BUG-06). MainProgram still calls the old names.
    # These aliases preserve call-site compatibility without changing callers.

    def is_child_ready(self) -> bool:
        """Alias for has_pending() — backward compatibility with MainProgram."""
        return self.has_pending()

    def set_child_ready(self) -> None:
        """No-op — child-ready state is now derived from DB pending rows."""
        pass

    def clear_child_ready(self) -> None:
        """No-op — child-ready state is now derived from DB pending rows."""
        pass

    def get_pending(self) -> tuple:
        """
        Retrieve the oldest pending payload.

        Returns (row_id, json_str) or (None, None) if queue is empty.
        """
        with _lock:
            conn = get_connection(self.db_path)
            try:
                row = conn.execute(
                    "SELECT id, json_str FROM json_data "
                    "WHERE status = 'pending' ORDER BY id ASC LIMIT 1"
                ).fetchone()
                if row:
                    return row["id"], row["json_str"]
                return None, None
            except Exception as e:
                log.error("DatabaseHandler: get_pending failed — %s", e)
                return None, None
            finally:
                conn.close()

    # Keep old name as alias so existing callers don't break immediately
    def get_json_string(self) -> tuple:
        return self.get_pending()

    # ─────────────────────────────────────────────────────────────
    # STATUS UPDATES
    # ─────────────────────────────────────────────────────────────
    def _set_status(self, row_id: int, status: str) -> bool:
        """
        Internal: update status for a row.

        BUG-04 FIX: original had 'except sqlite3.Error' then
        'except sqlite3.OperationalError' — OperationalError is a subclass
        of Error, so the second except was unreachable. Consolidated to
        single 'except Exception'.

        BUG-03 FIX: no 'raise\n        pass' dead code blocks.

        The old retry-on-lock loop is unnecessary now that get_connection()
        applies busy_timeout=5000ms — SQLite handles lock waits internally.
        """
        with _lock:
            conn = get_connection(self.db_path)
            try:
                conn.execute(
                    "UPDATE json_data SET status = ? WHERE id = ?",
                    (status, row_id)
                )
                conn.commit()
                log.debug("DatabaseHandler: row %d → %s", row_id, status)
                return True
            except Exception as e:
                conn.rollback()
                log.error(
                    "DatabaseHandler: _set_status(%d, %s) failed — %s",
                    row_id, status, e
                )
                return False
            finally:
                conn.close()

    def mark_as_sent(self, row_id: int) -> bool:
        return self._set_status(row_id, "sent")

    def mark_as_failed(self, row_id: int) -> bool:
        return self._set_status(row_id, "failed")

    def reset_status(self, row_id: int) -> bool:
        return self._set_status(row_id, "pending")

    # ─────────────────────────────────────────────────────────────
    # STATS
    # ─────────────────────────────────────────────────────────────
    def get_stats(self) -> dict:
        """Return count of rows by status. Useful for health checks."""
        with _lock:
            conn = get_connection(self.db_path)
            try:
                rows = conn.execute(
                    "SELECT status, COUNT(*) FROM json_data GROUP BY status"
                ).fetchall()
                return {row["status"]: row[1] for row in rows}
            except Exception as e:
                log.error("DatabaseHandler: get_stats failed — %s", e)
                return {}
            finally:
                conn.close()

    # ─────────────────────────────────────────────────────────────
    # BACKUP / RESTORE
    # ─────────────────────────────────────────────────────────────
    def backup_database(self, backup_path: str = None) -> bool:
        """
        Create a safe backup using SQLite's online backup API.

        BUG-07 FIX: original used shutil.copyfile() on a live database.
        With WAL mode, the database can have unflushed pages in the WAL
        file — a raw file copy can capture an inconsistent state and
        produce a corrupt backup.

        Fixed: sqlite3.Connection.backup() uses the official SQLite online
        backup API which is safe for live databases under concurrent writes.

        Returns True on success, False on failure.
        """
        if backup_path is None:
            backup_path = self.db_path + ".backup"

        src_conn = get_connection(self.db_path)
        dst_conn = None
        try:
            dst_conn = get_connection(backup_path)
            src_conn.backup(dst_conn)
            log.info("DatabaseHandler: backup created at %s", backup_path)
            return True
        except Exception as e:
            log.error("DatabaseHandler: backup_database failed — %s", e)
            return False
        finally:
            src_conn.close()
            if dst_conn:
                dst_conn.close()

    def restore_database(self, backup_path: str = None) -> bool:
        """
        Restore database from a backup created by backup_database().
        Uses sqlite3 online backup API (safe, consistent).
        """
        if backup_path is None:
            backup_path = self.db_path + ".backup"

        if not os.path.exists(backup_path):
            log.error("DatabaseHandler: restore — backup not found: %s",
                      backup_path)
            return False

        src_conn = get_connection(backup_path)
        dst_conn = None
        try:
            dst_conn = get_connection(self.db_path)
            src_conn.backup(dst_conn)
            log.info("DatabaseHandler: restored from %s", backup_path)
            return True
        except Exception as e:
            log.error("DatabaseHandler: restore_database failed — %s", e)
            return False
        finally:
            src_conn.close()
            if dst_conn:
                dst_conn.close()

    # Legacy close() — no-op now (no persistent connection), kept for
    # backward compatibility with any callers that call db.close()
    def close(self) -> None:
        pass