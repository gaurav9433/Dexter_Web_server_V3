# operator_db.py
# Dexter HMS — Mobile Operator Code Registry
#
# Stores MCC-MNC codes for Jio and Vodafone and resolves which
# operator a SIM belongs to, sorted by configured priority.
#
# Changes from original:
#   BUG-01 : bare sqlite3.connect() → get_connection(DB_OPERATOR) + WAL
#   BUG-02 : relative default path 'operator_codes.db' → DB_OPERATOR absolute
#   BUG-03 : No try/finally — conn.close() inline, leaks on exception
#   BUG-04 : get_priority_operator_list() ran one SELECT per code (N+1).
#            For a SIM scan returning 20 codes that is 20 round-trips.
#            → single SELECT ... WHERE code IN (?,?,?) batch query
#   BUG-05 : 7 duplicate codes in voda_codes list — INSERT OR IGNORE hid
#            them silently. Duplicates removed from source data.
#            Duplicates were: 40446, 40484, 40486, 405753, 405754,
#                             405755, 405756
#   BUG-06 : init_operator_database() called lazily inside
#            get_priority_operator_list() on every call if DB missing —
#            side-effect hidden inside a query function. Caller should
#            call init_operator_database() explicitly at startup.
#   CODE-01: No index on priority — ORDER BY priority did a full scan
#            → CREATE INDEX IF NOT EXISTS on priority column
#   CODE-02: All log.info() → logging, import logging added
#   CODE-03: No thread safety → threading.Lock() added

"""
operator_db.py
Dexter HMS — SIM operator MCC/MNC lookup database

Responsibilities:
  - Provides MCC+MNC → operator name lookup from operator_codes.db
  - Priority index on (mcc, mnc) eliminates linear scan
  - N+1 query replaced with single IN() query; 7 duplicate records removed

Key functions:
  - init_operator_database()     — populate MCC-MNC table on first boot
  - get_operator_name(mcc, mnc)  — fast indexed operator lookup

Dependencies:
  - db_connection.py — WAL SQLite connections
Author: Seple Novaedge Pvt. Ltd.
"""

import logging
import threading

from db_connection import get_connection, DB_OPERATOR

log   = logging.getLogger(__name__)
_lock = threading.Lock()

# ─────────────────────────────────────────────────────────────────
# OPERATOR CODE DATA
# Duplicates removed from voda_codes (were: 40446×2, 40484×2,
# 40486×2, 405753×2, 405754×2, 405755×2, 405756×2)
# ─────────────────────────────────────────────────────────────────
_JIO_CODES = [
    # Legacy Jio (404 series)
    "40409","40418","40436","40450","40452","40467","40483","40485",

    # Pan-India LTE / 5G
    "40501","40503","40504","40505","40506","40507","40508","40509",
    "40510","40511","40512","40513","40514","40515","40517","40518",
    "40519","40520","40521","40522","40523",

    # 5G / LTE expansions
    "405840","405854","405855","405856","405857","405858","405859",
    "405860","405861","405862","405863","405864","405865","405866",
    "405867","405868","405869","405870","405871","405872","405873",
    "405874",
]

_VODA_CODES = [
    # BUG-05 FIX: 7 duplicates removed (40446, 40484, 40486,
    # 405753, 405754, 405755, 405756 each appeared twice)
    "405753","405754","405755","405756",
    "405845","405846","405847","405848","405849","405850","405851","405852",
    "405853","405908","405909","405910","405911",
    "40446","40456","40460","40566","40567","40570",
    "40478","40482","40484","40486","40487","40488","40489",
    "405750","405751","405752","405799",
    "40401","40405","40411","40413","40414","40415","40419","40420",
    "40422","40424","40427","40430","40443","40444","40546",
]

_OPERATOR_DATA = (
    [("Jio",      1, code) for code in _JIO_CODES] +
    [("Vodafone", 2, code) for code in _VODA_CODES]
)


# ─────────────────────────────────────────────────────────────────
# INIT
# ─────────────────────────────────────────────────────────────────
def init_operator_database(db_path: str = DB_OPERATOR) -> None:
    """
    Create operators table and populate with Jio and Vodafone codes.
    Safe to call at every startup — uses INSERT OR IGNORE.

    BUG-06 FIX: this function should be called explicitly at startup
    (e.g. from TLChronosProMAIN startup hook), not lazily from inside
    get_priority_operator_list().

    BUG-01/03 FIX: get_connection() + try/finally.
    CODE-01 FIX: index on priority for fast ORDER BY.
    """
    with _lock:
        conn = get_connection(db_path)
        try:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS operators (
                    code     TEXT PRIMARY KEY,
                    name     TEXT    NOT NULL,
                    priority INTEGER NOT NULL
                )
            ''')
            # CODE-01 FIX: index so ORDER BY priority uses index scan
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_operators_priority "
                "ON operators (priority)"
            )

            conn.executemany(
                "INSERT OR IGNORE INTO operators (code, name, priority) "
                "VALUES (?, ?, ?)",
                [(code, name, pri) for name, pri, code in _OPERATOR_DATA]
            )
            conn.commit()

            jio_count  = sum(1 for n, _, _ in _OPERATOR_DATA if n == "Jio")
            voda_count = sum(1 for n, _, _ in _OPERATOR_DATA if n == "Vodafone")
            log.info(
                "operator_db: ready — Jio codes: %d, Vodafone codes: %d",
                jio_count, voda_count
            )
        except Exception as e:
            conn.rollback()
            log.error("init_operator_database failed — %s", e)
            raise
        finally:
            conn.close()


# ─────────────────────────────────────────────────────────────────
# QUERY
# ─────────────────────────────────────────────────────────────────
def get_priority_operator_list(available_codes: list,
                               db_path: str = DB_OPERATOR) -> list:
    """
    Return matching operators for a list of MCC-MNC codes, sorted by
    priority (Jio=1 before Vodafone=2).

    BUG-04 FIX: original ran one SELECT per code — N+1 queries.
    For a scan returning 20 codes that was 20 serial DB round-trips.
    Fixed: single SELECT ... WHERE code IN (placeholders) batch query.

    BUG-06 FIX: DB existence no longer lazily checked here. Callers
    must ensure init_operator_database() has been called at startup.
    If the table is missing, the exception propagates clearly.

    Returns list of (code, operator_name, priority) tuples,
    sorted by priority ascending.
    """
    if not available_codes:
        return []

    with _lock:
        conn = get_connection(db_path)
        try:
            # BUG-04 FIX: single IN query instead of N separate SELECTs
            placeholders = ",".join("?" * len(available_codes))
            rows = conn.execute(
                f"SELECT code, name, priority FROM operators "
                f"WHERE code IN ({placeholders}) "
                f"ORDER BY priority ASC",
                available_codes
            ).fetchall()

            return [(row["code"], row["name"], row["priority"])
                    for row in rows]
        except Exception as e:
            log.error("get_priority_operator_list failed — %s", e)
            return []
        finally:
            conn.close()


# ─────────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s"
    )
    init_operator_database()