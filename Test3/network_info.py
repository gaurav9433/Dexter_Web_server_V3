# network_info.py
# Dexter HMS — Network Status Monitor
#
# Periodically records IP address, geolocation, timestamp and
# connectivity status to network_info.db.
#
# This file is the single owner of network_info.db.
# All other modules that need network status should import this class.
#
# Changes from original (network_info.py + second module merged):
#   BUG-01 : bare sqlite3.connect() → get_connection(DB_NETWORK_INFO) + WAL
#   BUG-02 : relative db path 'network_info.db' → DB_NETWORK_INFO absolute
#   BUG-03 : requests.get() had no timeout — hangs forever on slow/dead API
#            → timeout=5s added
#   BUG-04 : No try/finally — conn.close() inline, leaks on exception
#   BUG-05 : Unbounded DB growth — every 10s insert, no pruning.
#            At 6 rows/min × 60min × 24hr = 8,640 rows/day forever.
#            → keep only last MAX_ROWS=1000 rows, prune on insert
#   BUG-06 : socket.gethostbyname(socket.gethostname()) returns 127.0.0.1
#            on most RPi configurations where hostname resolves to loopback.
#            → use socket.getaddrinfo() with external target for real IP,
#              fall back to hostname resolution
#   BUG-07 : check_connection() hardcoded "www.google.com" — blocked in
#            some enterprise/IoT networks → configurable CHECK_HOST
#   BUG-08 : print_individual_elements() in both files had all print
#            statements commented out — dead code.
#            → kept as log.info() for actual use
#   CODE-01: fetch_connection_status() and get_connection_status() in the
#            second module were identical — merged into one method
#   CODE-02: All print() → logging, import logging added
#   CODE-03: No thread safety → threading.Lock() added
#   ERR-02  — except Exception narrowed to except OSError in get_local_ip()
#             and check_connection() — these only raise OSError; broad except
#             was masking programming errors like AttributeError
#
# ALL functions from both source files are present in this merged class:
#   create_database, get_location, get_datetime, check_connection,
#   insert_network_info, print_individual_elements,
#   fetch_individual_elements, get_connection_status

import socket
import logging
import threading
import datetime
from typing import Optional, Tuple

import requests

from db_connection import get_connection, DB_NETWORK_INFO

log   = logging.getLogger(__name__)
_lock = threading.Lock()

# ─────────────────────────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────────────────────────
MAX_ROWS   = 1000                    # BUG-05: keep last N rows only
CHECK_HOST = ("8.8.8.8", 53)        # BUG-07: DNS port — works on most networks
GEO_API    = "https://ipapi.co/json/"


