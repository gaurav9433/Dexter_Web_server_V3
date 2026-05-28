# -*- coding: utf-8 -*-
# serial_data_logger.py
# Dexter HMS — Serial Controller Data Logger
#
# Reads JSON telemetry (panel_current, battery_voltage, ac_voltage,
# lithium_ion_bat_volt_sense) from a serial-connected controller and
# stores the latest values in parameters.db.
#
# Changes from original:
#   BUG-01 : module-level watchdog = SoftwareWatchdog() — background
#            thread started at import time, not in __main__
#   BUG-02 : module-level controller_db_manager = ControllerDatabaseManager()
#            — DB opened and table created at every import
#            Both moved inside if __name__ == "__main__"
#   BUG-03 : ControllerDatabaseManager stored self.conn as instance attr —
#            if connect() called twice before close(), first handle leaked
#            → per-operation get_connection() + finally: close()
#   BUG-04 : insert_or_update_parameters used SELECT COUNT(*) then
#            UPDATE or INSERT — not atomic, race condition possible
#            → INSERT OR REPLACE (UPSERT)
#   BUG-05 : 4 separate get_X() methods each opened/closed the DB —
#            callers doing get_panel_current() + get_battery_voltage()
#            + get_ac_voltage() + get_lithium_ion_bat_volt_sense() made
#            4 round-trips. → get_all_parameters() returns all in one query
#   BUG-06 : serial read buffer grew unbounded when no '}' was found in
#            corrupt/partial data — memory leak on bad serial stream
#            → MAX_BUFFER_SIZE cap with truncation + warning
#   BUG-07 : os.execl() in watchdog thread restarted with no serial port
#            cleanup — port left open by OS, next open may fail
#            → ser.close() called before execl if port is open
#   BUG-08 : fetch_and_print_parameters() printed only row id — all other
#            fields were commented out — entirely dead code
#            → replaced with log.info() via get_all_parameters()
#   CODE-01 : serial port hardcoded as "/dev/ttyUSB0"
#             → SERIAL_PORT constant at top of file, easy to change
#   CODE-02 : watchdog timeout hardcoded 100s inside SoftwareWatchdog() call
#             → WATCHDOG_TIMEOUT constant
#   CODE-03 : bare sqlite3.connect() → get_connection(DB_CONTROLLER_PARAMS)
#   CODE-04 : relative 'parameters.db' → DB_CONTROLLER_PARAMS absolute path
#   CODE-05 : All log.info() → logging

"""
serial_data_logger.py
Dexter HMS — Analog sensor value logger via serial controller board

Responsibilities:
  - Reads analog sensor values from the controller board via serial port
  - Stores readings in parameters.db (SQLite) using INSERT OR REPLACE
  - Uses db_connection.py for WAL-mode connections

Key functions:
  - read_and_log_sensor_data() — read serial frame and store to DB

Dependencies:
  - db_connection.py       — WAL SQLite connections
  - SerialCommunication.py — serial port I/O
Author: Seple Novaedge Pvt. Ltd.
"""

import os
import sys
import json
import time
import threading
import logging
from datetime import datetime
from typing import Optional

import serial

from buffer_manager import insert_json_to_db
from db_connection import get_connection, DB_CONTROLLER_PARAMS

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────────────────────────
SERIAL_PORT      = "/dev/ttyUSB0"   # CODE-01: change here, not in code
SERIAL_BAUD      = 9600
SERIAL_TIMEOUT   = 1
WATCHDOG_TIMEOUT = 600              # CODE-02: seconds (was hardcoded 100)
MAX_BUFFER_SIZE  = 4096             # BUG-06: max serial read buffer bytes


# ─────────────────────────────────────────────────────────────────
# SOFTWARE WATCHDOG
# ─────────────────────────────────────────────────────────────────
class SoftwareWatchdog:
    """
    Restarts the process if reset() is not called within timeout seconds.

    BUG-07 FIX: original os.execl() had no serial port cleanup.
    The port was left open by the OS — the next process open could fail
    with "device busy". Fixed: _current_serial ref allows close() before
    execl so the OS releases the port cleanly.
    """

    def __init__(self, timeout: int = WATCHDOG_TIMEOUT):
        self.timeout       = timeout
        self.last_reset    = time.time()
        self._running      = True
        self._current_serial = None       # BUG-07: set by main() before loop
        self.thread        = threading.Thread(
            target=self._watchdog_loop, daemon=True
        )
        self.thread.start()

    def _watchdog_loop(self) -> None:
        while self._running:
            if time.time() - self.last_reset > self.timeout:
                self._restart_program()
            time.sleep(1)

    def reset(self) -> None:
        self.last_reset = time.time()

    def stop(self) -> None:
        self._running = False
        self.thread.join()

    def _restart_program(self) -> None:
        self._running = False

        # BUG-07 FIX: close serial port before execl
        if self._current_serial and self._current_serial.is_open:
            try:
                self._current_serial.close()
                log.info("watchdog: serial port closed before restart")
            except Exception as e:
                log.warning("watchdog: serial close failed — %s", e)

        log_data = {
            "watchdog_log": [{
                "Module Reboot": "Power Status",
                "timestamp": datetime.now().strftime("%d-%m-%y %H:%M:%S")
            }]
        }
        try:
            insert_json_to_db(json.dumps(log_data))
        except Exception as e:
            log.error("watchdog: failed to insert reboot log — %s", e)

        log.warning("watchdog: timeout — restarting process")
        python = sys.executable or "/usr/bin/python3"
        os.execl(python, python, *sys.argv)


