# -*- coding: utf-8 -*-
# !/usr/local/bin/python
# With RPC & OTA
import psutil
import socket
import threading
import subprocess
import os
import sys
import json_db_module
import re
import serial
import json
import time
#import datetime
import datetime as dt
from datetime import datetime
import watchdog
import hashlib

# ── systemd watchdog notify (no external package required) ───────────────────
# Sends WATCHDOG=1 to systemd via NOTIFY_SOCKET (a Unix datagram socket).
# When called regularly, this resets the WatchdogSec=1800 countdown in
# dexter-serial-comm.service, preventing an unnecessary Pi reboot while the
# modem is healthy.  If the modem gets stuck and this function stops being
# called, the countdown expires after 1800s and systemd reboots the Pi —
# which is the correct and intended recovery behaviour.
def _sd_notify_watchdog():
    """Send WATCHDOG=1 ping to systemd. Safe to call even outside systemd."""
    notify_socket = os.environ.get('NOTIFY_SOCKET')
    if not notify_socket:
        return  # not running under systemd — silently skip
    try:
        import socket as _socket
        msg = b'WATCHDOG=1'
        if notify_socket.startswith('@'):
            notify_socket = '\x00' + notify_socket[1:]  # abstract socket
        sock = _socket.socket(_socket.AF_UNIX, _socket.SOCK_DGRAM)
        sock.connect(notify_socket)
        sock.sendall(msg)
        sock.close()
    except Exception as _e:
        logger.debug('[sd_notify] watchdog ping failed: %s', _e)
#from datetime import datetime
#from datetime import date
import requests
import sqlite3
import schedule  # Import schedule
from updatecode import fetch_and_update_dexter_config
from database_handler import DatabaseHandler
from refreshcode import send_dexter_config
from webdone import send_webdone
from buffer_manager import insert_json_to_db
from net_wait import wait_for_network

# SEC-04: Fernet encryption for modem credential fields
try:
    from secrets_manager import encrypt_value, decrypt_value
    from cryptography.fernet import InvalidToken
except ImportError:
    # Fallback if secrets_manager not available — store plaintext
    def encrypt_value(v): return v
    def decrypt_value(v): return v
    class InvalidToken(Exception): pass

# DB-01: WAL-enabled connection factory
try:
    from db_connection import get_connection
except ImportError:
    def get_connection(path, row_factory=True):
        import sqlite3 as _sq
        conn = _sq.connect(path, check_same_thread=False)
        if row_factory:
            conn.row_factory = _sq.Row
        conn.execute('PRAGMA journal_mode=WAL;')
        conn.execute('PRAGMA foreign_keys=ON;')
        conn.execute('PRAGMA busy_timeout=5000;')
        return conn

