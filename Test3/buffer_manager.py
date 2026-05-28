# buffer_manager.py
# Dexter HMS — Hardened Buffer Manager
# Fixes: DB-01 (WAL), DB-03 (Buffer Cap), DB-04 (Index),
#        Thread Safety, Error Handling, TTL Purge, Stats API

"""
buffer_manager.py
Dexter HMS — Bounded upload buffer for ThingsBoard telemetry

Responsibilities:
  - Queues telemetry events in buffer.db (SQLite) for cloud delivery
  - Enforces MAX_BUFFER_ROWS = 50,000 hard cap — oldest events auto-purged
  - TTL_DAYS = 7 purge on events older than 7 days regardless of delivery status
  - Tracks retry_count and sent_at per event for delivery monitoring
  - Provides get_stats() for ThingsBoard buffer health telemetry

Key classes:
  - BoundedBufferManager — thread-safe, capped, TTL-aware queue

Dependencies:
  - db_connection.py — WAL SQLite connections
Author: Seple Novaedge Pvt. Ltd.
"""

import sqlite3
import threading
import logging
import time
from typing import Dict, List, Optional, Tuple

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# CONSTANTS — change here only, affects everywhere
# ─────────────────────────────────────────────
DB_PATH          = "/home/pi/Test3/buffer.db"
MAX_BUFFER_ROWS  = 50_000   # Hard cap — oldest purged when hit
WARN_BUFFER_ROWS = 40_000   # Warning threshold logged to syslog
TTL_DAYS         = 7        # Events older than 7 days auto-deleted
BATCH_SIZE       = 100      # Rows fetched per upload batch

# ─────────────────────────────────────────────
# MODULE-LEVEL LOCK — one lock for entire module
# ─────────────────────────────────────────────
_lock = threading.Lock()


# ─────────────────────────────────────────────
# INTERNAL — apply all PRAGMAs on every connection
# ─────────────────────────────────────────────
def _get_connection(db_path: str) -> sqlite3.Connection:
    """
    Opens a SQLite connection with all performance and
    safety PRAGMAs applied. Replaces bare sqlite3.connect().
    """
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")       # DB-01: readers never block writers
    conn.execute("PRAGMA foreign_keys=ON;")        # DB-02: FK enforcement
    conn.execute("PRAGMA synchronous=NORMAL;")     # Safe + faster with WAL
    conn.execute("PRAGMA cache_size=-8000;")       # 8 MB page cache
    conn.execute("PRAGMA mmap_size=67108864;")     # 64 MB memory-mapped I/O
    conn.execute("PRAGMA busy_timeout=5000;")      # Wait 5s on lock before error
    conn.execute("PRAGMA wal_autocheckpoint=1000;")# Checkpoint at ~4 MB WAL
    return conn


# ─────────────────────────────────────────────
# INIT — create table + index on fresh DB
# ─────────────────────────────────────────────
def init_db(db_path: str = DB_PATH) -> None:
    """
    Creates buffer table with delivery-tracking columns
    and an index on (status, created_at) for fast batch fetch.
    Safe to call on every startup — uses IF NOT EXISTS.
    """
    with _lock:
        conn = _get_connection(db_path)
        try:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS buffer (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    json_object TEXT    NOT NULL,
                    status      TEXT    NOT NULL DEFAULT 'pending',
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    created_at  INTEGER NOT NULL DEFAULT (strftime('%s','now')),
                    sent_at     INTEGER
                )
            ''')
            # DB-04: Index — fast batch fetch of pending rows in insert order
            conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_buffer_status_created
                ON buffer (status, created_at)
            ''')
            conn.commit()
            log.info("buffer_manager: DB initialised at %s", db_path)
        except Exception as e:
            conn.rollback()
            log.error("buffer_manager: init_db failed — %s", e)
            raise
        finally:
            conn.close()