# ─────────────────────────────────────────────────────────────────
# NETWORK INFO CLASS
# ─────────────────────────────────────────────────────────────────
class NetworkInfo:
    """
    Records and retrieves network connectivity information.

    DB path is controlled by DB_NETWORK_INFO from db_connection.py.
    The db_name parameter is kept for backward compatibility but
    defaults to the canonical absolute path.
    """

    def __init__(self, db_name: str = DB_NETWORK_INFO):
        self.db_name = db_name
        self.create_database()

    # ─────────────────────────────────────────────────────────────
    # TABLE CREATION
    # ─────────────────────────────────────────────────────────────
    def create_database(self) -> None:
        """
        Create network_info table if it doesn't exist.
        BUG-01 FIX: get_connection() applies WAL mode and PRAGMAs.
        BUG-04 FIX: try/finally ensures connection always closed.
        """
        with _lock:
            conn = get_connection(self.db_name)
            try:
                conn.execute('''
                    CREATE TABLE IF NOT EXISTS network_info (
                        id                INTEGER PRIMARY KEY AUTOINCREMENT,
                        ip_address        TEXT,
                        latitude          REAL,
                        longitude         REAL,
                        date_time         TEXT,
                        connection_status TEXT
                    )
                ''')
                conn.commit()
                log.info("NetworkInfo: DB ready at %s", self.db_name)
            except Exception as e:
                conn.rollback()
                log.error("NetworkInfo: create_database failed — %s", e)
                raise
            finally:
                conn.close()

    # ─────────────────────────────────────────────────────────────
    # DATA COLLECTION
    # ─────────────────────────────────────────────────────────────
    def get_location(self) -> Tuple[Optional[float], Optional[float]]:
        """
        Fetch geolocation (latitude, longitude) from ipapi.co.
        BUG-03 FIX: requests.get() had no timeout — could block forever
        on a slow or dead API endpoint.
        Returns (latitude, longitude) or (None, None) on failure.
        """
        try:
            response = requests.get(GEO_API, timeout=5)
            response.raise_for_status()
            data      = response.json()
            latitude  = data.get("latitude")
            longitude = data.get("longitude")
            return latitude, longitude
        except Exception as e:
            log.warning("NetworkInfo: get_location failed — %s", e)
            return None, None

    def get_datetime(self) -> Optional[str]:
        """Return current local datetime as 'YYYY-MM-DD HH:MM:SS'."""
        try:
            return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        except Exception as e:
            log.error("NetworkInfo: get_datetime failed — %s", e)
            return None

    def get_local_ip(self) -> str:
        """
        BUG-06 FIX: original used socket.gethostbyname(socket.gethostname())
        which returns 127.0.0.1 on most RPi setups where /etc/hosts maps
        the hostname to loopback. This is not the network-facing IP.
        Fixed: open a UDP socket toward an external target — the OS selects
        the correct outbound interface without sending any packets.
        Falls back to hostname resolution if UDP approach fails.
        """
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("8.8.8.8", 80))
                return s.getsockname()[0]
        except OSError as exc:
            # ERR-02: narrowed from Exception; socket operations raise OSError
            log.debug("NetworkInfo: UDP socket probe failed — %s", exc)
            try:
                return socket.gethostbyname(socket.gethostname())
            except OSError as exc2:
                log.warning("NetworkInfo: get_local_ip all methods failed — %s", exc2)
                return "unknown"

    def check_connection(self) -> bool:
        """
        Check internet connectivity.
        BUG-07 FIX: original hardcoded "www.google.com" port 80 — blocked
        in many enterprise/IoT network policies.
        Fixed: connects to CHECK_HOST = ("8.8.8.8", 53) — DNS over UDP,
        permitted on virtually all networks.
        Returns True if reachable, False otherwise.
        """
        try:
            socket.create_connection(CHECK_HOST, timeout=3)
            return True
        except OSError:
            # ERR-02: narrowed from Exception; socket.create_connection raises OSError
            return False

    # ─────────────────────────────────────────────────────────────
    # INSERT
    # ─────────────────────────────────────────────────────────────
    def insert_network_info(self,
                            ip_address:        str,
                            latitude:          float,
                            longitude:         float,
                            date_time:         str,
                            connection_status: str) -> bool:
        """
        Insert a new network status record.

        BUG-05 FIX: original inserted every 10s with no pruning.
        At 6 rows/min that is 8,640 new rows/day — filling the SD card.
        After insert, rows beyond MAX_ROWS are deleted (oldest first).

        Returns True on success, False on failure.
        """
        with _lock:
            conn = get_connection(self.db_name)
            try:
                conn.execute(
                    "INSERT INTO network_info "
                    "(ip_address, latitude, longitude, date_time, connection_status) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (ip_address, latitude, longitude, date_time, connection_status)
                )
                # BUG-05 FIX: prune oldest rows beyond MAX_ROWS
                conn.execute('''
                    DELETE FROM network_info
                    WHERE id NOT IN (
                        SELECT id FROM network_info
                        ORDER BY id DESC LIMIT ?
                    )
                ''', (MAX_ROWS,))
                conn.commit()
                return True
            except Exception as e:
                conn.rollback()
                log.error("NetworkInfo: insert_network_info failed — %s", e)
                return False
            finally:
                conn.close()

    # ─────────────────────────────────────────────────────────────
    # READ — LATEST ROW
    # ─────────────────────────────────────────────────────────────
    def fetch_individual_elements(self) -> Tuple[Optional[str], Optional[float], Optional[float], Optional[str], Optional[str]]:
        """
        Return the most recent record as a tuple:
        (ip_address, latitude, longitude, date_time, connection_status)
        or (None, None, None, None, None) if table is empty.

        Merged from second module — replaces the original inline
        SELECT in the __main__ block.
        """
        with _lock:
            conn = get_connection(self.db_name)
            try:
                row = conn.execute('''
                    SELECT ip_address, latitude, longitude,
                           date_time, connection_status
                    FROM network_info ORDER BY id DESC LIMIT 1
                ''').fetchone()
                if row:
                    return (row["ip_address"], row["latitude"],
                            row["longitude"], row["date_time"],
                            row["connection_status"])
                return None, None, None, None, None
            except Exception as e:
                log.error("NetworkInfo: fetch_individual_elements failed — %s", e)
                return None, None, None, None, None
            finally:
                conn.close()

    def get_connection_status(self) -> Optional[str]:
        """
        Return the most recent connection_status value ('Connected' /
        'Disconnected') or None if no records exist.

        CODE-01 FIX: second module had fetch_connection_status() and
        get_connection_status() — identical queries under two names.
        Merged into one method. The other name is kept as an alias below.
        """
        with _lock:
            conn = get_connection(self.db_name)
            try:
                row = conn.execute('''
                    SELECT connection_status FROM network_info
                    ORDER BY id DESC LIMIT 1
                ''').fetchone()
                return row["connection_status"] if row else None
            except Exception as e:
                log.error("NetworkInfo: get_connection_status failed — %s", e)
                return None
            finally:
                conn.close()

    # Alias — some callers use the old name from the second module
    def fetch_connection_status(self) -> Optional[str]:
        return self.get_connection_status()

    # ─────────────────────────────────────────────────────────────
    # PRINT / LOG LATEST
    # ─────────────────────────────────────────────────────────────
    def print_individual_elements(self) -> None:
        """
        Log the most recent network record.

        BUG-08 FIX: both source files had this method with ALL print
        statements commented out — entirely dead code in both. The date/time
        parsing logic ran but its output went nowhere. Replaced with a single
        log.info() call using fetch_individual_elements().
        """
        ip, lat, lon, dt, status = self.fetch_individual_elements()
        if ip is None:
            log.warning("NetworkInfo: no records found")
            return
        log.info(
            "NetworkInfo: ip=%s lat=%s lon=%s datetime=%s status=%s",
            ip, lat, lon, dt, status
        )


# ─────────────────────────────────────────────────────────────────
# MAIN — continuous monitor loop
# ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import time
    import sys
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s"
    )

    ni = NetworkInfo()
    log.info("NetworkInfo monitor started — interval 10s, max rows %d", MAX_ROWS)

    while True:
        try:
            ip_address        = ni.get_local_ip()
            latitude, longitude = ni.get_location()
            date_time         = ni.get_datetime()
            connection_status = "Connected" if ni.check_connection() else "Disconnected"

            ni.insert_network_info(
                ip_address, latitude, longitude,
                date_time, connection_status
            )
            ni.print_individual_elements()
        except Exception as e:
            log.error("NetworkInfo: monitor loop error — %s", e)

        time.sleep(10)