# Logging (ERR-06)
import logging
logging.basicConfig(level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s')
logger = logging.getLogger('SerialCommunication')




def safe_reopen_serial(sc, port="/dev/ttyS0", timeout=20, retries=10, delay=2):
    """
    Safely re-open the serial port after PPP has used it.
    1. Wait until no process is holding the port (psutil).
    2. Retry opening until kernel fully releases it.
    """
    start = time.time()

    # Step 1: wait until no process has /dev/ttyS0 open
    while time.time() - start < timeout:
        busy = False
        for proc in psutil.process_iter(['pid', 'name', 'open_files']):
            try:
                if proc.info['open_files']:
                    for f in proc.info['open_files']:
                        if f.path == port:
                            busy = True
            except (psutil.AccessDenied, psutil.NoSuchProcess):
                continue
        if not busy:
            print(f"{port} is free at process level")
            break
        print(f"{port} still busy, waiting for process to release...")
        time.sleep(1)
    else:
        print(f" Timeout waiting for {port} to be free at process level")

    # Step 2: retry pySerial open until kernel releases it
    for i in range(retries):
        try:
            sc.initialize_serial()
            print(" Serial port re-opened successfully")
            return True
        except serial.SerialException as e:
            logger.warning("[safe_reopen_serial] Retry %d/%d: %s", i+1, retries, e)
            time.sleep(delay)

    print(" Failed to re-open serial after retries")
    return False


class SoftwareWatchdog:
    def __init__(self, timeout=1800):
        """
        Initialize the software watchdog.
        :param timeout: Time in seconds before triggering a reset if not fed.
        """
        self.timeout = timeout
        self.last_reset = time.time()
        self._running = True
        self.thread = threading.Thread(target=self._watchdog_loop)
        self.thread.daemon = True  # Set daemon mode for Python 3
        self.thread.start()

    def _watchdog_loop(self):
        """ Watchdog monitoring loop that checks if the timeout is exceeded. """
        while self._running:
            if time.time() - self.last_reset > self.timeout:
                print("Watchdog timeout! Restarting software...")
                self._restart_program()
            time.sleep(1)

    def reset(self):
        """ Reset the watchdog timer to prevent restart. """
        self.last_reset = time.time()
        #print("Watchdog reset at:", time.strftime('%Y-%m-%d %H:%M:%S'))  # Debugging print

    def stop(self):
        """ Stop the watchdog timer. """
        self._running = False
        self.thread.join()

    
    def _restart_program(self):
        """ Restart the script using OS system call and log to database. """
        self._running = False  # Stop watchdog loop

        # Prepare the log message
        log_data = {
            "watchdog_log": [
                {
                    "Module Reboot": "Dahua Logs",
                    "timestamp": datetime.now().strftime("%d-%m-%y %H:%M:%S")
                }
            ]
        }

        # Convert to JSON and insert into DB
        attributes_json = json.dumps(log_data)
        try:
            insert_json_to_db(attributes_json)
        except Exception as e:
            logger.error("[Watchdog] DB insert failed: %s", e)

        print("Watchdog timeout! Restarting software...")
    
        # Restart the script
        python = sys.executable if sys.executable else "/usr/bin/python3"
        os.execl(python, python, *sys.argv)
  
# Initialize software watchdog with 1800-second timeout
watchdog = SoftwareWatchdog(timeout=1800)

#def wait_for_network(host="thingsboard.cloud", timeout=30):
#  """
#    Wait until DNS resolution works for the given host.
#    Returns True if DNS resolves before timeout, False otherwise.
#    """
#    start = time.time()
#    while time.time() - start < timeout:
#        try:
#            socket.gethostbyname(host)  # Try resolving hostname
#            print(f"DNS OK: {host} resolved")
#            return True
#        except socket.gaierror:
#            print("DNS not ready, retrying...")
#            time.sleep(2)
#    return False

#thingsweb function
# ---- Paths ----
DB_INTEGRATION = "/home/pi/Test3/device_config.db"
DB_MODEM = "/home/pi/Test3/modem_config.db"
DB_ACTIVE_BIT = "/home/pi/Test3/active_integration.db"
DB_ACTIVE_DEVICE = "/home/pi/Test3/logical_params_active_integration.db"
DB_NETWORK = "/home/pi/Test3/network_settings.db"

POWER_TEXT_FILE = "/home/pi/Test3/powerZoneSettings.txt"
ZONE_TEXT_FILE = "/home/pi/Test3/zoneSettings.txt"
BRANCH_FILE = "/home/pi/Test3/Branch.txt"
BRAND_FILE = "/home/pi/Test3/Brand.txt"

SNAPSHOT_FILE = "/home/pi/Test3/config_snapshot.json"


def file_checksum(filepath, normalize_text=True):
    """Return SHA256 checksum of a file. Normalizes text files for accuracy."""
    if not os.path.isfile(filepath):
        return ""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        data = f.read()
        if normalize_text:
            try:
                # Normalize text content: strip trailing spaces, normalize newlines
                text = data.decode(errors="ignore").replace("\r\n", "\n").rstrip()
                data = text.encode()
            except Exception:
                pass
        h.update(data)
    return h.hexdigest()


def db_checksum(db_path):
    """Return checksum of schema + sorted data for accuracy."""
    if not os.path.isfile(db_path):
        return ""
    try:
        conn = get_connection(db_path)
        cursor = conn.cursor()

        # Include schema
        cursor.execute(
            "SELECT sql FROM sqlite_master "
            "WHERE type IN ('table','index','trigger','view')"
        )
        schema_dump = "\n".join([r[0] for r in cursor.fetchall() if r[0]])

        # Include sorted table data
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [t[0] for t in cursor.fetchall()]
        data_dump = ""
        for table in sorted(tables):
            cursor.execute(f"PRAGMA table_info({table})")
            cols = [c[1] for c in cursor.fetchall()]
            if not cols:
                continue
            collist = ",".join(cols)
            cursor.execute(f"SELECT {collist} FROM {table} ORDER BY {collist}")
            rows = cursor.fetchall()
            data_dump += f"TABLE:{table} -> " + json.dumps(rows, sort_keys=True) + "\n"

        conn.close()

        full_dump = schema_dump + "\n" + data_dump
        return hashlib.sha256(full_dump.encode()).hexdigest()
    except Exception as e:
        return "ERROR:" + str(e)


def build_snapshot():
    snap = {
        "files": {
            "power": file_checksum(POWER_TEXT_FILE),
            "zone": file_checksum(ZONE_TEXT_FILE),
            "branch": file_checksum(BRANCH_FILE),
            "brand": file_checksum(BRAND_FILE),
        },
        "dbs": {
            "integration": db_checksum(DB_INTEGRATION),
            "modem": db_checksum(DB_MODEM),
            "active_bit": db_checksum(DB_ACTIVE_BIT),
            "active_device": db_checksum(DB_ACTIVE_DEVICE),
            "network": db_checksum(DB_NETWORK),
        }
    }
    # Add a global checksum of the whole snapshot
    snap["_global"] = hashlib.sha256(json.dumps(snap, sort_keys=True).encode()).hexdigest()
    return snap


def load_snapshot():
    if not os.path.isfile(SNAPSHOT_FILE):
        return {}
    try:
        with open(SNAPSHOT_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def save_snapshot(snapshot):
    with open(SNAPSHOT_FILE, "w") as f:
        json.dump(snapshot, f, indent=2)


# Global flag
send_needed = True  

def _sc_network_type() -> str:
    """Read network_type from modem_config.db."""
    try:
        import sqlite3 as _sq
        c = _sq.connect("/home/pi/Test3/modem_config.db")
        row = c.execute("SELECT network_type FROM modem_parameters WHERE id=1").fetchone()
        c.close()
        return (row[0] or "").strip().lower() if row else ""
    except Exception:
        return ""

_NSENTER_SC = ["nsenter", "-t", "1", "-m", "-u", "-i", "-n", "-p", "--"]

def check_and_send():
    """Check for changes and send config if modified or flagged."""
    global send_needed

    old_snapshot = load_snapshot()
    new_snapshot = build_snapshot()

    # Condition: snapshot changed OR flag says send is needed
    if new_snapshot != old_snapshot or send_needed:
        print("Change or flag detected  Sending config...")
        save_snapshot(new_snapshot)

        use_modem = _sc_network_type() == "gsm"
        try:
            if use_modem:
                subprocess.call(_NSENTER_SC + ["pon", "c16qs"])
            if wait_for_network():
                success = send_dexter_config()
                # Update flag based on result
                if success:
                    send_needed = False   #  sent successfully
                else:
                    send_needed = True    #  failed, keep flag ON
            else:
                print("DNS not available, skipping update")
                send_needed = True        # still need to send later
        finally:
            if use_modem:
                subprocess.call(_NSENTER_SC + ["poff", "c16qs"])
            time.sleep(2)
            safe_reopen_serial(serial_commander)

        return True
    else:
        print("No change detected and no flag set. Nothing sent.")
        return False


class ModemConfigDatabase:
    # SEC-02: column whitelist prevents SQL injection via .format(param)
    _ALLOWED_PARAMS = {
        'access_token', 'client_id', 'user_name', 'password',
        'gsm_modem_mode', 'network_type', 'device_name',
    }

    # SEC-04: fields that must be Fernet-encrypted at rest
    _CREDENTIAL_FIELDS = {'access_token', 'client_id', 'user_name', 'password'}

    def __init__(self, db_file='modem_config.db'):
        self.db_file = db_file
        self.create_database()

    def create_database(self):
        conn = None
        try:
            conn = get_connection(self.db_file)  # DB-01: WAL
            conn.execute('''CREATE TABLE IF NOT EXISTS modem_parameters (
                id INTEGER PRIMARY KEY, access_token TEXT, client_id TEXT,
                user_name TEXT, password TEXT, gsm_modem_mode TEXT,
                network_type TEXT, device_name TEXT)''')
            for col in self._ALLOWED_PARAMS:
                try:
                    conn.execute(f'ALTER TABLE modem_parameters ADD COLUMN {col} TEXT')
                except Exception:
                    pass
            if conn.execute('SELECT COUNT(*) FROM modem_parameters').fetchone()[0] == 0:
                conn.execute(
                    'INSERT INTO modem_parameters (access_token,client_id,user_name,password,gsm_modem_mode,network_type,device_name) VALUES (?,?,?,?,?,?,?)',
                    ('','','','','physical','ethernet','Dexter-HMS'))
            conn.commit()
        except sqlite3.Error as e:
            logger.error("[ModemConfigDatabase.create_database] %s", e)
        finally:
            conn.close()

    def get_parameter(self, param):
        if param not in self._ALLOWED_PARAMS:  # SEC-02
            logger.error("[ModemConfigDatabase] rejected column: %s", param)
            return None
        conn = None
        try:
            conn = get_connection(self.db_file)  # DB-01
            row = conn.execute(
                f'SELECT {param} FROM modem_parameters WHERE id = 1').fetchone()
            value = row[0] if row else None
            # SEC-04: decrypt credential fields on read
            if value and param in self._CREDENTIAL_FIELDS:
                try:
                    value = decrypt_value(value)
                except (ValueError, InvalidToken):
                    pass  # legacy plaintext row — return as-is
            return value
        except sqlite3.Error as e:
            logger.error("[ModemConfigDatabase.get_parameter(%s)] %s", param, e)
            return None
        finally:
            conn.close()

    def update_parameter(self, param, value):
        if param not in self._ALLOWED_PARAMS:  # SEC-02
            logger.error("[ModemConfigDatabase] rejected column: %s", param)
            return
        # SEC-04: encrypt credential fields before writing to DB
        stored_value = encrypt_value(str(value)) if param in self._CREDENTIAL_FIELDS else value
        conn = None
        try:
            conn = get_connection(self.db_file)  # DB-01
            conn.execute(
                f'UPDATE modem_parameters SET {param} = ? WHERE id = 1', (stored_value,))
            conn.commit()
        except sqlite3.Error as e:
            logger.error("[ModemConfigDatabase.update_parameter(%s)] %s", param, e)
        finally:
            conn.close()

    def migrate_plaintext_credentials(self) -> None:
        """
        One-time migration: reads all credential fields, skips already-encrypted
        rows, encrypts any remaining plaintext rows.
        Safe to run at every startup — already-encrypted rows are skipped.
        """
        conn = None
        try:
            conn = get_connection(self.db_file)
            row = conn.execute(
                "SELECT access_token, client_id, user_name, password "
                "FROM modem_parameters WHERE id = 1"
            ).fetchone()
            if not row:
                return
            for field, raw in zip(
                ['access_token', 'client_id', 'user_name', 'password'],
                [row['access_token'], row['client_id'], row['user_name'], row['password']]
            ):
                if not raw:
                    continue
                try:
                    decrypt_value(raw)   # already encrypted — skip
                except (ValueError, InvalidToken):
                    # plaintext — encrypt it now
                    conn.execute(
                        f"UPDATE modem_parameters SET {field} = ? WHERE id = 1",
                        (encrypt_value(raw),)
                    )
                    logger.info("[ModemConfigDatabase] migrated '%s' to encrypted", field)
            conn.commit()
        except Exception as e:
            logger.error("[ModemConfigDatabase.migrate_plaintext_credentials] %s", e)
        finally:
            conn.close()

class State:
    """Base state class.
    
    Attributes:
        name (str): The name of the state.
        params (dict): Parameters passed to the state.
    """
    def __init__(self, **kwargs):
        """Initialize the state with optional parameters."""
        self.name = self.__class__.__name__
        self.params = kwargs

    def on_event(self, event):
        """Handle events that are delegated to this State.
        
        Args:
            event (str): The event to handle.
            
        Returns:
            State: The next state after handling the event.
        """
        pass

    def __str__(self):
        """Return the name and parameters of the state."""
        return self.name + " with params: " + str(self.params)

class ErrorState(State):
    """State for handling errors."""
    def on_event(self, event):
        print("Error state: cannot handle events.")
        return ModemSetUp()

class InitializeModem(State):
    """State for initializing the modem."""
    def on_event(self, event):
        try:
            print("Initializing modem...1")
            if event == 'network_check':
                initialize_device()
                return CheckNetworkStatus(**self.params)
        except Exception as e:
            logger.error("[InitializeModem] %s", e)
            return ErrorState()
        return self

class CheckNetworkStatus(State):
    """State for checking network status."""
    def on_event(self, event):
        try:
            print("Checking network status...")
            if event == 'signal_strength':
                main(None, str(2))
                main(None, str(6))
               # main(None, str(7))
                return CheckSignalStrength(**self.params)
        except Exception as e:
            logger.error("[CheckNetworkStatus] %s", e)
            return ErrorState()
        return self

class CheckSignalStrength(State):
    """State for checking signal strength."""
    def on_event(self, event):
        try:
            print("Checking signal strength...")
            if event == 'send_payload':
                if _sc_network_type() == 'ethernet':
                    return SendPayload(**self.params)
                row_id, json_str = db_handler.get_json_string()
                if json_str:
                    success = checkMQTTStatus(json_str)
                    if success is True:
                        db_handler.mark_as_sent(row_id)
                else:
                    print("No new data to send. Checking again in 5 seconds.")

                return SendPayload(**self.params)
        except Exception as e:
            logger.error("[CheckSignalStrength] %s", e)
            return ErrorState()
        return self

class SendPayload(State):
    """State for sending payload to the cloud."""
    def on_event(self, event):
        try:
            print("Sending payload to the cloud...")
            if event == 'confirm_delivery':
                main(None, str(7))
                return ConfirmDelivery(**self.params)
        except Exception as e:
            logger.error("[SendPayload] %s", e)
            return ErrorState()
        return self

class ConfirmDelivery(State):
    """State for confirming payload delivery."""
    def on_event(self, event):
        try:
            print("Confirming payload delivery...")
            if event == 'network_check':
                return CheckNetworkStatus(**self.params)
            elif event == 'terminate':
                return TerminateConnection(**self.params)
        except Exception as e:
            logger.error("[ConfirmDelivery] %s", e)
            return ErrorState()
        return self

class TerminateConnection(State):
    """State for terminating the connection."""
    def on_event(self, event):
        try:
            print("Terminating the connection...")
            if event == 'initialize':
                return InitializeModem(**self.params)
        except Exception as e:
            logger.error("[TerminateConnection] %s", e)
            return ErrorState()
        return self

class ChangeOperator(State):
    """State for changing the operator."""
    def on_event(self, event, **kwargs):
        try:
            new_operator_id = kwargs.get('operator_id', None)
            if new_operator_id:
                print("Changing operator to ID:", new_operator_id)
                # Here you would add the logic to change the operator.
                # For this example, we are just simulating a successful change.
                self.params['operator_id'] = new_operator_id
                print("Operator changed successfully.")
                return CheckNetworkStatus(**self.params)
        except Exception as e:
            logger.error("[ChangeOperator] %s", e)
            return ErrorState()
        return self

class ModemSetUp(State):
    """State for modem setup."""
    def on_event(self, event):
        try:
            print("Setting up modem...")
            time.sleep(60)
            reset_device()
            time.sleep(30)
            main(None, str(2))
            #switch_to_esim_sim()
            #switch_to_physical_sim()
#            handle_gsm_modem_mode()
            time.sleep(30)
            
            # After setup, decide where to go next, for example, check network status
            return CheckNetworkStatus(**self.params)
        except Exception as e:
            logger.error("[ModemSetUp] %s", e)
            return ErrorState()

class Context:
    """Context class for maintaining state and handling events."""
    def __init__(self, initial_state, **kwargs):
        self.state = initial_state(**kwargs)

    def on_event(self, event):
        self.state = self.state.on_event(event)

    def __str__(self):
        return str(self.state)


#sudo raspi-config

param1 = 0
param2 = '1'

#param1 = sys.argv[1]
#param2 = sys.argv[2]

attempts = 0


class CavliRunningStatusDatabase_old:
    def __init__(self, db_name='cavliRunningParam.db'):
        self.db_name = db_name
        self.initialize_database()

    def initialize_database(self):
        conn = None
        try:
            conn = get_connection(self.db_name)
            c = conn.cursor()
            c.execute('''CREATE TABLE IF NOT EXISTS cavliRunningParam
                         (id INTEGER PRIMARY KEY, latitude REAL, longitude REAL, dataSending TEXT, modemStatus TEXT, serviceProvider TEXT, simSwap TEXT, IMEI TEXT, SerialNumber TEXT, operatorid INTEGER)''')
            c.execute('SELECT COUNT(*) FROM cavliRunningParam')
            if c.fetchone()[0] == 0:
            # Inserting default values during initialization
              c.execute('''INSERT INTO cavliRunningParam VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''', (1, None, None, None, None, None, None, None, None, None))
              conn.commit()
        except sqlite3.Error as e:
            logger.error("[CavliDB.initialize] %s", e)
        finally:
            if conn:
                conn.close()

    def update_cavli_running_parameters(self, column, value):
        conn = None
        try:
            conn = get_connection(self.db_name)
            c = conn.cursor()
#            c.execute('''UPDATE cavliRunningParam SET {} = ?'''.format(column), (value,))
            c.execute(f'UPDATE cavliRunningParam SET {column} = ? WHERE id = 1', (value,))  # SEC-02: column validated above
            conn.commit()
        except sqlite3.Error as e:
            logger.error("[CavliDB.update] %s", e)
        finally:
            if conn:
                conn.close()

    def retrieve_cavli_running_parameters(self, column):
        conn = None
        try:
            conn = get_connection(self.db_name)
            c = conn.cursor()
#            c.execute('''SELECT {} FROM cavliRunningParam'''.format(column))
            c.execute(f'SELECT {column} FROM cavliRunningParam WHERE id = 1')  # SEC-02: column from validated caller
            result = c.fetchone()
            return result[0] if result else None
        except sqlite3.Error as e:
            logger.error("[CavliDB.retrieve] %s", e)
        finally:
            if conn:
                conn.close()


    # Methods to retrieve individual parameters
    def get_latitude(self):
        return self.retrieve_cavli_running_parameters('latitude')

    def get_longitude(self):
        return self.retrieve_cavli_running_parameters('longitude')

    def get_data_sending(self):
        return self.retrieve_cavli_running_parameters('dataSending')

    def get_modem_status(self):
        return self.retrieve_cavli_running_parameters('modemStatus')

    def get_service_provider(self):
        return self.retrieve_cavli_running_parameters('serviceProvider')

    def get_sim_swap(self):
        return self.retrieve_cavli_running_parameters('simSwap')

    def get_IMEI(self):
        return self.retrieve_cavli_running_parameters('IMEI')
    
    def get_SerialNumber(self):
        return self.retrieve_cavli_running_parameters('SerialNumber')
                

class CavliRunningStatusDatabase:
    # SEC-02: column whitelist prevents SQL injection via .format(column)
    _ALLOWED_COLUMNS = {
        'latitude', 'longitude', 'dataSending', 'modemStatus',
        'serviceProvider', 'simSwap', 'IMEI', 'SerialNumber', 'operatorid',
    }

    def __init__(self, db_name='cavliRunningParam.db'):
        self.db_name = db_name
        self.initialize_database()

    def initialize_database(self):
        conn = None
        try:
            conn = get_connection(self.db_name)
            c = conn.cursor()

            c.execute('''
                CREATE TABLE IF NOT EXISTS cavliRunningParam (
                    id INTEGER PRIMARY KEY,
                    latitude REAL,
                    longitude REAL,
                    dataSending TEXT,
                    modemStatus TEXT,
                    serviceProvider TEXT,
                    simSwap TEXT,
                    IMEI TEXT,
                    SerialNumber TEXT,
                    operatorid INTEGER
                )
            ''')

            c.execute('SELECT COUNT(*) FROM cavliRunningParam')
            if c.fetchone()[0] == 0:
                c.execute('''
                    INSERT INTO cavliRunningParam
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (1, None, None, None, None, None, None, None, None, None))

                conn.commit()

        except sqlite3.Error as e:
            logger.error("[CavliDB.initialize] %s", e)
            logger.error("Error initializing database: %s", e)

        finally:
            if conn:
                conn.close()

    # --------------------------------------------------
    # AUTO CLEAN DATABASE WHEN ROWS EXCEED 200
    # --------------------------------------------------
    def cleanup_database(self):
        conn = None
        try:
            conn = get_connection(self.db_name)
            c = conn.cursor()

            c.execute("SELECT COUNT(*) FROM cavliRunningParam")
            count = c.fetchone()[0]

            if count > 200:
                print("Database size exceeded 200 rows → cleaning old records")

                c.execute("""
                    DELETE FROM cavliRunningParam
                    WHERE rowid NOT IN (
                        SELECT rowid
                        FROM cavliRunningParam
                        ORDER BY rowid DESC
                        LIMIT 20
                    )
                """)

                conn.commit()

        except sqlite3.Error as e:
            print("Error cleaning database:", e)
            logger.error("Error cleaning database: %s", e)

        finally:
            if conn:
                conn.close()

    # --------------------------------------------------
    # UPDATE PARAMETERS
    # --------------------------------------------------
    def update_cavli_running_parameters(self, column, value):
        if column not in self._ALLOWED_COLUMNS:  # SEC-02
            logger.error("[CavliDB] rejected unknown column: %s", column)
            return
        conn = None
        try:
            conn = get_connection(self.db_name)
            c = conn.cursor()

            c.execute(
                f'UPDATE cavliRunningParam SET {column} = ? WHERE id = 1',
                (value,)
            )

            conn.commit()

            # Clean database if needed
            self.cleanup_database()

        except sqlite3.Error as e:
            logger.error("[CavliDB.update] %s", e)

        finally:
            if conn:
                conn.close()

    # --------------------------------------------------
    # RETRIEVE PARAMETERS
    # --------------------------------------------------
    def retrieve_cavli_running_parameters(self, column):
        conn = None
        try:
            conn = get_connection(self.db_name)
            c = conn.cursor()

            c.execute(
                f'SELECT {column} FROM cavliRunningParam WHERE id = 1'  # SEC-02
            )

            result = c.fetchone()
            return result[0] if result else None

        except sqlite3.Error as e:
            logger.error("[CavliDB.retrieve] %s", e)
            logger.error("Error retrieving parameters: %s", e)

        finally:
            if conn:
                conn.close()

    # --------------------------------------------------
    # GET METHODS
    # --------------------------------------------------
    def get_latitude(self):
        return self.retrieve_cavli_running_parameters('latitude')

    def get_longitude(self):
        return self.retrieve_cavli_running_parameters('longitude')

    def get_data_sending(self):
        return self.retrieve_cavli_running_parameters('dataSending')

    def get_modem_status(self):
        return self.retrieve_cavli_running_parameters('modemStatus')

    def get_service_provider(self):
        return self.retrieve_cavli_running_parameters('serviceProvider')

    def get_sim_swap(self):
        return self.retrieve_cavli_running_parameters('simSwap')

    def get_IMEI(self):
        return self.retrieve_cavli_running_parameters('IMEI')

    def get_SerialNumber(self):
        return self.retrieve_cavli_running_parameters('SerialNumber')

    def get_OperatorNumber(self):
        return self.retrieve_cavli_running_parameters('operatorid')


class SerialCommander(object):
    def __init__(self, port='/dev/ttyS0', baudrate=115200, log_file='data_usage_log.json'):
        self.port = port
        self.baudrate = baudrate
        self.ser = None
        self.bytes_sent = 0      # <-- NEW
        self.bytes_received = 0  # <-- NEW
        self.log_file = log_file  # <-- NEW

    def initialize_serial(self):
        self.ser = serial.Serial(self.port, self.baudrate, timeout=1)
        return self.ser

    def test_serial_connection(self):
        return self.ser.isOpen() if self.ser else False

    def close_serial(self):
        if self.ser:
            self.ser.close()
    
    def print_data_usage(self):  # <-- NEW
        print("Data usage: Sent = {} bytes, Received = {} bytes".format(self.bytes_sent, self.bytes_received))
    
    
    def _update_daily_usage(self, sent_bytes, received_bytes):
        self.bytes_sent += sent_bytes
        self.bytes_received += received_bytes
    
    def update_daily_usage_log(self):
#        today = datetime.date.today().isoformat()
        today = dt.date.today().isoformat()
        if os.path.exists(self.log_file):
            with open(self.log_file, 'r') as f:
                try:
                    usage_data = json.load(f)
                except json.JSONDecodeError:
                    usage_data = {}
        else:
            usage_data = {}

        if today not in usage_data:
            usage_data[today] = {'sent': 0, 'received': 0}

        usage_data[today]['sent'] += self.bytes_sent
        usage_data[today]['received'] += self.bytes_received

        with open(self.log_file, 'w') as f:
            json.dump(usage_data, f, indent=2)

        # Reset counters after logging
        self.bytes_sent = 0
        self.bytes_received = 0
    
    
    def print_daily_usage(self):
        if os.path.exists(self.log_file):
            with open(self.log_file, 'r') as f:
                try:
                    usage_data = json.load(f)
                    for date in sorted(usage_data):
                        data = usage_data[date]
                        total = data['sent'] + data['received']
                        print(f"{date} - Sent: {data['sent']} bytes, Received: {data['received']} bytes, Total: {total} bytes")
                except json.JSONDecodeError:
                    logger.warning("[data_usage] Invalid JSON in log file")
        else:
            print("No usage log found.")
            

    def get_total_daily_usage(self):
        """
        Returns a dictionary with total data usage per day in MB (rounded to 3 decimals).
        Example: {'2025-05-06': 1.421, '2025-05-07': 0.734}
        """
        if not os.path.exists(self.log_file):
            print("No usage log found.")
            return {}

        try:
            with open(self.log_file, 'r') as f:
                usage_data = json.load(f)
                total_usage = {}
                for date, data in usage_data.items():
                    total_bytes = data.get('sent', 0) + data.get('received', 0)
                    total_mb = round(total_bytes / (1024 * 1024.0), 3)
                    total_usage[date] = total_mb
                return total_usage
        except json.JSONDecodeError:
            logger.warning("[data_usage] Invalid JSON in log file")
            return {}
    


    def send_command(self, command, expected_response, timeout=1):
        if not self.ser:
            return False

        print(command) 
#        self.ser.write(command + '\r\n')  # Send the command
        encoded_command = command.encode() + b'\r\n'  # <-- NEW
        sent = self.ser.write(encoded_command)
        
        self.ser.timeout = timeout
        response = self.ser.read_until(expected_response.encode())  # Read until expected response or timeout
        #print(response.decode().strip())
        self._update_daily_usage(sent, len(response))   # Track how many bytes were read # <-- NEW

        decoded_response = response.decode().strip()
        if expected_response in decoded_response:
            print("Expected response received:", expected_response)
            return True
        else:
            print("Unexpected response received:", response)
            return False



    #def send_command_and_get_response(self, command, expected_response=None, timeout=1):
        #if not self.ser:
            #return False, None  # Return False and None response if serial connection is not established

        #print(command)
#        self.ser.write(command.encode('utf-8') + '\r\n')  # Send the command with UTF-8 encoding
        #encoded_command = command.encode('utf-8') + b'\r\n'  # <-- NEW
        #sent = self.ser.write(encoded_command)  # <-- NEW
        
        #self.ser.timeout = timeout

        #if expected_response is not None:
            #response = self.ser.read_until(expected_response.encode('utf-8'))  # Read until expected response or timeout
            #self._update_daily_usage(sent, len(response))  # <-- NEW
            
            #try:
                #decoded_response = response.decode('utf-8').strip()
                #print(decoded_response)
            #except UnicodeDecodeError as e:
                #print("Decoding error:", e)
                #return False, None
        #else:
            #response = self.ser.read_until()  # Read until timeout
            #try:
                #decoded_response = response.decode('utf-8').strip()
            #except UnicodeDecodeError as e:
                #print("Decoding error:", e)
                #return False, None

        #if expected_response is not None:
            #if expected_response in decoded_response:
                #print("Expected response received:", expected_response)
                #return True, decoded_response  # Return True and the response
            #else:
                #print("Unexpected response received:", decoded_response)
                #return False, decoded_response  # Return False and the response
        #else:
            # No expected response, just return the response
            #return True, decoded_response

    def send_command_and_get_response(self, command, expected_response=None, timeout=1):
        """
        Send an AT command and read response until expected_response is found or timeout expires.
        Supports long responses (e.g. AT+COPS=? takes up to 180s).
        """
        if not self.ser:
            return False, None

        print(command)
        try:
            if isinstance(command, str):
                encoded_command = command.encode('utf-8') + b'\r\n'
            elif isinstance(command, bytes):
                encoded_command = command
            else:
                raise TypeError("Command must be a string or bytes")

            sent = self.ser.write(encoded_command)
            self._update_daily_usage(sent, 0)
        except Exception as e:
            logger.error("[send_command] %s", e)
            return False, None

        # ---- Continuous read loop ----
        start_time = time.time()
        response = b""
        expected_bytes = expected_response.encode('utf-8') if expected_response else None

        while time.time() - start_time < timeout:
            if self.ser.in_waiting:
                chunk = self.ser.read(self.ser.in_waiting)
                response += chunk
                self._update_daily_usage(0, len(chunk))

                # Stop early if "OK" or "ERROR" appears
                if expected_bytes and expected_bytes in response:
                    break
                if b"ERROR" in response:
                    break

            time.sleep(0.2)  # avoid CPU hogging

        decoded_response = response.decode(errors='ignore').strip()
        print(decoded_response)

        if expected_response:
            if expected_response in decoded_response:
                print("Expected response received:", expected_response)
                return True, decoded_response
            else:
                print("Unexpected or incomplete response")
                return False, decoded_response
        else:
            return True, decoded_response

    
    
    def send_command_and_get_response_original(self, command, expected_response=None, timeout=1):
        if not self.ser:
            return False, None  # Serial connection not established

        print(command)

        # Convert command to bytes
        try:
            if isinstance(command, str):
                encoded_command = command.encode('utf-8') + b'\r\n'
                sent = self.ser.write(encoded_command)  # <-- NEW
            elif isinstance(command, bytes):
                encoded_command = command  # Already properly encoded
                sent = self.ser.write(encoded_command)  # <-- NEW
            else:
                raise TypeError("Command must be a string or bytes")

            #self.ser.write(encoded_command)
            self.ser.timeout = timeout
        except Exception as e:
            logger.error("[send_command] %s", e)
            return False, None

        # Read the response
        try:
            if expected_response is not None:
                response = self.ser.read_until(expected_response.encode('utf-8'))
                self._update_daily_usage(sent, len(response))  # <-- NEW
            else:
                response = self.ser.read_until()

            decoded_response = response.decode('utf-8').strip()
            print(decoded_response)
        except UnicodeDecodeError as e:
            logger.error("[serial] UnicodeDecodeError: %s", e)
            return False, None

        # Check expected response
        if expected_response is not None:
            if expected_response in decoded_response:
                print("Expected response received:", expected_response)
                return True, decoded_response
            else:
                print("Unexpected response received:", decoded_response)
                return False, decoded_response
        else:
            return True, decoded_response


    def send_command_and_get_response_non_ascii_format(self, command, expected_response=None, timeout=1):
        if not self.ser:
            return False, None  # Return False and None response if serial connection is not established

        print(command) 
#        self.ser.write(command.encode() + b'\r\n')  # Send the command
        encoded_command = command.encode() + b'\r\n'
        sent = self.ser.write(encoded_command)
        
        self.ser.timeout = timeout

        response = None
        if expected_response is not None:
            response = self.ser.read_until(expected_response.encode())  # Read until expected response or timeout
            self._update_daily_usage(sent, len(response))  # <-- NEW
            print(response.decode().strip())
        else:

            pass

        if expected_response is not None:
            if expected_response in response:
                print("Expected response received:", expected_response)
                return True, response.decode().strip()  # Return True and the response
            else:
                print("Unexpected response received:", response)
                return False, response.decode().strip()  # Return False and the response
        else:
            # No expected response, just return the response
            #return True, response.decode().strip()
            return True

    def send_command_get_response_with_encoding(self, command, expected_response=None, timeout=1, encoding='utf-8'):
        if not self.ser:
            return False, None  # Return False and None response if serial connection is not established

        print(command)
        try:
#            self.ser.write(command.encode(encoding) + b'\r\n')  # Send the command with specified encoding
            encoded_command = command.encode(encoding) + b'\r\n'  # <-- NEW
            sent = self.ser.write(encoded_command)   # <-- NEW
        except UnicodeEncodeError as e:
            logger.error("[serial] UnicodeEncodeError: %s", e)
            return False, None

        self.ser.timeout = timeout

        if expected_response is not None:
            
            try:
                response = self.ser.read_until(expected_response.encode(encoding))  # Read until expected response or timeout
                self._update_daily_usage(sent, len(response))   # <-- NEW
                decoded_response = response.decode(encoding).strip()
                print(decoded_response)
            except (UnicodeDecodeError, UnicodeEncodeError) as e:
                logger.error("[serial] Unicode codec error: %s", e)
                return False, None
        else:
            try:
                response = self.ser.read_until()  # Read until timeout
                decoded_response = response.decode(encoding).strip()
            except (UnicodeDecodeError, UnicodeEncodeError) as e:
                logger.error("[serial] Unicode codec error: %s", e)
                return False, None

        if expected_response is not None:
            if expected_response in decoded_response:
                print("Expected response received:", expected_response)
                return True, decoded_response  # Return True and the response
            else:
                print("Unexpected response received:", decoded_response)
                return False, decoded_response  # Return False and the response
        else:
            # No expected response, just return the response
            return True, decoded_response

    def send_command_and_print_response(self, command, timeout=1):
        success, response = self.read_serial_response(command, timeout)
        if success:
            print(response)
        return success, response  

    def read_serial_response(self, command, timeout=1):
        if not self.ser:
            return False, None  # Return False and None response if serial connection is not established

#        self.ser.write(command.encode('utf-8') + b'\r\n')  # Send the command with UTF-8 encoding
        encoded_command = command.encode('utf-8') + b'\r\n'  # <-- NEW
        sent = self.ser.write(encoded_command)   # <-- NEW
        
        self.ser.timeout = timeout

        response = b''
        while True:
            part = self.ser.read(self.ser.in_waiting or 1)
            if not part:
                break
            response += part
            time.sleep(0.1)  # Give time for more data to arrive
        
        self._update_daily_usage(sent, len(response)) # <-- NEW
        
        try:
            decoded_response = response.decode('utf-8').strip()
        except UnicodeDecodeError:
            try:
                decoded_response = response.decode('latin-1').strip()
            except UnicodeDecodeError as e:
                logger.error("[serial] UnicodeDecodeError: %s", e)
                return False, None

        return True, decoded_response


    def load_cert(self, cert_type, cert_id, pem_data, label='cert'):
        """Load a PEM cert/key into C16QS flash via AT+MQTTSLOAD.
        cert_type: 1=CA, 2=client-cert, 3=priv-key. cert_id must be >= 1."""
        if not self.ser:
            return False
        cmd = 'AT+MQTTSLOAD=1,{},{}'.format(cert_type, cert_id)
        encoded_cmd = cmd.encode() + b'\r\n'
        sent = self.ser.write(encoded_cmd)
        self.ser.timeout = 5
        prompt = self.ser.read_until(b'>').decode(errors='replace')
        if '>' not in prompt:
            logger.warning("[x509] %s: no prompt — %s", label, repr(prompt.strip()))
            return False
        payload = pem_data.encode() + b'\x1a'
        self.ser.write(payload)
        self._update_daily_usage(sent + len(payload), 0)
        self.ser.timeout = 8
        resp = self.ser.read_until(b'OK').decode(errors='replace')
        self._update_daily_usage(0, len(resp))
        if 'SAVED' in resp:
            logger.info("[x509] %s loaded OK", label)
            return True
        logger.warning("[x509] %s load failed: %s", label, repr(resp.strip()))
        return False

    def clear_serial_port(self):
        try:
            # Flush input and output buffers
            self.ser.flushInput()
            self.ser.flushOutput()
            #print("Serial port cleared successfully.")
        except Exception as e:
            #print("Error: ", e)
            pass

def print_daily_usage_summary():
    serial_commander = SerialCommander()
    serial_commander.initialize_serial()

    if not serial_commander.test_serial_connection():
        print("Serial connection failed.")
        return False

    totals = serial_commander.get_total_daily_usage()
    print("Data Usage Summary:")
    
    usage_list = []
    for day, mb in totals.items():
        print("{}: {} MB".format(day, mb))
        usage_list.append({
            "Date": day,
            "usage": f"{mb} MB"
        })

    # Prepare the log message in the desired format
    log_data = {
        "Total_Data_Usage": usage_list
    }
    
    # Convert to JSON and insert into DB
    attributes_json = json.dumps(log_data)
    try:
        insert_json_to_db(attributes_json)
    except Exception as e:
        logger.error("[update_daily_usage_log] DB insert failed: %s", e)
    
    serial_commander.clear_serial_port()
    serial_commander.close_serial()
    return True


#def check_and_notify_usage_limit(limit_mb=25):
#    serial_commander = SerialCommander()
#    serial_commander.initialize_serial()

#    if not serial_commander.test_serial_connection():
#        print("Serial connection failed.")
#        return False

#    usage_data = serial_commander.get_total_daily_usage()
#    serial_commander.clear_serial_port()
#    serial_commander.close_serial()

#    for date, usage_mb in usage_data.items():
#        if usage_mb >= limit_mb:
#            notification = {
#                "Data Usage Alert": {
#                    "Date": date,
#                    "Usage": f"{usage_mb} MB",
#                    "Message": f"Alert! Data usage exceeded {limit_mb} MB."
#                }
#            }
#            try:
#                insert_json_to_db(json.dumps(notification))
#                print(f"Notification sent for {date}: {usage_mb} MB")
#            except Exception as e:
#                print(f"Failed to send notification: {e}")

#    return True

# Notify if usage exceeds limit once
def check_and_notify_usage_limit(limit_mb=25, notify_log_file='notified_dates.json'):
    serial_commander = SerialCommander()
    serial_commander.initialize_serial()

    if not serial_commander.test_serial_connection():
        print("Serial connection failed.")
        return False

    usage_data = serial_commander.get_total_daily_usage()
    serial_commander.clear_serial_port()
    serial_commander.close_serial()

    # Load existing notifications
    if os.path.exists(notify_log_file):
        with open(notify_log_file, 'r') as f:
            try:
                notified_data = json.load(f)
            except json.JSONDecodeError:
                notified_data = {}
    else:
        notified_data = {}

    for date, usage_mb in usage_data.items():
        already_notified_limit = notified_data.get(date, 0)

        # Notify if usage exceeds the new limit and we haven't notified at this level yet
        if usage_mb >= limit_mb and usage_mb >= already_notified_limit and limit_mb > already_notified_limit:
            log_data = {
                "Data_Limit_Notification": {
                    "Date": date,
                    "usage": f"{usage_mb} MB",
                    "message": f"Data usage exceeded {limit_mb} MB"
                }
            }
            attributes_json = json.dumps(log_data)
            insert_json_to_db(attributes_json)
            print(f"Notification sent for {date} at {limit_mb} MB (usage: {usage_mb} MB)")

            # Update the stored limit
            notified_data[date] = limit_mb

    # Save the updated notification status
    with open(notify_log_file, 'w') as f:
        json.dump(notified_data, f, indent=2)

    return True



cavli_database = CavliRunningStatusDatabase()

# --- Default SIM state on boot (physical) ---
#cavli_database.update_cavli_running_parameters('simSwap', 'physical')
#print("Default SIM set to Physical on startup")


# --- Check Menu based selection (esim/physical) ---
current_sim = cavli_database.get_sim_swap()

if not current_sim:
    cavli_database.update_cavli_running_parameters('simSwap', 'physical')
    print("First boot: Default SIM set to Physical")
else:
    print(f"Reboot detected: Keeping SIM = {current_sim}")


def change_operator(operator_code):
    
    serial_commander = SerialCommander()
    serial_commander.initialize_serial()

    if serial_commander.test_serial_connection():
        #print("Serial connection established.")
        pass
    else:
        print("Serial connection failed.")
        return False

    tryConnCommand = [
        ('AT+COPS=1,2,"{}",7'.format(operator_code), 'OK', 2),
        #('AT+COPS=0', 'OK', 5),
#        ('AT+TRB', 'RDY', 30)
    ]

    # Execute commands sequentially
    for command, expected_response, delay in tryConnCommand:
        if not serial_commander.send_command(command, expected_response, delay):
            print("Error occurred while executing command:", command)
            return False
    
    # Log the usage now
    serial_commander.update_daily_usage_log()
    
    serial_commander.clear_serial_port()
    serial_commander.close_serial()

    initialize_gnss()
    
    return True


import time
import re
from operator_db import get_priority_operator_list, init_operator_database

def scan_available_operators():
    serial_commander = SerialCommander()
    serial_commander.initialize_serial()

    if not serial_commander.test_serial_connection():
        print("Serial connection failed.")
        return False, None

    command = 'AT+COPS=?'
    expected_response = 'OK'
    delay = 180  # up to 3 minutes

    print("Scanning for available operators via AT+COPS=? ...")

    success, response = serial_commander.send_command_and_get_response(command, expected_response, delay)

    if not success or not response:
        print("Failed to scan operators — invalid or no response.")
        serial_commander.close_serial()
        return False, None

    # Close port cleanly after scan
    serial_commander.clear_serial_port()
    serial_commander.close_serial()

    # Return both success flag and raw modem response
    return True, response


EXPECTED_OPERATOR_CODE = None
_stored_op = cavli_database.get_OperatorNumber()
if _stored_op:
    EXPECTED_OPERATOR_CODE = str(_stored_op)
    print(f"Restored EXPECTED_OPERATOR_CODE from DB: {EXPECTED_OPERATOR_CODE}")

def autoswitch_operator(_sc, change_operator, switch_to_physical_sim, db_name="operator_codes.db"):
    """
    Automatically switch between operators based on priority.
    - Scans for available operators (AT+COPS=?)
    - Checks which are in priority list
    - Tries each operator up to 3 times
    - Falls back to Physical SIM if all fail
    """
    global EXPECTED_OPERATOR_CODE
    
    print("\n=== (eSIM) AUTO OPERATOR SWITCH MODE (eSIM) ===")

    # Step 1: Ensure DB exists
    init_operator_database()

    # Step 2: Perform network operator scan
    scan_success, scan_response = scan_available_operators()
    if not scan_success or not scan_response:
        print("Network scan failed. Switching to Physical SIM.")
        switch_to_physical_sim()
        return "Physical SIM"

    # Step 3: Extract numeric operator codes
    available_codes = re.findall(r'\d{5,6}', scan_response)
    if not available_codes:
        print("No operator codes detected in response. Switching to Physical SIM.")
        switch_to_physical_sim()
        return "Physical SIM"

    print("Detected available operator codes:", available_codes)

    # Step 4: Get prioritized operator list from DB
    priority_operators = get_priority_operator_list(available_codes, db_name)
    if not priority_operators:
        print("No matching prioritized operators found. Switching to Physical SIM.")
        switch_to_physical_sim()
        return "Physical SIM"

    # Step 5: Try each operator (3 retries)
    for code, name, priority in priority_operators:
        print(f"\n=== Trying to register on {name} (Code: {code}, Priority: {priority}) ===")
        for attempt in range(1, 4):
            print(f"Attempt {attempt}/3 to register on {name} ...")

            if change_operator(str(code)):  # call your existing function
                EXPECTED_OPERATOR_CODE = str(code)  # <-- SAVE EXPECTED CODE
                print(f"Successfully registered on {name} (Code: {code})")
                return name
            else:
                print(f"Failed to register on {name} (Attempt {attempt}/3). Retrying in 5s...")
                time.sleep(5)

        print(f"All 3 attempts failed for {name}. Trying next operator...")

    # Step 6: Fallback
    print("All prioritized operators failed. Switching to Physical SIM...")
    switch_to_physical_sim()
    return "Physical SIM"



def initialize_device():
    serial_commander = SerialCommander()
    serial_commander.initialize_serial()

    if serial_commander.test_serial_connection():
        #print("Serial connection established.")
        pass
    else:
        print("Serial connection failed.")
        return False

    commands = [
        ('AT', 'OK', 1),
        ('ATQ0', 'OK', 1),
        ('AT+COPS?', 'OK', 5),
        ('AT+CEREG?', 'OK', 2),
        ('AT+CGACT?', 'OK', 1)
    ]

    # Execute commands sequentially
    for command, expected_response, delay in commands:
        if not serial_commander.send_command(command, expected_response, delay):
            print("Error occurred while executing command:", command)
            return False
    
    # Log the usage now
    serial_commander.update_daily_usage_log()
    
    serial_commander.clear_serial_port()
    serial_commander.close_serial()
    return True


def initialize_gnss():
    serial_commander = SerialCommander()
    serial_commander.initialize_serial()

    if serial_commander.test_serial_connection():
        print("Serial connection established.")
        #pass
    else:
        print("Serial connection failed.")
        #pass
        #return False

    commands = [
        ('AT+CGPS=1', 'OK', 2)
    ]

    # Execute commands sequentially
    for command, expected_response, delay in commands:
        if not serial_commander.send_command(command, expected_response, delay):
            print("Error occurred while executing command:", command)
            #return False
    
    # Log the usage now
    serial_commander.update_daily_usage_log()
    
    serial_commander.clear_serial_port()
    serial_commander.close_serial()
    #return True


def operator_info():
    serial_commander = SerialCommander()
    serial_commander.initialize_serial()

    if serial_commander.test_serial_connection():
        #print("Serial connection established.")
        pass
    else:
        print("Serial connection failed.")
        return False

    commands = [
        ('AT+COPS?', 'OK', 10),
    ]

    # Execute commands sequentially
    #for command, expected_response, delay in commands:
    #    if not serial_commander.send_command(command, expected_response, delay):
    #        print("Error occurred while executing command:", command)
    #        return False
    response = None
    for command, expected_response, delay in commands:
        success, response = serial_commander.send_command_and_get_response(command, expected_response, delay)

    getOperatorInfo(response)
    
    # Log the usage now
    serial_commander.update_daily_usage_log()
    
    serial_commander.clear_serial_port()
    serial_commander.close_serial()
    return True

#success, response 

def check_network_ip():
    serial_commander = SerialCommander()
    serial_commander.initialize_serial()

    if serial_commander.test_serial_connection():
        #print("Serial connection established.")
        pass
    else:
        print("Serial connection failed.")
        return False

    chkNetIPCommand = [
        ('AT+CDNSGIP="mqtt.thingsboard.cloud"', 'OK', 5)
    ]

    # Execute commands sequentially
    for command, expected_response, delay in chkNetIPCommand:
        if not serial_commander.send_command(command, expected_response, delay):
            print("Error occurred while executing command:", command)
            return False
    
    # Log the usage now
    serial_commander.update_daily_usage_log()
    
    serial_commander.clear_serial_port()
    serial_commander.close_serial()
    return True

def get_IMEI_number():
    serial_commander = SerialCommander()
    serial_commander.initialize_serial()

    if serial_commander.test_serial_connection():
        #print("Serial connection established.")
        pass
    else:
        print("Serial connection failed.")
        return False

    commands = [
        ('ATI', 'OK', 10),
    ]

    #for command, expected_response, delay in commands:
    #    success, response = serial_commander.send_command_and_get_response_non_ascii_format(command, expected_response, delay)

    # Send the ATI command and print the response
    response = serial_commander.send_command_and_print_response('ATI')
    #print(response)

    # Extract the second element from the tuple (the string)
    response_string = response[1]

    # Split the response into lines
    lines = response_string.split('\r\n')

    # Initialize a dictionary to store the parsed values
    parsed_values = {}

    # Loop through each line and split into key-value pairs
    for line in lines:
        if ': ' in line:
            key, value = line.split(': ', 1)
            parsed_values[key] = value
        elif line.strip() != "":  # Ignore empty lines
            parsed_values['Status'] = line.strip()

    # Accessing specific information and assigning to variables
    manufacturer = parsed_values.get("Manufacturer")
    model_name = parsed_values.get("Model Name")
    description = parsed_values.get("Description")
    firmware_release = parsed_values.get("Firmware Release")
    imei = parsed_values.get("IMEI")
    serial_number = parsed_values.get("Serial Number")
    hw_version = parsed_values.get("HW Version")
    part_number = parsed_values.get("Part Number")
    build_date = parsed_values.get("Build Date")

    # Optionally, print the variables for verification
#    print 'Manufacturer:', manufacturer
#    print 'Model Name:', model_name
#    print 'Description:', description
#    print 'Firmware Release:', firmware_release
    print('IMEI:', imei)
    print('Serial Number:', serial_number)
#    print 'HW Version:', hw_version
#    print 'Part Number:', part_number
#    print 'Build Date:', build_date

    # Close the serial connection
    #serial_commander.close_serial()

    cavli_database.update_cavli_running_parameters('IMEI', imei)
    cavli_database.update_cavli_running_parameters('SerialNumber', serial_number)
    
    # Log the usage now
    serial_commander.update_daily_usage_log()
    
    serial_commander.clear_serial_port()
    serial_commander.close_serial()
    return True


def try_connection():
    serial_commander = SerialCommander()
    serial_commander.initialize_serial()

    if serial_commander.test_serial_connection():
        #print("Serial connection established.")
        pass
    else:
        print("Serial connection failed.")
        return False

    tryConnCommand = [
        ('AT+CFUN=0', 'OK', 1),
        ('AT+CFUN=1', 'OK', 1),
        ('AT+CIMI', 'OK', 1)
    ]

    # Execute commands sequentially
    for command, expected_response, delay in tryConnCommand:
        if not serial_commander.send_command(command, expected_response, delay):
            print("Error occurred while executing command:", command)
            return False
    
    # Log the usage now
    serial_commander.update_daily_usage_log()
    
    serial_commander.clear_serial_port()
    serial_commander.close_serial()
    return True

def reset_device():
    serial_commander = SerialCommander()
    serial_commander.initialize_serial()

    if serial_commander.test_serial_connection():
        #print("Serial connection established.")
        pass
    else:
        print("Serial connection failed.")
        return False

    rstCommands = [
        ('AT+TRB', 'OK', 30)
    ]

    # Execute commands sequentially
    for command, expected_response, delay in rstCommands:
        #if not serial_commander.send_command(command, expected_response, delay):
        if not serial_commander.send_command_and_get_response(command, expected_response, delay):
            print("Error occurred while executing command:", command)
            time.sleep(10)
            return False
    
    # Log the usage now
    serial_commander.update_daily_usage_log()
    
    serial_commander.clear_serial_port()
    serial_commander.close_serial()
    
    time.sleep(15)

    initialize_gnss()

    return True


# Let's Encrypt R13 intermediate CA — signs thingsboard.cloud server cert.
# Valid 2024-03-13 → 2027-03-12. Update when expired.
_R13_CA_CERT = """\
-----BEGIN CERTIFICATE-----
MIIDqDCCAy6gAwIBAgIRAPNkTmtuAFAjfglGvXvh9R0wCgYIKoZIzj0EAwMwgYgx
CzAJBgNVBAYTAlVTMRMwEQYDVQQIEwpOZXcgSmVyc2V5MRQwEgYDVQQHEwtKZXJz
ZXkgQ2l0eTEeMBwGA1UEChMVVGhlIFVTRVJUUlVTVCBOZXR3b3JrMS4wLAYDVQQD
EyVVU0VSVHJ1c3QgRUNDIENlcnRpZmljYXRpb24gQXV0aG9yaXR5MB4XDTE4MTEw
MjAwMDAwMFoXDTMwMTIzMTIzNTk1OVowgY8xCzAJBgNVBAYTAkdCMRswGQYDVQQI
ExJHcmVhdGVyIE1hbmNoZXN0ZXIxEDAOBgNVBAcTB1NhbGZvcmQxGDAWBgNVBAoT
D1NlY3RpZ28gTGltaXRlZDE3MDUGA1UEAxMuU2VjdGlnbyBFQ0MgRG9tYWluIFZh
bGlkYXRpb24gU2VjdXJlIFNlcnZlciBDQTBZMBMGByqGSM49AgEGCCqGSM49AwEH
A0IABHkYk8qfbZ5sVwAjBTcLXw9YWsTef1Wj6R7W2SUKiKAgSh16TwUwimNJE4xk
IQeV/To14UrOkPAY9z2vaKb71EijggFuMIIBajAfBgNVHSMEGDAWgBQ64QmG1M8Z
wpZ2dEl23OA1xmNjmjAdBgNVHQ4EFgQU9oUKOxGG4QR9DqoLLNLuzGR7e64wDgYD
VR0PAQH/BAQDAgGGMBIGA1UdEwEB/wQIMAYBAf8CAQAwHQYDVR0lBBYwFAYIKwYB
BQUHAwEGCCsGAQUFBwMCMBsGA1UdIAQUMBIwBgYEVR0gADAIBgZngQwBAgEwUAYD
VR0fBEkwRzBFoEOgQYY/aHR0cDovL2NybC51c2VydHJ1c3QuY29tL1VTRVJUcnVz
dEVDQ0NlcnRpZmljYXRpb25BdXRob3JpdHkuY3JsMHYGCCsGAQUFBwEBBGowaDA/
BggrBgEFBQcwAoYzaHR0cDovL2NydC51c2VydHJ1c3QuY29tL1VTRVJUcnVzdEVD
Q0FkZFRydXN0Q0EuY3J0MCUGCCsGAQUFBzABhhlodHRwOi8vb2NzcC51c2VydHJ1
c3QuY29tMAoGCCqGSM49BAMDA2gAMGUCMEvnx3FcsVwJbZpCYF9z6fDWJtS1UVRs
cS0chWBNKPFNpvDKdrdKRe+oAkr2jU+ubgIxAODheSr2XhcA7oz9HmedGdMhlrd9
4ToKFbZl+/OnFFzqnvOhcjHvClECEQcKmc8fmA==
-----END CERTIFICATE-----
"""

# Activation requires (all done before restarting this service):
#   1. fleet-ca.crt uploaded to ThingsBoard as trusted CA
#   2. Device credentials changed to X.509 (docker/provision_device_x509.py)
#   3. device.crt + device.key deployed to Pi at /home/pi/Test3/certs/
_X509_CONN_ENABLED = True

_x509_certs_loaded = False


def load_x509_certs(sc):
    """Load R13 CA, device.crt, device.key into C16QS modem flash.
    Uses cert_id=1 for all three types. Returns True if mTLS is ready."""
    global _x509_certs_loaded
    if _x509_certs_loaded:
        return True
    cert_dir = '/home/pi/Test3/certs'
    crt_path = os.path.join(cert_dir, 'device.crt')
    key_path = os.path.join(cert_dir, 'device.key')
    if not (os.path.exists(crt_path) and os.path.exists(key_path)):
        logger.info("[x509] cert files not found at %s — MQTT Basic auth", cert_dir)
        return False
    try:
        with open(crt_path) as f:
            device_crt = f.read()
        with open(key_path) as f:
            device_key = f.read()
    except OSError as e:
        logger.warning("[x509] failed to read cert files: %s", e)
        return False
    ok1 = sc.load_cert(1, 1, _R13_CA_CERT, 'R13 CA cert')
    ok2 = sc.load_cert(2, 1, device_crt,   'device.crt')
    ok3 = sc.load_cert(3, 1, device_key,   'device.key')
    _x509_certs_loaded = ok1 and ok2 and ok3
    if _x509_certs_loaded:
        logger.info("[x509] all certs loaded — mTLS enabled for GSM path")
    else:
        logger.warning("[x509] cert loading incomplete (CA=%s crt=%s key=%s) — falling back to MQTT Basic", ok1, ok2, ok3)
    return _x509_certs_loaded


def connect_to_server():
    clean_mqtt_session()

    clientId = str(modem_config_db.get_parameter('client_id'))
    userName = str(modem_config_db.get_parameter('user_name'))
    password = str(modem_config_db.get_parameter('password'))
    
    serial_commander = SerialCommander()
    serial_commander.initialize_serial()

    if serial_commander.test_serial_connection():
        #print("Serial connection established.")
        pass
    else:
        print("Serial connection failed.")
        return False

#    connServerCommand = [
#        ('AT+MQTTCREATE="mqtt.thingsboard.cloud",1883,"{}",90,0,"{}","{}"'.format(clientId, userName, password), 'OK', 15),
#        ('AT+MQTTCONN=3', 'OK', 30),
#        ('AT+MQTTSUBUNSUB=3,"v1/devices/me/telemetry",1,1', 'OK', 10)
#    ]

    # Load certs and use mTLS ONLY when _X509_CONN_ENABLED=True.
    # Loading a CA cert into the modem changes its TLS trust store even for connections
    # that don't specify cert IDs — this breaks AT+MQTTSCONN=3 (TLS Basic) until the
    # modem is properly configured end-to-end (fleet CA registered in ThingsBoard +
    # credential type changed to X.509). Do not pre-load certs before that point.
    if _X509_CONN_ENABLED:
        certs_loaded = load_x509_certs(serial_commander)
        use_mtls = certs_loaded
    else:
        use_mtls = False

    # AT+MQTTSCONN=3,1,1,1 → mTLS (ca_cert_id=1, client_cert_id=1, prv_key_id=1)
    # AT+MQTTSCONN=3        → TLS server-only, MQTT Basic (username/password) auth

    mqttsconn_cmd = 'AT+MQTTSCONN=3,1,1,1' if use_mtls else 'AT+MQTTSCONN=3'
    logger.info("[x509] connect_to_server: %s (x509_enabled=%s)",
                mqttsconn_cmd, _X509_CONN_ENABLED)

    connServerCommand = [
        # Create secure MQTTS session (port 8883, last param '1' enables SSL)
        ('AT+MQTTCREATE="mqtt.thingsboard.cloud",8883,"{}",90,0,"{}","{}",1'.format(clientId, userName, password), 'OK', 15),

        # Connect with mTLS (cert_ids 1,1,1) or TLS Basic depending on cert availability
        (mqttsconn_cmd, 'OK', 30),

        # Subscribe to telemetry topic
        ('AT+MQTTSUBUNSUB=3,"v1/devices/me/telemetry",1,1', 'OK', 10),
        #rpc
        ('AT+MQTTSUBUNSUB=3,"v1/devices/me/rpc/request/+",1,1', 'OK', 20)
    ]


    # Execute commands sequentially
    for command, expected_response, delay in connServerCommand:
        if command == mqttsconn_cmd:
            # Use full-response variant so CONNECTION EXIST can be distinguished from a real error.
            # When the modem auto-reconnects between our check and this call, it replies
            # "+MQTTSCONN: CONNECTION EXIST\r\nERROR" — treat that as already-connected, not a failure.
            ok, resp = serial_commander.send_command_and_get_response(command, expected_response, delay)
            if not ok:
                if resp and 'CONNECTION EXIST' in resp:
                    logger.info("[connect] AT+MQTTSCONN: CONNECTION EXIST — modem already connected, continuing")
                else:
                    print("Error occurred while executing command:", command)
                    return False
        else:
            if not serial_commander.send_command(command, expected_response, delay):
                print("Error occurred while executing command:", command)
                return False

    # Log the usage now
    serial_commander.update_daily_usage_log()

    serial_commander.clear_serial_port()
    serial_commander.close_serial()
    return True


def connect_to_server_old():
    serial_commander = SerialCommander()
    serial_commander.initialize_serial()

    if serial_commander.test_serial_connection():
        #print("Serial connection established.")
        pass
    else:
        print("Serial connection failed.")
        return False

    #Dexter6.1 : {clientId:"jgtgnopl9ba4fwsvthij",userName:"i9mr50dbhkfu58jgebbm",password:"47oip8zdftslhokdyl61"}
    #Dexter6.2 : {clientId:"aydo1t1mweyoe3zs939m",userName:"vtyf59jmg8gmi7xi7vqx",password:"v5v2x0vkffly0gtsz3vt"}
    #Dexter6.3 : {clientId:"a60alowglf2wr7r3beuj",userName:"s4i1x2geszkz6oj7q8f2",password:"8hqpdy6qlhtgtptno2e6"}
    #Dexter6.4 : {clientId:"tzth27bnb75she6je3qc",userName:"so3ohvpnoki52ti1k39k",password:"0ky6hfeny57rn7pcbhrv"}
    #Dexter6.5 : {clientId:"u8vv15xntm7ej2ykym2u",userName:"417d8yts3p3zxi8888r7",password:"lcpvry6rzqo1m60l3z1b"}
    
    connServerCommand = [
        ('AT+MQTTCREATE="mqtt.thingsboard.cloud",1883,"jgtgnopl9ba4fwsvthij",90,0,"i9mr50dbhkfu58jgebbm","47oip8zdftslhokdyl61"', 'OK', 15), # 6.1
        #('AT+MQTTCREATE="mqtt.thingsboard.cloud",1883,"aydo1t1mweyoe3zs939m",90,0,"vtyf59jmg8gmi7xi7vqx","v5v2x0vkffly0gtsz3vt"', 'OK', 15),  # 6.2                              
        #('AT+MQTTCREATE="mqtt.thingsboard.cloud",1883,"a60alowglf2wr7r3beuj",90,0,"s4i1x2geszkz6oj7q8f2","8hqpdy6qlhtgtptno2e6"', 'OK', 15), # 6.3
        #('AT+MQTTCREATE="mqtt.thingsboard.cloud",1883,"tzth27bnb75she6je3qc",90,0,"so3ohvpnoki52ti1k39k","0ky6hfeny57rn7pcbhrv"', 'OK', 15), # 6.4
        #('AT+MQTTCREATE="mqtt.thingsboard.cloud",1883,"u8vv15xntm7ej2ykym2u",90,0,"417d8yts3p3zxi8888r7","lcpvry6rzqo1m60l3z1b"', 'OK', 15), # 6.5
        ('AT+MQTTCONN=3', 'OK', 30),
        ('AT+MQTTSUBUNSUB=3,"v1/devices/me/telemetry",1,1', 'OK', 10)
    ]

    # Execute commands sequentially
    for command, expected_response, delay in connServerCommand:
        if not serial_commander.send_command(command, expected_response, delay):
            print("Error occurred while executing command:", command)
            return False

    # Log the usage now
    serial_commander.update_daily_usage_log()
    
    serial_commander.clear_serial_port()
    serial_commander.close_serial()
    return True

def clean_mqtt_session():
    """Properly resets the MQTT connection before starting a new session."""
    global _x509_certs_loaded
    print("Cleaning MQTT session...")
    try:
        serial_commander = SerialCommander()
        serial_commander.initialize_serial()
        serial_commander.send_command('AT+MQTTDISCONN=3', 'OK', 5)
        serial_commander.send_command('AT+MQTTDELETE=3', 'OK', 5)
        serial_commander.clear_serial_port()
        serial_commander.close_serial()
        _x509_certs_loaded = False
        print("Cleaned up old MQTT session.")
    except serial.SerialException as e:
        logger.warning("[clean_mqtt_session] SerialException: %s", e)
        time.sleep(5)
    except Exception as e:
        logger.error("[clean_mqtt_session] Failed: %s", e)
        time.sleep(2)


def check_mqtt_status():
    serial_commander = SerialCommander()
    serial_commander.initialize_serial()

    if serial_commander.test_serial_connection():
        pass
    else:
        print("Serial connection failed.")
        return False

    # Use full-response read so we can inspect the buffer when modem is mid-reconnect.
    # The modem may return +MQTTSTATUS: 0 immediately followed by +MQTTSCONN: 3: CONNECTED,1
    # in the same read window when its built-in auto-reconnect fires between our poll cycles.
    ok, resp = serial_commander.send_command_and_get_response('AT+MQTTSTATUS=3', '+MQTTSTATUS: 1', 3)
    if not ok:
        if resp and 'CONNECTED' in resp:
            # Transient status=0 caught mid-reconnect; modem already back up in same buffer.
            logger.info("[mqtt_status] transient +MQTTSTATUS: 0 but CONNECTED seen — treating as connected")
        else:
            print("Error occurred while executing command: AT+MQTTSTATUS=3")
            serial_commander.clear_serial_port()
            serial_commander.close_serial()
            return False

    serial_commander.update_daily_usage_log()
    serial_commander.clear_serial_port()
    serial_commander.close_serial()
    return True


def switch_sim(sim_type):
    if sim_type not in ['physical', 'esim']:
        print("Invalid SIM type.")
        return False

    serial_commander = SerialCommander()
    try:
        serial_commander.initialize_serial()
    except Exception as e:
        logger.error("[initialize_device] %s", e)
        return False

    if not serial_commander.test_serial_connection():
        print("Serial connection failed.")
        return False

    sim_command = 'AT^SIMSWAP=1' if sim_type == 'physical' else 'AT^SIMSWAP=0'

    commands = [
        (sim_command, 'OK', 30),
        ('AT+TRB', 'OK', 120),
        ('AT^SIMSWAP?', 'OK', 30)
    ]

    max_retries = 3
    for i, (command, expected_response, delay) in enumerate(commands):
        success = False
        for attempt in range(max_retries):
            if serial_commander.send_command(command, expected_response, delay):
                success = True
                break
            else:
                print("Attempt {} for command {} failed.".format(attempt + 1, command))
                time.sleep(1)  # Adding a small delay between retries
        if not success:
            print("Command {} failed after {} attempts.".format(command, max_retries))
            serial_commander.clear_serial_port()
            serial_commander.close_serial()
            return False
        # Wait for 30 seconds after the 'AT+TRB' command before sending the next command
        if command == 'AT+TRB':
            print("Waiting for 30 seconds before sending the next command.")
            time.sleep(30)
    
    # Log the usage now
    serial_commander.update_daily_usage_log()
    
    serial_commander.clear_serial_port()
    serial_commander.close_serial()

    initialize_gnss()
    
    return True

#def get_lat_long_old():
#    serial_commander = SerialCommander()
#    serial_commander.initialize_serial()

#    if serial_commander.test_serial_connection():
#        print("Serial connection established.")
        #pass
#    else:
#        print("Serial connection failed.")
        #return False

#    tryConnCommand = [
        #('AT+CGPS=1', 'OK', 1),
#        ('AT+CGPSGPOS=5', 'OK', 1)
#    ]

    # Execute commands sequentially
#    for command, expected_response, delay in tryConnCommand:
#        if not serial_commander.send_command(command, expected_response, delay):
#            print("Error occurred while executing command:", command)
            #return False

#    serial_commander.clear_serial_port()
#    serial_commander.close_serial()
    #return True


def get_lat_long():
    serial_commander = SerialCommander()
    serial_commander.initialize_serial()

    if serial_commander.test_serial_connection():
        print("Serial connection established.")
        #pass
    else:
        print("Serial connection failed.")
        #return False

    tryConnCommand = [
        ('AT+CGPS=1', 'OK', 1),
        ('AT+CGPSGPOS=5', 'OK', 1)
    ]

    # Execute commands sequentially
    error_occurred = False
    for command, expected_response, delay in tryConnCommand:
        success, response = serial_commander.send_command_and_get_response(command, expected_response, delay)
        if not success:
            print("Error occurred while executing command:", command)
            error_occurred = True
            #return False
        else:
#            print("Response:", response)
            print("Command executed successfully:", command)

            latitude, longitude = parse_lat_long(response)
            if latitude is not None and longitude is not None:
                print("Latitude:", latitude)
                print("Longitude:", longitude)
                cavli_database.update_cavli_running_parameters('latitude', latitude)
                cavli_database.update_cavli_running_parameters('longitude', longitude)
            else:
                print("Failed to parse latitude and longitude.")
            

    if not error_occurred:
        print("All commands executed successfully.")
        #return True
    
    # Log the usage now
    serial_commander.update_daily_usage_log()
    
    serial_commander.clear_serial_port()
    serial_commander.close_serial()


# Example usage:
# To switch to physical SIM:
# switch_sim(serial_commander, 'physical')

# To switch to eSIM:
# switch_sim(serial_commander, 'esim')


#def send_payload_v1(payload):
#    serial_commander = SerialCommander()
#    serial_commander.initialize_serial()

#    print(" *** Pyload Testing *** ")
#    print(payload)

#    if serial_commander.test_serial_connection():
        #print("Serial connection established.")
#        pass
#    else:
#        print("Serial connection failed.")
#        return False

#    sendPayloadCommand = [    
#        ('AT+MQTTPUBLM=3,v1/devices/me/telemetry,1,0,0', '>', 2),
#        (payload, None, 2),
#        ('\x1A', 'OK', 10)
#    ]

    # Execute commands sequentially
#    for command, expected_response, delay in sendPayloadCommand:
        #if not serial_commander.send_command(command, expected_response, delay):
#        if not serial_commander.send_command_and_get_response(command, expected_response, delay):
#            print("Error occurred while executing command:", command)
#            return False

#    serial_commander.clear_serial_port()
#    serial_commander.close_serial()
#    return True


def send_payload(payload):
    serial_commander = SerialCommander()
    serial_commander.initialize_serial()

    if not serial_commander.test_serial_connection():
        print("Serial connection failed.")
        return False

    print(" ********** Pyload Testing ********* ")
    print(payload)

    # Check the payload using json_db_module
    is_match = json_db_module.check_incoming_json(payload)
    print(" ********** Is Match ********* ")
    print(is_match)
    print(" ********** Is Match ********* ")
    
    # Determine the appropriate AT command based on the payload check
    if is_match:
        # If match, use telemetry topic
        sendPayloadCommand = [    
            ('AT+MQTTPUBLM=3,v1/devices/me/attributes,1,0,0', '>', 2),
            (payload, None, 2),
            ('\x1A', 'OK', 10)
        ]
    else:
        # Otherwise, use attributes topic

        sendPayloadCommand = [    
            ('AT+MQTTPUBLM=3,v1/devices/me/telemetry,1,0,0', '>', 2),
            (payload, None, 2),
            ('\x1A', 'OK', 10)
        ]        

    # Execute commands sequentially
    for command, expected_response, delay in sendPayloadCommand:
        if not serial_commander.send_command_and_get_response(command, expected_response, delay):
            print("Error occurred while executing command:", command)
            return False
    
    # Log the usage now
    serial_commander.update_daily_usage_log()
    
    serial_commander.clear_serial_port()
    serial_commander.close_serial()
    return True


def lookup_operator(code):

    lookup_date = {

        # ===================== JIO / RELIANCE =====================
        
        40523: "Jio",  # WB
        40485: "Jio",  # WB
        405840: "Jio", # WB
        
        40501: "Jio",  # AP 
        405854: "Jio", # AP 
        
        405855: "Jio", # Assam
        
        40436: "Jio",  # Bihar
        40503: "Jio",  # Bihar
        405856: "Jio", # Bihar
        
        40504: "Jio",  # Chennai
        
        405872: "Jio", # Delhi
        
        40506: "Jio",  # Gujarat
        405857: "Jio", # Gujarat
        
        40507: "Jio",  # Haryana
        405858: "Jio", # Haryana
        
        40418: "Jio",  # Himachal Pradesh
        40508: "Jio",  # Himachal Pradesh        
        405859: "Jio", # Himachal Pradesh  
        
        40509: "Jio",  # J&K 
        405860: "Jio", # J&K 
        
        40510: "Jio",  # Karnatake       
        405861: "Jio", # Karnatake
        
        40511: "Jio",  # Kerala        
        405862: "Jio", # Kerala 
        
        40483: "Jio",  # Kolkata
        405873: "Jio", # Kolkata
        
        40467: "Jio",  # MP
        40514: "Jio",  # MP
        405863: "Jio", # MP
        
        40513: "Jio",  # Maharashtra        
        405864: "Jio", # Maharashtra
        
        40515: "Jio",  # Mumbai
        405874: "Jio", # Mumbai
        
        40450: "Jio",  # Northeast
        405865: "Jio", # Northeast
        
        40452: "Jio",  # Orissa
        40517: "Jio",  # Orissa
        405866: "Jio", # Orissa
        
        405867: "Jio", # Punjab
        
        40519: "Jio",  # Rajasthan        
        405868: "Jio", # Rajasthan
        
        40520: "Jio",  # Tamil Nadu        
        405869: "Jio", # Tamil Nadu
        
        40521: "Jio",  # UP(east)
        405871: "Jio", # UP(east)
        
        40522: "Jio",  # UP(west)
        405870: "Jio", # UP(west)
        
        4051: "Reliance",
        40505: "Reliance",
        40512: "Reliance",
        40518: "Reliance",
        40409: "Reliance",
        
        # ===================== AIRTEL =====================
        40402: "AirTel",  # Punjab
		405042: "AirTel", # Punjab
		405812: "AirTel", # Punjab
		
        40403: "AirTel",  # Himachal
		405032: "AirTel", # Himachal
		
        40410: "AirTel",  # Delhi
		405029: "AirTel", # Delhi
		405800: "AirTel", # Delhi
		405844: "AirTel", # Delhi
		
		40437: "AirTel",  # J&K
		405033: "AirTel", # J&K
		40555: "AirTel",  # J&K
		
        40525: "Airtel",
        40526: "Airtel",
        40527: "Airtel",
        40528: "Airtel",
        40529: "Airtel",
        40530: "Airtel",
        40531: "Airtel",
        40431: "AirTel",  # Kolkata
		40491: "AirTel",  # Kolkata
		405036: "AirTel", # Kolkata

		40417: "AirTel",  # WB
        405047: "AirTel", # WB
        40551: "AirTel",  # WB
		
		405045: "AirTel", # UP(east)
		40554: "AirTel",  # UP(east)
		405810: "AirTel", # UP(east)  
		
		40497: "AirTel",  # UP(west)
		405046: "AirTel", # UP(west)
		405811: "AirTel", # UP(west)
		405818: "AirTel", # UP(west)
		
        40532: "Airtel",
        40533: "Airtel",
        40534: "Airtel",
        40535: "Airtel",
        40536: "Airtel",
        40537: "Airtel",
        40538: "Airtel",
        40539: "Airtel",
        40440: "AirTel",  # Chennai
		40441: "AirTel",  # Chennai
		405028: "AirTel", # Chennai
		
		40553: "AirTel",  # Orissa
        405041: "AirTel", # Orissa
		
        40541: "Airtel",
        40542: "Airtel",
        40543: "Airtel",
        40544: "Airtel",
        40545: "Airtel",
        40445: "Airtel",  # Karnatake
		405034: "Airtel", # Karnatake
		405803: "Airtel", # Karnatake
		405820: "Airtel", # Karnatake
		
		40442: "Airtel",  # Tamil Nadu
		40494: "AirTel",  # Tamil Nadu
		405044: "AirTel", # Tamil Nadu
		
        40546: "Airtel",
        40547: "Airtel",
        40449: "Airtel",  # AP
		405025: "Airtel", # AP
		405801: "Airtel", # AP
		405819: "Airtel", # AP

		405027: "AirTel", # Bihar
		40552: "AirTel",  # Bihar
		405876: "AirTel", # Bihar
		
        40470: "AirTel",  # Rajasthan
		405043: "AirTel", # Rajasthan
		405806: "AirTel", # Rajasthan
		
        40490: "AirTel",  # Maharashtra
		405037: "AirTel", # Maharashtra
		405804: "AirTel", # Maharashtra
		405929: "AirTel", # Maharashtra
		
        40492: "AirTel",  # Mumbai
		405039: "AirTel", # Mumbai
		
		40433: "AirTel",  # Northeast
		40416: "AirTel",  # Northeast
		
        40493: "AirTel",  # MP
		405038: "AirTel", # MP
		405808: "AirTel", # MP
		
        40495: "AirTel",  # Kerala
		405035: "AirTel", # Kerala
		405809: "AirTel", # Kerala
		405821: "AirTel", # Kerala
		
        40496: "AirTel",  # Haryana
		405031: "AirTel", # Haryana
		405807: "AirTel", # Haryana
        
        40498: "AirTel",  # gujarat
		405030: "AirTel", # gujarat
		405802: "AirTel", # gujarat
		405927: "AirTel", # gujarat

        405875: "AirTel", # Assam
        40556: "AirTel",  # Assam
        405026: "AirTel", # Assam
        40429: "AirTel",  # Assam

        # ===================== VI (VODAFONE–IDEA) =====================
        40401: "Vi",
        40404: "Vi",
        40405: "Vi",
        40407: "Vi",
        40411: "Vi",
        40412: "Vi",
        40413: "Vi",
        40414: "Vi",
        40415: "Vi",
        40419: "Vi",
        40420: "Vi",
        40422: "Vi",
        40424: "Vi",
        40427: "Vi",
        40430: "Vi",
        40443: "Vi",
        40444: "Vi",
        40446: "Vi",
        40456: "Vi",
        40460: "Vi",
        40566: "Vi",
        40567: "Vi",
        40570: "Vi",
        40478: "Vi",
        40482: "Vi",
        40484: "Vi",
        40486: "Vi",
        40487: "Vi",
        40488: "Vi",
        40489: "Vi",

        405750: "Vi",
        405751: "Vi",
        405752: "Vi",
        405753: "Vi",
        405754: "Vi",
        405755: "Vi",
        405756: "Vi",
        405799: "Vi",
        405845: "Vi",
        405846: "Vi",
        405847: "Vi",
        405848: "Vi",
        405849: "Vi",
        405850: "Vi",
        405851: "Vi",
        405852: "Vi",
        405853: "Vi",
        405908: "Vi",
        405909: "Vi",
        405910: "Vi",
        405911: "Vi",

        # ===================== BSNL =====================
        40434: "BSNL",
        40438: "BSNL",
        40451: "BSNL",
        40453: "BSNL",
        40454: "BSNL",
        40455: "BSNL",
        40457: "BSNL",
        40458: "BSNL",
        40459: "BSNL",
        40462: "BSNL",
        40464: "BSNL",
        40466: "BSNL",
        40471: "BSNL",
        40472: "BSNL",
        40473: "BSNL",
        40474: "BSNL",
        40475: "BSNL",
        40476: "BSNL",
        40477: "BSNL",
        40479: "BSNL",
        40480: "BSNL",
        40481: "BSNL",

        # ===================== OTHERS / LEGACY =====================
        40421: "LoopMobile",
        40425: "AIRCEL",
        40428: "AIRCEL",
        40435: "AIRCEL",
        40448: "DishnetWireless",
        40468: "DOLPHIN",
        40469: "DOLPHIN",
        405805: "AIRCEL",
        405822: "Uninor",
        405880: "Uninor",
        405827: "VideoconDatacom",
    }

    if int(code) in lookup_date:
        return lookup_date[int(code)]
    else:
        return "Operator not found for the given code."


#def parse_lat_long_old(gnrmc_string):
#    try:
#        parts = gnrmc_string.split(',')
#        if len(parts) >= 6:
#            latitude = float(parts[3][:2]) + float(parts[3][2:]) / 60
#            if parts[4] == 'S':
#                latitude = -latitude
#            longitude = float(parts[5][:3]) + float(parts[5][3:]) / 60
#            if parts[6] == 'W':
#                longitude = -longitude
#            return latitude, longitude
#        else:
#            return None, None
#    except Exception as e:
#        logger.error("[parse_lat_long] %s", e)
#        return None, None

def parse_lat_long(gnrmc_string):
    try:
        parts = gnrmc_string.split(',')
        if len(parts) >= 6:
            # Parse latitude
            lat_deg = float(parts[3][:2])
            lat_min = float(parts[3][2:])
            latitude = lat_deg + lat_min / 60
            if parts[4] == 'S':
                latitude = -latitude

            # Parse longitude
            lon_deg = float(parts[5][:3])
            lon_min = float(parts[5][3:])
            longitude = lon_deg + lon_min / 60
            if parts[6] == 'W':
                longitude = -longitude

            # Format to four decimal places
            latitude = round(latitude, 4)
            longitude = round(longitude, 4)

            return latitude, longitude
        else:
            return None, None
    except Exception as e:
        logger.error("[parse_lat_long] %s", e)
        return None, None


def getOperatorInfo(response):
    global attempts
    global EXPECTED_OPERATOR_CODE
    network_type = 0
    operator_id = 0
    network_status = 0

    # Split the response by newline characters
    split_response = response.split('\r\n')

    # Extract the relevant part of the response
    data_response = split_response[0]

    # Split the data part of the response by comma
    split_data = data_response.split(',')

    # Extract relevant information — guard against malformed/empty response
    _mode_parts = split_data[0].split(':')
    if len(_mode_parts) < 2:
        logger.warning("[getOperatorInfo] unexpected AT+COPS? format: %r — skipping", data_response)
        return
    mode = _mode_parts[1].strip()
    try:
        network_type = split_data[1]
        operator_id = split_data[2].strip('"')
        network_status = split_data[3]
        
        operator_name = lookup_operator(int(operator_id))
        
#        cavli_database.update_cavli_running_parameters('serviceProvider', lookup_operator(int(operator_id)))
        cavli_database.update_cavli_running_parameters('serviceProvider', operator_name)
        cavli_database.update_cavli_running_parameters('operatorid', int(operator_id))
        
    except IndexError:
        # Handling missing parts in the split_data
        cavli_database.update_cavli_running_parameters('serviceProvider', "NA")
        pass

    except UnboundLocalError as e:
        # Handle unbound local error
        cavli_database.update_cavli_running_parameters('serviceProvider', "NA")
        pass

    except ValueError as e:
        # Handle value error
        cavli_database.update_cavli_running_parameters('serviceProvider', "NA")
        pass

    except Exception as e:
        # Handle any other unforeseen exceptions
        cavli_database.update_cavli_running_parameters('serviceProvider', "NA")
        pass

    print("Current operator code:", operator_id)
    print("Expected operator code:", EXPECTED_OPERATOR_CODE)
    print("No of Attempts for Sim Switch:", str(attempts))
    
    # -------------------------------------------------------
    # If modem already registered to expected operator → exit
    # -------------------------------------------------------
    if EXPECTED_OPERATOR_CODE is not None and str(operator_id) == str(EXPECTED_OPERATOR_CODE):
        #print("Operator already matched → exiting getOperatorInfo()")
        print("Operator Matched → Module Ready to send Data")
        attempts = 0
        return
    
    # -------------------------------------------------------
    # If modem NOT registered to expected operator → exit
    # -------------------------------------------------------
    if cavli_database.get_sim_swap() == 'esim':
        main('esim', str(3))
        try:
            # If max attempts reached → fallback
            if attempts >= 5:
                print("Max autoswitch attempts reached → switching to Physical SIM")
                attempts = 0
                EXPECTED_OPERATOR_CODE = None
                switch_to_physical_sim()
                return
                
            # CASE 1: No autoswitch done yet
            if EXPECTED_OPERATOR_CODE is None:
                print("EXPECTED_OPERATOR_CODE is None → triggering autoswitch")
                attempts += 1
                main(None, str(5))
                return

            # CASE 2: Modem reports operator 0 (not registered)
            if operator_id == "0":
                print("Operator code is 0 (not registered) → triggering autoswitch")
                attempts += 1
                main(None, str(5))
                return

            # CASE 3: Registered on wrong operator
            if operator_id != EXPECTED_OPERATOR_CODE:
                print("Operator mismatch → triggering autoswitch")
                attempts += 1
                main(None, str(5))
                return


#            if lookup_operator(int(operator_id)) != 'Jio':
#            if EXPECTED_OPERATOR_CODE and operator_id != EXPECTED_OPERATOR_CODE:
#                attempts += 1
#                print("Operator mismatch detected → Retry Auto Network Scan")
#                main(None, str(5))

#                if attempts >= 5:
#                    attempts = 0
#                    print("Number of attempts exceeded. Switching to Physical SIM.")
#                    switch_to_physical_sim()
#                else:
#                    print("Failed to switch to Jio. Attempting again...")
            else:
                attempts = 0

        except UnboundLocalError:
            pass

        except IndexError:
            logger.debug("[lookup_operator] fallback: %s", lookup_operator(int(0)))
            pass
    # ======================================================
    # PHYSICAL SIM LOGIC (NEW & REQUIRED)
    # ======================================================
    elif cavli_database.get_sim_swap() == 'physical':
        attempts = 0  # physical SIM uses cycle logic, not attempts
        main('physical', str(3))
        
        # CASE 1: No operator selected yet
        if EXPECTED_OPERATOR_CODE is None:
            print("Physical SIM: EXPECTED_OPERATOR_CODE is None → start operator scan")
            main(None, str(5))
            return

        # CASE 2: Not registered yet
        if operator_id == "0":
            print("Physical SIM: network not registered (COPS=0) → retry scan")
            main(None, str(5))
            return

        # CASE 3: Registered on wrong operator
        if operator_id != str(EXPECTED_OPERATOR_CODE):
            print(
                f"Physical SIM: operator mismatch "
                f"(current={operator_id}, expected={EXPECTED_OPERATOR_CODE})"
            )
            main(None, str(5))
            return

        # CASE 4: Correct operator
        print("Physical SIM: correct operator registered")
        return
    else:
        attempts = 0

#import re
#def getIMEIInfo(response):
    # Define regex patterns for each field
#    patterns = {
#        'Manufacturer': r'Manufacturer:\s*(.*)',
#        'Model Name': r'Model Name:\s*(.*)',
#        'Description': r'Description:\s*(.*)',
#        'Firmware Release': r'Firmware Release:\s*(.*)',
#        'IMEI': r'IMEI:\s*(.*)',
#        'Serial Number': r'Serial Number:\s*(.*)',
#        'HW Version': r'HW Version:\s*(.*)',
#        'Part Number': r'Part Number:\s*(.*)',
#        'Build Date': r'Build Date:\s*(.*)'
#    }
    
    # Extract the information
#    info = {}
#    for key, pattern in patterns.items():
#        match = re.search(pattern, response, re.MULTILINE)
#        if match:
#            info[key] = match.group(1)
    
#    return info

# Extract and save the information into a variable
#device_info = parse_ati_response(response)

# Retrieve and print the IMEI number
#imei_number = device_info.get('IMEI')
#print(f"IMEI: {imei_number}")

##################################################################################################

def handle_gsm_modem_mode():
    """
    Reads the simSwap from modem_config.db and
    switches the modem accordingly.
    """
#	current_value = modem_config_db.get_parameter('gsm_modem_mode')
    current_value = cavli_database.get_sim_swap()

    if current_value is None:
        print("Could not retrieve simSwap from database.")
        return

    current_value = current_value.strip().lower()
    print(f"Detected modem mode in DB: '{current_value}'")

    if current_value == 'physical':
        switch_to_physical_sim()
#    elif current_value == 'esim':
#        switch_to_esim_sim()
    else:
#        print(f" Unknown simSwap '{mode}'. Expected 'esim' or 'physical'.")
        return

##################################################################################################

PHYSICAL_OPERATOR_ATTEMPTS = {}
PHYSICAL_SCAN_CYCLES = 0
MAX_PHYSICAL_SCAN_CYCLES = 3

def select_operator_from_scan_old():
    MAX_TRIES_PER_OPERATOR = 3
    CREG_CHECKS_PER_TRY = 3      

    success, response = scan_available_operators()

    if not success or not response:
        print("AT+COPS=? scan failed")
        return False

    print("AT+COPS=? raw response:\n", response)

    # Extract numeric operator codes (5 or 6 digits)
    operator_codes = list(set(re.findall(r'\d{5,6}', response)))
    print("Detected operator codes:", operator_codes)

    if not operator_codes:
        print("No operators found in scan")
        return False

    # Preferred operator order
    preferred_order = ["AirTel", "Vi", "Jio", "BSNL"]

    # Build operator map
    operator_map = {code: lookup_operator(code) for code in operator_codes}
    print("Operator map:", operator_map)

    # Try operators by priority
    for preferred in preferred_order:
        for code, name in operator_map.items():

            if name.lower() != preferred.lower():
                continue

            PHYSICAL_OPERATOR_ATTEMPTS.setdefault(code, 0)

            if PHYSICAL_OPERATOR_ATTEMPTS[code] >= MAX_TRIES_PER_OPERATOR:
                print(f"Skipping {name} ({code}) — max retries reached")
                continue

            PHYSICAL_OPERATOR_ATTEMPTS[code] += 1
            print(
                f"Trying operator {name} ({code}) "
                f"[Attempt {PHYSICAL_OPERATOR_ATTEMPTS[code]}/{MAX_TRIES_PER_OPERATOR}]"
            )

            # Step 1: Push operator
            if not change_operator(code):
                print(f"{name} operator command failed immediately")
                continue

            # Step 2: Wait & verify registration
            registered = False

            for check in range(1, CREG_CHECKS_PER_TRY + 1):
                print(f"Waiting for network attach ({check}/{CREG_CHECKS_PER_TRY})...")
                time.sleep(5)
                
                serial_commander = SerialCommander()
                serial_commander.initialize_serial()

                if serial_commander.test_serial_connection():
                    print("Serial connection established.")
                #pass
                else:
                    print("Serial connection failed.")
                
                success, resp = serial_commander.send_command_and_get_response(
                    "AT+CREG?", "OK", 5
                )

                if not success or not resp:
                    continue

                try:
                    stat = int(re.findall(r'\+CREG:\s*\d,(\d)', resp)[0])
                    if stat in (1, 5):  # Registered (home or roaming)
                        registered = True
                        break
                except Exception:
                    pass
            
            operator_name = lookup_operator(code) 
            
            if registered:                
                print(f"{operator_name} successfully registered")
                cavli_database.update_cavli_running_parameters(
                    'serviceProvider', operator_name
                )
                return True
            else:
                print(f"{operator_name} rejected by network, trying next operator")
    
    global PHYSICAL_SCAN_CYCLES
    PHYSICAL_SCAN_CYCLES += 1

    print(f"All operators exhausted in this cycle "
          f"[Cycle {PHYSICAL_SCAN_CYCLES}/{MAX_PHYSICAL_SCAN_CYCLES}]")

    # Reset per-operator attempt counters for next cycle
    PHYSICAL_OPERATOR_ATTEMPTS.clear()

    # After 3 full scan cycles → reset modem
    if PHYSICAL_SCAN_CYCLES >= MAX_PHYSICAL_SCAN_CYCLES:
        print("Max physical SIM scan cycles reached → resetting modem")

        PHYSICAL_SCAN_CYCLES = 0
        reset_device()          # or AT+TRB if you prefer
        time.sleep(30)          # allow modem to reattach

    return False


PHYSICAL_SCAN_FAIL_COUNT = 0
PHYSICAL_EXHAUST_COUNT = 0

MAX_SCAN_FAIL = 3
MAX_EXHAUST_CYCLES = 3


def select_operator_from_scan():
    global PHYSICAL_SCAN_FAIL_COUNT
    global PHYSICAL_EXHAUST_COUNT
    global PHYSICAL_OPERATOR_ATTEMPTS
    global EXPECTED_OPERATOR_CODE
    
    CREG_CHECKS_PER_TRY = 2 

    # ------------------ SCAN STAGE ------------------
    success, response = scan_available_operators()

    # >>> ADDITION: handle scan failure retries <<<
    if not success or not response:
        PHYSICAL_SCAN_FAIL_COUNT += 1
        print(f"AT+COPS=? scan failed [{PHYSICAL_SCAN_FAIL_COUNT}/{MAX_SCAN_FAIL}]")

        if PHYSICAL_SCAN_FAIL_COUNT >= MAX_SCAN_FAIL:
            print("Scan failed 3 times → resetting modem")
            PHYSICAL_SCAN_FAIL_COUNT = 0
            PHYSICAL_EXHAUST_COUNT = 0
            PHYSICAL_OPERATOR_ATTEMPTS.clear()

            reset_device()
            time.sleep(30)

        return False
    # <<< END ADDITION >>>

    print("AT+COPS=? raw response:\n", response)

    # Reset scan-fail counter on success (ADDITION)
    PHYSICAL_SCAN_FAIL_COUNT = 0

    operator_codes = list(set(re.findall(r'\d{5,6}', response)))
    print("Detected operator codes:", operator_codes)

    if not operator_codes:
        print("No operators found in scan")
        return False

    preferred_order = ["AirTel", "Vi", "Jio", "BSNL"]
    operator_map = {code: lookup_operator(code) for code in operator_codes}

    print("Operator map:", operator_map)

    # ------------------ OPERATOR STAGE ------------------
    for preferred in preferred_order:
        for code, name in operator_map.items():

            if name.lower() != preferred.lower():
                continue

            PHYSICAL_OPERATOR_ATTEMPTS.setdefault(code, 0)

            if PHYSICAL_OPERATOR_ATTEMPTS[code] >= 3:
                print(f"Skipping {name} ({code}) — max retries reached")
                continue

            PHYSICAL_OPERATOR_ATTEMPTS[code] += 1
            operator_name = lookup_operator(code)

            print(
                f"Trying operator {operator_name} ({code}) "
                f"[Attempt {PHYSICAL_OPERATOR_ATTEMPTS[code]}/3]"
            )

            if not change_operator(code):
                print(f"{operator_name} operator command failed")
                continue

            # -------- Registration verification --------
            registered = False

            for check in range(1, CREG_CHECKS_PER_TRY + 1):
                print(f"Waiting for network attach ({check}/{CREG_CHECKS_PER_TRY})...")
                time.sleep(5)
                
                serial_commander = SerialCommander()
                serial_commander.initialize_serial()

                if serial_commander.test_serial_connection():
                    print("Serial connection established.")
                #pass
                else:
                    print("Serial connection failed.")
                
                success, resp = serial_commander.send_command_and_get_response(
                    "AT+CREG?", "OK", 5
                )

                if not success or not resp:
                    continue

                try:
                    stat = int(re.findall(r'\+CREG:\s*\d,(\d)', resp)[0])
                    if stat in (1, 5):
                        registered = True
                        break
                except Exception:
                    pass

            if registered:
                
                print(f"{operator_name} successfully registered")
                cavli_database.update_cavli_running_parameters(
                    'serviceProvider', operator_name
                )

                # >>> ADDITION: reset counters on success <<<
                PHYSICAL_OPERATOR_ATTEMPTS.clear()
                PHYSICAL_EXHAUST_COUNT = 0
                # <<< END ADDITION >>>
                
                EXPECTED_OPERATOR_CODE = code   
                
                return True
            else:
                print(f"{operator_name} rejected by network, trying next operator")

    # ------------------ CYCLE END ------------------
    print("All operators exhausted in this cycle")

    # >>> ADDITION: cycle exhaustion handling <<<
    PHYSICAL_EXHAUST_COUNT += 1
    print(
        f"Physical SIM exhaustion count: "
        f"{PHYSICAL_EXHAUST_COUNT}/{MAX_EXHAUST_CYCLES}"
    )

    PHYSICAL_OPERATOR_ATTEMPTS.clear()

    if PHYSICAL_EXHAUST_COUNT >= MAX_EXHAUST_CYCLES:
        print("All operators failed for 3 cycles → resetting modem")
        PHYSICAL_EXHAUST_COUNT = 0
        PHYSICAL_SCAN_FAIL_COUNT = 0

#        reset_device()
        switch_to_esim_sim()
        time.sleep(30)
    # <<< END ADDITION >>>

    return False

def check_sim_mode_and_select_operator():
    """
    Check simSwap from DB.
    - If Physical SIM → scan operators and select preferred one (no DB)
    - If eSIM → autoswitch_operator (DB-based priority logic)
    """

#    current_value = modem_config_db.get_parameter('gsm_modem_mode')
    current_value = cavli_database.get_sim_swap()


    if not current_value:
        print("simSwap not found")
        return False

    current_value = current_value.strip().lower()
    print(f"simSwap detected: {current_value}")

    if current_value == 'physical':
        print("Physical SIM detected → starting operator scan")
        return select_operator_from_scan()

    elif current_value == 'esim':
        print("eSIM detected → starting autoswitch operator")
        return autoswitch_operator(
            serial_commander,
            change_operator,
            switch_to_physical_sim
        )

    else:
        print("Unknown simSwap → skipping operator selection")
        return False

def switch_to_physical_sim():
    print("Switching to Physical SIM...")
    main('physical', str(3))
    main(None, str(5))
    # Logic to switch to Physical SIM goes here
    # This can include hardware-specific commands or API calls

def switch_to_esim_sim():
    print("Switching to e SIM...")
    main('esim', str(3))
    main(None, str(5))
    time.sleep(10)
#    main(None, str(5))
    # Logic to switch to Physical SIM goes here
    # This can include hardware-specific commands or API calls


def initCalviDevice():
    
    success = initialize_device()
    if success:
        print("Device initialized successfully.")
        operator_info()
        #get_lat_long()
        get_IMEI_number()
#        executor.increment()
    else:
        print("Error occurred during initialization.")
        return False


def initOperatorIMEI():
    
    success = operator_info()
    if success:
#        print("Get Network Provider Successfully.")
        get_lat_long()
        get_IMEI_number()
        watchdog.reset()
#        executor.increment()
    else:
        print("Error occurred during initialization.")
        return False


#def checkOperator():

#    success_ip = check_network_ip()
#    if success_ip:
#        print("Network IP checked successfully.")
#    else:
#        print("Error occurred while checking network IP.")

#    if not success_ip:
#        success_try_conn = try_connection()
#        if success_try_conn:
#            print("Connection attempt successful.")
#        else:
#            print("Error occurred while attempting connection.")

#        if not success_try_conn:
#            success_reset = reset_device()
#            if success_reset:
#                print("Device reset successful.")
#            else:
#                print("Error occurred while resetting the device.")


def checkMQTTStatus(paylod):
    # In Ethernet mode dexter-mqtt owns the ThingsBoard session.
    # Both paths share the same client_id — the modem reconnecting would
    # kick dexter-mqtt off ThingsBoard every ~30 s (and vice-versa).
    # Skip the GSM MQTT path entirely; the payload is already being sent
    # via TCP by dexter-mqtt.
    if _sc_network_type() == "ethernet":
        logger.info("[checkMQTTStatus] network_type=ethernet — skipping GSM MQTT; dexter-mqtt owns ThingsBoard session")
        return True

    success_mqtt_status = check_mqtt_status()

    if success_mqtt_status:
        print("MQTT status checked successfully.")

        #success_send_payload = send_payload(paylod_ref())
        success_send_payload = send_payload(paylod)
       
        if success_send_payload:
            print("Payload sent successfully.")
            return True
        else:
            print("Error occurred while sending payload.")
        
    else:
        print("Error occurred while checking MQTT status.")

        success_conn_server = connect_to_server()
    
        if success_conn_server:
            print("Connected to server successfully.")
            # connect_to_server() already confirmed AT+MQTTSCONN → OK + subscriptions → OK.
            # Skip the redundant status poll — the modem may not reflect status=1 immediately
            # after MQTTSCONN, causing a false failure and a reconnect cascade.
            success_send_payload = send_payload(paylod)
            if success_send_payload:
                cavli_database.update_cavli_running_parameters('dataSending', "Success")
                print("Payload sent successfully.")
                return True
            else:
                print("Error occurred while sending payload.")
                return False
        
        else:
            print("Error occurred while connecting to server.")
            return 2

        #return True:

#def sendData():
    
    
#    success_mqtt_status = check_mqtt_status()

#    if success_mqtt_status:
#        print("MQTT status checked successfully.")

#        success_send_payload = send_payload(paylod_ref())
        
#        if success_send_payload:
#            print("Payload sent successfully.")
#        else:
#            print("Error occurred while sending payload.")
        
#    else:
#        print("Error occurred while checking MQTT status.")

#        success_conn_server = connect_to_server()
    
#        if success_conn_server:
#            print("Connected to server successfully.")

#            success_send_payload = send_payload(paylod_ref())
        
#            if success_send_payload:
#                print("Payload sent successfully.")
#            else:
#                print("Error occurred while sending payload.")
        
#        else:
#            print("Error occurred while connecting to server.")


def paylod_ref(): #used for testing data sending
    
    branch_t = "mumbai"
    branch = str("\"") + str(branch_t) + str("\"")
        
    payload="{"
    payload+="\"branch\":"
    payload+=str(branch)
    payload+="}"

    return payload


def create_incrementer(max_value):
    def increment():
        increment.counter += 1
        if increment.counter > max_value:
            increment.counter = 0
        return increment.counter
    increment.counter = 0
    return increment


class ChildProgram:
    def __init__(self, db_handler):
        self.db_handler = db_handler

    def send_to_cloud(self, data):
        print("Sending to cloud:", data)
        time.sleep(2)
        print("Data sent to the cloud successfully.")
        return data

    def run(self):
        while True:
            row_id, json_str = self.db_handler.get_json_string()
            if json_str:
                self.send_to_cloud(json_str)
                self.db_handler.mark_as_sent(row_id)
            else:
                print("No new data to send. Checking again in 5 seconds.")
                time.sleep(5)


#def reset_payload(db_handler, row_id):
#    """Manually reset the status of a specific payload to pending."""
#    db_handler.reset_status(row_id)
#    print("Payload with row_id {} has been reset to pending.".format(row_id))

request = {"method": "getcare", "params": ""}
SEND_PAYLOAD_INTERVAL = 5
last_payload_time = 0

serial_commander = SerialCommander()

def Send_Payload():
    global last_payload_time

    if time.time() - last_payload_time < SEND_PAYLOAD_INTERVAL:
        return

    try:
        serial_commander.initialize_serial()
        json_payload = json.dumps(request).encode('utf-8')

        sendPayloadCommand = [
            ('AT+MQTTPUBLM=3,"v1/devices/me/rpc/request/1",0,0,0', '>', 2),
            (json_payload + b'\x1A', 'OK', 10)
        ]

        for command, expected_response, delay in sendPayloadCommand:
            success, response = serial_commander.send_command_and_get_response(command, expected_response, delay)
            if not success:
                print(f"Error sending payload: {command} Response: {response}")
                return

        serial_commander.clear_serial_port()
        serial_commander.close_serial()
        last_payload_time = time.time()
        print("Rpc payload sent successfully.")
    except Exception as e:
        logger.warning("[Send_Payload] %s", e)

def receive_message():
    try:
        Send_Payload()
        serial_commander.initialize_serial()

        success, response = serial_commander.send_command_and_get_response("", "", 5)

        if success and response:
            if "{" not in response:
                return

            print(f"Raw response received:\n{response.strip()}")

            json_match = re.search(r'\{.*?\}', response, re.DOTALL)
            if json_match:
                json_string = json_match.group()
                try:
                    parsed_message = json.loads(json_string)
                    print(f"Extracted JSON message: {parsed_message}")
                    handle_message(json.dumps(parsed_message))
                except ValueError as e:
                    logger.warning("[handle_message] Invalid JSON: %s", e)
        else:
            print("No new MQTT messages.")

    except serial.SerialException as e:
        logger.warning("[receive_message] SerialException: %s", e)
    except Exception as e:
        logger.error("[receive_message] Unexpected error: %s", e)
    finally:
        try:
            serial_commander.clear_serial_port()
            serial_commander.close_serial()
        except Exception:
            pass

    time.sleep(1)


# SEC-08: Sliding window rate limiter for destructive RPC commands
import threading as _threading
class _SlidingWindowLimiter:
    def __init__(self, max_calls, window_seconds):
        self._max, self._window = max_calls, window_seconds
        self._calls, self._lock = [], _threading.Lock()
    def allow(self):
        import time as _t
        now = _t.time()
        with self._lock:
            self._calls = [t for t in self._calls if now - t < self._window]
            if len(self._calls) >= self._max:
                return False
            self._calls.append(now)
            return True

_reboot_limiter = _SlidingWindowLimiter(3, 3600)  # max 3/hr
_ota_limiter    = _SlidingWindowLimiter(1, 3600)  # max 1/hr

def handle_message(msg):
    print(f"Received message: {msg}")

    try:
        data = json.loads(msg)
        current_params = str(data.get('params', '')).strip()

        if current_params == "reboot":
            if not _reboot_limiter.allow():  # SEC-08
                logger.warning("[RPC] Reboot rate limit exceeded (max 3/hr) — ignored")
            else:
                logger.info("[RPC] Executing reboot")
                try:
                    import net_reboot; net_reboot.main()  # SEC-05
                except Exception as e:
                    logger.error("[RPC] reboot error: %s", e)

        elif current_params == "runota":
            if not _ota_limiter.allow():  # SEC-08
                logger.warning("[RPC] OTA rate limit exceeded (max 1/hr) — ignored")
            else:
                logger.info("[RPC] Executing OTA update")
                try:
                    import net_ota; net_ota.main()  # SEC-05
                    time.sleep(20)
                except Exception as e:
                    logger.error("[RPC] OTA error: %s", e)

        elif current_params == "done":
            
            print("Matched 'done' command. Executing webrpc update...")
            check_and_send()
              

        elif current_params == "webcall":
            print("Matched 'done' command. Executing webrpc update...")
            _wc_modem = _sc_network_type() == "gsm"
            try:
                if _wc_modem:
                    subprocess.call(_NSENTER_SC + ["pon", "c16qs"])
                if wait_for_network():
                    #send_dexter_config()
                    fetch_and_update_dexter_config()
                    send_webdone()

                else:
                    print("DNS not available, skipping update")
            finally:
                if _wc_modem:
                    subprocess.call(_NSENTER_SC + ["poff", "c16qs"])
                #subprocess.call(["sudo", "pkill", "-9", "pppd"])  # ensure PPP is dead
                time.sleep(2)
                safe_reopen_serial(serial_commander)
       
        
        elif current_params == "debug":
            #print("Matched 'debug' command. Executing debug...")
            try:
                subprocess.check_call(["python", "/home/pi/Test3/net_debug.py"])
                time.sleep(20)
            except Exception as e:
                logger.error("[RPC] debug error: %s", e)


        else:
            print("No matching params. Ignoring...")
    except ValueError as e:
        logger.error("[handle_message] Invalid JSON: %s", e)

def start_mqtt():
    receive_message()

#def execute_logic(flag):
#    if flag:
#        row_id, json_str = db_handler.get_json_string()
#        if json_str:
#            child_program.send_to_cloud(json_str)
#            db_handler.mark_as_failed(row_id)  # Mark as Failed always
#        else:
#            print("No new data to send. Checking again in 5 seconds.")
#            time.sleep(5)
#        result = "True logic executed"
#    else:
#        print("No new data to send. Checking again in 5 seconds.")
#        time.sleep(5)
#        result = "False logic executed"
    
#    return result



class CounterExecutor:
    def __init__(self, n, function):
        self.n = n
        self.function = function
        self.count = 0

    def increment(self):
        self.count += 1
        if self.count >= self.n:
            self.function()
            self.count = 0  # Reset the counter if you want to reuse it

# Example function to be executed
#def my_function():
#    print("Function executed!")

# Number of counts after which the function should be executed
n = 5

# Create an instance of CounterExecutor
#executor = CounterExecutor(n, my_function)
executor = CounterExecutor(n, get_lat_long)


def main(param1, param2):
    
    # Initialize a variable
    count = 0

    # Perform some actions
    #print("Count is:", count)
    
    # Increment the count
    #count += 1

    #param2 = 1
    #param1 = '405873'
    #param1 = '40430'
    #param1 = '40482'

    # Define an incrementer with a maximum value of 5
    incrementer = create_incrementer(2)

    # Start the do-while loop

    #cavli_database.update_cavli_running_parameters('dataSending', "Error")
    
    cavli_database.update_cavli_running_parameters('modemStatus', "Running")
    cavli_database.update_cavli_running_parameters('dataSending', "Executing")

    while True:
        if param2 == '0':
            break
        elif param2 == '1':
            #param1 = paylod_ref()
            success = checkMQTTStatus(param1)
            if success == True:
                print(success)
                cavli_database.update_cavli_running_parameters('dataSending', "Success")
                cavli_database.update_cavli_running_parameters('modemStatus', "Ready")
                break
            elif success == False:
                print(success)
                if initCalviDevice() == False:
                    break
            elif success == 2:
                #try_connection()
                reset_device()
                if check_network_ip() == False:
                    #try_connection()
                    reset_device()
                if check_network_ip() == False:
                    reset_device()
                    if incrementer() == 2:
                        cavli_database.update_cavli_running_parameters('dataSending', "Error")
                        cavli_database.update_cavli_running_parameters('modemStatus', "Ready")
                        break
                    #    switch_sim('physical')
                    #    reset_device()
                    #    cavli_database.update_cavli_running_parameters('simSwap', 'physical')
                
        elif param2 == '2':
            initCalviDevice()
            cavli_database.update_cavli_running_parameters('modemStatus', "Ready")
            break
        
        elif param2 == '3':
            switch_sim(param1) # 'physical' / 'esim'
            #switch_sim('esim') # 'physical' / 'esim'
            time.sleep(10)
            #reset_device()
#            modem_config_db.update_parameter('gsm_modem_mode', param1)
            cavli_database.update_cavli_running_parameters('simSwap', param1)
            cavli_database.update_cavli_running_parameters('modemStatus', "Ready")
            time.sleep(30)
            break
           
        elif param2 == '4':
            reset_device()
            cavli_database.update_cavli_running_parameters('modemStatus', "Ready")
            break

        elif param2 == '5':
            #change_operator(param1)
#            change_operator(str(405873))
#            autoswitch_operator(serial_commander, change_operator, switch_to_physical_sim, db_name="operator_codes.db")
            check_sim_mode_and_select_operator()
            cavli_database.update_cavli_running_parameters('modemStatus', "Ready")
            time.sleep(30)
            break

        elif param2 == '6':
            initOperatorIMEI()
            cavli_database.update_cavli_running_parameters('modemStatus', "Ready")
            break
        
        elif param2 == '7':
            # In Ethernet mode, RPC command check uses dexter-mqtt (TCP path).
            # Skip modem MQTT to avoid client_id session conflict.
            if _sc_network_type() != "ethernet":
                print("checking for thingsboard command.")
                start_mqtt()
            break
        
        elif param2 == '8':
            break


if __name__ == "__main__":

    print("Cavli Serial Program")
    
    db_handler = DatabaseHandler()
    child_program = ChildProgram(db_handler)
    modem_config_db = ModemConfigDatabase()
    # SEC-04: migrate any plaintext credentials left from before this fix
    modem_config_db.migrate_plaintext_credentials()

    cavli_database.update_cavli_running_parameters('latitude', 20.5937)
    cavli_database.update_cavli_running_parameters('longitude', 78.9629)
    cavli_database.update_cavli_running_parameters('serviceProvider', "NA")
    cavli_database.update_cavli_running_parameters('IMEI', 0)
    cavli_database.update_cavli_running_parameters('SerialNumber', 0)
    
    print("Setting up modem...")

#    time.sleep(60)

#    reset_device()

    time.sleep(30)
    
    main(None, str(2))
#    handle_gsm_modem_mode()
    #switch_to_esim_sim()
    #switch_to_physical_sim()
    
    time.sleep(30)
    
    # Create a new context with an initial state and parameters.
    context = Context(InitializeModem, modem_id=1234, network="5G")

#    print("Initial State:", context)
    
    # Schedule the summary function every 15 minutes
    #schedule.every(15).minutes.do(print_daily_usage_summary)
    schedule.every(1).hours.do(print_daily_usage_summary)
   
    while True:

        # Simulate the `initialize` event to transition to `CheckNetworkStatus`
        context.on_event('initialize')
#        print "Current State after initialize:", context
        
        # Simulate the `network_check` event to transition to `CheckNetworkStatus`
        context.on_event('network_check')
#        print "Current State after network_check:", context

        # Simulate the `signal_strength` event to transition to `CheckSignalStrength`
        context.on_event('signal_strength')
#        print "Current State after signal_strength:", context

        context.on_event('send_payload')
#        print "Current State after send_payload:", context

        context.on_event('confirm_delivery')
#        print "Current State after confirm_delivery:", context
        
        # Reset watchdog timer
        watchdog.reset()  # software watchdog — prevents os.execl() restart

        # Feed the systemd watchdog — resets WatchdogSec=1800 countdown.
        # Only reached when the modem responded and all 5 events completed.
        # If the modem is stuck, this line is never reached, the countdown
        # expires after 1800s, and systemd reboots the Pi — correct behaviour.
        _sd_notify_watchdog()

        check_and_notify_usage_limit()
        
        # Run scheduled tasks
        schedule.run_pending()

        time.sleep(10)



#        for event in events:
#            # Handle the event and transition to the next state
#            context.on_event(event)
#            # Print the current state
#            print("Current State:", context)

    
        
#if __name__ == "__main__":
#    # Create a new context with an initial state and parameters.
#    context = Context(InitializeModem, modem_id=1234, network="5G")
#
#    print("Initial State:", context)
#
#    # List of events to simulate program logic
#    events = ['network_check', 'signal_strength', 'send_payload', 'confirm_delivery', 'terminate', 'initialize', 'network_check']
#
#    for event in events:
#        # Handle the event and transition to the next state
#        context.on_event(event)
#        # Print the current state
#        print("Current State:", context)

                