# ─────────────────────────────────────────────
# INTERNAL HELPERS
# ─────────────────────────────────────────────
def _get_row_count(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COUNT(*) FROM buffer").fetchone()
    return row[0] if row else 0


def _purge_oldest(conn: sqlite3.Connection, n: int) -> int:
    """Delete the n oldest rows to make space when cap is hit."""
    result = conn.execute('''
        DELETE FROM buffer WHERE id IN (
            SELECT id FROM buffer ORDER BY created_at ASC LIMIT ?
        )
    ''', (n,))
    return result.rowcount


def _purge_ttl(conn: sqlite3.Connection) -> int:
    """Delete rows older than TTL_DAYS regardless of status."""
    cutoff = int(time.time()) - (TTL_DAYS * 86400)
    result = conn.execute(
        "DELETE FROM buffer WHERE created_at < ?", (cutoff,)
    )
    return result.rowcount


# ─────────────────────────────────────────────
# PUBLIC API
# ─────────────────────────────────────────────
def insert_json_to_db(json_data: str, db_path: str = DB_PATH) -> bool:
    """
    Insert one JSON payload into the buffer.

    - Enforces MAX_BUFFER_ROWS hard cap (DB-03).
      If cap is hit, oldest rows are purged to make room.
      Most recent events are always preserved.
    - Logs a warning when approaching WARN_BUFFER_ROWS.
    - Thread-safe via module-level lock.

    Returns True on success, False on failure.
    """
    with _lock:
        conn = _get_connection(db_path)
        try:
            count = _get_row_count(conn)

            if count >= MAX_BUFFER_ROWS:
                # Purge oldest to stay within cap — never block, never raise
                purged = _purge_oldest(conn, count - MAX_BUFFER_ROWS + 1)
                log.warning(
                    "buffer_manager: cap hit (%d rows). Purged %d oldest events.",
                    count, purged
                )
            elif count >= WARN_BUFFER_ROWS:
                log.warning(
                    "buffer_manager: buffer near cap — %d / %d rows (%.1f%%)",
                    count, MAX_BUFFER_ROWS, count / MAX_BUFFER_ROWS * 100
                )

            conn.execute(
                "INSERT INTO buffer (json_object) VALUES (?)",
                (json_data,)
            )
            conn.commit()
            return True

        except Exception as e:
            conn.rollback()
            log.error("buffer_manager: insert failed — %s", e)
            return False
        finally:
            conn.close()


def get_and_delete_json_from_db(db_path: str = DB_PATH) -> Optional[str]:
    """
    Retrieve and delete the oldest pending record.
    Used by the MQTT publisher for one-at-a-time delivery.
    Returns the JSON string, or None if buffer is empty.
    """
    with _lock:
        conn = _get_connection(db_path)
        try:
            row = conn.execute(
                "SELECT id, json_object FROM buffer WHERE status='pending' "
                "ORDER BY created_at ASC LIMIT 1"
            ).fetchone()

            if row:
                conn.execute("DELETE FROM buffer WHERE id=?", (row["id"],))
                conn.commit()
                return row["json_object"]
            return None

        except Exception as e:
            conn.rollback()
            log.error("buffer_manager: get_and_delete failed — %s", e)
            return None
        finally:
            conn.close()


def get_batch(batch_size: int = BATCH_SIZE,
              db_path: str = DB_PATH) -> List[Tuple[int, str]]:
    """
    Fetch up to batch_size pending rows without deleting them.
    Use mark_sent() / mark_failed() after upload attempt.
    Returns list of (id, json_object) tuples.
    """
    with _lock:
        conn = _get_connection(db_path)
        try:
            rows = conn.execute('''
                SELECT id, json_object FROM buffer
                WHERE status = 'pending'
                ORDER BY created_at ASC
                LIMIT ?
            ''', (batch_size,)).fetchall()
            return [(r["id"], r["json_object"]) for r in rows]
        except Exception as e:
            log.error("buffer_manager: get_batch failed — %s", e)
            return []
        finally:
            conn.close()


def mark_sent(row_ids: List[int], db_path: str = DB_PATH) -> None:
    """Mark rows as successfully delivered and record sent timestamp."""
    if not row_ids:
        return
    with _lock:
        conn = _get_connection(db_path)
        try:
            placeholders = ",".join("?" * len(row_ids))
            conn.execute(f'''
                UPDATE buffer
                SET status='sent', sent_at=strftime('%s','now')
                WHERE id IN ({placeholders})
            ''', row_ids)
            conn.commit()
        except Exception as e:
            conn.rollback()
            log.error("buffer_manager: mark_sent failed — %s", e)
        finally:
            conn.close()


def mark_failed(row_ids: List[int], db_path: str = DB_PATH) -> None:
    """Increment retry_count on failed delivery rows."""
    if not row_ids:
        return
    with _lock:
        conn = _get_connection(db_path)
        try:
            placeholders = ",".join("?" * len(row_ids))
            conn.execute(f'''
                UPDATE buffer
                SET retry_count = retry_count + 1
                WHERE id IN ({placeholders})
            ''', row_ids)
            conn.commit()
        except Exception as e:
            conn.rollback()
            log.error("buffer_manager: mark_failed failed — %s", e)
        finally:
            conn.close()


def purge_ttl(db_path: str = DB_PATH) -> int:
    """
    Delete all rows older than TTL_DAYS.
    Call this once per day from the main scheduler.
    Returns number of rows deleted.
    """
    with _lock:
        conn = _get_connection(db_path)
        try:
            deleted = _purge_ttl(conn)
            conn.commit()
            if deleted:
                log.info("buffer_manager: TTL purge deleted %d old rows", deleted)
            return deleted
        except Exception as e:
            conn.rollback()
            log.error("buffer_manager: purge_ttl failed — %s", e)
            return 0
        finally:
            conn.close()


def get_stats(db_path: str = DB_PATH) -> Dict[str, int]:
    """
    Returns buffer health metrics.
    Publish this to ThingsBoard telemetry for remote monitoring.

    Example output:
    {
        'buffer_total': 1200,
        'buffer_pending': 950,
        'buffer_sent': 250,
        'buffer_pct': 2.4,
        'oldest_pending_age_hours': 3.2
    }
    """
    with _lock:
        conn = _get_connection(db_path)
        try:
            total   = _get_row_count(conn)
            pending = conn.execute(
                "SELECT COUNT(*) FROM buffer WHERE status='pending'"
            ).fetchone()[0]
            sent    = conn.execute(
                "SELECT COUNT(*) FROM buffer WHERE status='sent'"
            ).fetchone()[0]

            oldest_row = conn.execute(
                "SELECT MIN(created_at) FROM buffer WHERE status='pending'"
            ).fetchone()[0]

            age_hours = 0.0
            if oldest_row:
                age_hours = round((time.time() - oldest_row) / 3600, 1)

            return {
                "buffer_total":             total,
                "buffer_pending":           pending,
                "buffer_sent":              sent,
                "buffer_pct":               round(total / MAX_BUFFER_ROWS * 100, 1),
                "buffer_cap":               MAX_BUFFER_ROWS,
                "oldest_pending_age_hours": age_hours,
            }
        except Exception as e:
            log.error("buffer_manager: get_stats failed — %s", e)
            return {}
        finally:
            conn.close()