# ─────────────────────────────────────────────────────────────────
# CONTROLLER DATABASE MANAGER
# ─────────────────────────────────────────────────────────────────
class ControllerDatabaseManager:
    """
    Single-row store for the latest controller readings.

    BUG-03 FIX: original stored self.conn as an instance attribute.
    If connect() was called before the previous connection was closed,
    the old handle was silently dropped (leaked). Fixed: per-operation
    get_connection() + finally: close(). No persistent self.conn.

    CODE-03/04 FIX: get_connection(DB_CONTROLLER_PARAMS) replaces
    sqlite3.connect('parameters.db').
    """

    def __init__(self, db_path: str = DB_CONTROLLER_PARAMS):
        self.db_path = db_path

    def create_table(self) -> None:
        conn = get_connection(self.db_path)
        try:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS parameters (
                    id                        INTEGER PRIMARY KEY,
                    panel_current             REAL,
                    battery_voltage           REAL,
                    ac_voltage                REAL,
                    lithium_ion_bat_volt_sense REAL
                )
            ''')
            conn.commit()
            log.info("ControllerDB: table ready at %s", self.db_path)
        except Exception as e:
            conn.rollback()
            log.error("ControllerDB: create_table failed — %s", e)
            raise
        finally:
            conn.close()

    def insert_or_update_parameters(self,
                                    panel_current:              float,
                                    battery_voltage:            float,
                                    ac_voltage:                 float,
                                    lithium_ion_bat_volt_sense: float) -> bool:
        """
        BUG-04 FIX: original did SELECT COUNT(*) then UPDATE or INSERT —
        two statements, not atomic. Under concurrent access (unlikely here
        but possible) both threads could see count=0 and both INSERT,
        leaving two rows and breaking the single-row assumption.
        Fixed: INSERT OR REPLACE atomically handles both cases.
        id=1 is always the single live row.
        """
        conn = get_connection(self.db_path)
        try:
            conn.execute('''
                INSERT OR REPLACE INTO parameters
                    (id, panel_current, battery_voltage,
                     ac_voltage, lithium_ion_bat_volt_sense)
                VALUES (1, ?, ?, ?, ?)
            ''', (panel_current, battery_voltage,
                  ac_voltage, lithium_ion_bat_volt_sense))
            conn.commit()
            return True
        except Exception as e:
            conn.rollback()
            log.error("ControllerDB: insert_or_update_parameters failed — %s", e)
            return False
        finally:
            conn.close()

    def get_all_parameters(self) -> Optional[dict]:
        """
        BUG-05 FIX: original had 4 separate get_X() methods, each
        opening and closing the DB independently. A caller reading all
        four values made 4 DB round-trips.

        Returns all sensor values in one query as a dict:
            {"panel_current": 1.2, "battery_voltage": 12.4, ...}
        or None if no row exists.
        """
        conn = get_connection(self.db_path)
        try:
            row = conn.execute(
                "SELECT panel_current, battery_voltage, "
                "ac_voltage, lithium_ion_bat_volt_sense "
                "FROM parameters WHERE id = 1"
            ).fetchone()
            if row is None:
                return None
            return {
                "panel_current":              row["panel_current"],
                "battery_voltage":            row["battery_voltage"],
                "ac_voltage":                 row["ac_voltage"],
                "lithium_ion_bat_volt_sense": row["lithium_ion_bat_volt_sense"],
            }
        except Exception as e:
            log.error("ControllerDB: get_all_parameters failed — %s", e)
            return None
        finally:
            conn.close()

    # Individual getters kept for backward compatibility with existing callers
    def get_panel_current(self) -> Optional[float]:
        p = self.get_all_parameters()
        return p["panel_current"] if p else None

    def get_battery_voltage(self) -> Optional[float]:
        p = self.get_all_parameters()
        return p["battery_voltage"] if p else None

    def get_ac_voltage(self) -> Optional[float]:
        p = self.get_all_parameters()
        return p["ac_voltage"] if p else None

    def get_lithium_ion_bat_volt_sense(self) -> Optional[float]:
        p = self.get_all_parameters()
        return p["lithium_ion_bat_volt_sense"] if p else None

    def fetch_and_print_parameters(self) -> None:
        """
        BUG-08 FIX: original printed only row[0] (id) — every other
        field was commented out. Replaced with log.info() of all fields.
        """
        params = self.get_all_parameters()
        if params:
            log.info(
                "ControllerDB: panel_current=%.3f battery_voltage=%.3f "
                "ac_voltage=%.3f li_bat_volt=%.3f",
                params["panel_current"], params["battery_voltage"],
                params["ac_voltage"],    params["lithium_ion_bat_volt_sense"]
            )
        else:
            log.warning("ControllerDB: no parameters row found")


# ─────────────────────────────────────────────────────────────────
# SERIAL HELPERS
# ─────────────────────────────────────────────────────────────────
def setup_serial_connection(port: str = SERIAL_PORT,
                            baudrate: int = SERIAL_BAUD,
                            timeout: int = SERIAL_TIMEOUT) -> Optional[serial.Serial]:
    try:
        ser = serial.Serial(port, baudrate=baudrate, timeout=timeout)
        log.info("Serial: connected on %s @ %d baud", port, baudrate)
        return ser
    except serial.SerialException as e:
        log.error("Serial: failed to open %s — %s", port, e)
        return None


def initVariable(controller_db: ControllerDatabaseManager) -> None:
    """Zero-initialise the parameters row on first boot."""
    controller_db.insert_or_update_parameters(0.0, 0.0, 0.0, 0.0)
    controller_db.fetch_and_print_parameters()


# ─────────────────────────────────────────────────────────────────
# MAIN LOOP
# ─────────────────────────────────────────────────────────────────
def main(controller_db: ControllerDatabaseManager,
         watchdog_timer: SoftwareWatchdog) -> None:
    """
    Continuously read JSON telemetry from the serial controller and
    persist the latest values to parameters.db.

    BUG-06 FIX: buffer was appended without any size limit. Corrupt or
    continuous serial data with no '}' would grow buffer unboundedly,
    consuming all RAM. If buffer exceeds MAX_BUFFER_SIZE, it is truncated
    to the last '{' — preserving any partial JSON in progress.
    """
    while True:
        ser = setup_serial_connection()
        if ser is None:
            log.warning("Serial: retrying in 5s...")
            time.sleep(5)
            continue

        # BUG-07 FIX: give watchdog a reference so it can close port on restart
        watchdog_timer._current_serial = ser

        buffer = ""
        while True:
            try:
                data = ser.read(100)
                if not data:
                    continue

                buffer += data.decode("utf-8", errors="ignore")

                # BUG-06 FIX: cap buffer size to prevent RAM exhaustion
                if len(buffer) > MAX_BUFFER_SIZE:
                    log.warning(
                        "Serial: buffer overflow (%d bytes) — truncating",
                        len(buffer)
                    )
                    last_open = buffer.rfind("{")
                    buffer = buffer[last_open:] if last_open != -1 else ""

                # Extract complete JSON objects from buffer
                while True:
                    start = buffer.find("{")
                    end   = buffer.find("}")
                    if start == -1 or end == -1 or end <= start:
                        break

                    json_string = buffer[start:end + 1]
                    buffer      = buffer[end + 1:]

                    try:
                        parsed = json.loads(json_string)
                    except ValueError:
                        log.debug("Serial: failed to parse JSON fragment: %s",
                                  json_string[:80])
                        continue

                    panel_current              = parsed.get("panel_current")
                    battery_voltage            = parsed.get("battery_voltage")
                    ac_voltage                 = parsed.get("ac_voltage")
                    lithium_ion_bat_volt_sense = parsed.get("lithium_ion_bat_volt_sense")

                    if panel_current is None or battery_voltage is None:
                        log.warning("Serial: JSON missing required fields: %s",
                                    json_string[:80])
                        continue

                    watchdog_timer.reset()
                    controller_db.insert_or_update_parameters(
                        panel_current, battery_voltage,
                        ac_voltage, lithium_ion_bat_volt_sense
                    )
                    controller_db.fetch_and_print_parameters()

            except serial.SerialException as e:
                log.error("Serial: communication error — %s", e)
                break

        ser.close()
        watchdog_timer._current_serial = None
        log.info("Serial: port closed, reconnecting...")


# ─────────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s"
    )

    # BUG-01/02 FIX: watchdog and DB manager created here only,
    # not at module import level
    controller_db_manager = ControllerDatabaseManager()
    controller_db_manager.create_table()

    watchdog = SoftwareWatchdog(timeout=WATCHDOG_TIMEOUT)

    initVariable(controller_db_manager)
    main(controller_db_manager, watchdog)