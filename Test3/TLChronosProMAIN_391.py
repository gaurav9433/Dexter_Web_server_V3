#!/usr/bin/python
# -*- coding: utf-8 -*-


import subprocess
from subprocess import call
from subprocess import Popen
from pad4pi import rpi_gpio
from Adafruit_CharLCD import Adafruit_CharLCD
from datetime import datetime
import random
import time
import SDL_DS1307
import sys
import datetime
#import commands
import threading
import RPi.GPIO as GPIO
GPIO.cleanup()  # Make sure GPIO is cleaned up at the very end of your script
from time import sleep
import smtplib
import socket
#import urllib2
import urllib
import socket
import os
import sqlite3
from shiftRegister import ShiftRegister
import logging
import os
import json
import random
import requests
import array
import subprocess
import threading
from database_handler import DatabaseHandler
from db_connection import (verify_all_databases, DB_MODEM_CONFIG, DB_PANEL,
                            DB_SYSTEM_SETTINGS, DB_CAVLI_RUNNING,
                            DB_CONTROLLER_PARAMS,
                            DB_TAILSCALE)
from db_schema_migration import run_all_migrations
from secrets_manager import encrypt_value, decrypt_value
from cryptography.fernet import InvalidToken
from cryptography import x509 as _x509_crypto
from cryptography.hazmat.primitives import hashes as _crypto_hashes
import credential_auth                             # CRED-GATE: challenge-response
from webdone import send_webdone
from buffer_manager import get_and_delete_json_from_db
from buffer_manager import init_db
from tailscale_setup import setup_tailscale_and_save_info
from cavlidata import send_cavlidata_status
import location_manager   # GPS lat/lon acquisition + 12hr TB scheduled send
import imei_manager        # IMEI TB send twice a day (every 12hr)

# ── systemd watchdog notify (stdlib only — no pip install needed) ────────────
def _sd_notify_watchdog():
    """Send WATCHDOG=1 to systemd via NOTIFY_SOCKET. Safe outside systemd."""
    ns = os.environ.get('NOTIFY_SOCKET')
    if not ns:
        return
    try:
        if ns.startswith('@'):
            ns = '\x00' + ns[1:]
        import socket as _sock
        s = _sock.socket(_sock.AF_UNIX, _sock.SOCK_DGRAM)
        s.connect(ns)
        s.sendall(b'WATCHDOG=1')
        s.close()
    except Exception as _e:
        logger.debug('[sd_notify] watchdog ping failed: %s', _e)
from stopser import stop_autorun
from Lan_setting import portainer_register
from syslog_file_logger import get_dual_logger
from heartbeat_manager import HeartbeatManager
try:
    from amc_integration import check_amc_bas
except (ImportError, SystemExit):
    check_amc_bas = lambda: 'Offline'  # AMC disabled or module not present
from payload_manager import insert_with_cap  # backlog cap at insert time
#sudo timedatectl set-ntp false
#Additional Notes:
#If the system is configured to synchronize time with NTP, manual updates may not persist. You might need to stop the NTP service permanently if manual updates are required.
#sudo systemctl disable ntp 
logger = get_dual_logger('TL_maincode')
# Logging is configured by the module-level logger setup below
# (removed development test log lines)


menuSubSubState = 0

mutiKeyInput = 0
changeinPos = 0


phoneNumberBuff = [[0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],   # 1 
               [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],       # 2
               [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],       # 3
               [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],       # 4 
               [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],       # 5 
               [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],       # 6 
               [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],       # 7                   
               [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],       # 8
               [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],       # 9
               [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],       # 10
               [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],       # 11
               [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],       # 12 
               [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],       # 13
               [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],       # 14                   
               [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],       # 15
               [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],       # 16
               [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],       # 17
               [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],       # 18
               [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],       # 19
               [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0]]       # 20


branchNameAddressBuffer = [[0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0], # Beanch Name
               [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],       # Address Line 1
               [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],       # Address Line 2    
               [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],       # Street
               [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],       # City
               [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],       # District
               [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],       # State                                  
               [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0]]       # Pin Code

#credientalsBuffer = [[0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,/n 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],  # Address Line 1
#               [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],       # Street
#               [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],       # District
#               [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
#               [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0]]       # Pin Code

credientalsBuffer = [[' ']*32,  # Tb Credential: Client ID
                     [' ']*32,  # Tb Credential: User name
                     [' ']*32,  # Tb Credential: Password
                     [' ']*32,  # (if you have other lines)
                     [' ']*32]  # (if you have other lines)

# CRED-GATE: shared state for challenge-response gate
# _cred_challenge holds the current challenge shown on LCD
# _cred_show_time holds timestamp when SHOW state was entered (for auto-clear)
# _cred_response_buf holds digits entered by operator on keypad
_cred_challenge      = [None]   # mutable so sub-functions can update
_cred_show_time      = [None]
_cred_resp_digits    = ['']
_cred_session_expiry = [None]   # timestamp when session expires; None = no session
_CRED_SESSION_SEC    = 120      # operator can view all credentials for 2 minutes

                     #[' ']*32,  # Tb Credential: User name
                     #[' ']*32,  # Tb Credential: Password
                     #[' ']*32,  # (if you have other lines)
                     #[' ']*32]  # (if you have other lines)


zoneProgSetMenu = 0
menuCodeSelectState = 0
GuserSetState = 0
menuSubState = 0
menuSubSubSubState = 0
menuSubSubSubSubState = 0

maintenanceState = 0
isLampTestACTIVATED = 0
isRelayTestACTIVATED = 0
isHooterTestACTIVATED = 0    

zoneSettings = [0,0,0,
        0,0,0,
        0,0,0,
        0,0,0,
        0,0,0,
        0,0,0,
        0,0,0,                
        0,0,0,
        0,0,0,
        0,0,0,
        0,0,0,
        0,0,0,
        0,0,0,
        0,0,0,
        0,0,0,                
        0,0,0]


powerZoneSettings = [0,0,0,
        0,0,0,
        0,0,0,
        0,0,0,
        0,0,0,
        0,0,0,
        0,0,0,                
        0,0,0,
        0,0,0,
        0,0,0,
        0,0,0,
        0,0,0,
        0,0,0,
        0,0,0,
        0,0,0,                
        0,0,0]


zoneIsCamDisconnected = [0] * 17
zoneIsFault = [0] * 17
zoneIsPowerOff = [0] * 17
zoneIsActive = [0] * 17
zoneIsHDDError = [0] * 17
powerZoneIsActive = [0] * 17
zoneIsCamTamper = [0] * 17

zoneIsActiveType = [0] * 17
zoneIsFaultType = [0] * 17
powerZoneIsActiveType = [0] * 17

zoneFaultBuzzerOn = 0

powerZoneSettingsOnCounter = 0
powerZoneOnCounter = 0


parameter_names = []
parameter_values = []

lowBatteryBuzzOn = 0
mainSense = 0

statusbox_mains_on = "true"
statusbox_battery_on = "false"
statusbox_battery_reverse = "false"
statusbox_sos_status = "true"
statusbox_network = 'NA'
statusbox_no_of_connected_device = 0
statusbox_battery_low = "false"

network_type = 2
hb_manager = None  # HB-01: populated in __main__ before main loop starts
ds1307 = None  # populated in __main__ after RTC init

GPIO.setmode(GPIO.BCM)

KEYPAD = [
    ["1","2","3","C"],   
    ["4","5","6","D"],
    ["7","8","9","A"],
    ["*","0","@","B"]
]

COL_PINS = [12,13,16,18]
ROW_PINS = [19,20,21,26]

KEY_DELAY = 300

factory = rpi_gpio.KeypadFactory()
keypad = factory.create_keypad(keypad=KEYPAD, row_pins=ROW_PINS, col_pins=COL_PINS, key_delay=KEY_DELAY)

lcd = Adafruit_CharLCD()

keypressed = 0
_last_nav_key_pressed = None   # tracks last "@"/"*" for ghost-B debounce at confirm screens
_last_nav_key_time    = 0.0
def print_key(key):
    global keypressed, _last_nav_key_pressed, _last_nav_key_time
    if key in ["@", "*"]:
        _last_nav_key_pressed = key
        _last_nav_key_time    = time.time()
    keypressed = key

keypad.registerKeyPressHandler(print_key)
#-----------------------------------------------

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
    #    self.thread.setDaemon(True)  # Set daemon mode for Python 2 compatibility
        self.thread.daemon = True  # Set daemon mode for Python 3 compatibility
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
        """ Restart the script using OS system call. """
        self._running = False  # Stop watchdog loop
        #self.thread.join()  # Ensure the thread terminates
        python = sys.executable if sys.executable else "/usr/bin/python3"
        os.execl(python, python, *sys.argv)
    
# Initialize software watchdog with 1800-second timeout
watchdog = SoftwareWatchdog(timeout=1800)
#------------------------------------------------

#SERIAL_DB_FILE = '/home/pi/Test3/securelink.db'

class DeviceSerialNoInfoDB:
    def __init__(self, db_path='/home/pi/Test3/securelink.db'):
        self.db_path = db_path
        self.init_db()

    def init_db(self):
        """Create DB and table if not exists."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS device_info (
                        id INTEGER PRIMARY KEY,
                        panel_number TEXT,
                        batch_number TEXT
                     )''')
        conn.commit()
        conn.close()

    def get_parameter(self, param_name):
        """Retrieve a parameter (panel_number or batch_number) from the device_info table."""
        if param_name not in ('panel_number', 'batch_number'):
            raise ValueError("Invalid parameter. Use 'panel_number' or 'batch_number'.")

        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute(f"SELECT {param_name} FROM device_info ORDER BY id DESC LIMIT 1")
        result = c.fetchone()
        conn.close()

        return result[0] if result else None
    
    def fetch_device_info(self):
        """Fetch panel and batch info from DB."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT panel_number, batch_number FROM device_info LIMIT 1")
        row = c.fetchone()
        conn.close()
        return row if row else ('XX', 'BNXXX')
    
#------------------------------------------------
class PowerZoneActiveDeviceCounter:
    def __init__(self):
        self.counters = {
            'BAS': 0,
            'FAS': 0,
            'TIME_LOCK': 0,
            'BACS': 0,
            'CCTV': 0,
            'IAS': 0
        }

    def update_device(self, device_name, status):
        if device_name in self.counters:
            if status:
                self.counters[device_name] += 1
            else:
                if self.counters[device_name] > 0:
                    self.counters[device_name] -= 1
                else:
                    print(f"Counter for {device_name} is already zero and cannot be decremented!")
        else:
            print("Device not found!")

    def get_counter(self, device_name):
        if device_name in self.counters:
            return self.counters[device_name]
        else:
            return "Device not found!"

    def get_all_counters(self):
        return self.counters


# SEC-04: modem_parameters credential fields — Fernet-encrypted at rest
_MODEM_CREDENTIAL_FIELDS = {'access_token', 'client_id', 'user_name', 'password'}

class ModemConfigDatabase:
    def __init__(self, db_file=DB_MODEM_CONFIG):  # DB-FIX: use imported constant
        self.db_file = db_file
        self.create_database()

    def create_database(self):
        # Complete schema including all columns used across TLChronosProMAIN and SerialCommunication
        # PROV-FIX-4: added swatch_host, swatch_username, swatch_password so these columns
        # exist on a fresh device. Without them webdone.get_parameter() returns None and
        # send_webdone() returns False before attempting login.
        ALL_COLUMNS = [
            'access_token', 'client_id', 'user_name', 'password',
            'gsm_modem_mode', 'network_type', 'device_name',
            'batch_number', 'panel_number',
            'swatch_mqtt_host',
            'swatch_host', 'swatch_username', 'swatch_password',   # PROV-FIX-4
        ]
        conn = None
        try:
            conn = sqlite3.connect(self.db_file)
            cursor = conn.cursor()

            # Create table with full schema
            cursor.execute('''CREATE TABLE IF NOT EXISTS modem_parameters (
                                id                              INTEGER PRIMARY KEY,
                                access_token                    TEXT,
                                client_id                       TEXT,
                                user_name                       TEXT,
                                password                        TEXT,
                                gsm_modem_mode                  TEXT,
                                network_type                    TEXT,
                                device_name                     TEXT,
                                batch_number                    TEXT,
                                panel_number                    TEXT,
                                swatch_mqtt_host                TEXT,
                                swatch_host                     TEXT,
                                swatch_username                 TEXT,
                                swatch_password                 TEXT
                            )''')

            # Add any column missing from older DB schema (ALTER TABLE is safe — ignores if exists)
            for col in ALL_COLUMNS:
                try:
                    cursor.execute(f'ALTER TABLE modem_parameters ADD COLUMN {col} TEXT')
                    logger.info("[ModemConfigDatabase] Schema updated: added column %s", col)
                except sqlite3.OperationalError:
                    pass  # Column already exists

            # Insert default row if table is empty
            cursor.execute('SELECT COUNT(*) FROM modem_parameters')
            if cursor.fetchone()[0] == 0:
                cursor.execute('''INSERT INTO modem_parameters
                                  (access_token, client_id, user_name, password,
                                   gsm_modem_mode, network_type, device_name)
                                  VALUES (?, ?, ?, ?, ?, ?, ?)''',
                               ('', '', '', '', 'physical', 'ethernet', 'Dexter-HMS'))

            conn.commit()
        except sqlite3.Error as e:
            logger.error("[ModemConfigDatabase.create_database] %s", e)
        finally:
            if conn:
                conn.close()

    def get_parameter(self, param):
        conn = None
        try:
            conn = sqlite3.connect(self.db_file)
            cursor = conn.cursor()
            cursor.execute('SELECT {} FROM modem_parameters WHERE id = 1'.format(param))
            row = cursor.fetchone()
            value = row[0] if row else None
            # SEC-04: decrypt credential fields on read
            if value and param in _MODEM_CREDENTIAL_FIELDS:
                try:
                    value = decrypt_value(value)
                except (ValueError, InvalidToken):
                    pass  # legacy plaintext — return as-is
            return value
        except sqlite3.Error as e:
            print(f"Error retrieving parameter {param}: {e}")
            logger.error(f"Error retrieving parameter {param}: {e}")
            return None
        finally:
            if conn:
                conn.close()

    def update_parameter(self, param, value):
        # SEC-04: encrypt credential fields before writing
        stored = encrypt_value(str(value)) if param in _MODEM_CREDENTIAL_FIELDS else value
        conn = None
        try:
            conn = sqlite3.connect(self.db_file)
            cursor = conn.cursor()
            cursor.execute('UPDATE modem_parameters SET {} = ? WHERE id = 1'.format(param), (stored,))
            conn.commit()
        except sqlite3.Error as e:
            print(f"Error updating parameter {param}: {e}")
            logger.error(f"Error updating parameter {param}: {e}")
        finally:
            if conn:
                conn.close()


    def migrate_plaintext_credentials(self) -> None:
        """One-time migration: encrypt any plaintext credentials already in DB.
        Safe to run every startup — already-encrypted rows are skipped."""
        conn = None
        try:
            conn = sqlite3.connect(self.db_file)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT access_token, client_id, user_name, password "
                "FROM modem_parameters WHERE id = 1"
            )
            row = cursor.fetchone()
            if not row:
                return
            for field, raw in zip(
                ['access_token','client_id','user_name','password'], row
            ):
                if not raw:
                    continue
                try:
                    decrypt_value(raw)
                except (ValueError, InvalidToken):
                    cursor.execute(
                        f"UPDATE modem_parameters SET {field} = ? WHERE id = 1",
                        (encrypt_value(raw),)
                    )
                    logger.info("[ModemConfigDatabase] migrated '%s' to encrypted", field)
            conn.commit()
        except Exception as e:
            logger.error("[ModemConfigDatabase.migrate_plaintext_credentials] %s", e)
        finally:
            if conn:
                conn.close()


class MainProgram:
    def __init__(self, db_handler):
        self.db_handler = db_handler

    def send_json_to_child(self, json_str):
        # CAP-FIX: use insert_with_cap instead of insert_json
        # Enforces MAX_PENDING=500 rows, evicts heartbeats first.
        # Prevents payloads.db growing unbounded during long network outages.
        insert_with_cap(json_str)
        # self.db_handler.insert_json(json_str)  # old — no cap

    def is_child_ready(self):
        return self.db_handler.is_child_ready()

    def set_child_ready(self):
        self.db_handler.set_child_ready()

    def clear_child_ready(self):
        self.db_handler.clear_child_ready()

    def get_child_status(self):
        return self.is_child_ready()

    def run(self, json_payload):
        self.send_json_to_child(json_payload)



class SystemSettingsDB:
    def __init__(self):
        # DB-FIX: removed phantom self.conn that was opened here then immediately closed
        # inside create_table(), leaving a stale closed-connection on self.
        # create_table now opens its own short-lived connection like every other method.
        self.create_table()

    def create_table(self):
        conn = sqlite3.connect(DB_SYSTEM_SETTINGS)
        try:
            cursor = conn.cursor()
            cursor.execute('''CREATE TABLE IF NOT EXISTS system_settings
                                  (id INTEGER PRIMARY KEY, name TEXT, value TEXT)''')
            conn.commit()
        except sqlite3.Error as e:
            print("Error occurred:", e)
            logger.error("Error occurred:", e)
        finally:
            conn.close()

    def add_element(self, name, value):
        conn = sqlite3.connect(DB_SYSTEM_SETTINGS)
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT id FROM system_settings WHERE name = ?", (name,))
            if cursor.fetchone() is None:
                cursor.execute("INSERT INTO system_settings (name, value) VALUES (?, ?)", (name, value))
                conn.commit()
#                print("Element '{}' added successfully.".format(name))
            else:
                print(f"Element '{name}' already exists in the database.")
        except sqlite3.Error as e:
            print("Error occurred:", e)
            logger.error("Error occurred:", e)
        finally:
            conn.close()

    def update_element(self, name, new_value):
        conn = sqlite3.connect(DB_SYSTEM_SETTINGS)
        cursor = conn.cursor()
        try:
            cursor.execute("UPDATE system_settings SET value = ? WHERE name = ?", (new_value, name))
            conn.commit()
#            print("Element '{}' updated successfully.".format(name))
        except sqlite3.Error as e:
            print("Error occurred:", e)
            logger.error("Error occurred:", e)
        finally:
            conn.close()

    def retrieve_element(self, name):
        conn = sqlite3.connect(DB_SYSTEM_SETTINGS)
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT value FROM system_settings WHERE name = ?", (name,))
            value = cursor.fetchone()
            if value:
                return value[0]
            else:
#                print("Element '{}' does not exist in the database.".format(name))
                return None
        except sqlite3.Error as e:
            print("Error occurred:", e)
            logger.error("Error occurred:", e)
        finally:
            conn.close()

    def retrieve_table(self):
        conn = sqlite3.connect(DB_SYSTEM_SETTINGS)
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT * FROM system_settings")
            rows = cursor.fetchall()
            return rows
        except sqlite3.Error as e:
            print("Error occurred:", e)
            logger.error("Error occurred:", e)
        finally:
            conn.close()



class NetworkSettings:
    def __init__(self, db_file):
        self.db_file = db_file
        self.conn = None
        self.create_database()

    def create_database(self):
        # FIX: original only created Settings table when DB file was absent.
        # If the DB existed but was empty, CREATE TABLE was skipped and
        # add_new_fields() crashed with 'no such table: Settings'.
        self.conn = sqlite3.connect(self.db_file)
        cursor = self.conn.cursor()
        cursor.execute('''CREATE TABLE IF NOT EXISTS Settings (
                            id INTEGER PRIMARY KEY,
                            setting_name TEXT UNIQUE,
                            setting_value TEXT
                        )''')
        self.conn.commit()
        self.add_new_fields()

    def add_new_fields(self):
        """Add new settings to the database if they don't exist."""
        default_settings = [
            ("preferred_dns_server", "8.8.8.8"),
            ("alternate_dns_server", "8.8.4.4"),
            ("reset_to_dhcp", "True")
        ]
        try:
            cursor = self.conn.cursor()
            for setting_name, setting_value in default_settings:
                cursor.execute('''INSERT OR IGNORE INTO Settings (setting_name, setting_value)
                                  VALUES (?, ?)''', (setting_name, setting_value))
            self.conn.commit()
        except sqlite3.Error as e:
            logger.error("[NetworkSettings.add_new_fields] %s", e)

    def update_setting(self, setting_name, setting_value):
        try:
            cursor = self.conn.cursor()
            cursor.execute('''INSERT OR REPLACE INTO Settings (setting_name, setting_value)
                              VALUES (?, ?)''', (setting_name, setting_value))
            self.conn.commit()
#            print("Setting '{}' updated successfully.".format(setting_name))
        except sqlite3.Error as e:
            logger.error("[NetworkSettings.update_setting] %s", e)

    def get_setting(self, setting_name):
        try:
            cursor = self.conn.cursor()
            cursor.execute('''SELECT setting_value FROM Settings WHERE setting_name = ?''', (setting_name,))
            result = cursor.fetchone()
            if result:
                return result[0]
            else:
#                print("Setting '{}' not found.".format(setting_name))
                return None
        except sqlite3.Error as e:
            logger.error("[NetworkSettings.get_setting] %s", e)
            return None


class MsgQueueBuffer:
    def __init__(self, size):
        self.size = size
        self.buffer = []
        self.token_id_counter = 1

    def add(self, token):
        if len(self.buffer) == self.size:
            self.buffer.pop(0)  # Remove the oldest element if buffer is full
        self.buffer.append((self.token_id_counter, token))
        self.token_id_counter += 1

    def remove_last(self):
        if self.buffer:
            return self.buffer.pop()  # Remove and return the last element
        else:
            return None

    def remove_by_id(self, token_id):
        for i, (token_id_, _) in enumerate(self.buffer):
            if token_id_ == token_id:
                return self.buffer.pop(i)  # Remove and return the element with the specified token ID
        return None

    def get_token_by_id(self, token_id):
        for token_id_, token in self.buffer:
            if token_id_ == token_id:
                return token
        return None

    def get_num_entries(self):
        return len(self.buffer)

    def display_elements(self):
#        print("Elements in the buffer:")
        for token_id, token in self.buffer:
            print("Token ID:", token_id, "Token:", token)

    def query_and_subtract_first(self):
        if self.buffer:
            first_token_id, _ = self.buffer[0]
            self.remove_by_id(first_token_id)

    def get_next_subtracted_element1(self):
        if self.buffer:
            first_token_id, token = self.buffer[0]
            return first_token_id, token
        else:
            return None

    def get_next_subtracted_element(self):
        if self.buffer:
            _, token = self.buffer[0]  # Ignore the token ID
            return token
        else:
            return None


class CavliRunningStatusDatabase_old:
    def __init__(self, db_name=DB_CAVLI_RUNNING):  # DB-FIX: use imported constant
        self.db_name = db_name
        self.initialize_database()

    def initialize_database(self):
        conn = None
        try:
            conn = sqlite3.connect(self.db_name)
            c = conn.cursor()
            c.execute('''CREATE TABLE IF NOT EXISTS cavliRunningParam
                         (id INTEGER PRIMARY KEY, latitude REAL, longitude REAL, dataSending TEXT, modemStatus TEXT, serviceProvider TEXT, simSwap TEXT, IMEI TEXT, SerialNumber TEXT,operatorid INTEGER)''')
            c.execute('SELECT COUNT(*) FROM cavliRunningParam')
            if c.fetchone()[0] == 0:
            # Inserting default values during initialization
               c.execute('''INSERT INTO cavliRunningParam VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?,?)''', (1, None, None, None, None, None, None, None, None,None))
               conn.commit()
        except sqlite3.Error as e:
            print("Error initializing database:", e)
            logger.error("Error initializing database: %s", e)

        finally:
            if conn:
                conn.close()

    def update_cavli_running_parameters(self, column, value):
        conn = None
        try:
            conn = sqlite3.connect(self.db_name)
            c = conn.cursor()
#            c.execute('''UPDATE cavliRunningParam SET {} = ?'''.format(column), (value,))
            c.execute('UPDATE cavliRunningParam SET {} = ? WHERE id = 1'.format(column), (value,))
            conn.commit()
        except sqlite3.Error as e:
            print("Error updating parameters:", e)
            logger.error("Error updating parameters:", e)
        finally:
            if conn:
                conn.close()

    def retrieve_cavli_running_parameters(self, column):
        conn = None
        try:
            conn = sqlite3.connect(self.db_name)
            c = conn.cursor()
#            c.execute('''SELECT {} FROM cavliRunningParam'''.format(column))
            c.execute('SELECT {} FROM cavliRunningParam WHERE id = 1'.format(column))
            result = c.fetchone()
            return result[0] if result else None
        except sqlite3.Error as e:
            print("Error retrieving parameters:", e)
            logger.error("Error retrieving parameters:", e)
        finally:
            if conn:
                conn.close()


    def display_latitude(self):
        latitude = self.retrieve_cavli_running_parameters('latitude')
        if latitude is not None:
            print("Latitude:", latitude)
        else:
            print("Latitude not found.")

    def display_longitude(self):
        longitude = self.retrieve_cavli_running_parameters('longitude')
        if longitude is not None:
            print("Longitude:", longitude)
        else:
            print("Longitude not found.")

    def display_data_sending(self):
        data_sending = self.retrieve_cavli_running_parameters('dataSending')
        if data_sending is not None:
            print("Data Sending:", data_sending)
        else:
            print("Data Sending not found.")

    def display_modem_status(self):
        modem_status = self.retrieve_cavli_running_parameters('modemStatus')
        if modem_status is not None:
            print("Modem Status:", modem_status)
        else:
            print("Modem Status not found.")

    def display_service_provider(self):
        service_provider = self.retrieve_cavli_running_parameters('serviceProvider')
        if service_provider is not None:
            print("Service Provider:", service_provider)
        else:
            print("Service Provider not found.")

    def display_sim_swap(self):
        sim_swap = self.retrieve_cavli_running_parameters('simSwap')
        if sim_swap is not None:
            print("SIM Swap:", sim_swap)
        else:
            print("SIM Swap not found.")

    def display_IMEI(self):
        service_provider = self.retrieve_cavli_running_parameters('IMEI')
        if IMEI is not None:
            print("IMEI:", IMEI)
        else:
            print("IMEI not found.")

    def display_SerialNumber(self):
        SerialNumber = self.retrieve_cavli_running_parameters('SerialNumber')
        if SerialNumber is not None:
            print("Serial Number:", SerialNumber)
        else:
            print("Serial Number not found.")


    def update_latitude(self, value):
        self.update_cavli_running_parameters('latitude', value)

    def update_longitude(self, value):
        self.update_cavli_running_parameters('longitude', value)

    def update_data_sending(self, value):
        self.update_cavli_running_parameters('dataSending', value)

    def update_modem_status(self, value):
        self.update_cavli_running_parameters('modemStatus', value)

    def update_service_provider(self, value):
        self.update_cavli_running_parameters('serviceProvider', value)

    def update_sim_swap(self, value):
        self.update_cavli_running_parameters('simSwap', value)

    def update_IMEI(self, value):
        self.update_cavli_running_parameters('IMEI', value)

    def update_SerialNumber(self, value):
        self.update_cavli_running_parameters('SerialNumber', value)

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
    
    def get_OperatorNumber(self):
        return self.retrieve_cavli_running_parameters('operatorid')

class CavliRunningStatusDatabase:
    def __init__(self, db_name=DB_CAVLI_RUNNING):  # DB-FIX: use imported constant
        self.db_name = db_name
        self.initialize_database()

    def initialize_database(self):
        conn = None
        try:
            conn = sqlite3.connect(self.db_name)
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
            print("Error initializing database:", e)
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
            conn = sqlite3.connect(self.db_name)
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
        conn = None
        try:
            conn = sqlite3.connect(self.db_name)
            c = conn.cursor()

            c.execute(
                'UPDATE cavliRunningParam SET {} = ? WHERE id = 1'.format(column),
                (value,)
            )

            conn.commit()

            # Clean database if needed
            self.cleanup_database()

        except sqlite3.Error as e:
            print("Error updating parameters:", e)
            logger.error("Error updating parameters: %s", e)

        finally:
            if conn:
                conn.close()

    # --------------------------------------------------
    # RETRIEVE PARAMETERS
    # --------------------------------------------------
    def retrieve_cavli_running_parameters(self, column):
        conn = None
        try:
            conn = sqlite3.connect(self.db_name)
            c = conn.cursor()

            c.execute(
                'SELECT {} FROM cavliRunningParam WHERE id = 1'.format(column)
            )

            result = c.fetchone()
            return result[0] if result else None

        except sqlite3.Error as e:
            print("Error retrieving parameters:", e)
            logger.error("Error retrieving parameters: %s", e)

        finally:
            if conn:
                conn.close()

    # --------------------------------------------------
    # DISPLAY FUNCTIONS
    # --------------------------------------------------    
    def display_latitude(self):
        latitude = self.retrieve_cavli_running_parameters('latitude')
        if latitude is not None:
            print("Latitude:", latitude)
        else:
            print("Latitude not found.")
	
    def display_longitude(self):
        longitude = self.retrieve_cavli_running_parameters('longitude')
        if longitude is not None:
            print("Longitude:", longitude)
        else:
            print("Longitude not found.")

    def display_data_sending(self):
        data_sending = self.retrieve_cavli_running_parameters('dataSending')
        if data_sending is not None:
            print("Data Sending:", data_sending)
        else:
            print("Data Sending not found.")

    def display_modem_status(self):
        modem_status = self.retrieve_cavli_running_parameters('modemStatus')
        if modem_status is not None:
            print("Modem Status:", modem_status)
        else:
            print("Modem Status not found.")

    def display_service_provider(self):
        service_provider = self.retrieve_cavli_running_parameters('serviceProvider')
        if service_provider is not None:
            print("Service Provider:", service_provider)
        else:
            print("Service Provider not found.")

    def display_sim_swap(self):
        sim_swap = self.retrieve_cavli_running_parameters('simSwap')
        if sim_swap is not None:
            print("SIM Swap:", sim_swap)
        else:
            print("SIM Swap not found.")

    def display_IMEI(self):
        service_provider = self.retrieve_cavli_running_parameters('IMEI')
        if IMEI is not None:
            print("IMEI:", IMEI)
        else:
            print("IMEI not found.")

    def display_SerialNumber(self):
        SerialNumber = self.retrieve_cavli_running_parameters('SerialNumber')
        if SerialNumber is not None:
            print("Serial Number:", SerialNumber)
        else:
            print("Serial Number not found.")

    # --------------------------------------------------
    # UPDATE METHODS
    # --------------------------------------------------
    def update_latitude(self, value):
        self.update_cavli_running_parameters('latitude', value)

    def update_longitude(self, value):
        self.update_cavli_running_parameters('longitude', value)

    def update_data_sending(self, value):
        self.update_cavli_running_parameters('dataSending', value)

    def update_modem_status(self, value):
        self.update_cavli_running_parameters('modemStatus', value)

    def update_service_provider(self, value):
        self.update_cavli_running_parameters('serviceProvider', value)

    def update_sim_swap(self, value):
        self.update_cavli_running_parameters('simSwap', value)

    def update_IMEI(self, value):
        self.update_cavli_running_parameters('IMEI', value)

    def update_SerialNumber(self, value):
        self.update_cavli_running_parameters('SerialNumber', value)

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


class NetworkInfo:
    def __init__(self, db_name="network_info.db"):
        self.db_name = db_name

    def fetch_individual_elements(self):
        # DB-FIX: close() was inside try branches — leaks on exception; moved to finally
        conn = None
        try:
            conn = sqlite3.connect(self.db_name)
            cursor = conn.cursor()
            cursor.execute('''SELECT ip_address, latitude, longitude, date_time, connection_status FROM network_info 
                              ORDER BY id DESC LIMIT 1''')
            row = cursor.fetchone()
            if row:
                return row
            return None, None, None, None, None
        except Exception as e:
            print("Error retrieving individual elements:", e)
            logger.error("Error retrieving individual elements:", e)
            return None, None, None, None, None
        finally:
            if conn: conn.close()

    def fetch_connection_status(self):
        conn = None
        try:
            conn = sqlite3.connect(self.db_name)
            cursor = conn.cursor()
            cursor.execute('''SELECT connection_status FROM network_info 
                              ORDER BY id DESC LIMIT 1''')
            row = cursor.fetchone()
            return row[0] if row else None
        except Exception as e:
            print("Error retrieving connection status:", e)
            logger.error("Error retrieving connection status:", e)
            return None
        finally:
            if conn: conn.close()  # DB-FIX: was inside try branches

    def print_individual_elements(self):
        conn = None
        try:
            conn = sqlite3.connect(self.db_name)
            cursor = conn.cursor()
            cursor.execute('''SELECT ip_address, latitude, longitude, date_time, connection_status FROM network_info 
                              ORDER BY id DESC LIMIT 1''')
            row = cursor.fetchone()
            if row:
                ip_address, latitude, longitude, date_time, connection_status = row
                
                # Splitting date and time
                date_parts, time_parts = date_time.split(" ")
                year, month, day = date_parts.split("-")
                hour, minute, _ = time_parts.split(":")
                
            else:
                print("No network information found.")
        except Exception as e:
            print("Error retrieving individual elements:", e)
            logger.error("Error retrieving individual elements:", e)
        finally:
            if conn: conn.close()  # DB-FIX: was at end of try, not in finally

    def get_connection_status(self):
        conn = None
        try:
            conn = sqlite3.connect(self.db_name)
            cursor = conn.cursor()
            cursor.execute('''SELECT connection_status FROM network_info 
                          ORDER BY id DESC LIMIT 1''')
            row = cursor.fetchone()
            return row[0] if row else None
        except Exception as e:
            print("Error retrieving connection status:", e)
            logger.error("Error retrieving connection status:", e)
            return None
        finally:
            if conn: conn.close()  # DB-FIX: was inside try branches


class DeviceCounter:
    def __init__(self, db_name="device_counter.db"):
        """Initialize the device counter database and ensure the counter is set up."""
        self.db_name = db_name
        self._initialize_counter()

    def _create_connection(self):
        """Create a new database connection."""
        return sqlite3.connect(self.db_name)

    def _create_table(self):
        """Create the device counter table if it doesn't exist."""
        conn = None
        try:
            conn = self._create_connection()
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS device_counter (
                    id INTEGER PRIMARY KEY,
                    value INTEGER
                )
            ''')
            conn.commit()
        except sqlite3.Error as e:
            print("Error creating table:", e)
            logger.error("[ControllerDatabaseManager.create_table] %s", e)
        finally:
            if conn:
                conn.close()

    def _initialize_counter(self):
        """Initialize the device counter value in the database if not already present."""
        self._create_table()
        if self._get_count() is None:
            conn = None
            try:
                conn = self._create_connection()
                cursor = conn.cursor()
                cursor.execute('INSERT INTO device_counter (value) VALUES (0)')
                conn.commit()
            except sqlite3.Error as e:
                print("Error initializing counter:", e)
                logger.error("Error initializing counter:", e)
            finally:
                if conn:
                    conn.close()

    def _get_count(self):
        """Get the current device counter value from the database."""
        conn = None
        try:
            conn = self._create_connection()
            cursor = conn.cursor()
            cursor.execute('SELECT value FROM device_counter WHERE id = 1')
            row = cursor.fetchone()
            return row[0] if row else None
        except sqlite3.Error as e:
            print("Error fetching counter value:", e)
            logger.error("Error fetching counter value:", e)
        finally:
            if conn:
                conn.close()

    def _update_count(self, value):
        """Update the device counter value in the database."""
        conn = None
        try:
            conn = self._create_connection()
            cursor = conn.cursor()
            cursor.execute('UPDATE device_counter SET value = ? WHERE id = 1', (value,))
            conn.commit()
        except sqlite3.Error as e:
            print("Error updating counter value:", e)
            logger.error("Error updating counter value:", e)
        finally:
            if conn:
                conn.close()

    def increment(self):
        """Increment the device counter by one."""
        try:
            current_value = self._get_count()
            new_value = current_value + 1
            self._update_count(new_value)
        except TypeError as e:
            print("Error during increment:", e)
            logger.error("Error during increment:", e)

    def decrement(self):
        """Decrement the device counter by one, ensuring it does not go below zero."""
        try:
            current_value = self._get_count()
            if current_value > 0:
                new_value = current_value - 1
                self._update_count(new_value)
        except TypeError as e:
            print("Error during decrement:", e)
            logger.error("Error during decrement:", e)

    def reset(self):
        """Reset the device counter to zero."""
        try:
            self._update_count(0)
        except TypeError as e:
            print("Error during reset:", e)
            logger.error("Error during reset:", e)

    def get_value(self):
        """Get the current value of the device counter."""
        try:
            return self._get_count()
        except TypeError as e:
            print("Error getting counter value:", e)
            logger.error("Error getting counter value:", e)
            return None


class ControllerDatabaseManager:
    def __init__(self, db_name=DB_CONTROLLER_PARAMS):  # DB-FIX: use imported constant
        self.db_name = db_name

    def connect(self):
        try:
            self.conn = sqlite3.connect(self.db_name)
            return self.conn
        except sqlite3.Error as e:
            print("Error connecting to database:", e)
            logger.error("[ControllerDatabaseManager.connect] %s", e)
            return None

    def create_table(self):
        conn = self.connect()
        if conn is not None:
            try:
                cursor = conn.cursor()
                cursor.execute('''CREATE TABLE IF NOT EXISTS parameters (
                    id INTEGER PRIMARY KEY,
                    panel_current REAL,
                    battery_voltage REAL,
                    ac_voltage REAL,
                    lithium_ion_bat_volt_sense REAL
                )''')
                conn.commit()
            except sqlite3.Error as e:
                print("Error creating table:", e)
                logger.error("[ControllerDatabaseManager.create_table] %s", e)
            finally:
                conn.close()

    def insert_or_update_parameters(self, panel_current, battery_voltage, ac_voltage, lithium_ion_bat_volt_sense):
        conn = self.connect()
        if conn is not None:
            try:
                cursor = conn.cursor()
                cursor.execute('''SELECT COUNT(*) FROM parameters''')
                count = cursor.fetchone()[0]

                if count > 0:
                    cursor.execute('''UPDATE parameters
                                      SET panel_current = ?, battery_voltage = ?, ac_voltage = ?, lithium_ion_bat_volt_sense = ?
                                      WHERE id = 1''', (panel_current, battery_voltage, ac_voltage, lithium_ion_bat_volt_sense))
#                    print("Parameters updated successfully.")
                else:
                    cursor.execute('''INSERT INTO parameters (panel_current, battery_voltage, ac_voltage, lithium_ion_bat_volt_sense)
                                      VALUES (?, ?, ?, ?)''', (panel_current, battery_voltage, ac_voltage, lithium_ion_bat_volt_sense))
#                    print("Parameters inserted successfully.")
                conn.commit()
            except sqlite3.Error as e:
                print("Error inserting or updating parameters:", e)
                logger.error("[ControllerDatabaseManager.insert_or_update] %s", e)
            finally:
                conn.close()

    def fetch_and_print_parameters(self):
        conn = self.connect()
        if conn is not None:
            try:
                cursor = conn.cursor()
                cursor.execute('''SELECT * FROM parameters''')
                rows = cursor.fetchall()
                for row in rows:
                    print("ID:", row[0])
                    print("Panel Current:", row[1])
                    print("Battery Voltage:", row[2])
                    print("AC Voltage:", row[3])
                    print("Lithium-ion Battery Voltage Sense:", row[4])
            except sqlite3.Error as e:
                print("Error fetching parameters:", e)
                logger.error("[ControllerDatabaseManager.fetch] %s", e)
            finally:
                conn.close()

    def get_panel_current(self):
        conn = self.connect()
        if conn is not None:
            try:
                cursor = conn.cursor()
                cursor.execute('''SELECT panel_current FROM parameters WHERE id = 1''')
                result = cursor.fetchone()
                if result:
                    return result[0]
                return None
            except sqlite3.Error as e:
                print("Error getting panel current:", e)
                logger.error("Error getting panel current:", e)
                return None
            finally:
                conn.close()

    def get_battery_voltage(self):
        conn = self.connect()
        if conn is not None:
            try:
                cursor = conn.cursor()
                cursor.execute('''SELECT battery_voltage FROM parameters WHERE id = 1''')
                result = cursor.fetchone()
                if result:
                    return result[0]
                return None
            except sqlite3.Error as e:
                print("Error getting battery voltage:", e)
                logger.error("Error getting battery voltage:", e)
                return None
            finally:
                conn.close()

    def get_ac_voltage(self):
        conn = self.connect()
        if conn is not None:
            try:
                cursor = conn.cursor()
                cursor.execute('''SELECT ac_voltage FROM parameters WHERE id = 1''')
                result = cursor.fetchone()
                if result:
                    return result[0]
                return None
            except sqlite3.Error as e:
                print("Error getting AC voltage:", e)
                logger.error("Error getting AC voltage:", e)
                return None
            finally:
                conn.close()

    def get_lithium_ion_bat_volt_sense(self):
        conn = self.connect()
        if conn is not None:
            try:
                cursor = conn.cursor()
                cursor.execute('''SELECT lithium_ion_bat_volt_sense FROM parameters WHERE id = 1''')
                result = cursor.fetchone()
                if result:
                    return result[0]
                return None
            except sqlite3.Error as e:
                print("Error getting lithium-ion battery voltage sense:", e)
                logger.error("[ControllerDatabaseManager.get_lithium_ion] %s", e)
                return None
            finally:
                conn.close()


counterTimer1Sec6 = 0
SCHEDULE_UPDATE_GNSS_NETWORK = 780


counter1Sec = 0
counter500mSec = 0
counter3Sec = 0
tick1Sec = 0
tick500mSec = 0
tick3Sec = 0
toggleBit1Sec = 0
toggleBit500mSecSec = 0
tick1Sec1 = 0
tick1Sec2 = 0
tick1Sec3 = 0
tick1Sec4 = 0
tick1Sec5 = 0
tick1Sec6 = 0
tick500mSec1 = 0 
tick500mSec2 = 0
tick3Sec1 = 0
tick3Sec2 = 0
tick3Sec4 = 0

counter1Min = 0
tick1Min = 0

counter10Min = 0
counter10Min_1 = 0
tick10Min = 0
tick10Min_1 = 0

reset10MinCounter = 0
reset10MinCounter_1 = 0

tick3MinTimer1 = 0
tick3MinTimer2 = 0

counter250mSec = 0
tick250mSec = 0
toggleBit250mSecSec = 0

tick1Min1 = 0
tick1Min2 = 0
counter15Min = 0
tick15Min = 0
tick3Sec3 = 0
counter1min1 = 0

# -------------------------------------------- Tick Timer ----------------------------------------------
# DEF0036 / tickTimer()
# ------------------------------------------------------------------------------------------------------            
def tickTimer():
    ''' Tick Timer from Delay Timer Routine '''
    
    DELAY_TIME = 0.1#0.01
    DELAY_1SEC = 4#10
    DELAY_500mSEC = 2#5
    DELAY_3SEC = 12#30
    DELAY_1MIN = int(240*3)
    DELAY_10MIN = 240*10
    DELAY_15MIN = DELAY_1MIN * 15 
    DELAY_250mSEC = 1

    global counter1Sec
    global counter500mSec
    global counter3Sec
    global tick1Sec
    global tick500mSec
    global tick3Sec
    global toggleBit1Sec
    global toggleBit500mSecSec
    global tick1Sec1
    global tick1Sec2
    global tick1Sec3
    global tick1Sec4
    global tick1Sec5
    global tick1Sec6
    global tick500mSec1
    global tick500mSec2
    global tick3Sec1
    global tick3Sec2
    global tick3Sec4

    global counter1Min
    global tick1Min

    global counter10Min
    global counter10Min_1
    global tick10Min
    global tick10Min_1

    global reset10MinCounter
    global reset10MinCounter_1

    global tick3MinTimer1
    global tick3MinTimer2

    global counter250mSec
    global tick250mSec
    global toggleBit250mSecSec

    global tick1Min1
    global tick1Min2
    global counter15Min
    global tick15Min
    global tick3Sec3
    global counter1min1
    
    time.sleep(0.1)
    
    counter1Sec = counter1Sec + 1
    if counter1Sec > DELAY_1SEC:
        counter1Sec = 0
        tick1Sec = 1
        
    counter500mSec = counter500mSec + 1
    if counter500mSec > DELAY_500mSEC:
       counter500mSec = 0
       tick500mSec = 1

    counter250mSec = counter250mSec + 1
    if counter250mSec > DELAY_250mSEC:    
        counter250mSec = 0
        tick250mSec = 1
        
    counter3Sec = counter3Sec + 1
    if counter3Sec > DELAY_3SEC:
       counter3Sec = 0
       tick3Sec = 1

    counter1Min = int(counter1Min + 1)
    if counter1Min > DELAY_1MIN:
       counter1Min = 0
       tick1Min = 1

    if tick1Min == 1:
        tick1Min = 0
        tick3MinTimer1 = 1
        tick3MinTimer2 = 1
        tick1Min1 = 1

    if tick1Min1 == 1:
        tick1Min1 = 0
        counter15Min = counter15Min + 1
        if counter15Min > 15:
            counter15Min = 0
            tick15Min = 1 
    
    if reset10MinCounter == 1:
        reset10MinCounter = 0
        counter10Min = 0
        
    counter10Min = int(counter10Min + 1)
    if counter10Min > DELAY_10MIN:
       counter10Min = 0
       tick10Min = 1

    if reset10MinCounter_1 == 1:
        reset10MinCounter_1 = 0
        counter10Min_1 = 0
        
    counter10Min_1 = int(counter10Min_1 + 1)
    if counter10Min_1 > DELAY_10MIN:
       counter10Min_1 = 0
       tick10Min_1 = 1

    if tick1Sec == 1:
        tick1Sec = 0
        toggleBit1Sec = not toggleBit1Sec
        tick1Sec1 = 1
        tick1Sec2 = 1
        tick1Sec3 = 1
        tick1Sec4 = 1
        tick1Sec5 = 1
        tick1Sec6 = 1
        
    if tick500mSec == 1:
        tick500mSec = 0
        toggleBit500mSecSec = not toggleBit500mSecSec
        tick500mSec1 = 1
        tick500mSec2 = 1

    if tick250mSec == 1:
        tick250mSec = 0
        toggleBit250mSecSec = not toggleBit250mSecSec
        
    if tick3Sec == 1:
        tick3Sec = 0
        tick3Sec1 = 1
        tick3Sec2 = 1
        tick3Sec3 = 1
        tick3Sec4 = 1

    if tick3Sec3 == 1:
        tick3Sec3 = 0
        counter1min1 = counter1min1 + 1
        if counter1min1 > 25:
            counter1min1 = 0
            tick1Min2 = 1


#  SH2                     Q7/7                 Q6/6                    Q5/5                    Q4/4                    Q3/3                    Q2/2                        Q1/1                Q0/15
frontPanelLED1 = {'NOT_IMPLEMENTED':0x80, 'FAS_FAULT_LED':0x40, 'BAS_ACTIVE_LED':0x20, 'TIME_LOCK_OFF_LED':0x10, 'BAS_FAULT_LED':0x08, 'TIME_LOCK_FAULT_LED':0x04, 'NVR_DVR_OFF_LED':0x02, 'CCTV_TAMPER_LED':0x01}

#  SH3                     Q7/7                 Q6/6                    Q5/5                   Q4/4                    Q3/3                    Q2/2                         Q1/1                Q0/15
frontPanelLED2 = {'NOT_IMPLEMENTED':0x80, 'SYSTEM_HEALTHY_LED':0x40, 'BACS_OFF_LED':0x20, 'CCTV_HDD_ERROR_LED':0x10, 'BAT_ON_LED':0x08, 'CCTV_DISCONNECTED_LED':0x04, 'FAS_ACTIVE_LED':0x02, 'BAS_OFF_LED':0x01}
                                                                                                                                                                                            
#  SH1                  Q7/7                Q6/6              Q5/5                 Q4/4             Q3/3            Q2/2            Q1/1         Q0/15
relayBuzzer = {'NOT_IMPLEMENTED':0x80, 'LCD_BACK_ON':0x40,'REMOTE_BUZZER':0x20,'REMOTE_LED1':0x10,'BUZZER':0x08,'RELAY_3':0x04, 'RELAY_2':0x02, 'RELAY_1':0x01}

#  SH1                      Q7/7             Q6/6              Q5/5                 Q4/4                    Q3/3                    Q2/2                       Q1/1                    Q0/15
muxSelectionAndLED = {'4G_LTE_LED':0x80, 'FAS_OFF_LED':0x40,'NETWORK_LED':0x20,'BACS_FAULT_LED':0x10,'MUX_SELECT_LINE4':0x08,'MUX_SELECT_LINE3':0x04, 'MUX_SELECT_LINE2':0x02, 'MUX_SELECT_LINE1':0x01}


shiftRegSet = {'CLEAR':0x00,'SET':0xFF}

sr = ShiftRegister()

shiftRegister1Buffers = 0b00000000
shiftRegister2Buffers = 0b00000000
shiftRegister3Buffers = 0b00000000
shiftRegister4Buffers = 0b00000000

shiftRegister1Buffers |= 0b00000000
shiftRegister2Buffers |= 0b00000000
shiftRegister3Buffers |= 0b00000000
shiftRegister4Buffers |= 0b00000000

muxSelection = 0b00001111

# ── Communicator relay reset state (RELAY_1 = Cavli modem power) ─────────────
_relay1_reset_in_progress = False   # True while a power-cycle is underway
_relay1_reset_start_time  = 0.0     # time.time() snapshot of phase start
_relay1_reset_phase       = 0       # 0=idle 1=OFF(5s) 2=ON-wait(30s) 3=svc-restart
_relay1_error_holdoff     = 0.0     # don't re-trigger within hold-off window
_relay1_error_count       = 0       # consecutive 'Error' polls (need 2 to trigger)
_relay1_reboot_count      = 0       # reboots triggered today by this logic
_relay1_reboot_date       = None    # date of last reboot counter reset
_RELAY1_MAX_REBOOTS_PER_DAY = 2     # safety cap — max forced reboots per day


def createDatabase():
    connection = sqlite3.connect(DB_PANEL)
    try:
        cursor = connection.cursor()
        cursor.execute(
            "CREATE TABLE IF NOT EXISTS systemLogs "
            "(deviceType TEXT, logType TEXT, rtcYear INTEGER, rtcMonth INTEGER, "
            "rtcDate INTEGER, rtcHour INTEGER, rtcMinute INTEGER, rtcSecound INTEGER)"
        )  # DB-FIX: was bare CREATE TABLE + bare except; use IF NOT EXISTS instead
        connection.commit()
    except sqlite3.Error as e:
        logger.error("[createDatabase] %s", e)
    finally:
        connection.close()

def writeLogToDatabase(deviceType=None, logType=None, rtcYear=None, rtcMonth=None, rtcDate=None, rtcHour=None, rtcMinute=None, rtcSecound=None):

    try:        
        rtcYear = ds1307._read_year()
    except IOError:
        rtcYear = 0
    except ValueError:
        rtcYear = 0

    try:
        rtcMonth = ds1307._read_month()
    except IOError:
        rtcMonth = 0
    except ValueError:
        rtcMonth = 0

    try:
        rtcDate = ds1307._read_date()
    except IOError: 
        rtcDate = 0
    except ValueError:
        rtcDate = 0

    try:
        rtcHour = ds1307._read_hours()
    except IOError: 
        rtcHour = 0
    except ValueError:
        rtcHour = 0
        
    try:
        rtcMinute = ds1307._read_minutes()
        gTemp1 = rtcMinute
    except IOError:
        rtcMinute = 0
    except ValueError:
        rtcMinute = 0
        
    try:
        rtcSecound = ds1307._read_seconds()
    except IOError:
        rtcSecound = 0
    except ValueError:
        rtcSecound = 0

    # DB-FIX: wrap in try/finally so connection is always closed (previously leaked)
    connection = sqlite3.connect(DB_PANEL)
    try:
        cursor = connection.cursor()
        # DB-FIX: was bare CREATE TABLE + bare except; use IF NOT EXISTS
        try:
            cursor.execute(
                "CREATE TABLE IF NOT EXISTS systemLogs "
                "(deviceType TEXT, logType TEXT, rtcYear INTEGER, rtcMonth INTEGER, "
                "rtcDate INTEGER, rtcHour INTEGER, rtcMinute INTEGER, rtcSecound INTEGER)"
            )
        except sqlite3.OperationalError:
            pass
        cursor.execute(
            "INSERT INTO systemLogs (deviceType, logType, rtcYear, rtcMonth, rtcDate, "
            "rtcHour, rtcMinute, rtcSecound) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (deviceType, logType, rtcYear, rtcMonth, rtcDate, rtcHour, rtcMinute, rtcSecound)
        )
        connection.commit()
    except sqlite3.Error as e:
        print("Error writing log:", e)
        logger.error("[writeLogToDatabase] %s", e)
    finally:
        connection.close()

    
def readLogFromDatabase():
    rows = cursor.execute("SELECT deviceType, logType, rtcYear, rtcMonth, rtcDate, rtcHour, rtcMinute, rtcSecound  FROM systemLogs").fetchall()
    print(rows)

def clearLogsFromDB():
    connection = None
    try:
        # Connect to the SQLite database
        connection = sqlite3.connect(DB_PANEL)
        cursor = connection.cursor()

        # Execute the DELETE statement to clear all records
        cursor.execute("DELETE FROM systemLogs")

        # Commit the transaction
        connection.commit()

    except sqlite3.Error as e:
        print("Error clearing database:", e)
        logger.error("Error clearing database:", e)
        #return False

    finally:
        # Close the connection
        if connection:
            connection.close()


counterLogType = 0


class Counter:
    def __init__(self, limit):
        self.limit = limit
        self.count = 0
        self.running = False

    def start_counter(self):
        self.running = True

    def increment(self):
        if self.running:
            self.count += 1
            if self.count >= self.limit:
                return True  # Counter reached the set value
        return False

    def reset(self):
        self.count = 0

    def check_reset_counter(self):
        if self.count >= self.limit:
            self.reset()


class EthernetProcess:
    def execute(self):
#        scheduleGETDataForGNSSNetwork
        setup_mode_value = system_settings_db.retrieve_element("setup_mode")        
        if setup_mode_value == "disabled":
            send_to_ethernet_subprocess()    
        
class ESIM_GSMProcess:
    def execute(self):
        setup_mode_value = system_settings_db.retrieve_element("setup_mode")        
        if setup_mode_value == "disabled":
            send_to_cavli_subprocess()


class CombinedEthernetESIMProcess:
    def __init__(self):
        self.ethernet_process = EthernetProcess()
        self.esim_gsm_process = ESIM_GSMProcess()

    def execute(self):
        self.ethernet_process.execute()
        self.esim_gsm_process.execute()
        #print("Executed Combined Ethernet and eSIM/GSM Processes")

class ProcessController:
    def __init__(self):
        self.processes = {
            1: EthernetProcess(),
            2: ESIM_GSMProcess(),
            3: CombinedEthernetESIMProcess()
        }

    def execute_process(self, process_number):
        process = self.processes.get(process_number)
        if process:
            process.execute()
        else:
            print("Invalid input, no process found for the given number")



fieldInputStatusLED1 = 0
fieldInputStatusLED2 = 0
zoneCounter = 0


# MUX DEBOUNCE: require this many consecutive identical reads before firing an event.
# Eliminates false triggers from mux switching transients and contact noise.
# 3 reads × ~16 loop positions × ~10ms each = ~480ms minimum debounce window.
# Real events (held > 480ms) always fire. Transient glitches (< 480ms) are ignored.
MUX_CONFIRM_READS = 3
_mux_pending = {}   # {varname: (pending_state, consecutive_count)}

mux1_x0 = -1  # -1 = unseen on boot; fires initial scan
mux1_x1 = -1  # -1 = unseen on boot; fires initial scan
mux1_x2 = -1  # -1 = unseen on boot; fires initial scan
mux1_x3 = -1  # -1 = unseen on boot; fires initial scan
mux1_x4 = -1  # -1 = unseen on boot; fires initial scan
mux1_x5 = -1  # -1 = unseen on boot; fires initial scan
mux1_x6 = -1  # -1 = unseen on boot; fires initial scan
mux1_x7 = -1  # -1 = unseen on boot; fires initial scan
mux1_x8 = -1  # -1 = unseen on boot; fires initial scan
mux1_x9 = -1  # -1 = unseen on boot; fires initial scan
mux1_x10 = -1  # -1 = unseen on boot; fires initial scan
mux1_x11 = -1  # -1 = unseen on boot; fires initial scan
mux1_x12 = -1  # -1 = unseen on boot; fires initial scan
mux1_x13 = -1  # -1 = unseen on boot; fires initial scan
mux1_x14 = -1  # -1 = unseen on boot; fires initial scan
mux1_x15 = -1  # -1 = unseen on boot; fires initial scan
mux2_x0 = -1  # -1 = unseen on boot; fires initial scan
mux2_x1 = -1  # -1 = unseen on boot; fires initial scan
mux2_x2 = -1  # -1 = unseen on boot; fires initial scan
mux2_x3 = -1  # -1 = unseen on boot; fires initial scan
mux2_x4 = -1  # -1 = unseen on boot; fires initial scan
mux2_x5 = -1  # -1 = unseen on boot; fires initial scan
mux2_x6 = -1  # -1 = unseen on boot; fires initial scan
mux2_x7 = -1  # -1 = unseen on boot; fires initial scan
mux2_x8 = -1  # -1 = unseen on boot; fires initial scan
mux2_x9 = -1  # -1 = unseen on boot; fires initial scan
mux2_x10 = -1  # -1 = unseen on boot; fires initial scan
mux2_x11 = -1  # -1 = unseen on boot; fires initial scan
mux2_x12 = -1  # -1 = unseen on boot; fires initial scan
mux2_x13 = -1  # -1 = unseen on boot; fires initial scan
mux2_x14 = -1  # -1 = unseen on boot; fires initial scan
mux2_x15 = -1  # -1 = unseen on boot; fires initial scan
mux3_x0 = -1  # -1 = unseen on boot; fires initial scan
mux3_x1 = -1  # -1 = unseen on boot; fires initial scan
mux3_x2 = -1  # -1 = unseen on boot; fires initial scan
mux3_x3 = -1  # -1 = unseen on boot; fires initial scan
mux3_x4 = -1  # -1 = unseen on boot; fires initial scan
mux3_x5 = -1  # -1 = unseen on boot; fires initial scan
mux3_x6 = -1  # -1 = unseen on boot; fires initial scan
mux3_x7 = -1  # -1 = unseen on boot; fires initial scan
mux3_x8 = -1  # -1 = unseen on boot; fires initial scan
mux3_x9 = -1  # -1 = unseen on boot; fires initial scan
mux3_x10 = -1  # -1 = unseen on boot; fires initial scan
mux3_x11 = -1  # -1 = unseen on boot; fires initial scan
mux3_x12 = -1  # -1 = unseen on boot; fires initial scan
mux3_x13 = -1  # -1 = unseen on boot; fires initial scan
mux3_x14 = -1  # -1 = unseen on boot; fires initial scan
mux3_x15 = -1  # -1 = unseen on boot; fires initial scan
mux4_x0 = -1  # -1 = unseen on boot; fires initial scan
mux4_x1 = -1  # -1 = unseen on boot; fires initial scan
mux4_x2 = -1  # -1 = unseen on boot; fires initial scan
mux4_x3 = -1  # -1 = unseen on boot; fires initial scan
mux4_x4 = -1  # -1 = unseen on boot; fires initial scan
mux4_x5 = -1  # -1 = unseen on boot; fires initial scan
mux4_x6 = -1  # -1 = unseen on boot; fires initial scan
mux4_x7 = -1  # -1 = unseen on boot; fires initial scan
mux4_x8 = -1  # -1 = unseen on boot; fires initial scan
mux4_x9 = -1  # -1 = unseen on boot; fires initial scan
mux4_x10 = -1  # -1 = unseen on boot; fires initial scan
mux4_x11 = -1  # -1 = unseen on boot; fires initial scan
mux4_x12 = -1  # -1 = unseen on boot; fires initial scan
mux4_x13 = -1  # -1 = unseen on boot; fires initial scan
mux4_x14 = -1  # -1 = unseen on boot; fires initial scan
mux4_x15 = -1  # -1 = unseen on boot; fires initial scan
systemPowerOffShutDownMode = 0


MAINLOCK = 8                        # Pin 24 (mux_3_output)
BYPASS_KEY = 9                      # Pin 21 (mux_2_output)
TAMPER = 10                         # Pin 19 (mux_1_output)
DURESS_REMOTE = 11                  # Pin 23 (N/A)  

GPIO.setup(MAINLOCK, GPIO.IN)       #  ACTIVE state is LOW
GPIO.setup(BYPASS_KEY, GPIO.IN)     #  ACTIVE state is LOW
GPIO.setup(TAMPER, GPIO.IN)         #  ACTIVE state is HIGH
GPIO.setup(DURESS_REMOTE, GPIO.IN)  #  ACTIVE state is LOW

GPIO.setup(MAINLOCK, GPIO.IN, pull_up_down=GPIO.PUD_UP)
GPIO.setup(BYPASS_KEY, GPIO.IN, pull_up_down=GPIO.PUD_UP)
GPIO.setup(TAMPER, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
GPIO.setup(DURESS_REMOTE, GPIO.IN, pull_up_down=GPIO.PUD_UP)


def muxSelectionZoneInitScan( value = 0, muxChSelection = 0b0000000 ):

    global BYPASS_KEY
    global TAMPER
    global MAINLOCK
    global DURESS_REMOTE

    global fieldInputStatusLED1
    global fieldInputStatusLED2
    global zoneCounter
    global muxSelection
    
    mux_1 = 0
    mux_2 = 0
    mux_3 = 0
    mux_4 = 0

    mux_1 = GPIO.input(TAMPER)
    mux_2 = GPIO.input(BYPASS_KEY)
    mux_3 = GPIO.input(MAINLOCK)
    mux_4 = GPIO.input(DURESS_REMOTE)


    fieldInputStatusLED1 = 0b00000000
    
    if mux_1 == 1:
        fieldInputStatusLED1 = fieldInputStatusLED1 | 0b00000001
    if mux_2 == 1:        
        fieldInputStatusLED1 = fieldInputStatusLED1 | 0b00000010
    if mux_3 == 1:        
        fieldInputStatusLED1 = fieldInputStatusLED1 | 0b00000100
    if mux_4 == 1:
        fieldInputStatusLED1 = fieldInputStatusLED1 | 0b00001000


    global mux1_x0
    global mux1_x1
    global mux1_x2
    global mux1_x3
    global mux1_x4
    global mux1_x5
    global mux1_x6
    global mux1_x7
    global mux1_x8
    global mux1_x9
    global mux1_x10
    global mux1_x11
    global mux1_x12
    global mux1_x13
    global mux1_x14
    global mux1_x15

    global mux2_x0
    global mux2_x1
    global mux2_x2
    global mux2_x3
    global mux2_x4
    global mux2_x5
    global mux2_x6
    global mux2_x7
    global mux2_x8
    global mux2_x9
    global mux2_x10
    global mux2_x11
    global mux2_x12
    global mux2_x13
    global mux2_x14
    global mux2_x15

    global mux3_x0
    global mux3_x1
    global mux3_x2
    global mux3_x3
    global mux3_x4
    global mux3_x5
    global mux3_x6
    global mux3_x7
    global mux3_x8
    global mux3_x9
    global mux3_x10
    global mux3_x11
    global mux3_x12
    global mux3_x13
    global mux3_x14
    global mux3_x15
    
    global mux4_x0
    global mux4_x1
    global mux4_x2
    global mux4_x3
    global mux4_x4
    global mux4_x5
    global mux4_x6
    global mux4_x7
    global mux4_x8
    global mux4_x9
    global mux4_x10
    global mux4_x11
    global mux4_x12
    global mux4_x13
    global mux4_x14
    global mux4_x15

    global zoneSettings
    global powerZoneSettings

    global zoneIsCamDisconnected
    global zoneIsFault
    global zoneIsPowerOff
    global zoneIsActive
    global zoneIsHDDError
    global powerZoneIsActive
    global zoneIsCamTamper

    Z1 = 0
    Z2 = 0
    Z3 = 0
    Z4 = 0
    Z5 = 0
    Z6 = 0
    Z7 = 0
    Z8 = 0
    Z9 = 0
    Z10 = 0
    Z11 = 0
    Z12 = 0
    Z13 = 0
    Z14 = 0
    Z15 = 0
    Z16 = 0

    PZ1 = 0
    PZ2 = 0
    PZ3 = 0
    PZ4 = 0
    PZ5 = 0
    PZ6 = 0
    PZ7 = 0
    PZ8 = 0
    PZ9 = 0
    PZ10 = 0
    PZ11 = 0
    PZ12 = 0
    PZ13 = 0
    PZ14 = 0
    PZ15 = 0
    PZ16 = 0
    
        
    if zoneSettings[2] == 1:
        Z1 = 'BAS'
    elif zoneSettings[2] == 2:
        Z1 = 'FAS'
    elif zoneSettings[2] == 3:
        Z1 = 'TIME_LOCK'
    elif zoneSettings[2] == 4:
        Z1 = 'BACS'
    elif zoneSettings[2] == 6:
        Z1 = 'IAS'

    if zoneSettings[5] == 1:
        Z2 = 'BAS'
    elif zoneSettings[5] == 2:
        Z2 = 'FAS'
    elif zoneSettings[5] == 3:
        Z2 = 'TIME_LOCK'
    elif zoneSettings[5] == 4:
        Z2 = 'BACS'
    elif zoneSettings[5] == 6:
        Z2 = 'IAS'


    if zoneSettings[8] == 1:
        Z3 = 'BAS'
    elif zoneSettings[8] == 2:
        Z3 = 'FAS'
    elif zoneSettings[8] == 3:
        Z3 = 'TIME_LOCK'
    elif zoneSettings[8] == 4:
        Z3 = 'BACS'
    elif zoneSettings[8] == 6:
        Z3 = 'IAS'
    

    if zoneSettings[11] == 1:
        Z4 = 'BAS'
    elif zoneSettings[11] == 2:
        Z4 = 'FAS'
    elif zoneSettings[11] == 3:
        Z4 = 'TIME_LOCK'
    elif zoneSettings[11] == 4:
        Z4 = 'BACS'
    elif zoneSettings[11] == 6:
        Z4 = 'IAS'


    if zoneSettings[14] == 1:
        Z5 = 'BAS'
    elif zoneSettings[14] == 2:
        Z5 = 'FAS'
    elif zoneSettings[14] == 3:
        Z5 = 'TIME_LOCK'
    elif zoneSettings[14] == 4:
        Z5 = 'BACS'
    elif zoneSettings[14] == 6:
        Z5 = 'IAS'


    if zoneSettings[17] == 1:
        Z6 = 'BAS'
    elif zoneSettings[17] == 2:
        Z6 = 'FAS'
    elif zoneSettings[17] == 3:
        Z6 = 'TIME_LOCK'
    elif zoneSettings[17] == 4:
        Z6 = 'BACS'
    elif zoneSettings[17] == 6:
        Z6 = 'IAS'


    if zoneSettings[20] == 1:
        Z7 = 'BAS'
    elif zoneSettings[20] == 2:
        Z7 = 'FAS'
    elif zoneSettings[20] == 3:
        Z7 = 'TIME_LOCK'
    elif zoneSettings[20] == 4:
        Z7 = 'BACS'
    elif zoneSettings[20] == 6:
        Z7 = 'IAS'


    if zoneSettings[23] == 1:
        Z8 = 'BAS'
    elif zoneSettings[23] == 2:
        Z8 = 'FAS'
    elif zoneSettings[23] == 3:
        Z8 = 'TIME_LOCK'
    elif zoneSettings[23] == 4:
        Z8 = 'BACS'
    elif zoneSettings[23] == 6:
        Z8 = 'IAS'


    if zoneSettings[26] == 1:
        Z9 = 'BAS'
    elif zoneSettings[26] == 2:
        Z9 = 'FAS'
    elif zoneSettings[26] == 3:
        Z9 = 'TIME_LOCK'
    elif zoneSettings[26] == 4:
        Z9 = 'BACS'
    elif zoneSettings[26] == 6:
        Z9 = 'IAS'

    if zoneSettings[29] == 1:
        Z10 = 'BAS'
    elif zoneSettings[29] == 2:
        Z10 = 'FAS'
    elif zoneSettings[29] == 3:
        Z10 = 'TIME_LOCK'
    elif zoneSettings[29] == 4:
        Z10 = 'BACS'
    elif zoneSettings[29] == 6:
        Z10 = 'IAS'


    if zoneSettings[32] == 1:
        Z11 = 'BAS'
    elif zoneSettings[32] == 2:
        Z11 = 'FAS'
    elif zoneSettings[32] == 3:
        Z11 = 'TIME_LOCK'
    elif zoneSettings[32] == 4:
        Z11 = 'BACS'
    elif zoneSettings[32] == 6:
        Z11 = 'IAS'


    if zoneSettings[35] == 1:
        Z12 = 'BAS'
    elif zoneSettings[35] == 2:
        Z12 = 'FAS'
    elif zoneSettings[35] == 3:
        Z12 = 'TIME_LOCK'
    elif zoneSettings[35] == 4:
        Z12 = 'BACS'
    elif zoneSettings[35] == 6:
        Z12 = 'IAS'


    if zoneSettings[38] == 1:
        Z13 = 'BAS'
    elif zoneSettings[38] == 2:
        Z13 = 'FAS'
    elif zoneSettings[38] == 3:
        Z13 = 'TIME_LOCK'
    elif zoneSettings[38] == 4:
        Z13 = 'BACS'

    if zoneSettings[41] == 1:
        Z14 = 'BAS'
    elif zoneSettings[41] == 2:
        Z14 = 'FAS'
    elif zoneSettings[41] == 3:
        Z14 = 'TIME_LOCK'
    elif zoneSettings[41] == 4:
        Z14 = 'BACS'
    elif zoneSettings[41] == 6:
        Z14 = 'IAS'


    if powerZoneSettings[2] == 1:
        PZ1 = 'BAS'
    elif powerZoneSettings[2] == 2:
        PZ1 = 'FAS'
    elif powerZoneSettings[2] == 3:
        PZ1 = 'TIME_LOCK'
    elif powerZoneSettings[2] == 4:
        PZ1 = 'BACS'
    elif powerZoneSettings[2] == 5:
        PZ1 = 'CCTV'
    elif powerZoneSettings[2] == 6:
        PZ1 = 'IAS'

    if powerZoneSettings[5] == 1:
        PZ2 = 'BAS'
    elif powerZoneSettings[5] == 2:
        PZ2 = 'FAS'
    elif powerZoneSettings[5] == 3:
        PZ2 = 'TIME_LOCK'
    elif powerZoneSettings[5] == 4:
        PZ2 = 'BACS'
    elif powerZoneSettings[5] == 5:
        PZ2 = 'CCTV'
    elif powerZoneSettings[5] == 6:
        PZ2 = 'IAS'

    if powerZoneSettings[8] == 1:
        PZ3 = 'BAS'
    elif powerZoneSettings[8] == 2:
        PZ3 = 'FAS'
    elif powerZoneSettings[8] == 3:
        PZ3 = 'TIME_LOCK'
    elif powerZoneSettings[8] == 4:
        PZ3 = 'BACS'
    elif powerZoneSettings[8] == 5:
        PZ3 = 'CCTV'
    elif powerZoneSettings[8] == 6:
        PZ3 = 'IAS'

    if powerZoneSettings[11] == 1:
        PZ4 = 'BAS'
    elif powerZoneSettings[11] == 2:
        PZ4 = 'FAS'
    elif powerZoneSettings[11] == 3:
        PZ4 = 'TIME_LOCK'
    elif powerZoneSettings[11] == 4:
        PZ4 = 'BACS'
    elif powerZoneSettings[11] == 5:
        PZ4 = 'CCTV'
    elif powerZoneSettings[11] == 6:
        PZ4 = 'IAS'

    if powerZoneSettings[14] == 1:
        PZ5 = 'BAS'
    elif powerZoneSettings[14] == 2:
        PZ5 = 'FAS'
    elif powerZoneSettings[14] == 3:
        PZ5 = 'TIME_LOCK'
    elif powerZoneSettings[14] == 4:
        PZ5 = 'BACS'
    elif powerZoneSettings[14] == 5:
        PZ5 = 'CCTV'
    elif powerZoneSettings[14] == 6:
        PZ5 = 'IAS'

    if powerZoneSettings[17] == 1:
        PZ6 = 'BAS'
    elif powerZoneSettings[17] == 2:
        PZ6 = 'FAS'
    elif powerZoneSettings[17] == 3:
        PZ6 = 'TIME_LOCK'
    elif powerZoneSettings[17] == 4:
        PZ6 = 'BACS'
    elif powerZoneSettings[17] == 5:
        PZ6 = 'CCTV'
    elif powerZoneSettings[17] == 6:
        PZ6 = 'IAS'

    if powerZoneSettings[20] == 1:
        PZ7 = 'BAS'
    elif powerZoneSettings[20] == 2:
        PZ7 = 'FAS'
    elif powerZoneSettings[20] == 3:
        PZ7 = 'TIME_LOCK'
    elif powerZoneSettings[20] == 4:
        PZ7 = 'BACS'
    elif powerZoneSettings[20] == 5:
        PZ7 = 'CCTV'
    elif powerZoneSettings[20] == 6:
        PZ7 = 'IAS'

    if powerZoneSettings[23] == 1:
        PZ8 = 'BAS'
    elif powerZoneSettings[23] == 2:
        PZ8 = 'FAS'
    elif powerZoneSettings[23] == 3:
        PZ8 = 'TIME_LOCK'
    elif powerZoneSettings[23] == 4:
        PZ8 = 'BACS'
    elif powerZoneSettings[23] == 5:
        PZ8 = 'CCTV'
    elif powerZoneSettings[23] == 6:
        PZ8 = 'IAS'


    global powerZoneSettingsOnCounter 
    powerZoneSettingsOnCounter = 0
    if powerZoneSettings[0] == 1:
        powerZoneSettingsOnCounter = powerZoneSettingsOnCounter + 1
    if powerZoneSettings[3] == 1:
        powerZoneSettingsOnCounter = powerZoneSettingsOnCounter + 1
    if powerZoneSettings[6] == 1:
        powerZoneSettingsOnCounter = powerZoneSettingsOnCounter + 1
    if powerZoneSettings[9] == 1:   
        powerZoneSettingsOnCounter = powerZoneSettingsOnCounter + 1
    if powerZoneSettings[12] == 1:   
        powerZoneSettingsOnCounter = powerZoneSettingsOnCounter + 1
    if powerZoneSettings[15] == 1:    
        powerZoneSettingsOnCounter = powerZoneSettingsOnCounter + 1
    if powerZoneSettings[18] == 1:
        powerZoneSettingsOnCounter = powerZoneSettingsOnCounter + 1
    if powerZoneSettings[21] == 1:                
        powerZoneSettingsOnCounter = powerZoneSettingsOnCounter + 1

    global zoneIsActiveType
    global zoneIsFaultType
    global powerZoneIsActiveType

    global frontPanelLED2
    global shiftRegister3Buffers
    global zoneFaultBuzzerOn

    global powerZoneOnCounter


    pass_this_step = 0

    if muxSelection == 0:
        
        if mux_1 == 1:
            if mux1_x0 != 1:   # state-change: only act on transition
                mux1_x0 = 1
                if zoneSettings[0] == 1:
                    writeLogToDatabase(Z1,'ZONE_1_ACTIVE')
                    zoneIsActive[1] = 1
                    zoneIsActiveType[1] = Z1

                    if zoneSettings[1] == 1:
                        zoneFaultBuzzerOn = 1

                    generateReportMsg(Z1, 'system_activate')

        else:
            if mux1_x0 != 0:   # state-change: only act on transition
                mux1_x0 = 0
                if zoneSettings[0] == 1:
                    writeLogToDatabase(Z1,'ZONE_1_DEACTIVE')
                    zoneIsActive[1] = 0
                    zoneIsActiveType[1] = 0

                    generateReportMsg(Z1, 'system_activation_restored')


        if mux_2 == 1:
            if mux2_x0 != 1:   # state-change: only act on transition
                mux2_x0 = 1
                if zoneSettings[21] == 1:
                    writeLogToDatabase('CCTV','ZONE_8_CAM_DISCONNECTED')
                    zoneIsCamDisconnected[8] = 1

                    if zoneSettings[22] == 1:
                        zoneFaultBuzzerOn = 1
                        
                    generateReportMsg('CCTV', 'camera_disconnect')
                        
        else:
            if mux2_x0 != 0:   # state-change: only act on transition
                mux2_x0 = 0
                if zoneSettings[21] == 1:
                    writeLogToDatabase('CCTV','ZONE_8_CAM_CONNECTION_ESTABLISHED')
                    zoneIsCamDisconnected[8] = 0
                    
                    generateReportMsg('CCTV', 'connection_established')
        

        if mux_3 == 1:
            if mux3_x0 != 1:   # state-change: only act on transition
                mux3_x0 = 1
                if zoneSettings[39] == 1:
                    writeLogToDatabase(Z14,'ZONE_14_ACTIVE')
                    zoneIsActive[14] = 1
                    zoneIsActiveType[14] = Z14

                    if zoneSettings[40] == 1:
                        zoneFaultBuzzerOn = 1
                        
                    generateReportMsg(Z14, 'system_activate')
        else:                
            if mux3_x0 != 0:   # state-change: only act on transition
                mux3_x0 = 0
                if zoneSettings[39] == 1:
                    writeLogToDatabase(Z14,'ZONE_14_DEACTIVE')
                    zoneIsActive[14] = 0
                    zoneIsActiveType[14] = 0

                    generateReportMsg(Z14, 'system_activation_restored')

           
    elif muxSelection == 1:

        
        if mux_1 == 1:
            if mux1_x1 != 1:   # state-change: only act on transition
                mux1_x1 = 1
                if zoneSettings[0] == 1:
                    writeLogToDatabase(Z1,'ZONE_1_FAULT')
                    zoneIsFault[1] = 1
                    zoneIsFaultType[1] = Z1

                    if zoneSettings[1] == 1:
                        zoneFaultBuzzerOn = 1

                    generateReportMsg(Z1, 'alarm_system_fault')
                    
        else:
            if mux1_x1 != 0:   # state-change: only act on transition
                mux1_x1 = 0
                if zoneSettings[0] == 1:
                    writeLogToDatabase(Z1,'ZONE_1_RESTORE')
                    zoneIsFault[1] = 0
                    zoneIsFaultType[1] = 0
                    
                    generateReportMsg(Z1, 'system_fault_condition_restored')
                
        
        if mux_2 == 1:
            if mux2_x1 != 1:   # state-change: only act on transition
                mux2_x1 = 1
                if zoneSettings[21] == 1:
                    writeLogToDatabase('CCTV','ZONE_8_HDD_ERROR')
                    zoneIsHDDError[8] = 1

                    if zoneSettings[22] == 1:
                        zoneFaultBuzzerOn = 1

                    generateReportMsg('CCTV', 'hdd_error')                        
                    
        else:
            if mux2_x1 != 0:   # state-change: only act on transition
                mux2_x1 = 0
                if zoneSettings[21] == 1:                
                    writeLogToDatabase('CCTV','ZONE_8_HDD_ERROR_RESTORE')
                    zoneIsHDDError[8] = 0

                    generateReportMsg('CCTV', 'error_restored')                        
                    

        if mux_3 == 1:
            if mux3_x1 != 1:   # state-change: only act on transition
                mux3_x1 = 1
                if zoneSettings[39] == 1:                
                    writeLogToDatabase(Z14,'ZONE_14_FAULT')
                    zoneIsFault[14] = 1
                    zoneIsFaultType[14] = Z14
                    
                    if zoneSettings[40] == 1:
                        zoneFaultBuzzerOn = 1

                    generateReportMsg(Z14, 'alarm_system_fault')                                                
                    
        else:                
            if mux3_x1 != 0:   # state-change: only act on transition
                mux3_x1 = 0
                if zoneSettings[39] == 1:                                
                    writeLogToDatabase(Z14,'ZONE_14_RESTORE')
                    zoneIsFault[14] = 0
                    zoneIsFaultType[14] = 0

                    generateReportMsg(Z14, 'system_fault_condition_restored')                                                


    elif muxSelection == 2:

                                  
        if mux_1 == 1:
            if mux1_x2 != 1:   # state-change: only act on transition
                mux1_x2 = 1
                if zoneSettings[3] == 1:
                    writeLogToDatabase(Z2,'ZONE_2_ACTIVE')
                    zoneIsActive[2] = 1
                    zoneIsActiveType[2] = Z2

                    if zoneSettings[4] == 1:
                        zoneFaultBuzzerOn = 1
                        
                    generateReportMsg(Z2, 'system_activate')
        else:
            if mux1_x2 != 0:   # state-change: only act on transition
                mux1_x2 = 0
                if zoneSettings[3] == 1:                
                    writeLogToDatabase(Z2,'ZONE_2_DEACTIVE')
                    zoneIsActive[2] = 0
                    zoneIsActiveType[2] = 0
                    
                    generateReportMsg(Z2, 'system_activation_restored')                
               

        if mux_2 == 1:
            if mux2_x2 != 1:   # state-change: only act on transition
                mux2_x2 = 1
                if powerZoneSettings[0] == 1:
                    writeLogToDatabase(PZ1,'ZONE_1_POWER_OFF')
                    zoneIsPowerOff[1] = 1
                    powerZoneIsActiveType[1] = PZ1

                    if powerZoneSettings[1] == 1:
                        zoneFaultBuzzerOn = 1                    

                    generateReportMsg(PZ1, 'alarm_system_off')                                                
                    hb_manager and hb_manager.send_offline_heartbeat(PZ1)  # HB-03: immediate offline heartbeat

                    
        else:

            if mux2_x2 != 0:   # state-change: only act on transition
                mux2_x2 = 0
                if powerZoneSettings[0] == 1:
                    writeLogToDatabase(PZ1,'ZONE_1_POWER_ON')
                    zoneIsPowerOff[1] = 0
                    powerZoneIsActiveType[1] = 0

                    generateReportMsg(PZ1, 'alarm_system_on')                                                
                    hb_manager and hb_manager.send_online_heartbeat(PZ1)  # HB-04: immediate online heartbeat
                

        if mux_3 == 1:
            if mux3_x2 != 1:   # state-change: only act on transition
                mux3_x2 = 1
                if zoneSettings[42] == 1:
                    writeLogToDatabase('CCTV','ZONE_15_CAM_TAMPER')
                    zoneIsCamTamper[15] = 1

                    if zoneSettings[43] == 1:
                        zoneFaultBuzzerOn = 1

                    generateReportMsg('CCTV', 'tamper')                                                                        
                    
        else:
            if mux3_x2 != 0:   # state-change: only act on transition
                mux3_x2 = 0
                if zoneSettings[42] == 1:                
                    writeLogToDatabase('CCTV','ZONE_15_CAM_TAMPER_RESTORE')
                    zoneIsCamTamper[15] = 0

                    generateReportMsg('CCTV', 'tamper_restored')                                                                        

            
            
    elif muxSelection == 3:

        if mux_1 == 1:
            if mux1_x3 != 1:   # state-change: only act on transition
                mux1_x3 = 1
                if zoneSettings[3] == 1:
                    writeLogToDatabase(Z2,'ZONE_2_FAULT')
                    zoneIsFault[2] = 1
                    zoneIsFaultType[2] = Z2

                    if zoneSettings[4] == 1:
                        zoneFaultBuzzerOn = 1

                    generateReportMsg(Z2, 'alarm_system_fault')                                                                        
                    
        else:                
            if mux1_x3 != 0:   # state-change: only act on transition
                mux1_x3 = 0
                if zoneSettings[3] == 1:
                    writeLogToDatabase(Z2,'ZONE_2_RESTORE')
                    zoneIsFault[2] = 0
                    zoneIsFaultType[2] = Z2


                    generateReportMsg(Z2, 'system_fault_condition_restored')
                    

        if mux_2 == 1:
            if mux2_x3 != 1:   # state-change: only act on transition
                mux2_x3 = 1              
                if powerZoneSettings[3] == 1:
                    writeLogToDatabase(PZ2,'ZONE_2_POWER_OFF')
                    zoneIsPowerOff[2] = 1
                    powerZoneIsActiveType[2] = PZ2
                    
                    if powerZoneSettings[4] == 1:
                        zoneFaultBuzzerOn = 1

                    generateReportMsg(PZ2, 'alarm_system_off')
                    hb_manager and hb_manager.send_offline_heartbeat(PZ2)  # HB-03: immediate offline heartbeat

                    
        else:

            if mux2_x3 != 0:   # state-change: only act on transition
                mux2_x3 = 0
                if powerZoneSettings[3] == 1:                
                    writeLogToDatabase(PZ2,'ZONE_2_POWER_ON')
                    zoneIsPowerOff[2] = 0
                    powerZoneIsActiveType[2] = PZ2

                    generateReportMsg(PZ2, 'alarm_system_on')
                    hb_manager and hb_manager.send_online_heartbeat(PZ2)  # HB-04: immediate online heartbeat

                

        if mux_3 == 1:
            if mux3_x3 != 1:   # state-change: only act on transition
                mux3_x3 = 1
                if zoneSettings[42] == 1:
                    writeLogToDatabase('CCTV','ZONE_15_CAM_DISCONNECTED')
                    zoneIsCamDisconnected[15] = 1

                    if zoneSettings[43] == 1:
                        zoneFaultBuzzerOn = 1

                    generateReportMsg('CCTV', 'camera_disconnect')
                    
        else:
            if mux3_x3 != 0:   # state-change: only act on transition
                mux3_x3 = 0
                if zoneSettings[42] == 1:                
                    writeLogToDatabase('CCTV','ZONE_15_CAM_CONNECTETION_ESTABLISHED')
                    zoneIsCamDisconnected[15] = 0

                    generateReportMsg('CCTV', 'connection_established')


    elif muxSelection == 4:

        if mux_1 == 1:
            if mux1_x4 != 1:   # state-change: only act on transition
                mux1_x4 = 1            
                if zoneSettings[6] == 1:
                    writeLogToDatabase(Z3,'ZONE_3_ACTIVE')
                    zoneIsActive[3] = 1
                    zoneIsActiveType[3] = Z3

                    if zoneSettings[7] == 1:
                        zoneFaultBuzzerOn = 1
                        
                    generateReportMsg(Z3, 'system_activate')
                    
        else:
            if mux1_x4 != 0:   # state-change: only act on transition
                mux1_x4 = 0
                if zoneSettings[6] == 1:                
                    writeLogToDatabase(Z3,'ZONE_3_DEACTIVE')
                    zoneIsActive[3] = 0
                    zoneIsActiveType[3] = 0
                    
                    generateReportMsg(Z3, 'system_activation_restored')                


        if mux_2 == 1:

            if mux2_x4 != 1:   # state-change: only act on transition
                mux2_x4 = 1              
                if powerZoneSettings[6] == 1:
                    writeLogToDatabase(PZ3,'ZONE_3_POWER_OFF')
                    zoneIsPowerOff[3] = 1
                    powerZoneIsActiveType[3] = PZ3

                    if powerZoneSettings[7] == 1:
                        zoneFaultBuzzerOn = 1

                    generateReportMsg(PZ3, 'alarm_system_off')                    
                    hb_manager and hb_manager.send_offline_heartbeat(PZ3)  # HB-03: immediate offline heartbeat

        else:

            if mux2_x4 != 0:   # state-change: only act on transition
                mux2_x4 = 0
                if powerZoneSettings[6] == 1:
                    writeLogToDatabase(PZ3,'ZONE_3_POWER_ON')
                    zoneIsPowerOff[3] = 0
                    powerZoneIsActiveType[3] = 0

                    generateReportMsg(PZ3, 'alarm_system_on')                                        
                    hb_manager and hb_manager.send_online_heartbeat(PZ3)  # HB-04: immediate online heartbeat


        if mux_3 == 1:
            if mux3_x4 != 1:   # state-change: only act on transition
                mux3_x4 = 1              
                if zoneSettings[42] == 1:                
                    writeLogToDatabase('CCTV','ZONE_15_HDD_ERROR')
                    zoneIsHDDError[15] = 1

                    if zoneSettings[43] == 1:
                        zoneFaultBuzzerOn = 1

                    generateReportMsg('CCTV', 'hdd_error')                    
                    
        else:
            if mux3_x4 != 0:   # state-change: only act on transition
                mux3_x4 = 0
                if zoneSettings[42] == 1:                                
                    writeLogToDatabase('CCTV','ZONE_15_HDD_ERROR_RESTORE')
                    zoneIsHDDError[15] = 0

                    generateReportMsg('CCTV', 'error_restored')
             


    elif muxSelection == 5:

        if mux_1 == 1:
            if mux1_x5 != 1:   # state-change: only act on transition
                mux1_x5 = 1              
                if zoneSettings[6] == 1:
                    writeLogToDatabase(Z3,'ZONE_3_FAULT')
                    zoneIsFault[3] = 1
                    zoneIsFaultType[3] = Z3
                    
                    if zoneSettings[7] == 1:
                        zoneFaultBuzzerOn = 1

                    generateReportMsg(Z3, 'alarm_system_fault')                    
                    
        else:                
            if mux1_x5 != 0:   # state-change: only act on transition
                mux1_x5 = 0
                if zoneSettings[6] == 1:                
                    writeLogToDatabase(Z3,'ZONE_3_RESTORE')
                    zoneIsFault[3] = 0
                    zoneIsFaultType[3] = Z3


                    generateReportMsg(Z3, 'system_fault_condition_restored')                    
                    

        if mux_2 == 1:
            if mux2_x5 != 1:   # state-change: only act on transition
                mux2_x5 = 1             
                if powerZoneSettings[9] == 1:                
                    writeLogToDatabase(PZ4,'ZONE_4_POWER_OFF')
                    zoneIsPowerOff[4] = 1
                    powerZoneIsActiveType[4] = PZ4

                    if powerZoneSettings[10] == 1:
                        zoneFaultBuzzerOn = 1

                    generateReportMsg(PZ4, 'alarm_system_off')                    
                    hb_manager and hb_manager.send_offline_heartbeat(PZ4)  # HB-03: immediate offline heartbeat

        else:

            if mux2_x5 != 0:   # state-change: only act on transition
                mux2_x5 = 0
                if powerZoneSettings[9] == 1:                                
                    writeLogToDatabase(PZ4,'ZONE_4_POWER_ON')
                    zoneIsPowerOff[4] = 0
                    powerZoneIsActiveType[4] = 0

                    generateReportMsg(PZ4, 'alarm_system_on')                    
                    hb_manager and hb_manager.send_online_heartbeat(PZ4)  # HB-04: immediate online heartbeat


        if mux_3 == 1:
            if mux3_x5 != 1:   # state-change: only act on transition
                mux3_x5 = 1               
                if zoneSettings[45] == 1:                
                    writeLogToDatabase('CCTV','ZONE_16_CAM_TAMPER')
                    zoneIsCamTamper[16] = 1

                    if zoneSettings[46] == 1:
                        zoneFaultBuzzerOn = 1

                    generateReportMsg('CCTV', 'tamper')                                                                
                    
        else:
            if mux3_x5 != 0:   # state-change: only act on transition
                mux3_x5 = 0
                if zoneSettings[45] == 1:                                
                    writeLogToDatabase('CCTV','ZONE_16_CAM_TAMPER_RESTORE')
                    zoneIsCamTamper[16] = 0

                    generateReportMsg('CCTV', 'tamper_restored')                    
        

    elif muxSelection == 6:
        if mux_1 == 1:
            if mux1_x6 != 1:   # state-change: only act on transition
                mux1_x6 = 1             
                if zoneSettings[9] == 1:
                    writeLogToDatabase(Z4,'ZONE_4_ACTIVE')
                    zoneIsActive[4] = 1
                    zoneIsActiveType[4] = Z4

                    if zoneSettings[10] == 1:
                        zoneFaultBuzzerOn = 1
                        
                    generateReportMsg(Z4, 'system_activate')
        else:
            if mux1_x6 != 0:   # state-change: only act on transition
                mux1_x6 = 0
                if zoneSettings[9] == 1:                
                    writeLogToDatabase(Z4,'ZONE_4_DEACTIVE')
                    zoneIsActive[4] = 0
                    zoneIsActiveType[4] = 0
                    
                    generateReportMsg(Z4, 'system_activation_restored')                            


        if mux_2 == 1:
            if mux2_x6 != 1:   # state-change: only act on transition
                mux2_x6 = 1               
                if zoneSettings[24] == 1:
                    writeLogToDatabase(Z9,'ZONE_9_ACTIVE')
                    zoneIsActive[9] = 1
                    zoneIsActiveType[9] = Z9
                    if zoneSettings[25] == 1:
                        zoneFaultBuzzerOn = 1
                    generateReportMsg(Z9, 'system_activate')
                        
        else:
            if mux2_x6 != 0:   # state-change: only act on transition
                mux2_x6 = 0
                if zoneSettings[24] == 1:
                    writeLogToDatabase(Z9,'ZONE_9_DEACTIVE')
                    zoneIsActive[9] = 0
                    zoneIsActiveType[9] = 0
                    
                    generateReportMsg(Z9, 'system_activation_restored')                


        if mux_3 == 1:
            if mux3_x6 != 1:   # state-change: only act on transition
                mux3_x6 = 1
                if zoneSettings[45] == 1:                                
                    writeLogToDatabase('CCTV','ZONE_16_CAM_DISCONNECTED')
                    zoneIsCamDisconnected[16] = 1
                    if zoneSettings[46] == 1:
                        zoneFaultBuzzerOn = 1
                        
                        generateReportMsg('CCTV', 'camera_disconnect')                
        else:
            if mux3_x6 != 0:   # state-change: only act on transition
                mux3_x6 = 0
                if zoneSettings[45] == 1:                
                    writeLogToDatabase('CCTV','ZONE_16_CAM_CONNECTION_ESTABLISHED')
                    zoneIsCamDisconnected[16] = 0

                    generateReportMsg('CCTV', 'connection_established')                


    elif muxSelection == 7:
        if mux_1 == 1:
            if mux1_x7 != 1:   # state-change: only act on transition
                mux1_x7 = 1                
                if zoneSettings[9] == 1:                
                    writeLogToDatabase(Z4,'ZONE_4_FAULT')
                    zoneIsFault[4] = 1
                    zoneIsFaultType[4] = Z4
                    if zoneSettings[10] == 1:
                        zoneFaultBuzzerOn = 1

                        generateReportMsg(Z4, 'alarm_system_fault')                                        
        else:                
            if mux1_x7 != 0:   # state-change: only act on transition
                mux1_x7 = 0
                if zoneSettings[9] == 1:                                
                    writeLogToDatabase(Z4,'ZONE_4_RESTORE')
                    zoneIsFault[4] = 0
                    zoneIsFaultType[4] = 0
                    
                    generateReportMsg(Z4, 'system_fault_condition_restored')                                        
                    

        if mux_2 == 1:
            if mux2_x7 != 1:   # state-change: only act on transition
                mux2_x7 = 1                
                if zoneSettings[24] == 1:
                    writeLogToDatabase(Z9,'ZONE_9_FAULT')
                    zoneIsFault[9] = 1
                    zoneIsFaultType[9] = Z9
                    if zoneSettings[25] == 1:
                        zoneFaultBuzzerOn = 1

                        generateReportMsg(Z9, 'alarm_system_fault')                                        
                        
        else:                            
            if mux2_x7 != 0:   # state-change: only act on transition
                mux2_x7 = 0
                if zoneSettings[24] == 1:
                    writeLogToDatabase(Z9,'ZONE_9_RESTORE')
                    zoneIsFault[9] = 0
                    zoneIsFaultType[9] = 0

                    generateReportMsg(Z9, 'system_fault_condition_restored')                                        


        if mux_3 == 1:
            if mux3_x7 != 1:   # state-change: only act on transition
                mux3_x7 = 1               
                if zoneSettings[45] == 1:                
                    writeLogToDatabase('CCTV','ZONE_16_HDD_ERROR')
                    zoneIsHDDError[16] = 1
                    if zoneSettings[46] == 1:
                        zoneFaultBuzzerOn = 1

                        generateReportMsg('CCTV', 'hdd_error')                                        
                        
        else:
            if mux3_x7 != 0:   # state-change: only act on transition
                mux3_x7 = 0
                if zoneSettings[45] == 1:                
                    writeLogToDatabase('CCTV','ZONE_16_HDD_ERROR_RESTORE')
                    zoneIsHDDError[16] = 0

                    generateReportMsg('CCTV', 'error_restored')

        
        if mux_4 == 1:
            if mux4_x7 != 1:   # state-change guard
                mux4_x7 = 1
                writeLogToDatabase('X7','NONE')
            

    elif muxSelection == 8:
        if mux_1 == 1:
            if mux1_x8 != 1:   # state-change: only act on transition
                mux1_x8 = 1                
                if zoneSettings[12] == 1:
                    writeLogToDatabase(Z5,'ZONE_5_ACTIVE')
                    zoneIsActive[5] = 1
                    zoneIsActiveType[5] = Z5
                    if zoneSettings[13] == 1:
                        zoneFaultBuzzerOn = 1
                    generateReportMsg(Z5, 'system_activate')                        
        else:
            if mux1_x8 != 0:   # state-change: only act on transition
                mux1_x8 = 0
                if zoneSettings[12] == 1:
                    writeLogToDatabase(Z5,'ZONE_5_DEACTIVE')
                    zoneIsActive[5] = 0
                    zoneIsActiveType[5] = 0
                    
                    generateReportMsg(Z5, 'system_activation_restored')                

                
        if mux_2 == 1:
            if mux2_x8 != 1:   # state-change: only act on transition
                mux2_x8 = 1                
                if zoneSettings[27] == 1:
                    writeLogToDatabase(Z10,'ZONE_10_ACTIVE')
                    zoneIsActive[10] = 1
                    zoneIsActiveType[10] = Z10
                    if zoneSettings[28] == 1:
                        zoneFaultBuzzerOn = 1
                    generateReportMsg(Z10, 'system_activate')
                        
        else:
            if mux2_x8 != 0:   # state-change: only act on transition
                mux2_x8 = 0
                if zoneSettings[27] == 1:
                    writeLogToDatabase(Z10,'ZONE_10_DEACTIVE')
                    zoneIsActive[10] = 0
                    zoneIsActiveType[10] = 0
                    
                    generateReportMsg(Z10, 'system_activation_restored')                
                

        if mux_3 == 1:
            if mux3_x8 != 1:   # state-change: only act on transition
                mux3_x8 = 1
                if powerZoneSettings[12] == 1:                
                    writeLogToDatabase(PZ5,'ZONE_5_POWER_OFF')
                    zoneIsPowerOff[5] = 1
                    powerZoneIsActiveType[5] = PZ5
                    if powerZoneSettings[13] == 1:
                        zoneFaultBuzzerOn = 1

                    generateReportMsg(PZ5, 'alarm_system_off')
                    hb_manager and hb_manager.send_offline_heartbeat(PZ5)  # HB-03: immediate offline heartbeat

        else:

            if mux3_x8 != 0:   # state-change: only act on transition
                mux3_x8 = 0
                if powerZoneSettings[12] == 1:                
                    writeLogToDatabase(PZ5,'ZONE_5_POWER_ON')
                    zoneIsPowerOff[5] = 0
                    powerZoneIsActiveType[5] = 0

                    generateReportMsg(PZ5, 'alarm_system_on')                                                                                    
                    hb_manager and hb_manager.send_online_heartbeat(PZ5)  # HB-04: immediate online heartbeat

        if mux_4 == 1:
            if mux4_x8 != 1:   # state-change guard
                mux4_x8 = 1
                writeLogToDatabase('X8','NONE')


    elif muxSelection == 9:
        if mux_1 == 1:
            if mux1_x9 != 1:   # state-change: only act on transition
                mux1_x9 = 1               
                if zoneSettings[12] == 1:
                    writeLogToDatabase(Z5,'ZONE_5_FAULT')
                    zoneIsFault[5] = 1
                    zoneIsFaultType[5] = Z5
                    if zoneSettings[13] == 1:
                        zoneFaultBuzzerOn = 1                    

                    generateReportMsg(Z5, 'alarm_system_fault')                                                                                    

        else:                
            if mux1_x9 != 0:   # state-change: only act on transition
                mux1_x9 = 0
                if zoneSettings[12] == 1:
                    writeLogToDatabase(Z5,'ZONE_5_RESTORE')
                    zoneIsFault[5] = 0
                    zoneIsFaultType[5] = 0

                    generateReportMsg(Z5, 'system_fault_condition_restored')                                                                                    
                    

        if mux_2 == 1:
            if mux2_x9 != 1:   # state-change: only act on transition
                mux2_x9 = 1                
                if zoneSettings[27] == 1:
                    writeLogToDatabase(Z10,'ZONE_10_FAULT')
                    zoneIsFault[10] = 1
                    zoneIsFaultType[10] = Z10
                    if zoneSettings[28] == 1:
                        zoneFaultBuzzerOn = 1

                    generateReportMsg(Z10, 'alarm_system_fault')                                                                                    
                        
        else:                
            if mux2_x9 != 0:   # state-change: only act on transition
                mux2_x9 = 0
                if zoneSettings[27] == 1:
                    writeLogToDatabase(Z10,'ZONE_10_RESTORE')
                    zoneIsFault[10] = 0

                    generateReportMsg(Z10, 'system_fault_condition_restored')                                                                                    
        


        if mux_3 == 1:
            if mux3_x9 != 1:   # state-change: only act on transition
                mux3_x9 = 1               
                if powerZoneSettings[15] == 1:
                    writeLogToDatabase(PZ6,'ZONE_6_POWER_OFF')
                    zoneIsPowerOff[6] = 1
                    powerZoneIsActiveType[6] = PZ6

                    if powerZoneSettings[16] == 1:
                        zoneFaultBuzzerOn = 1

                    generateReportMsg(PZ6, 'alarm_system_off')
                    hb_manager and hb_manager.send_offline_heartbeat(PZ6)  # HB-03: immediate offline heartbeat

                        
        else:

            if mux3_x9 != 0:   # state-change: only act on transition
                mux3_x9 = 0
                if powerZoneSettings[15] == 1:
                    writeLogToDatabase(PZ6,'ZONE_6_POWER_ON')
                    zoneIsPowerOff[6] = 0
                    powerZoneIsActiveType[6] = 0

                    generateReportMsg(PZ6, 'alarm_system_on')                                                                                    
                    hb_manager and hb_manager.send_online_heartbeat(PZ6)  # HB-04: immediate online heartbeat

                    
        if mux_4 == 1:
            if mux4_x9 != 1:   # state-change: only act on transition
                mux4_x9 = 1               
                writeLogToDatabase('X9','NONE')                        

    elif muxSelection == 10:
        if mux_1 == 1:
            if mux1_x10 != 1:   # state-change: only act on transition
                mux1_x10 = 1              
                if zoneSettings[15] == 1:
                    writeLogToDatabase(Z6,'ZONE_6_ACTIVE')
                    zoneIsActive[6] = 1
                    zoneIsActiveType[6] = Z6
                    if zoneSettings[16] == 1:
                        zoneFaultBuzzerOn = 1
                        
                    generateReportMsg(Z6, 'system_activate')
                        
        else:
            if mux1_x10 != 0:   # state-change: only act on transition
                mux1_x10 = 0
                if zoneSettings[15] == 1:
                    writeLogToDatabase(Z6,'ZONE_6_DEACTIVE')
                    zoneIsActive[6] = 0
                    zoneIsActiveType[6] = 0
                    
                    generateReportMsg(Z6, 'system_activation_restored')                
            

        if mux_2 == 1:
            if mux2_x10 != 1:   # state-change: only act on transition
                mux2_x10 = 1               
                if zoneSettings[30] == 1:
                    writeLogToDatabase(Z11,'ZONE_11_ACTIVE')
                    zoneIsActive[11] = 1
                    zoneIsActiveType[11] = Z11
                    if zoneSettings[31] == 1:
                        zoneFaultBuzzerOn = 1
                        
                    generateReportMsg(Z11, 'system_activate')                                    
        else:                
            if mux2_x10 != 0:   # state-change: only act on transition
                mux2_x10 = 0
                if zoneSettings[30] == 1:
                    writeLogToDatabase(Z11,'ZONE_11_DEACTIVE')
                    zoneIsActive[11] = 0
                    zoneIsActiveType[11] = 0

                    generateReportMsg(Z11, 'system_activation_restored')                        


        if mux_3 == 1:
            if mux3_x10 != 1:   # state-change: only act on transition
                mux3_x10 = 1               
                if powerZoneSettings[18] == 1:
                    writeLogToDatabase(PZ7,'ZONE_7_POWER_OFF')
                    zoneIsPowerOff[7] = 1
                    powerZoneIsActiveType[7] = PZ7
                    if powerZoneSettings[19] == 1:
                        zoneFaultBuzzerOn = 1                                                                                

                    generateReportMsg(PZ7, 'alarm_system_off')
                    hb_manager and hb_manager.send_offline_heartbeat(PZ7)  # HB-03: immediate offline heartbeat

        else:

            if mux3_x10 != 0:   # state-change: only act on transition
                mux3_x10 = 0
                if powerZoneSettings[18] == 1:
                    writeLogToDatabase(PZ7,'ZONE_7_POWER_ON')
                    zoneIsPowerOff[7] = 0
                    powerZoneIsActiveType[7] = 0

                    generateReportMsg(PZ7, 'alarm_system_on')                                                                                                        
                    hb_manager and hb_manager.send_online_heartbeat(PZ7)  # HB-04: immediate online heartbeat

                    
        if mux_4 == 1:
            if mux4_x10 != 1:   # state-change: only act on transition
                mux4_x10 = 1               
                writeLogToDatabase('X10','NONE')                        

    elif muxSelection == 11:
        if mux_1 == 1:
            if mux1_x11 != 1:   # state-change: only act on transition
                mux1_x11 = 1               
                if zoneSettings[15] == 1:
                    writeLogToDatabase(Z6,'ZONE_6_FAULT')
                    zoneIsFault[6] = 1
                    zoneIsFaultType[6] = Z6
                    if zoneSettings[16] == 1:
                        zoneFaultBuzzerOn = 1                                                                                

                    generateReportMsg(Z6, 'alarm_system_fault')                                                                                                        
                    
        else:                
            if mux1_x11 != 0:   # state-change: only act on transition
                mux1_x11 = 0
                if zoneSettings[15] == 1:
                    writeLogToDatabase(Z6,'ZONE_6_RESTORE')
                    zoneIsFault[6] = 0
                    zoneIsFaultType[6] = 0

                    generateReportMsg(Z6, 'system_fault_condition_restored')                                                                                                        
                    

        if mux_2 == 1:
            if mux2_x11 != 1:   # state-change: only act on transition
                mux2_x11 = 1                
                if zoneSettings[30] == 1:
                    writeLogToDatabase(Z11,'ZONE_11_FAULT')
                    zoneIsFault[11] = 1
                    zoneIsFaultType[11] = Z11
                    if zoneSettings[31] == 1:
                        zoneFaultBuzzerOn = 1                                                                                

                    generateReportMsg(Z11, 'alarm_system_fault')                                                                                                        
                    
        else:                
            if mux2_x11 != 0:   # state-change: only act on transition
                mux2_x11 = 0
                if zoneSettings[30] == 1:                
                    writeLogToDatabase(Z11,'ZONE_11_RESTORE')
                    zoneIsFault[11] = 0
                    zoneIsFaultType[11] = 0

                    generateReportMsg(Z11, 'system_fault_condition_restored')                                                                                                        
                    


        if mux_3 == 1:
            if mux3_x11 != 1:   # state-change: only act on transition
                mux3_x11 = 1               
                if powerZoneSettings[21] == 1:
                    writeLogToDatabase(PZ8,'ZONE_8_POWER_OFF')
                    zoneIsPowerOff[8] = 1
                    powerZoneIsActiveType[8] = PZ8
                    if powerZoneSettings[22] == 1:
                        zoneFaultBuzzerOn = 1

                    generateReportMsg(PZ8, 'alarm_system_off')
                    hb_manager and hb_manager.send_offline_heartbeat(PZ8)  # HB-03: immediate offline heartbeat

                        
        else:

            if mux3_x11 != 0:   # state-change: only act on transition
                mux3_x11 = 0
                if powerZoneSettings[21] == 1:                
                    writeLogToDatabase(PZ8,'ZONE_8_POWER_ON')
                    zoneIsPowerOff[8] = 0
                    powerZoneIsActiveType[8] = 0

                    generateReportMsg(PZ8, 'alarm_system_on')
                    hb_manager and hb_manager.send_online_heartbeat(PZ8)  # HB-04: immediate online heartbeat

        
        if mux_4 == 1:
            if mux4_x11 != 1:   # state-change: only act on transition
                mux4_x11 = 1                
                writeLogToDatabase('X11','NONE')                        

    elif muxSelection == 12:
        
        if mux_1 == 1:
            if mux1_x12 != 1:   # state-change: only act on transition
                mux1_x12 = 1               
                if zoneSettings[18] == 1:                
                    writeLogToDatabase('CCTV','ZONE_7_CAM_TAMPER')
                    zoneIsCamTamper[7] = 1
                    if zoneSettings[19] == 1:
                        zoneFaultBuzzerOn = 1

                    generateReportMsg('CCTV', 'tamper')                                                                                                                                                
                        
        else:
            if mux1_x12 != 0:   # state-change: only act on transition
                mux1_x12 = 0
                if zoneSettings[18] == 1:                                
                    writeLogToDatabase('CCTV','ZONE_7_CAM_TAMPER_RESTORE')
                    zoneIsCamTamper[7] = 0

                    generateReportMsg('CCTV', 'tamper_restored')                                                                                                                            
            


        if mux_2 == 1:
            if mux2_x12 != 1:   # state-change: only act on transition
                mux2_x12 = 1               
                if zoneSettings[33] == 1:                                                
                    writeLogToDatabase(Z12,'ZONE_12_ACTIVE')
                    zoneIsActive[12] = 1
                    zoneIsActiveType[12] = Z12
                    if zoneSettings[34] == 1:
                        zoneFaultBuzzerOn = 1
                        
                    generateReportMsg(Z12, 'system_activate')
                        
        else:                
            if mux2_x12 != 0:   # state-change: only act on transition
                mux2_x12 = 0
                if zoneSettings[33] == 1:                                                                
                    writeLogToDatabase(Z12,'ZONE_12_DEACTIVE')
                    zoneIsActive[12] = 0
                    zoneIsActiveType[12] = 0

                    generateReportMsg(Z12, 'system_activation_restored')                                



        global systemPowerOffShutDownMode
        if mux_3 == 1:
            if mux3_x12 != 1:   # state-change: only act on transition
                mux3_x12 = 1                
                writeLogToDatabase('SYSTEM','SYSTEM_POWER_OFF')
                systemPowerOffShutDownMode = 1
        else:
            if mux3_x12 != 0:   # state-change: only act on transition
                mux3_x12 = 0
                writeLogToDatabase('SYSTEM','SYSTEM_POWER_ON')
                systemPowerOffShutDownMode = 0

        
        if mux_4 == 1:
            if mux4_x12 != 1:   # state-change: only act on transition
                mux4_x12 = 1                
                writeLogToDatabase('X12','NONE')                        

    elif muxSelection == 13:
        if mux_1 == 1:
            if mux1_x13 != 1:   # state-change: only act on transition
                mux1_x13 = 1                
                if zoneSettings[18] == 1:                                                                
                    writeLogToDatabase('CCTV','ZONE_7_CAM_DISCONNECTED')
                    zoneIsCamDisconnected[7] = 1
                    if zoneSettings[19] == 1:
                        zoneFaultBuzzerOn = 1
                        
                    generateReportMsg('CCTV', 'camera_disconnect')                                                                                                                            
                    
        else:
            if mux1_x13 != 0:   # state-change: only act on transition
                mux1_x13 = 0
                if zoneSettings[18] == 1:                                                                                
                    writeLogToDatabase('CCTV','ZONE_7_CAM_CONNECTION_ESTABLISHED')
                    zoneIsCamDisconnected[7] = 0

                    generateReportMsg('CCTV', 'connection_established')                                                                                                                                                               


        if mux_2 == 1:
            if mux2_x13 != 1:   # state-change: only act on transition
                mux2_x13 = 1               
                if zoneSettings[33] == 1:                                                                
                    writeLogToDatabase(Z12,'ZONE_12_FAULT')
                    zoneIsFault[12] = 1
                    zoneIsFaultType[12] = Z12
                    if zoneSettings[34] == 1:
                        zoneFaultBuzzerOn = 1

                    generateReportMsg(Z12, 'alarm_system_fault')                                                                                                                            
                                                            
        else:                
            if mux2_x13 != 0:   # state-change: only act on transition
                mux2_x13 = 0
                if zoneSettings[33] == 1:                                                                                
                    writeLogToDatabase(Z12,'ZONE_12_RESTORE')
                    zoneIsFault[12] = 0
                    zoneIsFaultType[12] = Z12

                    generateReportMsg(Z12, 'system_fault_condition_restored')                                                                                                                                             


        global mainSense
        global statusbox_mains_on
        global statusbox_battery_on
                
        if mux_3 == 1:
            if mux3_x13 != 1:   # state-change: only act on transition
                mux3_x13 = 1
                mainSense = 1
                statusbox_mains_on = "false"
                statusbox_battery_on = "true"
                
                sendData2TB("battery_on")                
        else:
            if mux3_x13 != 0:   # state-change: only act on transition
                mux3_x13 = 0
                mainSense = 0
                statusbox_mains_on = "true"
                statusbox_battery_on = "false"
                
                sendData2TB("mains_on")
                
        if mux_4 == 1:
            if mux4_x13 != 1:   # state-change: only act on transition
                mux4_x13 = 1                
                writeLogToDatabase('X13','NONE')
                                                                                                    

    elif muxSelection == 14:
        if mux_1 == 1:
            if mux1_x14 != 1:   # state-change: only act on transition
                mux1_x14 = 1
                #mux1_x14 = 1                
                if zoneSettings[18] == 1:                                                                
                    writeLogToDatabase('CCTV','ZONE_7_HDD_ERROR')
                    zoneIsHDDError[7] = 1
                    if zoneSettings[19] == 1:
                        zoneFaultBuzzerOn = 1
                        
                    generateReportMsg('CCTV', 'hdd_error')
                   
                        
        else:
            if mux1_x14 != 0:   # state-change: only act on transition
                mux1_x14 = 0
                if zoneSettings[18] == 1:                                                                                
                    writeLogToDatabase('CCTV','ZONE_7_HDD_ERROR_RESTORE')
                    zoneIsHDDError[7] = 0

                    generateReportMsg('CCTV', 'error_restored')                                       
                    
        
        if mux_2 == 1:
            if mux2_x14 != 1:   # state-change: only act on transition
                mux2_x14 = 1               
                if zoneSettings[36] == 1:                                                                                
                    writeLogToDatabase(Z13,'ZONE_13_ACTIVE')
                    zoneIsActive[13] = 1
                    zoneIsActiveType[13] = Z13
                    if zoneSettings[37] == 1:
                        zoneFaultBuzzerOn = 1
                        
                    generateReportMsg(Z13, 'system_activate')
                                                           
                        
        else:                
            if mux2_x14 != 0:   # state-change: only act on transition
                mux2_x14 = 0
                if zoneSettings[36] == 1:                                                                                                
                    writeLogToDatabase(Z13,'ZONE_13_DEACTIVE')
                    zoneIsActive[13] = 0
                    zoneIsActiveType[13] = 0
                    
                    generateReportMsg(Z13, 'system_activation_restored')                                
                                                           

        global statusbox_battery_reverse

        if mux_3 == 1:
            if mux3_x14 != 1:   # state-change: only act on transition
                mux3_x14 = 1                
                statusbox_battery_reverse = "false"                
                print(statusbox_battery_reverse)
                
        else:
            if mux3_x14 != 0:   # state-change: only act on transition
                mux3_x14 = 0
                statusbox_battery_reverse = "true"
                print(statusbox_battery_reverse)
                sendData2TB("battery_reverse")
                # BATT-FIX-1: send system status immediately on battery_reverse
                sendData2TBSystemStatus("true", "true", statusbox_mains_on, statusbox_battery_reverse, statusbox_battery_low, statusbox_sos_status, statusbox_network, statusbox_no_of_connected_device)

        if mux_4 == 1:
            if mux4_x14 != 1:   # state-change: only act on transition
                mux4_x14 = 1               
                writeLogToDatabase('X14','NONE')
                                                                            

    elif muxSelection == 15:

        if mux_1 == 1:
            if mux1_x15 != 1:   # state-change: only act on transition
                mux1_x15 = 1                
                if zoneSettings[21] == 1:                                                                                                
                    writeLogToDatabase('CCTV','ZONE_8_CAM_TAMPER')
                    zoneIsCamTamper[8] = 1
                    if zoneSettings[22] == 1:
                        zoneFaultBuzzerOn = 1

                    generateReportMsg('CCTV', 'tamper')
                    
        else:
            if mux1_x15 != 0:   # state-change: only act on transition
                mux1_x15 = 0
                if zoneSettings[21] == 1:                                                                                                                
                    writeLogToDatabase('CCTV','ZONE_8_CAM_TAMPER_RESTORE')
                    zoneIsCamTamper[8] = 0
                    
                    generateReportMsg('CCTV', 'tamper_restored')
                    

        if mux_2 == 1:
            if mux2_x15 != 1:   # state-change: only act on transition
                mux2_x15 = 1                
                if zoneSettings[36] == 1:                                                                                                                
                    writeLogToDatabase(Z13,'ZONE_13_FAULT')
                    zoneIsFault[13] = 1
                    zoneIsFaultType[13] = Z13
                    if zoneSettings[37] == 1:
                        zoneFaultBuzzerOn = 1

                    generateReportMsg(Z13, 'alarm_system_fault')
                                           
        else:                
            if mux2_x15 != 0:   # state-change: only act on transition
                mux2_x15 = 0
                if zoneSettings[36] == 1:                                                                                                                                
                    writeLogToDatabase(Z13,'ZONE_13_RESTORE')
                    zoneIsFault[13] = 0
                    zoneIsFaultType[13] = Z13

                    generateReportMsg(Z13, 'system_fault_condition_restored')                           
        
        if mux_3 == 1:
            if mux3_x15 != 1:   # state-change: only act on transition
                mux3_x15 = 1               
                writeLogToDatabase('X15','NONE')
                                           
        if mux_4 == 1:
            if mux4_x15 != 1:   # state-change: only act on transition
                mux4_x15 = 1
                writeLogToDatabase('X15','NONE')                           



def muxSelectionZone1( value = 0, muxChSelection = 0b0000000 ):

    global BYPASS_KEY
    global TAMPER
    global MAINLOCK
    global DURESS_REMOTE

    global fieldInputStatusLED1
    global fieldInputStatusLED2
    global zoneCounter
    global muxSelection
    
    mux_1 = 0
    mux_2 = 0
    mux_3 = 0
    mux_4 = 0

    mux_1 = GPIO.input(TAMPER)
    mux_2 = GPIO.input(BYPASS_KEY)
    mux_3 = GPIO.input(MAINLOCK)
    mux_4 = GPIO.input(DURESS_REMOTE)


    fieldInputStatusLED1 = 0b00000000
    
    if mux_1 == 1:
        fieldInputStatusLED1 = fieldInputStatusLED1 | 0b00000001
    if mux_2 == 1:        
        fieldInputStatusLED1 = fieldInputStatusLED1 | 0b00000010
    if mux_3 == 1:        
        fieldInputStatusLED1 = fieldInputStatusLED1 | 0b00000100
    if mux_4 == 1:
        fieldInputStatusLED1 = fieldInputStatusLED1 | 0b00001000


    global mux1_x0
    global mux1_x1
    global mux1_x2
    global mux1_x3
    global mux1_x4
    global mux1_x5
    global mux1_x6
    global mux1_x7
    global mux1_x8
    global mux1_x9
    global mux1_x10
    global mux1_x11
    global mux1_x12
    global mux1_x13
    global mux1_x14
    global mux1_x15

    global mux2_x0
    global mux2_x1
    global mux2_x2
    global mux2_x3
    global mux2_x4
    global mux2_x5
    global mux2_x6
    global mux2_x7
    global mux2_x8
    global mux2_x9
    global mux2_x10
    global mux2_x11
    global mux2_x12
    global mux2_x13
    global mux2_x14
    global mux2_x15

    global mux3_x0
    global mux3_x1
    global mux3_x2
    global mux3_x3
    global mux3_x4
    global mux3_x5
    global mux3_x6
    global mux3_x7
    global mux3_x8
    global mux3_x9
    global mux3_x10
    global mux3_x11
    global mux3_x12
    global mux3_x13
    global mux3_x14
    global mux3_x15
    
    global mux4_x0
    global mux4_x1
    global mux4_x2
    global mux4_x3
    global mux4_x4
    global mux4_x5
    global mux4_x6
    global mux4_x7
    global mux4_x8
    global mux4_x9
    global mux4_x10
    global mux4_x11
    global mux4_x12
    global mux4_x13
    global mux4_x14
    global mux4_x15

    global zoneSettings
    global powerZoneSettings

    global zoneIsCamDisconnected
    global zoneIsFault
    global zoneIsPowerOff
    global zoneIsActive
    global zoneIsHDDError
    global zoneIsFault
    global powerZoneIsActive
    global zoneIsCamTamper

    Z1 = 0
    Z2 = 0
    Z3 = 0
    Z4 = 0
    Z5 = 0
    Z6 = 0
    Z7 = 0
    Z8 = 0
    Z9 = 0
    Z10 = 0
    Z11 = 0
    Z12 = 0
    Z13 = 0
    Z14 = 0
    Z15 = 0
    Z16 = 0

    PZ1 = 0
    PZ2 = 0
    PZ3 = 0
    PZ4 = 0
    PZ5 = 0
    PZ6 = 0
    PZ7 = 0
    PZ8 = 0
    PZ9 = 0
    PZ10 = 0
    PZ11 = 0
    PZ12 = 0
    PZ13 = 0
    PZ14 = 0
    PZ15 = 0
    PZ16 = 0
    
        
    if zoneSettings[2] == 1:
        Z1 = 'BAS'
    elif zoneSettings[2] == 2:
        Z1 = 'FAS'
    elif zoneSettings[2] == 3:
        Z1 = 'TIME_LOCK'
    elif zoneSettings[2] == 4:
        Z1 = 'BACS'
    elif zoneSettings[2] == 6:
        Z1 = 'IAS'

    if zoneSettings[5] == 1:
        Z2 = 'BAS'
    elif zoneSettings[5] == 2:
        Z2 = 'FAS'
    elif zoneSettings[5] == 3:
        Z2 = 'TIME_LOCK'
    elif zoneSettings[5] == 4:
        Z2 = 'BACS'
    elif zoneSettings[5] == 6:
        Z2 = 'IAS'


    if zoneSettings[8] == 1:
        Z3 = 'BAS'
    elif zoneSettings[8] == 2:
        Z3 = 'FAS'
    elif zoneSettings[8] == 3:
        Z3 = 'TIME_LOCK'
    elif zoneSettings[8] == 4:
        Z3 = 'BACS'
    elif zoneSettings[8] == 6:
        Z3 = 'IAS'
    

    if zoneSettings[11] == 1:
        Z4 = 'BAS'
    elif zoneSettings[11] == 2:
        Z4 = 'FAS'
    elif zoneSettings[11] == 3:
        Z4 = 'TIME_LOCK'
    elif zoneSettings[11] == 4:
        Z4 = 'BACS'
    elif zoneSettings[11] == 6:
        Z4 = 'IAS'


    if zoneSettings[14] == 1:
        Z5 = 'BAS'
    elif zoneSettings[14] == 2:
        Z5 = 'FAS'
    elif zoneSettings[14] == 3:
        Z5 = 'TIME_LOCK'
    elif zoneSettings[14] == 4:
        Z5 = 'BACS'
    elif zoneSettings[14] == 6:
        Z5 = 'IAS'


    if zoneSettings[17] == 1:
        Z6 = 'BAS'
    elif zoneSettings[17] == 2:
        Z6 = 'FAS'
    elif zoneSettings[17] == 3:
        Z6 = 'TIME_LOCK'
    elif zoneSettings[17] == 4:
        Z6 = 'BACS'
    elif zoneSettings[17] == 6:
        Z6 = 'IAS'


    if zoneSettings[20] == 1:
        Z7 = 'BAS'
    elif zoneSettings[20] == 2:
        Z7 = 'FAS'
    elif zoneSettings[20] == 3:
        Z7 = 'TIME_LOCK'
    elif zoneSettings[20] == 4:
        Z7 = 'BACS'
    elif zoneSettings[20] == 6:
        Z7 = 'IAS'


    if zoneSettings[23] == 1:
        Z8 = 'BAS'
    elif zoneSettings[23] == 2:
        Z8 = 'FAS'
    elif zoneSettings[23] == 3:
        Z8 = 'TIME_LOCK'
    elif zoneSettings[23] == 4:
        Z8 = 'BACS'
    elif zoneSettings[23] == 6:
        Z8 = 'IAS'


    if zoneSettings[26] == 1:
        Z9 = 'BAS'
    elif zoneSettings[26] == 2:
        Z9 = 'FAS'
    elif zoneSettings[26] == 3:
        Z9 = 'TIME_LOCK'
    elif zoneSettings[26] == 4:
        Z9 = 'BACS'
    elif zoneSettings[26] == 6:
        Z9 = 'IAS'

    if zoneSettings[29] == 1:
        Z10 = 'BAS'
    elif zoneSettings[29] == 2:
        Z10 = 'FAS'
    elif zoneSettings[29] == 3:
        Z10 = 'TIME_LOCK'
    elif zoneSettings[29] == 4:
        Z10 = 'BACS'
    elif zoneSettings[29] == 6:
        Z10 = 'IAS'


    if zoneSettings[32] == 1:
        Z11 = 'BAS'
    elif zoneSettings[32] == 2:
        Z11 = 'FAS'
    elif zoneSettings[32] == 3:
        Z11 = 'TIME_LOCK'
    elif zoneSettings[32] == 4:
        Z11 = 'BACS'
    elif zoneSettings[32] == 6:
        Z11 = 'IAS'


    if zoneSettings[35] == 1:
        Z12 = 'BAS'
    elif zoneSettings[35] == 2:
        Z12 = 'FAS'
    elif zoneSettings[35] == 3:
        Z12 = 'TIME_LOCK'
    elif zoneSettings[35] == 4:
        Z12 = 'BACS'
    elif zoneSettings[35] == 6:
        Z12 = 'IAS'


    if zoneSettings[38] == 1:
        Z13 = 'BAS'
    elif zoneSettings[38] == 2:
        Z13 = 'FAS'
    elif zoneSettings[38] == 3:
        Z13 = 'TIME_LOCK'
    elif zoneSettings[38] == 4:
        Z13 = 'BACS'

    if zoneSettings[41] == 1:
        Z14 = 'BAS'
    elif zoneSettings[41] == 2:
        Z14 = 'FAS'
    elif zoneSettings[41] == 3:
        Z14 = 'TIME_LOCK'
    elif zoneSettings[41] == 4:
        Z14 = 'BACS'
    elif zoneSettings[41] == 6:
        Z14 = 'IAS'


    if powerZoneSettings[2] == 1:
        PZ1 = 'BAS'
    elif powerZoneSettings[2] == 2:
        PZ1 = 'FAS'
    elif powerZoneSettings[2] == 3:
        PZ1 = 'TIME_LOCK'
    elif powerZoneSettings[2] == 4:
        PZ1 = 'BACS'
    elif powerZoneSettings[2] == 5:
        PZ1 = 'CCTV'
    elif powerZoneSettings[2] == 6:
        PZ1 = 'IAS'

    if powerZoneSettings[5] == 1:
        PZ2 = 'BAS'
    elif powerZoneSettings[5] == 2:
        PZ2 = 'FAS'
    elif powerZoneSettings[5] == 3:
        PZ2 = 'TIME_LOCK'
    elif powerZoneSettings[5] == 4:
        PZ2 = 'BACS'
    elif powerZoneSettings[5] == 5:
        PZ2 = 'CCTV'
    elif powerZoneSettings[5] == 6:
        PZ2 = 'IAS'

    if powerZoneSettings[8] == 1:
        PZ3 = 'BAS'
    elif powerZoneSettings[8] == 2:
        PZ3 = 'FAS'
    elif powerZoneSettings[8] == 3:
        PZ3 = 'TIME_LOCK'
    elif powerZoneSettings[8] == 4:
        PZ3 = 'BACS'
    elif powerZoneSettings[8] == 5:
        PZ3 = 'CCTV'
    elif powerZoneSettings[8] == 6:
        PZ3 = 'IAS'

    if powerZoneSettings[11] == 1:
        PZ4 = 'BAS'
    elif powerZoneSettings[11] == 2:
        PZ4 = 'FAS'
    elif powerZoneSettings[11] == 3:
        PZ4 = 'TIME_LOCK'
    elif powerZoneSettings[11] == 4:
        PZ4 = 'BACS'
    elif powerZoneSettings[11] == 5:
        PZ4 = 'CCTV'
    elif powerZoneSettings[11] == 6:
        PZ4 = 'IAS'

    if powerZoneSettings[14] == 1:
        PZ5 = 'BAS'
    elif powerZoneSettings[14] == 2:
        PZ5 = 'FAS'
    elif powerZoneSettings[14] == 3:
        PZ5 = 'TIME_LOCK'
    elif powerZoneSettings[14] == 4:
        PZ5 = 'BACS'
    elif powerZoneSettings[14] == 5:
        PZ5 = 'CCTV'
    elif powerZoneSettings[14] == 6:
        PZ5 = 'IAS'

    if powerZoneSettings[17] == 1:
        PZ6 = 'BAS'
    elif powerZoneSettings[17] == 2:
        PZ6 = 'FAS'
    elif powerZoneSettings[17] == 3:
        PZ6 = 'TIME_LOCK'
    elif powerZoneSettings[17] == 4:
        PZ6 = 'BACS'
    elif powerZoneSettings[17] == 5:
        PZ6 = 'CCTV'
    elif powerZoneSettings[17] == 6:
        PZ6 = 'IAS'

    if powerZoneSettings[20] == 1:
        PZ7 = 'BAS'
    elif powerZoneSettings[20] == 2:
        PZ7 = 'FAS'
    elif powerZoneSettings[20] == 3:
        PZ7 = 'TIME_LOCK'
    elif powerZoneSettings[20] == 4:
        PZ7 = 'BACS'
    elif powerZoneSettings[20] == 5:
        PZ7 = 'CCTV'
    elif powerZoneSettings[20] == 6:
        PZ7 = 'IAS'

    if powerZoneSettings[23] == 1:
        PZ8 = 'BAS'
    elif powerZoneSettings[23] == 2:
        PZ8 = 'FAS'
    elif powerZoneSettings[23] == 3:
        PZ8 = 'TIME_LOCK'
    elif powerZoneSettings[23] == 4:
        PZ8 = 'BACS'
    elif powerZoneSettings[23] == 5:
        PZ8 = 'CCTV'
    elif powerZoneSettings[23] == 6:
        PZ8 = 'IAS'


    global powerZoneSettingsOnCounter 
    powerZoneSettingsOnCounter = 0
    if powerZoneSettings[0] == 1:
        powerZoneSettingsOnCounter = powerZoneSettingsOnCounter + 1
    if powerZoneSettings[3] == 1:
        powerZoneSettingsOnCounter = powerZoneSettingsOnCounter + 1
    if powerZoneSettings[6] == 1:
        powerZoneSettingsOnCounter = powerZoneSettingsOnCounter + 1
    if powerZoneSettings[9] == 1:   
        powerZoneSettingsOnCounter = powerZoneSettingsOnCounter + 1
    if powerZoneSettings[12] == 1:   
        powerZoneSettingsOnCounter = powerZoneSettingsOnCounter + 1
    if powerZoneSettings[15] == 1:    
        powerZoneSettingsOnCounter = powerZoneSettingsOnCounter + 1
    if powerZoneSettings[18] == 1:
        powerZoneSettingsOnCounter = powerZoneSettingsOnCounter + 1
    if powerZoneSettings[21] == 1:                
        powerZoneSettingsOnCounter = powerZoneSettingsOnCounter + 1


    global zoneIsActiveType
    global zoneIsFaultType
    global powerZoneIsActiveType

    global frontPanelLED2
    global shiftRegister3Buffers
    global zoneFaultBuzzerOn


    global powerZoneOnCounter


    if muxSelection == 0:
        
        if mux_1 == 1:
            if mux1_x0 == 0:
                mux1_x0 = 1
                if zoneSettings[0] == 1:
                    writeLogToDatabase(Z1,'ZONE_1_ACTIVE')
                    zoneIsActive[1] = 1
                    zoneIsActiveType[1] = Z1

                    if zoneSettings[1] == 1:
                        zoneFaultBuzzerOn = 1

                    generateReportMsg(Z1, 'system_activate')

        else:
            if mux1_x0 == 1:
                mux1_x0 = 0
                if zoneSettings[0] == 1:
                    writeLogToDatabase(Z1,'ZONE_1_DEACTIVE')
                    zoneIsActive[1] = 0
                    zoneIsActiveType[1] = 0

                    generateReportMsg(Z1, 'system_activation_restored')


        if mux_2 == 1:
            if mux2_x0 == 0:
                mux2_x0 = 1
                if zoneSettings[21] == 1:
                    writeLogToDatabase('CCTV','ZONE_8_CAM_DISCONNECTED')
                    zoneIsCamDisconnected[8] = 1

                    if zoneSettings[22] == 1:
                        zoneFaultBuzzerOn = 1
                        
                    generateReportMsg('CCTV', 'camera_disconnect')
                        
        else:
            if mux2_x0 == 1:
                mux2_x0 = 0
                if zoneSettings[21] == 1:
                    writeLogToDatabase('CCTV','ZONE_8_CAM_CONNECTION_ESTABLISHED')
                    zoneIsCamDisconnected[8] = 0
                    
                    generateReportMsg('CCTV', 'connection_established')
        

        if mux_3 == 1:
            if mux3_x0 == 0:
                mux3_x0 = 1
                if zoneSettings[39] == 1:
                    writeLogToDatabase(Z14,'ZONE_14_ACTIVE')
                    zoneIsActive[14] = 1
                    zoneIsActiveType[14] = Z14

                    if zoneSettings[40] == 1:
                        zoneFaultBuzzerOn = 1
                        
                    generateReportMsg(Z14, 'system_activate')
        else:                
            if mux3_x0 == 1:
                mux3_x0 = 0
                if zoneSettings[39] == 1:
                    writeLogToDatabase(Z14,'ZONE_14_DEACTIVE')
                    zoneIsActive[14] = 0
                    zoneIsActiveType[14] = 0

                    generateReportMsg(Z14, 'system_activation_restored')

            
    elif muxSelection == 1:

        
        if mux_1 == 1:
            if mux1_x1 == 0:
                mux1_x1 = 1
                if zoneSettings[0] == 1:
                    writeLogToDatabase(Z1,'ZONE_1_FAULT')
                    zoneIsFault[1] = 1
                    zoneIsFaultType[1] = Z1

                    if zoneSettings[1] == 1:
                        zoneFaultBuzzerOn = 1

                    generateReportMsg(Z1, 'alarm_system_fault')
                    
        else:
            if mux1_x1 == 1:
                mux1_x1 = 0
                if zoneSettings[0] == 1:
                    writeLogToDatabase(Z1,'ZONE_1_RESTORE')
                    zoneIsFault[1] = 0
                    zoneIsFaultType[1] = 0
                    
                    generateReportMsg(Z1, 'system_fault_condition_restored')
                

        
        if mux_2 == 1:
            if mux2_x1 == 0:
                mux2_x1 = 1
                if zoneSettings[21] == 1:
                    writeLogToDatabase('CCTV','ZONE_8_HDD_ERROR')
                    zoneIsHDDError[8] = 1

                    if zoneSettings[22] == 1:
                        zoneFaultBuzzerOn = 1

                    generateReportMsg('CCTV', 'hdd_error')                        
                    
        else:
            if mux2_x1 == 1:
                mux2_x1 = 0
                if zoneSettings[21] == 1:                
                    writeLogToDatabase('CCTV','ZONE_8_HDD_ERROR_RESTORE')
                    zoneIsHDDError[8] = 0

                    generateReportMsg('CCTV', 'error_restored')                        
                    


        if mux_3 == 1:
            if mux3_x1 == 0:
                mux3_x1 = 1
                if zoneSettings[39] == 1:                
                    writeLogToDatabase(Z14,'ZONE_14_FAULT')
                    zoneIsFault[14] = 1
                    zoneIsFaultType[14] = Z14
                    
                    if zoneSettings[40] == 1:
                        zoneFaultBuzzerOn = 1

                    generateReportMsg(Z14, 'alarm_system_fault')                                                
                    
        else:                
            if mux3_x1 == 1:
                mux3_x1 = 0
                if zoneSettings[39] == 1:                                
                    writeLogToDatabase(Z14,'ZONE_14_RESTORE')
                    zoneIsFault[14] = 0
                    zoneIsFaultType[14] = 0

                    generateReportMsg(Z14, 'system_fault_condition_restored')                                                


    elif muxSelection == 2:

                                  
        if mux_1 == 1:
            if mux1_x2 == 0:
                mux1_x2 = 1
                if zoneSettings[3] == 1:
                    writeLogToDatabase(Z2,'ZONE_2_ACTIVE')
                    zoneIsActive[2] = 1
                    zoneIsActiveType[2] = Z2

                    if zoneSettings[4] == 1:
                        zoneFaultBuzzerOn = 1
                        
                    generateReportMsg(Z2, 'system_activate')
        else:
            if mux1_x2 == 1:
                mux1_x2 = 0
                if zoneSettings[3] == 1:                
                    writeLogToDatabase(Z2,'ZONE_2_DEACTIVE')
                    zoneIsActive[2] = 0
                    zoneIsActiveType[2] = 0
                    
                    generateReportMsg(Z2, 'system_activation_restored')                
               

        if mux_2 == 1:
            if mux2_x2 == 0:
                mux2_x2 = 1
                if powerZoneSettings[0] == 1:
                    writeLogToDatabase(PZ1,'ZONE_1_POWER_OFF')
                    zoneIsPowerOff[1] = 1
                    powerZoneIsActiveType[1] = PZ1

                    if powerZoneSettings[1] == 1:
                        zoneFaultBuzzerOn = 1                    

                    generateReportMsg(PZ1, 'alarm_system_off')
                    hb_manager and hb_manager.send_offline_heartbeat(PZ1)  # HB-03: immediate offline heartbeat
                    
                    power_zone_active_device_counter.update_device(PZ1, False)
                    
        else:

            if mux2_x2 == 1:
                mux2_x2 = 0
                if powerZoneSettings[0] == 1:
                    writeLogToDatabase(PZ1,'ZONE_1_POWER_ON')
                    zoneIsPowerOff[1] = 0
                    powerZoneIsActiveType[1] = 0

                    generateReportMsg(PZ1, 'alarm_system_on')                                                
                    hb_manager and hb_manager.send_online_heartbeat(PZ1)  # HB-04: immediate online heartbeat

                    power_zone_active_device_counter.update_device(PZ1, True)
                    
                
                

        if mux_3 == 1:
            if mux3_x2 == 0:
                mux3_x2 = 1
                if zoneSettings[42] == 1:
                    writeLogToDatabase('CCTV','ZONE_15_CAM_TAMPER')
                    zoneIsCamTamper[15] = 1

                    if zoneSettings[43] == 1:
                        zoneFaultBuzzerOn = 1

                    generateReportMsg('CCTV', 'tamper')                                                                        
                    
        else:
            if mux3_x2 == 1:
                mux3_x2 = 0
                if zoneSettings[42] == 1:                
                    writeLogToDatabase('CCTV','ZONE_15_CAM_TAMPER_RESTORE')
                    zoneIsCamTamper[15] = 0

                    generateReportMsg('CCTV', 'tamper_restored')                                                                        


            
            
    elif muxSelection == 3:

        if mux_1 == 1:
            if mux1_x3 == 0:
                mux1_x3 = 1
                if zoneSettings[3] == 1:
                    writeLogToDatabase(Z2,'ZONE_2_FAULT')
                    zoneIsFault[2] = 1
                    zoneIsFaultType[2] = Z2

                    if zoneSettings[4] == 1:
                        zoneFaultBuzzerOn = 1

                    generateReportMsg(Z2, 'alarm_system_fault')                                                                        
                    
        else:                
            if mux1_x3 == 1:
                mux1_x3 = 0
                if zoneSettings[3] == 1:
                    writeLogToDatabase(Z2,'ZONE_2_RESTORE')
                    zoneIsFault[2] = 0
                    zoneIsFaultType[2] = Z2


                    generateReportMsg(Z2, 'system_fault_condition_restored')
                    

        if mux_2 == 1:
            if mux2_x3 == 0:
                mux2_x3 = 1
                if powerZoneSettings[3] == 1:
                    writeLogToDatabase(PZ2,'ZONE_2_POWER_OFF')
                    zoneIsPowerOff[2] = 1
                    powerZoneIsActiveType[2] = PZ2
                    
                    if powerZoneSettings[4] == 1:
                        zoneFaultBuzzerOn = 1

                    generateReportMsg(PZ2, 'alarm_system_off')
                    hb_manager and hb_manager.send_offline_heartbeat(PZ2)  # HB-03: immediate offline heartbeat
                    
                    power_zone_active_device_counter.update_device(PZ2, False)
                    
        else:

            if mux2_x3 == 1:
                mux2_x3 = 0
                if powerZoneSettings[3] == 1:                
                    writeLogToDatabase(PZ2,'ZONE_2_POWER_ON')
                    zoneIsPowerOff[2] = 0
                    powerZoneIsActiveType[2] = PZ2

                    generateReportMsg(PZ2, 'alarm_system_on')
                    hb_manager and hb_manager.send_online_heartbeat(PZ2)  # HB-04: immediate online heartbeat
                    
                    power_zone_active_device_counter.update_device(PZ2, True)
                


        if mux_3 == 1:
            if mux3_x3 == 0:
                mux3_x3 = 1
                if zoneSettings[42] == 1:
                    writeLogToDatabase('CCTV','ZONE_15_CAM_DISCONNECTED')
                    zoneIsCamDisconnected[15] = 1

                    if zoneSettings[43] == 1:
                        zoneFaultBuzzerOn = 1

                    generateReportMsg('CCTV', 'camera_disconnect')
                    
        else:
            if mux3_x3 == 1:
                mux3_x3 = 0
                if zoneSettings[42] == 1:                
                    writeLogToDatabase('CCTV','ZONE_15_CAM_CONNECTETION_ESTABLISHED')
                    zoneIsCamDisconnected[15] = 0

                    generateReportMsg('CCTV', 'connection_established')


    elif muxSelection == 4:

        if mux_1 == 1:
            if mux1_x4 == 0:
                mux1_x4 = 1
                if zoneSettings[6] == 1:
                    writeLogToDatabase(Z3,'ZONE_3_ACTIVE')
                    zoneIsActive[3] = 1
                    zoneIsActiveType[3] = Z3

                    if zoneSettings[7] == 1:
                        zoneFaultBuzzerOn = 1
                        
                    generateReportMsg(Z3, 'system_activate')
                    
        else:
            if mux1_x4 == 1:
                mux1_x4 = 0
                if zoneSettings[6] == 1:                
                    writeLogToDatabase(Z3,'ZONE_3_DEACTIVE')
                    zoneIsActive[3] = 0
                    zoneIsActiveType[3] = 0
                    
                    generateReportMsg(Z3, 'system_activation_restored')                


        if mux_2 == 1:

            if mux2_x4 == 0:
                mux2_x4 = 1
                if powerZoneSettings[6] == 1:
                    writeLogToDatabase(PZ3,'ZONE_3_POWER_OFF')
                    zoneIsPowerOff[3] = 1
                    powerZoneIsActiveType[3] = PZ3

                    if powerZoneSettings[7] == 1:
                        zoneFaultBuzzerOn = 1

                    generateReportMsg(PZ3, 'alarm_system_off')                    
                    hb_manager and hb_manager.send_offline_heartbeat(PZ3)  # HB-03: immediate offline heartbeat

                    power_zone_active_device_counter.update_device(PZ3, False)
        else:

            if mux2_x4 == 1:
                mux2_x4 = 0
                if powerZoneSettings[6] == 1:
                    writeLogToDatabase(PZ3,'ZONE_3_POWER_ON')
                    zoneIsPowerOff[3] = 0
                    powerZoneIsActiveType[3] = 0

                    generateReportMsg(PZ3, 'alarm_system_on')
                    hb_manager and hb_manager.send_online_heartbeat(PZ3)  # HB-04: immediate online heartbeat
                    
                    power_zone_active_device_counter.update_device(PZ3, True)


        if mux_3 == 1:
            if mux3_x4 == 0:
                mux3_x4 = 1
                if zoneSettings[42] == 1:                
                    writeLogToDatabase('CCTV','ZONE_15_HDD_ERROR')
                    zoneIsHDDError[15] = 1

                    if zoneSettings[43] == 1:
                        zoneFaultBuzzerOn = 1

                    generateReportMsg('CCTV', 'hdd_error')                    
                    
        else:
            if mux3_x4 == 1:
                mux3_x4 = 0
                if zoneSettings[42] == 1:                                
                    writeLogToDatabase('CCTV','ZONE_15_HDD_ERROR_RESTORE')
                    zoneIsHDDError[15] = 0

                    generateReportMsg('CCTV', 'error_restored')
             


    elif muxSelection == 5:

        if mux_1 == 1:
            if mux1_x5 == 0:
                mux1_x5 = 1
                if zoneSettings[6] == 1:
                    writeLogToDatabase(Z3,'ZONE_3_FAULT')
                    zoneIsFault[3] = 1
                    zoneIsFaultType[3] = Z3
                    
                    if zoneSettings[7] == 1:
                        zoneFaultBuzzerOn = 1

                    generateReportMsg(Z3, 'alarm_system_fault')                    
                    
        else:                
            if mux1_x5 == 1:
                mux1_x5 = 0
                if zoneSettings[6] == 1:                
                    writeLogToDatabase(Z3,'ZONE_3_RESTORE')
                    zoneIsFault[3] = 0
                    zoneIsFaultType[3] = Z3


                    generateReportMsg(Z3, 'system_fault_condition_restored')                    
                    


        if mux_2 == 1:
            if mux2_x5 == 0:
                mux2_x5 = 1
                if powerZoneSettings[9] == 1:                
                    writeLogToDatabase(PZ4,'ZONE_4_POWER_OFF')
                    zoneIsPowerOff[4] = 1
                    powerZoneIsActiveType[4] = PZ4

                    if powerZoneSettings[10] == 1:
                        zoneFaultBuzzerOn = 1

                    generateReportMsg(PZ4, 'alarm_system_off')                    
                    hb_manager and hb_manager.send_offline_heartbeat(PZ4)  # HB-03: immediate offline heartbeat
                    power_zone_active_device_counter.update_device(PZ4, False)
        else:

            if mux2_x5 == 1:
                mux2_x5 = 0
                if powerZoneSettings[9] == 1:                                
                    writeLogToDatabase(PZ4,'ZONE_4_POWER_ON')
                    zoneIsPowerOff[4] = 0
                    powerZoneIsActiveType[4] = 0

                    generateReportMsg(PZ4, 'alarm_system_on')                    
                    hb_manager and hb_manager.send_online_heartbeat(PZ4)  # HB-04: immediate online heartbeat
                    power_zone_active_device_counter.update_device(PZ4, True)



        if mux_3 == 1:
            if mux3_x5 == 0:
                mux3_x5 = 1
                if zoneSettings[45] == 1:                
                    writeLogToDatabase('CCTV','ZONE_16_CAM_TAMPER')
                    zoneIsCamTamper[16] = 1

                    if zoneSettings[46] == 1:
                        zoneFaultBuzzerOn = 1

                    generateReportMsg('CCTV', 'tamper')                                                                
                    
        else:
            if mux3_x5 == 1:
                mux3_x5 = 0
                if zoneSettings[45] == 1:                                
                    writeLogToDatabase('CCTV','ZONE_16_CAM_TAMPER_RESTORE')
                    zoneIsCamTamper[16] = 0

                    generateReportMsg('CCTV', 'tamper_restored')                    
        

    elif muxSelection == 6:
        if mux_1 == 1:
            if mux1_x6 == 0:
                mux1_x6 = 1
                if zoneSettings[9] == 1:
                    writeLogToDatabase(Z4,'ZONE_4_ACTIVE')
                    zoneIsActive[4] = 1
                    zoneIsActiveType[4] = Z4

                    if zoneSettings[10] == 1:
                        zoneFaultBuzzerOn = 1
                        
                    generateReportMsg(Z4, 'system_activate')
        else:
            if mux1_x6 == 1:
                mux1_x6 = 0
                if zoneSettings[9] == 1:                
                    writeLogToDatabase(Z4,'ZONE_4_DEACTIVE')
                    zoneIsActive[4] = 0
                    zoneIsActiveType[4] = 0
                    
                    generateReportMsg(Z4, 'system_activation_restored')                            
   

        if mux_2 == 1:
            if mux2_x6 == 0:
                mux2_x6 = 1
                if zoneSettings[24] == 1:
                    writeLogToDatabase(Z9,'ZONE_9_ACTIVE')
                    zoneIsActive[9] = 1
                    zoneIsActiveType[9] = Z9
                    if zoneSettings[25] == 1:
                        zoneFaultBuzzerOn = 1
                    generateReportMsg(Z9, 'system_activate')
                        
        else:
            if mux2_x6 == 1:
                mux2_x6 = 0
                if zoneSettings[24] == 1:
                    writeLogToDatabase(Z9,'ZONE_9_DEACTIVE')
                    zoneIsActive[9] = 0
                    zoneIsActiveType[9] = 0
                    
                    generateReportMsg(Z9, 'system_activation_restored')                


        if mux_3 == 1:
            if mux3_x6 == 0:
                mux3_x6 = 1
                if zoneSettings[45] == 1:                                
                    writeLogToDatabase('CCTV','ZONE_16_CAM_DISCONNECTED')
                    zoneIsCamDisconnected[16] = 1
                    if zoneSettings[46] == 1:
                        zoneFaultBuzzerOn = 1
                        
                        generateReportMsg('CCTV', 'camera_disconnect')                
        else:
            if mux3_x6 == 1:
                mux3_x6 = 0
                if zoneSettings[45] == 1:                
                    writeLogToDatabase('CCTV','ZONE_16_CAM_CONNECTION_ESTABLISHED')
                    zoneIsCamDisconnected[16] = 0

                    generateReportMsg('CCTV', 'connection_established')                


    elif muxSelection == 7:
        if mux_1 == 1:
            if mux1_x7 == 0:
                mux1_x7 = 1
                if zoneSettings[9] == 1:                
                    writeLogToDatabase(Z4,'ZONE_4_FAULT')
                    zoneIsFault[4] = 1
                    zoneIsFaultType[4] = Z4
                    if zoneSettings[10] == 1:
                        zoneFaultBuzzerOn = 1

                        generateReportMsg(Z4, 'alarm_system_fault')                                        
        else:                
            if mux1_x7 == 1:
                mux1_x7 = 0
                if zoneSettings[9] == 1:                                
                    writeLogToDatabase(Z4,'ZONE_4_RESTORE')
                    zoneIsFault[4] = 0
                    zoneIsFaultType[4] = 0
                    
                    generateReportMsg(Z4, 'system_fault_condition_restored')                                        
                    

        if mux_2 == 1:
            if mux2_x7 == 0:
                mux2_x7 = 1
                if zoneSettings[24] == 1:
                    writeLogToDatabase(Z9,'ZONE_9_FAULT')
                    zoneIsFault[9] = 1
                    zoneIsFaultType[9] = Z9
                    if zoneSettings[25] == 1:
                        zoneFaultBuzzerOn = 1

                        generateReportMsg(Z9, 'alarm_system_fault')                                        
                        
        else:                            
            if mux2_x7 == 1:
                mux2_x7 = 0
                if zoneSettings[24] == 1:
                    writeLogToDatabase(Z9,'ZONE_9_RESTORE')
                    zoneIsFault[9] = 0
                    zoneIsFaultType[9] = 0

                    generateReportMsg(Z9, 'system_fault_condition_restored')                                        



        if mux_3 == 1:
            if mux3_x7 == 0:
                mux3_x7 = 1
                if zoneSettings[45] == 1:                
                    writeLogToDatabase('CCTV','ZONE_16_HDD_ERROR')
                    zoneIsHDDError[16] = 1
                    if zoneSettings[46] == 1:
                        zoneFaultBuzzerOn = 1

                        generateReportMsg('CCTV', 'hdd_error')                                        
                        
        else:
            if mux3_x7 == 1:
                mux3_x7 = 0
                if zoneSettings[45] == 1:                
                    writeLogToDatabase('CCTV','ZONE_16_HDD_ERROR_RESTORE')
                    zoneIsHDDError[16] = 0

                    generateReportMsg('CCTV', 'error_restored')

        
        if mux_4 == 1:
            if mux4_x7 == 0:
                mux4_x7 = 1
                writeLogToDatabase('X7','NONE')            
            

    elif muxSelection == 8:
        if mux_1 == 1:
            if mux1_x8 == 0:
                mux1_x8 = 1
                if zoneSettings[12] == 1:
                    writeLogToDatabase(Z5,'ZONE_5_ACTIVE')
                    zoneIsActive[5] = 1
                    zoneIsActiveType[5] = Z5
                    if zoneSettings[13] == 1:
                        zoneFaultBuzzerOn = 1
                    generateReportMsg(Z5, 'system_activate')                        
        else:
            if mux1_x8 == 1:
                mux1_x8 = 0
                if zoneSettings[12] == 1:
                    writeLogToDatabase(Z5,'ZONE_5_DEACTIVE')
                    zoneIsActive[5] = 0
                    zoneIsActiveType[5] = 0
                    
                    generateReportMsg(Z5, 'system_activation_restored')                

                
        if mux_2 == 1:
            if mux2_x8 == 0:
                mux2_x8 = 1
                if zoneSettings[27] == 1:
                    writeLogToDatabase(Z10,'ZONE_10_ACTIVE')
                    zoneIsActive[10] = 1
                    zoneIsActiveType[10] = Z10
                    if zoneSettings[28] == 1:
                        zoneFaultBuzzerOn = 1
                    generateReportMsg(Z10, 'system_activate')
                        
        else:
            if mux2_x8 == 1:
                mux2_x8 = 0
                if zoneSettings[27] == 1:
                    writeLogToDatabase(Z10,'ZONE_10_DEACTIVE')
                    zoneIsActive[10] = 0
                    zoneIsActiveType[10] = 0
                    
                    generateReportMsg(Z10, 'system_activation_restored')                
                


        if mux_3 == 1:
            if mux3_x8 == 0:
                mux3_x8 = 1
                if powerZoneSettings[12] == 1:                
                    writeLogToDatabase(PZ5,'ZONE_5_POWER_OFF')
                    zoneIsPowerOff[5] = 1
                    powerZoneIsActiveType[5] = PZ5
                    if powerZoneSettings[13] == 1:
                        zoneFaultBuzzerOn = 1

                    generateReportMsg(PZ5, 'alarm_system_off')
                    hb_manager and hb_manager.send_offline_heartbeat(PZ5)  # HB-03: immediate offline heartbeat

                    power_zone_active_device_counter.update_device(PZ5, False)
        else:

            if mux3_x8 == 1:
                mux3_x8 = 0
                if powerZoneSettings[12] == 1:                
                    writeLogToDatabase(PZ5,'ZONE_5_POWER_ON')
                    zoneIsPowerOff[5] = 0
                    powerZoneIsActiveType[5] = 0

                    generateReportMsg(PZ5, 'alarm_system_on')                                                                                    
                    hb_manager and hb_manager.send_online_heartbeat(PZ5)  # HB-04: immediate online heartbeat

                    power_zone_active_device_counter.update_device(PZ5, True)

        if mux_4 == 1:
            if mux4_x8 == 0:
                mux4_x8 = 1
                writeLogToDatabase('X8','NONE')                        


    elif muxSelection == 9:
        if mux_1 == 1:
            if mux1_x9 == 0:
                mux1_x9 = 1
                if zoneSettings[12] == 1:
                    writeLogToDatabase(Z5,'ZONE_5_FAULT')
                    zoneIsFault[5] = 1
                    zoneIsFaultType[5] = Z5
                    if zoneSettings[13] == 1:
                        zoneFaultBuzzerOn = 1                    

                    generateReportMsg(Z5, 'alarm_system_fault')                                                                                    

        else:                
            if mux1_x9 == 1:
                mux1_x9 = 0
                if zoneSettings[12] == 1:
                    writeLogToDatabase(Z5,'ZONE_5_RESTORE')
                    zoneIsFault[5] = 0
                    zoneIsFaultType[5] = 0

                    generateReportMsg(Z5, 'system_fault_condition_restored')                                                                                    
                    


        if mux_2 == 1:
            if mux2_x9 == 0:
                mux2_x9 = 1
                if zoneSettings[27] == 1:
                    writeLogToDatabase(Z10,'ZONE_10_FAULT')
                    zoneIsFault[10] = 1
                    zoneIsFaultType[10] = Z10
                    if zoneSettings[28] == 1:
                        zoneFaultBuzzerOn = 1

                    generateReportMsg(Z10, 'alarm_system_fault')                                                                                    
                        
        else:                
            if mux2_x9 == 1:
                mux2_x9 = 0
                if zoneSettings[27] == 1:
                    writeLogToDatabase(Z10,'ZONE_10_RESTORE')
                    zoneIsFault[10] = 0

                    generateReportMsg(Z10, 'system_fault_condition_restored')                                                                                    
        


        if mux_3 == 1:
            if mux3_x9 == 0:
                mux3_x9 = 1
                if powerZoneSettings[15] == 1:
                    writeLogToDatabase(PZ6,'ZONE_6_POWER_OFF')
                    zoneIsPowerOff[6] = 1
                    powerZoneIsActiveType[6] = PZ6

                    if powerZoneSettings[16] == 1:
                        zoneFaultBuzzerOn = 1

                    generateReportMsg(PZ6, 'alarm_system_off')
                    hb_manager and hb_manager.send_offline_heartbeat(PZ6)  # HB-03: immediate offline heartbeat
                    
                    power_zone_active_device_counter.update_device(PZ6, False)
                        
        else:

            if mux3_x9 == 1:
                mux3_x9 = 0
                if powerZoneSettings[15] == 1:
                    writeLogToDatabase(PZ6,'ZONE_6_POWER_ON')
                    zoneIsPowerOff[6] = 0
                    powerZoneIsActiveType[6] = 0

                    generateReportMsg(PZ6, 'alarm_system_on')
                    hb_manager and hb_manager.send_online_heartbeat(PZ6)  # HB-04: immediate online heartbeat
                    
                    power_zone_active_device_counter.update_device(PZ6, True)
                    
        if mux_4 == 1:
            if mux4_x9 == 0:
                mux4_x9 = 1
                writeLogToDatabase('X9','NONE')                        

    elif muxSelection == 10:
        if mux_1 == 1:
            if mux1_x10 == 0:
                mux1_x10 = 1
                if zoneSettings[15] == 1:
                    writeLogToDatabase(Z6,'ZONE_6_ACTIVE')
                    zoneIsActive[6] = 1
                    zoneIsActiveType[6] = Z6
                    if zoneSettings[16] == 1:
                        zoneFaultBuzzerOn = 1
                        
                    generateReportMsg(Z6, 'system_activate')
                        
        else:
            if mux1_x10 == 1:
                mux1_x10 = 0
                if zoneSettings[15] == 1:
                    writeLogToDatabase(Z6,'ZONE_6_DEACTIVE')
                    zoneIsActive[6] = 0
                    zoneIsActiveType[6] = 0
                    
                    generateReportMsg(Z6, 'system_activation_restored')                
            

        if mux_2 == 1:
            if mux2_x10 == 0:
                mux2_x10 = 1
                if zoneSettings[30] == 1:
                    writeLogToDatabase(Z11,'ZONE_11_ACTIVE')
                    zoneIsActive[11] = 1
                    zoneIsActiveType[11] = Z11
                    if zoneSettings[31] == 1:
                        zoneFaultBuzzerOn = 1
                        
                    generateReportMsg(Z11, 'system_activate')                                    
        else:                
            if mux2_x10 == 1:
                mux2_x10 = 0
                if zoneSettings[30] == 1:
                    writeLogToDatabase(Z11,'ZONE_11_DEACTIVE')
                    zoneIsActive[11] = 0
                    zoneIsActiveType[11] = 0

                    generateReportMsg(Z11, 'system_activation_restored')                        


        if mux_3 == 1:
            if mux3_x10 == 0:
                mux3_x10 = 1
                if powerZoneSettings[18] == 1:
                    writeLogToDatabase(PZ7,'ZONE_7_POWER_OFF')
                    zoneIsPowerOff[7] = 1
                    powerZoneIsActiveType[7] = PZ7
                    if powerZoneSettings[19] == 1:
                        zoneFaultBuzzerOn = 1                                                                                

                    generateReportMsg(PZ7, 'alarm_system_off')
                    hb_manager and hb_manager.send_offline_heartbeat(PZ7)  # HB-03: immediate offline heartbeat

                    power_zone_active_device_counter.update_device(PZ7, False)
        else:

            if mux3_x10 == 1:
                mux3_x10 = 0
                if powerZoneSettings[18] == 1:
                    writeLogToDatabase(PZ7,'ZONE_7_POWER_ON')
                    zoneIsPowerOff[7] = 0
                    powerZoneIsActiveType[7] = 0

                    generateReportMsg(PZ7, 'alarm_system_on')                                                                                                        
                    hb_manager and hb_manager.send_online_heartbeat(PZ7)  # HB-04: immediate online heartbeat
                    power_zone_active_device_counter.update_device(PZ7, True)
                    
        if mux_4 == 1:
            if mux4_x10 == 0:
                mux4_x10 = 1
                writeLogToDatabase('X10','NONE')                        

    elif muxSelection == 11:
        if mux_1 == 1:
            if mux1_x11 == 0:
                mux1_x11 = 1
                if zoneSettings[15] == 1:
                    writeLogToDatabase(Z6,'ZONE_6_FAULT')
                    zoneIsFault[6] = 1
                    zoneIsFaultType[6] = Z6
                    if zoneSettings[16] == 1:
                        zoneFaultBuzzerOn = 1                                                                                

                    generateReportMsg(Z6, 'alarm_system_fault')                                                                                                        
                    
        else:                
            if mux1_x11 == 1:
                mux1_x11 = 0
                if zoneSettings[15] == 1:
                    writeLogToDatabase(Z6,'ZONE_6_RESTORE')
                    zoneIsFault[6] = 0
                    zoneIsFaultType[6] = 0

                    generateReportMsg(Z6, 'system_fault_condition_restored')                                                                                                        
                    

        if mux_2 == 1:
            if mux2_x11 == 0:
                mux2_x11 = 1
                if zoneSettings[30] == 1:
                    writeLogToDatabase(Z11,'ZONE_11_FAULT')
                    zoneIsFault[11] = 1
                    zoneIsFaultType[11] = Z11
                    if zoneSettings[31] == 1:
                        zoneFaultBuzzerOn = 1                                                                                

                    generateReportMsg(Z11, 'alarm_system_fault')                                                                                                        
                    
        else:                
            if mux2_x11 == 1:
                mux2_x11 = 0
                if zoneSettings[30] == 1:                
                    writeLogToDatabase(Z11,'ZONE_11_RESTORE')
                    zoneIsFault[11] = 0
                    zoneIsFaultType[11] = 0

                    generateReportMsg(Z11, 'system_fault_condition_restored')                                                                                                        
                    


        if mux_3 == 1:
            if mux3_x11 == 0:
                mux3_x11 = 1
                if powerZoneSettings[21] == 1:
                    writeLogToDatabase(PZ8,'ZONE_8_POWER_OFF')
                    zoneIsPowerOff[8] = 1
                    powerZoneIsActiveType[8] = PZ8
                    if powerZoneSettings[22] == 1:
                        zoneFaultBuzzerOn = 1

                    generateReportMsg(PZ8, 'alarm_system_off')
                    hb_manager and hb_manager.send_offline_heartbeat(PZ8)  # HB-03: immediate offline heartbeat
                    power_zone_active_device_counter.update_device(PZ8, False)
                        
        else:

            if mux3_x11 == 1:
                mux3_x11 = 0
                if powerZoneSettings[21] == 1:                
                    writeLogToDatabase(PZ8,'ZONE_8_POWER_ON')
                    zoneIsPowerOff[8] = 0
                    powerZoneIsActiveType[8] = 0

                    generateReportMsg(PZ8, 'alarm_system_on')
                    hb_manager and hb_manager.send_online_heartbeat(PZ8)  # HB-04: immediate online heartbeat
                    power_zone_active_device_counter.update_device(PZ8, True)
        
        if mux_4 == 1:
            if mux4_x11 == 0:
                mux4_x11 = 1
                writeLogToDatabase('X11','NONE')                        

    elif muxSelection == 12:
        
        if mux_1 == 1:
            if mux1_x12 == 0:
                mux1_x12 = 1
                if zoneSettings[18] == 1:                
                    writeLogToDatabase('CCTV','ZONE_7_CAM_TAMPER')
                    zoneIsCamTamper[7] = 1
                    if zoneSettings[19] == 1:
                        zoneFaultBuzzerOn = 1

                    generateReportMsg('CCTV', 'tamper')                                                                                                                                                
                        
        else:
            if mux1_x12 == 1:
                mux1_x12 = 0
                if zoneSettings[18] == 1:                                
                    writeLogToDatabase('CCTV','ZONE_7_CAM_TAMPER_RESTORE')
                    zoneIsCamTamper[7] = 0

                    generateReportMsg('CCTV', 'tamper_restored')                                                                                                                            
            


        if mux_2 == 1:
            if mux2_x12 == 0:
                mux2_x12 = 1
                if zoneSettings[33] == 1:                                                
                    writeLogToDatabase(Z12,'ZONE_12_ACTIVE')
                    zoneIsActive[12] = 1
                    zoneIsActiveType[12] = Z12
                    if zoneSettings[34] == 1:
                        zoneFaultBuzzerOn = 1
                        
                    generateReportMsg(Z12, 'system_activate')
                        
        else:                
            if mux2_x12 == 1:
                mux2_x12 = 0
                if zoneSettings[33] == 1:                                                                
                    writeLogToDatabase(Z12,'ZONE_12_DEACTIVE')
                    zoneIsActive[12] = 0
                    zoneIsActiveType[12] = 0

                    generateReportMsg(Z12, 'system_activation_restored')                                



        global systemPowerOffShutDownMode
        if mux_3 == 1:
            if mux3_x12 == 0:
                mux3_x12 = 1
                writeLogToDatabase('SYSTEM','SYSTEM_POWER_OFF')
                systemPowerOffShutDownMode = 1
        else:
            if mux3_x12 == 1:
                mux3_x12 = 0
                writeLogToDatabase('SYSTEM','SYSTEM_POWER_ON')
                systemPowerOffShutDownMode = 0

        
        if mux_4 == 1:
            if mux4_x12 == 0:
                mux4_x12 = 1
                writeLogToDatabase('X12','NONE')                        

    elif muxSelection == 13:
        if mux_1 == 1:
            if mux1_x13 == 0:
                mux1_x13 = 1
                if zoneSettings[18] == 1:                                                                
                    writeLogToDatabase('CCTV','ZONE_7_CAM_DISCONNECTED')
                    zoneIsCamDisconnected[7] = 1
                    if zoneSettings[19] == 1:
                        zoneFaultBuzzerOn = 1
                        
                    generateReportMsg('CCTV', 'camera_disconnect')                                                                                                                            
                        
        else:
            if mux1_x13 == 1:
                mux1_x13 = 0
                if zoneSettings[18] == 1:                                                                                
                    writeLogToDatabase('CCTV','ZONE_7_CAM_CONNECTION_ESTABLISHED')
                    zoneIsCamDisconnected[7] = 0

                    generateReportMsg('CCTV', 'connection_established')                                                                                                                            
                

        if mux_2 == 1:
            if mux2_x13 == 0:
                mux2_x13 = 1
                if zoneSettings[33] == 1:                                                                
                    writeLogToDatabase(Z12,'ZONE_12_FAULT')
                    zoneIsFault[12] = 1
                    zoneIsFaultType[12] = Z12
                    if zoneSettings[34] == 1:
                        zoneFaultBuzzerOn = 1

                    generateReportMsg(Z12, 'alarm_system_fault')                                                                                                                            
                        
        else:                
            if mux2_x13 == 1:
                mux2_x13 = 0
                if zoneSettings[33] == 1:                                                                                
                    writeLogToDatabase(Z12,'ZONE_12_RESTORE')
                    zoneIsFault[12] = 0
                    zoneIsFaultType[12] = Z12

                    generateReportMsg(Z12, 'system_fault_condition_restored')                                                                                                                                                
        


        global mainSense
        global statusbox_mains_on
        global statusbox_battery_on
                
        if mux_3 == 1:
            if mux3_x13 == 0:
                mux3_x13 = 1
                mainSense = 1
                statusbox_mains_on = "false"
                statusbox_battery_on = "true"

                sendData2TB("battery_on")
        else:
            if mux3_x13 == 1:
                mux3_x13 = 0
                mainSense = 0
                statusbox_mains_on = "true"
                statusbox_battery_on = "false"

                sendData2TB("mains_on")

        if mux_4 == 1:
            if mux4_x13 == 0:
                mux4_x13 = 1
                writeLogToDatabase('X13','NONE')                        

    elif muxSelection == 14:
        if mux_1 == 1:
            if mux1_x14 == 0:
                mux1_x14 = 1
                if zoneSettings[18] == 1:                                                                
                    writeLogToDatabase('CCTV','ZONE_7_HDD_ERROR')
                    zoneIsHDDError[7] = 1
                    if zoneSettings[19] == 1:
                        zoneFaultBuzzerOn = 1
                        
                    generateReportMsg('CCTV', 'hdd_error')                                                                                                                                                
                        
        else:
            if mux1_x14 == 1:
                mux1_x14 = 0
                if zoneSettings[18] == 1:                                                                                
                    writeLogToDatabase('CCTV','ZONE_7_HDD_ERROR_RESTORE')
                    zoneIsHDDError[7] = 0

                    generateReportMsg('CCTV', 'error_restored')                                                                                                                                                
                    

        
        if mux_2 == 1:
            if mux2_x14 == 0:
                mux2_x14 = 1
                if zoneSettings[36] == 1:                                                                                
                    writeLogToDatabase(Z13,'ZONE_13_ACTIVE')
                    zoneIsActive[13] = 1
                    zoneIsActiveType[13] = Z13
                    if zoneSettings[37] == 1:
                        zoneFaultBuzzerOn = 1
                        
                    generateReportMsg(Z13, 'system_activate')
                        
        else:                
            if mux2_x14 == 1:
                mux2_x14 = 0
                if zoneSettings[36] == 1:                                                                                                
                    writeLogToDatabase(Z13,'ZONE_13_DEACTIVE')
                    zoneIsActive[13] = 0
                    zoneIsActiveType[13] = 0
                    
                    generateReportMsg(Z13, 'system_activation_restored')                                


        global statusbox_battery_reverse
        """
        if mux_3 == 1:
            if mux3_x14 == 0:
                mux3_x14 = 1
                statusbox_battery_reverse = "false"
                print(statusbox_battery_reverse)
                
        else:
            if mux3_x14 == 1:
                mux3_x14 = 0
                statusbox_battery_reverse = "true"
                print(statusbox_battery_reverse)
                sendData2TB("battery_reverse")                
        """
        if mux_3 == 1:
            # Battery normal (not reversed)
            # FIX: was == 0 which misses first read when mux3_x14 = -1 (boot)
            if mux3_x14 != 1:
                was_reversed = (mux3_x14 == 0)  # True only if we saw reverse before
                mux3_x14 = 1
                statusbox_battery_reverse = "false"
                print(statusbox_battery_reverse)
                if was_reversed:
                    # Only send restore if battery was previously reversed
                    sendData2TB("battery_reverse_restore")
                    # BATT-FIX-2a: send system status immediately on battery_reverse_restore
                    sendData2TBSystemStatus("true", "true", statusbox_mains_on, statusbox_battery_reverse, statusbox_battery_low, statusbox_sos_status, statusbox_network, statusbox_no_of_connected_device)

        else:
            # Battery reversed
            # FIX: was == 1 which misses first read when mux3_x14 = -1 (boot)
            if mux3_x14 != 0:
                mux3_x14 = 0
                statusbox_battery_reverse = "true"
                print(statusbox_battery_reverse)
                sendData2TB("battery_reverse")
                # BATT-FIX-2b: send system status immediately on battery_reverse
                sendData2TBSystemStatus("true", "true", statusbox_mains_on, statusbox_battery_reverse, statusbox_battery_low, statusbox_sos_status, statusbox_network, statusbox_no_of_connected_device)


        if mux_4 == 1:
            if mux4_x14 == 0:
                mux4_x14 = 1
                writeLogToDatabase('X14','NONE')                        

    elif muxSelection == 15:

        if mux_1 == 1:
            if mux1_x15 == 0:
                mux1_x15 = 1
                if zoneSettings[21] == 1:                                                                                                
                    writeLogToDatabase('CCTV','ZONE_8_CAM_TAMPER')
                    zoneIsCamTamper[8] = 1
                    if zoneSettings[22] == 1:
                        zoneFaultBuzzerOn = 1

                    generateReportMsg('CCTV', 'tamper')                                                                                                                                                
                        
        else:
            if mux1_x15 == 1:
                mux1_x15 = 0
                if zoneSettings[21] == 1:                                                                                                                
                    writeLogToDatabase('CCTV','ZONE_8_CAM_TAMPER_RESTORE')
                    zoneIsCamTamper[8] = 0
                    
                    generateReportMsg('CCTV', 'tamper_restored')                                                                                                                                                
                

        if mux_2 == 1:
            if mux2_x15 == 0:
                mux2_x15 = 1
                if zoneSettings[36] == 1:                                                                                                                
                    writeLogToDatabase(Z13,'ZONE_13_FAULT')
                    zoneIsFault[13] = 1
                    zoneIsFaultType[13] = Z13
                    if zoneSettings[37] == 1:
                        zoneFaultBuzzerOn = 1

                    generateReportMsg(Z13, 'alarm_system_fault')                                                                                                                                                
                        
        else:                
            if mux2_x15 == 1:
                mux2_x15 = 0
                if zoneSettings[36] == 1:                                                                                                                                
                    writeLogToDatabase(Z13,'ZONE_13_RESTORE')
                    zoneIsFault[13] = 0
                    zoneIsFaultType[13] = Z13

                    generateReportMsg(Z13, 'system_fault_condition_restored')                                                                                                                                                
                    
        
        if mux_3 == 1:
            if mux3_x15 == 0:
                mux3_x15 = 1
                writeLogToDatabase('X15','NONE')
        if mux_4 == 1:
            if mux4_x15 == 0:
                mux4_x15 = 1
                writeLogToDatabase('X15','NONE')                        


def generateReportMsg(deviceType, deviceReportType):

    setup_mode_value = system_settings_db.retrieve_element("setup_mode")        
    if setup_mode_value == "disabled":

        if deviceReportType == 'system_activate': 
        
            if deviceType == 'BAS':                                         #2
                sendData2TB("intrusion_alarm_system_activate")
                #msg_queue_buffer.add("intrusion_alarm_system_activate")
            elif deviceType == 'FAS':
                sendData2TB("fire_alarm_system_activate")
                #msg_queue_buffer.add("fire_alarm_system_activate")
            elif deviceType == 'BACS':
                sendData2TB("access_control_door_open")
                #msg_queue_buffer.add("access_control_door_open")
            elif deviceType == 'TIME_LOCK':
                sendData2TB("time_lock_door_open")
            elif deviceType == 'IAS':
                sendData2TB("integrated_alarm_system_activate")                

        elif deviceReportType == 'alarm_system_on':                         #4
                            
            if deviceType == 'BAS':
                sendData2TB("intrusion_alarm_system_on")
                #msg_queue_buffer.add("intrusion_alarm_system_on")
            elif deviceType == 'FAS':
                sendData2TB("fire_alarm_system_on")
                #msg_queue_buffer.add("fire_alarm_system_on")
            elif deviceType == 'TIME_LOCK':
                sendData2TB("time_lock_system_on")
                #msg_queue_buffer.add("time_lock_system_on")
            elif deviceType == 'BACS':
                sendData2TB("access_control_system_on")
                #msg_queue_buffer.add("access_control_system_on")
            elif deviceType == 'CCTV':
                sendData2TB("dvr_nvr_on")
                #msg_queue_buffer.add("dvr_nvr_on")
            elif deviceType == 'IAS':
                sendData2TB("integrated_alarm_system_on")

        elif deviceReportType == 'alarm_system_off':                        #4

            if deviceType == 'BAS':
                sendData2TB("intrusion_alarm_system_off")
                #msg_queue_buffer.add("intrusion_alarm_system_off")
            elif deviceType == 'FAS':
                sendData2TB("fire_alarm_system_off")
                #msg_queue_buffer.add("fire_alarm_system_off")
            elif deviceType == 'TIME_LOCK':
                sendData2TB("time_lock_system_off")
                #msg_queue_buffer.add("time_lock_system_off")
            elif deviceType == 'BACS':
                sendData2TB("access_control_system_off")
                #msg_queue_buffer.add("access_control_system_off")
            elif deviceType == 'CCTV':
                sendData2TB("dvr_nvr_off")
                #msg_queue_buffer.add("dvr_nvr_off")
            elif deviceType == 'IAS':
                sendData2TB("integrated_alarm_system_off")

        elif deviceReportType == 'alarm_system_fault':                      #2

            if deviceType == 'BAS':
                sendData2TB("intrusion_alarm_system_fault")
                #msg_queue_buffer.add("intrusion_alarm_system_fault")
            elif deviceType == 'FAS':
                sendData2TB("fire_alarm_system_fault")
                #msg_queue_buffer.add("fire_alarm_system_fault")
            elif deviceType == 'BACS':
                sendData2TB("access_control_system_tamper")
                #msg_queue_buffer.add("access_control_system_tamper")
            elif deviceType == 'TIME_LOCK':
                sendData2TB("time_lock_tamper")
                #msg_queue_buffer.add("time_lock_tamper")
            elif deviceType == 'IAS':
                sendData2TB("integrated_alarm_system_fault")

        elif deviceReportType == 'system_activation_restored':              #2
            
            if deviceType == 'BAS':
                sendData2TB("intrusion_alarm_system_activation_restored")
                #msg_queue_buffer.add("intrusion_alarm_system_activation_restored")
            elif deviceType == 'FAS':
                sendData2TB("fire_alarm_system_activation_restored")
                #msg_queue_buffer.add("fire_alarm_system_activation_restored")
            elif deviceType == 'BACS':
                sendData2TB("access_control_door_close")
                #msg_queue_buffer.add("access_control_door_close")
            elif deviceType == 'TIME_LOCK':
                sendData2TB("time_lock_door_close")
                #msg_queue_buffer.add("time_lock_door_close")
            elif deviceType == 'IAS':
                sendData2TB("integrated_alarm_system_activation_restored")

        elif deviceReportType == 'system_fault_condition_restored':         #2
            if deviceType == 'BAS':
                sendData2TB("intrusion_alarm_system_fault_condition_restored")
                #msg_queue_buffer.add("intrusion_alarm_system_fault_condition_restored")            
            elif deviceType == 'FAS':
                sendData2TB("fire_alarm_system_fault_condition_restored")
                #msg_queue_buffer.add("fire_alarm_system_fault_condition_restored")
            elif deviceType == 'TIME_LOCK':
                sendData2TB("time_lock_tamper_restored")
                #msg_queue_buffer.add("time_lock_tamper_restored")
            elif deviceType == 'BACS':
                sendData2TB("access_control_system_tamper_restored")
                #msg_queue_buffer.add("access_control_system_tamper_restored")
            elif deviceType == 'IAS':
                sendData2TB("integrated_alarm_system_fault_condition_restored")

        elif deviceReportType == 'tamper_restored':                         #3
            
            if deviceType == 'TIME_LOCK':
                sendData2TB("time_lock_tamper_restored")
                #msg_queue_buffer.add("fire_alarm_system_fault_condition_restored")
            elif deviceType == 'BACS':
                sendData2TB("access_control_system_tamper_restored")
                #msg_queue_buffer.add("fire_alarm_system_fault_condition_restored")
            elif deviceType == 'CCTV':
                sendData2TB("camera_tampered_restored")
                #msg_queue_buffer.add("fire_alarm_system_fault_condition_restored")


        elif deviceReportType == 'heartbeat':                               #5
        
            if deviceType == 'BAS':
                sendData2TB("heartbeat_BAS")
                #msg_queue_buffer.add("heartbeat_BAS")
            elif deviceType == 'FAS':
                sendData2TB("heartbeat_FAS")
                #msg_queue_buffer.add("heartbeat_FAS")
            if deviceType == 'TIME_LOCK':
                sendData2TB("heartbeat_time_lock")
                #msg_queue_buffer.add("heartbeat_time_lock")
            elif deviceType == 'BACS':
                sendData2TB("heartbeat_access_control")
                #msg_queue_buffer.add("heartbeat_access_control")
            elif deviceType == 'CCTV':
                sendData2TB("heartbeat_CCTV")
                #msg_queue_buffer.add("heartbeat_CCTV")
            elif deviceType == 'IAS':
                sendData2TB("heartbeat_IBAS")

        elif deviceReportType == 'dvr_nvr_off':                             #1
        
            if deviceType == 'CCTV':
                sendData2TB("dvr_nvr_off")
                #msg_queue_buffer.add("dvr_nvr_off")


        elif deviceReportType == 'dvr_nvr_on':                              #1
        
            if deviceType == 'CCTV':
                sendData2TB("dvr_nvr_on")
                #msg_queue_buffer.add("dvr_nvr_on")


        elif deviceReportType == 'hdd_error':                               #1
        
            if deviceType == 'CCTV':
                sendData2TB("hdd_error")
                #msg_queue_buffer.add("hdd_error")


        elif deviceReportType == 'error_restored':                          #1
        
            if deviceType == 'CCTV':
                sendData2TB("hdd_error_restored")
                #msg_queue_buffer.add("hdd_error_restored")


        elif deviceReportType == 'connection_established':                  #1
        
            if deviceType == 'CCTV':
                sendData2TB("camera_connection_established")
                #msg_queue_buffer.add("camera_connection_established")


        elif deviceReportType == 'camera_disconnect':                       #1
        
            if deviceType == 'CCTV':
                sendData2TB("camera_disconnect")
                #msg_queue_buffer.add("camera_disconnect")


        elif deviceReportType == 'door_open':                               #2
        
            if deviceType == 'BACS':
                sendData2TB("access_control_door_open")
                #msg_queue_buffer.add("access_control_door_open")
            elif deviceType == 'TIME_LOCK':
                sendData2TB("time_lock_door_open")
                #msg_queue_buffer.add("time_lock_door_open")


        elif deviceReportType == 'door_close':                              #2
        
            if deviceType == 'BACS':
                sendData2TB("access_control_door_close")
                #msg_queue_buffer.add("access_control_door_close")
            elif deviceType == 'TIME_LOCK':
                sendData2TB("time_lock_door_close")
                #msg_queue_buffer.add("time_lock_door_close")


        elif deviceReportType == 'tamper':                                  #3
        
            if deviceType == 'BACS':
                sendData2TB("access_control_system_tamper")
                #msg_queue_buffer.add("access_control_system_tamper")
            elif deviceType == 'TIME_LOCK':
                sendData2TB("time_lock_tamper")
                #msg_queue_buffer.add("time_lock_tamper")
            elif deviceType == 'CCTV':
                sendData2TB("camera_tampered")
                #msg_queue_buffer.add("camera_tampered")



# Main function to send data to another process
def send_to_cavli_subprocess():
    """
    Drain msg_queue_buffer (in-memory) into payloads.db via main_program.run().
    payloads.db is read ONLY by thingsboard_mqtt_publisher.py — never read back here.
    """
    next_subtracted_element = msg_queue_buffer.get_next_subtracted_element()
    if next_subtracted_element:
        main_program.run(next_subtracted_element)
        msg_queue_buffer.query_and_subtract_first()



# Main function to send data to another process
def send_to_ethernet_subprocess():
    """
    Drain msg_queue_buffer (in-memory) into payloads.db via main_program.run().
    payloads.db is read ONLY by thingsboard_mqtt_publisher.py — never read back here.
    The fallback path (reading payloads.db and re-inserting) was removed because
    it created an infinite loop: payloads.db → run() → insert → payloads.db → ...
    """
    next_subtracted_element = msg_queue_buffer.get_next_subtracted_element()
    if next_subtracted_element:
        main_program.run(next_subtracted_element)
        msg_queue_buffer.query_and_subtract_first()


# Simulated cloud sending function
def send_to_ethernet_subprocess_script():

    if network_info.get_connection_status() == 'Connected':
        
        next_subtracted_element = msg_queue_buffer.get_next_subtracted_element()
        if next_subtracted_element:

            print(next_subtracted_element)

            # Command to run the helper script
            command = ['python', 'helper_script.py', next_subtracted_element]
            #command = ['python', 'helper_script_token.py', next_subtracted_element]
            # Run the helper script with subprocess and pass the JSON parameters as command-line arguments
            result = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

            # Query and subtract the first added element
            msg_queue_buffer.query_and_subtract_first()
        
        else:
            #print("\nNo elements are subtracted from the buffer.")
            pass
        
        # Sequentially send data from the buffer to the cloud
    elif network_info.get_connection_status() == 'Disconnected':

        #print("No internet connection. Data not sent to the cloud.")
        pass


# Main function to send data to another process
def send_to_ethernet_subprocess_new():
    """
    Sends data to the child process using the DatabaseHandler.
    """
    if not main_program.get_child_status():
        # Child program is not ready. Waiting...
        pass  # This ensures we don't hog the CPU, waiting in a loop
    else:
        next_subtracted_element = msg_queue_buffer.get_next_subtracted_element()
        if next_subtracted_element:
            # Child status check
            command = ['python', 'helper_script.py', next_subtracted_element]

            # Run the helper script with subprocess and pass the JSON parameters as command-line arguments
            result = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

            # Query and subtract the first added element
            msg_queue_buffer.query_and_subtract_first()            
            print("Child status: {}".format(main_program.get_child_status()))
            main_program.run(next_subtracted_element)
            msg_queue_buffer.query_and_subtract_first()
        else:
            row_id, json_str = db_handler.get_json_string()
            if row_id:
                # Child status check
                main_program.run(json_str)
                db_handler.mark_as_sent(row_id)
            else:
                # No pending JSON entries found
                pass



def NetworkSettingsInit():
    
    # Get data from individual elements and store them in variables
    e_sim_enabled = network_settings.get_setting("e-SIM Enable/Disable")
    network_selection = network_settings.get_setting("Network Selection for e-SIM")
    gnss_enabled = network_settings.get_setting("Enable/Disable GNSS")
    alert_types_sms = network_settings.get_setting("Alert Types (SMS)")
    notification_schedule = network_settings.get_setting("Notification Schedule")
    led_status_enabled = network_settings.get_setting("Enable/Disable for Network LED Status")
    wireless_lan_enabled = network_settings.get_setting("Enable/Disable for Wireless LAN")
    ip_module_enabled = network_settings.get_setting("Enable/Disable IP Module")
    static_dynamic_enabled = network_settings.get_setting("Enable/Disable Static/dynamic")
    ipv4_ipv6_selection = network_settings.get_setting("IPv4/IPv6 Selection")
    ip_address = network_settings.get_setting("Set IP Address")
    port_number = network_settings.get_setting("Set Port Number")
    subnet_mask = network_settings.get_setting("Subnet mask")
    gateway = network_settings.get_setting("Gateway")
    dns_setup = network_settings.get_setting("DNS Setup")
    apn_settings = network_settings.get_setting("APN Settings")
    network_test_enabled = network_settings.get_setting("Network Test")
    gsm_enabled = network_settings.get_setting("Enable/Disable GSM")

    preferred_dns_server = network_settings.get_setting("preferred_dns_server")
    alternate_dns_server = network_settings.get_setting("alternate_dns_server")
    reset_to_dhcp = network_settings.get_setting("reset_to_dhcp")



def send_imei_id(value):

        
    # Format: {"imei_id": "<15-digit string>"}
    # TEL-FIX-3: flat imei_id — {"imei_id": value} not double-nested
    # Device IMEI — always send regardless of integration state
    payload = json.dumps({"imei_id": str(value)})
    msg_queue_buffer.add(payload)


def sendData2TBbattery_voltage(value):

        
    # Format: {"battery_voltage": <float 0-30>}
    # TEL-FIX: flat payload — battery_voltage as top-level key
    msg_queue_buffer.add(json.dumps({"battery_voltage": float(value)}))
    

def sendData2TBsmps_voltage(value):

    # Format: {"ac_voltage": <float 0-260>}

    # TEL-FIX: flat payload — ac_voltage as top-level key
    msg_queue_buffer.add(json.dumps({"ac_voltage": float(value)}))


def sendData2TBsystem_current(value):

    # Format: {"system_current": <float 0-5>}

    # TEL-FIX: flat payload — system_current as top-level key
    msg_queue_buffer.add(json.dumps({"system_current": float(value)}))
    

def sendData2TBLatLong(lat, lon):
        
    payload="{"
    payload+="\"lat\":"
    payload+=str(lat)
    payload+=","
    payload+="\"lon\":"
    payload+=str(lon)
    payload+="}"
        
    msg_queue_buffer.add(payload)


def sendData2TBSystemStatus(    statusbox_system_on_t = "false",
                                statusbox_system_healthy_t = "false",
                                statusbox_mains_on_t = "false",
                                statusbox_battery_reverse_t = "false",
                                statusbox_battery_low_t = "false",
                                statusbox_sos_status_t = "false",
                                statusbox_network_t_t = 'NA',
                                statusbox_no_of_connected_device_t = 0):


    statusbox_network_t = str("\"") + str(statusbox_network_t_t) + str("\"")        

    # TEL-FIX-2: flat dict — remove system_status wrapper
    # Each statusbox_* becomes its own ThingsBoard time-series key
    payload = json.dumps({
        "statusbox_system_on":             statusbox_system_on_t,
        "statusbox_system_healthy":         statusbox_system_healthy_t,
        "statusbox_mains_on":               statusbox_mains_on_t,
        "statusbox_battery_reverse":        statusbox_battery_reverse_t,
        "statusbox_battery_low":            statusbox_battery_low_t,
        "statusbox_sos_status":             statusbox_sos_status_t,
        "statusbox_network":                statusbox_network_t_t,
        "statusbox_no_of_connected_device": statusbox_no_of_connected_device_t,
    })

    # System status is panel health data — always send regardless of NVR integration
    msg_queue_buffer.add(payload)
    #cloudDataSendingOptions(dataSendingOption, payload)


def calculate_zones_on():
    
    global powerZoneSettingsOnCounter
    global powerZoneOnCounter
    
    """
    Connects to the SQLite database, calculates the number of zones that are currently on,
    and returns the result.
    
    Returns:
    int: The number of zones that are currently on.
    """
    def count_log_types(cursor, log_types):
        """
        Counts the occurrences of specified log types using the given database cursor.
        
        Parameters:
        cursor (sqlite3.Cursor): The SQLite cursor object.
        log_types (list): A list of log types to count.
        
        Returns:
        dict: A dictionary where keys are log types and values are their counts.
        """
        # Dictionary to store the counts
        log_type_counts = {}

        # Loop through each logType and count its occurrences
        for log_type in log_types:
            count = cursor.execute("SELECT COUNT(*) FROM systemLogs WHERE logType = ?", (log_type,)).fetchone()[0]
            log_type_counts[log_type] = count
        
        return log_type_counts

    # Define log types for POWER_OFF and POWER_ON
    power_off_log_types = [
        'ZONE_1_POWER_OFF',
        'ZONE_2_POWER_OFF',
        'ZONE_3_POWER_OFF',
        'ZONE_4_POWER_OFF',
        'ZONE_5_POWER_OFF',
        'ZONE_6_POWER_OFF',
        'ZONE_7_POWER_OFF',
        'ZONE_8_POWER_OFF'
    ]

    power_on_log_types = [
        'ZONE_1_POWER_ON',
        'ZONE_2_POWER_ON',
        'ZONE_3_POWER_ON',
        'ZONE_4_POWER_ON',
        'ZONE_5_POWER_ON',
        'ZONE_6_POWER_ON',
        'ZONE_7_POWER_ON',
        'ZONE_8_POWER_ON'
    ]
    
    # Database path
    database_path = DB_PANEL

    # Connect to the Database
    connection = sqlite3.connect(database_path)
    cursor = connection.cursor()

    # Get the counts for POWER_OFF and POWER_ON log types
    power_off_counts = count_log_types(cursor, power_off_log_types)
    power_on_counts = count_log_types(cursor, power_on_log_types)

    # Calculate total POWER_OFF and POWER_ON counts
    total_power_off_counts = sum(power_off_counts.values())
    total_power_on_counts = sum(power_on_counts.values())

    zones_on = powerZoneSettingsOnCounter

    # Closing the connection
    connection.close()

    #print "zones_on : " + str(powerZoneOnCounter)
    
    return zones_on


# Define the function
def count_device_instances(powerZoneSettings):
    # Initialize counts for each device type
    device_counts = {
        1: 'BAS',
        2: 'FAS',
        3: 'TIME_LOCK',
        4: 'BACS',
        5: 'CCTV',
        6: 'IAS'
    }

    # Initialize a set to keep track of active device types
    active_devices = set()

    # Iterate over the powerZoneSettings array
    for i in range(0, len(powerZoneSettings), 3):  # Increment by 3 for each row; function start at 0 index
        device_type = powerZoneSettings[i + 2]  # Get the device type from the third column
        status = powerZoneSettings[i]  # Get the status from the first column
        if status == 1:               # if the status equal to 1, indicating the device is Active Condition
            active_devices.add(device_type) # the device_type is added to the active_devices set

    # Initialize counts for each device type
    device_instances = {
        'BAS': 0,
        'FAS': 0,
        'TIME_LOCK': 0,
        'BACS': 0,
        'CCTV': 0,
        'IAS': 0        
    }

    # Count active devices
    for device_type in active_devices:
        device_instances[device_counts[device_type]] = 1

    return device_instances


import device_parameters_module
dpm = device_parameters_module  # alias used in device menu functions
import requests
from requests.auth import HTTPDigestAuth
from requests.exceptions import ConnectionError  # Import ConnectionError
from hikvisionapi import Client


def check_hikvision_nvr(): 
    device_type = 'HikvisionNVR1'
    devices = device_parameters_module.get_device_parameters(device_type)
    ipaddress = devices[0]['ip_address']
    userid = devices[0]['username']
    password = devices[0]['password']

    try:
        # Simulating a client connection to Hikvision NVR
        cam = Client('http://' + ipaddress, userid, password)
        #print("Hikvision NVR is active.")
        return "Active"

    except ConnectionError as e:
        #print("Connection error to Hikvision NVR at IP:", ipaddress, "Error:", e)
        return "Inactive"

    except Exception as e:
        #print("Error initializing Hikvision NVR:", e)
        return "Inactive"


def check_dahua_nvr():
    device_type = 'DahuaNVR1'
    devices = device_parameters_module.get_device_parameters(device_type)
    ipaddress = devices[0]['ip_address']
    username = devices[0]['username']
    password = devices[0]['password']

    url = 'http://{}/cgi-bin/magicBox.cgi?action=getVendor'.format(ipaddress)

    try:
        response = requests.get(url, auth=HTTPDigestAuth(username, password), verify=False, timeout=10)

        if response.status_code == 200:
            #print("Dahua NVR is active.")
            return "Active"
        else:
            print("Unexpected status code from Dahua NVR:", response.status_code)

    except requests.RequestException as e:
        #print("Request exception for Dahua NVR:", e)
        return "Inactive"

def check_cp_plus_nvr():
    device_type = 'CP_PlusNVR1'
    devices = device_parameters_module.get_device_parameters(device_type)
    ipaddress = devices[0]['ip_address']
    username = devices[0]['username']
    password = devices[0]['password']

    url = 'http://{}/cgi-bin/magicBox.cgi?action=getVendor'.format(ipaddress)

    try:
        response = requests.get(url, auth=HTTPDigestAuth(username, password), verify=False, timeout=10)

        if response.status_code == 200:
            #print("Dahua NVR is active.")
            return "Active"
        else:
            print("Unexpected status code from CP_PLUS NVR:", response.status_code)

    except requests.RequestException as e:
        #print("Request exception for Dahua NVR:", e)
        return "Inactive"

def check_hikvision_biometric():
    device_type = 'HikvisionBioMetric1'
    devices = device_parameters_module.get_device_parameters(device_type)

    if not devices or len(devices[0]) < 5:
        #print("Device parameters missing for Hikvision Biometric.")
        return "Inactive"

    ipaddress = devices[0]['ip_address']
    username = devices[0]['username']
    password = devices[0]['password']
    url = 'http://{}/ISAPI/System/deviceInfo'.format(ipaddress)

    try:
        response = requests.get(url, auth=(username, password), timeout=10)

        if response.status_code == 200:
            #print("Hikvision Biometric is active.")
            return "Active"
        else:
            print("Unexpected response from Hikvision Biometric:", response.status_code)

    except requests.RequestException as e:
        #print("Request exception for Hikvision Biometric:", e)
        return "Inactive"

# Example usage:
# print(check_hikvision_nvr())
# print(check_dahua_nvr())
# print(check_hikvision_biometric())
# (duplicate requests/device_parameters imports removed — DB-03)

def check_texecom_bas():
    """
    Returns a short status string for the Texecom BAS panel — shown on the
    LCD STATUS screen inside the Active Integration menu.

    FIX: Original used TCP socket connect_ex() to the Texecom panel IP:port.
    This is wrong — Texecom is the TCP SERVER and texecomConnect.py connects
    OUT to it. Dexter cannot accept an inbound connection from the panel, so
    connect_ex() always returns ECONNREFUSED → always showed "Offline" even
    when the panel was fully connected and streaming events.

    Correct approach: read texecomConnStat.txt which texecomConnect.py writes:
      "1" = protocol connected and panel responding
      "0" = disconnected or not yet connected
    If the file is missing the service has never connected → "Offline".
    Returns one of: "Online", "Offline", "Disabled"
    """
    CONN_STAT_FILE = "/home/pi/Test3/texecomConnStat.txt"
    try:
        flag = logical_params_module.get_parameter("active_integration_texecom_bas")
        if flag != 1:
            return "Disabled"

        try:
            with open(CONN_STAT_FILE, "r") as _f:
                val = _f.read().strip()
            return "Online" if val == "1" else "Offline"
        except FileNotFoundError:
            # Service enabled but never connected yet
            return "Offline"

    except Exception as e:
        logger.error("check_texecom_bas error: %s", e)
        return "Error"

def check_hik_bas() -> str:
    """
    Check Hikvision BAS panel connection status.
    Uses HTTP GET /ISAPI/System/deviceInfo with Digest Auth —
    identical pattern to check_hikvision_status().
    Returns "Active" or "Inactive".
    """
    server_ip, username, password = get_device_credentials("HikvisionBAS1")

    if not server_ip or not username or not password:
        return "Inactive"

    try:
        url = 'http://{}/ISAPI/System/deviceInfo'.format(server_ip)
        response = requests.get(url, auth=HTTPDigestAuth(username, password),
                                verify=False, timeout=10)
        if response.status_code == 200:
            return "Active"
        elif response.status_code in (401, 403):
            return "Inactive"
        else:
            return "Inactive"
    except requests.RequestException:
        return "Inactive"


def check_hikvision_status(device_type):
    """
    Check the connection status of a Hikvision biometric device.

    :param device_type: The type of the device (e.g., 'HikvisionBioMetric1').
    :return: "Active" if the connection is established, "Inactive" otherwise.
    """
    server_ip, username, password = get_device_credentials(device_type)

    # Validate the credentials retrieved
    if not server_ip or not username or not password:
        #print("Invalid device credentials.")
        return "Inactive"

    try:
        # Form the URL to check device status
        url = 'http://{}/ISAPI/System/deviceInfo'.format(server_ip)

        # Send GET request with HTTP Digest Authentication
        response = requests.get(url, auth=HTTPDigestAuth(username, password), verify=False, timeout=10)

        # Evaluate the response status code
        if response.status_code == 200:
            #print("Connection successful.")
            return "Active"
        elif response.status_code in (401, 403):
            #print("Authentication or access error. Status code:", response.status_code)
            return "Inactive"
        else:
            #print("Unexpected response. Status code:", response.status_code)
            return "Inactive"

    except requests.RequestException as e:
        #print("An error occurred while connecting to the device:", e)
        return "Inactive"

def get_device_credentials(device_type):
    """
    Retrieve the server IP, username, and password for a given device type.

    :param device_type: The type of the device (e.g., 'HikvisionBioMetric1').
    :return: A tuple containing (server_ip, username, password).
    """
    try:
        # Fetch device parameters from the module.
        devices = device_parameters_module.get_device_parameters(device_type)

        # Assuming the returned structure: a list of tuples where each tuple contains:
        # (id, name, ip_address, username, password, ...)
        if not devices or len(devices[0]) < 5:
            raise ValueError("Device parameters are missing or invalid format.")

        # Extracting the relevant parameters.
        server_ip = devices[0]['ip_address']
        username = devices[0]['username']
        password = devices[0]['password']

        # Return the extracted credentials.
        return server_ip, username, password

    except Exception as e:
        print("Error retrieving device credentials: {}".format(str(e)))
        logger.error("Error retrieving device credentials: {}".format(str(e)))
        return None, None, None

# Example usage
#device_type = 'HikvisionBioMetric1'
#status = check_hikvision_status(device_type)
#print("Device Status:", status)


counterTimer1Sec4 = 0
counterTimer1Sec5 = 0
SCHEDULE_UPDATE_2_TB = 300
SCHEDULE_UPDATE_2_ACTIVE_DEVICE_TB = 30
logTypeSysParam = 0

battery_voltage = 0
panel_current = 0
ac_voltage = 0
is_valid_network_available = False

def scheduleSystemStatusUpload():
    
    global tick1Sec4
    global counterTimer1Sec4
    global counterTimer1Sec5
    global logTypeSysParam

    global statusbox_system_on
    global statusbox_system_healthy
    global statusbox_mains_on
    global password_tamper_sms
    global statusbox_battery_reverse
    global statusbox_battery_low
    global statusbox_battery_on
    global statusbox_network
    global statusbox_4g_lte
    global statusbox_no_of_connected_device
    global statusbox_sos_status

    global ac_voltage
    global panel_current
    global battery_voltage

    global SCHEDULE_UPDATE_2_TB
    global SCHEDULE_UPDATE_2_ACTIVE_DEVICE_TB    

    #global dataSendingOption
    # global latitude / global longitude removed — lat/lon TB sends are now
    # handled entirely by location_manager (reads cavli_database on its schedule)


    if tick1Sec4 == 1:
        tick1Sec4 = 0

        # HB-01: drive 5-minute periodic group heartbeat
        hb_manager.tick()

        counterTimer1Sec5 = counterTimer1Sec5 + 1

        if counterTimer1Sec5 == SCHEDULE_UPDATE_2_ACTIVE_DEVICE_TB:
            counterTimer1Sec5 = 0
            consume_json()                
            

        counterTimer1Sec4 = counterTimer1Sec4 + 1            
            
        if counterTimer1Sec4 == SCHEDULE_UPDATE_2_TB:
            counterTimer1Sec4 = 0

            global powerZoneSettings

            # Call the function to count device instances
            device_counts = count_device_instances(powerZoneSettings)

            # Extract counts into separate variables
            bas_count = device_counts['BAS']
            fas_count = device_counts['FAS']
            time_lock_count = device_counts['TIME_LOCK']
            bacs_count = device_counts['BACS']
            cctv_count = device_counts['CCTV']
            ias_count = device_counts['IAS']

            if logTypeSysParam == 0:
                # GW-HB: gateway (panel) heartbeat — flat key, no log_type dependency
                msg_queue_buffer.add(json.dumps({"heartbeat": "online"}))
                logTypeSysParam = 1                
            elif logTypeSysParam == 1:
                statusbox_network = cavli_database.get_service_provider()
                statusbox_no_of_connected_device = calculate_zones_on()
                sendData2TBSystemStatus("true", "true", statusbox_mains_on, statusbox_battery_reverse, statusbox_battery_low, statusbox_sos_status, statusbox_network, statusbox_no_of_connected_device)

                global is_valid_network_available

                if statusbox_network != "NA":                 # Network is valid
                    if is_valid_network_available == False:   # Only if it was previously False
                        is_valid_network_available = True     # Mark it as now available
                        sendData2TB("network")
                        provider = cavli_database.get_service_provider()
                        operator = cavli_database.get_OperatorNumber()
                        sendData2TB({"operator_detail": [{"service_provider": provider,"operator_no": operator} ]})
                        
                        
                                        # Sent only once when it becomes valid
                else:
                    if is_valid_network_available == True:
                        is_valid_network_available = False
                        sendData2TB("network_disconnect")      # Sent every time it goes from valid to invalid                  
                
                logTypeSysParam = 2                                
            elif logTypeSysParam == 2:
                if get_active_integration() == 1:  # ACTIVE-INTEGRATION GATE
                    battery_voltage = controller_db_manager.get_battery_voltage()
                    ac_voltage      = controller_db_manager.get_ac_voltage()
                    panel_current   = controller_db_manager.get_panel_current()
                    # TEL-FIX-1: flat dict — each key becomes its own ThingsBoard time-series
                    msg_queue_buffer.add(json.dumps({
                        "battery_voltage": battery_voltage,
                        "ac_voltage":      ac_voltage,
                        "system_current":  panel_current,
                    }))
                logTypeSysParam = 3
            elif logTypeSysParam == 3:
                # Previously ac_voltage step — now combined in step 2, skip to 4
                logTypeSysParam = 4
            elif logTypeSysParam == 4:
                # Previously panel_current step — now combined in step 2, skip to 5
                logTypeSysParam = 5
            elif logTypeSysParam == 5:
                # location_manager handles all lat/lon TB sends.
                # On startup: sends India default immediately, retries real GPS
                # 5x every 15min, then every 12hr forever until GPS confirmed.
                # Once real GPS confirmed: sends every 12hr (twice a day).
                # SerialCommunication.py keeps cavli_database updated via AT commands.
                # No direct send here — location_manager reads DB on its own schedule.
                location_manager.tick()   # no-op; kept for debug logging only
                logTypeSysParam = 6                                

            elif logTypeSysParam == 6:
                # HB-02: heartbeat_BAS now sent by hb_manager.tick() every 5 min
                logTypeSysParam = 7                                
            elif logTypeSysParam == 7:
                # HB-02: heartbeat_FAS now sent by hb_manager.tick() every 5 min
                logTypeSysParam = 8                
            elif logTypeSysParam == 8:
                # HB-02: heartbeat_time_lock now sent by hb_manager.tick() every 5 min
                logTypeSysParam = 9                                
            elif logTypeSysParam == 9:
                # HB-02: heartbeat_access_control now sent by hb_manager.tick() every 5 min
                logTypeSysParam = 10
            elif logTypeSysParam == 10:
                # HB-02: heartbeat_CCTV now sent by hb_manager.tick() every 5 min
                logTypeSysParam = 11
            elif logTypeSysParam == 11:
                # HB-02: heartbeat_IAS now sent by hb_manager.tick() every 5 min
                logTypeSysParam = 12
            elif logTypeSysParam == 12:
                # imei_manager handles IMEI TB sends every 12hr (twice a day).
                # Sent immediately at startup and then every 12hr via threading.Timer.
                # No direct send here.
                logTypeSysParam = 0
            elif logTypeSysParam == 13:
                #consume_json()
                logTypeSysParam = 13

            #consume_json()                
                
def sendData2TB(log_type):
    # No active-integration gate here.
    # sendData2TB() sends ALL panel and mux-wired events — zone alarms,
    # camera_tampered, hdd_error, mains_on, system_on etc.
    # These come from hardware GPIO/mux scanning, NOT from NVR IP polling.
    # NVR IP polling is blocked at the service level (sys.exit(0) in each
    # NVR module when integration is disabled) — not here.

    try:        
        rtcYear = ds1307._read_year()
    except IOError:
        rtcYear = 0
    except ValueError:
        rtcYear = 0

    try:
        rtcMonth = ds1307._read_month()
    except IOError:
        rtcMonth = 0
    except ValueError:
        rtcMonth = 0

    try:
        rtcDate = ds1307._read_date()
    except IOError: 
        rtcDate = 0
    except ValueError:
        rtcDate = 0

    try:
        rtcHour = ds1307._read_hours()
    except IOError: 
        rtcHour = 0
    except ValueError:
        rtcHour = 0
        
    try:
        rtcMinute = ds1307._read_minutes()
    except IOError:
        rtcMinute = 0
    except ValueError:
        rtcMinute = 0
        
    try:
        rtcSecound = ds1307._read_seconds()
    except IOError:
        rtcSecound = 0
    except ValueError:
        rtcSecound = 0

    # Telemetry Format Spec v1.0 — Category 1 Event Log:
    # {"log_type":"<event>","zone_no":null,"date":"DD:MM:YY","time":"HH:MM"}
    # No branch field. Date zero-padded DD:MM:YY. Time zero-padded HH:MM (no seconds).
    date    = (str(rtcDate).zfill(2)  + ":" +
               str(rtcMonth).zfill(2) + ":" +
               str(rtcYear).zfill(2))
    timenow = (str(rtcHour).zfill(2)   + ":" +
               str(rtcMinute).zfill(2))

    if isinstance(log_type, (dict, list)):
        log_type_t = json.dumps(log_type)
    else:
        log_type_t = '"' + str(log_type) + '"'

    payload = ('{"log_type":' + log_type_t +
               ',"zone_no":null' +
               ',"date":"' + date    + '"' +
               ',"time":"' + timenow + '"}' )

    msg_queue_buffer.add(payload)


def rtcCheck():

    #i = 0
    global rtcFaulty

    rtcFaulty = 0

    try:
        ds1307.read_datetime()
    except ValueError:
        ds1307.write_all(seconds=0, minutes=0, hours=12, day=1, date=18, month=1, year=18, save_as_24h=True)
        ds1307.write_now()
        #pass
    except IOError:
        #i = 0
        rtcFaulty = 1


def zoneScanInit(shiftRegister4Buffers, shiftRegister3Buffers, shiftRegister2Buffers, shiftRegister1Buffers):
    
    global muxSelection

    time.sleep(2.0)
       

    time.sleep(2.0)
    muxSelection = 0b00001111 # 0 / 15
    sr.ssrWrite_4( (shiftRegister4Buffers | muxSelection), shiftRegister3Buffers, shiftRegister2Buffers, shiftRegister1Buffers )
    time.sleep(2.0)
    muxSelectionZoneInitScan()
    time.sleep(2.0)
      
    
    time.sleep(2.0)
    muxSelection = 0b00001110 # 1 / 14
    sr.ssrWrite_4( (shiftRegister4Buffers | muxSelection), shiftRegister3Buffers, shiftRegister2Buffers, shiftRegister1Buffers )
    time.sleep(2.0)    
    muxSelectionZoneInitScan()
    time.sleep(2.0)
    

    time.sleep(2.0)
    muxSelection = 0b00001101 # 2 / 13
    sr.ssrWrite_4( (shiftRegister4Buffers | muxSelection), shiftRegister3Buffers, shiftRegister2Buffers, shiftRegister1Buffers )
    time.sleep(2.0)    
    muxSelectionZoneInitScan()
    time.sleep(2.0)
    

    time.sleep(2.0)
    muxSelection = 0b00001100 # 3 / 12
    sr.ssrWrite_4( (shiftRegister4Buffers | muxSelection), shiftRegister3Buffers, shiftRegister2Buffers, shiftRegister1Buffers )
    time.sleep(2.0)    
    muxSelectionZoneInitScan()
    time.sleep(2.0)
    

    time.sleep(2.0)
    muxSelection = 0b00001011 # 4 / 11
    sr.ssrWrite_4( (shiftRegister4Buffers | muxSelection), shiftRegister3Buffers, shiftRegister2Buffers, shiftRegister1Buffers )
    time.sleep(2.0)    
    muxSelectionZoneInitScan()
    time.sleep(2.0)
    

    time.sleep(2.0)
    muxSelection = 0b00001010 # 5 / 10
    sr.ssrWrite_4( (shiftRegister4Buffers | muxSelection), shiftRegister3Buffers, shiftRegister2Buffers, shiftRegister1Buffers )
    time.sleep(2.0)
    muxSelectionZoneInitScan()
    time.sleep(2.0)
    

    time.sleep(2.0)
    muxSelection = 0b00001001 # 6 / 9
    sr.ssrWrite_4( (shiftRegister4Buffers | muxSelection), shiftRegister3Buffers, shiftRegister2Buffers, shiftRegister1Buffers )
    time.sleep(2.0)    
    muxSelectionZoneInitScan()
    time.sleep(2.0)
         

    time.sleep(2.0)
    muxSelection = 0b00001000 # 7 / 8
    sr.ssrWrite_4( (shiftRegister4Buffers | muxSelection), shiftRegister3Buffers, shiftRegister2Buffers, shiftRegister1Buffers )
    time.sleep(2.0)    
    muxSelectionZoneInitScan()
    time.sleep(2.0)
    

    time.sleep(2.0)
    muxSelection = 0b00000111 # 8 / 7
    sr.ssrWrite_4( (shiftRegister4Buffers | muxSelection), shiftRegister3Buffers, shiftRegister2Buffers, shiftRegister1Buffers )
    time.sleep(2.0)    
    muxSelectionZoneInitScan()
    time.sleep(2.0)
    

    time.sleep(2.0)
    muxSelection = 0b00000110 # 9 / 6
    sr.ssrWrite_4( (shiftRegister4Buffers | muxSelection), shiftRegister3Buffers, shiftRegister2Buffers, shiftRegister1Buffers )
    time.sleep(2.0)    
    muxSelectionZoneInitScan()
    time.sleep(2.0)
    

    time.sleep(2.0)
    muxSelection = 0b00000101 # 10 / 5
    sr.ssrWrite_4( (shiftRegister4Buffers | muxSelection), shiftRegister3Buffers, shiftRegister2Buffers, shiftRegister1Buffers )
    time.sleep(2.0)    
    muxSelectionZoneInitScan()
    time.sleep(2.0)
    

    time.sleep(2.0)
    muxSelection = 0b00000100 # 11 / 4
    sr.ssrWrite_4( (shiftRegister4Buffers | muxSelection), shiftRegister3Buffers, shiftRegister2Buffers, shiftRegister1Buffers )
    time.sleep(2.0)    
    muxSelectionZoneInitScan()
    time.sleep(2.0)
    

    time.sleep(2.0)
    muxSelection = 0b00000011 # 12 / 3
    sr.ssrWrite_4( (shiftRegister4Buffers | muxSelection), shiftRegister3Buffers, shiftRegister2Buffers, shiftRegister1Buffers )
    time.sleep(2.0)    
    muxSelectionZoneInitScan()
    time.sleep(2.0)
    

    time.sleep(2.0)
    muxSelection = 0b00000010 # 13 / 2
    sr.ssrWrite_4( (shiftRegister4Buffers | muxSelection), shiftRegister3Buffers, shiftRegister2Buffers, shiftRegister1Buffers )
    time.sleep(2.0)    
    muxSelectionZoneInitScan()
    time.sleep(2.0)
    

    time.sleep(2.0)
    muxSelection = 0b00000001 # 14 / 1
    sr.ssrWrite_4( (shiftRegister4Buffers | muxSelection), shiftRegister3Buffers, shiftRegister2Buffers, shiftRegister1Buffers )
    time.sleep(2.0)    
    muxSelectionZoneInitScan()
    time.sleep(2.0)
    

    time.sleep(2.0)
    muxSelection = 0b00000000 # 15 / 0
    sr.ssrWrite_4( (shiftRegister4Buffers | muxSelection), shiftRegister3Buffers, shiftRegister2Buffers, shiftRegister1Buffers )
    time.sleep(2.0)    
    muxSelectionZoneInitScan()
    time.sleep(2.0)


def zoneScan():
    
    global zoneCounter
    global muxSelection

    global fieldInputStatusLED1
    global fieldInputStatusLED2

        
    if zoneCounter == 15:
        muxSelection = 0b00001111 # 0 / 15
    elif zoneCounter == 14:
        muxSelection = 0b00001110 # 1 / 14
    elif zoneCounter == 13:
        muxSelection = 0b00001101 # 2 / 13
    elif zoneCounter == 12:
        muxSelection = 0b00001100 # 3 / 12
    elif zoneCounter == 11:
        muxSelection = 0b00001011 # 4 / 11
    elif zoneCounter == 10:
        muxSelection = 0b00001010 # 5 / 10
    elif zoneCounter == 9:
        muxSelection = 0b00001001 # 6 / 9
    elif zoneCounter == 8:
        muxSelection = 0b00001000 # 7 / 8
    elif zoneCounter == 7:
        muxSelection = 0b00000111 # 8 / 7
    elif zoneCounter == 6:
        muxSelection = 0b00000110 # 9 / 6
    elif zoneCounter == 5:
        muxSelection = 0b00000101 # 10 / 5
    elif zoneCounter == 4:
        muxSelection = 0b00000100 # 11 / 4
    elif zoneCounter == 3:
        muxSelection = 0b00000011 # 12 / 3
    elif zoneCounter == 2:
        muxSelection = 0b00000010 # 13 / 2
    elif zoneCounter == 1:
        muxSelection = 0b00000001 # 14 / 1
    elif zoneCounter == 0:
        muxSelection = 0b00000000 # 15 / 0

    zoneCounter = zoneCounter + 1
    if zoneCounter >= 16:
        zoneCounter = 0
       
""""
LOW_BATTERY = 7                        # Pin 26
GPIO.setup(LOW_BATTERY, GPIO.IN)       #  ACTIVE state is LOW
GPIO.setup(LOW_BATTERY, GPIO.IN, pull_up_down=GPIO.PUD_UP)

lowBatteryDetected    = 0
lowBatteryDetectedHIST = 0

trigger_signal         = False
trigger_signal_lockbit = False
is_low_battery_detected = False
_battery_low_sent      = False  # True = battery_low sent; prevents repeat sends until restore

def digitalInput():

    global lowBatteryDetected
    global lowBatteryDetectedHIST
    global statusbox_battery_low

    global trigger_signal
    global trigger_signal_lockbit

    global is_low_battery_detected
    global _battery_low_sent
    global lowBatteryDetectionWaitPeriod   # FIX: needed to force LCD to BATTERY_STATUS

    low_battery_input = GPIO.input(LOW_BATTERY)

    # ── Battery LOW detected (GPIO goes LOW) ──────────────────────────────────
    if low_battery_input == False:
        lowBatteryDetected     = True
        statusbox_battery_low  = "true"
        lowBatteryDetectionWaitPeriod = 1   # FIX: forces LCD to BATTERY_STATUS screen

        if not _battery_low_sent:
            # Send battery_low ONCE — held until battery recovers
            _battery_low_sent      = True
            is_low_battery_detected = True
            sendData2TB("battery_low")
            # BATT-FIX-3: send system status immediately on battery_low
            sendData2TBSystemStatus("true", "true", statusbox_mains_on, statusbox_battery_reverse, statusbox_battery_low, statusbox_sos_status, statusbox_network, statusbox_no_of_connected_device)

        counter.start_counter()

        if trigger_signal == False:
            trigger_signal = True

    # ── Battery OK / restored (GPIO goes HIGH) ────────────────────────────────
    else:
        lowBatteryDetected    = False
        statusbox_battery_low = "false"
        lowBatteryDetectionWaitPeriod = 0   # FIX: release LCD from BATTERY_STATUS screen

        if _battery_low_sent:
            # Reset flag so battery_low can fire again on next low event.
            _battery_low_sent       = False
            is_low_battery_detected = False
            sendData2TB("battery_low_restore")
            # BATT-FIX-4: send system status immediately on battery_low_restore
            sendData2TBSystemStatus("true", "true", statusbox_mains_on, statusbox_battery_reverse, statusbox_battery_low, statusbox_sos_status, statusbox_network, statusbox_no_of_connected_device)

        trigger_signal         = False
        trigger_signal_lockbit = False
        counter.check_reset_counter()

    # ── History update ────────────────────────────────────────────────────────
    lowBatteryDetectedHIST = (low_battery_input == False)

    # ── Power-off trigger logic ───────────────────────────────────────────────
    if trigger_signal == True and trigger_signal_lockbit == False:
        if counter.increment():
            sendData2TB("power_off")
            trigger_signal_lockbit = True

"""            

LOW_BATTERY = 7                        # Pin 26
GPIO.setup(LOW_BATTERY, GPIO.IN, pull_up_down=GPIO.PUD_UP)

lowBatteryDetected = 0
lowBatteryDetectedHIST = 0

trigger_signal = False
trigger_signal_lockbit = False
is_low_battery_detected = False

def digitalInput():

    global lowBatteryDetected
    global lowBatteryDetectedHIST
    global statusbox_battery_low

    global trigger_signal
    global trigger_signal_lockbit

    global is_low_battery_detected

    low_battery_input = GPIO.input(LOW_BATTERY)

    # =======================================================
    # BATTERY LOW detection (HIGH → LOW) — edge triggered
    # =======================================================
    if low_battery_input == False:
        lowBatteryDetected = True
        statusbox_battery_low = "true"

        counter.start_counter()

        if is_low_battery_detected == False:
            is_low_battery_detected = True
            sendData2TB("battery_low")
            # BATT-FIX-3: send system status immediately — once on battery_low event
            sendData2TBSystemStatus("true", "true", statusbox_mains_on, statusbox_battery_reverse, statusbox_battery_low, statusbox_sos_status, statusbox_network, statusbox_no_of_connected_device)
            trigger_signal = True

    else:
        lowBatteryDetected = False
        statusbox_battery_low = "false"
        is_low_battery_detected = False

    # =======================================================
    # BATTERY RESTORE detection (LOW → HIGH) — edge triggered
    # =======================================================
    if lowBatteryDetectedHIST == False and low_battery_input == True:
        sendData2TB("battery_low_restore")
        # BATT-FIX-4: send system status immediately — once on battery_low_restore
        sendData2TBSystemStatus("true", "true", statusbox_mains_on, statusbox_battery_reverse, statusbox_battery_low, statusbox_sos_status, statusbox_network, statusbox_no_of_connected_device)
        trigger_signal = False
        trigger_signal_lockbit = False
        counter.check_reset_counter()

    # =======================================================
    # Update history
    # =======================================================
    if low_battery_input == False:
        lowBatteryDetectedHIST = False   # battery low
    else:
        lowBatteryDetectedHIST = True    # battery ok

    # =======================================================
    # Power off trigger logic
    # =======================================================
    if trigger_signal == True and trigger_signal_lockbit == False:
        #print("POWER_OFF_Enter")
        if counter.increment():
            print("POWER_OFF")
            sendData2TB("power_off")
            # BATT-FIX-5: send system status immediately on power_off
            sendData2TBSystemStatus("true", "true", statusbox_mains_on, statusbox_battery_reverse, statusbox_battery_low, statusbox_sos_status, statusbox_network, statusbox_no_of_connected_device)
            trigger_signal_lockbit = True



counterTimer1Sec3 = 0        
isLANStatusCheckOn = 0
counterTimer1Sec2 = 0        
buzzerOnTime3Sec1 = 0
buzzerOnTime3Sec = 0
beepOn1Sec = 0
duressActivate = 0
# ------------------ Output Shift Register LED Display -----------------
#  / outputShiftRegLEDDisplay()
#-----------------------------------------------------------------------
def outputShiftRegLEDDisplay():
    

    global onTime

    global sleepSwitch
    global tamper
    global LCDBackLightON
    global toggleBit500mSecSec
    global duressActivate
    global byPassLockActivated
    global lowBatteryDetected
    global isOnMaintenanceMode
    global tamperPassActivated
    global isLampTestACTIVATED

    global isRelayTestACTIVATED
    global isHooterTestACTIVATED

    global beepOn1Sec
    global buzzerOnTime3Sec
    global counterTimer1Sec2
    global tick1Sec2

    global ledOnTime
    global toggleBit250mSecSec
    global toggleBit1Sec
    global accessIsRestrictedNationalHOLIDAY
    global lowBatteryBuzzOn

    global shiftRegister1Buffers
    global shiftRegister2Buffers
    global shiftRegister3Buffers
    global shiftRegister4Buffers

    global relayBuzzer
    global muxSelection
    global shiftRegSet
    
    global muxSelectionAndLED

    global parameter_names
    global parameter_values
        

#    #  SH2                     Q7/7                 Q6/6                    Q5/5                    Q4/4                    Q3/3                    Q2/2                        Q1/1                Q0/15
#    frontPanelLED1 = {'NOT_IMPLEMENTED':0x80, 'FAS_FAULT_LED':0x40, 'BAS_ACTIVE_LED':0x20, 'TIME_LOCK_OFF_LED':0x10, 'BAS_FAULT_LED':0x08, 'TIME_LOCK_FAULT_LED':0x04, 'NVR_DVR_OFF_LED':0x02, 'CCTV_TAMPER_LED':0x01}


#    #  SH3                     Q7/7                 Q6/6                    Q5/5                   Q4/4                    Q3/3                    Q2/2                         Q1/1                Q0/15
#    frontPanelLED2 = {'NOT_IMPLEMENTED':0x80, 'SYSTEM_HEALTHY_LED':0x40, 'BACS_OFF_LED':0x20, 'CCTV_HDD_ERROR_LED':0x10, 'BAT_ON_LED':0x08, 'CCTV_DISCONNECTED_LED':0x04, 'FAS_ACTIVE_LED':0x02, 'BAS_OFF_LED':0x01}

                                                                                                                                                                                            
#    #  SH1                  Q7/7                Q6/6              Q5/5                 Q4/4             Q3/3            Q2/2            Q1/1         Q0/15
#    relayBuzzer = {'NOT_IMPLEMENTED':0x80, 'LCD_BACK_ON':0x40,'REMOTE_BUZZER':0x20,'REMOTE_LED1':0x10,'BUZZER':0x08,'RELAY_2':0x04, 'RELAY_2':0x02, 'RELAY_1':0x01}


#    #  SH1                      Q7/7             Q6/6              Q5/5                 Q4/4                    Q3/3                    Q2/2                       Q1/1                    Q0/15
#    muxSelectionAndLED = {'4G_LTE_LED':0x80, 'FAS_OFF_LED':0x40,'NETWORK_LED':0x20,'BACS_FAULT_LED':0x10,'MUX_SELECT_LINE4':0x08,'MUX_SELECT_LINE3':0x04, 'MUX_SELECT_LINE2':0x02, 'MUX_SELECT_LINE1':0x01}


    global zoneIsActive
    global zoneIsCamDisconnected
    global zoneIsFault
    global zoneIsHDDError
    global powerZoneIsActive
    global zoneIsCamTamper
    global zoneIsPowerOff

    global frontPanelLED1
    global frontPanelLED2


    shiftRegister1Buffers = shiftRegister1Buffers | relayBuzzer['REMOTE_LED1']
    shiftRegister1Buffers = shiftRegister1Buffers | relayBuzzer['REMOTE_BUZZER']

    global mainSense
    shiftRegister3Buffers = shiftRegister3Buffers & ~(frontPanelLED2['BAT_ON_LED'])
    if mainSense == 1:
        shiftRegister3Buffers = shiftRegister3Buffers | frontPanelLED2['BAT_ON_LED']
        
    global zoneIsFaultType
    global frontPanelLEDs
    global zoneIsPowerOff


    NUM_ZONES = 15    
    
    #FAULT LED
    shiftRegister1Buffers = shiftRegister1Buffers & ~(relayBuzzer['RELAY_2'])
    
    shiftRegister3Buffers = shiftRegister3Buffers & ~(frontPanelLED2['CCTV_HDD_ERROR_LED'])
    if any(element == 1 for element in zoneIsHDDError):				        
        shiftRegister3Buffers = shiftRegister3Buffers | frontPanelLED2['CCTV_HDD_ERROR_LED']
        shiftRegister1Buffers = shiftRegister1Buffers | relayBuzzer['RELAY_2']

    shiftRegister2Buffers = shiftRegister2Buffers & ~(frontPanelLED1['TIME_LOCK_FAULT_LED'])           
    for zone in range(1, NUM_ZONES + 1):
        if zoneIsFault[zone] == 1 and zoneIsFaultType[zone] == 'TIME_LOCK':
            shiftRegister2Buffers |= frontPanelLED1['TIME_LOCK_FAULT_LED']
            shiftRegister1Buffers = shiftRegister1Buffers | relayBuzzer['RELAY_2']

    shiftRegister2Buffers = shiftRegister2Buffers & ~(frontPanelLED1['BAS_FAULT_LED'])                    
    for zone in range(1, NUM_ZONES + 1):
        if zoneIsFault[zone] == 1 and zoneIsFaultType[zone] == 'BAS':
            shiftRegister2Buffers |= frontPanelLED1['BAS_FAULT_LED']
            shiftRegister1Buffers = shiftRegister1Buffers | relayBuzzer['RELAY_2']

    shiftRegister4Buffers = shiftRegister4Buffers & ~(muxSelectionAndLED['BACS_FAULT_LED'])                    
    for zone in range(1, NUM_ZONES + 1):
        if zoneIsFault[zone] == 1 and zoneIsFaultType[zone] == 'BACS':
            shiftRegister4Buffers = shiftRegister4Buffers | muxSelectionAndLED['BACS_FAULT_LED']
            shiftRegister1Buffers = shiftRegister1Buffers | relayBuzzer['RELAY_2']

    shiftRegister2Buffers = shiftRegister2Buffers & ~(frontPanelLED1['FAS_FAULT_LED'])                    
    for zone in range(1, NUM_ZONES + 1):
        if zoneIsFault[zone] == 1 and zoneIsFaultType[zone] == 'FAS':
            shiftRegister2Buffers = shiftRegister2Buffers | frontPanelLED1['FAS_FAULT_LED']
            shiftRegister1Buffers = shiftRegister1Buffers | relayBuzzer['RELAY_2']


    #OFF LED
    shiftRegister2Buffers = shiftRegister2Buffers & ~(frontPanelLED1['TIME_LOCK_OFF_LED'])
    
    for zone in range(1, NUM_ZONES + 1):
        if zoneIsPowerOff[zone] == 1 and powerZoneIsActiveType[zone] == 'TIME_LOCK':
            shiftRegister2Buffers = shiftRegister2Buffers | frontPanelLED1['TIME_LOCK_OFF_LED']

    shiftRegister3Buffers = shiftRegister3Buffers & ~(frontPanelLED2['BAS_OFF_LED'])                    
    for zone in range(1, NUM_ZONES + 1):
        if zoneIsPowerOff[zone] == 1 and powerZoneIsActiveType[zone] == 'BAS':
            shiftRegister3Buffers = shiftRegister3Buffers | frontPanelLED2['BAS_OFF_LED']       

    shiftRegister3Buffers = shiftRegister3Buffers & ~(frontPanelLED2['BACS_OFF_LED'])                    
    for zone in range(1, NUM_ZONES + 1):
        if zoneIsPowerOff[zone] == 1 and powerZoneIsActiveType[zone] == 'BACS':
            shiftRegister3Buffers = shiftRegister3Buffers | frontPanelLED2['BACS_OFF_LED']

    shiftRegister4Buffers = shiftRegister4Buffers & ~(muxSelectionAndLED['FAS_OFF_LED'])                    
    for zone in range(1, NUM_ZONES + 1):
        if zoneIsPowerOff[zone] == 1 and powerZoneIsActiveType[zone] == 'FAS':
            shiftRegister4Buffers = shiftRegister4Buffers | muxSelectionAndLED['FAS_OFF_LED']

    shiftRegister2Buffers = shiftRegister2Buffers & ~(frontPanelLED1['NVR_DVR_OFF_LED'])                    
    for zone in range(1, NUM_ZONES + 1):
        if zoneIsPowerOff[zone] == 1 and powerZoneIsActiveType[zone] == 'CCTV':
            shiftRegister2Buffers = shiftRegister2Buffers | frontPanelLED1['NVR_DVR_OFF_LED']

    #ACTIVE LED
    shiftRegister1Buffers = shiftRegister1Buffers & ~(relayBuzzer['RELAY_3'])
    
    shiftRegister2Buffers = shiftRegister2Buffers & ~(frontPanelLED1['BAS_ACTIVE_LED'])                                
    for zone in range(1, NUM_ZONES + 1):
        if zoneIsActive[zone] == 1 and zoneIsActiveType[zone] == 'BAS':
            shiftRegister2Buffers = shiftRegister2Buffers | frontPanelLED1['BAS_ACTIVE_LED']
            shiftRegister1Buffers = shiftRegister1Buffers | relayBuzzer['RELAY_3']

    shiftRegister3Buffers = shiftRegister3Buffers & ~(frontPanelLED2['FAS_ACTIVE_LED'])                                
    for zone in range(1, NUM_ZONES + 1):
        if zoneIsActive[zone] == 1 and zoneIsActiveType[zone] == 'FAS':
            shiftRegister3Buffers = shiftRegister3Buffers | frontPanelLED2['FAS_ACTIVE_LED']    #Done
            shiftRegister1Buffers = shiftRegister1Buffers | relayBuzzer['RELAY_3']

    for zone in range(1, NUM_ZONES + 1):
        if zoneIsActive[zone] == 1 and zoneIsActiveType[zone] == 'BACS':
            shiftRegister1Buffers = shiftRegister1Buffers | relayBuzzer['RELAY_3']

    for zone in range(1, NUM_ZONES + 1):
        if zoneIsActive[zone] == 1 and zoneIsActiveType[zone] == 'TIME_LOCK':
            shiftRegister1Buffers = shiftRegister1Buffers | relayBuzzer['RELAY_3']

    shiftRegister1Buffers = shiftRegister1Buffers & ~(relayBuzzer['RELAY_1'])
    
    shiftRegister3Buffers = shiftRegister3Buffers & ~(frontPanelLED2['CCTV_DISCONNECTED_LED'])                                		
    if any(element == 1 for element in zoneIsCamDisconnected):				        #Done
        shiftRegister3Buffers = shiftRegister3Buffers | frontPanelLED2['CCTV_DISCONNECTED_LED']
        shiftRegister1Buffers = shiftRegister1Buffers | relayBuzzer['RELAY_2']

    shiftRegister2Buffers = shiftRegister2Buffers & ~(frontPanelLED1['CCTV_TAMPER_LED'])        
    if any(element == 1 for element in zoneIsCamTamper):
        shiftRegister2Buffers = shiftRegister2Buffers | frontPanelLED1['CCTV_TAMPER_LED']
        shiftRegister1Buffers = shiftRegister1Buffers | relayBuzzer['RELAY_2']


    if zoneIsActiveType == 1:
        pass

    shiftRegister1Buffers = shiftRegister1Buffers & ~(relayBuzzer['LCD_BACK_ON'])                                		            		
    if LCDBackLightON == 1:
        shiftRegister1Buffers = shiftRegister1Buffers | relayBuzzer['LCD_BACK_ON']
        
    if duressActivate == 1:
        pass

    if duressActivate == 1:
        shiftRegister2Buffers = shiftRegister2Buffers | frontPanelLED2['NOT_IMPLEMENTED']        

    shiftRegister1Buffers = shiftRegister1Buffers & ~(relayBuzzer['BUZZER'])    
    if lowBatteryDetected == 1:
        if lowBatteryBuzzOn == 1:
            setup_mode_value = system_settings_db.retrieve_element("setup_mode")
            if setup_mode_value == "disabled":
                shiftRegister1Buffers = shiftRegister1Buffers | relayBuzzer['BUZZER']        
            

    if tamperPassActivated == 1:        


        global secondsCounterTB

        COUNTER_MAX_VAL_IN_SEC = 30
    
        if secondsCounterTB > COUNTER_MAX_VAL_IN_SEC:
            pass
        else:
            setup_mode_value = system_settings_db.retrieve_element("setup_mode")
            if setup_mode_value == "disabled":            
                shiftRegister1Buffers = shiftRegister1Buffers | relayBuzzer['BUZZER']        
            if toggleBit1Sec == 1:
                secondsCounterTB = secondsCounterTB + 1
    else:
         secondsCounterTB = 0

    global tick3MinTimer2
    global networkStatus
    global isLANStatusCheckOn 
    
    if tick3MinTimer2 == 1:
        tick3MinTimer2 = 0
        if isLANStatusCheckOn == 1:
            lanConnectChk()
        else:    
            networkStatus = 0
                
    shiftRegister4Buffers = shiftRegister4Buffers & ~(muxSelectionAndLED['4G_LTE_LED'])                                		                    

        
    if beepOn1Sec == 1:
        beepOn1Sec = 0
        buzzerOnTime3Sec = 1

    if tick1Sec2 == 1 and buzzerOnTime3Sec == 1:
        tick1Sec2 = 0

        counterTimer1Sec2 = counterTimer1Sec2 + 1
        if counterTimer1Sec2 > 2:
            counterTimer1Sec2 = 0
            buzzerOnTime3Sec = 0
            
    if buzzerOnTime3Sec == 1:
        setup_mode_value = system_settings_db.retrieve_element("setup_mode")
        if setup_mode_value == "disabled":
            shiftRegister1Buffers = shiftRegister1Buffers | relayBuzzer['BUZZER']        

    global zoneFaultBuzzerOn
    global tick1Sec3
    global buzzerOnTime3Sec1
    global counterTimer1Sec3
    
    if zoneFaultBuzzerOn == 1:
        zoneFaultBuzzerOn = 0
        buzzerOnTime3Sec1 = 1

    if tick1Sec3 == 1 and buzzerOnTime3Sec1 == 1:
        tick1Sec3 = 0

        counterTimer1Sec3 = counterTimer1Sec3 + 1
        if counterTimer1Sec3 > 60:
            counterTimer1Sec3 = 0
            buzzerOnTime3Sec1 = 0
            
    if buzzerOnTime3Sec1 == 1:
        setup_mode_value = system_settings_db.retrieve_element("setup_mode")
        if setup_mode_value == "disabled":        
            shiftRegister1Buffers = shiftRegister1Buffers | relayBuzzer['BUZZER']        
    
    global statusbox_network
    
    shiftRegister4Buffers = shiftRegister4Buffers & ~(muxSelectionAndLED['NETWORK_LED'])                                		                
     
    cavli_database.get_service_provider()
    statusbox_network = cavli_database.get_service_provider()
    if statusbox_network != "NA":
                 shiftRegister4Buffers = shiftRegister4Buffers | muxSelectionAndLED['NETWORK_LED']
       
    
    if isLampTestACTIVATED == 1:
        shiftRegister1Buffers = shiftRegister1Buffers | relayBuzzer['REMOTE_LED1']
        shiftRegister4Buffers = shiftRegister4Buffers | muxSelectionAndLED['4G_LTE_LED']
        shiftRegister2Buffers = shiftRegister2Buffers | frontPanelLED1['CCTV_TAMPER_LED']
        shiftRegister3Buffers = shiftRegister3Buffers | frontPanelLED2['CCTV_DISCONNECTED_LED']
        shiftRegister3Buffers = shiftRegister3Buffers | frontPanelLED2['FAS_ACTIVE_LED']
        shiftRegister2Buffers = shiftRegister2Buffers | frontPanelLED1['BAS_ACTIVE_LED']
        shiftRegister2Buffers = shiftRegister2Buffers | frontPanelLED1['NVR_DVR_OFF_LED']
        shiftRegister4Buffers = shiftRegister4Buffers | muxSelectionAndLED['FAS_OFF_LED']
        shiftRegister3Buffers = shiftRegister3Buffers | frontPanelLED2['BACS_OFF_LED']        
        shiftRegister3Buffers = shiftRegister3Buffers | frontPanelLED2['BAS_OFF_LED']
        shiftRegister2Buffers = shiftRegister2Buffers | frontPanelLED1['TIME_LOCK_OFF_LED']
        shiftRegister2Buffers = shiftRegister2Buffers | frontPanelLED1['FAS_FAULT_LED']
        shiftRegister4Buffers = shiftRegister4Buffers | muxSelectionAndLED['BACS_FAULT_LED']
        shiftRegister2Buffers |= frontPanelLED1['BAS_FAULT_LED']
        shiftRegister3Buffers = shiftRegister3Buffers | frontPanelLED2['CCTV_HDD_ERROR_LED']
        shiftRegister1Buffers = shiftRegister1Buffers | relayBuzzer['LCD_BACK_ON']
        shiftRegister3Buffers = shiftRegister3Buffers | frontPanelLED2['BAT_ON_LED']
        shiftRegister2Buffers |= frontPanelLED1['TIME_LOCK_FAULT_LED']

        shiftRegister4Buffers = shiftRegister4Buffers | muxSelectionAndLED['NETWORK_LED']

    if isHooterTestACTIVATED == 1:
        shiftRegister1Buffers = shiftRegister1Buffers | relayBuzzer['REMOTE_BUZZER']
        shiftRegister1Buffers = shiftRegister1Buffers | relayBuzzer['BUZZER']

    if isRelayTestACTIVATED == 1:
        shiftRegister1Buffers = shiftRegister1Buffers | relayBuzzer['RELAY_1']
        shiftRegister1Buffers = shiftRegister1Buffers | relayBuzzer['RELAY_2']
        shiftRegister1Buffers = shiftRegister1Buffers | relayBuzzer['RELAY_3']



def keypadScanningMultiNumKeyWithDot(maxRANGE=None, rowPOS=None, buffer_clear=None):    
    
    KEY_1 = [' ','1','#','.','+']
    KEY_2 = [' ','2','#','.','+']
    KEY_3 = [' ','3','#','.','+']
    KEY_4 = [' ','4','#','.','+']
    KEY_5 = [' ','5','#','.','+']
    KEY_6 = [' ','6','#','.','+']
    KEY_7 = [' ','7','#','.','+']
    KEY_8 = [' ','8','#','.','+']
    KEY_9 = [' ','9','#','.','+']
    KEY_0 = [' ','0','#','.','+']

    MAX_KEY = 4 # Range 0-1
    
    global keyPos 
    global changeinPos
    global keyInputMultiMode
    global mutiKeyInput
    global phoneNumberBuff 
    global keypressed
    global numKeyPressedHist
    global numberCounter

    if keypressed == "B":
        keypressed = None
        keyPos = keyPos + 1
        if keyPos > maxRANGE: # 15 [1-16]
            keyPos = 0
        if changeinPos == 1:
            changeinPos = 0
            mutiKeyInput = 0
        elif changeinPos == 0:
            changeinPos = 1
            mutiKeyInput = 0
    
    if keypressed == "1":
        keypressed = None
        mutiKeyInput = mutiKeyInput + 1
        if mutiKeyInput > MAX_KEY:
            mutiKeyInput = 0
        phoneNumberBuff[rowPOS][keyPos] = KEY_1[mutiKeyInput]
    elif keypressed == "2":
        keypressed = None
        mutiKeyInput = mutiKeyInput + 1
        if mutiKeyInput > MAX_KEY:
            mutiKeyInput = 0
        phoneNumberBuff[rowPOS][keyPos] = KEY_2[mutiKeyInput]
    elif keypressed == "3":
        keypressed = None
        mutiKeyInput = mutiKeyInput + 1
        if mutiKeyInput > MAX_KEY:
            mutiKeyInput = 0
        phoneNumberBuff[rowPOS][keyPos] = KEY_3[mutiKeyInput]            
    elif keypressed == "4":
        keypressed = None
        mutiKeyInput = mutiKeyInput + 1
        if mutiKeyInput > MAX_KEY:
            mutiKeyInput = 0
        phoneNumberBuff[rowPOS][keyPos] = KEY_4[mutiKeyInput]            
    elif keypressed == "5":
        keypressed = None
        mutiKeyInput = mutiKeyInput + 1
        if mutiKeyInput > MAX_KEY:
            mutiKeyInput = 0
        phoneNumberBuff[rowPOS][keyPos] = KEY_5[mutiKeyInput]            
    elif keypressed == "6":
        keypressed = None
        mutiKeyInput = mutiKeyInput + 1
        if mutiKeyInput > MAX_KEY:
            mutiKeyInput = 0
        phoneNumberBuff[rowPOS][keyPos] = KEY_6[mutiKeyInput]            
    elif keypressed == "7":
        keypressed = None
        mutiKeyInput = mutiKeyInput + 1
        if mutiKeyInput > MAX_KEY:
            mutiKeyInput = 0
        phoneNumberBuff[rowPOS][keyPos] = KEY_7[mutiKeyInput]            
    elif keypressed == "8":
        keypressed = None
        mutiKeyInput = mutiKeyInput + 1
        if mutiKeyInput > MAX_KEY:
            mutiKeyInput = 0
        phoneNumberBuff[rowPOS][keyPos] = KEY_8[mutiKeyInput]            
    elif keypressed == "9":
        keypressed = None
        mutiKeyInput = mutiKeyInput + 1
        if mutiKeyInput > MAX_KEY:
            mutiKeyInput = 0
        phoneNumberBuff[rowPOS][keyPos] = KEY_9[mutiKeyInput]            
    elif keypressed == "0":
        keypressed = None
        mutiKeyInput = mutiKeyInput + 1
        if mutiKeyInput > MAX_KEY:
            mutiKeyInput = 0
        phoneNumberBuff[rowPOS][keyPos] = KEY_0[mutiKeyInput]            

    if buffer_clear == 'clear':
        buffer_clear = None
        keypressed = None
        mutiKeyInput = 0
        keyPos = 0
        for index in range(0,16,1):
            phoneNumberBuff[rowPOS][index] = ' '
        rowPOS = 0
        keyPos = 0
    
    if keypressed == "C":
        keypressed = None
        for index in range(0,16,1):
            phoneNumberBuff[rowPOS][index] = ' '
        rowPOS = 0
        keyPos = 0
        lcd.clear()
        lcd.home()       


numKeyPressedHist = 0
numberCounter = 0

def keypadScanning(digitMax=None, valueRangeINIT=None, valueRangeMAX=None, valueRangeMIN=None, buffer_clear=None):
    global keypressed
    global numKeyPressedHist
    global numberCounter
  
    if keypressed == "1":
        keypressed = None
        numKeyPressedPresent = 1
        if numberCounter < digitMax:
            numberCounter = numberCounter + 1
            temp = numKeyPressedHist
            numKeyPressedHist = numKeyPressedPresent + (numKeyPressedHist * 10)
            if numKeyPressedHist > valueRangeMAX or numKeyPressedHist < valueRangeMIN:
                 numKeyPressedHist = temp
    elif keypressed == "2":
        keypressed = None
        numKeyPressedPresent = 2
        if numberCounter < digitMax:
            numberCounter = numberCounter + 1
            temp = numKeyPressedHist
            numKeyPressedHist = numKeyPressedPresent + (numKeyPressedHist * 10)
            if numKeyPressedHist > valueRangeMAX or numKeyPressedHist < valueRangeMIN:
                 numKeyPressedHist = temp            
    elif keypressed == "3":
        keypressed = None
        numKeyPressedPresent = 3
        if numberCounter < digitMax:
            numberCounter = numberCounter + 1
            temp = numKeyPressedHist            
            numKeyPressedHist = numKeyPressedPresent + (numKeyPressedHist * 10)
            if numKeyPressedHist > valueRangeMAX or numKeyPressedHist < valueRangeMIN:
                 numKeyPressedHist = temp
    elif keypressed == "4":
        keypressed = None
        numKeyPressedPresent = 4
        if numberCounter < digitMax:
            numberCounter = numberCounter + 1
            temp = numKeyPressedHist
            numKeyPressedHist = numKeyPressedPresent + (numKeyPressedHist * 10)
            if numKeyPressedHist > valueRangeMAX or numKeyPressedHist < valueRangeMIN:
                 numKeyPressedHist = temp
    elif keypressed == "5":
        keypressed = None
        numKeyPressedPresent = 5
        if numberCounter < digitMax:
            numberCounter = numberCounter + 1
            temp = numKeyPressedHist
            numKeyPressedHist = numKeyPressedPresent + (numKeyPressedHist * 10)
            if numKeyPressedHist > valueRangeMAX or numKeyPressedHist < valueRangeMIN:
                 numKeyPressedHist = temp
    elif keypressed == "6":
        keypressed = None
        numKeyPressedPresent = 6
        if numberCounter < digitMax:
            numberCounter = numberCounter + 1
            temp = numKeyPressedHist
            numKeyPressedHist = numKeyPressedPresent + (numKeyPressedHist * 10)
            if numKeyPressedHist > valueRangeMAX or numKeyPressedHist < valueRangeMIN:
                 numKeyPressedHist = temp
    elif keypressed == "7":
        keypressed = None
        numKeyPressedPresent = 7
        if numberCounter < digitMax:
            numberCounter = numberCounter + 1
            temp = numKeyPressedHist
            numKeyPressedHist = numKeyPressedPresent + (numKeyPressedHist * 10)
            if numKeyPressedHist > valueRangeMAX or numKeyPressedHist < valueRangeMIN:
                 numKeyPressedHist = temp
    elif keypressed == "8":
        keypressed = None
        numKeyPressedPresent = 8
        if numberCounter < digitMax:
            numberCounter = numberCounter + 1
            temp = numKeyPressedHist
            numKeyPressedHist = numKeyPressedPresent + (numKeyPressedHist * 10)
            if numKeyPressedHist > valueRangeMAX or numKeyPressedHist < valueRangeMIN:
                 numKeyPressedHist = temp
    elif keypressed == "9":
        keypressed = None
        numKeyPressedPresent = 9
        if numberCounter < digitMax:
            numberCounter = numberCounter + 1
            temp = numKeyPressedHist
            numKeyPressedHist = numKeyPressedPresent + (numKeyPressedHist * 10)
            if numKeyPressedHist > valueRangeMAX or numKeyPressedHist < valueRangeMIN:
                 numKeyPressedHist = temp
    elif keypressed == "0":
        keypressed = None
        numKeyPressedPresent = 0
        if numberCounter < digitMax:
            numberCounter = numberCounter + 1
            temp = numKeyPressedHist
            numKeyPressedHist = numKeyPressedPresent + (numKeyPressedHist * 10)
            if numKeyPressedHist > valueRangeMAX or numKeyPressedHist < valueRangeMIN:
                 numKeyPressedHist = temp
                 
    if keypressed == "C":
        keypressed = None
        numKeyPressedHist = 0
        numberCounter = 0
        lcd.clear()
        lcd.home()
        
    if buffer_clear == 'clear':
        buffer_clear = None
        numKeyPressedHist = 0
        numberCounter = 0
        
    if numKeyPressedHist > valueRangeMAX or numKeyPressedHist < valueRangeMIN:
        return valueRangeINIT
    else:
        return numKeyPressedHist


def numeric2Asterisk(value=None):

    DIGIT_0 = '*'
    DIGIT_10 = '**'
    DIGIT_100 = '***'
    DIGIT_1000 = '****'
    DIGIT_10000 = '*****'
    DIGIT_100000 = '******'
    DIGIT_1000000 = '*******'
    DIGIT_10000000 = '********'
    DIGIT_100000000 = '*********'
    DIGIT_1000000000 = '**********'
    DIGIT_10000000000 = '***********'

    if value > 0 and value <= 9:
        return DIGIT_0
    elif value >= 10 and value <= 99:
        return DIGIT_10
    elif value >= 100 and value <= 999:
        return DIGIT_100
    elif value >= 1000 and value <= 9999:
        return DIGIT_1000
    elif value >= 10000 and value <= 99999:
        return DIGIT_10000
    elif value >= 100000 and value <= 999999:
        return DIGIT_100000
    elif value >= 1000000 and value <= 9999999:
        return DIGIT_1000000
    elif value >= 10000000 and value <= 99999999:
        return DIGIT_10000000
    elif value >= 100000000 and value <= 999999999:
        return DIGIT_100000000
    elif value >= 1000000000 and value <= 9999999999:
        return DIGIT_1000000000
    elif value >= 10000000000 and value <= 99999999999:
        return DIGIT_10000000000    
    else:
        return ' '

def returnToDisplayScan():

    global menuSubPasswordState
    global menuCurrentPos
    global GuserSetState
    global menuSubState
    global menuSubSubState
    global GmainStateState
    global menuMainState
    global menuCodeSelectState
    global GtaskManagerSTATE
    global zoneProgSetMenu
    menuSubPasswordState = 0
    menuCurrentPos = 0
    GuserSetState = 0 
    menuSubState = 0
    menuSubSubState = 0
    GmainStateState = 0
    menuMainState = 0
    menuCodeSelectState = 0
    GtaskManagerSTATE = 0
    zoneProgSetMenu = 0
    exitMenuAuto(1)
    
    keypadScanning(0,0,0,0,'clear')
    
    lcd.clear()
    lcd.home()


brandName = ""
def brandNameRead():
  global brandName
  log = open("/home/pi/Test3/Brand.txt","r")
  brandName = log.read()
  log.flush()
  log.close()

branchName = ""
# noinspection PyPep8Naming
def readBranchName():
    global branchName
    log = open("/home/pi/Test3/Branch.txt","r")
    branchName = log.read()
    log.flush()
    log.close()


rtcOptions = [0,0,0,0,0,0,0]
rtcParam = {'HOUR':0, 'MINUTE':1,'SECOND':2,'DAY':3, 'MONTH':4,'YEAR':5, 'MARKER':6}

def realTimeClock():
    
        global rtcOptions
        global rtcParam

        try:
            rtcOptions[rtcParam['HOUR']] = ds1307._read_hours()
        except ValueError:
           rtcOptions[rtcParam['HOUR']] = 0
        except IOError:
            rtcOptions[rtcParam['HOUR']] = 0
            
        try:
            rtcOptions[rtcParam['MINUTE']] = ds1307._read_minutes()
        except ValueError:
            rtcOptions[rtcParam['MINUTE']] = 0            
        except IOError:
            rtcOptions[rtcParam['MINUTE']] = 0

        try:
            rtcOptions[rtcParam['SECOND']] = ds1307._read_seconds()
        except ValueError:
            rtcOptions[rtcParam['SECOND']] = 0           
        except IOError:
            rtcOptions[rtcParam['SECOND']] = 0
        
        try:
            rtcOptions[rtcParam['DAY']] = ds1307._read_date()
        except ValueError:
            rtcOptions[rtcParam['DAY']] = 0            
        except IOError:
            rtcOptions[rtcParam['DAY']] = 0
        
        try:
            rtcOptions[rtcParam['MONTH']] = ds1307._read_month()
        except ValueError:
            rtcOptions[rtcParam['MONTH']] = 0            
        except IOError:
            rtcOptions[rtcParam['MONTH']] = 0
        
        try:        
            rtcOptions[rtcParam['YEAR']] = ds1307._read_year()
        except ValueError:
            rtcOptions[rtcParam['YEAR']] = 0
        except IOError:
            rtcOptions[rtcParam['YEAR']] = 0

        if rtcOptions[rtcParam['HOUR']] >= 12:
            rtcOptions[rtcParam['MARKER']] = 1
        else:
            rtcOptions[rtcParam['MARKER']] = 0

startMenuExitCountSchd = 0


def menuPositionUpDnWithoutClear(DownMIN, UpMAX):
    global keypressed
    global menuCurrentPos
    
    if keypressed == "@":
        keypressed = None
        lcd.home()
        if menuCurrentPos < UpMAX+1:
            menuCurrentPos = menuCurrentPos + 1
            if menuCurrentPos > UpMAX:
                menuCurrentPos = UpMAX
    elif keypressed == "*":
        keypressed = None
        lcd.home()
        if menuCurrentPos > DownMIN:
            menuCurrentPos = menuCurrentPos - 1
            if menuCurrentPos < DownMIN:
                menuCurrentPos = DownMIN
    return menuCurrentPos            



def exitMenuAuto(rstCountSchd=None):
    ''' Auto exit from programming menu after 10 minutes of in activity. Pass 1 to Reset Values. '''
    global tick10Min
    global reset10MinCounter

    global startMenuExitCountSchd

    if rstCountSchd == 1:
        rstCountSchd = 0
        startMenuExitCountSchd = 0
        reset10MinCounter = 0
        tick10Min = 0

    if startMenuExitCountSchd == 0 and reset10MinCounter == 0:
        startMenuExitCountSchd = 1
        reset10MinCounter = 1
        
    if tick10Min == 1:
        tick10Min = 0
        
        global GmainStateState
        global menuCurrentPos
        global GuserSetState
        global menuMainState
        global menuCodeSelectState

        menuCodeSelectState = 0
        GmainStateState = 0
        menuCurrentPos = 0
        GuserSetState = 0
        menuMainState = 0

        startMenuExitCountSchd = 0
        reset10MinCounter = 0

        lcd.clear()
        lcd.home()


def menuPositionUpDn(DownMIN, UpMAX):
    global keypressed
    global menuCurrentPos
    
    if keypressed == "@":
        keypressed = None
        lcd.clear()
        lcd.home()
        if menuCurrentPos < UpMAX+1:
            menuCurrentPos = menuCurrentPos + 1
            if menuCurrentPos > UpMAX:
                menuCurrentPos = UpMAX
    elif keypressed == "*":
        keypressed = None
        lcd.clear()
        lcd.home()
        if menuCurrentPos > DownMIN:
            menuCurrentPos = menuCurrentPos - 1
            if menuCurrentPos < DownMIN:
                menuCurrentPos = DownMIN
    return menuCurrentPos            

#--------------------------------------------------------------------------------
def keypadScanningMultiKey(maxRANGE=None, rowPOS=None, buffer_clear=None):    
    
    KEY_1 = [' ','1','A','B','C']
    KEY_2 = [' ','2','D','E','F']
    KEY_3 = [' ','3','G','H','I']
    KEY_4 = [' ','4','J','K','L']
    KEY_5 = [' ','5','M','N','O']
    KEY_6 = [' ','6','P','Q','R']
    KEY_7 = [' ','7','S','T','U']
    KEY_8 = [' ','8','V','W','X']
    KEY_9 = [' ','9','Y','Z','@']
    KEY_0 = [' ','0','-','/','_']

    MAX_KEY = 4 # Range 0-3
    
    global keyPos 
    global changeinPos
    global keyInputMultiMode
    global mutiKeyInput
    global branchNameAddressBuffer
    global keypressed
    global numKeyPressedHist
    global numberCounter

    if keypressed == "B":
        keypressed = None
        keyPos = keyPos + 1
        if keyPos > maxRANGE: # 15 [1-16]
            keyPos = 0
        if changeinPos == 1:
            changeinPos = 0
            mutiKeyInput = 0
        elif changeinPos == 0:
            changeinPos = 1
            mutiKeyInput = 0
    
    if keypressed == "1":
        keypressed = None
        mutiKeyInput = mutiKeyInput + 1
        if mutiKeyInput > MAX_KEY:
            mutiKeyInput = 0
        branchNameAddressBuffer[rowPOS][keyPos] = KEY_1[mutiKeyInput]
    elif keypressed == "2":
        keypressed = None
        mutiKeyInput = mutiKeyInput + 1
        if mutiKeyInput > MAX_KEY:
            mutiKeyInput = 0
        branchNameAddressBuffer[rowPOS][keyPos] = KEY_2[mutiKeyInput]
    elif keypressed == "3":
        keypressed = None
        mutiKeyInput = mutiKeyInput + 1
        if mutiKeyInput > MAX_KEY:
            mutiKeyInput = 0
        branchNameAddressBuffer[rowPOS][keyPos] = KEY_3[mutiKeyInput]            
    elif keypressed == "4":
        keypressed = None
        mutiKeyInput = mutiKeyInput + 1
        if mutiKeyInput > MAX_KEY:
            mutiKeyInput = 0
        branchNameAddressBuffer[rowPOS][keyPos] = KEY_4[mutiKeyInput]            
    elif keypressed == "5":
        keypressed = None
        mutiKeyInput = mutiKeyInput + 1
        if mutiKeyInput > MAX_KEY:
            mutiKeyInput = 0
        branchNameAddressBuffer[rowPOS][keyPos] = KEY_5[mutiKeyInput]            
    elif keypressed == "6":
        keypressed = None
        mutiKeyInput = mutiKeyInput + 1
        if mutiKeyInput > MAX_KEY:
            mutiKeyInput = 0
        branchNameAddressBuffer[rowPOS][keyPos] = KEY_6[mutiKeyInput]            
    elif keypressed == "7":
        keypressed = None
        mutiKeyInput = mutiKeyInput + 1
        if mutiKeyInput > MAX_KEY:
            mutiKeyInput = 0
        branchNameAddressBuffer[rowPOS][keyPos] = KEY_7[mutiKeyInput]            
    elif keypressed == "8":
        keypressed = None
        mutiKeyInput = mutiKeyInput + 1
        if mutiKeyInput > MAX_KEY:
            mutiKeyInput = 0
        branchNameAddressBuffer[rowPOS][keyPos] = KEY_8[mutiKeyInput]            
    elif keypressed == "9":
        keypressed = None
        mutiKeyInput = mutiKeyInput + 1
        if mutiKeyInput > MAX_KEY:
            mutiKeyInput = 0
        branchNameAddressBuffer[rowPOS][keyPos] = KEY_9[mutiKeyInput]            
    elif keypressed == "0":
        keypressed = None
        mutiKeyInput = mutiKeyInput + 1
        if mutiKeyInput > MAX_KEY:
            mutiKeyInput = 0
        branchNameAddressBuffer[rowPOS][keyPos] = KEY_0[mutiKeyInput]            

    if keypressed == "C":
        keypressed = None
        for index in range(0,16,1):
            branchNameAddressBuffer[rowPOS][index] = ' '
        rowPOS = 0
        keyPos = 0
        lcd.clear()
        lcd.home()


def keypadScanningMultiKeyWithSmallCaps(maxRANGE=None, rowPOS=None, buffer_clear=None):    
    
    KEY_1 = [' ','1','A','a','B','b','C','c']
    KEY_2 = [' ','2','D','d','E','e','F','f']
    KEY_3 = [' ','3','G','g','H','h','I','i']
    KEY_4 = [' ','4','J','j','K','k','L','l']
    KEY_5 = [' ','5','M','m','N','n','O','o']
    KEY_6 = [' ','6','P','p','Q','q','R','r']
    KEY_7 = [' ','7','S','s','T','t','U','u']
    KEY_8 = [' ','8','V','v','W','w','X','x']
    KEY_9 = [' ','9','Y','y','Z','z','@','*']
    KEY_0 = [' ','0','-','/','_','#','+','#']

    MAX_KEY = 7 # Range 0-3
    
    global keyPos 
    global changeinPos
    global keyInputMultiMode
    global mutiKeyInput
    global branchNameAddressBuffer
    global keypressed
    global numKeyPressedHist
    global numberCounter

    if keypressed == "B":
        keypressed = None
        keyPos = keyPos + 1
        if keyPos > maxRANGE: # 15 [1-16]
            keyPos = 0
        if changeinPos == 1:
            changeinPos = 0
            mutiKeyInput = 0
        elif changeinPos == 0:
            changeinPos = 1
            mutiKeyInput = 0
    
    if keypressed == "1":
        keypressed = None
        mutiKeyInput = mutiKeyInput + 1
        if mutiKeyInput > MAX_KEY:
            mutiKeyInput = 0
        branchNameAddressBuffer[rowPOS][keyPos] = KEY_1[mutiKeyInput]
    elif keypressed == "2":
        keypressed = None
        mutiKeyInput = mutiKeyInput + 1
        if mutiKeyInput > MAX_KEY:
            mutiKeyInput = 0
        branchNameAddressBuffer[rowPOS][keyPos] = KEY_2[mutiKeyInput]
    elif keypressed == "3":
        keypressed = None
        mutiKeyInput = mutiKeyInput + 1
        if mutiKeyInput > MAX_KEY:
            mutiKeyInput = 0
        branchNameAddressBuffer[rowPOS][keyPos] = KEY_3[mutiKeyInput]            
    elif keypressed == "4":
        keypressed = None
        mutiKeyInput = mutiKeyInput + 1
        if mutiKeyInput > MAX_KEY:
            mutiKeyInput = 0
        branchNameAddressBuffer[rowPOS][keyPos] = KEY_4[mutiKeyInput]            
    elif keypressed == "5":
        keypressed = None
        mutiKeyInput = mutiKeyInput + 1
        if mutiKeyInput > MAX_KEY:
            mutiKeyInput = 0
        branchNameAddressBuffer[rowPOS][keyPos] = KEY_5[mutiKeyInput]            
    elif keypressed == "6":
        keypressed = None
        mutiKeyInput = mutiKeyInput + 1
        if mutiKeyInput > MAX_KEY:
            mutiKeyInput = 0
        branchNameAddressBuffer[rowPOS][keyPos] = KEY_6[mutiKeyInput]            
    elif keypressed == "7":
        keypressed = None
        mutiKeyInput = mutiKeyInput + 1
        if mutiKeyInput > MAX_KEY:
            mutiKeyInput = 0
        branchNameAddressBuffer[rowPOS][keyPos] = KEY_7[mutiKeyInput]            
    elif keypressed == "8":
        keypressed = None
        mutiKeyInput = mutiKeyInput + 1
        if mutiKeyInput > MAX_KEY:
            mutiKeyInput = 0
        branchNameAddressBuffer[rowPOS][keyPos] = KEY_8[mutiKeyInput]            
    elif keypressed == "9":
        keypressed = None
        mutiKeyInput = mutiKeyInput + 1
        if mutiKeyInput > MAX_KEY:
            mutiKeyInput = 0
        branchNameAddressBuffer[rowPOS][keyPos] = KEY_9[mutiKeyInput]            
    elif keypressed == "0":
        keypressed = None
        mutiKeyInput = mutiKeyInput + 1
        if mutiKeyInput > MAX_KEY:
            mutiKeyInput = 0
        branchNameAddressBuffer[rowPOS][keyPos] = KEY_0[mutiKeyInput]            

    if keypressed == "C":
        keypressed = None
        for index in range(0,16,1):
            branchNameAddressBuffer[rowPOS][index] = ' '
        rowPOS = 0
        keyPos = 0
        lcd.clear()
        lcd.home() 
#----------------------------------------------------------------------------------

def keypadScanningMultiKey_crediential(maxRANGE=None, rowPOS=None, buffer_clear=None):    

    KEY_1 = [' ','1','A','a','B','b','C','c']
    KEY_2 = [' ','2','D','d','E','e','F','f']
    KEY_3 = [' ','3','G','g','H','h','I','i']
    KEY_4 = [' ','4','J','j','K','k','L','l']
    KEY_5 = [' ','5','M','m','N','n','O','o']
    KEY_6 = [' ','6','P','p','Q','q','R','r']
    KEY_7 = [' ','7','S','s','T','t','U','u']
    KEY_8 = [' ','8','V','v','W','w','X','x']
    KEY_9 = [' ','9','Y','y','Z','z','@','*']
    KEY_0 = [' ','0','-','/','_','#','+','#']

    MAX_KEY = 7 # Range 0-7
    
    global keyPos 
    global changeinPos
    global keyInputMultiMode
    global mutiKeyInput
    global credientalsBuffer
    global keypressed
    global numKeyPressedHist
    global numberCounter

    if keypressed == "B":
        keypressed = None
        keyPos = keyPos + 1        
        if keyPos > maxRANGE: # 31 [1-32]
            keyPos = 0

        # If the key position is beyond 15, it's on the second line (line 1)
        if keyPos > 15:
            rowPOS = 1  # Set rowPOS to 1 for the second line
        else:
            rowPOS = 0  # Set rowPOS to 0 for the first line
        
        if changeinPos == 1:
            changeinPos = 0
            mutiKeyInput = 0
        elif changeinPos == 0:
            changeinPos = 1
            mutiKeyInput = 0
    
    if keypressed == "1":
        keypressed = None
        mutiKeyInput = mutiKeyInput + 1
        if mutiKeyInput > MAX_KEY:
            mutiKeyInput = 0
        credientalsBuffer[rowPOS][keyPos] = KEY_1[mutiKeyInput]
    elif keypressed == "2":
        keypressed = None
        mutiKeyInput = mutiKeyInput + 1
        if mutiKeyInput > MAX_KEY:
            mutiKeyInput = 0
        credientalsBuffer[rowPOS][keyPos] = KEY_2[mutiKeyInput]
    elif keypressed == "3":
        keypressed = None
        mutiKeyInput = mutiKeyInput + 1
        if mutiKeyInput > MAX_KEY:
            mutiKeyInput = 0
        credientalsBuffer[rowPOS][keyPos] = KEY_3[mutiKeyInput]            
    elif keypressed == "4":
        keypressed = None
        mutiKeyInput = mutiKeyInput + 1
        if mutiKeyInput > MAX_KEY:
            mutiKeyInput = 0
        credientalsBuffer[rowPOS][keyPos] = KEY_4[mutiKeyInput]            
    elif keypressed == "5":
        keypressed = None
        mutiKeyInput = mutiKeyInput + 1
        if mutiKeyInput > MAX_KEY:
            mutiKeyInput = 0
        credientalsBuffer[rowPOS][keyPos] = KEY_5[mutiKeyInput]            
    elif keypressed == "6":
        keypressed = None
        mutiKeyInput = mutiKeyInput + 1
        if mutiKeyInput > MAX_KEY:
            mutiKeyInput = 0
        credientalsBuffer[rowPOS][keyPos] = KEY_6[mutiKeyInput]            
    elif keypressed == "7":
        keypressed = None
        mutiKeyInput = mutiKeyInput + 1
        if mutiKeyInput > MAX_KEY:
            mutiKeyInput = 0
        credientalsBuffer[rowPOS][keyPos] = KEY_7[mutiKeyInput]            
    elif keypressed == "8":
        keypressed = None
        mutiKeyInput = mutiKeyInput + 1
        if mutiKeyInput > MAX_KEY:
            mutiKeyInput = 0
        credientalsBuffer[rowPOS][keyPos] = KEY_8[mutiKeyInput]            
    elif keypressed == "9":
        keypressed = None
        mutiKeyInput = mutiKeyInput + 1
        if mutiKeyInput > MAX_KEY:
            mutiKeyInput = 0
        credientalsBuffer[rowPOS][keyPos] = KEY_9[mutiKeyInput]            
    elif keypressed == "0":
        keypressed = None
        mutiKeyInput = mutiKeyInput + 1
        if mutiKeyInput > MAX_KEY:
            mutiKeyInput = 0
        credientalsBuffer[rowPOS][keyPos] = KEY_0[mutiKeyInput]            

    if keypressed == "C":
        keypressed = None
        for index in range(0,32,1):
            credientalsBuffer[rowPOS][index] = ' '
        rowPOS = 0
        keyPos = 0
        lcd.clear()
        lcd.home()

#==========================================================================================

def resetToDefault():

    global adminPass
    global servicePass
    keyDetect = 123321
    adminPass[1] = int(keyDetect) 
    adminPasswordFileRW('write')
    servicePass[1] = int(keyDetect) 
    keyDetect = 123321
    servicePasswordFileRW('write')

    global lowBatSet
    lowBatSet[1] = 0
    lowBatSet[3] = 60
    lowBatFileRW('write')

    lowBatteryBuzzOn = 0
    log = open("/home/pi/Test3/lowbatbuzzer.txt","w")
    log.write(str(lowBatteryBuzzOn))
    log.flush()
    log.close()

    global zoneSettings

    #Zone 1
    zoneSettings[0] = 0
    zoneSettings[1] = 0
    zoneSettings[2] = 1
    #Zone 2
    zoneSettings[3] = 0
    zoneSettings[4] = 0
    zoneSettings[5] = 1
    #Zone 3
    zoneSettings[6] = 0
    zoneSettings[7] = 0
    zoneSettings[8] = 2
    #Zone 4
    zoneSettings[9] = 0
    zoneSettings[10] = 0
    zoneSettings[11] = 2
    #Zone 5
    zoneSettings[12] = 0
    zoneSettings[13] = 0
    zoneSettings[14] = 3
    #Zone 6
    zoneSettings[15] = 0
    zoneSettings[16] = 0
    zoneSettings[17] = 4
    #Zone 7
    zoneSettings[18] = 0
    zoneSettings[19] = 0
    zoneSettings[20] = 5
    #Zone 8
    zoneSettings[21] = 0
    zoneSettings[22] = 0
    zoneSettings[23] = 5
    #Zone 9    
    zoneSettings[24] = 0
    zoneSettings[25] = 0
    zoneSettings[26] = 1
    #Zone 10    
    zoneSettings[27] = 0
    zoneSettings[28] = 0
    zoneSettings[29] = 1
    #Zone 11    
    zoneSettings[30] = 0
    zoneSettings[31] = 0            
    zoneSettings[32] = 2
    #Zone 12
    zoneSettings[33] = 0
    zoneSettings[34] = 0
    zoneSettings[35] = 2
    #Zone 13
    zoneSettings[36] = 0
    zoneSettings[37] = 0
    zoneSettings[38] = 3
    #Zone 14    
    zoneSettings[39] = 0
    zoneSettings[40] = 0
    zoneSettings[41] = 4
    #Zone 15    
    zoneSettings[42] = 0
    zoneSettings[43] = 0
    zoneSettings[44] = 5
    #Zone 16    
    zoneSettings[45] = 0
    zoneSettings[46] = 0
    zoneSettings[47] = 5

    zoneSettingsFileRW('write')

    global powerZoneSettings

    #Zone 1
    powerZoneSettings[0] = 0
    powerZoneSettings[1] = 0
    powerZoneSettings[2] = 1
    #Zone 2
    powerZoneSettings[3] = 0
    powerZoneSettings[4] = 0
    powerZoneSettings[5] = 2
    #Zone 3
    powerZoneSettings[6] = 0
    powerZoneSettings[7] = 0
    powerZoneSettings[8] = 3
    #Zone 4
    powerZoneSettings[9] = 0
    powerZoneSettings[10] = 0
    powerZoneSettings[11] = 4
    #Zone 5
    powerZoneSettings[12] = 0
    powerZoneSettings[13] = 0
    powerZoneSettings[14] = 5
    #Zone 6
    powerZoneSettings[15] = 0
    powerZoneSettings[16] = 0
    powerZoneSettings[17] = 5
    #Zone 7
    powerZoneSettings[18] = 0
    powerZoneSettings[19] = 0
    powerZoneSettings[20] = 5
    #Zone 8
    powerZoneSettings[21] = 0
    powerZoneSettings[22] = 0
    powerZoneSettings[23] = 5
    #Zone 9    
    powerZoneSettings[24] = 0
    powerZoneSettings[25] = 0
    powerZoneSettings[26] = 0
    #Zone 10    
    powerZoneSettings[27] = 0
    powerZoneSettings[28] = 0
    powerZoneSettings[29] = 0
    #Zone 11    
    powerZoneSettings[30] = 0
    powerZoneSettings[31] = 0            
    powerZoneSettings[32] = 0
    #Zone 12
    powerZoneSettings[33] = 0
    powerZoneSettings[34] = 0
    powerZoneSettings[35] = 0
    #Zone 13
    powerZoneSettings[36] = 0
    powerZoneSettings[37] = 0
    powerZoneSettings[38] = 0
    #Zone 14    
    powerZoneSettings[39] = 0
    powerZoneSettings[40] = 0
    powerZoneSettings[41] = 0
    #Zone 15    
    powerZoneSettings[42] = 0
    powerZoneSettings[43] = 0
    powerZoneSettings[44] = 0
    #Zone 16    
    powerZoneSettings[45] = 0
    powerZoneSettings[46] = 0
    powerZoneSettings[47] = 0

    powerZoneSettingsFileRW('write')
    
    network_settings.update_setting("e-SIM Enable/Disable", "True")
    network_settings.update_setting("Network Selection for e-SIM", "LTE")
    network_settings.update_setting("Enable/Disable GNSS", "True")
    network_settings.update_setting("Alert Types (SMS)", "Vibrate")
    network_settings.update_setting("Notification Schedule", "Every hour")

    network_settings.update_setting("Enable/Disable for Network LED Status", "True")
    network_settings.update_setting("Enable/Disable for Wireless LAN", "False")
    network_settings.update_setting("Enable/Disable IP Module", "False")
    network_settings.update_setting("Enable/Disable Static/dynamic", "dynamic")
    network_settings.update_setting("IPv4/IPv6 Selection", "IPv4")
    network_settings.update_setting("Set IP Address", "192.168.0.123")
    network_settings.update_setting("Set Port Number", "1881")
    network_settings.update_setting("Subnet mask", "255.255.255.0")
    network_settings.update_setting("Gateway", "192.168.0.1")
    network_settings.update_setting("DNS Setup", "Automatic")
    network_settings.update_setting("APN Settings", "internet")
    network_settings.update_setting("Network Test", "False")
    network_settings.update_setting("Enable/Disable GSM", "True")

    # Add or update network settings
    network_settings.update_setting("preferred_dns_server", "8.8.8.8")
    network_settings.update_setting("alternate_dns_server", "8.8.4.4")
    network_settings.update_setting("reset_to_dhcp", "True")
    

    system_settings_db.update_element("setup_mode", "enabled")
    
    system_settings_db.update_element("reset_to_default", "false")


def powerZoneSettingsFileRW(readWrite = None):

  #File Handling for Zone Settings
  global powerZoneSettings
  temp = []
  
  listTemp = [0,0,0,
        0,0,0,
        0,0,0,
        0,0,0,
        0,0,0,
        0,0,0,
        0,0,0,               
        0,0,0,
        0,0,0,
        0,0,0,
        0,0,0,
        0,0,0,
        0,0,0,
        0,0,0,
        0,0,0,                
        0,0,0]


  n = x = 0
  ROW_OFFSET = 0
  
  if readWrite == 'read':
    log = open("/home/pi/Test3/powerZoneSettings.txt","r")
    for line in log:
      listTemp[n] = line        
      n = n + 1        
    log.flush()
    log.close()
    for x in range(0,16+ROW_OFFSET):
        
      if x == 0: 
        temp = listTemp[x].split()
        powerZoneSettings[0] = int(temp[0])
        powerZoneSettings[1] = int(temp[1])
        powerZoneSettings[2] = int(temp[2])
        
      elif x == 1:
        temp = listTemp[x].split()
        powerZoneSettings[3] = int(temp[0])
        powerZoneSettings[4] = int(temp[1])
        powerZoneSettings[5] = int(temp[2])
        
      elif x == 2:
        temp = listTemp[x].split()
        powerZoneSettings[6] = int(temp[0])
        powerZoneSettings[7] = int(temp[1])
        powerZoneSettings[8] = int(temp[2])
        
      elif x == 3:
        temp = listTemp[x].split()
        powerZoneSettings[9] = int(temp[0])
        powerZoneSettings[10] = int(temp[1])
        powerZoneSettings[11] = int(temp[2])
        
      elif x == 4:
        temp = listTemp[x].split()
        powerZoneSettings[12] = int(temp[0])
        powerZoneSettings[13] = int(temp[1])
        powerZoneSettings[14] = int(temp[2])
        
      elif x == 5:
        temp = listTemp[x].split()
        powerZoneSettings[15] = int(temp[0])
        powerZoneSettings[16] = int(temp[1])
        powerZoneSettings[17] = int(temp[2])
        
      elif x == 6:
        temp = listTemp[x].split()
        powerZoneSettings[18] = int(temp[0])
        powerZoneSettings[19] = int(temp[1])
        powerZoneSettings[20] = int(temp[2])
        
      elif x == 7:
        temp = listTemp[x].split()
        powerZoneSettings[21] = int(temp[0])
        powerZoneSettings[22] = int(temp[1])
        powerZoneSettings[23] = int(temp[2])
        
      elif x == 8: 
        temp = listTemp[x].split()
        powerZoneSettings[24] = int(temp[0])
        powerZoneSettings[25] = int(temp[1])
        powerZoneSettings[26] = int(temp[2])
        
      elif x == 9:
        temp = listTemp[x].split()
        powerZoneSettings[27] = int(temp[0])
        powerZoneSettings[28] = int(temp[1])
        powerZoneSettings[29] = int(temp[2])
        
      elif x == 10:
        temp = listTemp[x].split()
        powerZoneSettings[30] = int(temp[0])
        powerZoneSettings[31] = int(temp[1])
        powerZoneSettings[32] = int(temp[2])
        
      elif x == 11:
        temp = listTemp[x].split()
        powerZoneSettings[33] = int(temp[0])
        powerZoneSettings[34] = int(temp[1])
        powerZoneSettings[35] = int(temp[2])
      elif x == 12:
        temp = listTemp[x].split()
        powerZoneSettings[36] = int(temp[0])
        powerZoneSettings[37] = int(temp[1])
        powerZoneSettings[38] = int(temp[2])
      elif x == 13:
        temp = listTemp[x].split()
        powerZoneSettings[39] = int(temp[0])
        powerZoneSettings[40] = int(temp[1])
        powerZoneSettings[41] = int(temp[2])
      elif x == 14:
        temp = listTemp[x].split()
        powerZoneSettings[42] = int(temp[0])
        powerZoneSettings[43] = int(temp[1])
        powerZoneSettings[44] = int(temp[2])
      elif x == 15:
        temp = listTemp[x].split()
        powerZoneSettings[45] = int(temp[0])
        powerZoneSettings[46] = int(temp[1])
        powerZoneSettings[47] = int(temp[2])
      
  elif readWrite == 'write':
    log = open("/home/pi/Test3/powerZoneSettings.txt","w")
    for x in range(0,16+ROW_OFFSET):
      if x == 0:
        log.write(str(powerZoneSettings[0]))
        log.write(str(" "))
        log.write(str(powerZoneSettings[1]))
        log.write(str(" "))
        log.write(str(powerZoneSettings[2]))        
        log.write("\n")
      elif x == 1:
        log.write(str(powerZoneSettings[3]))
        log.write(str(" "))
        log.write(str(powerZoneSettings[4]))
        log.write(str(" "))
        log.write(str(powerZoneSettings[5]))        
        log.write("\n")
      elif x == 2:
        log.write(str(powerZoneSettings[6]))
        log.write(str(" "))
        log.write(str(powerZoneSettings[7]))
        log.write(str(" "))
        log.write(str(powerZoneSettings[8]))        
        log.write("\n")
      elif x == 3:
        log.write(str(powerZoneSettings[9]))
        log.write(str(" "))
        log.write(str(powerZoneSettings[10]))
        log.write(str(" "))
        log.write(str(powerZoneSettings[11]))        
        log.write("\n")
      elif x == 4:
        log.write(str(powerZoneSettings[12]))
        log.write(str(" "))
        log.write(str(powerZoneSettings[13]))
        log.write(str(" "))
        log.write(str(powerZoneSettings[14]))        
        log.write("\n")
      elif x == 5:
        log.write(str(powerZoneSettings[15]))
        log.write(str(" "))
        log.write(str(powerZoneSettings[16]))
        log.write(str(" "))
        log.write(str(powerZoneSettings[17]))        
        log.write("\n")
      elif x == 6:
        log.write(str(powerZoneSettings[18]))
        log.write(str(" "))
        log.write(str(powerZoneSettings[19]))
        log.write(str(" "))
        log.write(str(powerZoneSettings[20]))        
        log.write("\n")
      elif x == 7:
        log.write(str(powerZoneSettings[21]))
        log.write(str(" "))
        log.write(str(powerZoneSettings[22]))
        log.write(str(" "))
        log.write(str(powerZoneSettings[23]))        
        log.write("\n")
      elif x == 8:
        log.write(str(powerZoneSettings[24]))
        log.write(str(" "))
        log.write(str(powerZoneSettings[25]))
        log.write(str(" "))
        log.write(str(powerZoneSettings[26]))        
        log.write("\n")
      elif x == 9:
        log.write(str(powerZoneSettings[27]))
        log.write(str(" "))
        log.write(str(powerZoneSettings[28]))
        log.write(str(" "))
        log.write(str(powerZoneSettings[29]))        
        log.write("\n")
      elif x == 10:
        log.write(str(powerZoneSettings[30]))
        log.write(str(" "))
        log.write(str(powerZoneSettings[31]))
        log.write(str(" "))
        log.write(str(powerZoneSettings[32]))        
        log.write("\n")
      elif x == 11:
        log.write(str(powerZoneSettings[33]))
        log.write(str(" "))
        log.write(str(powerZoneSettings[34]))
        log.write(str(" "))
        log.write(str(powerZoneSettings[35]))        
        log.write("\n")
      elif x == 12:
        log.write(str(powerZoneSettings[36]))
        log.write(str(" "))
        log.write(str(powerZoneSettings[37]))
        log.write(str(" "))
        log.write(str(powerZoneSettings[38]))        
        log.write("\n")
      elif x == 13:
        log.write(str(powerZoneSettings[39]))
        log.write(str(" "))
        log.write(str(powerZoneSettings[40]))
        log.write(str(" "))
        log.write(str(powerZoneSettings[41]))        
        log.write("\n")
      elif x == 14:
        log.write(str(powerZoneSettings[42]))
        log.write(str(" "))
        log.write(str(powerZoneSettings[43]))
        log.write(str(" "))
        log.write(str(powerZoneSettings[44]))        
        log.write("\n")
      elif x == 15:
        log.write(str(powerZoneSettings[45]))
        log.write(str(" "))
        log.write(str(powerZoneSettings[46]))
        log.write(str(" "))
        log.write(str(powerZoneSettings[47]))        
        log.write("\n")
        
    log.flush()
    log.close()

def zoneSettingsFileRW(readWrite = None):

  #File Handling for Zone Settings
  global zoneSettings
  temp = []
  
  listTemp = [0,0,0,
        0,0,0,
        0,0,0,
        0,0,0,
        0,0,0,
        0,0,0,
        0,0,0,               
        0,0,0,
        0,0,0,
        0,0,0,
        0,0,0,
        0,0,0,
        0,0,0,
        0,0,0,
        0,0,0,                
        0,0,0]


  n = x = 0
  ROW_OFFSET = 0
  
  if readWrite == 'read':
    log = open("/home/pi/Test3/zoneSettings.txt","r")
    for line in log:
      listTemp[n] = line        
      n = n + 1        
    log.flush()
    log.close()
    for x in range(0,16+ROW_OFFSET):
        
      if x == 0: 
        temp = listTemp[x].split()
        zoneSettings[0] = int(temp[0])
        zoneSettings[1] = int(temp[1])
        zoneSettings[2] = int(temp[2])
        
      elif x == 1:
        temp = listTemp[x].split()
        zoneSettings[3] = int(temp[0])
        zoneSettings[4] = int(temp[1])
        zoneSettings[5] = int(temp[2])
        
      elif x == 2:
        temp = listTemp[x].split()
        zoneSettings[6] = int(temp[0])
        zoneSettings[7] = int(temp[1])
        zoneSettings[8] = int(temp[2])
        
      elif x == 3:
        temp = listTemp[x].split()
        zoneSettings[9] = int(temp[0])
        zoneSettings[10] = int(temp[1])
        zoneSettings[11] = int(temp[2])
        
      elif x == 4:
        temp = listTemp[x].split()
        zoneSettings[12] = int(temp[0])
        zoneSettings[13] = int(temp[1])
        zoneSettings[14] = int(temp[2])
        
      elif x == 5:
        temp = listTemp[x].split()
        zoneSettings[15] = int(temp[0])
        zoneSettings[16] = int(temp[1])
        zoneSettings[17] = int(temp[2])
        
      elif x == 6:
        temp = listTemp[x].split()
        zoneSettings[18] = int(temp[0])
        zoneSettings[19] = int(temp[1])
        zoneSettings[20] = int(temp[2])
        
      elif x == 7:
        temp = listTemp[x].split()
        zoneSettings[21] = int(temp[0])
        zoneSettings[22] = int(temp[1])
        zoneSettings[23] = int(temp[2])
        
      elif x == 8: 
        temp = listTemp[x].split()
        zoneSettings[24] = int(temp[0])
        zoneSettings[25] = int(temp[1])
        zoneSettings[26] = int(temp[2])
        
      elif x == 9:
        temp = listTemp[x].split()
        zoneSettings[27] = int(temp[0])
        zoneSettings[28] = int(temp[1])
        zoneSettings[29] = int(temp[2])
        
      elif x == 10:
        temp = listTemp[x].split()
        zoneSettings[30] = int(temp[0])
        zoneSettings[31] = int(temp[1])
        zoneSettings[32] = int(temp[2])
        
      elif x == 11:
        temp = listTemp[x].split()
        zoneSettings[33] = int(temp[0])
        zoneSettings[34] = int(temp[1])
        zoneSettings[35] = int(temp[2])
      elif x == 12:
        temp = listTemp[x].split()
        zoneSettings[36] = int(temp[0])
        zoneSettings[37] = int(temp[1])
        zoneSettings[38] = int(temp[2])
      elif x == 13:
        temp = listTemp[x].split()
        zoneSettings[39] = int(temp[0])
        zoneSettings[40] = int(temp[1])
        zoneSettings[41] = int(temp[2])
      elif x == 14:
        temp = listTemp[x].split()
        zoneSettings[42] = int(temp[0])
        zoneSettings[43] = int(temp[1])
        zoneSettings[44] = int(temp[2])
      elif x == 15:
        temp = listTemp[x].split()
        zoneSettings[45] = int(temp[0])
        zoneSettings[46] = int(temp[1])
        zoneSettings[47] = int(temp[2])
        
      
  elif readWrite == 'write':
    log = open("/home/pi/Test3/zoneSettings.txt","w")
    for x in range(0,16+ROW_OFFSET):
      if x == 0:
        log.write(str(zoneSettings[0]))
        log.write(str(" "))
        log.write(str(zoneSettings[1]))
        log.write(str(" "))
        log.write(str(zoneSettings[2]))        
        log.write("\n")
      elif x == 1:
        log.write(str(zoneSettings[3]))
        log.write(str(" "))
        log.write(str(zoneSettings[4]))
        log.write(str(" "))
        log.write(str(zoneSettings[5]))        
        log.write("\n")
      elif x == 2:
        log.write(str(zoneSettings[6]))
        log.write(str(" "))
        log.write(str(zoneSettings[7]))
        log.write(str(" "))
        log.write(str(zoneSettings[8]))        
        log.write("\n")
      elif x == 3:
        log.write(str(zoneSettings[9]))
        log.write(str(" "))
        log.write(str(zoneSettings[10]))
        log.write(str(" "))
        log.write(str(zoneSettings[11]))        
        log.write("\n")
      elif x == 4:
        log.write(str(zoneSettings[12]))
        log.write(str(" "))
        log.write(str(zoneSettings[13]))
        log.write(str(" "))
        log.write(str(zoneSettings[14]))        
        log.write("\n")
      elif x == 5:
        log.write(str(zoneSettings[15]))
        log.write(str(" "))
        log.write(str(zoneSettings[16]))
        log.write(str(" "))
        log.write(str(zoneSettings[17]))        
        log.write("\n")
      elif x == 6:
        log.write(str(zoneSettings[18]))
        log.write(str(" "))
        log.write(str(zoneSettings[19]))
        log.write(str(" "))
        log.write(str(zoneSettings[20]))        
        log.write("\n")
      elif x == 7:
        log.write(str(zoneSettings[21]))
        log.write(str(" "))
        log.write(str(zoneSettings[22]))
        log.write(str(" "))
        log.write(str(zoneSettings[23]))        
        log.write("\n")
      elif x == 8:
        log.write(str(zoneSettings[24]))
        log.write(str(" "))
        log.write(str(zoneSettings[25]))
        log.write(str(" "))
        log.write(str(zoneSettings[26]))        
        log.write("\n")
      elif x == 9:
        log.write(str(zoneSettings[27]))
        log.write(str(" "))
        log.write(str(zoneSettings[28]))
        log.write(str(" "))
        log.write(str(zoneSettings[29]))        
        log.write("\n")
      elif x == 10:
        log.write(str(zoneSettings[30]))
        log.write(str(" "))
        log.write(str(zoneSettings[31]))
        log.write(str(" "))
        log.write(str(zoneSettings[32]))        
        log.write("\n")
      elif x == 11:
        log.write(str(zoneSettings[33]))
        log.write(str(" "))
        log.write(str(zoneSettings[34]))
        log.write(str(" "))
        log.write(str(zoneSettings[35]))        
        log.write("\n")
      elif x == 12:
        log.write(str(zoneSettings[36]))
        log.write(str(" "))
        log.write(str(zoneSettings[37]))
        log.write(str(" "))
        log.write(str(zoneSettings[38]))        
        log.write("\n")
      elif x == 13:
        log.write(str(zoneSettings[39]))
        log.write(str(" "))
        log.write(str(zoneSettings[40]))
        log.write(str(" "))
        log.write(str(zoneSettings[41]))        
        log.write("\n")
      elif x == 14:
        log.write(str(zoneSettings[42]))
        log.write(str(" "))
        log.write(str(zoneSettings[43]))
        log.write(str(" "))
        log.write(str(zoneSettings[44]))        
        log.write("\n")
      elif x == 15:
        log.write(str(zoneSettings[45]))
        log.write(str(" "))
        log.write(str(zoneSettings[46]))
        log.write(str(" "))
        log.write(str(zoneSettings[47]))        
        log.write("\n")
        
    log.flush()
    log.close()


servicePass = [0,0,0,0]

def servicePasswordFileRW(readWrite = None):
    
    global servicePass

    temp = []
    listTemp = [0,0]
    n = x = 0
    ROW_OFFSET = 0
    
    if readWrite == 'read':
        log = open("/home/pi/Test3/servicePass.txt","r")
        for line in log:
            listTemp[n] = line        
            n = n + 1        
        log.flush()
        log.close()
        for x in range(0,2+ROW_OFFSET):
            if x == 0: 
                temp = listTemp[x].split()
                servicePass[0] = int(temp[0])
                servicePass[1] = int(temp[1])
            elif x == 1:
                temp = listTemp[x].split()
                servicePass[2] = int(temp[0])
                servicePass[3] = int(temp[1])            
            
    elif readWrite == 'write':
        log = open("/home/pi/Test3/servicePass.txt","w")
        for x in range(0,2+ROW_OFFSET):
            if x == 0:
                log.write(str(servicePass[0]))
                log.write(str(" "))
                log.write(str(servicePass[1])+"\n")
            elif x == 1:
                log.write(str(servicePass[2]))
                log.write(str(" "))
                log.write(str(servicePass[3])+"\n")                
        log.flush()
        log.close()



adminPass = [0,0,0,0]
#panelProgramChangeCMS = 0

def adminPasswordFileRW(readWrite = None):
    '''
    #number = 0
    if readWrite == 'read':
        log = open("/home/pi/TLChronosPro/AdminPass.txt","r")
        number = log.read()
        #print log.read()
        log.flush()
        log.close()
        return(int(number))
    elif readWrite == 'write':
        log = open("/home/pi/TLChronosPro/AdminPass.txt","w")
        log.write(str(value)) 
        log.flush()
        log.close()
    '''
    global adminPass

    temp = []
    listTemp = [0,0]
    n = x = 0
    ROW_OFFSET = 0
    
    if readWrite == 'read':
        log = open("/home/pi/Test3/AdminPass.txt","r")
        for line in log:
            listTemp[n] = line        
            n = n + 1        
        log.flush()
        log.close()
        for x in range(0,2+ROW_OFFSET):
            if x == 0: 
                temp = listTemp[x].split()
                adminPass[0] = int(temp[0])
                adminPass[1] = int(temp[1])
            elif x == 1:
                temp = listTemp[x].split()
                adminPass[2] = int(temp[0])
                adminPass[3] = int(temp[1])            
            
    elif readWrite == 'write':
        log = open("/home/pi/Test3/AdminPass.txt","w")
        for x in range(0,2+ROW_OFFSET):
            if x == 0:
                log.write(str(adminPass[0]))
                log.write(str(" "))
                log.write(str(adminPass[1])+"\n")
            elif x == 1:
                log.write(str(adminPass[2]))
                log.write(str(" "))
                log.write(str(adminPass[3])+"\n")                
        log.flush()
        log.close() 


def configureStaticNetwork():
    try:
        # Command to be executed
        command = ['nsenter', '-t', '1', '-m', '-u', '-i', '-n', '-p', '--', '/usr/bin/python3', '/home/pi/Test3/Configure_Network_7.py']

        # Execute the command
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stdout, stderr = process.communicate()

        # Check for errors
        if process.returncode == 0:
            #print("Output:")
            print(stdout)
        else:
            #print("Errors:")
            print(stderr)
            #logger.error(str(e))

    except Exception as e:
        #print("An error occurred:")
        print(str(e))
        logger.error(str(e))


def resetDHCP():
    # Update both dhcpcd.conf and /etc/network/interfaces to DHCP, then reboot.
    # reset_to_dhcp removes the eth0 static block from dhcpcd.conf.
    # _apply_interfaces_dhcp rewrites /etc/network/interfaces so
    # _check_dhcp_active() correctly sees DHCP (not static) on next boot.
    try:
        command = [
            'nsenter', '-t', '1', '-m', '-u', '-i', '-n', '-p', '--',
            '/usr/bin/python3', '-c',
            'import sys; sys.path.insert(0,"/home/pi/Test3"); '
            'from reset_to_dhcp import reset_to_dhcp; reset_to_dhcp(); '
            'from Configure_Network_7 import _apply_interfaces_dhcp; _apply_interfaces_dhcp()'
        ]
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stdout, stderr = process.communicate()
        if process.returncode == 0:
            print(stdout)
        else:
            print(stderr)
    except Exception as e:
        print(str(e))
        logger.error(str(e))



cmsParam = [0,0,0,0,0,0,0,0]
cmsParamTemp = [0,0,0,0,0,0,0,0]

preffered_dns_ip = "8.8.8.8"
alternate_dns_ip = "8.8.4.4"
netwoek_setting_configuration = 0

def _check_dhcp_active():
    """Return True if eth0 is on DHCP (no static block found in either config file)."""
    try:
        result = subprocess.check_output(
            ['nsenter', '-t', '1', '-m', '--', 'cat', '/etc/dhcpcd.conf'],
            stderr=subprocess.DEVNULL
        )
        if 'interface eth0' in result.decode('utf-8', errors='replace'):
            return False  # static block in dhcpcd.conf — not DHCP
    except Exception:
        pass
    try:
        result = subprocess.check_output(
            ['nsenter', '-t', '1', '-m', '--', 'cat', '/etc/network/interfaces'],
            stderr=subprocess.DEVNULL
        )
        if 'iface eth0 inet static' in result.decode('utf-8', errors='replace'):
            return False  # static block in /etc/network/interfaces — not DHCP
    except Exception:
        pass
    return True

# "Active" = DHCP already configured on host (show [Auto-Enabled], no reboot needed)
# "True"   = user just pressed Enter this session (reboot path)
# "False"  = static IP configured (show [Auto-Enable])
dhcp_enabled = "Active" if _check_dhcp_active() else "False"

#import reset_to_dhcp

def networkSettings():
    
    global menuSubState
    global index
    global sub_index
    global GmainStateState
    global menuCurrentPos
    global GuserSetState
    global keypressed
    global menuMainState
    global isLANStatusCheckOn
    global isWlanOn
    global isElanOn
    global menuSubSubState

    global clearKey
    global cmsParam
    global cmsParamTemp
    global toggleBit500mSecSec

    global phoneNumberBuff
    global keyPos

    global preffered_dns_ip
    global alternate_dns_ip

    global netwoek_setting_configuration
    global dhcp_enabled
    global _last_nav_key_pressed
    global _last_nav_key_time

    MAXPOS = 28
    MINPOS = 0

    # Function to format text to 16 characters
    def format_text(text, width=16):
        text = str(text)
        if len(text) >= width:
            return text[:width]
        return text + " " * (width - len(text))

    # Function to center text
    def center_text(text, width):
        text = str(text)
        if len(text) >= width:
            return text[:width]
        padding = (width - len(text)) // 2
        return " " * padding + text + " " * (width - len(text) - padding)

    # Cancel stale pending states when user navigates away.
    if menuSubSubState != 25 and netwoek_setting_configuration == 2:
        netwoek_setting_configuration = 0
    if menuSubSubState != 24 and dhcp_enabled == "True":
        dhcp_enabled = "False"   # cancel pending reboot only — "Active" is never reset here

    if menuSubSubState == 0:                  #  4

        led_status_enabled = network_settings.get_setting("Enable/Disable for Network LED Status")

        if led_status_enabled not in ('True', 'False'):
            led_status_enabled = "True"  # default when DB has None/unexpected
            network_settings.update_setting("Enable/Disable for Network LED Status", "True")

        if led_status_enabled == "True":
            lcd.home()
            lcd.noCursor()
            lcd.message("<LAN LED Status>\n Status is[On] ")
            if keypressed == "B":                       
                keypressed = None
                network_settings.update_setting("Enable/Disable for Network LED Status", "False")

        elif led_status_enabled == "False":
            lcd.home()
            lcd.message("<LAN LED Status>\n Status is[Off]")
            if keypressed == "B":                       
                keypressed = None
                network_settings.update_setting("Enable/Disable for Network LED Status", "True")
                
        menuSubSubState = menuPositionUpDn(0,MAXPOS)

    elif menuSubSubState == 1:              #   5     
        wireless_lan_enabled = network_settings.get_setting("Enable/Disable for Wireless LAN")

        if clearKey == 0:
            clearKey = 1
        
        if wireless_lan_enabled not in ('True', 'False'):
            wireless_lan_enabled = "False"  # default when DB has None/unexpected
            network_settings.update_setting("Enable/Disable for Wireless LAN", "False")

        if wireless_lan_enabled == "True":
            lcd.home()
            lcd.message("< Wireless Lan >\nInterface [On] ")
            if keypressed == "B":                       
                keypressed = None
                network_settings.update_setting("Enable/Disable for Wireless LAN", "False")
                call("sudo ifconfig wlan0 down", shell=True)                                
                
        elif wireless_lan_enabled == "False":
            lcd.home()
            lcd.message("< Wireless Lan >\nInterface [Off]")
            if keypressed == "B":                       
                keypressed = None
                network_settings.update_setting("Enable/Disable for Wireless LAN", "True")                
                call("sudo ifconfig wlan0 up", shell=True)                
                
        menuSubSubState = menuPositionUpDn(0,MAXPOS)

    elif menuSubSubState == 2:                       
        
        ip_address = network_settings.get_setting("Set IP Address")        
        
        if clearKey == 1:
            clearKey = 0
            keypadScanning(0,0,0,0,'clear')
            keyDetect = 0
            keyPos = 0
            for index in range(0,16,1):
                phoneNumberBuff[6][index] = ' '
            lcd.clear()
            lcd.home()
        lcd.noCursor()
        lcd.message("<Set IP Address>")        
        lcd.message("\n")
        lcd.message(str(ip_address))
        lcd.message("    ")
            
        menuSubSubState = menuPositionUpDn(0,MAXPOS)

    elif menuSubSubState == 3:                       

        if clearKey == 0:
            clearKey = 1
            keypadScanning(0,0,0,0,'clear')
            keyDetect = 0
            keyPos = 0
            padWithSpace = 0            
            for index in range(0,16,1):
                phoneNumberBuff[6][index] = ' '
            lcd.clear()
            lcd.home()                
            
        keypadScanningMultiNumKeyWithDot(16,6,None)
        lcd.home()
#        for padWithSpace in range(0,16,1):
#            if padWithSpace == keyPos:
#                if toggleBit500mSecSec:
#                    lcd.message("v")
#                else:
#                    lcd.message(" ")
#            else:                
 #               lcd.message(" ")
        lcd.message("\n")
        for index in range(0,16,1):
            lcd.message(str(phoneNumberBuff[6][index]))

        lcd.setCursor(keyPos, 1)  # Row 1, Column `keyPos` Set the cursor position for user input
        lcd.cursor()  # Show cursor

        menuSubSubState = menuPositionUpDn(0,MAXPOS)

    elif menuSubSubState == 4:        #
        
        if clearKey == 1:
            clearKey = 0
            keypadScanning(0,0,0,0,'clear')
            keyDetect = 0
            lcd.clear()
            lcd.home()            
        lcd.home()
        lcd.message(" Add IP Address ")
        
        lcd.message("\n")
        lcd.message("     Enter      ")

        if keypressed == "B":
            keypressed = None
            result = ''
            #for item in sequence:
            for item in phoneNumberBuff[6]:
                if item == ' ':
                    break
                result += str(item)            
            #result = "192.168.0.55"
            #print(result)  # Output: 192.168.0.134                
            network_settings.update_setting("Set IP Address", result)
            # FIX: mark as Static so Configure_Network_7.py applies static IP
            network_settings.update_setting("Enable/Disable Static/dynamic", "Static")
            network_settings.update_setting("reset_to_dhcp", "False")
            
        menuSubSubState = menuPositionUpDn(0,MAXPOS)	
                                                                                                                                                                 

    elif menuSubSubState == 5:                       #
        port_number = network_settings.get_setting("Set Port Number")
        
        if clearKey == 0:
            clearKey = 1
            keypadScanning(0,0,0,0,'clear')
            keyDetect = 0
            lcd.clear()
            lcd.home()
        lcd.home()            
        keyDetect = keypadScanning(5,0,65535,1)
        lcd.message("Set Port Numbner")
        lcd.message("\n")
        lcd.message("[")
        lcd.message(str(port_number))
        lcd.message("] ")
        if toggleBit500mSecSec:
            lcd.noCursor()
            lcd.message(">")
        else:
            lcd.message(" ")                
        lcd.message(str(keyDetect))
        if keypressed == "B":
            keypressed = None
            #network_settings.update_setting("Set Port Number", "1881")
            network_settings.update_setting("Set Port Number", str(keyDetect))                        
            lcd.clear()
        menuSubSubState = menuPositionUpDn(0,MAXPOS)

    elif menuSubSubState == 6:                       #
        
        gateway = network_settings.get_setting("Gateway")
        
        if clearKey == 1:
            clearKey = 0
            keypadScanning(0,0,0,0,'clear')
            keyDetect = 0
            keyPos = 0
            for index in range(0,16,1):
                phoneNumberBuff[6][index] = ' '
            lcd.clear()
            lcd.home()

        lcd.message("<    Gateway   >")
        lcd.message("\n")
        lcd.message(str(gateway))
        lcd.message("    ")
            
        menuSubSubState = menuPositionUpDn(0,MAXPOS)

    elif menuSubSubState == 7:                       

        if clearKey == 0:
            clearKey = 1
            keypadScanning(0,0,0,0,'clear')
            keyDetect = 0
            keyPos = 0
            padWithSpace = 0            
            for index in range(0,16,1):
                phoneNumberBuff[6][index] = ' '
            lcd.clear()
            lcd.home()                
            
        keypadScanningMultiNumKeyWithDot(16,6,None)
        lcd.home()
#        for padWithSpace in range(0,16,1):
#            if padWithSpace == keyPos:
#                if toggleBit500mSecSec:
#                    lcd.message("v")
#                else:
#                    lcd.message(" ")
#            else:                
#                lcd.message(" ")
        lcd.message("\n")
        for index in range(0,16,1):
            lcd.message(str(phoneNumberBuff[6][index]))
        lcd.setCursor(keyPos, 1)  # Row 1, Column `keyPos` Set the cursor position for user input
        lcd.cursor()  # Show cursor

        menuSubSubState = menuPositionUpDn(0,MAXPOS)

    elif menuSubSubState == 8:        #
        
        if clearKey == 1:
            clearKey = 0
            keypadScanning(0,0,0,0,'clear')
            keyDetect = 0
            lcd.clear()
            lcd.home()            
        lcd.home()
        lcd.message("  Add  Gateway  ")
        lcd.message("\n")
        lcd.message("     Enter      ")

        if keypressed == "B":
            keypressed = None
            result = ''
            for item in phoneNumberBuff[6]:
                if item == ' ':
                    break
                result += str(item)                
            network_settings.update_setting("Gateway", result)
            
        menuSubSubState = menuPositionUpDn(0,MAXPOS)	


    elif menuSubSubState == 9:                       #
        ip_module_enabled = network_settings.get_setting("Enable/Disable IP Module")
        
        if clearKey == 0:
            clearKey = 1
            keypadScanning(0,0,0,0,'clear')
            keyDetect = 0
            lcd.clear()
            lcd.home()
        lcd.home()            
        lcd.message("   IP Module    ")
        lcd.message("\n")
        if ip_module_enabled == "True":
            lcd.message("    [Enable]    ")
        else:
            lcd.message("   [Disable]    ")
            
        if keypressed == "B":
            keypressed = None
            if ip_module_enabled == "True":
                network_settings.update_setting("Enable/Disable IP Module", "False")
            elif cmsParam[7] == 0:
                network_settings.update_setting("Enable/Disable IP Module", "True")
        menuSubSubState = menuPositionUpDn(0,MAXPOS)

    elif menuSubSubState == 10:        #

        subnet_mask = network_settings.get_setting("Subnet mask")
        
        if clearKey == 1:
            clearKey = 0
            keypadScanning(0,0,0,0,'clear')
            keyDetect = 0
            for index in range(0,16,1):
                phoneNumberBuff[6][index] = ' '
            lcd.clear()
            lcd.home()
        lcd.noCursor()    
        lcd.home()
        lcd.noCursor()
        lcd.message("  Subnet  Mask  ")
        lcd.message("\n")
        lcd.message(str(subnet_mask))
        lcd.message("    ")
        
        menuSubSubState = menuPositionUpDn(0,MAXPOS)	
            
    elif menuSubSubState == 11:                       

        if clearKey == 0:
            clearKey = 1
            keypadScanning(0,0,0,0,'clear')
            keyDetect = 0
            keyPos = 0
            padWithSpace = 0
            for index in range(0,16,1):
                phoneNumberBuff[6][index] = ' '
            lcd.clear()
            lcd.home()
            
        keypadScanningMultiNumKeyWithDot(16,6,None)
        lcd.home()
#        for padWithSpace in range(0,16,1):
#            if padWithSpace == keyPos:
#                if toggleBit500mSecSec:
#                    lcd.message("v")
#                else:
#                    lcd.message(" ")
#            else:                
#                lcd.message(" ")
        lcd.message("\n")
        for index in range(0,16,1):
            lcd.message(str(phoneNumberBuff[6][index]))
        lcd.setCursor(keyPos, 1)  # Row 1, Column `keyPos` Set the cursor position for user input
        lcd.cursor()  # Show cursor
        menuSubSubState = menuPositionUpDn(0,MAXPOS)

    elif menuSubSubState == 12:        #
        
        if clearKey == 1:
            clearKey = 0
            keypadScanning(0,0,0,0,'clear')
            keyDetect = 0
            lcd.clear()
            lcd.home()            
        lcd.home()
        lcd.noCursor()
        lcd.message("Add Subnet  Mask")
        
        lcd.message("\n")
        
        lcd.message("     Enter      ")

        if keypressed == "B":
            keypressed = None
            result = ''
            for item in phoneNumberBuff[6]:
                if item == ' ':
                    break
                result += str(item)            
            #result = "192.168.0.55"
            #print(result)  # Output: 192.168.0.134                
            network_settings.update_setting("Subnet mask", result)
            
        menuSubSubState = menuPositionUpDn(0,MAXPOS)	


    elif menuSubSubState == 13:                       #
        dns_setup = network_settings.get_setting("DNS Setup")
        
        if clearKey == 0:
            clearKey = 1
            keypadScanning(0,0,0,0,'clear')
            keyDetect = 0
            for index in range(0,16,1):
                phoneNumberBuff[6][index] = ' '
            lcd.clear()
            lcd.home()            
        lcd.home()
        lcd.message("   DNS   Setup  ")
        lcd.message("\n")
        lcd.message(str(dns_setup))
        lcd.message(" ")

        if keypressed == "B":
            keypressed = None
            network_settings.update_setting("DNS Setup", "Automatic")
            
        menuSubSubState = menuPositionUpDn(0,MAXPOS)	

    elif menuSubSubState == 14:                       #

        apn_settings = network_settings.get_setting("APN Settings")
        
        if clearKey == 1:
            clearKey = 0
            keypadScanning(0,0,0,0,'clear')
            keyDetect = 0
            lcd.clear()
            lcd.home()            
        lcd.home()
        
        lcd.message("  APN Settings  ")
        lcd.message("\n")
        lcd.message(str(apn_settings))
        lcd.message(" ")
        if keypressed == "B":
            keypressed = None
            network_settings.update_setting("APN Settings", "internet")
            
        menuSubSubState = menuPositionUpDn(0,MAXPOS)	

    elif menuSubSubState == 15:        #  4
        
        network_test_enabled = network_settings.get_setting("Network Test")

        if network_test_enabled not in ('True', 'False'):
            network_test_enabled = "False"  # default when DB has None/unexpected
            network_settings.update_setting("Network Test", "False")

        if network_test_enabled == "True":
            lcd.home()
            lcd.message("  Network  Test \n     [On]      ")
            if keypressed == "B":                       
                keypressed = None
                network_settings.update_setting("Network Test", "False")                
        elif network_test_enabled == "False":
            lcd.home()
            lcd.message("  Network  Test \n    [Off]      ")            
            if keypressed == "B":                       
                keypressed = None
                network_settings.update_setting("Network Test", "True")                
                
        menuSubSubState = menuPositionUpDn(0,MAXPOS)

    elif menuSubSubState == 16:        #   5     

        ipv4_ipv6_selection = network_settings.get_setting("IPv4/IPv6 Selection")
    
        if ipv4_ipv6_selection not in ('IPv6', 'IPv4'):
            ipv4_ipv6_selection = "IPv4"  # default when DB has None/unexpected
            network_settings.update_setting("IPv4/IPv6 Selection", "IPv4")

        if ipv4_ipv6_selection == "IPv6":
            lcd.home()
            lcd.message("    Interface   \n     [IPV6]    ")
            if keypressed == "B":                       
                keypressed = None
                network_settings.update_setting("IPv4/IPv6 Selection", "IPv4")
        elif ipv4_ipv6_selection == "IPv4":
            lcd.home()
            lcd.message("    Interface   \n     [IPV4]    ")                        
            if keypressed == "B":                       
                keypressed = None
                network_settings.update_setting("IPv4/IPv6 Selection", "IPv6")
                
        menuSubSubState = menuPositionUpDn(0,MAXPOS)

    elif menuSubSubState == 17:        #   5     

        static_dynamic_enabled = network_settings.get_setting("Enable/Disable Static/dynamic")
    
        if static_dynamic_enabled not in ('Static', 'dynamic'):
            static_dynamic_enabled = "dynamic"  # default when DB has None/unexpected
            network_settings.update_setting("Enable/Disable Static/dynamic", "dynamic")

        if static_dynamic_enabled == "Static":
            lcd.home()
            lcd.message(" Enable/Disable \n    [Static]   ")
            if keypressed == "B":                       
                keypressed = None
                network_settings.update_setting("Enable/Disable Static/dynamic", "dynamic")
                
        elif static_dynamic_enabled == "dynamic":
            lcd.home()
            lcd.message(" Enable/Disable \n   [dynamic]   ")            
            if keypressed == "B":                       
                keypressed = None
                network_settings.update_setting("Enable/Disable Static/dynamic", "Static")
                
        menuSubSubState = menuPositionUpDn(0,MAXPOS)


    elif menuSubSubState == 18:        #
        
        preffered_dns_ip = network_settings.get_setting("preferred_dns_server")
        
        if clearKey == 0:
            clearKey = 1
            keypadScanning(0,0,0,0,'clear')
            keyDetect = 0
            for index in range(0,16,1):
                phoneNumberBuff[6][index] = ' '
            lcd.clear()
            lcd.home()
        lcd.noCursor()    
        lcd.home()
        lcd.message(" Preffered  DNS ")        
        lcd.message("\n")
        lcd.message(str(preffered_dns_ip))
        lcd.message("    ")
        
        menuSubSubState = menuPositionUpDn(0,MAXPOS)	
    
            
    elif menuSubSubState == 19:                       

        if clearKey == 1:
            clearKey = 0
            keypadScanning(0,0,0,0,'clear')
            keyDetect = 0
            keyPos = 0
            padWithSpace = 0
            for index in range(0,16,1):
                phoneNumberBuff[6][index] = ' '
            lcd.clear()
            lcd.home()
            
        keypadScanningMultiNumKeyWithDot(16,6,None)
        lcd.home()
#        for padWithSpace in range(0,16,1):
#            if padWithSpace == keyPos:
#                if toggleBit500mSecSec:
#                    lcd.message("v")
#                else:
#                    lcd.message(" ")
#            else:                
#                lcd.message(" ")
        lcd.message("\n")
        for index in range(0,16,1):
            lcd.message(str(phoneNumberBuff[6][index]))
        lcd.setCursor(keyPos, 1)  # Row 1, Column `keyPos` Set the cursor position for user input
        lcd.cursor()  # Show cursor

        menuSubSubState = menuPositionUpDn(0,MAXPOS)

    
    elif menuSubSubState == 20:        #
        
        if clearKey == 0:
            clearKey = 1
            keypadScanning(0,0,0,0,'clear')
            keyDetect = 0
            lcd.clear()
            lcd.home()            
        lcd.home()
        lcd.noCursor()
        lcd.message("Add PrefferedDNS")
        
        lcd.message("\n")
        
        lcd.message("     Enter      ")

        if keypressed == "B":
            keypressed = None
            result = ''
            for item in phoneNumberBuff[6]:
                if item == ' ':
                    break
                result += str(item) 
            print(result)  # Output: 192.168.0.134                
            network_settings.update_setting("preferred_dns_server", result)
            #preffered_dns_ip = result

        menuSubSubState = menuPositionUpDn(0,MAXPOS)
        
    elif menuSubSubState == 21:        #

        alternate_dns_ip = network_settings.get_setting("alternate_dns_server")
        
        if clearKey == 1:
            clearKey = 0
            keypadScanning(0,0,0,0,'clear')
            keyDetect = 0
            for index in range(0,16,1):
                phoneNumberBuff[6][index] = ' '
            lcd.clear()
            lcd.home()
        lcd.noCursor()    
        lcd.home()
        lcd.noCursor()
        lcd.message(" Alternate  DNS ")        
        lcd.message("\n")
        lcd.message(str(alternate_dns_ip))
        lcd.message("    ")
        
        menuSubSubState = menuPositionUpDn(0,MAXPOS)	
                
    elif menuSubSubState == 22:                       

        if clearKey == 0:
            clearKey = 1
            keypadScanning(0,0,0,0,'clear')
            keyDetect = 0
            keyPos = 0
            padWithSpace = 0
            for index in range(0,16,1):
                phoneNumberBuff[6][index] = ' '
            lcd.clear()
            lcd.home()
            
        keypadScanningMultiNumKeyWithDot(16,6,None)
        lcd.home()
#        for padWithSpace in range(0,16,1):
#            if padWithSpace == keyPos:
#                if toggleBit500mSecSec:
#                    lcd.message("v")
#                else:
#                    lcd.message(" ")
#            else:                
#                lcd.message(" ")
        lcd.message("\n")
        for index in range(0,16,1):
            lcd.message(str(phoneNumberBuff[6][index]))
        lcd.setCursor(keyPos, 1)  # Row 1, Column `keyPos` Set the cursor position for user input
        lcd.cursor()  # Show cursor
        menuSubSubState = menuPositionUpDn(0,MAXPOS)
    
    elif menuSubSubState == 23:        #
        
        if clearKey == 1:
            clearKey = 0
            keypadScanning(0,0,0,0,'clear')
            keyDetect = 0
            lcd.clear()
            lcd.home()            
        lcd.home()
        lcd.noCursor()
        lcd.message("Add AlternateDNS")
        
        lcd.message("\n")
        
        lcd.message("     Enter      ")

        if keypressed == "B":
            keypressed = None
            result = ''
            for item in phoneNumberBuff[6]:
                if item == ' ':
                    break
                result += str(item)                 
            network_settings.update_setting("alternate_dns_server", result)
            
        menuSubSubState = menuPositionUpDn(0,MAXPOS)	

    elif menuSubSubState == 24:   # DHCP Enable
        if dhcp_enabled == "False":

            lcd.home()
            lcd.message("      DHCP      \n [Auto-Enable] ")
            if keypressed == "B":
                keypressed = None
                dhcp_enabled = "True"

        elif dhcp_enabled == "True":
            lcd.home()
            lcd.message("      DHCP      \nEnter=Yes >=Exit")
            if keypressed == "B":
                keypressed = None
                dhcp_enabled = "Rebooting"
                resetDHCP()
                rebootPanel()

        elif dhcp_enabled == "Rebooting":
            lcd.home()
            lcd.message("     System     \n  Rebooting... ")

        elif dhcp_enabled == "Active":
            # DHCP already configured on host — just show status, no reboot
            lcd.home()
            lcd.message("      DHCP      \n [Auto-Enabled]")
            if keypressed == "B":
                keypressed = None

        menuSubSubState = menuPositionUpDn(0,MAXPOS)

    elif menuSubSubState == 25:   # Network Setting Update

        if netwoek_setting_configuration == 0:
            lcd.home()
            lcd.message(" Network Setting\n   [Configure] ")
            if keypressed == "B":
                keypressed = None
                netwoek_setting_configuration = 2  # pending confirm — nav away resets to 0
                _last_nav_key_pressed = None        # discard scroll history; only keys ON confirm screen count

        elif netwoek_setting_configuration == 2:  # Confirm screen
            lcd.home()
            lcd.message("  Apply Config? \nEnter=Yes >=Exit")
            # If a nav key (@/*) was pressed within 500ms and ghost B overwrote it,
            # restore the nav key so menuPositionUpDn can navigate correctly.
            if _last_nav_key_pressed is not None and time.time() - _last_nav_key_time < 0.5:
                keypressed = _last_nav_key_pressed
                _last_nav_key_pressed = None
            elif keypressed == "B":
                keypressed = None
                netwoek_setting_configuration = 1
                configureStaticNetwork()
                rebootPanel()

        elif netwoek_setting_configuration == 1:
            lcd.home()
            lcd.message("     System     \n  Rebooting... ")
            if keypressed == "B":
                keypressed = None

        menuSubSubState = menuPositionUpDn(0,MAXPOS)

    elif menuSubSubState == 26:  
        lcd.home()
        lcd.message(format_text("   IP  Address  ") + "\n" + format_text(center_text(get_ip_address(), 16)))
        menuSubSubState = menuPositionUpDn(0,MAXPOS)

    elif menuSubSubState == 27:  
        lcd.home()
        lcd.message(format_text("     Gateway    ") + "\n" + format_text(center_text(get_default_gateway(), 16)))
        menuSubSubState = menuPositionUpDn(0,MAXPOS)

    elif menuSubSubState == MAXPOS:                       #
        if clearKey == 0:
            clearKey = 1
        lcd.home()
        lcd.message("<     EXIT      ")
        lcd.message("\n")
        lcd.message("    [ENTER]     ")
        menuSubSubState = menuPositionUpDn(0,MAXPOS)
        if keypressed == "B":
            keypressed = None
            # Cancel any pending operations that weren't confirmed.
            # Only reset "True" (pending reboot) → "False"; leave "Active" alone
            # so DHCP-already-configured state survives navigating to EXIT.
            if dhcp_enabled == "True":
                dhcp_enabled = "False"
            netwoek_setting_configuration = 0
            global menuCodeSelectState
            menuCurrentPos = 3
            menuSubState = 3
            lcd.clear()
            lcd.home()

chnageInProgramParam = 0
_reboot_in_progress = False   # guard: rebootPanel() is a one-shot — ignore any re-entry

def eSIMSettingseSIM_SETTINGS_ZONE_PROG():
    
    global menuSubState
    global index
    global sub_index
    global GmainStateState
    global menuCurrentPos
    global GuserSetState
    global keypressed
    global menuMainState
    global menuSubSubState

    global chnageInProgramParam

    # Function to format text to 16 characters
    def format_text(text, width=16):
        text = str(text)
        if len(text) >= width:
            return text[:width]
        return text + " " * (width - len(text))

    # Function to center text
    def center_text(text, width):
        text = str(text)
        if len(text) >= width:
            return text[:width]
        padding = (width - len(text)) // 2
        return " " * padding + text + " " * (width - len(text) - padding)

    if menuSubSubState == 0:

        current_value = cavli_database.get_sim_swap()
        
        
        lcd.home()
        lcd.message("      eSIM     >")
        lcd.message("\n")
        lcd.message(format_text(center_text(current_value, 16)))
        
        if keypressed == "B":
            keypressed = None
            new_value = None
            if current_value == 'esim':
                new_value = 'physical'
            elif current_value == 'physical':
                new_value = 'esim'
            if new_value is not None:
                cavli_database.update_sim_swap(new_value)
            chnageInProgramParam = 1

        menuSubSubState = menuPositionUpDn(0,2)

    if menuSubSubState == 1:

        current_value = modem_config_db.get_parameter('network_type')
        
        lcd.home()
        lcd.message("<    NETWORK   >")        
        lcd.message("\n")
        lcd.message(format_text(center_text(current_value, 16)))
        
        if keypressed == "B":
            keypressed = None

            new_value = current_value
            if current_value == 'ethernet':
                new_value = 'gsm'
            elif current_value == 'gsm':
                new_value = 'ethernet'
            modem_config_db.update_parameter('network_type', new_value)
            chnageInProgramParam = 1
            
        menuSubSubState = menuPositionUpDn(0,2)
        
    if menuSubSubState == 2:        
        lcd.home()
        lcd.message("<     EXIT      ")
        lcd.message("\n")
        lcd.message("    [ENTER]     ")
        menuSubSubState = menuPositionUpDn(0,2)
        if keypressed == "B":
            keypressed = None
            menuCurrentPos = 0
            menuSubState = 0
            if chnageInProgramParam == 1:
                chnageInProgramParam = 0
                rebootPanel()
            lcd.clear()
            lcd.home()



def GNSSSettingsGNSS_SETTINGS_PROG():
    
    global menuSubState
    global index
    global sub_index
    global GmainStateState
    global menuCurrentPos
    global GuserSetState
    global keypressed
    global menuMainState
    global menuSubSubState


    if menuSubSubState == 0:        
        lcd.home()
        lcd.message("      GNSS     >")
        lcd.message("\n")
        lcd.message("                ")
        if keypressed == "B":
            keypressed = None
        menuSubSubState = menuPositionUpDn(0,1)

    if menuSubSubState == 1:        
        lcd.home()
        lcd.message("<     EXIT      ")
        lcd.message("\n")
        lcd.message("    [ENTER]     ")
        
        menuSubSubState = menuPositionUpDn(0,1)
        
        if keypressed == "B":
            keypressed = None
            menuCurrentPos = 1
            menuSubState = 1
            lcd.clear()
            lcd.home()


# ---------------------------- DEVICE_CREDENTIAL_SETUP_PROG ---------------------------
# DEF0000
# -------------------------------------------------------------------------------
def menuSubSubStateDEVICE_CREDENTIAL_SETUP_PROG():
    
    global menuSubState
    global index
    global sub_index
    global GmainStateState
    global menuCurrentPos
    global GuserSetState
    global keypressed
    global menuMainState
    global menuSubSubState
    global menuSubSubSubState
    
    global clearKey
                
    menuList = {'CLIENT_ID':0,
                'USER_NAME':1,
                'PASSWORD':2,
                'ACCESS_TOKEN':3,
                'EXIT':4,
                'CLIENT_ID_PROG':5,
                'USER_NAME_PROG':6,
                'PASSWORD_PROG':7,
                'ACCESS_TOKEN_PROG':8}

    MENU_MAX = 4
    MENU_MIN = 0
    
    if menuSubSubState == menuList['CLIENT_ID']:
        
        lcd.message(" SET CLIENT ID >\n  PRESS ENTER   ")
        menuSubSubState = menuPositionUpDnWithoutClear(MENU_MIN, MENU_MAX)

        if keypressed == "B":           
            keypressed = None
            menuSubSubSubState = 0            
            menuCurrentPos = 0
            lcd.clear()
            lcd.home()
            clearKey = 0
            keypadScanning(0,0,0,0,'clear')
            menuSubSubState = menuList['CLIENT_ID_PROG']

    elif menuSubSubState == menuList['USER_NAME']:                                 
        lcd.message("<SET USER NAME >\n  PRESS  ENTER  ")
        menuSubSubState = menuPositionUpDnWithoutClear(MENU_MIN, MENU_MAX)
        if keypressed == "B":           
            keypressed = None
            menuSubSubSubState = 0           
            menuCurrentPos = 0
            lcd.clear()
            lcd.home()
            clearKey = 0
            keypadScanning(0,0,0,0,'clear')
            menuSubSubState = menuList['USER_NAME_PROG']

    elif menuSubSubState == menuList['PASSWORD']:                                 
        lcd.message("< SET PASSWORD >\n  PRESS  ENTER  ")
        menuSubSubState = menuPositionUpDnWithoutClear(MENU_MIN, MENU_MAX)
        if keypressed == "B":           
            keypressed = None
            menuSubSubSubState = 0
            menuCurrentPos = 0
            lcd.clear()
            lcd.home()
            clearKey = 0
            keypadScanning(0,0,0,0,'clear')
            menuSubSubState = menuList['PASSWORD_PROG']

    elif menuSubSubState == menuList['ACCESS_TOKEN']:
        lcd.message("<SET ACC TOKEN >\n  PRESS  ENTER  ")
        menuSubSubState = menuPositionUpDnWithoutClear(MENU_MIN, MENU_MAX)
        if keypressed == "B":
            keypressed = None
            menuSubSubSubState = 0
            menuCurrentPos = 0
            lcd.clear()
            lcd.home()
            clearKey = 0
            keypadScanning(0,0,0,0,'clear')
            menuSubSubState = menuList['ACCESS_TOKEN_PROG']

    elif menuSubSubState == menuList['EXIT']:                                               
        lcd.message("<     EXIT      \n    [ENTER]     ")
        menuSubSubState = menuPositionUpDnWithoutClear(MENU_MIN, MENU_MAX)
        if keypressed == "B":
            # CRED-GATE: end session when operator exits credential menu
            _cred_session_expiry[0] = None
            _cred_challenge[0] = None
            keypressed = "CLEAR"
            menuCurrentPos = 2
            menuSubState = 2
            lcd.clear()
            lcd.home()
            keypadScanning(0,0,0,0,'clear')

            
    elif menuSubSubState == menuList['CLIENT_ID_PROG']:                    
        SubMenuClientAddress()
        
    elif menuSubSubState == menuList['USER_NAME_PROG']:                    
        SubMenuUserName()
            
    elif menuSubSubState == menuList['PASSWORD_PROG']:                    
        SubMenuPassword()

    elif menuSubSubState == menuList['ACCESS_TOKEN_PROG']:
        SubMenuAccessToken()

#====================================================================================
def SubMenuClientAddress():
  
    CG_REQ, CG_VFY, SHOW_CLIENT_ID, SHOW_CLIENT_NAME, REG_CLIENT_NAME, EXIT = range(6)  # CRED-GATE
  
    MAX_POS = EXIT
    MIN_POS = SHOW_CLIENT_ID

    global keypressed
    global GmainStateState
    global menuCurrentPos
    global GuserSetState
    global menuSubState
    global menuSubSubState
    global menuMainState
    global toggleBit500mSecSec 
    global keyInputMultiMode
    global keyPos
    global rowPOS
    global clearKey  
    global credientalsBuffer  
    global menuSubSubSubState
  
  
    if menuSubSubSubState == CG_REQ:
        # CRED-GATE: show challenge — operator must call Seple
        import time as _ct
        if _cred_session_expiry[0] and _ct.time() < _cred_session_expiry[0]:
            _cred_show_time[0] = _ct.time()
            menuSubSubSubState = SHOW_CLIENT_ID  # CRED-GATE: session active
            menuCurrentPos = SHOW_CLIENT_ID
            lcd.clear(); lcd.home()
            return
        if not credential_auth.key_is_loaded():
            lcd.clear(); lcd.home()
            lcd.message("Key not set    \n")
            lcd.message("Contact Seple  ")
            menuSubSubSubState = EXIT
            return
        if credential_auth.is_locked_out():
            secs = credential_auth.time_remaining_locked()
            lcd.clear(); lcd.home()
            lcd.message("Access locked  \n")
            lcd.message(str(secs) + "s remaining    ")
            _cred_challenge[0] = None               # CRED-GATE-FIX: reset so next entry is fresh
            menuSubSubSubState = EXIT
            return
        if _cred_challenge[0] is None:          # generate once per entry
            _cred_challenge[0] = credential_auth.generate_challenge()
            _cred_resp_digits[0] = ''
        # Display on EVERY tick — keeps LCD showing challenge while operator reads it
        lcd.noCursor()
        lcd.message("Call Seple:    \n")
        lcd.message(str(_cred_challenge[0]) + "            ")
        menuSubSubSubState = menuPositionUpDn(CG_REQ, CG_VFY)

    elif menuSubSubSubState == CG_VFY:
        # CRED-GATE: collect 6-digit response from operator keypad
        if _cred_challenge[0] is None:
            menuSubSubSubState = SHOW_CLIENT_ID
            menuCurrentPos = SHOW_CLIENT_ID
            return
        if credential_auth.is_locked_out():
            secs = credential_auth.time_remaining_locked()
            lcd.clear(); lcd.home()
            lcd.message("Access locked  \n")
            lcd.message(str(secs) + "s remaining    ")
            _cred_challenge[0] = None               # CRED-GATE-FIX: reset so next entry is fresh
            menuSubSubSubState = EXIT
            return
        global keypressed
        lcd.noCursor()
        lcd.message("Enter code:    \n")
        display = _cred_resp_digits[0].ljust(6, '_')
        lcd.message(display + "          ")
        if keypressed and keypressed.isdigit() and len(_cred_resp_digits[0]) < 6:
            _cred_resp_digits[0] += keypressed
            keypressed = None
        elif keypressed == "C":
            _cred_resp_digits[0] = ''
            keypressed = None
        elif keypressed == "B" and len(_cred_resp_digits[0]) == 6:
            keypressed = None
            if credential_auth.verify_response(_cred_challenge[0], _cred_resp_digits[0]):
                import time as _t
                _cred_show_time[0] = _t.time()
                _cred_session_expiry[0] = _t.time() + _CRED_SESSION_SEC
                _cred_challenge[0] = None
                _cred_resp_digits[0] = ''
                menuSubSubSubState = SHOW_CLIENT_ID
                menuCurrentPos = SHOW_CLIENT_ID
                lcd.clear(); lcd.home()
            else:
                lcd.clear(); lcd.home()
                lcd.message("Access denied  \n")
                lcd.message("Wrong code     ")
                _cred_challenge[0] = None               # CRED-GATE-FIX: reset on wrong code
                menuSubSubSubState = EXIT
        elif keypressed == "D":
            keypressed = None
            _cred_challenge[0] = None               # CRED-GATE-FIX: reset on cancel
            menuSubSubSubState = EXIT
            lcd.clear(); lcd.home()

    elif menuSubSubSubState == SHOW_CLIENT_ID:

        c_id = modem_config_db.get_parameter("client_id")
        # Handle missing or empty values
        if c_id is None or str(c_id).strip() == "":
           c_id = "    Not Set"
        
        if clearKey == 1:
            clearKey = 0
            keypadScanning(0,0,0,0,'clear')
            keyDetect = 0
            keyPos = 0
            for index in range(0,32,1):
                credientalsBuffer[0][index] = ' ' 
            lcd.clear()
            lcd.home()
        lcd.noCursor()
        lcd.message("   Client ID   >")
        lcd.message("\n")
        lcd.message(str(c_id))
        lcd.message("            ")   #12 space
        # CRED-GATE: auto-clear after {credential_auth.SHOW_TIMEOUT_SEC} seconds
        if credential_auth.show_expired(_cred_show_time[0]):
            _cred_show_time[0] = None
            _cred_challenge[0] = None               # CRED-GATE-FIX: reset after show expires
            lcd.clear(); lcd.home()
            menuSubSubSubState = EXIT
            return
    
        menuSubSubSubState = menuPositionUpDn(MIN_POS,MAX_POS)

  
    elif menuSubSubSubState == SHOW_CLIENT_NAME:
    
        if clearKey == 0:
            clearKey = 1
            keypadScanning(0,0,0,0,'clear')
            keyDetect = 0
            keyPos = 0
            padWithSpace = 0            
            for index in range(0, 16):
               credientalsBuffer[0][index] = ' '  # Clear the first & second line of credentials
            lcd.clear()
            lcd.home()                
            
        keypadScanningMultiKey_crediential(maxRANGE=16, rowPOS=0, buffer_clear=None)

        lcd.message("Put Client ID: >")
        lcd.message("\n")
        # Display characters on the first line (0-15)
        for index in range(0, 16):
                # Replace '0' or space with an empty character for better visual experience
                if credientalsBuffer[0][index] == '0' or credientalsBuffer[0][index] == ' ':
                    lcd.message(" ")  # Blank space so user can see where to type
                else:
                    lcd.message(str(credientalsBuffer[0][index]))
        lcd.setCursor(keyPos, 1)  # Row 1, Column `keyPos` Set the cursor position for user input
        lcd.cursor()  # Show cursor
    
        menuSubSubSubState = menuPositionUpDn(MIN_POS,MAX_POS)


    elif menuSubSubSubState == REG_CLIENT_NAME:
        if clearKey == 0:
            clearKey = 1
            keypadScanning(0,0,0,0,'clear')
            keyDetect = 0
            keyPos = 0 
            lcd.clear()
            lcd.home()        
        lcd.home()
        lcd.noCursor()
        lcd.message("< Update Client>")
        lcd.message("\n")
        if toggleBit500mSecSec:
            lcd.message("  >")
        else:
            lcd.message("   ")
        lcd.message("[UPDATE]")
    
        if keypressed == "B":
            keypressed = None
      
            result = ''     
            for item in credientalsBuffer[0]:
                if item == ' ':
                    #result += ' '  # Add a space to the result instead of breaking
                    break
                result += str(item)   
#            print(result)  
         
            try:
                modem_config_db.update_parameter('client_id', result)            
                #print(f"Client ID in credientalsBuffer is {result}")
            except ValueError as e:
                print(f"Error: {e}")
                logger.error(f"Error: {e}")
            except Exception as e:
                print(f"An unexpected error occurred: {e}")
                logger.error(f"An unexpected error occurred: {e}")
      
        menuSubSubSubState = menuPositionUpDn(MIN_POS, MAX_POS)


    elif menuSubSubSubState == EXIT:                                            # 4    
        lcd.home()
        lcd.message("<     EXIT      ")
        lcd.message("\n")
        lcd.message("    [ENTER]     ")
        menuSubSubSubState = menuPositionUpDn(MIN_POS,MAX_POS)
        if keypressed == "B":
            keypressed = None
            global menuCodeSelectState
            menuCurrentPos = 0
            menuSubSubState = 0
            menuSubSubSubState = 0
            keypadScanning(0,0,0,0,'clear')
            lcd.clear()
            lcd.home()
#=====================================================================================

def SubMenuUserName():
  
    CG_REQ, CG_VFY, SHOW_USER, SHOW_USER_NAME, REG_USER_NAME, EXIT = range(6)  # CRED-GATE
  
    MAX_POS = EXIT
    MIN_POS = SHOW_USER

    global keypressed
    global GmainStateState
    global menuCurrentPos
    global GuserSetState
    global menuSubState
    global menuSubSubState
    global menuMainState
    global toggleBit500mSecSec
    global keyInputMultiMode
    global keyPos
    global rowPOS
    global clearKey 
    global credientalsBuffer  
    global menuSubSubSubState
  

    if menuSubSubSubState == CG_REQ:
        # CRED-GATE: show challenge — operator must call Seple
        import time as _ct
        if _cred_session_expiry[0] and _ct.time() < _cred_session_expiry[0]:
            _cred_show_time[0] = _ct.time()
            menuSubSubSubState = SHOW_USER  # CRED-GATE: session active
            menuCurrentPos = SHOW_USER
            lcd.clear(); lcd.home()
            return
        if not credential_auth.key_is_loaded():
            lcd.clear(); lcd.home()
            lcd.message("Key not set    \n")
            lcd.message("Contact Seple  ")
            menuSubSubSubState = EXIT
            return
        if credential_auth.is_locked_out():
            secs = credential_auth.time_remaining_locked()
            lcd.clear(); lcd.home()
            lcd.message("Access locked  \n")
            lcd.message(str(secs) + "s remaining    ")
            _cred_challenge[0] = None               # CRED-GATE-FIX: reset so next entry is fresh
            menuSubSubSubState = EXIT
            return
        if _cred_challenge[0] is None:          # generate once per entry
            _cred_challenge[0] = credential_auth.generate_challenge()
            _cred_resp_digits[0] = ''
        # Display on EVERY tick — keeps LCD showing challenge while operator reads it
        lcd.noCursor()
        lcd.message("Call Seple:    \n")
        lcd.message(str(_cred_challenge[0]) + "            ")
        menuSubSubSubState = menuPositionUpDn(CG_REQ, CG_VFY)

    elif menuSubSubSubState == CG_VFY:
        # CRED-GATE: collect 6-digit response from operator keypad
        if _cred_challenge[0] is None:
            menuSubSubSubState = SHOW_USER
            menuCurrentPos = SHOW_USER
            return
        if credential_auth.is_locked_out():
            secs = credential_auth.time_remaining_locked()
            lcd.clear(); lcd.home()
            lcd.message("Access locked  \n")
            lcd.message(str(secs) + "s remaining    ")
            _cred_challenge[0] = None               # CRED-GATE-FIX: reset so next entry is fresh
            menuSubSubSubState = EXIT
            return
        global keypressed
        lcd.noCursor()
        lcd.message("Enter code:    \n")
        display = _cred_resp_digits[0].ljust(6, '_')
        lcd.message(display + "          ")
        if keypressed and keypressed.isdigit() and len(_cred_resp_digits[0]) < 6:
            _cred_resp_digits[0] += keypressed
            keypressed = None
        elif keypressed == "C":
            _cred_resp_digits[0] = ''
            keypressed = None
        elif keypressed == "B" and len(_cred_resp_digits[0]) == 6:
            keypressed = None
            if credential_auth.verify_response(_cred_challenge[0], _cred_resp_digits[0]):
                import time as _t
                _cred_show_time[0] = _t.time()
                _cred_session_expiry[0] = _t.time() + _CRED_SESSION_SEC
                _cred_challenge[0] = None
                _cred_resp_digits[0] = ''
                menuSubSubSubState = SHOW_USER
                menuCurrentPos = SHOW_USER
                lcd.clear(); lcd.home()
            else:
                lcd.clear(); lcd.home()
                lcd.message("Access denied  \n")
                lcd.message("Wrong code     ")
                _cred_challenge[0] = None               # CRED-GATE-FIX: reset on wrong code
                menuSubSubSubState = EXIT
        elif keypressed == "D":
            keypressed = None
            _cred_challenge[0] = None               # CRED-GATE-FIX: reset on cancel
            menuSubSubSubState = EXIT
            lcd.clear(); lcd.home()

    elif menuSubSubSubState == SHOW_USER:

        u_name = modem_config_db.get_parameter("user_name")
        # Handle missing or empty values
        if u_name is None or str(u_name).strip() == "":
           u_name = "    Not Set"
        
        if clearKey == 1:
            clearKey = 0
            keypadScanning(0,0,0,0,'clear')
            keyDetect = 0
            keyPos = 0
            for index in range(0,16,1):
                credientalsBuffer[0][index] = ' ' 
            lcd.clear()
            lcd.home()
        lcd.noCursor()
        lcd.message("   User Name   >")
        lcd.message("\n")
        lcd.message(str(u_name))
        lcd.message("            ")  #12 space
        # CRED-GATE: auto-clear after {credential_auth.SHOW_TIMEOUT_SEC} seconds
        if credential_auth.show_expired(_cred_show_time[0]):
            _cred_show_time[0] = None
            _cred_challenge[0] = None               # CRED-GATE-FIX: reset after show expires
            lcd.clear(); lcd.home()
            menuSubSubSubState = EXIT
            return
    
        menuSubSubSubState = menuPositionUpDn(MIN_POS,MAX_POS)
  
    elif menuSubSubSubState == SHOW_USER_NAME:
    
        if clearKey == 0:
            clearKey = 1
            keypadScanning(0,0,0,0,'clear')
            keyDetect = 0
            keyPos = 0
            rowPOS = 0
            for index in range(0, 16):
              credientalsBuffer[0][index] = ' '   # Clear the first & second line of credentials   
            lcd.clear()
            lcd.home()
    
        keypadScanningMultiKey_crediential(maxRANGE=16, rowPOS=0, buffer_clear=None)

        lcd.message("Put User Name: >")
        lcd.message("\n")
        for index in range(0, 16):
            # Replace '0' or space with an empty character for better visual experience
            if credientalsBuffer[0][index] == '0' or credientalsBuffer[0][index] == ' ':
                lcd.message(" ")  # Blank space so user can see where to type
            else:
                lcd.message(str(credientalsBuffer[0][index]))  # Show actual character if it's not '0' or space
        
        lcd.setCursor(keyPos, 1)
        lcd.cursor()
    
        menuSubSubSubState = menuPositionUpDn(MIN_POS,MAX_POS)
    

    elif menuSubSubSubState == REG_USER_NAME:
        if clearKey == 0:
            clearKey = 1
            keypadScanning(0,0,0,0,'clear')
            keyDetect = 0
            keyPos = 0 
            lcd.clear()
            lcd.home()        
        lcd.home()
        lcd.noCursor()
        lcd.message("< Update  User >")
        lcd.message("\n")
        if toggleBit500mSecSec:
            lcd.message("  >")
        else:
            lcd.message("   ")
        lcd.message("[UPDATE]")
    
        if keypressed == "B":
            keypressed = None
      
            result = ''     
            for item in credientalsBuffer[0]:
                if item == ' ':
                   # result += ' '  # Add a space to the result instead of breaking
                    break
                result += str(item)   
#            print(result)  
        
            try:
                modem_config_db.update_parameter('user_name', result)            
                #print(f"User Name in credientalsBuffer is {result}")
            except ValueError as e:
                print(f"Error: {e}")
                logger.error(f"Error: {e}")
            except Exception as e:
                print(f"An unexpected error occurred: {e}")
                logger.error("An unexpected error occurred: {e}")
      
        menuSubSubSubState = menuPositionUpDn(MIN_POS, MAX_POS)


    elif menuSubSubSubState == EXIT:                                            # 4    
        lcd.home()
        lcd.message("<     EXIT      ")
        lcd.message("\n")
        lcd.message("    [ENTER]     ")
        menuSubSubSubState = menuPositionUpDn(MIN_POS,MAX_POS)
        if keypressed == "B":
            keypressed = None
            global menuCodeSelectState
            menuCurrentPos = 1
            menuSubSubState = 1
            menuSubSubSubState = 1
            
            keypadScanning(0,0,0,0,'clear')
            lcd.clear()
            lcd.home()
#===============================================================================

def SubMenuPassword():
   
    CG_REQ, CG_VFY, SHOW_PASSWORD, SHOW_CLIENT_PASSWORD, REG_CLIENT_PASSWORD, EXIT = range(6)  # CRED-GATE
    MAX_POS = EXIT
    MIN_POS = SHOW_PASSWORD

    global keypressed
    global GmainStateState
    global menuCurrentPos
    global GuserSetState
    global menuSubState
    global menuSubSubState
    global menuMainState
    global toggleBit500mSecSec
    global keyInputMultiMode
    global keyPos
    global rowPOS
    global clearKey  
    global credientalsBuffer  
    global menuSubSubSubState
  
    if menuSubSubSubState == CG_REQ:
        # CRED-GATE: show challenge — operator must call Seple
        import time as _ct
        if _cred_session_expiry[0] and _ct.time() < _cred_session_expiry[0]:
            _cred_show_time[0] = _ct.time()
            menuSubSubSubState = SHOW_PASSWORD  # CRED-GATE: session active
            menuCurrentPos = SHOW_PASSWORD
            lcd.clear(); lcd.home()
            return
        if not credential_auth.key_is_loaded():
            lcd.clear(); lcd.home()
            lcd.message("Key not set    \n")
            lcd.message("Contact Seple  ")
            menuSubSubSubState = EXIT
            return
        if credential_auth.is_locked_out():
            secs = credential_auth.time_remaining_locked()
            lcd.clear(); lcd.home()
            lcd.message("Access locked  \n")
            lcd.message(str(secs) + "s remaining    ")
            _cred_challenge[0] = None               # CRED-GATE-FIX: reset so next entry is fresh
            menuSubSubSubState = EXIT
            return
        if _cred_challenge[0] is None:          # generate once per entry
            _cred_challenge[0] = credential_auth.generate_challenge()
            _cred_resp_digits[0] = ''
        # Display on EVERY tick — keeps LCD showing challenge while operator reads it
        lcd.noCursor()
        lcd.message("Call Seple:    \n")
        lcd.message(str(_cred_challenge[0]) + "            ")
        menuSubSubSubState = menuPositionUpDn(CG_REQ, CG_VFY)

    elif menuSubSubSubState == CG_VFY:
        # CRED-GATE: collect 6-digit response from operator keypad
        if _cred_challenge[0] is None:
            menuSubSubSubState = SHOW_PASSWORD
            menuCurrentPos = SHOW_PASSWORD
            return
        if credential_auth.is_locked_out():
            secs = credential_auth.time_remaining_locked()
            lcd.clear(); lcd.home()
            lcd.message("Access locked  \n")
            lcd.message(str(secs) + "s remaining    ")
            _cred_challenge[0] = None               # CRED-GATE-FIX: reset so next entry is fresh
            menuSubSubSubState = EXIT
            return
        global keypressed
        lcd.noCursor()
        lcd.message("Enter code:    \n")
        display = _cred_resp_digits[0].ljust(6, '_')
        lcd.message(display + "          ")
        if keypressed and keypressed.isdigit() and len(_cred_resp_digits[0]) < 6:
            _cred_resp_digits[0] += keypressed
            keypressed = None
        elif keypressed == "C":
            _cred_resp_digits[0] = ''
            keypressed = None
        elif keypressed == "B" and len(_cred_resp_digits[0]) == 6:
            keypressed = None
            if credential_auth.verify_response(_cred_challenge[0], _cred_resp_digits[0]):
                import time as _t
                _cred_show_time[0] = _t.time()
                _cred_session_expiry[0] = _t.time() + _CRED_SESSION_SEC
                _cred_challenge[0] = None
                _cred_resp_digits[0] = ''
                menuSubSubSubState = SHOW_PASSWORD
                menuCurrentPos = SHOW_PASSWORD
                lcd.clear(); lcd.home()
            else:
                lcd.clear(); lcd.home()
                lcd.message("Access denied  \n")
                lcd.message("Wrong code     ")
                _cred_challenge[0] = None               # CRED-GATE-FIX: reset on wrong code
                menuSubSubSubState = EXIT
        elif keypressed == "D":
            keypressed = None
            _cred_challenge[0] = None               # CRED-GATE-FIX: reset on cancel
            menuSubSubSubState = EXIT
            lcd.clear(); lcd.home()

    elif menuSubSubSubState == SHOW_PASSWORD:

        u_pswd = modem_config_db.get_parameter("password")
        # Handle missing or empty values
        if u_pswd is None or str(u_pswd).strip() == "":
           u_pswd = "    Not Set"
        
        if clearKey == 1:
            clearKey = 0
            keypadScanning(0,0,0,0,'clear')
            keyDetect = 0
            keyPos = 0
            for index in range(0,16,1):
                credientalsBuffer[0][index] = ' ' 
            lcd.clear()
            lcd.home()
        lcd.noCursor()
        lcd.message("  Set Password>")
        lcd.message("\n")
        lcd.message(str(u_pswd))
        lcd.message("             ")  #13 space
        # CRED-GATE: auto-clear after {credential_auth.SHOW_TIMEOUT_SEC} seconds
        if credential_auth.show_expired(_cred_show_time[0]):
            _cred_show_time[0] = None
            _cred_challenge[0] = None               # CRED-GATE-FIX: reset after show expires
            lcd.clear(); lcd.home()
            menuSubSubSubState = EXIT
            return
    
        menuSubSubSubState = menuPositionUpDn(MIN_POS,MAX_POS)
  
    elif menuSubSubSubState == SHOW_CLIENT_PASSWORD:
    
        if clearKey == 0:
            clearKey = 1
            keypadScanning(0,0,0,0,'clear')
            keyDetect = 0
            keyPos = 0
            padWithSpace = 0            
            for index in range(0, 16):
               credientalsBuffer[0][index] = ' '  # Clear the first & second line of credentials
            lcd.clear()
            lcd.home()                
            
        keypadScanningMultiKey_crediential(maxRANGE=16, rowPOS=0, buffer_clear=None)

        lcd.message("Put Password:  >")
        lcd.message("\n")
        # Display characters on the first line (0-15)
        for index in range(0, 16):
            # Replace '0' or space with an empty character for better visual experience
            if credientalsBuffer[0][index] == '0' or credientalsBuffer[0][index] == ' ':
                lcd.message(" ")  # Blank space so user can see where to type
            else:
                lcd.message(str(credientalsBuffer[0][index]))
        lcd.setCursor(keyPos, 1)  # Row 1, Column `keyPos` Set the cursor position for user input
        lcd.cursor()  # Show cursor
       
        menuSubSubSubState = menuPositionUpDn(MIN_POS,MAX_POS)
    

    elif menuSubSubSubState == REG_CLIENT_PASSWORD:
        if clearKey == 0:
            clearKey = 1
            keypadScanning(0,0,0,0,'clear')
            keyDetect = 0
            keyPos = 0 
            lcd.clear()
            lcd.home()        
        lcd.home()
        lcd.noCursor()
        lcd.message("< Update Pswrd >")
        lcd.message("\n")
        if toggleBit500mSecSec:
            lcd.message("  >")
        else:
            lcd.message("   ")
        lcd.message("[UPDATE]")
    
        if keypressed == "B":
            keypressed = None
      
            result = ''     
            for item in credientalsBuffer[0]:
                if item == ' ':
                   # result += ' '  # Add a space to the result instead of breaking
                   break
                result += str(item)   
#            print(result)  
        
            try:
                modem_config_db.update_parameter('password', result)
            except ValueError as e:
                print(f"Error: {e}")
                logger.error(f"Error: {e}")
            except Exception as e:
                print(f"An unexpected error occurred: {e}")
                logger.error(f"An unexpected error occurred: {e}")
      
        menuSubSubSubState = menuPositionUpDn(MIN_POS, MAX_POS)


    elif menuSubSubSubState == EXIT:                                               
        lcd.home()
        lcd.message("<     EXIT      ")
        lcd.message("\n")
        lcd.message("    [ENTER]     ")
        menuSubSubSubState = menuPositionUpDn(MIN_POS,MAX_POS)
        if keypressed == "B":
            keypressed = None
            global menuCodeSelectState
            menuCurrentPos = 2
            menuSubSubState = 2 
            menuSubSubSubState = 2
            keypadScanning(0,0,0,0,'clear')
            lcd.clear()
            lcd.home()

#===============================================================================

def SubMenuAccessToken():

    CG_REQ, CG_VFY, SHOW_ACCESS_TOKEN, SHOW_ACCESS_TOKEN_VAL, REG_ACCESS_TOKEN, EXIT = range(6)  # CRED-GATE
    MAX_POS = EXIT
    MIN_POS = SHOW_ACCESS_TOKEN

    global keypressed
    global GmainStateState
    global menuCurrentPos
    global GuserSetState
    global menuSubState
    global menuSubSubState
    global menuMainState
    global toggleBit500mSecSec
    global keyInputMultiMode
    global keyPos
    global rowPOS
    global clearKey
    global credientalsBuffer
    global menuSubSubSubState

    if menuSubSubSubState == CG_REQ:
        # CRED-GATE: show challenge — operator must call Seple
        import time as _ct
        if _cred_session_expiry[0] and _ct.time() < _cred_session_expiry[0]:
            _cred_show_time[0] = _ct.time()
            menuSubSubSubState = SHOW_ACCESS_TOKEN  # CRED-GATE: session active
            menuCurrentPos = SHOW_ACCESS_TOKEN
            lcd.clear(); lcd.home()
            return
        if not credential_auth.key_is_loaded():
            lcd.clear(); lcd.home()
            lcd.message("Key not set    \n")
            lcd.message("Contact Seple  ")
            menuSubSubSubState = EXIT
            return
        if credential_auth.is_locked_out():
            secs = credential_auth.time_remaining_locked()
            lcd.clear(); lcd.home()
            lcd.message("Access locked  \n")
            lcd.message(str(secs) + "s remaining    ")
            _cred_challenge[0] = None               # CRED-GATE-FIX: reset so next entry is fresh
            menuSubSubSubState = EXIT
            return
        if _cred_challenge[0] is None:          # generate once per entry
            _cred_challenge[0] = credential_auth.generate_challenge()
            _cred_resp_digits[0] = ''
        # Display on EVERY tick — keeps LCD showing challenge while operator reads it
        lcd.noCursor()
        lcd.message("Call Seple:    \n")
        lcd.message(str(_cred_challenge[0]) + "            ")
        menuSubSubSubState = menuPositionUpDn(CG_REQ, CG_VFY)

    elif menuSubSubSubState == CG_VFY:
        # CRED-GATE: collect 6-digit response from operator keypad
        if _cred_challenge[0] is None:
            menuSubSubSubState = SHOW_ACCESS_TOKEN
            menuCurrentPos = SHOW_ACCESS_TOKEN
            return
        if credential_auth.is_locked_out():
            secs = credential_auth.time_remaining_locked()
            lcd.clear(); lcd.home()
            lcd.message("Access locked  \n")
            lcd.message(str(secs) + "s remaining    ")
            _cred_challenge[0] = None               # CRED-GATE-FIX: reset so next entry is fresh
            menuSubSubSubState = EXIT
            return
        global keypressed
        lcd.noCursor()
        lcd.message("Enter code:    \n")
        display = _cred_resp_digits[0].ljust(6, '_')
        lcd.message(display + "          ")
        if keypressed and keypressed.isdigit() and len(_cred_resp_digits[0]) < 6:
            _cred_resp_digits[0] += keypressed
            keypressed = None
        elif keypressed == "C":
            _cred_resp_digits[0] = ''
            keypressed = None
        elif keypressed == "B" and len(_cred_resp_digits[0]) == 6:
            keypressed = None
            if credential_auth.verify_response(_cred_challenge[0], _cred_resp_digits[0]):
                import time as _t
                _cred_show_time[0] = _t.time()
                _cred_session_expiry[0] = _t.time() + _CRED_SESSION_SEC
                _cred_challenge[0] = None
                _cred_resp_digits[0] = ''
                menuSubSubSubState = SHOW_ACCESS_TOKEN
                menuCurrentPos = SHOW_ACCESS_TOKEN
                lcd.clear(); lcd.home()
            else:
                lcd.clear(); lcd.home()
                lcd.message("Access denied  \n")
                lcd.message("Wrong code     ")
                _cred_challenge[0] = None               # CRED-GATE-FIX: reset on wrong code
                menuSubSubSubState = EXIT
        elif keypressed == "D":
            keypressed = None
            _cred_challenge[0] = None               # CRED-GATE-FIX: reset on cancel
            menuSubSubSubState = EXIT
            lcd.clear(); lcd.home()

    elif menuSubSubSubState == SHOW_ACCESS_TOKEN:

        u_token = modem_config_db.get_parameter("access_token")
        if u_token is None or str(u_token).strip() == "":
            u_token = "    Not Set"

        if clearKey == 1:
            clearKey = 0
            keypadScanning(0,0,0,0,'clear')
            keyDetect = 0
            keyPos = 0
            for index in range(0,16,1):
                credientalsBuffer[0][index] = ' '
            lcd.clear()
            lcd.home()
        lcd.noCursor()
        lcd.message(" Set Acc Token>")
        lcd.message("\n")
        lcd.message(str(u_token))
        lcd.message("             ")  #13 space
        # CRED-GATE: auto-clear after {credential_auth.SHOW_TIMEOUT_SEC} seconds
        if credential_auth.show_expired(_cred_show_time[0]):
            _cred_show_time[0] = None
            _cred_challenge[0] = None               # CRED-GATE-FIX: reset after show expires
            lcd.clear(); lcd.home()
            menuSubSubSubState = EXIT
            return

        menuSubSubSubState = menuPositionUpDn(MIN_POS, MAX_POS)

    elif menuSubSubSubState == SHOW_ACCESS_TOKEN_VAL:

        if clearKey == 0:
            clearKey = 1
            keypadScanning(0,0,0,0,'clear')
            keyDetect = 0
            keyPos = 0
            padWithSpace = 0
            for index in range(0, 16):
                credientalsBuffer[0][index] = ' '
            lcd.clear()
            lcd.home()

        keypadScanningMultiKey_crediential(maxRANGE=16, rowPOS=0, buffer_clear=None)

        lcd.message("Put Acc Token: >")
        lcd.message("\n")
        for index in range(0, 16):
            if credientalsBuffer[0][index] == '0' or credientalsBuffer[0][index] == ' ':
                lcd.message(" ")
            else:
                lcd.message(str(credientalsBuffer[0][index]))
        lcd.setCursor(keyPos, 1)
        lcd.cursor()

        menuSubSubSubState = menuPositionUpDn(MIN_POS, MAX_POS)

    elif menuSubSubSubState == REG_ACCESS_TOKEN:
        if clearKey == 0:
            clearKey = 1
            keypadScanning(0,0,0,0,'clear')
            keyDetect = 0
            keyPos = 0
            lcd.clear()
            lcd.home()
        lcd.home()
        lcd.noCursor()
        lcd.message("< Update Token >")
        lcd.message("\n")
        if toggleBit500mSecSec:
            lcd.message("  >")
        else:
            lcd.message("   ")
        lcd.message("[UPDATE]")

        if keypressed == "B":
            keypressed = None

            result = ''
            for item in credientalsBuffer[0]:
                if item == ' ':
                    break
                result += str(item)

            try:
                modem_config_db.update_parameter('access_token', result)
            except ValueError as e:
                print(f"Error: {e}")
                logger.error(f"Error: {e}")
            except Exception as e:
                print(f"An unexpected error occurred: {e}")
                logger.error(f"An unexpected error occurred: {e}")

        menuSubSubSubState = menuPositionUpDn(MIN_POS, MAX_POS)

    elif menuSubSubSubState == EXIT:
        lcd.home()
        lcd.message("<     EXIT      ")
        lcd.message("\n")
        lcd.message("    [ENTER]     ")
        menuSubSubSubState = menuPositionUpDn(MIN_POS, MAX_POS)
        if keypressed == "B":
            keypressed = None
            global menuCodeSelectState
            menuCurrentPos = 2
            menuSubSubState = 2
            menuSubSubSubState = 2
            keypadScanning(0,0,0,0,'clear')
            lcd.clear()
            lcd.home()

# ------------------------------- GSMSettings ----------------------------------
# DEF0000
# -------------------------------------------------------------------------------
def GSMSettingsGSM_SETTINGS_PROG():
    
    global menuSubState
    global index
    global sub_index
    global GmainStateState
    global menuCurrentPos
    global GuserSetState
    global keypressed
    global menuMainState
    global menuSubSubState


    if menuSubSubState == 0:        
        lcd.home()
        lcd.message("       GSM     >")
        lcd.message("\n")
        lcd.message("                ")
        if keypressed == "B":
            keypressed = None
        menuSubSubState = menuPositionUpDn(0,1)

    if menuSubSubState == 1:        
        lcd.home()
        lcd.message("<     EXIT      ")
        lcd.message("\n")
        lcd.message("    [ENTER]     ")
        
        menuSubSubState = menuPositionUpDn(0,1)
        if keypressed == "B":
            keypressed = None
            menuCurrentPos = 4
            menuSubState = 4
            menuSubSubState = 4
            lcd.clear()
            lcd.home()



panelLogData = ()
panelLogDataBuff = ()
panelLogDataArray = []
totalLogs = 0
indexLog = 0

def menuSubSubStateLOGS_PROG():
    
    global menuSubState
    global index
    global sub_index
    global GmainStateState
    global menuCurrentPos
    global GuserSetState
    global keypressed
    global menuMainState
    global menuSubSubState

    global panelLogData
    global indexLog
    global totalLogs

    global panelLogDataBuff
    global panelLogDataArray

    if menuSubSubState == 0:        
        lcd.home()
        lcd.message("<DOWNLOAD  LOGS>")
        lcd.message("\n")
        lcd.message("    [ENTER]     ")
        if keypressed == "B":
            keypressed = None

            connection = None
            try:
                #indexLog = 0
                # Connect to the database
                connection = sqlite3.connect(DB_PANEL)
                cursor = connection.cursor()

                rows = cursor.execute("SELECT deviceType, logType, rtcYear, rtcMonth, rtcDate, rtcHour, rtcMinute, rtcSecound  FROM systemLogs").fetchall()
                panelLogData = rows

                cursor.execute("SELECT * FROM systemLogs")
                totalLogs = len(cursor.fetchall())

            except sqlite3.Error as e:
                #print "Error clearing database:", e
                pass
            finally:
                # Close the connection
                if connection:
                    connection.close()
                
            
        menuSubSubState = menuPositionUpDn(0,3)
        
    if menuSubSubState == 1:
        
        lcd.home()
        lcd.message("   VIEW  LOGS  >")
        lcd.message("\n")
        x = 0
        x = int(totalLogs)
        lcd.message(str(x))
        lcd.message("        ")        
        if keypressed == "B":
            keypressed = None
            
        menuSubSubState = menuPositionUpDn(0,3)
        

    if menuSubSubState == 2:        
        lcd.home()

        try:
            lcd.message(str(panelLogData[indexLog][1]))
            lcd.message("      ")                
            lcd.message("\n")        

            lcd.message(str(panelLogData[indexLog][2]))
            lcd.message("/")                
            lcd.message(str(panelLogData[indexLog][3]))
            lcd.message("/")                
            lcd.message(str(panelLogData[indexLog][4]))
            lcd.message(" ")                
            lcd.message(str(panelLogData[indexLog][5]))
            lcd.message(":")                
            lcd.message(str(panelLogData[indexLog][6]))
            lcd.message("    ")
        except IndexError:
            lcd.message("   IndexError   ")
            lcd.message("\n")
            lcd.message("                ")            
        
        if keypressed == "B":
            keypressed = None

            indexLog = indexLog + 1
            if indexLog >= int(totalLogs):
                indexLog = 0
            
        menuSubSubState = menuPositionUpDn(0,3)
        
    if menuSubSubState == 3:        
        lcd.home()
        lcd.message("<     EXIT      ")
        lcd.message("\n")
        lcd.message("    [ENTER]     ")
        menuSubSubState = menuPositionUpDn(0,3)
        if keypressed == "B":
            keypressed = None
            menuCurrentPos = 0
            menuSubState = 0
            menuSubSubState = 0
            lcd.clear()
            lcd.home()
            keypadScanning(0,0,0,0,'clear')

# ------------------------------- EVENT_REPORTS_PROG ----------------------------------
# 
# -------------------------------------------------------------------------------
def menuSubSubStateEVENT_REPORTS_PROG():
    
    global menuSubState
    global index
    global sub_index
    global GmainStateState
    global menuCurrentPos
    global GuserSetState
    global keypressed
    global menuMainState
    global menuSubSubState

    if menuSubSubState == 0:        
        lcd.home()
        lcd.message("     REPORT    >")
        lcd.message("\n")
        lcd.message("                ")
        if keypressed == "B":
            keypressed = None
        menuSubSubState = menuPositionUpDn(0,1)
        
    if menuSubSubState == 1:        
        lcd.home()
        lcd.message("<     EXIT      ")
        lcd.message("\n")
        lcd.message("    [ENTER]     ")
        menuSubSubState = menuPositionUpDn(0,1)
        if keypressed == "B":
            keypressed = None
            menuCurrentPos = 1
            menuSubState = 1
            menuSubSubState=1
            lcd.clear()
            lcd.home()



# ------------------------------- DELETE_LOGS_PROG ----------------------------------
# 
# -------------------------------------------------------------------------------
def menuSubSubStateDELETE_LOGS_PROG():
    
    global menuSubState
    global index
    global sub_index
    global GmainStateState
    global menuCurrentPos
    global GuserSetState
    global keypressed
    global menuMainState
    global menuSubSubState

    
    if menuSubSubState == 0:        
        lcd.home()
        lcd.message("  DELETE LOGS  >")
        lcd.message("\n")
        totalLogs = 0
        connection = None
        try:
            # Connect to the database
            connection = sqlite3.connect(DB_PANEL)
            cursor = connection.cursor()

            rows = cursor.execute("SELECT deviceType, logType, rtcYear, rtcMonth, rtcDate, rtcHour, rtcMinute, rtcSecound  FROM systemLogs").fetchall()
            cursor.execute("SELECT * FROM systemLogs")
            totalLogs = len(cursor.fetchall())
        except sqlite3.Error as e:
            #print "Error clearing database:", e
            pass
        finally:
            # Close the connection
            if connection:
                connection.close()
            
        lcd.message("   [")
        lcd.message(str(totalLogs))
        lcd.message("]      ")
        
        if keypressed == "B":
            keypressed = None
            clearLogsFromDB()
            
        menuSubSubState = menuPositionUpDn(0,1)
        
    if menuSubSubState == 1:        
        lcd.home()
        lcd.message("<     EXIT      ")
        lcd.message("\n")
        lcd.message("    [ENTER]     ")
        menuSubSubState = menuPositionUpDn(0,1)
        if keypressed == "B":
            keypressed = None
            menuCurrentPos = 2
            menuSubState = 2
            menuSubSubState=2
            lcd.clear()
            lcd.home()



# Global variable for the database location
db_location = None

def set_db_location(location):
    """Set the database location."""
    global db_location
    db_location = location


def get_db_location():
    """Return the current database location."""
    return db_location


def _restart_integration_containers(*names):
    import http.client as _hc
    import socket as _sock
    import threading as _threading

    class _UnixHTTPConn(_hc.HTTPConnection):
        def __init__(self, sp):
            super().__init__("localhost")
            self._sp = sp
        def connect(self):
            s = _sock.socket(_sock.AF_UNIX, _sock.SOCK_STREAM)
            s.connect(self._sp)
            self.sock = s

    def _do():
        for name in names:
            try:
                _c = _UnixHTTPConn("/var/run/docker.sock")
                _c.request("POST", f"/containers/{name}/restart?t=2")
                _r = _c.getresponse(); _c.close()
                if _r.status not in (204, 304):
                    logger.warning("[integration] docker restart %s HTTP %s", name, _r.status)
                else:
                    logger.info("[integration] docker restart %s OK", name)
            except Exception as _e:
                logger.warning("[integration] docker restart %s failed: %s", name, _e)

    _threading.Thread(target=_do, daemon=True).start()


def initialize_active_integration_database():
    """Create and initialize the database with the required table."""
    if not db_location:
        raise ValueError("Database location is not set.")

    conn = None
    try:
        conn = sqlite3.connect(db_location)
        cursor = conn.cursor()

        # Create the table if it doesn't exist
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS active_integration_external_device (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                active_integration_on_off_bit INTEGER NOT NULL CHECK(active_integration_on_off_bit IN (0, 1))
            )
        """)

        conn.commit()
    except sqlite3.Error as e:
        print("Error initializing database: {}".format(e))
        logger.error("Error initializing database: {}".format(e))
    finally:
        if conn:
            conn.close()

def set_active_integration(value):
    """Set the active integration on/off bit in the database."""
    if not db_location:
        raise ValueError("Database location is not set.")

    if value not in (0, 1):
        raise ValueError("Value must be 0 or 1.")

    conn = None
    try:
        conn = sqlite3.connect(db_location)
        cursor = conn.cursor()

        # Check if the record already exists
        cursor.execute("""
            SELECT id FROM active_integration_external_device WHERE id = 1
        """)
        result = cursor.fetchone()

        if result:
            # Update the record if it exists
            cursor.execute("""
                UPDATE active_integration_external_device
                SET active_integration_on_off_bit = ?
                WHERE id = 1
            """, (value,))
        else:
            # Insert the record if it does not exist
            cursor.execute("""
                INSERT INTO active_integration_external_device (id, active_integration_on_off_bit)
                VALUES (1, ?)
            """, (value,))

        conn.commit()
    except sqlite3.Error as e:
        print("Error setting active integration value: {}".format(e))
        logger.error("Error setting active integration value: {}".format(e))
    finally:
        if conn:
            conn.close()



def get_active_integration():
    """Get the active integration on/off bit from the database."""
    if not db_location:
        raise ValueError("Database location is not set.")

    conn = None
    try:
        conn = sqlite3.connect(db_location)
        cursor = conn.cursor()

        # Retrieve the value
        cursor.execute("""
            SELECT active_integration_on_off_bit
            FROM active_integration_external_device
            WHERE id = 1
        """)
        result = cursor.fetchone()

        return result[0] if result else None
    except sqlite3.Error as e:
        print("Error retrieving active integration value: {}".format(e))
        logger.error("Error retrieving active integration value: {}".format(e))
    finally:
        if conn:
            conn.close()



import logical_params_module
# Initialize the database
logical_params_module.initialize_database()

clear_all_data_flag = 0


def outputManagement():

  global menuMainState
  global menuCurrentPos
  global keypressed
  global keyDetect
  global GuserSetState
  global menuSubState
  global GmainStateState
  global clearKey
  global toggleBit500mSecSec
  global zoneProgSetMenu 
  global zoneSettings
  global clear_all_data_flag
  
  MIN_POS = 0
  MAX_POS = 12

  if zoneProgSetMenu == 0:                          
    if clearKey == 0:
      clearKey = 1
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()
    lcd.home()
    lcd.message("      RELAY    >")
    lcd.message("\n")
    lcd.message("  CONFIGURATION ")
    zoneProgSetMenu = menuPositionUpDn(MIN_POS, MAX_POS)

  elif zoneProgSetMenu == 1:                        
    if clearKey == 1:
      clearKey = 0
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()
    lcd.home()
    lcd.message("<  ACTION  ON  >")
    lcd.message("\n")
    lcd.message("     TRIGGER    ")
    zoneProgSetMenu = menuPositionUpDn(MIN_POS, MAX_POS)

  elif zoneProgSetMenu == 2:                        
    if clearKey == 0:
      clearKey = 1
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()
      
    lcd.home()
    lcd.message("<  CLR BUFFER  >")
    lcd.message("\n")
    
    if clear_all_data_flag == 0:
        lcd.message("    [ENTER]     ")
    elif clear_all_data_flag == 1:
        lcd.message("    CLEARED!    ")
        
    if keypressed == "B":
      keypressed = None
      database_path = '/home/pi/Test3/payloads.db'
      clear_all_data(database_path)
      database_path = '/home/pi/Test3/buffer.db'
      clear_all_data(database_path)
      clear_all_data_flag = 1

    zoneProgSetMenu = menuPositionUpDn(MIN_POS, MAX_POS)

  elif zoneProgSetMenu == 3:                        
    if clearKey == 0:
      clearKey = 1
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()
    lcd.home()
    lcd.message("< ACTIVE INTGR >")    
    lcd.message("\n")
    
    if get_active_integration() == 1:
        lcd.message("     [ON]       ")
    elif get_active_integration() == 0:
        lcd.message("     [OFF]      ")        
        
    if keypressed == "B":
      keypressed = None
      
      if get_active_integration() == 1:
          set_active_integration(0)
      elif get_active_integration() == 0:
          set_active_integration(1)

    zoneProgSetMenu = menuPositionUpDn(MIN_POS, MAX_POS)


  elif zoneProgSetMenu == 4:                        
    if clearKey == 0:
      clearKey = 1
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()
    lcd.home()
    lcd.message("<ACT INT HV-NVR>")    
    lcd.message("\n")
    
    if logical_params_module.get_parameter("active_integration_hikvision_nvr") == 1:
        lcd.message("     [ON]       ")
    elif logical_params_module.get_parameter("active_integration_hikvision_nvr") == 0:
        lcd.message("     [OFF]      ")        
        
    if keypressed == "B":
      keypressed = None
      
      if logical_params_module.get_parameter("active_integration_hikvision_nvr") == 1:
          logical_params_module.set_parameter("active_integration_hikvision_nvr", 0)
          _restart_integration_containers(
              "dexter-nvr-hikvision","dexter-nvr-hikvision-field",
              "dexter-nvr-hik-lite","dexter-sd-hikvision","dexter-rtc-hikvision")
          logger.info("[active_integration] active_integration_hikvision_nvr=0 — restarted containers")
      elif logical_params_module.get_parameter("active_integration_hikvision_nvr") == 0:
          logical_params_module.set_parameter("active_integration_hikvision_nvr", 1)
          _restart_integration_containers(
              "dexter-nvr-hikvision","dexter-nvr-hikvision-field",
              "dexter-nvr-hik-lite","dexter-sd-hikvision","dexter-rtc-hikvision")
          logger.info("[active_integration] active_integration_hikvision_nvr=1 — restarted containers")

    zoneProgSetMenu = menuPositionUpDn(MIN_POS, MAX_POS)


  elif zoneProgSetMenu == 5:                        
    if clearKey == 0:
      clearKey = 1
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()
    lcd.home()
    lcd.message("<ACT INT HV-BIO>")        
    lcd.message("\n")
    
    if logical_params_module.get_parameter("active_integration_hikvision_biometric") == 1:
        lcd.message("     [ON]       ")
    elif logical_params_module.get_parameter("active_integration_hikvision_biometric") == 0:
        lcd.message("     [OFF]      ")        
        
    if keypressed == "B":
      keypressed = None
      
      if logical_params_module.get_parameter("active_integration_hikvision_biometric") == 1:
          logical_params_module.set_parameter("active_integration_hikvision_biometric", 0)
          _restart_integration_containers("dexter-nvr-hikvision-bacs")
          logger.info("[active_integration] active_integration_hikvision_biometric=0 — restarted containers")
      elif logical_params_module.get_parameter("active_integration_hikvision_biometric") == 0:
          logical_params_module.set_parameter("active_integration_hikvision_biometric", 1)
          _restart_integration_containers("dexter-nvr-hikvision-bacs")
          logger.info("[active_integration] active_integration_hikvision_biometric=1 — restarted containers")

    zoneProgSetMenu = menuPositionUpDn(MIN_POS, MAX_POS)


  elif zoneProgSetMenu == 6:                        
    if clearKey == 0:
      clearKey = 1
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()
    lcd.home()
    lcd.message("<ACT INT DU-NVR>")    

    lcd.message("\n")
    
    if logical_params_module.get_parameter("active_integration_dahua_nvr") == 1:
        lcd.message("     [ON]       ")
    elif logical_params_module.get_parameter("active_integration_dahua_nvr") == 0:
        lcd.message("     [OFF]      ")        
        
    if keypressed == "B":
      keypressed = None
      
      if logical_params_module.get_parameter("active_integration_dahua_nvr") == 1:
          logical_params_module.set_parameter("active_integration_dahua_nvr", 0)
          _restart_integration_containers(
              "dexter-nvr-dahua","dexter-extract-dahua",
              "dexter-sd-dahua","dexter-rtc-dahua","dexter-rec-dahua")
          logger.info("[active_integration] active_integration_dahua_nvr=0 — restarted containers")
      elif logical_params_module.get_parameter("active_integration_dahua_nvr") == 0:
          logical_params_module.set_parameter("active_integration_dahua_nvr", 1)
          _restart_integration_containers(
              "dexter-nvr-dahua","dexter-extract-dahua",
              "dexter-sd-dahua","dexter-rtc-dahua","dexter-rec-dahua")
          logger.info("[active_integration] active_integration_dahua_nvr=1 — restarted containers")

    zoneProgSetMenu = menuPositionUpDn(MIN_POS, MAX_POS)    

  elif zoneProgSetMenu == 7:                        
    if clearKey == 0:
      clearKey = 1
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()
    lcd.home()
    lcd.message("<ACT INT CP-NVR>")    

    lcd.message("\n")
    
    if logical_params_module.get_parameter("active_integration_cp_plus_nvr") == 1:
        lcd.message("     [ON]       ")
    elif logical_params_module.get_parameter("active_integration_cp_plus_nvr") == 0:
        lcd.message("     [OFF]      ")        
        
    if keypressed == "B":
      keypressed = None
      
      if logical_params_module.get_parameter("active_integration_cp_plus_nvr") == 1:
          logical_params_module.set_parameter("active_integration_cp_plus_nvr", 0)
          _restart_integration_containers(
              "dexter-nvr-cpplus","dexter-extract-cpplus",
              "dexter-sd-cpplus","dexter-rtc-cpplus","dexter-rec-cpplus")
          logger.info("[active_integration] active_integration_cp_plus_nvr=0 — restarted containers")
      elif logical_params_module.get_parameter("active_integration_cp_plus_nvr") == 0:
          logical_params_module.set_parameter("active_integration_cp_plus_nvr", 1)
          _restart_integration_containers(
              "dexter-nvr-cpplus","dexter-extract-cpplus",
              "dexter-sd-cpplus","dexter-rtc-cpplus","dexter-rec-cpplus")
          logger.info("[active_integration] active_integration_cp_plus_nvr=1 — restarted containers")

    zoneProgSetMenu = menuPositionUpDn(MIN_POS, MAX_POS)  


  elif zoneProgSetMenu == 8:                        
    if clearKey == 0:
      clearKey = 1
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()
    lcd.home()
    lcd.message("<ACT INT TX-BAS>")    
    lcd.message("\n")

    _texecom_flag = logical_params_module.get_parameter("active_integration_texecom_bas")
    if _texecom_flag == 1:
        lcd.message("     [ON]       ")
    elif _texecom_flag == 0:
        lcd.message("     [OFF]      ")
    else:
        lcd.message("     [OFF]      ")
        logical_params_module.set_parameter("active_integration_texecom_bas", 0)

    if keypressed == "B":
      keypressed = None
      _texecom_flag = logical_params_module.get_parameter("active_integration_texecom_bas")
      if _texecom_flag == 1:
          logical_params_module.set_parameter("active_integration_texecom_bas", 0)
          _restart_integration_containers("dexter-texecom-bas")
          logger.info("[active_integration] texecom_bas=0 — restarted containers")
      else:
          logical_params_module.set_parameter("active_integration_texecom_bas", 1)
          _restart_integration_containers("dexter-texecom-bas")
          logger.info("[active_integration] texecom_bas=1 — restarted containers")

    zoneProgSetMenu = menuPositionUpDn(MIN_POS, MAX_POS)


  elif zoneProgSetMenu == 9:                        
    if clearKey == 0:
      clearKey = 1
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()
    lcd.home()
    lcd.message("<ACT INT AM-BAS>")    
    lcd.message("\n")

    _amc_flag = logical_params_module.get_parameter("active_integration_amc_bas")
    if _amc_flag == 1:
        lcd.message("     [ON]       ")
    elif _amc_flag == 0:
        lcd.message("     [OFF]      ")
    else:
        lcd.message("     [OFF]      ")
        logical_params_module.set_parameter("active_integration_amc_bas", 0)

    if keypressed == "B":
      keypressed = None
      _amc_flag = logical_params_module.get_parameter("active_integration_amc_bas")
      if _amc_flag == 1:
          logical_params_module.set_parameter("active_integration_amc_bas", 0)
          _restart_integration_containers("dexter-amc")
          logger.info("[active_integration] amc_bas=0 — restarted containers")
      else:
          logical_params_module.set_parameter("active_integration_amc_bas", 1)
          _restart_integration_containers("dexter-amc")
          logger.info("[active_integration] amc_bas=1 — restarted containers")

    zoneProgSetMenu = menuPositionUpDn(MIN_POS, MAX_POS)


  elif zoneProgSetMenu == 10:                        
    if clearKey == 0:
      clearKey = 1
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()
    lcd.home()
    lcd.message("<ACT INT DS-BAS>")    
    lcd.message("\n")

    _dsc_flag = logical_params_module.get_parameter("active_integration_dsc_neo_bas")
    if _dsc_flag == 1:
        lcd.message("     [ON]       ")
    elif _dsc_flag == 0:
        lcd.message("     [OFF]      ")
    else:
        lcd.message("     [OFF]      ")
        logical_params_module.set_parameter("active_integration_dsc_neo_bas", 0)

    if keypressed == "B":
      keypressed = None
      _dsc_flag = logical_params_module.get_parameter("active_integration_dsc_neo_bas")
      if _dsc_flag == 1:
          logical_params_module.set_parameter("active_integration_dsc_neo_bas", 0)
          _restart_integration_containers("dexter-dsc-neo-bas")
          logger.info("[active_integration] dsc_neo_bas=0 — restarted containers")
      else:
          logical_params_module.set_parameter("active_integration_dsc_neo_bas", 1)
          _restart_integration_containers("dexter-dsc-neo-bas")
          logger.info("[active_integration] dsc_neo_bas=1 — restarted containers")

    zoneProgSetMenu = menuPositionUpDn(MIN_POS, MAX_POS)


  elif zoneProgSetMenu == 11:
    if clearKey == 0:
      clearKey = 1
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()
    lcd.home()
    lcd.message("<ACT INT HK-BAS>")
    lcd.message("\n")

    _hik_flag = logical_params_module.get_parameter("active_integration_hik_bas")
    if _hik_flag == 1:
        lcd.message("     [ON]       ")
    elif _hik_flag == 0:
        lcd.message("     [OFF]      ")
    else:
        lcd.message("     [OFF]      ")
        logical_params_module.set_parameter("active_integration_hik_bas", 0)

    if keypressed == "B":
      keypressed = None
      _hik_flag = logical_params_module.get_parameter("active_integration_hik_bas")
      if _hik_flag == 1:
          logical_params_module.set_parameter("active_integration_hik_bas", 0)
          _restart_integration_containers("dexter-hik-bas","dexter-rtc-hik-bas")
          logger.info("[active_integration] hik_bas=0 — restarted containers")
      else:
          logical_params_module.set_parameter("active_integration_hik_bas", 1)
          _restart_integration_containers("dexter-hik-bas","dexter-rtc-hik-bas")
          logger.info("[active_integration] hik_bas=1 — restarted containers")

    zoneProgSetMenu = menuPositionUpDn(MIN_POS, MAX_POS)


  elif zoneProgSetMenu == 12:   
    lcd.home()
    lcd.message("<     EXIT      ")
    lcd.message("\n")
    lcd.message("    [ENTER]     ")

    zoneProgSetMenu = menuPositionUpDn(MIN_POS, MAX_POS)
    if keypressed == "B":
      keypressed = None

      clear_all_data_flag = 0
      
      zoneProgSetMenu  = 0
      global menuCodeSelectState
      rtcProgSetMenu = 0
      menuSubState = 2
      menuCurrentPos = 2
      keypadScanning(0,0,0,0,'clear')            
      lcd.clear()
      lcd.home()


def progZoneSettings():

  global menuMainState
  global menuCurrentPos
  global keypressed
  global keyDetect
  global GuserSetState
  global menuSubState
  global GmainStateState
  global clearKey
  global toggleBit500mSecSec
  global zoneProgSetMenu 
  global zoneSettings

  
  MIN_POS = 0
  MAX_POS = 48

  # ZONE 1
  if zoneProgSetMenu == 0:                          #1 / 0
    if clearKey == 0:
      clearKey = 1
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()
    lcd.home()
    lcd.message("    Zone  1    >")
    lcd.message("\n")
    if zoneSettings[0] == 1:
      lcd.message("    [ACTIVE]    ")
    else:            
      lcd.message("   [DE-ACTIVE]  ")
    if keypressed == "B":
      keypressed = None
      if zoneSettings[0] == 1:
        zoneSettings[0] = 0
      elif zoneSettings[0] == 0:
        zoneSettings[0] = 1   
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()                
    zoneProgSetMenu = menuPositionUpDn(MIN_POS, MAX_POS)

  elif zoneProgSetMenu == 1:                        #2 / 1
    if clearKey == 1:
      clearKey = 0
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()
    lcd.home()
    lcd.message("<    Zone  1   >")
    lcd.message("\n")
    if zoneSettings[1] == 1:
      lcd.message("  [BUZZER ON]  ")
    else:            
      lcd.message("  [BUZZER OFF]  ")
    if keypressed == "B":
      keypressed = None
      if zoneSettings[1] == 1:
        zoneSettings[1] = 0
      elif zoneSettings[1] == 0:
        zoneSettings[1] = 1               
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()                
    zoneProgSetMenu = menuPositionUpDn(MIN_POS, MAX_POS)

  elif zoneProgSetMenu == 2:                        #3 / 2
    if clearKey == 1:
      clearKey = 0
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()
    lcd.home()
    lcd.message("< Device  Type >")
    lcd.message("\n")
    if zoneSettings[2] == 1:
      lcd.message("      [BAS]     ")
    elif zoneSettings[2] == 2:            
      lcd.message("      [FAS]     ")
    elif zoneSettings[2] == 3:            
      lcd.message("  [TIME  LOCK]  ")
    elif zoneSettings[2] == 4:            
      lcd.message("[ACCESS CONTROL]")
    elif zoneSettings[2] == 6:            
      lcd.message("      [IAS]     ")
    else:
      lcd.message("      [NONE]    ")      

    if keypressed == "1":
        keypressed = None
        zoneSettings[2] = 1
    elif keypressed == "2":
        keypressed = None
        zoneSettings[2] = 2
    elif keypressed == "3":
        keypressed = None
        zoneSettings[2] = 3
    elif keypressed == "4":
        keypressed = None
        zoneSettings[2] = 4
    elif keypressed == "6":
        keypressed = None
        zoneSettings[2] = 6
      
    if keypressed == "B":
      keypressed = None

      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()                
    zoneProgSetMenu = menuPositionUpDn(MIN_POS, MAX_POS)

  # ZONE 2
  elif zoneProgSetMenu == 3:                    #4 / 3
    if clearKey == 0:
      clearKey = 1
      keypadScanning(0,0,0,0,'clear')
      keyDetect = 0
      lcd.clear()
      lcd.home()
    lcd.home()
    lcd.message("<    Zone  2   >")
    lcd.message("\n")
    if zoneSettings[3] == 1:
      lcd.message("    [ACTIVE]    ")
    else:            
      lcd.message("   [DE-ACTIVE]  ")
    if keypressed == "B":
      keypressed = None
      if zoneSettings[3] == 1:
        zoneSettings[3] = 0
      elif zoneSettings[3] == 0:
        zoneSettings[3] = 1   
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()                
    zoneProgSetMenu = menuPositionUpDn(MIN_POS, MAX_POS)

  elif zoneProgSetMenu == 4:                    #5 / 4
    if clearKey == 1:
      clearKey = 0
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()
    lcd.home()
    lcd.message("<    Zone  2   >")
    lcd.message("\n")
    if zoneSettings[4] == 1:
      lcd.message("  [BUZZER ON]  ")
    else:            
      lcd.message("  [BUZZER OFF]  ")
    if keypressed == "B":
      keypressed = None
      if zoneSettings[4] == 1:
        zoneSettings[4] = 0
      elif zoneSettings[4] == 0:
        zoneSettings[4] = 1               
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()                
    zoneProgSetMenu = menuPositionUpDn(MIN_POS, MAX_POS)

  elif zoneProgSetMenu == 5:                    #6 / 5
    if clearKey == 1:
      clearKey = 0
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()
    lcd.home()
    lcd.message("< Device  Type >")
    lcd.message("\n")
    if zoneSettings[5] == 1:
      lcd.message("      [BAS]     ")
    elif zoneSettings[5] == 2:            
      lcd.message("      [FAS]     ")
    elif zoneSettings[5] == 3:            
      lcd.message("  [TIME  LOCK]  ")
    elif zoneSettings[5] == 4:            
      lcd.message("[ACCESS CONTROL]")
    elif zoneSettings[5] == 6:            
      lcd.message("      [IAS]     ")      
    else:
      lcd.message("      [NONE]    ")      

    if keypressed == "1":
        keypressed = None
        zoneSettings[5] = 1
    elif keypressed == "2":
        keypressed = None
        zoneSettings[5] = 2
    elif keypressed == "3":
        keypressed = None
        zoneSettings[5] = 3
    elif keypressed == "4":
        keypressed = None
        zoneSettings[5] = 4
    elif keypressed == "6":
        keypressed = None
        zoneSettings[5] = 6
      
    if keypressed == "B":
      keypressed = None

      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()                
    zoneProgSetMenu = menuPositionUpDn(MIN_POS, MAX_POS)

  # ZONE 3
  elif zoneProgSetMenu == 6:                #7  / 6
    if clearKey == 0:
      clearKey = 1
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()
    lcd.home()
    lcd.message("<    Zone  3   >")
    lcd.message("\n")
    if zoneSettings[6] == 1:
      lcd.message("    [ACTIVE]    ")
    else:            
      lcd.message("   [DE-ACTIVE]  ")
    if keypressed == "B":
      keypressed = None
      if zoneSettings[6] == 1:
        zoneSettings[6] = 0
      elif zoneSettings[6] == 0:
        zoneSettings[6] = 1   
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()                
    zoneProgSetMenu = menuPositionUpDn(MIN_POS, MAX_POS)
    
  elif zoneProgSetMenu == 7:                #8 / 7
    if clearKey == 1:
      clearKey = 0
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()
    lcd.home()
    lcd.message("<    Zone  3   >")
    lcd.message("\n")
    if zoneSettings[7] == 1:
      lcd.message("  [BUZZER ON]  ")
    else:            
      lcd.message("  [BUZZER OFF]  ")
    if keypressed == "B":
      keypressed = None
      if zoneSettings[7] == 1:
        zoneSettings[7] = 0
      elif zoneSettings[7] == 0:
        zoneSettings[7] = 1               
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()                
    zoneProgSetMenu = menuPositionUpDn(MIN_POS, MAX_POS)

  elif zoneProgSetMenu == 8:                #9 / 8
    if clearKey == 1:
      clearKey = 0
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()
    lcd.home()
    lcd.message("< Device  Type >")
    lcd.message("\n")
    if zoneSettings[8] == 1:
      lcd.message("      [BAS]     ")
    elif zoneSettings[8] == 2:            
      lcd.message("      [FAS]     ")
    elif zoneSettings[8] == 3:            
      lcd.message("  [TIME  LOCK]  ")
    elif zoneSettings[8] == 4:            
      lcd.message("[ACCESS CONTROL]")
    elif zoneSettings[8] == 6:            
      lcd.message("      [IAS]     ")      
    else:
      lcd.message("      [NONE]    ")      

    if keypressed == "1":
        keypressed = None
        zoneSettings[8] = 1
    elif keypressed == "2":
        keypressed = None
        zoneSettings[8] = 2
    elif keypressed == "3":
        keypressed = None
        zoneSettings[8] = 3
    elif keypressed == "4":
        keypressed = None
        zoneSettings[8] = 4
    elif keypressed == "6":
        keypressed = None
        zoneSettings[8] = 6
 
    if keypressed == "B":
      keypressed = None

      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()                
    zoneProgSetMenu = menuPositionUpDn(MIN_POS, MAX_POS)

  # ZONE 4
  elif zoneProgSetMenu == 9:            #10 / 9
    if clearKey == 0:
      clearKey = 1
      keypadScanning(0,0,0,0,'clear')
      keyDetect = 0
      lcd.clear()
      lcd.home()
    lcd.home()
    lcd.message("<    Zone  4   >")
    lcd.message("\n")
    if zoneSettings[9] == 1:
      lcd.message("    [ACTIVE]    ")
    else:            
      lcd.message("   [DE-ACTIVE]  ")
    if keypressed == "B":
      keypressed = None
      if zoneSettings[9] == 1:
        zoneSettings[9] = 0
      elif zoneSettings[9] == 0:
        zoneSettings[9] = 1   
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()                
    zoneProgSetMenu = menuPositionUpDn(MIN_POS, MAX_POS)
    
  elif zoneProgSetMenu == 10:            #11 / 10
    if clearKey == 1:
      clearKey = 0
      keypadScanning(0,0,0,0,'clear')
      keyDetect = 0
      lcd.clear()
      lcd.home()
    lcd.home()
    lcd.message("<    Zone  4   >")
    lcd.message("\n")
    if zoneSettings[10] == 1:
      lcd.message("  [BUZZER ON]  ")
    else:            
      lcd.message("  [BUZZER OFF]  ")
    if keypressed == "B":
      keypressed = None
      if zoneSettings[10] == 1:
        zoneSettings[10] = 0
      elif zoneSettings[10] == 0:
        zoneSettings[10] = 1               
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()                
    zoneProgSetMenu = menuPositionUpDn(MIN_POS, MAX_POS)
    
  #----------------------------------------------------------------------  
  elif zoneProgSetMenu == 11:                #12 / 11
    if clearKey == 1:
      clearKey = 0
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()
    lcd.home()
    lcd.message("< Device  Type >")
    lcd.message("\n")
    if zoneSettings[11] == 1:
      lcd.message("      [BAS]     ")
    elif zoneSettings[11] == 2:            
      lcd.message("      [FAS]     ")
    elif zoneSettings[11] == 3:            
      lcd.message("  [TIME  LOCK]  ")
    elif zoneSettings[11] == 4:            
      lcd.message("[ACCESS CONTROL]")
    elif zoneSettings[11] == 6:            
      lcd.message("      [IAS]     ")      
    else:
      lcd.message("      [NONE]    ")      

    if keypressed == "1":
        keypressed = None
        zoneSettings[11] = 1
    elif keypressed == "2":
        keypressed = None
        zoneSettings[11] = 2
    elif keypressed == "3":
        keypressed = None
        zoneSettings[11] = 3
    elif keypressed == "4":
        keypressed = None
        zoneSettings[11] = 4
    elif keypressed == "6":
        keypressed = None
        zoneSettings[11] = 6
      
    if keypressed == "B":
      keypressed = None

      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()                
    zoneProgSetMenu = menuPositionUpDn(MIN_POS, MAX_POS)

  # ZONE 5
  elif zoneProgSetMenu == 12:            #13 / 12
    if clearKey == 0:
      clearKey = 1
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()
    lcd.home()
    lcd.message("<    Zone  5   >")
    lcd.message("\n")
    if zoneSettings[12] == 1:
      lcd.message("    [ACTIVE]    ")
    else:            
      lcd.message("   [DE-ACTIVE]  ")
    if keypressed == "B":
      keypressed = None
      if zoneSettings[12] == 1:
        zoneSettings[12] = 0
      elif zoneSettings[12] == 0:
        zoneSettings[12] = 1   
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()                
    zoneProgSetMenu = menuPositionUpDn(MIN_POS, MAX_POS)
    
  elif zoneProgSetMenu == 13:            #14 / 13
    if clearKey == 1:
      clearKey = 0
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()
    lcd.home()
    lcd.message("<    Zone  5   >")
    lcd.message("\n")
    if zoneSettings[13] == 1:
      lcd.message("  [BUZZER ON]  ")
    else:            
      lcd.message("  [BUZZER OFF]  ")
    if keypressed == "B":
      keypressed = None
      if zoneSettings[13] == 1:
        zoneSettings[13] = 0
      elif zoneSettings[13] == 0:
        zoneSettings[13] = 1               
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()                
    zoneProgSetMenu = menuPositionUpDn(MIN_POS, MAX_POS)

  elif zoneProgSetMenu == 14:            #15 / 14
    if clearKey == 1:
      clearKey = 0
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()
    lcd.home()
    lcd.message("< Device  Type >")
    lcd.message("\n")
    if zoneSettings[14] == 1:
      lcd.message("      [BAS]     ")
    elif zoneSettings[14] == 2:            
      lcd.message("      [FAS]     ")
    elif zoneSettings[14] == 3:            
      lcd.message("  [TIME  LOCK]  ")
    elif zoneSettings[14] == 4:            
      lcd.message("[ACCESS CONTROL]")
    elif zoneSettings[14] == 6:            
      lcd.message("      [IAS]     ")      
    else:
      lcd.message("      [NONE]    ")      

    if keypressed == "1":
        keypressed = None
        zoneSettings[14] = 1
    elif keypressed == "2":
        keypressed = None
        zoneSettings[14] = 2
    elif keypressed == "3":
        keypressed = None
        zoneSettings[14] = 3
    elif keypressed == "4":
        keypressed = None
        zoneSettings[14] = 4
    elif keypressed == "6":
        keypressed = None
        zoneSettings[14] = 6
      
    if keypressed == "B":
      keypressed = None

      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()                
    zoneProgSetMenu = menuPositionUpDn(MIN_POS, MAX_POS)

  # ZONE 6
  elif zoneProgSetMenu == 15:           #16 / 15
    if clearKey == 0:
      clearKey = 1
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()
    lcd.home()
    lcd.message("<    Zone  6   >")
    lcd.message("\n")
    if zoneSettings[15] == 1:
      lcd.message("    [ACTIVE]    ")
    else:            
      lcd.message("   [DE-ACTIVE]  ")
    if keypressed == "B":
      keypressed = None
      if zoneSettings[15] == 1:
        zoneSettings[15] = 0
      elif zoneSettings[15] == 0:
        zoneSettings[15] = 1   
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()                
    zoneProgSetMenu = menuPositionUpDn(MIN_POS, MAX_POS)
    
  elif zoneProgSetMenu == 16:           #17 / 16
    if clearKey == 1:
      clearKey = 0
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()
    lcd.home()
    lcd.message("<    Zone  6   >")
    lcd.message("\n")
    if zoneSettings[16] == 1:
      lcd.message("  [BUZZER ON]  ")
    else:            
      lcd.message("  [BUZZER OFF]  ")
    if keypressed == "B":
      keypressed = None
      if zoneSettings[16] == 1:
        zoneSettings[16] = 0
      elif zoneSettings[16] == 0:
        zoneSettings[16] = 1               
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()                
    zoneProgSetMenu = menuPositionUpDn(MIN_POS, MAX_POS)

  elif zoneProgSetMenu == 17:            #18 / 17
    if clearKey == 1:
      clearKey = 0
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()
    lcd.home()
    lcd.message("< Device  Type >")
    lcd.message("\n")
    if zoneSettings[17] == 1:
      lcd.message("      [BAS]     ")
    elif zoneSettings[17] == 2:            
      lcd.message("      [FAS]     ")
    elif zoneSettings[17] == 3:            
      lcd.message("  [TIME  LOCK]  ")
    elif zoneSettings[17] == 4:            
      lcd.message("[ACCESS CONTROL]")
    elif zoneSettings[17] == 6:            
      lcd.message("      [IAS]     ")      
    else:
      lcd.message("      [NONE]    ")      

    if keypressed == "1":
        keypressed = None
        zoneSettings[17] = 1
    elif keypressed == "2":
        keypressed = None
        zoneSettings[17] = 2
    elif keypressed == "3":
        keypressed = None
        zoneSettings[17] = 3
    elif keypressed == "4":
        keypressed = None
        zoneSettings[17] = 4
    elif keypressed == "6":
        keypressed = None
        zoneSettings[17] = 6
      
    if keypressed == "B":
      keypressed = None

      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()                
    zoneProgSetMenu = menuPositionUpDn(MIN_POS, MAX_POS)
    

  # ZONE 7
  elif zoneProgSetMenu == 18:           #18 / 17
    if clearKey == 0:
      clearKey = 1
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()
    lcd.home()
    lcd.message("<    Zone  7   >")
    lcd.message("\n")
    if zoneSettings[18] == 1:
      lcd.message("    [ACTIVE]    ")
    else:            
      lcd.message("   [DE-ACTIVE]  ")
    if keypressed == "B":
      keypressed = None
      if zoneSettings[18] == 1:
        zoneSettings[18] = 0
      elif zoneSettings[18] == 0:
        zoneSettings[18] = 1   
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()                
    zoneProgSetMenu = menuPositionUpDn(MIN_POS, MAX_POS)
    
  elif zoneProgSetMenu == 19:           #20 / 19
    if clearKey == 1:
      clearKey = 0
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()
    lcd.home()
    lcd.message("<    Zone  7   >")
    lcd.message("\n")
    if zoneSettings[19] == 1:
      lcd.message("  [BUZZER ON]  ")
    else:            
      lcd.message("  [BUZZER OFF]  ")
    if keypressed == "B":
      keypressed = None
      if zoneSettings[19] == 1:
        zoneSettings[19] = 0
      elif zoneSettings[19] == 0:
        zoneSettings[19] = 1               
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()                
    zoneProgSetMenu = menuPositionUpDn(MIN_POS, MAX_POS)

  elif zoneProgSetMenu == 20:            #21  / 20    
    if clearKey == 1:
      clearKey = 0
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()
    lcd.home()
    lcd.message("< Device  Type >")
    lcd.message("\n")

    zoneSettings[20] = 5
        
    if zoneSettings[20] == 1:
      lcd.message("      [BAS]     ")
    elif zoneSettings[20] == 2:            
      lcd.message("      [FAS]     ")
    elif zoneSettings[20] == 3:            
      lcd.message("  [TIME  LOCK]  ")
    elif zoneSettings[20] == 4:            
      lcd.message("[ACCESS CONTROL]")
    elif zoneSettings[20] == 5:            
      lcd.message("      [CCTV]    ")
    elif zoneSettings[20] == 6:            
      lcd.message("      [IAS]     ")      
    else:
      lcd.message("      [NONE]    ")      

    #keyDetect = keypadScanning(1,0,4,0)
    '''  
    if keypressed == "1":
        keypressed = None
        zoneSettings[20] = 1
    elif keypressed == "2":
        keypressed = None
        zoneSettings[20] = 2
    elif keypressed == "3":
        keypressed = None
        zoneSettings[20] = 3
    elif keypressed == "4":
        keypressed = None
        zoneSettings[20] = 4
    '''
    
    if keypressed == "B":
      keypressed = None

      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()                
    zoneProgSetMenu = menuPositionUpDn(MIN_POS, MAX_POS)
    

  # ZONE 8
  elif zoneProgSetMenu == 21:           #22 / 21
    if clearKey == 0:
      clearKey = 1
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()
    lcd.home()
    lcd.message("<    Zone  8   >")
    lcd.message("\n")
    if zoneSettings[21] == 1:
      lcd.message("    [ACTIVE]    ")
    else:            
      lcd.message("   [DE-ACTIVE]  ")
    if keypressed == "B":
      keypressed = None
      if zoneSettings[21] == 1:
        zoneSettings[21] = 0
      elif zoneSettings[21] == 0:
        zoneSettings[21] = 1   
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()                
    zoneProgSetMenu = menuPositionUpDn(MIN_POS, MAX_POS)
    
  elif zoneProgSetMenu == 22:           #23 / 22
    if clearKey == 1:
      clearKey = 0
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()
    lcd.home()
    lcd.message("<    Zone  8   >")
    lcd.message("\n")
    if zoneSettings[22] == 1:
      lcd.message("  [BUZZER ON]  ")
    else:            
      lcd.message("  [BUZZER OFF]  ")
    if keypressed == "B":
      keypressed = None
      if zoneSettings[22] == 1:
        zoneSettings[22] = 0
      elif zoneSettings[22] == 0:
        zoneSettings[22] = 1               
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()                
    zoneProgSetMenu = menuPositionUpDn(MIN_POS, MAX_POS)

  #----------------------------------------------------------------------  
  elif zoneProgSetMenu == 23:                #24 / 23
    if clearKey == 1:
      clearKey = 0
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()
    lcd.home()
    lcd.message("< Device  Type >")
    lcd.message("\n")
    zoneSettings[23] = 5
    if zoneSettings[23] == 1:
      lcd.message("      [BAS]     ")
    elif zoneSettings[23] == 2:            
      lcd.message("      [FAS]     ")
    elif zoneSettings[23] == 3:            
      lcd.message("  [TIME  LOCK]  ")
    elif zoneSettings[23] == 4:            
      lcd.message("[ACCESS CONTROL]")
    elif zoneSettings[23] == 5:            
      lcd.message("      [CCTV]    ")
    elif zoneSettings[23] == 6:            
      lcd.message("      [IAS]     ")      
    else:
      lcd.message("      [NONE]    ")      

    '''
    if keypressed == "1":
        keypressed = None
        zoneSettings[23] = 1
    elif keypressed == "2":
        keypressed = None
        zoneSettings[23] = 2
    elif keypressed == "3":
        keypressed = None
        zoneSettings[23] = 3
    elif keypressed == "4":
        keypressed = None
        zoneSettings[23] = 4
    '''
    
    if keypressed == "B":
      keypressed = None

      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()                
    zoneProgSetMenu = menuPositionUpDn(MIN_POS, MAX_POS)

  # ZONE 9
  if zoneProgSetMenu == 24:             #25 / 24
    if clearKey == 0:
      clearKey = 1
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()
    lcd.home()
    lcd.message("<    Zone  9   >")
    lcd.message("\n")
    if zoneSettings[24] == 1:
      lcd.message("    [ACTIVE]    ")
    else:            
      lcd.message("   [DE-ACTIVE]  ")
    if keypressed == "B":
      keypressed = None
      if zoneSettings[24] == 1:
        zoneSettings[24] = 0
      elif zoneSettings[24] == 0:
        zoneSettings[24] = 1   
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()                
    zoneProgSetMenu = menuPositionUpDn(MIN_POS, MAX_POS)
    
  elif zoneProgSetMenu == 25:           #26 / 25
    if clearKey == 1:
      clearKey = 0
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()
    lcd.home()
    lcd.message("<    Zone  9   >")
    lcd.message("\n")
    if zoneSettings[25] == 1:
      lcd.message("  [BUZZER ON]  ")
    else:            
      lcd.message("  [BUZZER OFF]  ")
    if keypressed == "B":
      keypressed = None
      if zoneSettings[25] == 1:
        zoneSettings[25] = 0
      elif zoneSettings[25] == 0:
        zoneSettings[25] = 1               
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()                
    zoneProgSetMenu = menuPositionUpDn(MIN_POS, MAX_POS)

  elif zoneProgSetMenu == 26:            #27 / 26
    if clearKey == 1:
      clearKey = 0
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()
    lcd.home()
    lcd.message("< Device  Type >")
    lcd.message("\n")
    if zoneSettings[26] == 1:
      lcd.message("      [BAS]     ")
    elif zoneSettings[26] == 2:            
      lcd.message("      [FAS]     ")
    elif zoneSettings[26] == 3:            
      lcd.message("  [TIME  LOCK]  ")
    elif zoneSettings[26] == 4:            
      lcd.message("[ACCESS CONTROL]")
    elif zoneSettings[26] == 6:            
      lcd.message("      [IAS]     ")      
    else:
      lcd.message("      [NONE]    ")      

    if keypressed == "1":
        keypressed = None
        zoneSettings[26] = 1
    elif keypressed == "2":
        keypressed = None
        zoneSettings[26] = 2
    elif keypressed == "3":
        keypressed = None
        zoneSettings[26] = 3
    elif keypressed == "4":
        keypressed = None
        zoneSettings[26] = 4
    elif keypressed == "6":
        keypressed = None
        zoneSettings[26] = 6

      
    if keypressed == "B":
      keypressed = None

      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()                
    zoneProgSetMenu = menuPositionUpDn(MIN_POS, MAX_POS)
    

  # ZONE 10
  elif zoneProgSetMenu == 27:           #28 / 27
    if clearKey == 0:
      clearKey = 1
      keypadScanning(0,0,0,0,'clear')
      keyDetect = 0
      lcd.clear()
      lcd.home()
    lcd.home()
    lcd.message("<    Zone  10  >")
    lcd.message("\n")
    if zoneSettings[27] == 1:
      lcd.message("    [ACTIVE]    ")
    else:            
      lcd.message("   [DE-ACTIVE]  ")
    if keypressed == "B":
      keypressed = None
      if zoneSettings[27] == 1:
        zoneSettings[27] = 0
      elif zoneSettings[27] == 0:
        zoneSettings[27] = 1   
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()                
    zoneProgSetMenu = menuPositionUpDn(MIN_POS, MAX_POS)


  elif zoneProgSetMenu == 28:           #29 / 28
    if clearKey == 1:
      clearKey = 0
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()
    lcd.home()
    lcd.message("<    Zone  10  >")
    lcd.message("\n")
    if zoneSettings[28] == 1:
      lcd.message("  [BUZZER ON]  ")
    else:            
      lcd.message("  [BUZZER OFF]  ")
    if keypressed == "B":
      keypressed = None
      if zoneSettings[28] == 1:
        zoneSettings[28] = 0
      elif zoneSettings[28] == 0:
        zoneSettings[28] = 1               
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()                
    zoneProgSetMenu = menuPositionUpDn(MIN_POS, MAX_POS)

  elif zoneProgSetMenu == 29:            #30 / 29
    if clearKey == 1:
      clearKey = 0
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()
    lcd.home()
    lcd.message("< Device  Type >")
    lcd.message("\n")
    if zoneSettings[29] == 1:
      lcd.message("      [BAS]     ")
    elif zoneSettings[29] == 2:            
      lcd.message("      [FAS]     ")
    elif zoneSettings[29] == 3:            
      lcd.message("  [TIME  LOCK]  ")
    elif zoneSettings[29] == 4:            
      lcd.message("[ACCESS CONTROL]")
    elif zoneSettings[29] == 6:            
      lcd.message("      [IAS]     ")      
    else:
      lcd.message("      [NONE]    ")      

    if keypressed == "1":
        keypressed = None
        zoneSettings[29] = 1
    elif keypressed == "2":
        keypressed = None
        zoneSettings[29] = 2
    elif keypressed == "3":
        keypressed = None
        zoneSettings[29] = 3
    elif keypressed == "4":
        keypressed = None
        zoneSettings[29] = 4
    elif keypressed == "6":
        keypressed = None
        zoneSettings[29] = 6
      
    if keypressed == "B":
      keypressed = None

      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()                
    zoneProgSetMenu = menuPositionUpDn(MIN_POS, MAX_POS)

  # ZONE 11
  elif zoneProgSetMenu == 30:           #31 / 30
    if clearKey == 0:
      clearKey = 1
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()
    lcd.home()
    lcd.message("<    Zone  11  >")
    lcd.message("\n")
    if zoneSettings[30] == 1:
      lcd.message("    [ACTIVE]    ")
    else:            
      lcd.message("   [DE-ACTIVE]  ")
    if keypressed == "B":
      keypressed = None
      if zoneSettings[30] == 1:
        zoneSettings[30] = 0
      elif zoneSettings[30] == 0:
        zoneSettings[30] = 1   
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()                
    zoneProgSetMenu = menuPositionUpDn(MIN_POS, MAX_POS)
    
  elif zoneProgSetMenu == 31:           #32 / 31
    if clearKey == 1:
      clearKey = 0
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()
    lcd.home()
    lcd.message("<    Zone  11  >")
    lcd.message("\n")
    if zoneSettings[31] == 1:
      lcd.message("  [BUZZER ON]  ")
    else:            
      lcd.message("  [BUZZER OFF]  ")
    if keypressed == "B":
      keypressed = None
      if zoneSettings[31] == 1:
        zoneSettings[31] = 0
      elif zoneSettings[31] == 0:
        zoneSettings[31] = 1               
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()                
    zoneProgSetMenu = menuPositionUpDn(MIN_POS, MAX_POS)

  elif zoneProgSetMenu == 32:            #33 / 32
    if clearKey == 1:
      clearKey = 0
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()
    lcd.home()
    lcd.message("< Device  Type >")
    lcd.message("\n")
    if zoneSettings[32] == 1:
      lcd.message("      [BAS]     ")
    elif zoneSettings[32] == 2:            
      lcd.message("      [FAS]     ")
    elif zoneSettings[32] == 3:            
      lcd.message("  [TIME  LOCK]  ")
    elif zoneSettings[32] == 4:            
      lcd.message("[ACCESS CONTROL]")
    elif zoneSettings[32] == 6:            
      lcd.message("      [IAS]     ")      
    else:
      lcd.message("      [NONE]    ")      

    if keypressed == "1":
        keypressed = None
        zoneSettings[32] = 1
    elif keypressed == "2":
        keypressed = None
        zoneSettings[32] = 2
    elif keypressed == "3":
        keypressed = None
        zoneSettings[32] = 3
    elif keypressed == "4":
        keypressed = None
        zoneSettings[32] = 4
    elif keypressed == "6":
        keypressed = None
        zoneSettings[32] = 6
      
    if keypressed == "B":
      keypressed = None

      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()                
    zoneProgSetMenu = menuPositionUpDn(MIN_POS, MAX_POS)
    

  # ZONE 12
  elif zoneProgSetMenu == 33:       #34 / 33
    if clearKey == 0:
      clearKey = 1
      keypadScanning(0,0,0,0,'clear')
      keyDetect = 0
      lcd.clear()
      lcd.home()
    lcd.home()
    lcd.message("<    Zone  12  >")
    lcd.message("\n")
    if zoneSettings[33] == 1:
      lcd.message("    [ACTIVE]    ")
    else:            
      lcd.message("   [DE-ACTIVE]  ")
    if keypressed == "B":
      keypressed = None
      if zoneSettings[33] == 1:
        zoneSettings[33] = 0
      elif zoneSettings[33] == 0:
        zoneSettings[33] = 1   
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()                
    zoneProgSetMenu = menuPositionUpDn(MIN_POS, MAX_POS)
    
  elif zoneProgSetMenu == 34:       #35 / 34
    if clearKey == 1:
      clearKey = 0
      keypadScanning(0,0,0,0,'clear')
      keyDetect = 0
      lcd.clear()
      lcd.home()
    lcd.home()
    lcd.message("<    Zone  12  >")
    lcd.message("\n")
    if zoneSettings[34] == 1:
      lcd.message("  [BUZZER ON]  ")
    else:            
      lcd.message("  [BUZZER OFF]  ")
    if keypressed == "B":
      keypressed = None
      if zoneSettings[34] == 1:
        zoneSettings[34] = 0
      elif zoneSettings[34] == 0:
        zoneSettings[34] = 1               
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()                
    zoneProgSetMenu = menuPositionUpDn(MIN_POS, MAX_POS)

  elif zoneProgSetMenu == 35:        #36 / 35
    if clearKey == 1:
      clearKey = 0
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()
    lcd.home()
    lcd.message("< Device  Type >")
    lcd.message("\n")
    if zoneSettings[35] == 1:
      lcd.message("      [BAS]     ")
    elif zoneSettings[35] == 2:            
      lcd.message("      [FAS]     ")
    elif zoneSettings[35] == 3:            
      lcd.message("  [TIME  LOCK]  ")
    elif zoneSettings[35] == 4:            
      lcd.message("[ACCESS CONTROL]")
    elif zoneSettings[35] == 6:            
      lcd.message("      [IAS]     ")      
    else:
      lcd.message("      [NONE]    ")      

    if keypressed == "1":
        keypressed = None
        zoneSettings[35] = 1
    elif keypressed == "2":
        keypressed = None
        zoneSettings[35] = 2
    elif keypressed == "3":
        keypressed = None
        zoneSettings[35] = 3
    elif keypressed == "4":
        keypressed = None
        zoneSettings[35] = 4
    elif keypressed == "6":
        keypressed = None
        zoneSettings[35] = 6
      
    if keypressed == "B":
      keypressed = None

      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()                
    zoneProgSetMenu = menuPositionUpDn(MIN_POS, MAX_POS)

  # ZONE 13
  elif zoneProgSetMenu == 36:       #37 / 36
    if clearKey == 0:
      clearKey = 1
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()
    lcd.home()
    lcd.message("<    Zone  13  >")
    lcd.message("\n")
    if zoneSettings[36] == 1:
      lcd.message("    [ACTIVE]    ")
    else:            
      lcd.message("   [DE-ACTIVE]  ")
    if keypressed == "B":
      keypressed = None
      if zoneSettings[36] == 1:
        zoneSettings[36] = 0
      elif zoneSettings[36] == 0:
        zoneSettings[36] = 1   
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()                
    zoneProgSetMenu = menuPositionUpDn(MIN_POS, MAX_POS)
    
  elif zoneProgSetMenu == 37:       #38 / 37
    if clearKey == 1:
      clearKey = 0
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()
    lcd.home()
    lcd.message("<    Zone  13  >")
    lcd.message("\n")
    if zoneSettings[37] == 1:
      lcd.message("  [BUZZER ON]  ")
    else:            
      lcd.message("  [BUZZER OFF]  ")
    if keypressed == "B":
      keypressed = None
      if zoneSettings[37] == 1:
        zoneSettings[37] = 0
      elif zoneSettings[37] == 0:
        zoneSettings[37] = 1               
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()                
    zoneProgSetMenu = menuPositionUpDn(MIN_POS, MAX_POS)

  elif zoneProgSetMenu == 38:        #39 / 38
    if clearKey == 1:
      clearKey = 0
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()
    lcd.home()
    lcd.message("< Device  Type >")
    lcd.message("\n")
    if zoneSettings[38] == 1:
      lcd.message("      [BAS]     ")
    elif zoneSettings[38] == 2:            
      lcd.message("      [FAS]     ")
    elif zoneSettings[38] == 3:            
      lcd.message("  [TIME  LOCK]  ")
    elif zoneSettings[38] == 4:            
      lcd.message("[ACCESS CONTROL]")
    elif zoneSettings[38] == 6:            
      lcd.message("      [IAS]     ")      
    else:
      lcd.message("      [NONE]    ")      

    if keypressed == "1":
        keypressed = None
        zoneSettings[38] = 1
    elif keypressed == "2":
        keypressed = None
        zoneSettings[38] = 2
    elif keypressed == "3":
        keypressed = None
        zoneSettings[38] = 3
    elif keypressed == "4":
        keypressed = None
        zoneSettings[38] = 4
    elif keypressed == "6":
        keypressed = None
        zoneSettings[38] = 6
      
    if keypressed == "B":
      keypressed = None

      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()                
    zoneProgSetMenu = menuPositionUpDn(MIN_POS, MAX_POS)

  # ZONE 14
  elif zoneProgSetMenu == 39:       #40 / 39
    if clearKey == 0:
      clearKey = 1
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()
    lcd.home()
    lcd.message("<    Zone  14  >")
    lcd.message("\n")
    if zoneSettings[39] == 1:
      lcd.message("    [ACTIVE]    ")
    else:            
      lcd.message("   [DE-ACTIVE]  ")
    if keypressed == "B":
      keypressed = None
      if zoneSettings[39] == 1:
        zoneSettings[39] = 0
      elif zoneSettings[39] == 0:
        zoneSettings[39] = 1   
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()                
    zoneProgSetMenu = menuPositionUpDn(MIN_POS, MAX_POS)
    
  elif zoneProgSetMenu == 40:       #41 / 40
    if clearKey == 1:
      clearKey = 0
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()
    lcd.home()
    lcd.message("<    Zone  14  >")
    lcd.message("\n")
    if zoneSettings[40] == 1:
      lcd.message("  [BUZZER ON]  ")
    else:            
      lcd.message("  [BUZZER OFF]  ")
    if keypressed == "B":
      keypressed = None
      if zoneSettings[40] == 1:
        zoneSettings[40] = 0
      elif zoneSettings[40] == 0:
        zoneSettings[40] = 1               
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()                
    zoneProgSetMenu = menuPositionUpDn(MIN_POS, MAX_POS)

  elif zoneProgSetMenu == 41:        #42 / 41
    if clearKey == 1:
      clearKey = 0
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()
    lcd.home()
    lcd.message("< Device  Type >")
    lcd.message("\n")
    if zoneSettings[41] == 1:
      lcd.message("      [BAS]     ")
    elif zoneSettings[41] == 2:            
      lcd.message("      [FAS]     ")
    elif zoneSettings[41] == 3:            
      lcd.message("  [TIME  LOCK]  ")
    elif zoneSettings[41] == 4:            
      lcd.message("[ACCESS CONTROL]")
    elif zoneSettings[41] == 6:            
      lcd.message("      [IAS]     ")      
    else:
      lcd.message("      [NONE]    ")      

    if keypressed == "1":
        keypressed = None
        zoneSettings[41] = 1
    elif keypressed == "2":
        keypressed = None
        zoneSettings[41] = 2
    elif keypressed == "3":
        keypressed = None
        zoneSettings[41] = 3
    elif keypressed == "4":
        keypressed = None
        zoneSettings[41] = 4
    elif keypressed == "6":
        keypressed = None
        zoneSettings[41] = 6
      
    if keypressed == "B":
      keypressed = None

      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()                
    zoneProgSetMenu = menuPositionUpDn(MIN_POS, MAX_POS)

  # ZONE 15
  elif zoneProgSetMenu == 42:   #43 / 42
    if clearKey == 0:
      clearKey = 1
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()
    lcd.home()
    lcd.message("<    Zone  15  >")
    lcd.message("\n")
    if zoneSettings[42] == 1:
      lcd.message("    [ACTIVE]    ")
    else:            
      lcd.message("   [DE-ACTIVE]  ")
    if keypressed == "B":
      keypressed = None
      if zoneSettings[42] == 1:
        zoneSettings[42] = 0
      elif zoneSettings[42] == 0:
        zoneSettings[42] = 1   
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()                
    zoneProgSetMenu = menuPositionUpDn(MIN_POS, MAX_POS)
    
  elif zoneProgSetMenu == 43:   #44 / 43
    if clearKey == 1:
      clearKey = 0
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()
    lcd.home()
    lcd.message("<    Zone  15  >")
    lcd.message("\n")
    if zoneSettings[43] == 1:
      lcd.message("  [BUZZER ON]  ")
    else:            
      lcd.message("  [BUZZER OFF]  ")
    if keypressed == "B":
      keypressed = None
      if zoneSettings[43] == 1:
        zoneSettings[43] = 0
      elif zoneSettings[43] == 0:
        zoneSettings[43] = 1               
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()                
    zoneProgSetMenu = menuPositionUpDn(MIN_POS, MAX_POS)

  #----------------------------------------------------------------------  
  elif zoneProgSetMenu == 44:                #45 / 44
    if clearKey == 1:
      clearKey = 0
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()
    lcd.home()
    lcd.message("< Device  Type >")
    lcd.message("\n")
    
    zoneSettings[44] = 5
        
    if zoneSettings[44] == 1:
      lcd.message("      [BAS]     ")
    elif zoneSettings[44] == 2:            
      lcd.message("      [FAS]     ")
    elif zoneSettings[44] == 3:            
      lcd.message("  [TIME  LOCK]  ")
    elif zoneSettings[44] == 4:            
      lcd.message("[ACCESS CONTROL]")
    elif zoneSettings[44] == 5:            
      lcd.message("      [CCTV]    ")
    elif zoneSettings[44] == 6:            
      lcd.message("      [IAS]     ")      
    else:
      lcd.message("      [NONE]    ")      

    '''    
    if keypressed == "1":
        keypressed = None
        zoneSettings[44] = 1
    elif keypressed == "2":
        keypressed = None
        zoneSettings[44] = 2
    elif keypressed == "3":
        keypressed = None
        zoneSettings[44] = 3
    elif keypressed == "4":
        keypressed = None
        zoneSettings[44] = 4
    '''
    
    if keypressed == "B":
      keypressed = None

      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()                
    zoneProgSetMenu = menuPositionUpDn(MIN_POS, MAX_POS)

  # ZONE 16
  elif zoneProgSetMenu == 45:   #46 / 46
    if clearKey == 0:
      clearKey = 1
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()
    lcd.home()
    lcd.message("<    Zone  16  >")
    lcd.message("\n")
    if zoneSettings[45] == 1:
      lcd.message("    [ACTIVE]    ")
    else:            
      lcd.message("   [DE-ACTIVE]  ")
    if keypressed == "B":
      keypressed = None
      if zoneSettings[45] == 1:
        zoneSettings[45] = 0
      elif zoneSettings[45] == 0:
        zoneSettings[45] = 1   
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()                
    zoneProgSetMenu = menuPositionUpDn(MIN_POS, MAX_POS)
    
  elif zoneProgSetMenu == 46:   #47 / 46
    if clearKey == 1:
      clearKey = 0
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()
    lcd.home()
    lcd.message("<    Zone  16  >")
    lcd.message("\n")
    if zoneSettings[46] == 1:
      lcd.message("  [BUZZER ON]  ")
    else:            
      lcd.message("  [BUZZER OFF]  ")
    if keypressed == "B":
      keypressed = None
      if zoneSettings[46] == 1:
        zoneSettings[46] = 0
      elif zoneSettings[46] == 0:
        zoneSettings[46] = 1               
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()                
    zoneProgSetMenu = menuPositionUpDn(MIN_POS, MAX_POS)

  elif zoneProgSetMenu == 47:    #48 / 47
    if clearKey == 1:
      clearKey = 0
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()
    lcd.home()
    lcd.message("< Device  Type >")
    lcd.message("\n")
    zoneSettings[47] = 5
    if zoneSettings[47] == 1:
      lcd.message("      [BAS]     ")
    elif zoneSettings[47] == 2:            
      lcd.message("      [FAS]     ")
    elif zoneSettings[47] == 3:            
      lcd.message("  [TIME  LOCK]  ")
    elif zoneSettings[47] == 4:            
      lcd.message("[ACCESS CONTROL]")
    elif zoneSettings[47] == 5:            
      lcd.message("      [CCTV]    ")
    elif zoneSettings[47] == 6:            
      lcd.message("      [IAS]     ")      
    else:
      lcd.message("      [NONE]    ")      

    '''  
    if keypressed == "1":
        keypressed = None
        zoneSettings[47] = 1
    elif keypressed == "2":
        keypressed = None
        zoneSettings[47] = 2
    elif keypressed == "3":
        keypressed = None
        zoneSettings[47] = 3
    elif keypressed == "4":
        keypressed = None
        zoneSettings[47] = 4
    '''              
    if keypressed == "B":
      keypressed = None

      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()                
    zoneProgSetMenu = menuPositionUpDn(MIN_POS, MAX_POS)
    
    
  elif zoneProgSetMenu == 48:   #49 / 48 
    lcd.home()
    lcd.message("<     EXIT      ")
    lcd.message("\n")
    lcd.message("    [ENTER]     ")
    zoneProgSetMenu = menuPositionUpDn(MIN_POS, MAX_POS)
    if keypressed == "B":
      keypressed = None
      zoneProgSetMenu  = 0
      zoneSettingsFileRW('write')
      global menuCodeSelectState
      rtcProgSetMenu = 0
      menuSubState = 0
      menuCurrentPos = 0
      keypadScanning(0,0,0,0,'clear')            
      lcd.clear()
      lcd.home()


def progPowerZoneSettings():

  global menuMainState
  global menuCurrentPos
  global keypressed
  global keyDetect
  global GuserSetState
  global menuSubState
  global GmainStateState
  global clearKey
  global toggleBit500mSecSec
  global zoneProgSetMenu 
  global powerZoneSettings

  
  MIN_POS = 0
  MAX_POS = 24

  # ZONE 1
  if zoneProgSetMenu == 0:                          #1 / 0
    if clearKey == 0:
      clearKey = 1
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()
    lcd.home()
    lcd.message("  Power Zone 1 >")
    lcd.message("\n")
    if powerZoneSettings[0] == 1:
      lcd.message("    [ACTIVE]    ")
    else:            
      lcd.message("   [DE-ACTIVE]  ")
    if keypressed == "B":
      keypressed = None
      if powerZoneSettings[0] == 1:
        powerZoneSettings[0] = 0
      elif powerZoneSettings[0] == 0:
        powerZoneSettings[0] = 1   
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()                
    zoneProgSetMenu = menuPositionUpDn(MIN_POS, MAX_POS)

  elif zoneProgSetMenu == 1:                        #2 / 1
    if clearKey == 1:
      clearKey = 0
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()
    lcd.home()
    lcd.message("< Power Zone 1 >")
    lcd.message("\n")
    if powerZoneSettings[1] == 1:
      lcd.message("  [BUZZER ON]  ")
    else:            
      lcd.message("  [BUZZER OFF]  ")
    if keypressed == "B":
      keypressed = None
      if powerZoneSettings[1] == 1:
        powerZoneSettings[1] = 0
      elif powerZoneSettings[1] == 0:
        powerZoneSettings[1] = 1               
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()                
    zoneProgSetMenu = menuPositionUpDn(MIN_POS, MAX_POS)

  elif zoneProgSetMenu == 2:                        #3 / 2
    if clearKey == 1:
      clearKey = 0
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()
    lcd.home()
    lcd.message("< Device  Type >")
    lcd.message("\n")
    if powerZoneSettings[2] == 1:
      lcd.message("      [BAS]     ")
    elif powerZoneSettings[2] == 2:            
      lcd.message("      [FAS]     ")
    elif powerZoneSettings[2] == 3:            
      lcd.message("  [TIME  LOCK]  ")
    elif powerZoneSettings[2] == 4:            
      lcd.message("[ACCESS CONTROL]")
    elif powerZoneSettings[2] == 5:            
      lcd.message("    [NVR/DVR]   ")
    elif powerZoneSettings[2] == 6:            
      lcd.message("      [IAS]     ")
    else:
      lcd.message("      [NONE]    ")      

    if keypressed == "1":
        keypressed = None
        powerZoneSettings[2] = 1
    elif keypressed == "2":
        keypressed = None
        powerZoneSettings[2] = 2
    elif keypressed == "3":
        keypressed = None
        powerZoneSettings[2] = 3
    elif keypressed == "4":
        keypressed = None
        powerZoneSettings[2] = 4
    elif keypressed == "5":
        keypressed = None
        powerZoneSettings[2] = 5
    elif keypressed == "6":
        keypressed = None
        powerZoneSettings[2] = 6
      
    if keypressed == "B":
      keypressed = None

      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()                
    zoneProgSetMenu = menuPositionUpDn(MIN_POS, MAX_POS)

  # ZONE 2
  elif zoneProgSetMenu == 3:                    #4 / 3
    if clearKey == 0:
      clearKey = 1
      keypadScanning(0,0,0,0,'clear')
      keyDetect = 0
      lcd.clear()
      lcd.home()
    lcd.home()
    lcd.message("< Power Zone 2 >")
    lcd.message("\n")
    if powerZoneSettings[3] == 1:
      lcd.message("    [ACTIVE]    ")
    else:            
      lcd.message("   [DE-ACTIVE]  ")
    if keypressed == "B":
      keypressed = None
      if powerZoneSettings[3] == 1:
        powerZoneSettings[3] = 0
      elif powerZoneSettings[3] == 0:
        powerZoneSettings[3] = 1   
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()                
    zoneProgSetMenu = menuPositionUpDn(MIN_POS, MAX_POS)

  elif zoneProgSetMenu == 4:                    #5 / 4
    if clearKey == 1:
      clearKey = 0
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()
    lcd.home()
    lcd.message("< Power Zone 2 >")
    lcd.message("\n")
    if powerZoneSettings[4] == 1:
      lcd.message("  [BUZZER ON]  ")
    else:            
      lcd.message("  [BUZZER OFF]  ")
    if keypressed == "B":
      keypressed = None
      if powerZoneSettings[4] == 1:
        powerZoneSettings[4] = 0
      elif powerZoneSettings[4] == 0:
        powerZoneSettings[4] = 1               
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()                
    zoneProgSetMenu = menuPositionUpDn(MIN_POS, MAX_POS)

  elif zoneProgSetMenu == 5:                    #6 / 5
    if clearKey == 1:
      clearKey = 0
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()
    lcd.home()
    lcd.message("< Device  Type >")
    lcd.message("\n")
    if powerZoneSettings[5] == 1:
      lcd.message("      [BAS]     ")
    elif powerZoneSettings[5] == 2:            
      lcd.message("      [FAS]     ")
    elif powerZoneSettings[5] == 3:            
      lcd.message("  [TIME  LOCK]  ")
    elif powerZoneSettings[5] == 4:            
      lcd.message("[ACCESS CONTROL]")
    elif powerZoneSettings[5] == 5:            
      lcd.message("    [NVR/DVR]   ")
    elif powerZoneSettings[5] == 6:            
      lcd.message("      [IAS]     ")      
    else:
      lcd.message("      [NONE]    ")      

    if keypressed == "1":
        keypressed = None
        powerZoneSettings[5] = 1
    elif keypressed == "2":
        keypressed = None
        powerZoneSettings[5] = 2
    elif keypressed == "3":
        keypressed = None
        powerZoneSettings[5] = 3
    elif keypressed == "4":
        keypressed = None
        powerZoneSettings[5] = 4
    elif keypressed == "5":
        keypressed = None
        powerZoneSettings[5] = 5
    elif keypressed == "6":
        keypressed = None
        powerZoneSettings[5] = 6
        
    if keypressed == "B":
      keypressed = None

      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()                
    zoneProgSetMenu = menuPositionUpDn(MIN_POS, MAX_POS)

  # ZONE 3
  elif zoneProgSetMenu == 6:                #7  / 6
    if clearKey == 0:
      clearKey = 1
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()
    lcd.home()
    lcd.message("< Power Zone 3 >")
    lcd.message("\n")
    if powerZoneSettings[6] == 1:
      lcd.message("    [ACTIVE]    ")
    else:            
      lcd.message("   [DE-ACTIVE]  ")
    if keypressed == "B":
      keypressed = None
      if powerZoneSettings[6] == 1:
        powerZoneSettings[6] = 0
      elif powerZoneSettings[6] == 0:
        powerZoneSettings[6] = 1   
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()                
    zoneProgSetMenu = menuPositionUpDn(MIN_POS, MAX_POS)
    
  elif zoneProgSetMenu == 7:                #8 / 7
    if clearKey == 1:
      clearKey = 0
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()
    lcd.home()
    lcd.message("< Power Zone 3 >")
    lcd.message("\n")
    if powerZoneSettings[7] == 1:
      lcd.message("  [BUZZER ON]  ")
    else:            
      lcd.message("  [BUZZER OFF]  ")
    if keypressed == "B":
      keypressed = None
      if powerZoneSettings[7] == 1:
        powerZoneSettings[7] = 0
      elif powerZoneSettings[7] == 0:
        powerZoneSettings[7] = 1               
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()                
    zoneProgSetMenu = menuPositionUpDn(MIN_POS, MAX_POS)


  elif zoneProgSetMenu == 8:                #9 / 8
    if clearKey == 1:
      clearKey = 0
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()
    lcd.home()
    lcd.message("< Device  Type >")
    lcd.message("\n")
    if powerZoneSettings[8] == 1:
      lcd.message("      [BAS]     ")
    elif powerZoneSettings[8] == 2:            
      lcd.message("      [FAS]     ")
    elif powerZoneSettings[8] == 3:            
      lcd.message("  [TIME  LOCK]  ")
    elif powerZoneSettings[8] == 4:            
      lcd.message("[ACCESS CONTROL]")
    elif powerZoneSettings[8] == 5:            
      lcd.message("    [NVR/DVR]   ")
    elif powerZoneSettings[8] == 6:            
      lcd.message("      [IAS]     ")      
    else:
      lcd.message("      [NONE]    ")      

    if keypressed == "1":
        keypressed = None
        powerZoneSettings[8] = 1
    elif keypressed == "2":
        keypressed = None
        powerZoneSettings[8] = 2
    elif keypressed == "3":
        keypressed = None
        powerZoneSettings[8] = 3
    elif keypressed == "4":
        keypressed = None
        powerZoneSettings[8] = 4
    elif keypressed == "5":
        keypressed = None
        powerZoneSettings[8] = 5
    elif keypressed == "6":
        keypressed = None
        powerZoneSettings[8] = 6        
      
    if keypressed == "B":
      keypressed = None

      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()                
    zoneProgSetMenu = menuPositionUpDn(MIN_POS, MAX_POS)

  # ZONE 4
  elif zoneProgSetMenu == 9:            #10 / 9
    if clearKey == 0:
      clearKey = 1
      keypadScanning(0,0,0,0,'clear')
      keyDetect = 0
      lcd.clear()
      lcd.home()
    lcd.home()
    lcd.message("< Power Zone 4 >")
    lcd.message("\n")
    if powerZoneSettings[9] == 1:
      lcd.message("    [ACTIVE]    ")
    else:            
      lcd.message("   [DE-ACTIVE]  ")
    if keypressed == "B":
      keypressed = None
      if powerZoneSettings[9] == 1:
        powerZoneSettings[9] = 0
      elif powerZoneSettings[9] == 0:
        powerZoneSettings[9] = 1   
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()                
    zoneProgSetMenu = menuPositionUpDn(MIN_POS, MAX_POS)
    
  elif zoneProgSetMenu == 10:            #11 / 10
    if clearKey == 1:
      clearKey = 0
      keypadScanning(0,0,0,0,'clear')
      keyDetect = 0
      lcd.clear()
      lcd.home()
    lcd.home()
    lcd.message("< Power Zone 4 >")
    lcd.message("\n")
    if powerZoneSettings[10] == 1:
      lcd.message("  [BUZZER ON]  ")
    else:            
      lcd.message("  [BUZZER OFF]  ")
    if keypressed == "B":
      keypressed = None
      if powerZoneSettings[10] == 1:
        powerZoneSettings[10] = 0
      elif powerZoneSettings[10] == 0:
        powerZoneSettings[10] = 1               
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()                
    zoneProgSetMenu = menuPositionUpDn(MIN_POS, MAX_POS)
    

  elif zoneProgSetMenu == 11:                #12 / 11
    if clearKey == 1:
      clearKey = 0
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()
    lcd.home()
    lcd.message("< Device  Type >")
    lcd.message("\n")
    if powerZoneSettings[11] == 1:
      lcd.message("      [BAS]     ")
    elif powerZoneSettings[11] == 2:            
      lcd.message("      [FAS]     ")
    elif powerZoneSettings[11] == 3:            
      lcd.message("  [TIME  LOCK]  ")
    elif powerZoneSettings[11] == 4:            
      lcd.message("[ACCESS CONTROL]")
    elif powerZoneSettings[11] == 5:            
      lcd.message("    [NVR/DVR]   ")
    elif powerZoneSettings[11] == 6:            
      lcd.message("      [IAS]     ")      
    else:
      lcd.message("      [NONE]    ")      

    if keypressed == "1":
        keypressed = None
        powerZoneSettings[11] = 1
    elif keypressed == "2":
        keypressed = None
        powerZoneSettings[11] = 2
    elif keypressed == "3":
        keypressed = None
        powerZoneSettings[11] = 3
    elif keypressed == "4":
        keypressed = None
        powerZoneSettings[11] = 4
    elif keypressed == "5":
        keypressed = None
        powerZoneSettings[11] = 5        
    elif keypressed == "6":
        keypressed = None
        powerZoneSettings[11] = 6        
      
    if keypressed == "B":
      keypressed = None

      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()                
    zoneProgSetMenu = menuPositionUpDn(MIN_POS, MAX_POS)

  # ZONE 5
  elif zoneProgSetMenu == 12:            #13 / 12
    if clearKey == 0:
      clearKey = 1
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()
    lcd.home()
    lcd.message("< Power Zone 5 >")
    lcd.message("\n")
    if powerZoneSettings[12] == 1:
      lcd.message("    [ACTIVE]    ")
    else:            
      lcd.message("   [DE-ACTIVE]  ")
    if keypressed == "B":
      keypressed = None
      if powerZoneSettings[12] == 1:
        powerZoneSettings[12] = 0
      elif powerZoneSettings[12] == 0:
        powerZoneSettings[12] = 1   
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()                
    zoneProgSetMenu = menuPositionUpDn(MIN_POS, MAX_POS)
    
  elif zoneProgSetMenu == 13:            #14 / 13
    if clearKey == 1:
      clearKey = 0
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()
    lcd.home()
    lcd.message("< Power Zone 5 >")
    lcd.message("\n")
    if powerZoneSettings[13] == 1:
      lcd.message("  [BUZZER ON]  ")
    else:            
      lcd.message("  [BUZZER OFF]  ")
    if keypressed == "B":
      keypressed = None
      if powerZoneSettings[13] == 1:
        powerZoneSettings[13] = 0
      elif powerZoneSettings[13] == 0:
        powerZoneSettings[13] = 1               
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()                
    zoneProgSetMenu = menuPositionUpDn(MIN_POS, MAX_POS)

  elif zoneProgSetMenu == 14:            #15 / 14
    if clearKey == 1:
      clearKey = 0
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()
    lcd.home()
    lcd.message("< Device  Type >")
    lcd.message("\n")
    if powerZoneSettings[14] == 1:
      lcd.message("      [BAS]     ")
    elif powerZoneSettings[14] == 2:            
      lcd.message("      [FAS]     ")
    elif powerZoneSettings[14] == 3:            
      lcd.message("  [TIME  LOCK]  ")
    elif powerZoneSettings[14] == 4:            
      lcd.message("[ACCESS CONTROL]")
    elif powerZoneSettings[14] == 5:            
      lcd.message("    [NVR/DVR]   ")
    elif powerZoneSettings[14] == 6:            
      lcd.message("      [IAS]     ")      
    else:
      lcd.message("      [NONE]    ")      

    if keypressed == "1":
        keypressed = None
        powerZoneSettings[14] = 1
    elif keypressed == "2":
        keypressed = None
        powerZoneSettings[14] = 2
    elif keypressed == "3":
        keypressed = None
        powerZoneSettings[14] = 3
    elif keypressed == "4":
        keypressed = None
        powerZoneSettings[14] = 4
    elif keypressed == "5":
        keypressed = None
        powerZoneSettings[14] = 5
    elif keypressed == "6":
        keypressed = None
        powerZoneSettings[14] = 6
      
    if keypressed == "B":
      keypressed = None

      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()                
    zoneProgSetMenu = menuPositionUpDn(MIN_POS, MAX_POS)

  # ZONE 6
  elif zoneProgSetMenu == 15:           #16 / 15
    if clearKey == 0:
      clearKey = 1
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()
    lcd.home()
    lcd.message("< Power Zone 6 >")
    lcd.message("\n")
    if powerZoneSettings[15] == 1:
      lcd.message("    [ACTIVE]    ")
    else:            
      lcd.message("   [DE-ACTIVE]  ")
    if keypressed == "B":
      keypressed = None
      if powerZoneSettings[15] == 1:
        powerZoneSettings[15] = 0
      elif powerZoneSettings[15] == 0:
        powerZoneSettings[15] = 1   
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()                
    zoneProgSetMenu = menuPositionUpDn(MIN_POS, MAX_POS)
    
  elif zoneProgSetMenu == 16:           #17 / 16
    if clearKey == 1:
      clearKey = 0
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()
    lcd.home()
    lcd.message("< Power Zone 6 >")
    lcd.message("\n")
    if powerZoneSettings[16] == 1:
      lcd.message("  [BUZZER ON]  ")
    else:            
      lcd.message("  [BUZZER OFF]  ")
    if keypressed == "B":
      keypressed = None
      if powerZoneSettings[16] == 1:
        powerZoneSettings[16] = 0
      elif powerZoneSettings[16] == 0:
        powerZoneSettings[16] = 1               
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()                
    zoneProgSetMenu = menuPositionUpDn(MIN_POS, MAX_POS)

  elif zoneProgSetMenu == 17:            #18 / 17
    if clearKey == 1:
      clearKey = 0
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()
    lcd.home()
    lcd.message("< Device  Type >")
    lcd.message("\n")
    if powerZoneSettings[17] == 1:
      lcd.message("      [BAS]     ")
    elif powerZoneSettings[17] == 2:            
      lcd.message("      [FAS]     ")
    elif powerZoneSettings[17] == 3:            
      lcd.message("  [TIME  LOCK]  ")
    elif powerZoneSettings[17] == 4:            
      lcd.message("[ACCESS CONTROL]")
    elif powerZoneSettings[17] == 5:            
      lcd.message("    [NVR/DVR]   ")
    elif powerZoneSettings[17] == 6:            
      lcd.message("      [IAS]     ")      
    else:
      lcd.message("      [NONE]    ")      

    if keypressed == "1":
        keypressed = None
        powerZoneSettings[17] = 1
    elif keypressed == "2":
        keypressed = None
        powerZoneSettings[17] = 2
    elif keypressed == "3":
        keypressed = None
        powerZoneSettings[17] = 3
    elif keypressed == "4":
        keypressed = None
        powerZoneSettings[17] = 4
    elif keypressed == "5":
        keypressed = None
        powerZoneSettings[17] = 5
    elif keypressed == "6":
        keypressed = None
        powerZoneSettings[17] = 6
      
    if keypressed == "B":
      keypressed = None

      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()                
    zoneProgSetMenu = menuPositionUpDn(MIN_POS, MAX_POS)
    

  # ZONE 7
  elif zoneProgSetMenu == 18:           #18 / 17
    if clearKey == 0:
      clearKey = 1
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()
    lcd.home()
    lcd.message("< Power Zone 7 >")
    lcd.message("\n")
    if powerZoneSettings[18] == 1:
      lcd.message("    [ACTIVE]    ")
    else:            
      lcd.message("   [DE-ACTIVE]  ")
    if keypressed == "B":
      keypressed = None
      if powerZoneSettings[18] == 1:
        powerZoneSettings[18] = 0
      elif powerZoneSettings[18] == 0:
        powerZoneSettings[18] = 1   
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()                
    zoneProgSetMenu = menuPositionUpDn(MIN_POS, MAX_POS)
    
  elif zoneProgSetMenu == 19:           #20 / 19
    if clearKey == 1:
      clearKey = 0
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()
    lcd.home()
    lcd.message("< Power Zone 7 >")
    lcd.message("\n")
    if powerZoneSettings[19] == 1:
      lcd.message("  [BUZZER ON]  ")
    else:            
      lcd.message("  [BUZZER OFF]  ")
      
    if keypressed == "B":
      keypressed = None
      if powerZoneSettings[19] == 1:
        powerZoneSettings[19] = 0
      elif powerZoneSettings[19] == 0:
        powerZoneSettings[19] = 1
        
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()                
    zoneProgSetMenu = menuPositionUpDn(MIN_POS, MAX_POS)

  elif zoneProgSetMenu == 20:            #21  / 20    
    if clearKey == 1:
      clearKey = 0
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()
    lcd.home()
    lcd.message("< Device  Type >")
    lcd.message("\n")
    if powerZoneSettings[20] == 1:
      lcd.message("      [BAS]     ")
    elif powerZoneSettings[20] == 2:            
      lcd.message("      [FAS]     ")
    elif powerZoneSettings[20] == 3:            
      lcd.message("  [TIME  LOCK]  ")
    elif powerZoneSettings[20] == 4:            
      lcd.message("[ACCESS CONTROL]")
    elif powerZoneSettings[20] == 5:            
      lcd.message("     [NVR/DVR]  ")
    elif powerZoneSettings[20] == 6:            
      lcd.message("      [IAS]     ")      
    else:
      lcd.message("      [NONE]    ")      

    if keypressed == "1":
        keypressed = None
        powerZoneSettings[20] = 1
    elif keypressed == "2":
        keypressed = None
        powerZoneSettings[20] = 2
    elif keypressed == "3":
        keypressed = None
        powerZoneSettings[20] = 3
    elif keypressed == "4":
        keypressed = None
        powerZoneSettings[20] = 4
    elif keypressed == "5":
        keypressed = None
        powerZoneSettings[20] = 5
    elif keypressed == "6":
        keypressed = None
        powerZoneSettings[20] = 6
      
    if keypressed == "B":
      keypressed = None

      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()                
    zoneProgSetMenu = menuPositionUpDn(MIN_POS, MAX_POS)

  # ZONE 8
  elif zoneProgSetMenu == 21:           #22 / 21
    if clearKey == 0:
      clearKey = 1
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()
    lcd.home()
    lcd.message("< Power Zone 8 >")
    lcd.message("\n")
    if powerZoneSettings[21] == 1:
      lcd.message("    [ACTIVE]    ")
    else:            
      lcd.message("   [DE-ACTIVE]  ")
    if keypressed == "B":
      keypressed = None
      if powerZoneSettings[21] == 1:
        powerZoneSettings[21] = 0
      elif powerZoneSettings[21] == 0:
        powerZoneSettings[21] = 1   
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()                
    zoneProgSetMenu = menuPositionUpDn(MIN_POS, MAX_POS)
    
  elif zoneProgSetMenu == 22:           #20 / 19
    if clearKey == 1:
      clearKey = 0
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()
    lcd.home()
    lcd.message("< Power Zone 8 >")
    lcd.message("\n")
    if powerZoneSettings[22] == 1:
      lcd.message("  [BUZZER ON]  ")
    else:            
      lcd.message("  [BUZZER OFF]  ")
      
    if keypressed == "B":
      keypressed = None
      if powerZoneSettings[22] == 1:
        powerZoneSettings[22] = 0
      elif powerZoneSettings[22] == 0:
        powerZoneSettings[22] = 1
        
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()                
    zoneProgSetMenu = menuPositionUpDn(MIN_POS, MAX_POS)


  elif zoneProgSetMenu == 23:                #24 / 23
    if clearKey == 1:
      clearKey = 0
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()
    lcd.home()
    lcd.message("< Device  Type >")
    lcd.message("\n")
    if powerZoneSettings[23] == 1:
      lcd.message("      [BAS]     ")
    elif powerZoneSettings[23] == 2:            
      lcd.message("      [FAS]     ")
    elif powerZoneSettings[23] == 3:            
      lcd.message("  [TIME  LOCK]  ")
    elif powerZoneSettings[23] == 4:            
      lcd.message("[ACCESS CONTROL]")
    elif powerZoneSettings[23] == 5:            
      lcd.message("    [NVR/DVR]   ")
    elif powerZoneSettings[23] == 6:            
      lcd.message("      [IAS]     ")      
      
    else:
      lcd.message("      [NONE]    ")      

    if keypressed == "1":
        keypressed = None
        powerZoneSettings[23] = 1
    elif keypressed == "2":
        keypressed = None
        powerZoneSettings[23] = 2
    elif keypressed == "3":
        keypressed = None
        powerZoneSettings[23] = 3
    elif keypressed == "4":
        keypressed = None
        powerZoneSettings[23] = 4
    elif keypressed == "5":
        keypressed = None
        powerZoneSettings[23] = 5
    elif keypressed == "6":
        keypressed = None
        powerZoneSettings[23] = 6        
      
    if keypressed == "B":
      keypressed = None

      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()                
    zoneProgSetMenu = menuPositionUpDn(MIN_POS, MAX_POS)
    
  elif zoneProgSetMenu == 24:   #25 / 24 
    lcd.home()
    lcd.message("<     EXIT      ")
    lcd.message("\n")
    lcd.message("    [ENTER]     ")
    zoneProgSetMenu = menuPositionUpDn(MIN_POS, MAX_POS)
    if keypressed == "B":
      keypressed = None
      zoneProgSetMenu  = 0
      powerZoneSettingsFileRW('write')
      global menuCodeSelectState
      rtcProgSetMenu = 0
      menuSubState = 1
      menuCurrentPos = 1
      keypadScanning(0,0,0,0,'clear')            
      lcd.clear()
      lcd.home()




lowBatSet = [0,0,0,0]

# -------------------------------------- Low Battery Settings File Read Write -----------------------------------------
# DEF0000 / lowBatFileRW()
# -----------------------------------------------------------------------------------------------------------------
def lowBatFileRW(readWrite = None):
    global lowBatSet

    temp = []
    listTemp = [0,0]
    n = x = 0
    ROW_OFFSET = 0
    
    if readWrite == 'read':
        log = open("/home/pi/Test3/lowBat.txt","r")
        for line in log:
            listTemp[n] = line        
            n = n + 1        
        log.flush()
        log.close()
        for x in range(0,2+ROW_OFFSET):
            if x == 0: 
                temp = listTemp[x].split()
                lowBatSet[0] = int(temp[0])
                lowBatSet[1] = int(temp[1])
            elif x == 1:
                temp = listTemp[x].split()
                lowBatSet[2] = int(temp[0])
                lowBatSet[3] = int(temp[1])            
            
    elif readWrite == 'write':
        log = open("/home/pi/Test3/lowBat.txt","w")
        for x in range(0,2+ROW_OFFSET):
            if x == 0:
                log.write(str(lowBatSet[0]))
                log.write(str(" "))
                log.write(str(lowBatSet[1])+"\n")
            elif x == 1:
                log.write(str(lowBatSet[2]))
                log.write(str(" "))
                log.write(str(lowBatSet[3])+"\n")                
        log.flush()
        log.close()      


branchNameAddress = [[0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0], # Beanch Name
               [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],       # Address Line 1
               [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],       # Address Line 2    
               [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],       # Street
               [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],       # City
               [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],       # District
               [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],       # State              
               [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0]]       # Pin Code


def branchNameAddressFileRW(readWrite = None):

  global holidayListParam
  global branchNameAddress

  temp = []
  #                        1 2 3 4 5 6 7 8
  branchNameAddressTemp = [0,0,0,0,0,0,0,0]
  n = x = 0
  ROW_OFFSET = 0
  
  if readWrite == 'read':
    log = open("/home/pi/Test3/branchNameAddress.txt","r")
    for line in log:
      branchNameAddressTemp[n] = line        
      n = n + 1        
    log.flush()
    log.close()
    
    for x in range(0,8+ROW_OFFSET):
      temp = branchNameAddressTemp[x].split()
      
      if temp[0] == '+':
        branchNameAddress[x][0] = ' '
      else:    
        branchNameAddress[x][0] = temp[0]
        
      if temp[1] == '+':
        branchNameAddress[x][1] = ' '
      else:    
        branchNameAddress[x][1] = temp[1]
        
      if temp[2] == '+':
        branchNameAddress[x][2] = ' '
      else:    
        branchNameAddress[x][2] = temp[2]
        
      if temp[3] == '+':
        branchNameAddress[x][3] = ' '
      else:    
        branchNameAddress[x][3] = temp[3]
        
      if temp[4] == '+':
        branchNameAddress[x][4] = ' '
      else:    
        branchNameAddress[x][4] = temp[4]
        
      if temp[5] == '+':
        branchNameAddress[x][5] = ' '
      else:    
        branchNameAddress[x][5] = temp[4]
        
      if temp[6] == '+':
        branchNameAddress[x][6] = ' '
      else:    
        branchNameAddress[x][6] = temp[6]
        
      if temp[7] == '+':
        branchNameAddress[x][7] = ' '
      else:    
        branchNameAddress[x][7] = temp[7]
        
      if temp[8] == '+':
        branchNameAddress[x][8] = ' '
      else:    
        branchNameAddress[x][8] = temp[8]
        
      if temp[9] == '+':
        branchNameAddress[x][9] = ' '
      else:    
        branchNameAddress[x][9] = temp[9]
        
      if temp[10] == '+':
        branchNameAddress[x][10] = ' '
      else:    
        branchNameAddress[x][10] = temp[10]
        
      if temp[11] == '+':
        branchNameAddress[x][11] = ' '
      else:    
        branchNameAddress[x][11] = temp[11]
        
      if temp[12] == '+':
        branchNameAddress[x][12] = ' '
      else:    
        branchNameAddress[x][12] = temp[12]
        
      if temp[13] == '+':
        branchNameAddress[x][13] = ' '
      else:    
        branchNameAddress[x][13] = temp[13]
        
      if temp[14] == '+':
        branchNameAddress[x][14] = ' '
      else:    
        branchNameAddress[x][14] = temp[14]
        
      if temp[15] == '+':
        branchNameAddress[x][15] = ' '
      else:    
        branchNameAddress[x][15] = temp[15]
      
  elif readWrite == 'write':
    log = open("/home/pi/Test3/branchNameAddress.txt","w")
    for x in range(0,8+ROW_OFFSET):
      if branchNameAddress[x][0] == ' ':
        log.write(str('+'))
      else:                
        log.write(str(branchNameAddress[x][0]))
      log.write(str(" "))
      
      if branchNameAddress[x][1] == ' ':
        log.write(str('+'))
      else:                            
        log.write(str(branchNameAddress[x][1]))
      log.write(str(" "))
      
      if branchNameAddress[x][2] == ' ':
        log.write(str('+'))
      else:                            
        log.write(str(branchNameAddress[x][2]))
      log.write(str(" "))
      
      if branchNameAddress[x][3] == ' ':
        log.write(str('+'))
      else:                            
        log.write(str(branchNameAddress[x][3]))
      log.write(str(" "))
      
      if branchNameAddress[x][4] == ' ':
        log.write(str('+'))
      else:                            
        log.write(str(branchNameAddress[x][4]))
      log.write(str(" "))
      
      if branchNameAddress[x][5] == ' ':
        log.write(str('+'))
      else:                            
        log.write(str(branchNameAddress[x][5]))
      log.write(str(" "))
      
      if branchNameAddress[x][6] == ' ':
        log.write(str('+'))
      else:                            
        log.write(str(branchNameAddress[x][6]))
      log.write(str(" "))
      
      if branchNameAddress[x][7] == ' ':
        log.write(str('+'))
      else:                            
        log.write(str(branchNameAddress[x][7]))
      log.write(str(" "))
      
      if branchNameAddress[x][8] == ' ':
        log.write(str('+'))
      else:                            
        log.write(str(branchNameAddress[x][8]))
      log.write(str(" "))
      
      if branchNameAddress[x][9] == ' ':
        log.write(str('+'))
      else:                            
        log.write(str(branchNameAddress[x][9]))
      log.write(str(" "))
      
      if branchNameAddress[x][10] == ' ':
        log.write(str('+'))
      else:                            
        log.write(str(branchNameAddress[x][10]))
      log.write(str(" "))
      
      if branchNameAddress[x][11] == ' ':
        log.write(str('+'))
      else:                            
        log.write(str(branchNameAddress[x][11]))
      log.write(str(" "))
      
      if branchNameAddress[x][12] == ' ':
        log.write(str('+'))
      else:                            
        log.write(str(branchNameAddress[x][12]))
      log.write(str(" "))
      
      if branchNameAddress[x][13] == ' ':
        log.write(str('+'))
      else:                            
        log.write(str(branchNameAddress[x][13]))
      log.write(str(" "))
      
      if branchNameAddress[x][14] == ' ':
        log.write(str('+'))
      else:                            
        log.write(str(branchNameAddress[x][14]))
      log.write(str(" "))
      
      if branchNameAddress[x][15] == ' ':
        log.write(str('+')+"\n")
      else:                            
        log.write(str(branchNameAddress[x][15])+"\n")
        
    log.flush()
    log.close()


def branchNameRead():
  global branchName
  log = open("/home/pi/Test3/Branch.txt","r")
  branchName = log.read()
  log.flush()
  log.close()


               #1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 
brandNameAddress = [[0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0], # Beanch Name
         [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],       # Address Line 1
         [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],       # Address Line 2    
         [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],       # Street
         [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],       # City
         [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],       # District
         [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],       # State              
         [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0]]       # Pin Code


def brandNameAddressFileRW(readWrite = None):

  global holidayListParam
  global brandhNameAddress

  temp = []
  #                        1 2 3 4 5 6 7 8
  branchNameAddressTemp = [0,0,0,0,0,0,0,0]
  n = x = 0
  ROW_OFFSET = 0
  
  if readWrite == 'read':
    log = open("/home/pi/Test3/brandNameAddress.txt","r")
    for line in log:
      branchNameAddressTemp[n] = line        
      n = n + 1        
    log.flush()
    log.close()
    
    for x in range(0,8+ROW_OFFSET):
      temp = branchNameAddressTemp[x].split()
      
      if temp[0] == '+':
        brandNameAddress[x][0] = ' '
      else:    
        brandNameAddress[x][0] = temp[0]
        
      if temp[1] == '+':
        brandNameAddress[x][1] = ' '
      else:    
        brandNameAddress[x][1] = temp[1]
        
      if temp[2] == '+':
        brandNameAddress[x][2] = ' '
      else:    
        brandNameAddress[x][2] = temp[2]
        
      if temp[3] == '+':
        brandNameAddress[x][3] = ' '
      else:    
        brandNameAddress[x][3] = temp[3]
        
      if temp[4] == '+':
        brandNameAddress[x][4] = ' '
      else:    
        brandNameAddress[x][4] = temp[4]
        
      if temp[5] == '+':
        brandNameAddress[x][5] = ' '
      else:    
        brandNameAddress[x][5] = temp[5]
        
      if temp[6] == '+':
        brandNameAddress[x][6] = ' '
      else:    
        brandNameAddress[x][6] = temp[6]
        
      if temp[7] == '+':
        brandNameAddress[x][7] = ' '
      else:    
        brandNameAddress[x][7] = temp[7]
        
      if temp[8] == '+':
        brandNameAddress[x][8] = ' '
      else:    
        brandNameAddress[x][8] = temp[8]
        
      if temp[9] == '+':
        brandNameAddress[x][9] = ' '
      else:    
        brandNameAddress[x][9] = temp[9]
        
      if temp[10] == '+':
        brandNameAddress[x][10] = ' '
      else:    
        brandNameAddress[x][10] = temp[10]
        
      if temp[11] == '+':
        brandNameAddress[x][11] = ' '
      else:    
        brandNameAddress[x][11] = temp[11]
        
      if temp[12] == '+':
        brandNameAddress[x][12] = ' '
      else:    
        brandNameAddress[x][12] = temp[12]
        
      if temp[13] == '+':
        brandNameAddress[x][13] = ' '
      else:    
        brandNameAddress[x][13] = temp[13]
        
      if temp[14] == '+':
        brandNameAddress[x][14] = ' '
      else:    
        brandNameAddress[x][14] = temp[14]
        
      if temp[15] == '+':
        brandNameAddress[x][15] = ' '
      else:    
        brandNameAddress[x][15] = temp[15]
      
  elif readWrite == 'write':
    log = open("/home/pi/Test3/brandNameAddress.txt","w")
    for x in range(0,8+ROW_OFFSET):
      if brandNameAddress[x][0] == ' ':
        log.write(str('+'))
      else:                
        log.write(str(brandNameAddress[x][0]))
      log.write(str(" "))
      
      if brandNameAddress[x][1] == ' ':
        log.write(str('+'))
      else:                            
        log.write(str(brandNameAddress[x][1]))
      log.write(str(" "))
      
      if brandNameAddress[x][2] == ' ':
        log.write(str('+'))
      else:                            
        log.write(str(brandNameAddress[x][2]))
      log.write(str(" "))
      
      if brandNameAddress[x][3] == ' ':
        log.write(str('+'))
      else:                            
        log.write(str(brandNameAddress[x][3]))
      log.write(str(" "))
      
      if brandNameAddress[x][4] == ' ':
        log.write(str('+'))
      else:                            
        log.write(str(brandNameAddress[x][4]))
      log.write(str(" "))
      
      if brandNameAddress[x][5] == ' ':
        log.write(str('+'))
      else:                            
        log.write(str(brandNameAddress[x][5]))
      log.write(str(" "))
      
      if brandNameAddress[x][6] == ' ':
        log.write(str('+'))
      else:                            
        log.write(str(brandNameAddress[x][6]))
      log.write(str(" "))
      
      if brandNameAddress[x][7] == ' ':
        log.write(str('+'))
      else:                            
        log.write(str(brandNameAddress[x][7]))
      log.write(str(" "))
      
      if brandNameAddress[x][8] == ' ':
        log.write(str('+'))
      else:                            
        log.write(str(brandNameAddress[x][8]))
      log.write(str(" "))
      
      if brandNameAddress[x][9] == ' ':
        log.write(str('+'))
      else:                            
        log.write(str(brandNameAddress[x][9]))
      log.write(str(" "))
      
      if brandNameAddress[x][10] == ' ':
        log.write(str('+'))
      else:                            
        log.write(str(brandNameAddress[x][10]))
      log.write(str(" "))
      
      if brandNameAddress[x][11] == ' ':
        log.write(str('+'))
      else:                            
        log.write(str(brandNameAddress[x][11]))
      log.write(str(" "))
      
      if brandNameAddress[x][12] == ' ':
        log.write(str('+'))
      else:                            
        log.write(str(brandNameAddress[x][12]))
      log.write(str(" "))
      
      if brandNameAddress[x][13] == ' ':
        log.write(str('+'))
      else:                            
        log.write(str(brandNameAddress[x][13]))
      log.write(str(" "))
      
      if brandNameAddress[x][14] == ' ':
        log.write(str('+'))
      else:                            
        log.write(str(brandNameAddress[x][14]))
      log.write(str(" "))
      
      if brandNameAddress[x][15] == ' ':
        log.write(str('+')+"\n")
      else:                            
        log.write(str(brandNameAddress[x][15])+"\n")
        
    log.flush()
    log.close()


def lowBatteryProg():

    LOW_BATTERY_1, LOW_BATTERY_2, LOW_BATTERY_3, LOW_BATTERY_4, LOW_BATTERY_5, EXIT = range(6)
    
    MAX_POS = EXIT
    MIN_POS = LOW_BATTERY_1

    global keypressed
    global GmainStateState
    global menuCurrentPos
    global GuserSetState
    global menuSubState
    global lowBatSet
    global menuMainState
    global lowBatteryBuzzOn
    global toggleBit500mSecSec
    global menuSubSubSubState

    if menuSubSubSubState == LOW_BATTERY_1:
        lcd.home()
        lowBatFileRW('read')
        lcd.message("   LOW Battery  ")
        lcd.message("\n")
        if lowBatSet[1] == 1:
            lcd.message(" Status:[Enable]")
        else:   
            lcd.message("Status:[Disable]")
        
        menuSubSubSubState = menuPositionUpDn(MIN_POS,MAX_POS)
        
    if menuSubSubSubState == LOW_BATTERY_2:        
        lowBatFileRW('read')
        lcd.home()
        lcd.message("   LOW Battery  ")
        lcd.message("\n")
        if toggleBit500mSecSec:
            lcd.message("   >")
        else:
            lcd.message("    ")         
        lcd.message("[")
        if lowBatSet[1] == 1:
            lcd.message("Enabled")
        else:
            lcd.message("Disabled")
        lcd.message("]   ")
        if keypressed == "B":
            keypressed = None
            if lowBatSet[1] == 0:
                lowBatSet[1] = 1
            elif lowBatSet[1] == 1:
                 lowBatSet[1] = 0
            lowBatFileRW('write')
        menuSubSubSubState = menuPositionUpDn(MIN_POS,MAX_POS)
    
    if menuSubSubSubState == LOW_BATTERY_3:        
        lcd.home()
        lcd.message("   LOW Battery  ")
        lcd.message("\n")
        lcd.message("[Delay 1-99 Min]")
        
        menuSubSubSubState = menuPositionUpDn(MIN_POS,MAX_POS)
        
    if menuSubSubSubState == LOW_BATTERY_4:
        keyDetect = keypadScanning(2,0,99,0)
        lcd.home()
        lowBatFileRW('read')
        lcd.message(" Delay : ")                
        lcd.message("[")
        lcd.message(str(lowBatSet[3]))
        lcd.message("]Min")
        lcd.message("\n")
        if toggleBit500mSecSec:
            lcd.message("      >")
        else:
            lcd.message("       ")
        lcd.message(str(keyDetect))            
        if keypressed == "B":
            keypressed = None
            lowBatSet[3] = int(keyDetect)
            lowBatFileRW('write')
            keypadScanning(0,0,0,0,'clear')
            lcd.clear()
        menuSubSubSubState = menuPositionUpDn(MIN_POS,MAX_POS)

    if menuSubSubSubState == LOW_BATTERY_5:
        log = open("/home/pi/Test3/lowbatbuzzer.txt","r")
        lowBatteryBuzzOn = int(log.read())
        log.flush()
        log.close()
        lcd.home()
        lcd.message(" Low Bat Buzzer ")
        lcd.message("\n")
        if toggleBit500mSecSec:
            lcd.message("    >")
        else:
            lcd.message("     ") 
        if lowBatteryBuzzOn:
            lcd.message("[Enable]   ")
        else:
            lcd.message("[Disable]  ")
        if keypressed == "B":
            keypressed = None
            if lowBatteryBuzzOn == 1:
                lowBatteryBuzzOn = 0
            elif lowBatteryBuzzOn == 0:
                lowBatteryBuzzOn = 1
            log = open("/home/pi/Test3/lowbatbuzzer.txt","w")
            log.write(str(lowBatteryBuzzOn))
            log.flush()
            log.close()
            keypadScanning(0,0,0,0,'clear')
            lcd.clear()
            lcd.home()
        menuSubSubSubState = menuPositionUpDn(MIN_POS,MAX_POS)

    if menuSubSubSubState == EXIT:        
        lcd.home()
        lcd.message("<     EXIT      ")
        lcd.message("\n")
        lcd.message("    [ENTER]     ")
        menuSubSubSubState = menuPositionUpDn(MIN_POS,MAX_POS)
        if keypressed == "B":
            keypressed = None
            global menuCodeSelectState
            menuSubState = 0
            menuCurrentPos = 0
            lcd.clear()
            lcd.home()


def menuSubSubStatePOWER_BACKUP_CONFIGURATION_PROG():
    
    global menuSubState
    global index
    global sub_index
    global GmainStateState
    global menuCurrentPos
    global GuserSetState
    global keypressed
    global menuMainState
    global menuSubSubState

    if menuSubSubState == 0:        
        lcd.home()
        lcd.message(" CONFIG BACKUP >")
        lcd.message("\n")
        lcd.message("                ")
        if keypressed == "B":
            keypressed = None
        menuSubSubState = menuPositionUpDn(0,2)

    if menuSubSubState == 1:        
        lcd.home()
        lcd.message("<  SOS  SIGNAL >")
        lcd.message("\n")
        lcd.message("                ")
        if keypressed == "B":
            keypressed = None
        menuSubSubState = menuPositionUpDn(0,2)
        
    if menuSubSubState == 2:        
        lcd.home()
        lcd.message("<     EXIT      ")
        lcd.message("\n")
        lcd.message("    [ENTER]     ")
        menuSubSubState = menuPositionUpDn(0,2)
        if keypressed == "B":
            keypressed = None
            menuCurrentPos = 1
            menuSubState = 1
            lcd.clear()
            lcd.home()


# ----------------------------------------- Lamp Test Pro -------------------------------------------
# DEF0000 proLampTest()  
# -------------------------------------------------------------------------------------------------------
def proLampTest():

    global maintenanceState
    global menuSubState
    global menuCurrentPos
    global menuMainState
    global keypressed
    global GtaskManagerSTATE
    global isLampTestACTIVATED
    global isRelayTestACTIVATED
    global isHooterTestACTIVATED    

    MAX_POS = 3
    MIN_POS = 0
    
    if maintenanceState == 0:
        if isLampTestACTIVATED == 1:
            lcd.home()
            lcd.message("    Lamp Test  >\n     [STOP]     ")
            if keypressed == "B":                       # Key = Enter
                keypressed = None
                isLampTestACTIVATED = 0
        elif isLampTestACTIVATED == 0:
            lcd.home()
            lcd.message("    Lamp Test  >\n    [START]     ")            
            if keypressed == "B":                       # Key = Enter
                keypressed = None
                isLampTestACTIVATED = 1
        maintenanceState = menuPositionUpDn(MIN_POS, MAX_POS)

    if maintenanceState == 1:
        if isRelayTestACTIVATED == 1:
            lcd.home()
            lcd.message("<  Relay Test  >\n     [STOP]     ")
            if keypressed == "B":                       # Key = Enter
                keypressed = None
                isRelayTestACTIVATED = 0
        elif isRelayTestACTIVATED == 0:
            lcd.home()
            lcd.message("<  Relay Test  >\n    [START]     ")            
            if keypressed == "B":                       # Key = Enter
                keypressed = None
                isRelayTestACTIVATED = 1
        maintenanceState = menuPositionUpDn(MIN_POS, MAX_POS)

    if maintenanceState == 2:
        if isHooterTestACTIVATED == 1:
            lcd.home()
            lcd.message("<  Buzzer Test >\n     [STOP]     ")
            if keypressed == "B":                       # Key = Enter
                keypressed = None
                isHooterTestACTIVATED = 0
        elif isHooterTestACTIVATED == 0:
            lcd.home()
            lcd.message("<  Buzzer Test >\n    [START]     ")            
            if keypressed == "B":                       # Key = Enter
                keypressed = None
                isHooterTestACTIVATED = 1
        maintenanceState = menuPositionUpDn(MIN_POS, MAX_POS)        
        
    if maintenanceState == 3:       # Exit
        lcd.home()
        lcd.message("<     EXIT      \n    [ENTER]     ")
        if keypressed == "B":
            keypressed = None
            maintenanceState = 0
            GtaskManagerSTATE  = 7
            isLampTestACTIVATED = 0
            isRelayTestACTIVATED = 0
            isHooterTestACTIVATED = 0            
            indexLog = 0
            menuCurrentPos = 6
            menuMainState = 6
            menuSubState = 0
            
            lcd.clear()
            lcd.home()
            keypadScanning(0,0,0,0,'clear')
            

def proLampTestExt():

    global maintenanceState
    global keypressed
    global GtaskManagerSTATE
    global isLampTestACTIVATED
    global isRelayTestACTIVATED
    global isHooterTestACTIVATED    

    MAX_POS = 4
    MIN_POS = 0
    
    if maintenanceState == 0:
        if isLampTestACTIVATED == 1:
            lcd.home()
            lcd.message("    Lamp Test  >\n     [STOP]     ")
            if keypressed == "B":                       # Key = Enter
                keypressed = None
                isLampTestACTIVATED = 0
        elif isLampTestACTIVATED == 0:
            lcd.home()
            lcd.message("    Lamp Test  >\n    [START]     ")            
            if keypressed == "B":                       # Key = Enter
                keypressed = None
                isLampTestACTIVATED = 1
        maintenanceState = menuPositionUpDn(MIN_POS, MAX_POS)

    if maintenanceState == 1:
        if isRelayTestACTIVATED == 1:
            lcd.home()
            lcd.message("<  Relay Test  >\n     [STOP]     ")
            if keypressed == "B":                       # Key = Enter
                keypressed = None
                isRelayTestACTIVATED = 0
        elif isRelayTestACTIVATED == 0:
            lcd.home()
            lcd.message("<  Relay Test  >\n    [START]     ")            
            if keypressed == "B":                       # Key = Enter
                keypressed = None
                isRelayTestACTIVATED = 1
        maintenanceState = menuPositionUpDn(MIN_POS, MAX_POS)

    if maintenanceState == 2:
        if isHooterTestACTIVATED == 1:
            lcd.home()
            lcd.message("<  Buzzer Test >\n     [STOP]     ")
            if keypressed == "B":                       # Key = Enter
                keypressed = None
                isHooterTestACTIVATED = 0
        elif isHooterTestACTIVATED == 0:
            lcd.home()
            lcd.message("<  Buzzer Test >\n    [START]     ")            
            if keypressed == "B":                       # Key = Enter
                keypressed = None
                isHooterTestACTIVATED = 1
        maintenanceState = menuPositionUpDn(MIN_POS, MAX_POS)        

    if maintenanceState == 3:       # Exit
        lcd.home()
        lcd.message("<    DEBUG     >\n    [START]     ")
        if keypressed == "B":
            keypressed = None
            try:
                lcd.home()
                lcd.message("<    DEBUG     >\n    [ACTIVE]     ")
                subprocess.check_call(["python", "/home/pi/Test3/net_debug.py"])
                time.sleep(20)
            except Exception as e:
                print(f"Error executing debug: {str(e)}")
                logger.error(f"Error executing debug: {str(e)}")

        maintenanceState = menuPositionUpDn(MIN_POS, MAX_POS)

    if maintenanceState == 4:       # Exit
        lcd.home()
        lcd.message("<     EXIT      \n    [ENTER]     ")
        if keypressed == "B":
            keypressed = None
            maintenanceState = 0
            GtaskManagerSTATE  = 7
            isLampTestACTIVATED = 0
            isRelayTestACTIVATED = 0
            isHooterTestACTIVATED = 0            
            indexLog = 0

            global GmainStateState
            GmainStateState = 0
            global menuCurrentPos
            menuCurrentPos = 0
            global GuserSetState
            GuserSetState = 0
            global menuCodeSelectState
            menuCodeSelectState = 0
            global menuMainState
            menuMainState = 0
            global menuSubState
            menuSubState = 0
            
            lcd.clear()
            lcd.home()
            keypadScanning(0,0,0,0,'clear')
            
        maintenanceState = menuPositionUpDn(MIN_POS, MAX_POS)




#---------------------------- Program State Machine Sub State ------------------------------
# OTA_UPDATE_PROG
# -------------------------------------------------------------------------------------------
def progStateMachineSubSubStateOTA_UPDATE_PROG():

    global menuMainState
    global keypressed
    global GmainStateState
    global menuCurrentPos
    global GuserSetState 
    global index
    global menuSubState
    global menuCodeSelectState
    global menuSubPasswordState
    global clearKey
    global isMemoryCleared
    global toggleBit500mSecSec
    global isPasswordReseted
    global isLogCleared
    global menuSubSubState
                
    menuList = {'OTA_UPDATE':0,
                'EXIT':1,
                'OTA_UPDATE_PROG':2}

    MENU_MAX = 1
    MENU_MIN = 0
    
    if menuSubState == menuList['OTA_UPDATE']:
        lcd.message("      OTA      >\n      UPDATE    ")
        menuSubState = menuPositionUpDnWithoutClear(MENU_MIN, MENU_MAX)
        menuMainStateHist = 0
        if keypressed == "B":           
            keypressed = None

        
    elif menuSubState == menuList['EXIT']:                                               
        lcd.message("<     EXIT      \n    [ENTER]     ")
        menuSubState = menuPositionUpDnWithoutClear(MENU_MIN, MENU_MAX)
        if keypressed == "B":
            keypressed = "CLEAR"
            menuCurrentPos = 9
            menuMainState = 9
            menuSubState = 0
            lcd.clear()
            lcd.home()
            keypadScanning(0,0,0,0,'clear')

    elif menuSubState == menuList['OTA_UPDATE_PROG']:
#        pass
        menuSubSubStateOTA_UPDATE_PROG()


#---------------------------- Program State Machine Sub State ------------------------------
# DEVICE_PROVISIONING_PROG
# -------------------------------------------------------------------------------------------
def progStateMachineSubSubStateDEVICE_PROVISIONING_PROG():

    global menuMainState
    global keypressed
    global GmainStateState
    global menuCurrentPos
    global GuserSetState 
    global index
    global menuSubState
    global menuCodeSelectState
    global menuSubPasswordState
    global clearKey
    global isMemoryCleared
    global toggleBit500mSecSec
    global isPasswordReseted
    global isLogCleared
    global menuSubSubState
                
    menuList = {'SOL_ID':0,
                'DEVICE_PROVISIONING':1,
                'EXIT':2,
                'SOL_ID_PROG':3,
                'DEVICE_PROVISIONING_PROG':4}

    MENU_MAX = 4
    MENU_MIN = 0
    
    if menuSubState == menuList['SOL_ID']:                                   
        lcd.message("     SOL ID    >\n               ")
        menuSubState = menuPositionUpDnWithoutClear(MENU_MIN, MENU_MAX)
        
        menuMainStateHist = 0
        if keypressed == "B":           
            keypressed = None
            menuSubState = menuList['SOL_ID_PROG']
            menuCurrentPos = 0
            menuSubSubState = 0
            lcd.clear()
            lcd.home()
            clearKey = 0
            keypadScanning(0,0,0,0,'clear')
    
    elif menuSubState == menuList['DEVICE_PROVISIONING']:                                   
        lcd.message("     DEVICE    >\n  PROVISIONING  ")
        menuSubState = menuPositionUpDnWithoutClear(MENU_MIN, MENU_MAX)
        menuMainStateHist = 0
        if keypressed == "B":           
            keypressed = None
            menuSubState = menuList['DEVICE_PROVISIONING_PROG']
            rtcProgSetMenu = 0
            menuCurrentPos = 0
            menuSubSubState = 0
            lcd.clear()
            lcd.home()
            clearKey = 0
            keypadScanning(0,0,0,0,'clear')

        
    elif menuSubState == menuList['EXIT']:                                               
        lcd.message("<     EXIT      \n    [ENTER]     ")
        menuSubState = menuPositionUpDnWithoutClear(MENU_MIN, MENU_MAX)
        if keypressed == "B":
            keypressed = "CLEAR"
            menuCurrentPos = 8
            menuMainState = 8
            menuSubState = 0
            lcd.clear()
            lcd.home()
            keypadScanning(0,0,0,0,'clear')

            
    elif menuSubState == menuList['SOL_ID_PROG']:
        menuSubSubStateSOL_ID_PROG()
    
    elif menuSubState == menuList['DEVICE_PROVISIONING_PROG']:
        #pass
        menuSubSubStateDEVICE_PROVISIONING_PROG()




def menuSubSubStateSOL_ID_PROG():
  
  SOL_ID, ADD_SOL_ID, REG_SOL_ID, EXIT = range(4)  
  
  MAX_POS = EXIT
  MIN_POS = SOL_ID

  global keypressed
  global GmainStateState
  global menuCurrentPos
  global GuserSetState
  global menuSubState
  global menuSubSubSubState
  global menuMainState

  global toggleBit500mSecSec
 
  global keyInputMultiMode

  global keyPos
  global rowPOS
  global clearKey
  
  global branchNameAddressBuffer
  
  global menuSubSubState       
  
  
  if menuSubSubState == SOL_ID:
    #branchNameAddressBuffer[0] = [' '] * 16
    if clearKey == 0:
      clearKey = 1
      keypadScanning(0,0,0,0,'clear')
      keyDetect = 0
      keyPos = 0 
      lcd.clear()
      lcd.home()        
      branchNameAddressBuffer[0] = [' '] * 16
    lcd.home()
    lcd.message("  Add  SOL ID  >")
    lcd.message("\n")
    lcd.message("              ")
    
    menuSubSubState = menuPositionUpDn(MIN_POS,MAX_POS)


  if menuSubSubState == ADD_SOL_ID: 
 
    if clearKey == 0:
        clearKey = 1
        keypadScanning(0,0,0,0,'clear')
        keyDetect = 0
        keyPos = 0
        padWithSpace = 0            
        for index in range(0, 16, 1):
            branchNameAddressBuffer[0][index] = ' '
        lcd.clear()
        lcd.home()                            
    keypadScanningMultiKey(15,0,None)
    
    lcd.message("SOL ID :")
    lcd.message("\n")

    for index in range(0, 16, 1):
        lcd.message(str(branchNameAddressBuffer[0][index]))
    lcd.setCursor(keyPos, 1)  # Row 1, Column `keyPos` Set the cursor position for user input
    lcd.cursor()  # Show cursor 
    menuSubSubState = menuPositionUpDn(MIN_POS,MAX_POS)


  if menuSubSubState == REG_SOL_ID:
    if clearKey == 0:
      clearKey = 1
      keypadScanning(0,0,0,0,'clear')
      keyDetect = 0
      keyPos = 0 
      lcd.clear()
      lcd.home()        
    lcd.home()
    lcd.noCursor()
    lcd.message("< Update SOL ID>")
    lcd.message("\n")
    if toggleBit500mSecSec:
      lcd.message("  >")
    else:
      lcd.message("   ")
    lcd.message("[UPDATE]")
    
    if keypressed == "B":
        keypressed = None
      
        result = ''     
        for item in branchNameAddressBuffer[0]:
            if item == ' ':  
                break
            result += str(item)

        # SOL-FIX-1: validate before writing — empty SOL ID must not
        # overwrite a valid device_name with a blank string. Without this,
        # pressing ENTER on an empty buffer writes "" to modem_config.db and
        # device_provisioning() fails (or PROV-FIX-2 aborts with LCD error).
        if not result.strip():
            lcd.clear()
            lcd.home()
            lcd.message("SOL ID EMPTY!   ")
            lcd.message("\n")
            lcd.message("ENTER SOL ID 1ST")
            time.sleep(2)
            lcd.clear()
            lcd.home()
            clearKey = 0   # force redraw of REG_SOL_ID screen on next cycle
        else:
            try:
                modem_config_db.update_parameter('device_name', result.strip())
                # SOL-FIX-2: show confirmation so user knows save succeeded.
                # SOL-FIX-3: return immediately after save so the same keypress
                # that triggered the save does NOT also call menuPositionUpDn()
                # and navigate away before the user sees the confirmation.
                lcd.clear()
                lcd.home()
                lcd.message("SOL ID SAVED:   ")
                lcd.message("\n")
                lcd.message(result.strip()[:16])
                time.sleep(2)
                lcd.clear()
                lcd.home()
            except ValueError as e:
                lcd.clear()
                lcd.home()
                lcd.message("SOL ID ERROR!   ")
                lcd.message("\n")
                lcd.message(str(e)[:16])
                logger.error(f"Error: {e}")
                time.sleep(2)
                lcd.clear()
                lcd.home()
            except Exception as e:
                lcd.clear()
                lcd.home()
                lcd.message("SAVE FAILED!    ")
                lcd.message("\n")
                lcd.message(str(e)[:16])
                logger.error(f"An unexpected error occurred: {e}")
                time.sleep(2)
                lcd.clear()
                lcd.home()
        return   # SOL-FIX-3: exit this state machine tick — do not call
                 # menuPositionUpDn() in the same iteration as the save keypress
    
    menuSubSubState = menuPositionUpDn(MIN_POS, MAX_POS)


  if menuSubSubState == EXIT:                                            # 4    
    lcd.home()
    lcd.message("<     EXIT      ")
    lcd.message("\n")
    lcd.message("    [ENTER]     ")
    menuSubSubState = menuPositionUpDn(MIN_POS,MAX_POS)
    if keypressed == "B":
      keypressed = None
      global menuCodeSelectState
      menuSubState = 0
      menuCurrentPos = 0
      menuSubSubState = 0
      menuSubSubSubState = 0
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()           

#-------------------------------------------
# ======== Mask ip ========


def mask_all_ips_json(
    db_path="/home/pi/Test3/device_config.db",
    table_name="device_parameters",
    column_name="camera_ip"
):
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        cursor.execute(f"SELECT rowid, {column_name} FROM {table_name}")
        rows = cursor.fetchall()

        updated_count = 0

        for rowid, json_data in rows:
            try:
                # Skip real SQL NULLs
                if json_data is None:
                    print(f"[Skip] row {rowid}: value is NULL")
                    continue

                # If plain string that looks like an IP
                if isinstance(json_data, str) and json_data.strip().count(".") == 3:
                    cursor.execute(
                        f"UPDATE {table_name} SET {column_name} = ? WHERE rowid = ?",
                        (None, rowid)   # set real NULL
                    )
                    updated_count += 1
                    print(f"[Mask] row {rowid}: plain IP string masked → NULL")
                    continue

                # Otherwise, try parsing as JSON
                if not isinstance(json_data, (str, bytes, bytearray)):
                    print(f"[Skip] row {rowid}: invalid type -> {type(json_data).__name__}, value={json_data!r}")
                    continue

                data = json.loads(json_data)

                # Replace IPs in list
                if isinstance(data, list):
                    for obj in data:
                        if isinstance(obj, dict) and "ip_address" in obj:
                            obj["ip_address"] = None

                # Replace IP in dict
                elif isinstance(data, dict):
                    if "ip_address" in data:
                        data["ip_address"] = None

                new_json = json.dumps(data)

                cursor.execute(
                    f"UPDATE {table_name} SET {column_name} = ? WHERE rowid = ?",
                    (new_json, rowid)
                )
                updated_count += 1

            except json.JSONDecodeError:
                print(f"[Skip] row {rowid}: not valid JSON -> {json_data!r}")
               # logger.error("Error:", e)
                continue

        conn.commit()
        print(f"Masked IPs in {updated_count} rows of {table_name}")

    except sqlite3.Error as e:
        print("Error:", e)
        logger.error("Error:", e)

    finally:
        if conn:
            conn.close()


# ======== clear all  ========


def clear_all_data(db_path):
    total_deleted = 0
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Get all non-system tables
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';")
        tables = [row[0] for row in cursor.fetchall()]

        pass_count = 0
        while True:
            pass_count += 1
            deleted_this_round = 0

            for table in tables:
                cursor.execute(f"SELECT COUNT(*) FROM {table}")
                count_before = cursor.fetchone()[0]

                if count_before > 0:
                    cursor.execute(f"DELETE FROM {table}")
                    deleted_this_round += count_before
                    print(f"[Pass {pass_count}] Cleared {count_before} rows from: {table}")

            conn.commit()
            total_deleted += deleted_this_round

            # Stop if nothing deleted this pass
            if deleted_this_round == 0:
                break

        print(f" {db_path}: Total {total_deleted} rows cleared.")

    except sqlite3.Error as e:
        print(f"Error clearing {db_path}: {e}")
        logger.error(f"Error clearing {db_path}: {e}")

    finally:
        if conn:
            conn.close()

    return total_deleted



def clear_both_databases():
    db_paths = [
        '/home/pi/Test3/payloads.db',
        '/home/pi/Test3/buffer.db'
    ]

    max_passes = 10  # safety limit
    for pass_num in range(1, max_passes + 1):
        print(f"\n=== Cleanup Pass {pass_num} ===")
        all_empty = True

        for db_path in db_paths:
            rows_cleared = clear_all_data(db_path)
            if rows_cleared > 0:
                all_empty = False

        if all_empty:
            print("\n All databases are empty. Stopping early.")
            break

        time.sleep(2)

    else:
        print("\n Max passes reached. Some data may still remain.")


# ── X.509 on-device provisioning ─────────────────────────────────────────────
def _provision_device_x509() -> bool:
    """
    Register this device's X.509 certificate fingerprint in SWatch via REST API.

    Reads device_name, swatch_host, swatch_username, swatch_password from
    modem_config_db (credentials are Fernet-encrypted at rest).
    Reads the cert PEM from /home/pi/Test3/certs/device.crt.
    Calls: login → get device → get credentials → POST X509_CERTIFICATE.
    Returns True on success, False on any error (never raises).
    """
    device_name  = str(modem_config_db.get_parameter("device_name")    or "").strip()
    swatch_host  = str(modem_config_db.get_parameter("swatch_host")     or "").strip()
    enc_user     = str(modem_config_db.get_parameter("swatch_username") or "").strip()
    enc_pass     = str(modem_config_db.get_parameter("swatch_password") or "").strip()

    if not device_name:
        logger.error("[x509] device_name not set in modem_config.db")
        return False

    if not swatch_host:
        swatch_host = "https://www.dexterhms.com"
        logger.info("[x509] swatch_host not set — using default %s", swatch_host)
    elif not swatch_host.startswith("http"):
        swatch_host = "https://" + swatch_host

    try:
        username = decrypt_value(enc_user) if enc_user else ""
    except Exception:
        username = enc_user
    try:
        password = decrypt_value(enc_pass) if enc_pass else ""
    except Exception:
        password = enc_pass

    if not username or not password:
        logger.error(
            "[x509] swatch_username/swatch_password not set in modem_config.db — "
            "set them via the web UI before running device provisioning"
        )
        return False

    cert_path = "/home/pi/Test3/certs/device.crt"
    try:
        with open(cert_path) as _f:
            cert_pem = _f.read()
    except OSError as e:
        logger.error("[x509] cert not found at %s: %s — run gen_device_cert.sh first", cert_path, e)
        return False

    try:
        _cert_obj   = _x509_crypto.load_pem_x509_certificate(cert_pem.encode())
        fingerprint = _cert_obj.fingerprint(_crypto_hashes.SHA256()).hex()
    except Exception as e:
        logger.error("[x509] cert fingerprint computation failed: %s", e)
        return False

    logger.info("[x509] device=%s  fingerprint=%s...", device_name, fingerprint[:16])

    _T = 20   # HTTP timeout seconds
    try:
        # 1. Login
        r = requests.post(
            f"{swatch_host}/api/auth/login",
            json={"username": username, "password": password},
            timeout=_T,
        )
        if not r.ok:
            logger.error("[x509] login failed: HTTP %d — %s", r.status_code, r.text[:200])
            return False
        hdrs = {
            "X-Authorization": f"Bearer {r.json()['token']}",
            "Content-Type":    "application/json",
        }
        logger.info("[x509] authenticated to %s", swatch_host)

        # 2. Get device
        r = requests.get(
            f"{swatch_host}/api/tenant/devices",
            params={"pageSize": 20, "page": 0, "deviceName": device_name},
            headers=hdrs, timeout=_T,
        )
        if not r.ok:
            logger.error("[x509] get device failed: HTTP %d", r.status_code)
            return False
        matches   = r.json().get("data", [])
        device    = next((d for d in matches if d["name"] == device_name), None)
        if device is None:
            logger.error("[x509] device '%s' not found in SWatch (got: %s)",
                         device_name, [d["name"] for d in matches])
            return False
        device_id = device["id"]["id"]
        logger.info("[x509] found device %s  id=%s", device_name, device_id)

        # 3. Get current credentials
        r = requests.get(
            f"{swatch_host}/api/device/{device_id}/credentials",
            headers=hdrs, timeout=_T,
        )
        if not r.ok:
            logger.error("[x509] get credentials failed: HTTP %d", r.status_code)
            return False
        creds = r.json()

        if creds.get("credentialsType") == "X509_CERTIFICATE" and creds.get("credentialsId") == fingerprint:
            logger.info("[x509] %s already up to date — no change needed", device_name)
            return True

        # 4. Update credentials to X509_CERTIFICATE
        r = requests.post(
            f"{swatch_host}/api/device/credentials",
            json={
                "id":               creds.get("id"),
                "deviceId":         creds.get("deviceId"),
                "credentialsType":  "X509_CERTIFICATE",
                "credentialsId":    fingerprint,
                "credentialsValue": cert_pem.strip(),
            },
            headers=hdrs, timeout=_T,
        )
        if not r.ok:
            logger.error("[x509] update credentials failed: HTTP %d — %s",
                         r.status_code, r.text[:200])
            return False

        logger.info("[x509] %s credentials updated to X509_CERTIFICATE", device_name)
        return True

    except Exception as e:
        logger.error("[x509] provisioning error: %s", e)
        return False


# ======== device provisionning with clear all,cavlidatause_on and mask ip  ========

def device_provisioning():
    max_retries = 3
    attempt = 0

    # Validate device_name before starting — setup_tailscale_and_save_info() needs it.
    try:
        _pre_device_name = modem_config_db.get_parameter("device_name")
    except Exception:
        _pre_device_name = None
    if not _pre_device_name or not str(_pre_device_name).strip():
        lcd.clear()
        lcd.home()
        lcd.message("DEVICE NAME     \nNOT SET! ABORT  ")
        logger.error("[device_provisioning] device_name not set in modem_config.db — aborting")
        time.sleep(3)
        return "failed"

    # Ethernet-only Pis must skip pon/poff — no modem peer config on host.
    use_modem = str(modem_config_db.get_parameter("network_type")).strip().lower() == "gsm"

    while attempt < max_retries:
        try:
            # Step 1
            stop_autorun()
            time.sleep(5)

            # Step 2 — bring modem up (GSM devices only)
            # nsenter: pppd must run in host network namespace so ppp0 is on the host.
            if use_modem:
                if subprocess.call(["nsenter", "-t", "1", "-m", "-u", "-i", "-n", "-p", "--", "pon", "c16qs"]) != 0:
                    raise RuntimeError("pon c16qs failed")
                time.sleep(20)

            # Step 3 — X.509 device provisioning via SWatch REST API.
            # Reads cert from /home/pi/Test3/certs/device.crt, computes SHA-256
            # fingerprint, and registers it on SWatch. No modem port needed —
            # runs over whatever internet path is active (PPP or eth0).
            prov_ok = False
            for _prov_attempt in range(3):
                prov_ok = _provision_device_x509()
                if prov_ok:
                    break
                logger.warning(
                    "provision: x509 attempt %d/3 failed — retrying in 5s",
                    _prov_attempt + 1
                )
                time.sleep(5)
            if not prov_ok:
                raise RuntimeError("X.509 provisioning failed after 3 attempts — cert not registered in SWatch")
            time.sleep(5)

            # Step 4 — Tailscale setup (over modem)
            setup_tailscale_and_save_info()
            time.sleep(5)

            # Step 5 — cavlidata heartbeat (over modem)
            send_cavlidata_status()
            time.sleep(2)

            # Step 6 — send care=done BEFORE dropping modem.
            # send_webdone() makes HTTPS REST calls to thingsboard.cloud.
            # eth0 is LAN-only on field devices — all internet goes via ppp0.
            # Running send_webdone() while ppp0 is still up ensures it reaches TB.
            webdone_ok = send_webdone()
            if not webdone_ok:
                raise RuntimeError("send_webdone failed — 'done' not delivered to ThingsBoard")
            time.sleep(2)

            # Step 7 � Portainer registration (internet still up � must be before poff)
            portainer_register()
            time.sleep(2)

            # Step 8 � drop modem after all internet calls are complete (GSM only)
            if use_modem:
                if subprocess.call(["nsenter", "-t", "1", "-m", "-u", "-i", "-n", "-p", "--", "poff", "c16qs"]) != 0:
                    raise RuntimeError("poff c16qs failed")
                time.sleep(3)

            # Step 8
            clear_both_databases()
            time.sleep(1)

            # Step 9
            mask_all_ips_json()
            time.sleep(1)

            # Signal next send_dexter_config to mask credentials (provisioning just done)
            try:
                with open("/home/pi/Test3/.provisioning_done", "w") as _f:
                    _f.write("1")
            except OSError:
                pass

            return "success"

        except Exception as e:
            attempt += 1
            print("Provisioning failed (attempt {}/{}). Error: {}".format(attempt, max_retries, e))
            logger.error("Provisioning failed (attempt {}/{}). Error: {}".format(attempt, max_retries, e))
            time.sleep(10)

    print("Provisioning failed after {} attempts.".format(max_retries))
    return "failed"
   

def menuSubSubStateDEVICE_PROVISIONING_PROG():
  DEVICE_PVSN, EXIT = range(2)  
  
  MAX_POS = EXIT
  MIN_POS = DEVICE_PVSN

  global keypressed
  global GmainStateState
  global menuCurrentPos
  global GuserSetState
  global menuSubState
  global menuMainState

  global toggleBit500mSecSec
 
  global keyInputMultiMode

  global keyPos
  global rowPOS
  global clearKey
  
  global credientalsBuffer
  global branchNameAddressBuffer
  
  global menuSubSubState
  
  global chnageInProgramParam
  
  if menuSubSubState == DEVICE_PVSN:

    if clearKey == 0:
      clearKey = 1
      keypadScanning(0,0,0,0,'clear')
      keyDetect = 0
      keyPos = 0 
      lcd.clear()
      lcd.home()
    lcd.message("  DEVICE PVSN  >\n  PRESS  ENTER  ")
    
    menuSubSubState = menuPositionUpDn(MIN_POS,MAX_POS)

    if keypressed == "B":           
        keypressed = None
        lcd.clear()
        lcd.home()
        lcd.message("PLEASE WAIT....\n               ")
        result = device_provisioning()
        print(result)
        chnageInProgramParam = 1
        rtcProgSetMenu = 0
        menuCurrentPos = 0
        menuSubSubState = 0
        lcd.clear()
        lcd.home()
        clearKey = 0
        keypadScanning(0,0,0,0,'clear')
        
    menuSubSubState = menuPositionUpDn(MIN_POS, MAX_POS)


  if menuSubSubState == EXIT:                                            # 4    
    lcd.home()
    lcd.message("<     EXIT      ")
    lcd.message("\n")
    lcd.message("    [ENTER]     ")
    menuSubSubState = menuPositionUpDn(MIN_POS,MAX_POS)
    if keypressed == "B":
      keypressed = None
      global menuCodeSelectState
      menuSubState = 0
      GmainStateState = 0
      menuCurrentPos = 0
      GuserSetState = 0
      menuMainState = 0
      menuCodeSelectState = 0
      menuSubSubState = 0
      if chnageInProgramParam == 1:
            chnageInProgramParam = 0
            rebootPanel()
      keypadScanning(0,0,0,0,'clear')
      returnToDisplayScan()
      lcd.clear()
      lcd.home()       
    

#---------------------------- Program State Machine Sub State ------------------------------
# PROTOCOL_CONFIGURATION_PROG
# -------------------------------------------------------------------------------------------
def progStateMachineSubSubStatePROTOCOL_CONFIGURATION_PROG():

    global menuMainState
    global keypressed
    global GmainStateState
    global menuCurrentPos
    global GuserSetState 
    global index
    global menuSubState
    global menuCodeSelectState
    global menuSubPasswordState
    global clearKey
    global isMemoryCleared
    global toggleBit500mSecSec
    global isPasswordReseted
    global isLogCleared
    global menuSubSubState
                
    menuList = {'PROTOCOL_SETTINGS':0,
                'EXIT':1,
                'PROTOCOL_SETTINGS_PROG':2}

    MENU_MAX = 1
    MENU_MIN = 0
    
    if menuSubState == menuList['PROTOCOL_SETTINGS']:                                   
        lcd.message("    PROTOCOL   >\n    SETTINGS    ")
        menuSubState = menuPositionUpDnWithoutClear(MENU_MIN, MENU_MAX)
        menuMainStateHist = 0
        if keypressed == "B":           
            keypressed = None
            menuSubState = menuList['PROTOCOL_SETTINGS_PROG']
            rtcProgSetMenu = 0
            menuCurrentPos = 0
            menuSubSubState = 0
            lcd.clear()
            lcd.home()
            clearKey = 0
            keypadScanning(0,0,0,0,'clear')

        
    elif menuSubState == menuList['EXIT']:                                               
        lcd.message("<     EXIT      \n    [ENTER]     ")
        menuSubState = menuPositionUpDnWithoutClear(MENU_MIN, MENU_MAX)
        if keypressed == "B":
            keypressed = "CLEAR"
            menuCurrentPos = 7
            menuMainState = 7
            menuSubState = 0
            lcd.clear()
            lcd.home()
            keypadScanning(0,0,0,0,'clear')

            
    elif menuSubState == menuList['PROTOCOL_SETTINGS_PROG']:                    
        menuSubSubStatePROTOCOL_SETTINGS_PROG()



# ----------------------    PROTOCOL_SETTINGS_PROG -----------------------------
# 
# ------------------------------------------------------------------------------
def menuSubSubStatePROTOCOL_SETTINGS_PROG():
    
    global menuSubState
    global index
    global sub_index
    global GmainStateState
    global menuCurrentPos
    global GuserSetState
    global keypressed
    global menuMainState
    global menuSubSubState

    if menuSubSubState == 0:        
        lcd.home()
        lcd.message("SECOND PROTOCOL>")
        lcd.message("\n")
        lcd.message("                ")
        if keypressed == "B":
            keypressed = None
        menuSubSubState = menuPositionUpDn(0,1)
        
    if menuSubSubState == 1:        
        lcd.home()
        lcd.message("<     EXIT      ")
        lcd.message("\n")
        lcd.message("    [ENTER]     ")
        menuSubSubState = menuPositionUpDn(0,1)
        if keypressed == "B":
            keypressed = None
            menuCurrentPos = 0
            menuSubState = 0
            lcd.clear()
            lcd.home()


#---------------------------- Program State Machine Sub State ------------------------------
# SYSTEM_SETTINGS_PROG
# -------------------------------------------------------------------------------------------
def progStateMachineSubSubStateSYSTEM_SETTINGS_PROG():

    global menuMainState
    global keypressed
    global GmainStateState
    global menuCurrentPos
    global GuserSetState 
    global index
    global menuSubState
    global menuCodeSelectState
    global menuSubPasswordState
    global clearKey
    global isMemoryCleared
    global toggleBit500mSecSec
    global isPasswordReseted
    global isLogCleared
    global menuSubSubState
                
    menuList = {'GENERAL_SETTINGS':0,
                'MAINTENANCE':1,
                'ADVANCE_SETTINGS': 2,
                'EXIT':3,
                'GENERAL_SETTINGS_PROG':4,
                'MAINTENANCE_PROG':5,
                'ADVANCE_SETTINGS_PROG':6}

    MENU_MAX = 3
    MENU_MIN = 0
    
    if menuSubState == menuList['GENERAL_SETTINGS']:                                   
        lcd.message("    GENERAL    >\n    SETTINGS    ")
        menuSubState = menuPositionUpDnWithoutClear(MENU_MIN, MENU_MAX)
        menuMainStateHist = 0
        if keypressed == "B":
            keypressed = None
            menuSubState = menuList['GENERAL_SETTINGS_PROG']
            menuSubSubState = 0
            rtcProgSetMenu = 0
            menuCurrentPos = 0
            menuSubSubState = 0
            lcd.clear()
            lcd.home()
            clearKey = 0
            keypadScanning(0,0,0,0,'clear')


    elif menuSubState == menuList['MAINTENANCE']:                                 
        lcd.message("< MAINTENANCE  >\n                ")
        menuSubState = menuPositionUpDnWithoutClear(MENU_MIN, MENU_MAX)
        if keypressed == "B":           
            keypressed = None
            menuSubState = menuList['MAINTENANCE_PROG']
            rtcProgSetMenu = 0
            menuCurrentPos = 0
            menuSubSubState = 0
            index = 0            
            lcd.clear()
            lcd.home()
            clearKey = 0
            keypadScanning(0,0,0,0,'clear')


    elif menuSubState == menuList['ADVANCE_SETTINGS']:                                 
        lcd.message("<   ADVANCE    >\n    SETTINGS    ")
        menuSubState = menuPositionUpDnWithoutClear(MENU_MIN, MENU_MAX)
        if keypressed == "B":           
            keypressed = None
            menuSubState = menuList['ADVANCE_SETTINGS_PROG']
            rtcProgSetMenu = 0
            menuCurrentPos = 0
            menuSubSubState = 0
            index = 0            
            lcd.clear()
            lcd.home()
            clearKey = 0
            keypadScanning(0,0,0,0,'clear')

        
    elif menuSubState == menuList['EXIT']:                                               
        lcd.message("<     EXIT      \n    [ENTER]     ")
        menuSubState = menuPositionUpDnWithoutClear(MENU_MIN, MENU_MAX)
        if keypressed == "B":
            keypressed = "CLEAR"
            menuCurrentPos = 5
            menuMainState = 5
            menuSubState = 0
            lcd.clear()
            lcd.home()
            keypadScanning(0,0,0,0,'clear')

            
    elif menuSubState == menuList['GENERAL_SETTINGS_PROG']:                    
        menuSubSubStateGENERAL_SETTINGS_PROG()

    elif menuSubState == menuList['MAINTENANCE_PROG']:                    
        menuSubSubStateMAINTENANCE_PROG()

    elif menuSubState == menuList['ADVANCE_SETTINGS_PROG']:                    
       menuSubSubStateADVANCE_SETTINGS_PROG()


#---------------------------- Program State Machine Sub State ------------------------------
# SECURITY_DEVICE_INTEGRATION_PROG
# -------------------------------------------------------------------------------------------
def progStateMachineSubSubStateSECURITY_DEVICE_INTEGRATION_PROG():

    global menuMainState
    global keypressed
    global GmainStateState
    global menuCurrentPos
    global GuserSetState 
    global index
    global menuSubState
    global menuCodeSelectState
    global menuSubPasswordState
    global clearKey
    global isMemoryCleared
    global toggleBit500mSecSec
    global isPasswordReseted
    global isLogCleared
    global menuSubSubState
                
    menuList = {'INTEGRATION_SETTINGS':0,
                'DEVICE_MANAGEMENT':1,
                'EXIT':2,
                'INTEGRATION_SETTINGS_PROG':3,
                'DEVICE_MANAGEMENT_PROG':4}

    MENU_MAX = 2
    MENU_MIN = 0
    
    if menuSubState == menuList['INTEGRATION_SETTINGS']:                                   
        lcd.message("  INTEGRATION  >\n    SETTINGS    ")
        menuSubState = menuPositionUpDnWithoutClear(MENU_MIN, MENU_MAX)
        menuMainStateHist = 0
        if keypressed == "B":           
            keypressed = None
            menuSubState = menuList['INTEGRATION_SETTINGS_PROG']
            rtcProgSetMenu = 0
            menuCurrentPos = 0
            menuSubSubState = 0
            lcd.clear()
            lcd.home()
            clearKey = 0
            keypadScanning(0,0,0,0,'clear')

    elif menuSubState == menuList['DEVICE_MANAGEMENT']:                                 
        lcd.message("<    DEVICE    >\n    MANAGEMENT  ")
        menuSubState = menuPositionUpDnWithoutClear(MENU_MIN, MENU_MAX)
        if keypressed == "B":           
            keypressed = None
            menuSubState = menuList['DEVICE_MANAGEMENT_PROG']
            rtcProgSetMenu = 0
            menuCurrentPos = 0
            menuSubSubState = 0
            index = 0            
            lcd.clear()
            lcd.home()
            clearKey = 0
            keypadScanning(0,0,0,0,'clear')

    elif menuSubState == menuList['EXIT']:                                               
        lcd.message("<     EXIT      \n    [ENTER]     ")
        menuSubState = menuPositionUpDnWithoutClear(MENU_MIN, MENU_MAX)
        if keypressed == "B":
            keypressed = "CLEAR"
            menuCurrentPos = 3
            menuMainState = 3
            menuSubState = 0
            lcd.clear()
            lcd.home()
            keypadScanning(0,0,0,0,'clear')

            
    elif menuSubState == menuList['INTEGRATION_SETTINGS_PROG']:                    
        menuSubSubStateINTEGRATION_SETTINGS_PROG()

    elif menuSubState == menuList['DEVICE_MANAGEMENT_PROG']:                    
        menuSubSubStateDEVICE_MANAGEMENT_PROG()


#---------------------------- Program State Machine Sub State ------------------------------
# POWER_MANAGEMENT_PROG
# -------------------------------------------------------------------------------------------
def progStateMachineSubSubStatePOWER_MANAGEMENT_PROG():

    global menuMainState
    global keypressed
    global GmainStateState
    global menuCurrentPos
    global GuserSetState 
    global index
    global menuSubState
    global menuCodeSelectState
    global menuSubPasswordState
    global clearKey
    global isMemoryCleared
    global toggleBit500mSecSec
    global isPasswordReseted
    global isLogCleared
    global menuSubSubState

    global menuSubSubSubState
    
    menuList = {'LOW_BATTERY':0,
                'POWER_BACKUP_CONFIGURATION':1,
                'EXIT':2,
                'LOW_BATTERY_PROG':3,
                'POWER_BACKUP_CONFIGURATION_PROG':4}

    MENU_MAX = 2
    MENU_MIN = 0
    
    if menuSubState == menuList['LOW_BATTERY']:                                   
        lcd.message("      LOW      >\n     BATTERY    ")
        menuSubState = menuPositionUpDnWithoutClear(MENU_MIN, MENU_MAX)
        menuMainStateHist = 0
        if keypressed == "B":           
            keypressed = None
            menuSubState = menuList['LOW_BATTERY_PROG']
            rtcProgSetMenu = 0
            menuCurrentPos = 0
            menuSubSubSubState = 0
            lcd.clear()
            lcd.home()
            clearKey = 0
            keypadScanning(0,0,0,0,'clear')

    elif menuSubState == menuList['POWER_BACKUP_CONFIGURATION']:                                 
        lcd.message("< POWER BACKUP >\n  CONFIGURATION ")
        menuSubState = menuPositionUpDnWithoutClear(MENU_MIN, MENU_MAX)
        if keypressed == "B":           
            keypressed = None
            menuSubState = menuList['POWER_BACKUP_CONFIGURATION_PROG']
            menuCurrentPos = 0
            menuSubSubSubState = 0
            index = 0
            menuSubSubState = 0
            lcd.clear()
            lcd.home()
            clearKey = 0
            keypadScanning(0,0,0,0,'clear')

    elif menuSubState == menuList['EXIT']:                                               
        lcd.message("<     EXIT      \n    [ENTER]     ")
        menuSubState = menuPositionUpDnWithoutClear(MENU_MIN, MENU_MAX)
        if keypressed == "B":
            keypressed = "CLEAR"
            menuCurrentPos = 4
            menuMainState = 4
            menuSubState = 0
            lcd.clear()
            lcd.home()
            keypadScanning(0,0,0,0,'clear')

            
    elif menuSubState == menuList['LOW_BATTERY_PROG']:  
        lowBatteryProg()

    elif menuSubState == menuList['POWER_BACKUP_CONFIGURATION_PROG']:                    
        menuSubSubStatePOWER_BACKUP_CONFIGURATION_PROG()
    

#---------------------------- Program State Machine Sub State ------------------------------
# SYSTEM_TEST_PROG
# -------------------------------------------------------------------------------------------
def progStateMachineSubSubStateSYSTEM_TEST_PROG():

    proLampTest()

#---------------------------- Program State Machine Sub State ------------------------------
# DEVICE_CONFIGURATION_PROG
# -------------------------------------------------------------------------------------------
def progStateMachineSubSubStateDEVICE_CONFIGURATION_PROG():

    #global GpSMSubStateMenu
    global menuMainState
    global keypressed
    global GmainStateState
    global menuCurrentPos
    global GuserSetState 
    global index
    global menuSubState
    global menuCodeSelectState
    global menuSubPasswordState
    global clearKey
    global isMemoryCleared
    global toggleBit500mSecSec
    global isPasswordReseted
    global isLogCleared
    global menuSubSubState
                
    menuList = {'NORMAL_ZONE':0,
                'POWER_ZONE':1,
                'OUTPUT_MANAGEMENT': 2,
                'EXIT':3,
                'NORMAL_ZONE_PROG':4,
                'POWER_ZONE_PROG':5,
                'OUTPUT_MANAGEMENT_PROG':6}

    MENU_MAX = 3
    MENU_MIN = 0
    
    if menuSubState == menuList['NORMAL_ZONE']:                                   
        lcd.message("  NORMAL ZONE  >\n  CONFIGURATION ")
        menuSubState = menuPositionUpDnWithoutClear(MENU_MIN, MENU_MAX)
        menuMainStateHist = 0
        if keypressed == "B":           
            keypressed = None
            menuSubState = menuList['NORMAL_ZONE_PROG']
            rtcProgSetMenu = 0
            menuCurrentPos = 0
            zoneSettingsFileRW('read')
            zoneProgSetMenu = 0
            menuSubSubState = 0
            lcd.clear()
            lcd.home()
            clearKey = 0
            keypadScanning(0,0,0,0,'clear')


    elif menuSubState == menuList['POWER_ZONE']:                                 
        lcd.message("< POWER  ZONE  >\n  CONFIGURATION ")
        menuSubState = menuPositionUpDnWithoutClear(MENU_MIN, MENU_MAX)
        if keypressed == "B":           
            keypressed = None
            menuSubState = menuList['POWER_ZONE_PROG']
            rtcProgSetMenu = 0
            menuCurrentPos = 0
            powerZoneSettingsFileRW('read')
            menuSubSubState = 0
            zoneProgSetMenu = 0
            index = 0            
            lcd.clear()
            lcd.home()
            clearKey = 0
            keypadScanning(0,0,0,0,'clear')


    elif menuSubState == menuList['OUTPUT_MANAGEMENT']:                                 
        lcd.message("<    OUTPUT    >\n   MANAGEMENT   ")
        menuSubState = menuPositionUpDnWithoutClear(MENU_MIN, MENU_MAX)
        if keypressed == "B":           
            keypressed = None
            menuSubState = menuList['OUTPUT_MANAGEMENT_PROG']
            rtcProgSetMenu = 0
            menuCurrentPos = 0

            zoneProgSetMenu = 0
            index = 0            
            lcd.clear()
            lcd.home()
            clearKey = 0
            keypadScanning(0,0,0,0,'clear')

        
    elif menuSubState == menuList['EXIT']:                                               
        lcd.message("<     EXIT      \n    [ENTER]     ")
        menuSubState = menuPositionUpDnWithoutClear(MENU_MIN, MENU_MAX)
        if keypressed == "B":
            keypressed = "CLEAR"
            menuCurrentPos = 0
            menuMainState = 0
            menuSubState = 0
            lcd.clear()
            lcd.home()
            keypadScanning(0,0,0,0,'clear')

            
    elif menuSubState == menuList['NORMAL_ZONE_PROG']:                    
        progZoneSettings()

    elif menuSubState == menuList['POWER_ZONE_PROG']:                    
        progPowerZoneSettings()

    elif menuSubState == menuList['OUTPUT_MANAGEMENT_PROG']:                    
       outputManagement()


#---------------------------- -------------------------------- ------------------------------
# EVENT_LOG_MANAGEMENT_PROG
# -------------------------------------------------------------------------------------------
def progStateMachineSubSubStateEVENT_LOG_MANAGEMENT_PROG():


    global menuMainState
    global keypressed
    global GmainStateState
    global menuCurrentPos
    global GuserSetState 
    global index
    global menuSubState
    global menuCodeSelectState
    global menuSubPasswordState
    global clearKey
    global isMemoryCleared
    global toggleBit500mSecSec
    global isPasswordReseted
    global isLogCleared
    global menuSubSubState
               
    menuList = {'LOGS':0,
                'EVENT_REPORTS':1,
                'CLEAR_REPORTS':2,
                'EXIT':3,
                'LOGS_PROG':4,
                'EVENT_REPORTS_PROG':5,
                'CLEAR_REPORTS_PROG':6}

    MENU_MAX = 3
    MENU_MIN = 0
    
    if menuSubState == menuList['LOGS']:                                   
        lcd.message("      LOGS     >\n    SETTINGS    ")
        menuSubState = menuPositionUpDnWithoutClear(MENU_MIN, MENU_MAX)
        menuMainStateHist = 0
        if keypressed == "B":           
            keypressed = None
            menuSubState = menuList['LOGS_PROG']
            rtcProgSetMenu = 0
            menuCurrentPos = 0
            menuSubSubState = 0
            lcd.clear()
            lcd.home()
            clearKey = 0
            keypadScanning(0,0,0,0,'clear')

    elif menuSubState == menuList['EVENT_REPORTS']:                                 
        lcd.message("<     EVENT    >\n     REPORTS    ")
        
        menuSubState = menuPositionUpDnWithoutClear(MENU_MIN, MENU_MAX)
        if keypressed == "B":           
            keypressed = None
            menuSubState = menuList['EVENT_REPORTS_PROG']
            rtcProgSetMenu = 0
            menuCurrentPos = 0
            menuSubSubState = 0
            index = 0            
            lcd.clear()
            lcd.home()
            clearKey = 0
            keypadScanning(0,0,0,0,'clear')


    elif menuSubState == menuList['CLEAR_REPORTS']:                                 
        lcd.message("<    CLEAR     >\n     REPORTS    ")
        
        menuSubState = menuPositionUpDnWithoutClear(MENU_MIN, MENU_MAX)
        if keypressed == "B":           
            keypressed = None
            menuSubState = menuList['CLEAR_REPORTS_PROG']
            rtcProgSetMenu = 0
            menuCurrentPos = 0
            menuSubSubState = 0
            index = 0            
            lcd.clear()
            lcd.home()
            clearKey = 0
            keypadScanning(0,0,0,0,'clear')
        
    elif menuSubState == menuList['EXIT']:                                               
        lcd.message("<     EXIT      \n    [ENTER]     ")
        menuSubState = menuPositionUpDnWithoutClear(MENU_MIN, MENU_MAX)
        if keypressed == "B":
            keypressed = "CLEAR"
            menuCurrentPos = 1
            menuMainState = 1
            menuSubState = 0
            lcd.clear()
            lcd.home()
            keypadScanning(0,0,0,0,'clear')

    elif menuSubState == menuList['LOGS_PROG']:                    
        menuSubSubStateLOGS_PROG()

    elif menuSubState == menuList['EVENT_REPORTS_PROG']:                    
        menuSubSubStateEVENT_REPORTS_PROG()

    elif menuSubState == menuList['CLEAR_REPORTS_PROG']:                    
        menuSubSubStateDELETE_LOGS_PROG()

def menuSubSubStateINTEGRATION_SETTINGS_PROG_ABANDONE():
    
    global menuSubState
    global index
    global sub_index
    global GmainStateState
    global menuCurrentPos
    global GuserSetState
    global keypressed
    global menuMainState
    global menuSubSubState

    if menuSubSubState == 0:        
        lcd.home()
        lcd.message("PASSIVE  INTEGR>")
        lcd.message("\n")
        lcd.message("                ")
        if keypressed == "B":
            keypressed = None
        menuSubSubState = menuPositionUpDn(0,2)

    if menuSubSubState == 1:        
        lcd.home()
        lcd.message("<ACTIVE  INTEGR>")
        lcd.message("\n")
        lcd.message("                ")
        if keypressed == "B":
            keypressed = None
        menuSubSubState = menuPositionUpDn(0,2)
        
    if menuSubSubState == 2:        
        lcd.home()
        lcd.message("<     EXIT      ")
        lcd.message("\n")
        lcd.message("    [ENTER]     ")
        menuSubSubState = menuPositionUpDn(0,2)
        if keypressed == "B":
            keypressed = None
            GmainStateState = 0
            menuCurrentPos = 0
            GuserSetState = 0
            menuMainState = 0
            menuSubState = 0
            returnToDisplayScan()
            lcd.clear()
            lcd.home()



def menuSubSubStateINTEGRATION_SETTINGS_PROG():
    

    global index
    global sub_index
    global GmainStateState
    global menuCurrentPos
    global GuserSetState
    global keypressed
    global menuMainState
    global menuSubState    
    global menuSubSubState
    global menuSubSubSubState


    menuList = {'PASSIVE_INTEGR':0,
                'ACTIVE_INTEGR':1,
                'EXIT':2,
                'PASSIVE_INTEGR_PROG':3,
                'ACTIVE_INTEGR_PROG':4}

    MENU_MAX = 2
    MENU_MIN = 0

    if menuSubSubState == menuList['PASSIVE_INTEGR']:                                           
        lcd.home()
        lcd.message("PASSIVE  INTEGR>")
        lcd.message("\n")
        lcd.message("                ")
        menuSubSubState = menuPositionUpDn(0,2)        
        if keypressed == "B":
            keypressed = None


    elif menuSubSubState == menuList['ACTIVE_INTEGR']:        
        lcd.home()
        lcd.message("<ACTIVE  INTEGR>")
        lcd.message("\n")
        lcd.message("                ")

        menuSubSubState = menuPositionUpDn(0,2)
        if keypressed == "B":
            keypressed = None
            menuSubSubSubState = 0
            menuCurrentPos = 0
            lcd.clear()
            lcd.home()
            clearKey = 0
            keypadScanning(0,0,0,0,'clear')
            menuSubSubState = menuList['ACTIVE_INTEGR_PROG']
        
    elif menuSubSubState == menuList['EXIT']:        
        lcd.home()
        lcd.message("<     EXIT      ")
        lcd.message("\n")
        lcd.message("    [ENTER]     ")
        menuSubSubState = menuPositionUpDn(0,2)
        if keypressed == "B":
            keypressed = None
            menuCurrentPos = 0
            menuSubState = 0
            lcd.clear()
            lcd.home()

    elif menuSubSubState == menuList['PASSIVE_INTEGR_PROG']:                    
        menuSubSubStatePASSIVE_INTEGR_PROG()

    elif menuSubSubState == menuList['ACTIVE_INTEGR_PROG']:                    
        menuSubSubStateACTIVE_INTEGR_PROG()


    
def menuSubSubStateACTIVE_INTEGR_PROG():    

    global menuSubState
    global index
    global sub_index
    global GmainStateState
    global menuCurrentPos
    global GuserSetState
    global keypressed
    global menuMainState
    global menuSubSubState
    global menuSubSubSubState
    global menuSubSubSubSubState


    # Function to format text to 16 characters
    def format_text(text, width=16):
        text = str(text)
        if len(text) >= width:
            return text[:width]
        return text + " " * (width - len(text))

    # Function to center text
    def center_text(text, width):
        text = str(text)
        if len(text) >= width:
            return text[:width]
        padding = (width - len(text)) // 2
        return " " * padding + text + " " * (width - len(text) - padding)


    menuList = {'HIKVISION_NVR':0,
                'HIKVISION_BACS':1,
                'DAHUA_NVR':2,
                'CP_PLUS_NVR':3,
                'TEXECOM_BAS':4,
                'HIK_BAS':5,
                'HIKVISION_NVR_STATUS':6,
                'DAHUA_NVR_STATUS':7,
                'CP_PLUS_NVR_STATUS':8,
                'HIKVISION_BACS_STATUS':9,
                'TEXECOM_BAS_STATUS':10,
                'HIK_BAS_STATUS':11,
                'EXIT':12,
                'HIKVISION_NVR_PROG':13,
                'HIKVISION_BACS_PROG':14,
                'DAHUA_NVR_PROG':15,
                'CP_PLUS_NVR_PROG':16,
                'TEXECOM_BAS_PROG':17,
                'HIK_BAS_PROG':18}

    if menuSubSubSubState == menuList['HIKVISION_NVR']:
        
        lcd.home()
        lcd.message("HIKVISION   NVR>")
        lcd.message("\n")
        lcd.message("                ")

        menuSubSubSubState = menuPositionUpDn(0,12)
        if keypressed == "B":
            keypressed = None
            menuSubSubSubSubState = 0
            menuCurrentPos = 0
            lcd.clear()
            lcd.home()
            clearKey = 0
            keypadScanning(0,0,0,0,'clear')
            
            menuSubSubSubState = menuList['HIKVISION_NVR_PROG']

    elif menuSubSubSubState == menuList['HIKVISION_BACS']:
        
        lcd.home()
        lcd.message("<HIKVISION BACS>")        
        lcd.message("\n")
        lcd.message("                ")

        menuSubSubSubState = menuPositionUpDn(0,12)
        if keypressed == "B":
            keypressed = None
            menuSubSubSubSubState = 0
            menuCurrentPos = 0
            lcd.clear()
            lcd.home()
            clearKey = 0
            keypadScanning(0,0,0,0,'clear')
            
            menuSubSubSubState = menuList['HIKVISION_BACS_PROG']


    elif menuSubSubSubState == menuList['DAHUA_NVR']:
        
        lcd.home()
        lcd.message("<  DAHUA  NVR  >")
        lcd.message("\n")
        lcd.message("                ")
        
        menuSubSubSubState = menuPositionUpDn(0,12)
        if keypressed == "B":
            keypressed = None
            menuSubSubSubSubState = 0
            menuCurrentPos = 0
            lcd.clear()
            lcd.home()
            clearKey = 0
            keypadScanning(0,0,0,0,'clear')
            
            menuSubSubSubState = menuList['DAHUA_NVR_PROG']

    elif menuSubSubSubState == menuList['CP_PLUS_NVR']:
        
        lcd.home()
        lcd.message("< CP_PLUS NVR >")
        lcd.message("\n")
        lcd.message("                ")
        
        menuSubSubSubState = menuPositionUpDn(0,12)
        if keypressed == "B":
            keypressed = None
            menuSubSubSubSubState = 0
            menuCurrentPos = 0
            lcd.clear()
            lcd.home()
            clearKey = 0
            keypadScanning(0,0,0,0,'clear')
            
            menuSubSubSubState = menuList['CP_PLUS_NVR_PROG']

    elif menuSubSubSubState == menuList['TEXECOM_BAS']:

        lcd.home()
        lcd.message("<  TEXECOM BAS >")
        lcd.message("\n")
        lcd.message("                ")

        menuSubSubSubState = menuPositionUpDn(0,12)
        if keypressed == "B":
            keypressed = None
            menuSubSubSubSubState = 0
            menuCurrentPos = 0
            lcd.clear()
            lcd.home()
            clearKey = 0
            keypadScanning(0,0,0,0,'clear')

            menuSubSubSubState = menuList['TEXECOM_BAS_PROG']


    elif menuSubSubSubState == menuList['HIK_BAS']:

        lcd.home()
        lcd.message("<HIKVISION  BAS>")
        lcd.message("\n")
        lcd.message("                ")

        menuSubSubSubState = menuPositionUpDn(0,12)
        if keypressed == "B":
            keypressed = None
            menuSubSubSubSubState = 0
            menuCurrentPos = 0
            lcd.clear()
            lcd.home()
            clearKey = 0
            keypadScanning(0,0,0,0,'clear')
            menuSubSubSubState = menuList['HIK_BAS_PROG']

#-----------------------------------------------------------------
    elif menuSubSubSubState == menuList['HIKVISION_NVR_STATUS']:
        lcd.home()       
        lcd.message(format_text("<Hik NVR STATUS>") + "\n" + format_text(center_text(check_hikvision_nvr(), 16)))
        
        menuSubSubSubState = menuPositionUpDn(0,12)

#----------------------------------------------------------------- 

    elif menuSubSubSubState == menuList['DAHUA_NVR_STATUS']:
        lcd.home()       
        lcd.message(format_text("<DAHUA NVR STAT>") + "\n" + format_text(center_text(check_dahua_nvr(), 16)))
        
        menuSubSubSubState = menuPositionUpDn(0,12)
#-----------------------------------------------------------------
    
    elif menuSubSubSubState == menuList['CP_PLUS_NVR_STATUS']:
        lcd.home()       
        lcd.message(format_text("<CPPLUS NVR STS>") + "\n" + format_text(center_text(check_cp_plus_nvr(), 16)))
        
        menuSubSubSubState = menuPositionUpDn(0,12)
#-----------------------------------------------------------------

    elif menuSubSubSubState == menuList['HIKVISION_BACS_STATUS']:
        lcd.home()       
        lcd.message(format_text("<Hik BACS STAT >") + "\n" + format_text(center_text(check_hikvision_status('HikvisionBioMetric1'), 16)))
        
        menuSubSubSubState = menuPositionUpDn(0,12)
#-----------------------------------------------------------------

    elif menuSubSubSubState == menuList['TEXECOM_BAS_STATUS']:
        lcd.home()
        lcd.message(format_text("<Texe BAS STAT >") + "\n" + format_text(center_text(check_texecom_bas(), 16)))

        menuSubSubSubState = menuPositionUpDn(0,12)
#-----------------------------------------------------------------
       
    elif menuSubSubSubState == menuList['HIK_BAS_STATUS']:
        lcd.home()
        lcd.message(format_text("<Hik  BAS STAT >") + "\n" + format_text(center_text(check_hik_bas(), 16)))
        menuSubSubSubState = menuPositionUpDn(0,12)
#-----------------------------------------------------------------

    elif menuSubSubSubState == menuList['EXIT']:        
        lcd.home()
        lcd.message("<     EXIT      ")
        lcd.message("\n")
        lcd.message("    [ENTER]     ")
        
        menuSubSubSubState = menuPositionUpDn(0,12)
        if keypressed == "B":
            keypressed = None
            menuCurrentPos = 1
            menuSubSubState = 1
            lcd.clear()
            lcd.home()

    elif menuSubSubSubState == menuList['HIKVISION_NVR_PROG']:
        try:
            # Example of expected `ip_address_ai` initialization
            # ip_address_ai = "192.168.1.1"  # Ensure this is a string
            # Check and convert if necessary
            menuSubSubSubStateHIKVISION_NVR_PROG()    
        except TypeError as e:
            print("TypeError occurred: {}".format(e))
            logger.error("An unexpected error occurred: {}".format(e))
            # Optionally log or handle the error further
            GmainStateState = 0
            menuCurrentPos = 0
            GuserSetState = 0
            menuMainState = 0
            menuSubState = 0
            returnToDisplayScan()
            lcd.clear()
            lcd.home()
        
        except Exception as e:
            print("An unexpected error occurred: {}".format(e))
            logger.error("An unexpected error occurred: {}".format(e))

            GmainStateState = 0
            menuCurrentPos = 0
            GuserSetState = 0
            menuMainState = 0
            menuSubState = 0
            returnToDisplayScan()
            lcd.clear()
            lcd.home()

    elif menuSubSubSubState == menuList['HIKVISION_BACS_PROG']:                    

        try:
            # Example of expected `ip_address_ai` initialization
            # ip_address_ai = "192.168.1.1"  # Ensure this is a string
            # Check and convert if necessary
            menuSubSubSubStateHIKVISION_BACS_PROG()
        except TypeError as e:
            print("TypeError occurred: {}".format(e))
            logger.error("An unexpected error occurred: {}".format(e))
            # Optionally log or handle the error further
            GmainStateState = 0
            menuCurrentPos = 0
            GuserSetState = 0
            menuMainState = 0
            menuSubState = 0
            returnToDisplayScan()
            lcd.clear()
            lcd.home()
        
        except Exception as e:
            print("An unexpected error occurred: {}".format(e))
            logger.error("An unexpected error occurred: {}".format(e))

            GmainStateState = 0
            menuCurrentPos = 0
            GuserSetState = 0
            menuMainState = 0
            menuSubState = 0
            returnToDisplayScan()
            lcd.clear()
            lcd.home()
       

    elif menuSubSubSubState == menuList['DAHUA_NVR_PROG']:                    

        try:
            # Example of expected `ip_address_ai` initialization
            # ip_address_ai = "192.168.1.1"  # Ensure this is a string
            # Check and convert if necessary
            menuSubSubSubStateDAHUA_NVR_PROG()
        except TypeError as e:
            print("TypeError occurred: {}".format(e))
            logger.error("An unexpected error occurred: {}".format(e))
            # Optionally log or handle the error further
            GmainStateState = 0
            menuCurrentPos = 0
            GuserSetState = 0
            menuMainState = 0
            menuSubState = 0
            returnToDisplayScan()
            lcd.clear()
            lcd.home()
        
        except Exception as e:
            print("An unexpected error occurred: {}".format(e))
            logger.error("An unexpected error occurred: {}".format(e))

            GmainStateState = 0
            menuCurrentPos = 0
            GuserSetState = 0
            menuMainState = 0
            menuSubState = 0
            returnToDisplayScan()
            lcd.clear()
            lcd.home()

    elif menuSubSubSubState == menuList['CP_PLUS_NVR_PROG']:                    

        try:
            # Example of expected `ip_address_ai` initialization
            # ip_address_ai = "192.168.1.1"  # Ensure this is a string
            # Check and convert if necessary
            menuSubSubSubStateCP_PLUS_NVR_PROG()
        except TypeError as e:
            print("TypeError occurred: {}".format(e))
            logger.error("TypeError occurred: {}".format(e))
            # Optionally log or handle the error further
            GmainStateState = 0
            menuCurrentPos = 0
            GuserSetState = 0
            menuMainState = 0
            menuSubState = 0
            returnToDisplayScan()
            lcd.clear()
            lcd.home()
        
        except Exception as e:
            print("An unexpected error occurred: {}".format(e))
            logger.error("An unexpected error occurred: {}".format(e))

            GmainStateState = 0
            menuCurrentPos = 0
            GuserSetState = 0
            menuMainState = 0
            menuSubState = 0
            returnToDisplayScan()
            lcd.clear()
            lcd.home()

    elif menuSubSubSubState == menuList['TEXECOM_BAS_PROG']:

        try:
            menuSubSubSubStateTEXECOM_BAS_PROG()
        except TypeError as e:
            print("TypeError occurred: {}".format(e))
            logger.error("An unexpected error occurred: {}".format(e))
            GmainStateState = 0
            menuCurrentPos = 0
            GuserSetState = 0
            menuMainState = 0
            menuSubState = 0
            returnToDisplayScan()
            lcd.clear()
            lcd.home()

        except Exception as e:
            print("An unexpected error occurred: {}".format(e))
            logger.error("An unexpected error occurred: {}".format(e))
            GmainStateState = 0
            menuCurrentPos = 0
            GuserSetState = 0
            menuMainState = 0
            menuSubState = 0
            returnToDisplayScan()
            lcd.clear()
            lcd.home()

    elif menuSubSubSubState == menuList['HIK_BAS_PROG']:

        try:
            menuSubSubSubStateHIK_BAS_PROG()
        except TypeError as e:
            logger.error("[HIK-BAS-PROG] TypeError: %s", e)
            GmainStateState = 0; menuCurrentPos = 0; GuserSetState = 0
            menuMainState = 0; menuSubState = 0
            returnToDisplayScan(); lcd.clear(); lcd.home()
        except Exception as e:
            logger.error("[HIK-BAS-PROG] Error: %s", e)
            GmainStateState = 0; menuCurrentPos = 0; GuserSetState = 0
            menuMainState = 0; menuSubState = 0
            returnToDisplayScan(); lcd.clear(); lcd.home()
        except TypeError as e:
            print("TypeError occurred: {}".format(e))
            logger.error("An unexpected error occurred: {}".format(e))
            GmainStateState = 0
            menuCurrentPos = 0
            GuserSetState = 0
            menuMainState = 0
            menuSubState = 0
            returnToDisplayScan()
            lcd.clear()
            lcd.home()

        except Exception as e:
            print("An unexpected error occurred: {}".format(e))
            logger.error("An unexpected error occurred: {}".format(e))
            GmainStateState = 0
            menuCurrentPos = 0
            GuserSetState = 0
            menuMainState = 0
            menuSubState = 0
            returnToDisplayScan()
            lcd.clear()
            lcd.home()    


#---------------------------- Program State Machine Sub Sub State -------------------------------
# ACTIVE_INTEGR_PROG
# -------------------------------------------------------------------------------------------

def menuSubSubSubStateHIKVISION_NVR_PROG():

    DEVICE_ID, DEVICE_IP, ADD_DEVICE_IP, REG_DEVICE_IP, DEVICE_NAME, ADD_DEVICE_NAME, REG_DEVICE_NAME, CG_REQ, CG_VFY, DEVICE_PASS, ADD_DEVICE_PASS, REG_DEVICE_PASS, DEVICE_PORT, EXIT = range(14)  # CRED-GATE
    
    MAX_POS = EXIT
    MIN_POS = DEVICE_ID

    global menuSubSubSubSubState

    global menuSubSubSubState
    global branchNameAddressBuffer
    global keypressed
    global clearKey
    global toggleBit500mSecSec
    global keyPos

    global rtcProgSetMenu
    global menuMainState
    global menuCurrentPos
    global keypressed
    global keyDetect
    global GuserSetState
    global menuSubState
    global GmainStateState
    global clearKey
    global toggleBit500mSecSec

    global menuSubState
    global index
    global sub_index
    global GmainStateState
    global menuCurrentPos
    global GuserSetState
    global keypressed
    global menuMainState

    global menuSubSubState

    global toggleBit500mSecSec

    global phoneNumberBuff
    global keyPos

    global keypressed
    global value1
    global GmainStateState
    global menuCurrentPos
    global GuserSetState
    global menuSubState
    global menuMainState

    global progPass
    global toggleBit500mSecSec
    global isPasswordMatched
    global beepOn1Sec

    global repeatCounter
    global multikey_Dic 
    global keyInputMultiMode
    global branchNameAddress
    global branchNameAddressBuffer
    global keyPos

    global device_id_ai
    global device_type_ai
    global ip_address_ai
    global username_ai
    global password_ai
    global port_ai

    
    device_type = "HikvisionNVR1"

    # Fetch devices of type "Hikvision NVR"
    devices = dpm.get_device_parameters(device_type)

    # Iterate through the result and extract individual parameters
    for device in devices:
        device_id_ai = device['id']       # ID
        device_type_ai = device['device_type']     # Device Type
        ip_address_ai = device['ip_address']      # IP Address
        username_ai = device['username']        # Username
        password_ai = device['password']        # Password
        port_ai = device['port']            # Port

    # DEVICE_ID  --------------------------------------------------------------------------------
    if menuSubSubSubSubState == DEVICE_ID:
        
        keyDetect = keypadScanning(2,0,99,0)
        if clearKey == 0:
            clearKey = 1
            keypadScanning(0,0,0,0,'clear')
            keyDetect = 0
            lcd.clear()
            lcd.home()
            
        lcd.home()
        lcd.message(str(device_type_ai))
        lcd.message("       ")        
        lcd.message("\n")
        lcd.message("ID No: [")
        try:
            lcd.message(str(device_id_ai))
        except ValueError:
            lcd.message(str(0))
        except IOError:
            lcd.message(str(0))
            
        lcd.message("]       ")
            
        lcd.message(str(keyDetect))
        if keypressed == "B":
            keypressed = None
            keypadScanning(0,0,0,0,'clear')
            lcd.clear()
            lcd.home()                
        menuSubSubSubSubState = menuPositionUpDn(0,MAX_POS)

    # DEVICE IP -------------------------------------------------------------------------------- 3
    elif menuSubSubSubSubState == DEVICE_IP:                       #
        
        if clearKey == 1:
            clearKey = 0
            keypadScanning(0,0,0,0,'clear')
            keyDetect = 0
            keyPos = 0             
            lcd.clear()
            lcd.home()
        lcd.noCursor()
        lcd.message("< Set  IP Addr >")
        lcd.message("\n")
        lcd.message(str(ip_address_ai))
        lcd.message("       ")

        # Save the string into the 2D list
        row_index = 0
        col_index = 0

        for char in ip_address_ai:
            phoneNumberBuff[row_index][col_index] = char
            col_index += 1
            if col_index >= 16:  # Move to the next row if column limit is exceeded
                col_index = 0
                row_index += 1
            
        menuSubSubSubSubState = menuPositionUpDn(0,MAX_POS)

    # ADD DEVICE IP
    elif menuSubSubSubSubState == ADD_DEVICE_IP:                       

        if clearKey == 0:
            clearKey = 1
            keypadScanning(0,0,0,0,'clear')
            keyDetect = 0
            keyPos = 0
            padWithSpace = 0            
            for index in range(0,14,1):
                phoneNumberBuff[6][index] = ' '
            lcd.clear()
            lcd.home()                
            
        keypadScanningMultiNumKeyWithDot(14,6,None)
        lcd.home()

        lcd.message("\n")
        for index in range(0,14,1):
            lcd.message(str(phoneNumberBuff[6][index]))
        lcd.setCursor(keyPos, 1)  # Row 1, Column `keyPos` Set the cursor position for user input
        lcd.cursor()  # Show cursor
        menuSubSubSubSubState = menuPositionUpDn(0,MAX_POS)

    # REG DEVICE IP
    elif menuSubSubSubSubState == REG_DEVICE_IP:        #
        
        if clearKey == 1:
            clearKey = 0
            keypadScanning(0,0,0,0,'clear')
            keyDetect = 0
            keyPos = 0             
            lcd.clear()
            lcd.home()            
        lcd.home()
        lcd.noCursor()
        lcd.message("< Upd  IP Addr >")
        lcd.message("\n")
        lcd.message("    [Enter]     ")

        if keypressed == "B":
            keypressed = None
            result = ''
            #for item in sequence:
            for item in phoneNumberBuff[6]:
                if item == ' ':
                    break
                result += str(item)

            # Update each field using the modify_device_field_by_type function
            try:
                #dpm.modify_device_field_by_type(device_type, "device_type", new_device_type)
                dpm.modify_device_field_by_type(device_type, "ip_address", result)
                #dpm.modify_device_field_by_type(device_type, "username", new_username)
                #dpm.modify_device_field_by_type(device_type, "password", new_password)
                #dpm.modify_device_field_by_type(device_type, "port", new_port)
                #print(f"All parameters updated successfully for devices of type {device_type}")
            except ValueError as e:
                print(f"Error: {e}")
                logger.error(f"Error: {e}")
            except Exception as e:
                print(f"An unexpected error occurred: {e}")
                logger.error(f"Error: {e}")

        menuSubSubSubSubState = menuPositionUpDn(0,MAX_POS)	

    # DEVICE NAME -------------------------------------------------------------------------------- 3
    elif menuSubSubSubSubState == DEVICE_NAME:
        if clearKey == 0:
            clearKey = 1
            lcd.clear()
            lcd.home()
            keyPos = 0             
        lcd.home()
        lcd.noCursor()
        lcd.message("< Set Dev Name >")        
        lcd.message("\n")
        lcd.message(str(username_ai))
        lcd.message("          ")

        for index in range(0,16,1):
            branchNameAddressBuffer[0][index] = ' '

        # Save the string into the 2D list
        row_index = 0
        col_index = 0

        for char in username_ai:
            branchNameAddressBuffer[row_index][col_index] = char
            col_index += 1
            if col_index >= 16:  # Move to the next row if column limit is exceeded
                col_index = 0
                row_index += 1
        
        menuSubSubSubSubState = menuPositionUpDn(MIN_POS, MAX_POS)

    # ADD DEVICE NAME
    elif menuSubSubSubSubState == ADD_DEVICE_NAME:
        if clearKey == 1:
            clearKey = 0
            keyPos = 0             
            lcd.clear()
            lcd.home()
        #keypadScanningMultiKey(15, 0, None)
        keypadScanningMultiKeyWithSmallCaps(15, 0, None)
        lcd.home()
        lcd.message("\n")
        for index in range(0, 16, 1):
            lcd.message(str(branchNameAddressBuffer[0][index]))
        lcd.setCursor(keyPos, 1)  # Row 1, Column `keyPos` Set the cursor position for user input
        lcd.cursor()  # Show cursor    
        menuSubSubSubSubState = menuPositionUpDn(MIN_POS, MAX_POS)

    # REG DEVICE NAME
    elif menuSubSubSubSubState == REG_DEVICE_NAME:
        if clearKey == 0:
            clearKey = 1
            keyPos = 0             
            lcd.clear()
            lcd.home()
        lcd.home()
        #lcd.message("UpdateDeviceName\n  >" if toggleBit500mSecSec else "   ")
        lcd.noCursor()
        lcd.message("< Upd Dev Name >")
        lcd.message("\n")
        lcd.message("    [Enter]     ")
        
        if keypressed == "B":
            keypressed = None
            
            result = ''
            #for item in sequence:
            for item in branchNameAddressBuffer[0]:
                if item == ' ':
                    break
                result += str(item)

            # Update each field using the modify_device_field_by_type function
            try:
                #dpm.modify_device_field_by_type(device_type, "device_type", new_device_type)
                #dpm.modify_device_field_by_type('HikvisionNVR1', "ip_address", result)
                dpm.modify_device_field_by_type(device_type, "username", result)
                #dpm.modify_device_field_by_type(device_type, "password", new_password)
                #dpm.modify_device_field_by_type(device_type, "port", new_port)
                #print(f"All parameters updated successfully for devices of type {device_type}")
            except ValueError as e:
                print(f"Error: {e}")
                logger.error(f"Error: {e}")
            except Exception as e:
                print(f"An unexpected error occurred: {e}")
                logger.error(f"Error: {e}")
            
            lcd.clear()
            lcd.home()
        menuSubSubSubSubState = menuPositionUpDn(MIN_POS, MAX_POS)

    # CRED-GATE: challenge-response before showing device password
    elif menuSubSubSubSubState == CG_REQ:
        import time as _ct
        if _cred_session_expiry[0] and _ct.time() < _cred_session_expiry[0]:
            _cred_show_time[0] = _ct.time()
            menuSubSubSubSubState = DEVICE_PASS
            menuCurrentPos = DEVICE_PASS  # FIX: sync menuCurrentPos so arrows work
            lcd.clear(); lcd.home()
            return
        if not credential_auth.key_is_loaded():
            lcd.clear(); lcd.home()
            lcd.message("Key not set    \n")
            lcd.message("Contact Seple  ")
            menuSubSubSubSubState = DEVICE_PORT
            return
        if credential_auth.is_locked_out():
            secs = credential_auth.time_remaining_locked()
            lcd.clear(); lcd.home()
            lcd.message("Access locked  \n")
            lcd.message(str(secs) + "s remaining    ")
            _cred_challenge[0] = None               # CRED-GATE-FIX: reset so next entry is fresh
            menuSubSubSubSubState = DEVICE_PORT
            return
        if _cred_challenge[0] is None:          # generate once per entry
            _cred_challenge[0] = credential_auth.generate_challenge()
            _cred_resp_digits[0] = ''
        # Display on EVERY tick — keeps LCD showing challenge while operator reads it
        lcd.noCursor()
        lcd.message("Call Seple:    \n")
        lcd.message(str(_cred_challenge[0]) + "            ")
        menuSubSubSubSubState = menuPositionUpDn(CG_REQ, CG_VFY)

    elif menuSubSubSubSubState == CG_VFY:
        if credential_auth.is_locked_out():
            secs = credential_auth.time_remaining_locked()
            lcd.clear(); lcd.home()
            lcd.message("Access locked  \n")
            lcd.message(str(secs) + "s remaining    ")
            _cred_challenge[0] = None               # CRED-GATE-FIX: reset so next entry is fresh
            menuSubSubSubSubState = DEVICE_PORT
            return
        #global keypressed
        lcd.noCursor()
        lcd.message("Enter code:    \n")
        display = _cred_resp_digits[0].ljust(6, '_')
        lcd.message(display + "          ")
        if keypressed and keypressed.isdigit() and len(_cred_resp_digits[0]) < 6:
            _cred_resp_digits[0] += keypressed
            keypressed = None
        elif keypressed == "C":
            _cred_resp_digits[0] = ''
            keypressed = None
        elif keypressed == "B" and len(_cred_resp_digits[0]) == 6:
            keypressed = None
            if credential_auth.verify_response(_cred_challenge[0], _cred_resp_digits[0]):
                import time as _t
                _cred_show_time[0] = _t.time()
                _cred_session_expiry[0] = _t.time() + _CRED_SESSION_SEC
                _cred_challenge[0] = None
                _cred_resp_digits[0] = ''
                menuSubSubSubSubState = DEVICE_PASS
                menuCurrentPos = DEVICE_PASS  # FIX: sync menuCurrentPos so arrows work
                lcd.clear(); lcd.home()
            else:
                lcd.clear(); lcd.home()
                lcd.message("Access denied  \n")
                lcd.message("Wrong code     ")
                _cred_challenge[0] = None               # CRED-GATE-FIX: reset on wrong code
                menuSubSubSubSubState = DEVICE_PORT
        elif keypressed == "D":
            keypressed = None
            _cred_challenge[0] = None               # CRED-GATE-FIX: reset on cancel
            menuSubSubSubSubState = DEVICE_PORT
            lcd.clear(); lcd.home()

    # DEVICE PASS -------------------------------------------------------------------------------- 3
    elif menuSubSubSubSubState == DEVICE_PASS:
        if clearKey == 0:
            clearKey = 1
            keyPos = 0             
            lcd.clear()
            lcd.home()
        lcd.home()
        lcd.noCursor()
        lcd.message("< Set Dev Pass >")
        lcd.message("\n")
        lcd.message(str(password_ai))
        lcd.message("         ")

        for index in range(0,16,1):
            branchNameAddressBuffer[0][index] = ' '

        # Save the string into the 2D list
        row_index = 0
        col_index = 0

        for char in password_ai:
            branchNameAddressBuffer[row_index][col_index] = char
            col_index += 1
            if col_index >= 16:  # Move to the next row if column limit is exceeded
                col_index = 0
                row_index += 1
        
        # CRED-GATE: auto-clear after timeout
        if credential_auth.show_expired(_cred_show_time[0]):
            _cred_show_time[0] = None
            _cred_challenge[0] = None               # CRED-GATE-FIX: reset after show expires
            lcd.clear(); lcd.home()
            menuSubSubSubSubState = DEVICE_PORT
            menuCurrentPos = DEVICE_PORT  # FIX: sync menuCurrentPos after timeout
            return
        menuSubSubSubSubState = menuPositionUpDn(MIN_POS, MAX_POS)

    # ADD DEVICE PASS
    elif menuSubSubSubSubState == ADD_DEVICE_PASS:
        if clearKey == 1:
            clearKey = 0
            keyPos = 0             
            lcd.clear()
            lcd.home()
        keypadScanningMultiKeyWithSmallCaps(15, 0, None)
        lcd.home()
        lcd.message("\n")
        for index in range(0, 16, 1):
            lcd.message(str(branchNameAddressBuffer[0][index]))
        lcd.setCursor(keyPos, 1)  # Row 1, Column `keyPos` Set the cursor position for user input
        lcd.cursor()  # Show cursor    
        menuSubSubSubSubState = menuPositionUpDn(MIN_POS, MAX_POS)

    # REG DEVICE PASS
    elif menuSubSubSubSubState == REG_DEVICE_PASS:
        if clearKey == 1:
            clearKey = 0
            lcd.clear()
            lcd.home()
        keypadScanningMultiKey(15, 0, None)
        lcd.home()
        lcd.noCursor()
        lcd.message("< Upd Dev Pass >")
        lcd.message("\n")
        lcd.message("    [Enter]     ")
        
        if keypressed == "B":
            keypressed = None
            
            result = ''
            #for item in sequence:
            for item in branchNameAddressBuffer[0]:
                if item == ' ':
                    break
                result += str(item)

            # Update each field using the modify_device_field_by_type function
            try:
                #dpm.modify_device_field_by_type(device_type, "device_type", new_device_type)
                #dpm.modify_device_field_by_type('HikvisionNVR1', "ip_address", result)
                #dpm.modify_device_field_by_type('HikvisionNVR1', "username", result)
                dpm.modify_device_field_by_type(device_type, "password", result)
                #dpm.modify_device_field_by_type(device_type, "port", new_port)
                #print(f"All parameters updated successfully for devices of type {device_type}")
            except ValueError as e:
                print(f"Error: {e}")
                logger.error(f"Error: {e}")
            except Exception as e:
                print(f"An unexpected error occurred: {e}")
                logger.error(f"Error: {e}")
            
            lcd.clear()
            lcd.home()
            
        menuSubSubSubSubState = menuPositionUpDn(MIN_POS, MAX_POS)

    # DEVICE PORT -------------------------------------------------------------------------------- 3
    elif menuSubSubSubSubState == DEVICE_PORT:                       #
        #port_number = network_settings.get_setting("Set Port Number")        
        if clearKey == 0:
            clearKey = 1
            keypadScanning(0,0,0,0,'clear')
            keyDetect = 0
            lcd.clear()
            lcd.home()
        lcd.home()
        lcd.noCursor()        
        keyDetect = keypadScanning(5,0,65535,1)
        lcd.message("< Set Port Num >")
        lcd.message("\n")
        lcd.message("[")
        lcd.message(str(port_ai))
        lcd.message("] ")
        if toggleBit500mSecSec:
            lcd.message(">")
        else:
            lcd.message(" ")                
        lcd.message(str(keyDetect))
        lcd.message("   ")
        
        if keypressed == "B":
            keypressed = None

            # Update each field using the modify_device_field_by_type function
            try:
                #dpm.modify_device_field_by_type(device_type, "device_type", new_device_type)
                #dpm.modify_device_field_by_type('HikvisionNVR1', "ip_address", result)
                #dpm.modify_device_field_by_type('HikvisionNVR1', "username", result)
                #dpm.modify_device_field_by_type('HikvisionNVR1', "password", result)
                dpm.modify_device_field_by_type(device_type, "port", keyDetect)
                #print(f"All parameters updated successfully for devices of type {device_type}")
            except ValueError as e:
                print(f"Error: {e}")
                logger.error(f"Error: {e}")
            except Exception as e:
                print(f"An unexpected error occurred: {e}")
                logger.error(f"Error: {e}")
            lcd.clear()
        menuSubSubSubSubState = menuPositionUpDn(0,MAX_POS)

    # EXIT
    elif menuSubSubSubSubState == EXIT:
        lcd.home()
        lcd.message("<     EXIT      \n    [ENTER]     ")
        menuSubSubSubSubState = menuPositionUpDn(MIN_POS, MAX_POS)
        
        if keypressed == "B":
            keypressed = None
            menuSubSubSubSubState = 0
            menuSubSubSubState = 0
            menuCurrentPos = 0
            lcd.clear()
            lcd.home()
            


def menuSubSubSubStateHIKVISION_BACS_PROG():

    DEVICE_ID, DEVICE_IP, ADD_DEVICE_IP, REG_DEVICE_IP, DEVICE_NAME, ADD_DEVICE_NAME, REG_DEVICE_NAME, CG_REQ, CG_VFY, DEVICE_PASS, ADD_DEVICE_PASS, REG_DEVICE_PASS, DEVICE_PORT, EXIT = range(14)  # CRED-GATE
    
    MAX_POS = EXIT
    MIN_POS = DEVICE_ID

    global menuSubSubSubSubState

    global menuSubSubSubState
    global branchNameAddressBuffer
    global keypressed
    global clearKey
    global toggleBit500mSecSec
    global keyPos

    global rtcProgSetMenu
    global menuMainState
    global menuCurrentPos
    global keypressed
    global keyDetect
    global GuserSetState
    global menuSubState
    global GmainStateState
    global clearKey
    global toggleBit500mSecSec

    global menuSubState
    global index
    global sub_index
    global GmainStateState
    global menuCurrentPos
    global GuserSetState
    global keypressed
    global menuMainState

    global menuSubSubState

    global toggleBit500mSecSec

    global phoneNumberBuff
    global keyPos

    global keypressed
    global value1
    global GmainStateState
    global menuCurrentPos
    global GuserSetState
    global menuSubState
    global menuMainState

    global progPass
    global toggleBit500mSecSec
    global isPasswordMatched
    global beepOn1Sec

    global repeatCounter
    global multikey_Dic 
    global keyInputMultiMode
    global branchNameAddress
    global branchNameAddressBuffer
    global keyPos

    global device_id_ai
    global device_type_ai
    global ip_address_ai
    global username_ai
    global password_ai
    global port_ai

    
    device_type = "HikvisionBioMetric1"

    # Fetch devices of type "Hikvision NVR"
    devices = dpm.get_device_parameters(device_type)

    # Iterate through the result and extract individual parameters
    for device in devices:
        device_id_ai = device['id']       # ID
        device_type_ai = device['device_type']     # Device Type
        ip_address_ai = device['ip_address']      # IP Address
        username_ai = device['username']        # Username
        password_ai = device['password']        # Password
        port_ai = device['port']            # Port
    

    # DEVICE_ID  --------------------------------------------------------------------------------
    if menuSubSubSubSubState == DEVICE_ID:
        
        keyDetect = keypadScanning(2,0,99,0)
        if clearKey == 0:
            clearKey = 1
            keypadScanning(0,0,0,0,'clear')
            keyDetect = 0
            lcd.clear()
            lcd.home()
        lcd.noCursor()    
        lcd.home()
        lcd.message(str(device_type_ai))
        lcd.message("       ")        
        lcd.message("\n")
        lcd.message("ID No: [")
        try:
            lcd.message(str(device_id_ai))
        except ValueError:
            lcd.message(str(0))
        except IOError:
            lcd.message(str(0))
            
        lcd.message("]       ")
            
        lcd.message(str(keyDetect))
        if keypressed == "B":
            keypressed = None
            keypadScanning(0,0,0,0,'clear')
            lcd.clear()
            lcd.home()                
        menuSubSubSubSubState = menuPositionUpDn(0,MAX_POS)

    # DEVICE IP -------------------------------------------------------------------------------- 3
    elif menuSubSubSubSubState == DEVICE_IP:                       #
        
        if clearKey == 1:
            clearKey = 0
            keypadScanning(0,0,0,0,'clear')
            keyDetect = 0
            keyPos = 0             
            lcd.clear()
            lcd.home()
        lcd.noCursor()
        lcd.message("< Set  IP Addr >")
        lcd.message("\n")
        lcd.message(str(ip_address_ai))
        lcd.message("       ")

        # Save the string into the 2D list
        row_index = 0
        col_index = 0

        for char in ip_address_ai:
            phoneNumberBuff[row_index][col_index] = char
            col_index += 1
            if col_index >= 16:  # Move to the next row if column limit is exceeded
                col_index = 0
                row_index += 1
            
        menuSubSubSubSubState = menuPositionUpDn(0,MAX_POS)

    # ADD DEVICE IP
    elif menuSubSubSubSubState == ADD_DEVICE_IP:                       

        if clearKey == 0:
            clearKey = 1
            keypadScanning(0,0,0,0,'clear')
            keyDetect = 0
            keyPos = 0
            padWithSpace = 0            
            for index in range(0,14,1):
                phoneNumberBuff[6][index] = ' '
            lcd.clear()
            lcd.home()                
            
        keypadScanningMultiNumKeyWithDot(14,6,None)
        lcd.home()

        lcd.message("\n")
        for index in range(0,14,1):
            lcd.message(str(phoneNumberBuff[6][index]))
        lcd.setCursor(keyPos, 1)  # Row 1, Column `keyPos` Set the cursor position for user input
        lcd.cursor()  # Show cursor
        menuSubSubSubSubState = menuPositionUpDn(0,MAX_POS)

    # REG DEVICE IP
    elif menuSubSubSubSubState == REG_DEVICE_IP:        #
        
        if clearKey == 1:
            clearKey = 0
            keypadScanning(0,0,0,0,'clear')
            keyDetect = 0
            keyPos = 0             
            lcd.clear()
            lcd.home()            
        lcd.home()
        lcd.noCursor()
        lcd.message("< Upd  IP Addr >")
        lcd.message("\n")
        lcd.message("    [Enter]     ")

        if keypressed == "B":
            keypressed = None
            result = ''
            #for item in sequence:
            for item in phoneNumberBuff[6]:
                if item == ' ':
                    break
                result += str(item)  

            # Update each field using the modify_device_field_by_type function
            try:
                #dpm.modify_device_field_by_type(device_type, "device_type", new_device_type)
                dpm.modify_device_field_by_type(device_type, "ip_address", result)
                #dpm.modify_device_field_by_type(device_type, "username", new_username)
                #dpm.modify_device_field_by_type(device_type, "password", new_password)
                #dpm.modify_device_field_by_type(device_type, "port", new_port)
                #print(f"All parameters updated successfully for devices of type {device_type}")
            except ValueError as e:
                print(f"Error: {e}")
                logger.error(f"Error: {e}")
            except Exception as e:
                print(f"An unexpected error occurred: {e}")
                logger.error(f"Error: {e}")

        menuSubSubSubSubState = menuPositionUpDn(0,MAX_POS)	

    # DEVICE NAME -------------------------------------------------------------------------------- 3
    elif menuSubSubSubSubState == DEVICE_NAME:
        if clearKey == 0:
            clearKey = 1
            lcd.clear()
            lcd.home()
            keyPos = 0             
        lcd.home()
        lcd.noCursor()
        lcd.message("< Set Dev Name >")        
        lcd.message("\n")
        lcd.message(str(username_ai))
        lcd.message("          ")

        for index in range(0,16,1):
            branchNameAddressBuffer[0][index] = ' '

        # Save the string into the 2D list
        row_index = 0
        col_index = 0

        for char in username_ai:
            branchNameAddressBuffer[row_index][col_index] = char
            col_index += 1
            if col_index >= 16:  # Move to the next row if column limit is exceeded
                col_index = 0
                row_index += 1
        
        menuSubSubSubSubState = menuPositionUpDn(MIN_POS, MAX_POS)

    # ADD DEVICE NAME
    elif menuSubSubSubSubState == ADD_DEVICE_NAME:
        if clearKey == 1:
            clearKey = 0
            keyPos = 0             
            lcd.clear()
            lcd.home()
        #keypadScanningMultiKey(15, 0, None)
        keypadScanningMultiKeyWithSmallCaps(15, 0, None)
        lcd.home()
        lcd.message("\n")
        for index in range(0, 16, 1):
            lcd.message(str(branchNameAddressBuffer[0][index]))
        lcd.setCursor(keyPos, 1)  # Row 1, Column `keyPos` Set the cursor position for user input
        lcd.cursor()  # Show cursor      
        menuSubSubSubSubState = menuPositionUpDn(MIN_POS, MAX_POS)

    # REG DEVICE NAME
    elif menuSubSubSubSubState == REG_DEVICE_NAME:
        if clearKey == 0:
            clearKey = 1
            keyPos = 0             
            lcd.clear()
            lcd.home()
        lcd.home()
        #lcd.message("UpdateDeviceName\n  >" if toggleBit500mSecSec else "   ")
        lcd.noCursor()
        lcd.message("< Upd Dev Name >")
        lcd.message("\n")
        lcd.message("    [Enter]     ")
        
        if keypressed == "B":
            keypressed = None
            
            result = ''
            #for item in sequence:
            for item in branchNameAddressBuffer[0]:
                if item == ' ':
                    break
                result += str(item)

            # Update each field using the modify_device_field_by_type function
            try:
                #dpm.modify_device_field_by_type(device_type, "device_type", new_device_type)
                #dpm.modify_device_field_by_type('HikvisionNVR1', "ip_address", result)
                dpm.modify_device_field_by_type(device_type, "username", result)
                #dpm.modify_device_field_by_type(device_type, "password", new_password)
                #dpm.modify_device_field_by_type(device_type, "port", new_port)
                #print(f"All parameters updated successfully for devices of type {device_type}")
            except ValueError as e:
                print(f"Error: {e}")
                logger.error(f"Error: {e}")
            except Exception as e:
                print(f"An unexpected error occurred: {e}")
                logger.error(f"Error: {e}")
            
            lcd.clear()
            lcd.home()
        menuSubSubSubSubState = menuPositionUpDn(MIN_POS, MAX_POS)

    # CRED-GATE: challenge-response before showing device password
    elif menuSubSubSubSubState == CG_REQ:
        import time as _ct
        if _cred_session_expiry[0] and _ct.time() < _cred_session_expiry[0]:
            _cred_show_time[0] = _ct.time()
            menuSubSubSubSubState = DEVICE_PASS
            menuCurrentPos = DEVICE_PASS  # FIX: sync menuCurrentPos so arrows work
            lcd.clear(); lcd.home()
            return
        if not credential_auth.key_is_loaded():
            lcd.clear(); lcd.home()
            lcd.message("Key not set    \n")
            lcd.message("Contact Seple  ")
            menuSubSubSubSubState = DEVICE_PORT
            return
        if credential_auth.is_locked_out():
            secs = credential_auth.time_remaining_locked()
            lcd.clear(); lcd.home()
            lcd.message("Access locked  \n")
            lcd.message(str(secs) + "s remaining    ")
            _cred_challenge[0] = None               # CRED-GATE-FIX: reset so next entry is fresh
            menuSubSubSubSubState = DEVICE_PORT
            return
        if _cred_challenge[0] is None:          # generate once per entry
            _cred_challenge[0] = credential_auth.generate_challenge()
            _cred_resp_digits[0] = ''
        # Display on EVERY tick — keeps LCD showing challenge while operator reads it
        lcd.noCursor()
        lcd.message("Call Seple:    \n")
        lcd.message(str(_cred_challenge[0]) + "            ")
        menuSubSubSubSubState = menuPositionUpDn(CG_REQ, CG_VFY)

    elif menuSubSubSubSubState == CG_VFY:
        if credential_auth.is_locked_out():
            secs = credential_auth.time_remaining_locked()
            lcd.clear(); lcd.home()
            lcd.message("Access locked  \n")
            lcd.message(str(secs) + "s remaining    ")
            _cred_challenge[0] = None               # CRED-GATE-FIX: reset so next entry is fresh
            menuSubSubSubSubState = DEVICE_PORT
            return
        #global keypressed
        lcd.noCursor()
        lcd.message("Enter code:    \n")
        display = _cred_resp_digits[0].ljust(6, '_')
        lcd.message(display + "          ")
        if keypressed and keypressed.isdigit() and len(_cred_resp_digits[0]) < 6:
            _cred_resp_digits[0] += keypressed
            keypressed = None
        elif keypressed == "C":
            _cred_resp_digits[0] = ''
            keypressed = None
        elif keypressed == "B" and len(_cred_resp_digits[0]) == 6:
            keypressed = None
            if credential_auth.verify_response(_cred_challenge[0], _cred_resp_digits[0]):
                import time as _t
                _cred_show_time[0] = _t.time()
                _cred_session_expiry[0] = _t.time() + _CRED_SESSION_SEC
                _cred_challenge[0] = None
                _cred_resp_digits[0] = ''
                menuSubSubSubSubState = DEVICE_PASS
                menuCurrentPos = DEVICE_PASS  # FIX: sync menuCurrentPos so arrows work
                lcd.clear(); lcd.home()
            else:
                lcd.clear(); lcd.home()
                lcd.message("Access denied  \n")
                lcd.message("Wrong code     ")
                _cred_challenge[0] = None               # CRED-GATE-FIX: reset on wrong code
                menuSubSubSubSubState = DEVICE_PORT
        elif keypressed == "D":
            keypressed = None
            _cred_challenge[0] = None               # CRED-GATE-FIX: reset on cancel
            menuSubSubSubSubState = DEVICE_PORT
            lcd.clear(); lcd.home()

    # DEVICE PASS -------------------------------------------------------------------------------- 3
    elif menuSubSubSubSubState == DEVICE_PASS:
        if clearKey == 0:
            clearKey = 1
            keyPos = 0             
            lcd.clear()
            lcd.home()
        lcd.home()
        lcd.noCursor()
        lcd.message("< Set Dev Pass >")
        lcd.message("\n")
        lcd.message(str(password_ai))
        lcd.message("         ")

        for index in range(0,16,1):
            branchNameAddressBuffer[0][index] = ' '

        # Save the string into the 2D list
        row_index = 0
        col_index = 0

        for char in password_ai:
            branchNameAddressBuffer[row_index][col_index] = char
            col_index += 1
            if col_index >= 16:  # Move to the next row if column limit is exceeded
                col_index = 0
                row_index += 1
        
        # CRED-GATE: auto-clear after timeout
        if credential_auth.show_expired(_cred_show_time[0]):
            _cred_show_time[0] = None
            _cred_challenge[0] = None               # CRED-GATE-FIX: reset after show expires
            lcd.clear(); lcd.home()
            menuSubSubSubSubState = DEVICE_PORT
            menuCurrentPos = DEVICE_PORT  # FIX: sync menuCurrentPos after timeout
            return
        menuSubSubSubSubState = menuPositionUpDn(MIN_POS, MAX_POS)

    # ADD DEVICE PASS
    elif menuSubSubSubSubState == ADD_DEVICE_PASS:
        if clearKey == 1:
            clearKey = 0
            keyPos = 0             
            lcd.clear()
            lcd.home()
        #keypadScanningMultiKey(15, 0, None)
        keypadScanningMultiKeyWithSmallCaps(15, 0, None)
        lcd.home()
        lcd.message("\n")
        for index in range(0, 16, 1):
            lcd.message(str(branchNameAddressBuffer[0][index]))
        lcd.setCursor(keyPos, 1)  # Row 1, Column `keyPos` Set the cursor position for user input
        lcd.cursor()  # Show cursor     
        menuSubSubSubSubState = menuPositionUpDn(MIN_POS, MAX_POS)

    # REG DEVICE PASS
    elif menuSubSubSubSubState == REG_DEVICE_PASS:
        if clearKey == 1:
            clearKey = 0
            lcd.clear()
            lcd.home()
        keypadScanningMultiKey(15, 0, None)
        lcd.home()
        lcd.noCursor()
        #lcd.message("UpdateDevicePass\n  >" if toggleBit500mSecSec else "   ")
        lcd.message("< Upd Dev Pass >")
        lcd.message("\n")
        lcd.message("    [Enter]     ")
        
        if keypressed == "B":
            keypressed = None
            
            result = ''
            #for item in sequence:
            for item in branchNameAddressBuffer[0]:
                if item == ' ':
                    break
                result += str(item)


            # Update each field using the modify_device_field_by_type function
            try:
                #dpm.modify_device_field_by_type(device_type, "device_type", new_device_type)
                #dpm.modify_device_field_by_type('HikvisionNVR1', "ip_address", result)
                #dpm.modify_device_field_by_type('HikvisionNVR1', "username", result)
                dpm.modify_device_field_by_type(device_type, "password", result)
                #dpm.modify_device_field_by_type(device_type, "port", new_port)
                #print(f"All parameters updated successfully for devices of type {device_type}")
            except ValueError as e:
                print(f"Error: {e}")
                logger.error(f"Error: {e}")
            except Exception as e:
                print(f"An unexpected error occurred: {e}")
                logger.error(f"Error: {e}")

            lcd.clear()
            lcd.home()
            
        menuSubSubSubSubState = menuPositionUpDn(MIN_POS, MAX_POS)

    # DEVICE PORT -------------------------------------------------------------------------------- 3
    elif menuSubSubSubSubState == DEVICE_PORT:                       #
        #port_number = network_settings.get_setting("Set Port Number")        
        if clearKey == 0:
            clearKey = 1
            keypadScanning(0,0,0,0,'clear')
            keyDetect = 0
            lcd.clear()
            lcd.home()
        lcd.home()            
        lcd.noCursor()
        keyDetect = keypadScanning(5,0,65535,1)
        lcd.message("< Set Port Num >")
        lcd.message("\n")
        lcd.message("[")
        lcd.message(str(port_ai))
        lcd.message("] ")
        if toggleBit500mSecSec:
            lcd.message(">")
        else:
            lcd.message(" ")                
        lcd.message(str(keyDetect))
        lcd.message("   ")
        
        if keypressed == "B":
            keypressed = None

            # Update each field using the modify_device_field_by_type function
            try:
                #dpm.modify_device_field_by_type(device_type, "device_type", new_device_type)
                #dpm.modify_device_field_by_type('HikvisionNVR1', "ip_address", result)
                #dpm.modify_device_field_by_type('HikvisionNVR1', "username", result)
                #dpm.modify_device_field_by_type('HikvisionNVR1', "password", result)
                dpm.modify_device_field_by_type(device_type, "port", keyDetect)
                #print(f"All parameters updated successfully for devices of type {device_type}")
            except ValueError as e:
                print(f"Error: {e}")
                logger.error(f"Error: {e}")
            except Exception as e:
                print(f"An unexpected error occurred: {e}")
                logger.error(f"Error: {e}")
            lcd.clear()
        menuSubSubSubSubState = menuPositionUpDn(0,MAX_POS)

    # EXIT
    elif menuSubSubSubSubState == EXIT:
        lcd.home()
        lcd.message("<     EXIT      \n    [ENTER]     ")
        menuSubSubSubSubState = menuPositionUpDn(MIN_POS, MAX_POS)
        
        if keypressed == "B":
            keypressed = None
            menuSubSubSubSubState = 1
            menuSubSubSubState = 1
            menuCurrentPos = 1
            lcd.clear()
            lcd.home()
            


def menuSubSubSubStateDAHUA_NVR_PROG():

    DEVICE_ID, DEVICE_IP, ADD_DEVICE_IP, REG_DEVICE_IP, DEVICE_NAME, ADD_DEVICE_NAME, REG_DEVICE_NAME, CG_REQ, CG_VFY, DEVICE_PASS, ADD_DEVICE_PASS, REG_DEVICE_PASS, DEVICE_PORT, EXIT = range(14)  # CRED-GATE
    
    MAX_POS = EXIT
    MIN_POS = DEVICE_ID

    global menuSubSubSubSubState

    global menuSubSubSubState
    global branchNameAddressBuffer
    global keypressed
    global clearKey
    global toggleBit500mSecSec
    global keyPos

    global rtcProgSetMenu
    global menuMainState
    global menuCurrentPos
    global keypressed
    global keyDetect
    global GuserSetState
    global menuSubState
    global GmainStateState
    global clearKey
    global toggleBit500mSecSec

    global menuSubState
    global index
    global sub_index
    global GmainStateState
    global menuCurrentPos
    global GuserSetState
    global keypressed
    global menuMainState

    global menuSubSubState

    global toggleBit500mSecSec

    global phoneNumberBuff
    global keyPos

    global keypressed
    global value1
    global GmainStateState
    global menuCurrentPos
    global GuserSetState
    global menuSubState
    global menuMainState

    global progPass
    global toggleBit500mSecSec
    global isPasswordMatched
    global beepOn1Sec

    global repeatCounter
    global multikey_Dic 
    global keyInputMultiMode
    global branchNameAddress
    global branchNameAddressBuffer
    global keyPos

    global device_id_ai
    global device_type_ai
    global ip_address_ai
    global username_ai
    global password_ai
    global port_ai

    
    device_type = "DahuaNVR1"

    # Fetch devices of type "Hikvision NVR"
    devices = dpm.get_device_parameters(device_type)

    # Iterate through the result and extract individual parameters
    for device in devices:
        device_id_ai = device['id']       # ID
        device_type_ai = device['device_type']     # Device Type
        ip_address_ai = device['ip_address']      # IP Address
        username_ai = device['username']        # Username
        password_ai = device['password']        # Password
        port_ai = device['port']            # Port

    # DEVICE_ID  --------------------------------------------------------------------------------
    if menuSubSubSubSubState == DEVICE_ID:
        
        keyDetect = keypadScanning(2,0,99,0)
        if clearKey == 0:
            clearKey = 1
            keypadScanning(0,0,0,0,'clear')
            keyDetect = 0
            lcd.clear()
            lcd.home()
        lcd.noCursor()    
        lcd.home()
        lcd.message(str(device_type_ai))
        lcd.message("       ")        
        lcd.message("\n")
        lcd.message("ID No: [")
        try:
            lcd.message(str(device_id_ai))
        except ValueError:
            lcd.message(str(0))
        except IOError:
            lcd.message(str(0))
            
        lcd.message("]       ")
            
        lcd.message(str(keyDetect))
        if keypressed == "B":
            keypressed = None
            keypadScanning(0,0,0,0,'clear')
            lcd.clear()
            lcd.home()                
        menuSubSubSubSubState = menuPositionUpDn(0,MAX_POS)

    # DEVICE IP -------------------------------------------------------------------------------- 3
    elif menuSubSubSubSubState == DEVICE_IP:                       #
        
        if clearKey == 1:
            clearKey = 0
            keypadScanning(0,0,0,0,'clear')
            keyDetect = 0
            keyPos = 0             
            lcd.clear()
            lcd.home()
        lcd.noCursor()
        lcd.message("< Set  IP Addr >")
        lcd.message("\n")
        lcd.message(str(ip_address_ai))
        lcd.message("       ")

        # Save the string into the 2D list
        row_index = 0
        col_index = 0

        for char in ip_address_ai:
            phoneNumberBuff[row_index][col_index] = char
            col_index += 1
            if col_index >= 16:  # Move to the next row if column limit is exceeded
                col_index = 0
                row_index += 1
            
        menuSubSubSubSubState = menuPositionUpDn(0,MAX_POS)

    # ADD DEVICE IP
    elif menuSubSubSubSubState == ADD_DEVICE_IP:                       

        if clearKey == 0:
            clearKey = 1
            keypadScanning(0,0,0,0,'clear')
            keyDetect = 0
            keyPos = 0
            padWithSpace = 0            
            for index in range(0,14,1):
                phoneNumberBuff[6][index] = ' '
            lcd.clear()
            lcd.home()                
            
        keypadScanningMultiNumKeyWithDot(14,6,None)
        lcd.home()

        lcd.message("\n")
        for index in range(0,14,1):
            lcd.message(str(phoneNumberBuff[6][index]))
        lcd.setCursor(keyPos, 1)  # Row 1, Column `keyPos` Set the cursor position for user input
        lcd.cursor()  # Show cursor 
        menuSubSubSubSubState = menuPositionUpDn(0,MAX_POS)

    # REG DEVICE IP
    elif menuSubSubSubSubState == REG_DEVICE_IP:        #
        
        if clearKey == 1:
            clearKey = 0
            keypadScanning(0,0,0,0,'clear')
            keyDetect = 0
            keyPos = 0             
            lcd.clear()
            lcd.home()            
        lcd.home()
        lcd.noCursor()
        lcd.message("< Upd  IP Addr >")
        lcd.message("\n")
        lcd.message("    [Enter]     ")

        if keypressed == "B":
            keypressed = None
            result = ''
            #for item in sequence:
            for item in phoneNumberBuff[6]:
                if item == ' ':
                    break
                result += str(item)            
            #result = "192.168.0.55"
#            print(result)  # Output: 192.168.0.134

            # Update each field using the modify_device_field_by_type function
            try:
                #dpm.modify_device_field_by_type(device_type, "device_type", new_device_type)
                dpm.modify_device_field_by_type(device_type, "ip_address", result)
                #dpm.modify_device_field_by_type(device_type, "username", new_username)
                #dpm.modify_device_field_by_type(device_type, "password", new_password)
                #dpm.modify_device_field_by_type(device_type, "port", new_port)
               # print (f"All parameters updated successfully for devices of type {device_type}")
            except ValueError as e:
                print(f"Error: {e}")
                logger.error(f"Error: {e}")
            except Exception as e:
                print(f"An unexpected error occurred: {e}")
                logger.error(f"Error: {e}")

        menuSubSubSubSubState = menuPositionUpDn(0,MAX_POS)	

    # DEVICE NAME -------------------------------------------------------------------------------- 3
    elif menuSubSubSubSubState == DEVICE_NAME:
        if clearKey == 0:
            clearKey = 1
            lcd.clear()
            lcd.home()
            keyPos = 0             
        lcd.home()
        lcd.noCursor()
        lcd.message("< Set Dev Name >")        
        lcd.message("\n")
        lcd.message(str(username_ai))
        lcd.message("          ")

        for index in range(0,16,1):
            branchNameAddressBuffer[0][index] = ' '

        # Save the string into the 2D list
        row_index = 0
        col_index = 0

        for char in username_ai:
            branchNameAddressBuffer[row_index][col_index] = char
            col_index += 1
            if col_index >= 16:  # Move to the next row if column limit is exceeded
                col_index = 0
                row_index += 1
        
        menuSubSubSubSubState = menuPositionUpDn(MIN_POS, MAX_POS)

    # ADD DEVICE NAME
    elif menuSubSubSubSubState == ADD_DEVICE_NAME:
        if clearKey == 1:
            clearKey = 0
            keyPos = 0             
            lcd.clear()
            lcd.home()
        keypadScanningMultiKeyWithSmallCaps(15, 0, None)
        lcd.home()
        lcd.message("\n")
        for index in range(0, 16, 1):
            lcd.message(str(branchNameAddressBuffer[0][index]))
        lcd.setCursor(keyPos, 1)  # Row 1, Column `keyPos` Set the cursor position for user input
        lcd.cursor()  # Show cursor    
        menuSubSubSubSubState = menuPositionUpDn(MIN_POS, MAX_POS)

    # REG DEVICE NAME
    elif menuSubSubSubSubState == REG_DEVICE_NAME:
        if clearKey == 0:
            clearKey = 1
            keyPos = 0             
            lcd.clear()
            lcd.home()
        lcd.home()
        lcd.noCursor()
        lcd.message("< Upd Dev Name >")
        lcd.message("\n")
        lcd.message("    [Enter]     ")
        
        if keypressed == "B":
            keypressed = None
            
            result = ''
            #for item in sequence:
            for item in branchNameAddressBuffer[0]:
                if item == ' ':
                    break
                result += str(item)

            # Update each field using the modify_device_field_by_type function
            try:
                #dpm.modify_device_field_by_type(device_type, "device_type", new_device_type)
                #dpm.modify_device_field_by_type('HikvisionNVR1', "ip_address", result)
                dpm.modify_device_field_by_type(device_type, "username", result)
                #dpm.modify_device_field_by_type(device_type, "password", new_password)
                #dpm.modify_device_field_by_type(device_type, "port", new_port)
                print(f"All parameters updated successfully for devices of type {device_type}")
            except ValueError as e:
                print(f"Error: {e}")
                logger.error(f"Error: {e}")
            except Exception as e:
                print(f"An unexpected error occurred: {e}")
                logger.error(f"Error: {e}")
            
            lcd.clear()
            lcd.home()
        menuSubSubSubSubState = menuPositionUpDn(MIN_POS, MAX_POS)

    # CRED-GATE: challenge-response before showing device password
    elif menuSubSubSubSubState == CG_REQ:
        import time as _ct
        if _cred_session_expiry[0] and _ct.time() < _cred_session_expiry[0]:
            _cred_show_time[0] = _ct.time()
            menuSubSubSubSubState = DEVICE_PASS
            menuCurrentPos = DEVICE_PASS  # FIX: sync menuCurrentPos so arrows work
            lcd.clear(); lcd.home()
            return
        if not credential_auth.key_is_loaded():
            lcd.clear(); lcd.home()
            lcd.message("Key not set    \n")
            lcd.message("Contact Seple  ")
            menuSubSubSubSubState = DEVICE_PORT
            return
        if credential_auth.is_locked_out():
            secs = credential_auth.time_remaining_locked()
            lcd.clear(); lcd.home()
            lcd.message("Access locked  \n")
            lcd.message(str(secs) + "s remaining    ")
            _cred_challenge[0] = None               # CRED-GATE-FIX: reset so next entry is fresh
            menuSubSubSubSubState = DEVICE_PORT
            return
        if _cred_challenge[0] is None:          # generate once per entry
            _cred_challenge[0] = credential_auth.generate_challenge()
            _cred_resp_digits[0] = ''
        # Display on EVERY tick — keeps LCD showing challenge while operator reads it
        lcd.noCursor()
        lcd.message("Call Seple:    \n")
        lcd.message(str(_cred_challenge[0]) + "            ")
        menuSubSubSubSubState = menuPositionUpDn(CG_REQ, CG_VFY)

    elif menuSubSubSubSubState == CG_VFY:
        if credential_auth.is_locked_out():
            secs = credential_auth.time_remaining_locked()
            lcd.clear(); lcd.home()
            lcd.message("Access locked  \n")
            lcd.message(str(secs) + "s remaining    ")
            _cred_challenge[0] = None               # CRED-GATE-FIX: reset so next entry is fresh
            menuSubSubSubSubState = DEVICE_PORT
            return
        #global keypressed
        lcd.noCursor()
        lcd.message("Enter code:    \n")
        display = _cred_resp_digits[0].ljust(6, '_')
        lcd.message(display + "          ")
        if keypressed and keypressed.isdigit() and len(_cred_resp_digits[0]) < 6:
            _cred_resp_digits[0] += keypressed
            keypressed = None
        elif keypressed == "C":
            _cred_resp_digits[0] = ''
            keypressed = None
        elif keypressed == "B" and len(_cred_resp_digits[0]) == 6:
            keypressed = None
            if credential_auth.verify_response(_cred_challenge[0], _cred_resp_digits[0]):
                import time as _t
                _cred_show_time[0] = _t.time()
                _cred_session_expiry[0] = _t.time() + _CRED_SESSION_SEC
                _cred_challenge[0] = None
                _cred_resp_digits[0] = ''
                menuSubSubSubSubState = DEVICE_PASS
                menuCurrentPos = DEVICE_PASS  # FIX: sync menuCurrentPos so arrows work
                lcd.clear(); lcd.home()
            else:
                lcd.clear(); lcd.home()
                lcd.message("Access denied  \n")
                lcd.message("Wrong code     ")
                _cred_challenge[0] = None               # CRED-GATE-FIX: reset on wrong code
                menuSubSubSubSubState = DEVICE_PORT
        elif keypressed == "D":
            keypressed = None
            _cred_challenge[0] = None               # CRED-GATE-FIX: reset on cancel
            menuSubSubSubSubState = DEVICE_PORT
            lcd.clear(); lcd.home()

    # DEVICE PASS -------------------------------------------------------------------------------- 3
    elif menuSubSubSubSubState == DEVICE_PASS:
        if clearKey == 0:
            clearKey = 1
            keyPos = 0             
            lcd.clear()
            lcd.home()
        lcd.home()
        lcd.noCursor()
        lcd.message("< Set Dev Pass >")
        lcd.message("\n")
        lcd.message(str(password_ai))
        lcd.message("         ")

        for index in range(0,16,1):
            branchNameAddressBuffer[0][index] = ' '

        # Save the string into the 2D list
        row_index = 0
        col_index = 0

        for char in password_ai:
            branchNameAddressBuffer[row_index][col_index] = char
            col_index += 1
            if col_index >= 16:  # Move to the next row if column limit is exceeded
                col_index = 0
                row_index += 1
        
        # CRED-GATE: auto-clear after timeout
        if credential_auth.show_expired(_cred_show_time[0]):
            _cred_show_time[0] = None
            _cred_challenge[0] = None               # CRED-GATE-FIX: reset after show expires
            lcd.clear(); lcd.home()
            menuSubSubSubSubState = DEVICE_PORT
            menuCurrentPos = DEVICE_PORT  # FIX: sync menuCurrentPos after timeout
            return
        menuSubSubSubSubState = menuPositionUpDn(MIN_POS, MAX_POS)

    # ADD DEVICE PASS
    elif menuSubSubSubSubState == ADD_DEVICE_PASS:
        if clearKey == 1:
            clearKey = 0
            keyPos = 0             
            lcd.clear()
            lcd.home()
        #keypadScanningMultiKey(15, 0, None)
        keypadScanningMultiKeyWithSmallCaps(15, 0, None)
        lcd.home()
        lcd.message("\n")
        for index in range(0, 16, 1):
            lcd.message(str(branchNameAddressBuffer[0][index]))
        lcd.setCursor(keyPos, 1)  # Row 1, Column `keyPos` Set the cursor position for user input
        lcd.cursor()  # Show cursor    
        menuSubSubSubSubState = menuPositionUpDn(MIN_POS, MAX_POS)

    # REG DEVICE PASS
    elif menuSubSubSubSubState == REG_DEVICE_PASS:
        if clearKey == 1:
            clearKey = 0
            lcd.clear()
            lcd.home()
        keypadScanningMultiKey(15, 0, None)
        lcd.home()
        lcd.noCursor()
        lcd.message("< Upd Dev Pass >")
        lcd.message("\n")
        lcd.message("    [Enter]     ")
        
        if keypressed == "B":
            keypressed = None
            
            result = ''
            #for item in sequence:
            for item in branchNameAddressBuffer[0]:
                if item == ' ':
                    break
                result += str(item)
           

            # Update each field using the modify_device_field_by_type function
            try:
                #dpm.modify_device_field_by_type(device_type, "device_type", new_device_type)
                #dpm.modify_device_field_by_type('HikvisionNVR1', "ip_address", result)
                #dpm.modify_device_field_by_type('HikvisionNVR1', "username", result)
                dpm.modify_device_field_by_type(device_type, "password", result)
                #dpm.modify_device_field_by_type(device_type, "port", new_port)
                print (f"All parameters updated successfully for devices of type {device_type}")
            except ValueError as e:
                print(f"Error: {e}")
                logger.error(f"Error: {e}")
            except Exception as e:
                print(f"An unexpected error occurred: {e}")
                logger.error(f"Error: {e}")
            
            lcd.clear()
            lcd.home()
            
        menuSubSubSubSubState = menuPositionUpDn(MIN_POS, MAX_POS)

    # DEVICE PORT -------------------------------------------------------------------------------- 3
    elif menuSubSubSubSubState == DEVICE_PORT:                       #
        #port_number = network_settings.get_setting("Set Port Number")        
        if clearKey == 0:
            clearKey = 1
            keypadScanning(0,0,0,0,'clear')
            keyDetect = 0
            lcd.clear()
            lcd.home()
        lcd.home()            
        lcd.noCursor()
        keyDetect = keypadScanning(5,0,65535,1)
        lcd.message("< Set Port Num >")
        lcd.message("\n")
        lcd.message("[")
        lcd.message(str(port_ai))
        lcd.message("] ")
        if toggleBit500mSecSec:
            lcd.message(">")
        else:
            lcd.message(" ")                
        lcd.message(str(keyDetect))
        lcd.message("   ")
        
        if keypressed == "B":
            keypressed = None

            # Update each field using the modify_device_field_by_type function
            try:
                #dpm.modify_device_field_by_type(device_type, "device_type", new_device_type)
                #dpm.modify_device_field_by_type('HikvisionNVR1', "ip_address", result)
                #dpm.modify_device_field_by_type('HikvisionNVR1', "username", result)
                #dpm.modify_device_field_by_type('HikvisionNVR1', "password", result)
                dpm.modify_device_field_by_type(device_type, "port", keyDetect)
                print(f"All parameters updated successfully for devices of type {device_type}")
            except ValueError as e:
                print(f"Error: {e}")
                logger.error(f"Error: {e}")
            except Exception as e:
                print(f"An unexpected error occurred: {e}")
                logger.error(f"Error: {e}")
            lcd.clear()
        menuSubSubSubSubState = menuPositionUpDn(0,MAX_POS)

    # EXIT
    elif menuSubSubSubSubState == EXIT:
        lcd.home()
        lcd.message("<     EXIT      \n    [ENTER]     ")
        menuSubSubSubSubState = menuPositionUpDn(MIN_POS, MAX_POS)
        
        if keypressed == "B":
            keypressed = None
            menuSubSubSubSubState = 2
            menuSubSubSubState = 2
            menuCurrentPos = 2
            lcd.clear()
            lcd.home()

def menuSubSubSubStateCP_PLUS_NVR_PROG():

    DEVICE_ID, DEVICE_IP, ADD_DEVICE_IP, REG_DEVICE_IP, DEVICE_NAME, ADD_DEVICE_NAME, REG_DEVICE_NAME, CG_REQ, CG_VFY, DEVICE_PASS, ADD_DEVICE_PASS, REG_DEVICE_PASS, DEVICE_PORT, EXIT = range(14)  # CRED-GATE
    
    MAX_POS = EXIT
    MIN_POS = DEVICE_ID

    global menuSubSubSubSubState

    global menuSubSubSubState
    global branchNameAddressBuffer
    global keypressed
    global clearKey
    global toggleBit500mSecSec
    global keyPos

    global rtcProgSetMenu
    global menuMainState
    global menuCurrentPos
    global keypressed
    global keyDetect
    global GuserSetState
    global menuSubState
    global GmainStateState
    global clearKey
    global toggleBit500mSecSec

    global menuSubState
    global index
    global sub_index
    global GmainStateState
    global menuCurrentPos
    global GuserSetState
    global keypressed
    global menuMainState

    global menuSubSubState

    global toggleBit500mSecSec

    global phoneNumberBuff
    global keyPos

    global keypressed
    global value1
    global GmainStateState
    global menuCurrentPos
    global GuserSetState
    global menuSubState
    global menuMainState

    global progPass
    global toggleBit500mSecSec
    global isPasswordMatched
    global beepOn1Sec

    global repeatCounter
    global multikey_Dic 
    global keyInputMultiMode
    global branchNameAddress
    global branchNameAddressBuffer
    global keyPos

    global device_id_ai
    global device_type_ai
    global ip_address_ai
    global username_ai
    global password_ai
    global port_ai

    
    device_type = "CP_PlusNVR1"

    # Fetch devices of type "Hikvision NVR"
    devices = dpm.get_device_parameters(device_type)

    # Iterate through the result and extract individual parameters
    for device in devices:
        device_id_ai = device['id']       # ID
        device_type_ai = device['device_type']     # Device Type
        ip_address_ai = device['ip_address']      # IP Address
        username_ai = device['username']        # Username
        password_ai = device['password']        # Password
        port_ai = device['port']            # Port

    # DEVICE_ID  --------------------------------------------------------------------------------
    if menuSubSubSubSubState == DEVICE_ID:
        
        keyDetect = keypadScanning(2,0,99,0)
        if clearKey == 0:
            clearKey = 1
            keypadScanning(0,0,0,0,'clear')
            keyDetect = 0
            lcd.clear()
            lcd.home()
        lcd.noCursor()    
        lcd.home()
        lcd.message(str(device_type_ai))
        lcd.message("       ")        
        lcd.message("\n")
        lcd.message("ID No: [")
        try:
            lcd.message(str(device_id_ai))
        except ValueError:
            lcd.message(str(0))
        except IOError:
            lcd.message(str(0))
            
        lcd.message("]       ")
            
        lcd.message(str(keyDetect))
        if keypressed == "B":
            keypressed = None
            keypadScanning(0,0,0,0,'clear')
            lcd.clear()
            lcd.home()                
        menuSubSubSubSubState = menuPositionUpDn(0,MAX_POS)

    # DEVICE IP -------------------------------------------------------------------------------- 3
    elif menuSubSubSubSubState == DEVICE_IP:                       #
        
        if clearKey == 1:
            clearKey = 0
            keypadScanning(0,0,0,0,'clear')
            keyDetect = 0
            keyPos = 0             
            lcd.clear()
            lcd.home()
        lcd.noCursor()
        lcd.message("< Set  IP Addr >")
        lcd.message("\n")
        lcd.message(str(ip_address_ai))
        lcd.message("       ")

        # Save the string into the 2D list
        row_index = 0
        col_index = 0

        for char in ip_address_ai:
            phoneNumberBuff[row_index][col_index] = char
            col_index += 1
            if col_index >= 16:  # Move to the next row if column limit is exceeded
                col_index = 0
                row_index += 1
            
        menuSubSubSubSubState = menuPositionUpDn(0,MAX_POS)

    # ADD DEVICE IP
    elif menuSubSubSubSubState == ADD_DEVICE_IP:                       

        if clearKey == 0:
            clearKey = 1
            keypadScanning(0,0,0,0,'clear')
            keyDetect = 0
            keyPos = 0
            padWithSpace = 0            
            for index in range(0,14,1):
                phoneNumberBuff[6][index] = ' '
            lcd.clear()
            lcd.home()                
            
        keypadScanningMultiNumKeyWithDot(14,6,None)
        lcd.home()

        lcd.message("\n")
        for index in range(0,14,1):
            lcd.message(str(phoneNumberBuff[6][index]))
        lcd.setCursor(keyPos, 1)  # Row 1, Column `keyPos` Set the cursor position for user input
        lcd.cursor()  # Show cursor 
        menuSubSubSubSubState = menuPositionUpDn(0,MAX_POS)

    # REG DEVICE IP
    elif menuSubSubSubSubState == REG_DEVICE_IP:        #
        
        if clearKey == 1:
            clearKey = 0
            keypadScanning(0,0,0,0,'clear')
            keyDetect = 0
            keyPos = 0             
            lcd.clear()
            lcd.home()            
        lcd.home()
        lcd.noCursor()
        lcd.message("< Upd  IP Addr >")
        lcd.message("\n")
        lcd.message("    [Enter]     ")

        if keypressed == "B":
            keypressed = None
            result = ''
            for item in phoneNumberBuff[6]:
                if item == ' ':
                    break
                result += str(item)     

            # Update each field using the modify_device_field_by_type function
            try:
                #dpm.modify_device_field_by_type(device_type, "device_type", new_device_type)
                dpm.modify_device_field_by_type(device_type, "ip_address", result)
                #dpm.modify_device_field_by_type(device_type, "username", new_username)
                #dpm.modify_device_field_by_type(device_type, "password", new_password)
                #dpm.modify_device_field_by_type(device_type, "port", new_port)
               # print (f"All parameters updated successfully for devices of type {device_type}")
            except ValueError as e:
                print(f"Error: {e}")
                logger.error(f"Error: {e}")
            except Exception as e:
                print(f"An unexpected error occurred: {e}")
                logger.error(f"Error: {e}")

        menuSubSubSubSubState = menuPositionUpDn(0,MAX_POS)	

    # DEVICE NAME -------------------------------------------------------------------------------- 3
    elif menuSubSubSubSubState == DEVICE_NAME:
        if clearKey == 0:
            clearKey = 1
            lcd.clear()
            lcd.home()
            keyPos = 0             
        lcd.home()
        lcd.noCursor()
        lcd.message("< Set Dev Name >")        
        lcd.message("\n")
        lcd.message(str(username_ai))
        lcd.message("          ")

        for index in range(0,16,1):
            branchNameAddressBuffer[0][index] = ' '

        # Save the string into the 2D list
        row_index = 0
        col_index = 0

        for char in username_ai:
            branchNameAddressBuffer[row_index][col_index] = char
            col_index += 1
            if col_index >= 16:  # Move to the next row if column limit is exceeded
                col_index = 0
                row_index += 1
        
        menuSubSubSubSubState = menuPositionUpDn(MIN_POS, MAX_POS)

    # ADD DEVICE NAME
    elif menuSubSubSubSubState == ADD_DEVICE_NAME:
        if clearKey == 1:
            clearKey = 0
            keyPos = 0             
            lcd.clear()
            lcd.home()
        keypadScanningMultiKeyWithSmallCaps(15, 0, None)
        lcd.home()
        lcd.message("\n")
        for index in range(0, 16, 1):
            lcd.message(str(branchNameAddressBuffer[0][index]))
        lcd.setCursor(keyPos, 1)  # Row 1, Column `keyPos` Set the cursor position for user input
        lcd.cursor()  # Show cursor    
        menuSubSubSubSubState = menuPositionUpDn(MIN_POS, MAX_POS)

    # REG DEVICE NAME
    elif menuSubSubSubSubState == REG_DEVICE_NAME:
        if clearKey == 0:
            clearKey = 1
            keyPos = 0             
            lcd.clear()
            lcd.home()
        lcd.home()
        lcd.noCursor()
        lcd.message("< Upd Dev Name >")
        lcd.message("\n")
        lcd.message("    [Enter]     ")
        
        if keypressed == "B":
            keypressed = None
            
            result = ''
            #for item in sequence:
            for item in branchNameAddressBuffer[0]:
                if item == ' ':
                    break
                result += str(item)
                

            # Update each field using the modify_device_field_by_type function
            try:
                #dpm.modify_device_field_by_type(device_type, "device_type", new_device_type)
                #dpm.modify_device_field_by_type('HikvisionNVR1', "ip_address", result)
                dpm.modify_device_field_by_type(device_type, "username", result)
                #dpm.modify_device_field_by_type(device_type, "password", new_password)
                #dpm.modify_device_field_by_type(device_type, "port", new_port)
                print(f"All parameters updated successfully for devices of type {device_type}")
            except ValueError as e:
                print(f"Error: {e}")
                logger.error(f"Error: {e}")
            except Exception as e:
                print(f"An unexpected error occurred: {e}")
                logger.error(f"An unexpected error occurred: {e}")
            
            lcd.clear()
            lcd.home()
        menuSubSubSubSubState = menuPositionUpDn(MIN_POS, MAX_POS)

    # CRED-GATE: challenge-response before showing device password
    elif menuSubSubSubSubState == CG_REQ:
        import time as _ct
        if _cred_session_expiry[0] and _ct.time() < _cred_session_expiry[0]:
            _cred_show_time[0] = _ct.time()
            menuSubSubSubSubState = DEVICE_PASS
            menuCurrentPos = DEVICE_PASS  # FIX: sync menuCurrentPos so arrows work
            lcd.clear(); lcd.home()
            return
        if not credential_auth.key_is_loaded():
            lcd.clear(); lcd.home()
            lcd.message("Key not set    \n")
            lcd.message("Contact Seple  ")
            menuSubSubSubSubState = DEVICE_PORT
            return
        if credential_auth.is_locked_out():
            secs = credential_auth.time_remaining_locked()
            lcd.clear(); lcd.home()
            lcd.message("Access locked  \n")
            lcd.message(str(secs) + "s remaining    ")
            _cred_challenge[0] = None               # CRED-GATE-FIX: reset so next entry is fresh
            menuSubSubSubSubState = DEVICE_PORT
            return
        if _cred_challenge[0] is None:          # generate once per entry
            _cred_challenge[0] = credential_auth.generate_challenge()
            _cred_resp_digits[0] = ''
        # Display on EVERY tick — keeps LCD showing challenge while operator reads it
        lcd.noCursor()
        lcd.message("Call Seple:    \n")
        lcd.message(str(_cred_challenge[0]) + "            ")
        menuSubSubSubSubState = menuPositionUpDn(CG_REQ, CG_VFY)

    elif menuSubSubSubSubState == CG_VFY:
        if credential_auth.is_locked_out():
            secs = credential_auth.time_remaining_locked()
            lcd.clear(); lcd.home()
            lcd.message("Access locked  \n")
            lcd.message(str(secs) + "s remaining    ")
            _cred_challenge[0] = None               # CRED-GATE-FIX: reset so next entry is fresh
            menuSubSubSubSubState = DEVICE_PORT
            return
        #global keypressed
        lcd.noCursor()
        lcd.message("Enter code:    \n")
        display = _cred_resp_digits[0].ljust(6, '_')
        lcd.message(display + "          ")
        if keypressed and keypressed.isdigit() and len(_cred_resp_digits[0]) < 6:
            _cred_resp_digits[0] += keypressed
            keypressed = None
        elif keypressed == "C":
            _cred_resp_digits[0] = ''
            keypressed = None
        elif keypressed == "B" and len(_cred_resp_digits[0]) == 6:
            keypressed = None
            if credential_auth.verify_response(_cred_challenge[0], _cred_resp_digits[0]):
                import time as _t
                _cred_show_time[0] = _t.time()
                _cred_session_expiry[0] = _t.time() + _CRED_SESSION_SEC
                _cred_challenge[0] = None
                _cred_resp_digits[0] = ''
                menuSubSubSubSubState = DEVICE_PASS
                menuCurrentPos = DEVICE_PASS  # FIX: sync menuCurrentPos so arrows work
                lcd.clear(); lcd.home()
            else:
                lcd.clear(); lcd.home()
                lcd.message("Access denied  \n")
                lcd.message("Wrong code     ")
                _cred_challenge[0] = None               # CRED-GATE-FIX: reset on wrong code
                menuSubSubSubSubState = DEVICE_PORT
        elif keypressed == "D":
            keypressed = None
            _cred_challenge[0] = None               # CRED-GATE-FIX: reset on cancel
            menuSubSubSubSubState = DEVICE_PORT
            lcd.clear(); lcd.home()

    # DEVICE PASS -------------------------------------------------------------------------------- 3
    elif menuSubSubSubSubState == DEVICE_PASS:
        if clearKey == 0:
            clearKey = 1
            keyPos = 0             
            lcd.clear()
            lcd.home()
        lcd.home()
        lcd.noCursor()
        lcd.message("< Set Dev Pass >")
        lcd.message("\n")
        lcd.message(str(password_ai))
        lcd.message("         ")

        for index in range(0,16,1):
            branchNameAddressBuffer[0][index] = ' '

        # Save the string into the 2D list
        row_index = 0
        col_index = 0

        for char in password_ai:
            branchNameAddressBuffer[row_index][col_index] = char
            col_index += 1
            if col_index >= 16:  # Move to the next row if column limit is exceeded
                col_index = 0
                row_index += 1
        
        # CRED-GATE: auto-clear after timeout
        if credential_auth.show_expired(_cred_show_time[0]):
            _cred_show_time[0] = None
            _cred_challenge[0] = None               # CRED-GATE-FIX: reset after show expires
            lcd.clear(); lcd.home()
            menuSubSubSubSubState = DEVICE_PORT
            menuCurrentPos = DEVICE_PORT  # FIX: sync menuCurrentPos after timeout
            return
        menuSubSubSubSubState = menuPositionUpDn(MIN_POS, MAX_POS)

    # ADD DEVICE PASS
    elif menuSubSubSubSubState == ADD_DEVICE_PASS:
        if clearKey == 1:
            clearKey = 0
            keyPos = 0             
            lcd.clear()
            lcd.home()

        keypadScanningMultiKeyWithSmallCaps(15, 0, None)
        lcd.home()
        
        lcd.message("\n")
        for index in range(0, 16, 1):
            lcd.message(str(branchNameAddressBuffer[0][index]))
        lcd.setCursor(keyPos, 1)  # Row 1, Column `keyPos` Set the cursor position for user input
        lcd.cursor()  # Show cursor    
        menuSubSubSubSubState = menuPositionUpDn(MIN_POS, MAX_POS)

    # REG DEVICE PASS
    elif menuSubSubSubSubState == REG_DEVICE_PASS:
        if clearKey == 1:
            clearKey = 0
            lcd.clear()
            lcd.home()
        keypadScanningMultiKey(15, 0, None)
        lcd.home()
        lcd.noCursor()
        #lcd.message("UpdateDevicePass\n  >" if toggleBit500mSecSec else "   ")
        lcd.message("< Upd Dev Pass >")
        lcd.message("\n")
        lcd.message("    [Enter]     ")
        
        if keypressed == "B":
            keypressed = None
            
            result = ''
            #for item in sequence:
            for item in branchNameAddressBuffer[0]:
                if item == ' ':
                    break
                result += str(item)

            # Update each field using the modify_device_field_by_type function
            try:
                #dpm.modify_device_field_by_type(device_type, "device_type", new_device_type)
                #dpm.modify_device_field_by_type('HikvisionNVR1', "ip_address", result)
                #dpm.modify_device_field_by_type('HikvisionNVR1', "username", result)
                dpm.modify_device_field_by_type(device_type, "password", result)
                #dpm.modify_device_field_by_type(device_type, "port", new_port)
                print (f"All parameters updated successfully for devices of type {device_type}")
            except ValueError as e:
                print(f"Error: {e}")
                logger.error(f"Error: {e}")
            except Exception as e:
                print(f"An unexpected error occurred: {e}")
                logger.error(f"An unexpected error occurred: {e}")
            
            lcd.clear()
            lcd.home()
            
        menuSubSubSubSubState = menuPositionUpDn(MIN_POS, MAX_POS)

    # DEVICE PORT -------------------------------------------------------------------------------- 3
    elif menuSubSubSubSubState == DEVICE_PORT:                       #
        #port_number = network_settings.get_setting("Set Port Number")        
        if clearKey == 0:
            clearKey = 1
            keypadScanning(0,0,0,0,'clear')
            keyDetect = 0
            lcd.clear()
            lcd.home()
        lcd.home()            
        lcd.noCursor()
        keyDetect = keypadScanning(5,0,65535,1)
        lcd.message("< Set Port Num >")
        lcd.message("\n")
        lcd.message("[")
        lcd.message(str(port_ai))
        lcd.message("] ")
        if toggleBit500mSecSec:
            lcd.message(">")
        else:
            lcd.message(" ")                
        lcd.message(str(keyDetect))
        lcd.message("   ")
        
        if keypressed == "B":
            keypressed = None

            # Update each field using the modify_device_field_by_type function
            try:
                #dpm.modify_device_field_by_type(device_type, "device_type", new_device_type)
                #dpm.modify_device_field_by_type('HikvisionNVR1', "ip_address", result)
                #dpm.modify_device_field_by_type('HikvisionNVR1', "username", result)
                #dpm.modify_device_field_by_type('HikvisionNVR1', "password", result)
                dpm.modify_device_field_by_type(device_type, "port", keyDetect)
                print(f"All parameters updated successfully for devices of type {device_type}")
            except ValueError as e:
                print(f"Error: {e}")
                logger.error(f"Error: {e}")
            except Exception as e:
                print(f"An unexpected error occurred: {e}")
                logger.error(f"An unexpected error occurred: {e}")
            lcd.clear()
        menuSubSubSubSubState = menuPositionUpDn(0,MAX_POS)

    # EXIT
    elif menuSubSubSubSubState == EXIT:
        lcd.home()
        lcd.message("<     EXIT      \n    [ENTER]     ")
        menuSubSubSubSubState = menuPositionUpDn(MIN_POS, MAX_POS)
        
        if keypressed == "B":
            keypressed = None
            menuSubSubSubSubState = 3
            menuSubSubSubState = 3
            menuCurrentPos = 3
            lcd.clear()
            lcd.home()

def menuSubSubSubStateTEXECOM_BAS_PROG():
    """
    LCD sub-sub-sub-state machine for Texecom BAS programming.
    Allows operator to view and update panel IP, UDL password and port.
    Uses device_type = 'TexecomBAS1' in device_config.db.
    Entry via: menuSubSubStateACTIVE_INTEGR_PROG → TEXECOM_BAS_PROG state.
    CRED-GATE: UDL password is protected by challenge-response (CG_REQ / CG_VFY)
    before the DEVICE_PASS show-state, matching the Hikvision NVR pattern.
    """

    # CRED-GATE: two gate states inserted before DEVICE_PASS
    DEVICE_ID, DEVICE_IP, ADD_DEVICE_IP, REG_DEVICE_IP, \
    CG_REQ, CG_VFY, \
    DEVICE_PASS, ADD_DEVICE_PASS, REG_DEVICE_PASS, \
    DEVICE_PORT, EXIT = range(11)

    MAX_POS = EXIT
    MIN_POS = DEVICE_ID

    global menuSubSubSubSubState
    global menuSubSubSubState
    global branchNameAddressBuffer
    global keypressed
    global clearKey
    global toggleBit500mSecSec
    global keyPos
    global rtcProgSetMenu
    global menuMainState
    global menuCurrentPos
    global keyDetect
    global GuserSetState
    global menuSubState
    global GmainStateState
    global menuSubState
    global index
    global sub_index
    global menuMainState
    global menuSubSubState
    global phoneNumberBuff
    global value1
    global progPass
    global isPasswordMatched
    global beepOn1Sec
    global repeatCounter
    global multikey_Dic
    global keyInputMultiMode
    global branchNameAddress
    global keyPos
    global device_id_ai
    global device_type_ai
    global ip_address_ai
    global username_ai
    global password_ai
    global port_ai

    device_type = "TexecomBAS1"

    devices = dpm.get_device_parameters(device_type)
    for device in devices:
        device_id_ai   = device['id']
        device_type_ai = device['device_type']
        ip_address_ai  = device['ip_address']
        username_ai    = device['username']
        password_ai    = device['password']
        port_ai        = device['port']

    # DEVICE_ID
    if menuSubSubSubSubState == DEVICE_ID:
        keyDetect = keypadScanning(2, 0, 99, 0)
        if clearKey == 0:
            clearKey = 1
            keypadScanning(0, 0, 0, 0, 'clear')
            keyDetect = 0
            lcd.clear()
            lcd.home()
        lcd.noCursor()
        lcd.home()
        lcd.message(str(device_type_ai))
        lcd.message("       ")
        lcd.message("\n")
        lcd.message("ID No: [")
        try:
            lcd.message(str(device_id_ai))
        except (ValueError, IOError):
            lcd.message(str(0))
        lcd.message("]       ")
        lcd.message(str(keyDetect))
        if keypressed == "B":
            keypressed = None
            keypadScanning(0, 0, 0, 0, 'clear')
            lcd.clear()
            lcd.home()
        menuSubSubSubSubState = menuPositionUpDn(0, MAX_POS)

    # DEVICE_IP
    elif menuSubSubSubSubState == DEVICE_IP:
        if clearKey == 1:
            clearKey = 0
            keypadScanning(0, 0, 0, 0, 'clear')
            keyDetect = 0
            keyPos = 0
            lcd.clear()
            lcd.home()
        lcd.noCursor()
        lcd.message("< Set  IP Addr >")
        lcd.message("\n")
        lcd.message(str(ip_address_ai))
        lcd.message("       ")
        row_index = 0
        col_index = 0
        for char in ip_address_ai:
            phoneNumberBuff[row_index][col_index] = char
            col_index += 1
            if col_index >= 16:
                col_index = 0
                row_index += 1
        menuSubSubSubSubState = menuPositionUpDn(0, MAX_POS)

    # ADD_DEVICE_IP
    elif menuSubSubSubSubState == ADD_DEVICE_IP:
        if clearKey == 0:
            clearKey = 1
            keypadScanning(0, 0, 0, 0, 'clear')
            keyDetect = 0
            keyPos = 0
            padWithSpace = 0
            for index in range(0, 14, 1):
                phoneNumberBuff[6][index] = ' '
            lcd.clear()
            lcd.home()
        keypadScanningMultiNumKeyWithDot(14, 6, None)
        lcd.home()
        lcd.message("\n")
        for index in range(0, 14, 1):
            lcd.message(str(phoneNumberBuff[6][index]))
        lcd.setCursor(keyPos, 1)
        lcd.cursor()
        menuSubSubSubSubState = menuPositionUpDn(0, MAX_POS)

    # REG_DEVICE_IP
    elif menuSubSubSubSubState == REG_DEVICE_IP:
        if clearKey == 1:
            clearKey = 0
            keypadScanning(0, 0, 0, 0, 'clear')
            keyDetect = 0
            keyPos = 0
            lcd.clear()
            lcd.home()
        lcd.home()
        lcd.noCursor()
        lcd.message("< Upd  IP Addr >")
        lcd.message("\n")
        lcd.message("    [Enter]     ")
        if keypressed == "B":
            keypressed = None
            result = ''
            for item in phoneNumberBuff[6]:
                if item == ' ':
                    break
                result += str(item)
            try:
                dpm.modify_device_field_by_type(device_type, "ip_address", result)
            except ValueError as e:
                print(f"Error: {e}")
                logger.error(f"Error: {e}")
            except Exception as e:
                print(f"An unexpected error occurred: {e}")
                logger.error(f"Error: {e}")
        menuSubSubSubSubState = menuPositionUpDn(0, MAX_POS)

    # CRED-GATE: challenge display — operator must call Seple to get response
    elif menuSubSubSubSubState == CG_REQ:
        import time as _ct
        if _cred_session_expiry[0] and _ct.time() < _cred_session_expiry[0]:
            # Active session — skip gate and go straight to show
            _cred_show_time[0] = _ct.time()
            menuSubSubSubSubState = DEVICE_PASS
            menuCurrentPos = DEVICE_PASS  # FIX: sync menuCurrentPos so arrows work
            lcd.clear(); lcd.home()
            return
        if not credential_auth.key_is_loaded():
            lcd.clear(); lcd.home()
            lcd.message("Key not set    \n")
            lcd.message("Contact Seple  ")
            menuSubSubSubSubState = DEVICE_PORT
            return
        if credential_auth.is_locked_out():
            secs = credential_auth.time_remaining_locked()
            lcd.clear(); lcd.home()
            lcd.message("Access locked  \n")
            lcd.message(str(secs) + "s remaining    ")
            _cred_challenge[0] = None               # CRED-GATE-FIX: reset so next entry is fresh
            menuSubSubSubSubState = DEVICE_PORT
            return
        if _cred_challenge[0] is None:              # generate once per entry
            _cred_challenge[0] = credential_auth.generate_challenge()
            _cred_resp_digits[0] = ''
        # Display on EVERY tick — keeps LCD showing challenge while operator reads it
        lcd.noCursor()
        lcd.message("Call Seple:    \n")
        lcd.message(str(_cred_challenge[0]) + "            ")
        menuSubSubSubSubState = menuPositionUpDn(CG_REQ, CG_VFY)

    # CRED-GATE: response entry and verification
    elif menuSubSubSubSubState == CG_VFY:
        if credential_auth.is_locked_out():
            secs = credential_auth.time_remaining_locked()
            lcd.clear(); lcd.home()
            lcd.message("Access locked  \n")
            lcd.message(str(secs) + "s remaining    ")
            _cred_challenge[0] = None               # CRED-GATE-FIX: reset so next entry is fresh
            menuSubSubSubSubState = DEVICE_PORT
            return
        lcd.noCursor()
        lcd.message("Enter code:    \n")
        display = _cred_resp_digits[0].ljust(6, '_')
        lcd.message(display + "          ")
        if keypressed and keypressed.isdigit() and len(_cred_resp_digits[0]) < 6:
            _cred_resp_digits[0] += keypressed
            keypressed = None
        elif keypressed == "C":
            _cred_resp_digits[0] = ''
            keypressed = None
        elif keypressed == "B" and len(_cred_resp_digits[0]) == 6:
            keypressed = None
            if credential_auth.verify_response(_cred_challenge[0], _cred_resp_digits[0]):
                import time as _t
                _cred_show_time[0] = _t.time()
                _cred_session_expiry[0] = _t.time() + _CRED_SESSION_SEC
                _cred_challenge[0] = None
                _cred_resp_digits[0] = ''
                menuSubSubSubSubState = DEVICE_PASS
                menuCurrentPos = DEVICE_PASS            # CRED-GATE-FIX: align tracker so next tick stays in DEVICE_PASS
                lcd.clear(); lcd.home()
            else:
                lcd.clear(); lcd.home()
                lcd.message("Access denied  \n")
                lcd.message("Wrong code     ")
                _cred_challenge[0] = None               # CRED-GATE-FIX: reset on wrong code
                menuSubSubSubSubState = DEVICE_PORT
        elif keypressed == "D":
            keypressed = None
            _cred_challenge[0] = None               # CRED-GATE-FIX: reset on cancel
            menuSubSubSubSubState = DEVICE_PORT
            lcd.clear(); lcd.home()

    # DEVICE_PASS — show UDL password; CRED-GATE auto-clears after timeout
    elif menuSubSubSubSubState == DEVICE_PASS:
        if clearKey == 0:
            clearKey = 1
            keyPos = 0
            lcd.clear()
            lcd.home()
        lcd.home()
        lcd.noCursor()
        lcd.message("< Set UDL Pass >")
        lcd.message("\n")
        lcd.message(str(password_ai))
        lcd.message("         ")
        for index in range(0, 16, 1):
            branchNameAddressBuffer[0][index] = ' '
        row_index = 0
        col_index = 0
        for char in password_ai:
            branchNameAddressBuffer[row_index][col_index] = char
            col_index += 1
            if col_index >= 16:
                col_index = 0
                row_index += 1
        # CRED-GATE: auto-clear after SHOW_TIMEOUT_SEC (300 s)
        if credential_auth.show_expired(_cred_show_time[0]):
            _cred_show_time[0] = None
            _cred_challenge[0] = None               # CRED-GATE-FIX: reset after show expires
            lcd.clear(); lcd.home()
            menuSubSubSubSubState = DEVICE_PORT
            menuCurrentPos = DEVICE_PORT  # FIX: sync menuCurrentPos after timeout
            return
        # CRED-GATE-FIX: floor at DEVICE_PASS so ▲ cannot drift back into CG_REQ/CG_VFY
        menuSubSubSubSubState = menuPositionUpDn(DEVICE_PASS, MAX_POS)

    # ADD_DEVICE_PASS
    elif menuSubSubSubSubState == ADD_DEVICE_PASS:
        if clearKey == 1:
            clearKey = 0
            keyPos = 0
            lcd.clear()
            lcd.home()
        keypadScanningMultiKeyWithSmallCaps(15, 0, None)
        lcd.home()
        lcd.message("\n")
        for index in range(0, 16, 1):
            lcd.message(str(branchNameAddressBuffer[0][index]))
        lcd.setCursor(keyPos, 1)
        lcd.cursor()
        menuSubSubSubSubState = menuPositionUpDn(MIN_POS, MAX_POS)

    # REG_DEVICE_PASS
    elif menuSubSubSubSubState == REG_DEVICE_PASS:
        if clearKey == 1:
            clearKey = 0
            lcd.clear()
            lcd.home()
        keypadScanningMultiKey(15, 0, None)
        lcd.home()
        lcd.noCursor()
        lcd.message("< Upd UDL Pass >")
        lcd.message("\n")
        lcd.message("    [Enter]     ")
        if keypressed == "B":
            keypressed = None
            result = ''
            for item in branchNameAddressBuffer[0]:
                if item == ' ':
                    break
                result += str(item)
            try:
                dpm.modify_device_field_by_type(device_type, "password", result)
                print(f"UDL password updated for {device_type}")
            except ValueError as e:
                print(f"Error: {e}")
                logger.error(f"Error: {e}")
            except Exception as e:
                print(f"An unexpected error occurred: {e}")
                logger.error(f"An unexpected error occurred: {e}")
            lcd.clear()
            lcd.home()
        menuSubSubSubSubState = menuPositionUpDn(MIN_POS, MAX_POS)

    # DEVICE_PORT
    elif menuSubSubSubSubState == DEVICE_PORT:
        if clearKey == 0:
            clearKey = 1
            keypadScanning(0, 0, 0, 0, 'clear')
            keyDetect = 0
            lcd.clear()
            lcd.home()
        lcd.home()
        lcd.noCursor()
        keyDetect = keypadScanning(5, 0, 65535, 1)
        lcd.message("< Set Port Num >")
        lcd.message("\n")
        lcd.message("[")
        lcd.message(str(port_ai))
        lcd.message("] ")
        if toggleBit500mSecSec:
            lcd.message(">")
        else:
            lcd.message(" ")
        lcd.message(str(keyDetect))
        lcd.message("   ")
        if keypressed == "B":
            keypressed = None
            try:
                dpm.modify_device_field_by_type(device_type, "port", keyDetect)
                print(f"Port updated for {device_type}")
            except ValueError as e:
                print(f"Error: {e}")
                logger.error(f"Error: {e}")
            except Exception as e:
                print(f"An unexpected error occurred: {e}")
                logger.error(f"An unexpected error occurred: {e}")
            lcd.clear()
        menuSubSubSubSubState = menuPositionUpDn(0, MAX_POS)

    # EXIT
    elif menuSubSubSubSubState == EXIT:
        lcd.home()
        lcd.message("<     EXIT      \n    [ENTER]     ")
        menuSubSubSubSubState = menuPositionUpDn(MIN_POS, MAX_POS)
        if keypressed == "B":
            keypressed = None
            menuSubSubSubSubState = 3
            menuSubSubSubState = 3
            menuCurrentPos = 3
            lcd.clear()
            lcd.home()



def menuSubSubSubStateHIK_BAS_PROG():
    """
    LCD credential programming for Hikvision BAS panel (HikvisionBAS1).
    Mirrors menuSubSubSubStateHIKVISION_NVR_PROG() exactly.
    CRED-GATE protects password display with challenge-response.
    """
    DEVICE_ID, DEVICE_IP, ADD_DEVICE_IP, REG_DEVICE_IP, \
    DEVICE_NAME, ADD_DEVICE_NAME, REG_DEVICE_NAME, \
    CG_REQ, CG_VFY, \
    DEVICE_PASS, ADD_DEVICE_PASS, REG_DEVICE_PASS, \
    DEVICE_PORT, EXIT = range(14)  # CRED-GATE

    MAX_POS = EXIT
    MIN_POS = DEVICE_ID

    global menuSubSubSubSubState
    global menuSubSubSubState
    global branchNameAddressBuffer
    global keypressed
    global clearKey
    global toggleBit500mSecSec
    global keyPos
    global rtcProgSetMenu
    global menuMainState
    global menuCurrentPos
    global keyDetect
    global GuserSetState
    global menuSubState
    global GmainStateState
    global menuSubState
    global index
    global sub_index
    global menuMainState
    global menuSubSubState
    global phoneNumberBuff
    global value1
    global progPass
    global isPasswordMatched
    global beepOn1Sec
    global repeatCounter
    global multikey_Dic
    global keyInputMultiMode
    global branchNameAddress
    global keyPos
    global device_id_ai
    global device_type_ai
    global ip_address_ai
    global username_ai
    global password_ai
    global port_ai

    device_type = "HikvisionBAS1"

    devices = dpm.get_device_parameters(device_type)
    for device in devices:
        device_id_ai   = device['id']
        device_type_ai = device['device_type']
        ip_address_ai  = device['ip_address']
        username_ai    = device['username']
        password_ai    = device['password']
        port_ai        = device['port']

    # DEVICE_ID
    if menuSubSubSubSubState == DEVICE_ID:
        keyDetect = keypadScanning(2, 0, 99, 0)
        if clearKey == 0:
            clearKey = 1
            keypadScanning(0, 0, 0, 0, 'clear')
            keyDetect = 0
            lcd.clear()
            lcd.home()
        lcd.noCursor()
        lcd.home()
        lcd.message(str(device_type_ai))
        lcd.message("       ")
        lcd.message("\n")
        lcd.message("ID No: [")
        try:
            lcd.message(str(device_id_ai))
        except (ValueError, IOError):
            lcd.message(str(0))
        lcd.message("]       ")
        lcd.message(str(keyDetect))
        if keypressed == "B":
            keypressed = None
            keypadScanning(0, 0, 0, 0, 'clear')
            lcd.clear()
            lcd.home()
        menuSubSubSubSubState = menuPositionUpDn(MIN_POS, MAX_POS)

    # DEVICE_IP
    elif menuSubSubSubSubState == DEVICE_IP:
        if clearKey == 1:
            clearKey = 0
            keypadScanning(0, 0, 0, 0, 'clear')
            keyDetect = 0
            keyPos = 0
            lcd.clear()
            lcd.home()
        lcd.noCursor()
        lcd.message("< Set  IP Addr >")
        lcd.message("\n")
        lcd.message(str(ip_address_ai))
        lcd.message("       ")
        row_index = 0
        col_index = 0
        for char in ip_address_ai:
            phoneNumberBuff[row_index][col_index] = char
            col_index += 1
            if col_index >= 16:
                col_index = 0
                row_index += 1
        menuSubSubSubSubState = menuPositionUpDn(MIN_POS, MAX_POS)

    # ADD_DEVICE_IP
    elif menuSubSubSubSubState == ADD_DEVICE_IP:
        if clearKey == 0:
            clearKey = 1
            keypadScanning(0, 0, 0, 0, 'clear')
            keyDetect = 0
            keyPos = 0
            for index in range(0, 14, 1):
                phoneNumberBuff[6][index] = ' '
            lcd.clear()
            lcd.home()
        keypadScanningMultiNumKeyWithDot(14, 6, None)
        lcd.home()
        lcd.message("\n")
        for index in range(0, 14, 1):
            lcd.message(str(phoneNumberBuff[6][index]))
        lcd.setCursor(keyPos, 1)
        lcd.cursor()
        menuSubSubSubSubState = menuPositionUpDn(MIN_POS, MAX_POS)

    # REG_DEVICE_IP
    elif menuSubSubSubSubState == REG_DEVICE_IP:
        if clearKey == 1:
            clearKey = 0
            keypadScanning(0, 0, 0, 0, 'clear')
            keyDetect = 0
            keyPos = 0
            lcd.clear()
            lcd.home()
        lcd.home()
        lcd.noCursor()
        lcd.message("< Upd  IP Addr >")
        lcd.message("\n")
        lcd.message("    [Enter]     ")
        if keypressed == "B":
            keypressed = None
            result = ''
            for item in phoneNumberBuff[6]:
                if item == ' ':
                    break
                result += str(item)
            try:
                dpm.modify_device_field_by_type(device_type, "ip_address", result)
            except Exception as e:
                logger.error("[HIK-BAS-PROG] IP update error: %s", e)
        menuSubSubSubSubState = menuPositionUpDn(MIN_POS, MAX_POS)

    # DEVICE NAME
    elif menuSubSubSubSubState == DEVICE_NAME:
        if clearKey == 1:
            clearKey = 0
            keyPos = 0
            lcd.clear()
            lcd.home()
        lcd.home()
        lcd.noCursor()
        lcd.message("< Set Dev Name >")
        lcd.message("\n")
        lcd.message(str(username_ai))
        lcd.message("          ")

        for index in range(0, 16, 1):
            branchNameAddressBuffer[0][index] = ' '

        row_index = 0
        col_index = 0
        for char in username_ai:
            branchNameAddressBuffer[row_index][col_index] = char
            col_index += 1
            if col_index >= 16:
                col_index = 0
                row_index += 1

        menuSubSubSubSubState = menuPositionUpDn(MIN_POS, MAX_POS)

    # ADD DEVICE NAME
    elif menuSubSubSubSubState == ADD_DEVICE_NAME:
        if clearKey == 1:
            clearKey = 0
            keyPos = 0
            lcd.clear()
            lcd.home()
        keypadScanningMultiKeyWithSmallCaps(15, 0, None)
        lcd.home()
        lcd.message("\n")
        for index in range(0, 16, 1):
            lcd.message(str(branchNameAddressBuffer[0][index]))
        lcd.setCursor(keyPos, 1)
        lcd.cursor()
        menuSubSubSubSubState = menuPositionUpDn(MIN_POS, MAX_POS)

    # REG DEVICE NAME
    elif menuSubSubSubSubState == REG_DEVICE_NAME:
        if clearKey == 0:
            clearKey = 1
            keyPos = 0
            lcd.clear()
            lcd.home()
        lcd.home()
        lcd.noCursor()
        lcd.message("< Upd Dev Name >")
        lcd.message("\n")
        lcd.message("    [Enter]     ")
        if keypressed == "B":
            keypressed = None
            result = ''
            for item in branchNameAddressBuffer[0]:
                if item == ' ':
                    break
                result += str(item)
            try:
                dpm.modify_device_field_by_type(device_type, "username", result)
            except ValueError as e:
                logger.error("[HIK-BAS-PROG] Username update ValueError: %s", e)
            except Exception as e:
                logger.error("[HIK-BAS-PROG] Username update error: %s", e)
            lcd.clear()
            lcd.home()
        menuSubSubSubSubState = menuPositionUpDn(MIN_POS, MAX_POS)

    # CRED-GATE: show challenge number — operator calls Seple for response
    elif menuSubSubSubSubState == CG_REQ:
        import time as _ct
        if _cred_session_expiry[0] and _ct.time() < _cred_session_expiry[0]:
            _cred_show_time[0] = _ct.time()
            menuSubSubSubSubState = DEVICE_PASS
            menuCurrentPos = DEVICE_PASS
            lcd.clear(); lcd.home()
            return
        if not credential_auth.key_is_loaded():
            lcd.clear(); lcd.home()
            lcd.message("Key not set    \n")
            lcd.message("Contact Seple  ")
            menuSubSubSubSubState = DEVICE_PORT
            return
        if credential_auth.is_locked_out():
            secs = credential_auth.time_remaining_locked()
            lcd.clear(); lcd.home()
            lcd.message("Access locked  \n")
            lcd.message(str(secs) + "s remaining    ")
            _cred_challenge[0] = None
            menuSubSubSubSubState = DEVICE_PORT
            return
        if _cred_challenge[0] is None:
            _cred_challenge[0] = credential_auth.generate_challenge()
            _cred_resp_digits[0] = ''
        lcd.noCursor()
        lcd.message("Call Seple:    \n")
        lcd.message(str(_cred_challenge[0]) + "            ")
        menuSubSubSubSubState = menuPositionUpDn(CG_REQ, CG_VFY)

    # CRED-GATE: enter 6-digit response code
    elif menuSubSubSubSubState == CG_VFY:
        if credential_auth.is_locked_out():
            secs = credential_auth.time_remaining_locked()
            lcd.clear(); lcd.home()
            lcd.message("Access locked  \n")
            lcd.message(str(secs) + "s remaining    ")
            _cred_challenge[0] = None
            menuSubSubSubSubState = DEVICE_PORT
            return
        lcd.noCursor()
        lcd.message("Enter code:    \n")
        display = _cred_resp_digits[0].ljust(6, '_')
        lcd.message(display + "          ")
        if keypressed and keypressed.isdigit() and len(_cred_resp_digits[0]) < 6:
            _cred_resp_digits[0] += keypressed
            keypressed = None
        elif keypressed == "C":
            _cred_resp_digits[0] = ''
            keypressed = None
        elif keypressed == "B" and len(_cred_resp_digits[0]) == 6:
            keypressed = None
            if credential_auth.verify_response(_cred_challenge[0], _cred_resp_digits[0]):
                import time as _t
                _cred_show_time[0] = _t.time()
                _cred_session_expiry[0] = _t.time() + _CRED_SESSION_SEC
                _cred_challenge[0] = None
                _cred_resp_digits[0] = ''
                menuSubSubSubSubState = DEVICE_PASS
                menuCurrentPos = DEVICE_PASS
                lcd.clear(); lcd.home()
            else:
                lcd.clear(); lcd.home()
                lcd.message("Access denied  \n")
                lcd.message("Wrong code     ")
                _cred_challenge[0] = None
                menuSubSubSubSubState = DEVICE_PORT
        elif keypressed == "D":
            keypressed = None
            _cred_challenge[0] = None
            menuSubSubSubSubState = DEVICE_PORT
            lcd.clear(); lcd.home()

    # DEVICE_PASS (show current password — CRED-GATE protected)
    elif menuSubSubSubSubState == DEVICE_PASS:
        if clearKey == 0:
            clearKey = 1
            keyPos = 0
            lcd.clear()
            lcd.home()
        lcd.home()
        lcd.noCursor()
        lcd.message("< Set Dev Pass >")
        lcd.message("\n")
        lcd.message(str(password_ai))
        lcd.message("         ")
        for index in range(0, 16, 1):
            branchNameAddressBuffer[0][index] = ' '
        row_index = 0
        col_index = 0
        for char in password_ai:
            branchNameAddressBuffer[row_index][col_index] = char
            col_index += 1
            if col_index >= 16:
                col_index = 0
                row_index += 1
        if credential_auth.show_expired(_cred_show_time[0]):
            _cred_show_time[0] = None
            _cred_challenge[0] = None
            lcd.clear(); lcd.home()
            menuSubSubSubSubState = DEVICE_PORT
            menuCurrentPos = DEVICE_PORT
            return
        menuSubSubSubSubState = menuPositionUpDn(MIN_POS, MAX_POS)

    # ADD_DEVICE_PASS
    elif menuSubSubSubSubState == ADD_DEVICE_PASS:
        if clearKey == 1:
            clearKey = 0
            keypadScanning(0, 0, 0, 0, 'clear')
            keyDetect = 0
            keyPos = 0
            lcd.clear()
            lcd.home()
        keypadScanningMultiKeyWithSmallCaps(15, 0, None)
        lcd.home()
        lcd.message("\n")
        for index in range(0, 15, 1):
            lcd.message(str(branchNameAddressBuffer[0][index]))
        lcd.setCursor(keyPos, 1)
        lcd.cursor()
        menuSubSubSubSubState = menuPositionUpDn(MIN_POS, MAX_POS)

    # REG_DEVICE_PASS
    elif menuSubSubSubSubState == REG_DEVICE_PASS:
        if clearKey == 1:
            clearKey = 0
            keypadScanning(0, 0, 0, 0, 'clear')
            keyDetect = 0
            keyPos = 0
            lcd.clear()
            lcd.home()
        lcd.home(); lcd.noCursor()
        lcd.message("< Upd Dev Pass >")
        lcd.message("\n")
        lcd.message("    [Enter]     ")
        if keypressed == "B":
            keypressed = None
            result = ''
            for item in branchNameAddressBuffer[0]:
                if item == ' ':
                    break
                result += str(item)
            try:
                dpm.modify_device_field_by_type(device_type, "password", result)
                _cred_show_time[0] = None
            except Exception as e:
                logger.error("[HIK-BAS-PROG] Password update error: %s", e)
        menuSubSubSubSubState = menuPositionUpDn(MIN_POS, MAX_POS)

    # DEVICE PORT
    elif menuSubSubSubSubState == DEVICE_PORT:
        if clearKey == 0:
            clearKey = 1
            keypadScanning(0, 0, 0, 0, 'clear')
            keyDetect = 0
            lcd.clear()
            lcd.home()
        lcd.home()
        lcd.noCursor()
        keyDetect = keypadScanning(5, 0, 65535, 1)
        lcd.message("< Set Port Num >")
        lcd.message("\n")
        lcd.message("[")
        lcd.message(str(port_ai))
        lcd.message("] ")
        if toggleBit500mSecSec:
            lcd.message(">")
        else:
            lcd.message(" ")
        lcd.message(str(keyDetect))
        lcd.message("   ")
        if keypressed == "B":
            keypressed = None
            try:
                dpm.modify_device_field_by_type(device_type, "port", keyDetect)
            except ValueError as e:
                logger.error("[HIK-BAS-PROG] Port update ValueError: %s", e)
            except Exception as e:
                logger.error("[HIK-BAS-PROG] Port update error: %s", e)
            lcd.clear()
        menuSubSubSubSubState = menuPositionUpDn(0, MAX_POS)

    # EXIT
    elif menuSubSubSubSubState == EXIT:
        if clearKey == 1:
            clearKey = 0
            keypadScanning(0, 0, 0, 0, 'clear')
            lcd.clear()
            lcd.home()
        lcd.home(); lcd.noCursor()
        lcd.message("<     EXIT      ")
        lcd.message("\n")
        lcd.message("    [ENTER]     ")
        if keypressed == "B":
            keypressed = None
            menuSubSubSubSubState = 0
            menuCurrentPos = 0
            menuSubSubSubState = 5   # HIK_BAS position in menuList
            lcd.clear(); lcd.home()
        menuSubSubSubSubState = menuPositionUpDn(MIN_POS, MAX_POS)

def menuSubSubStateDEVICE_MANAGEMENT_PROG():
    
    global menuSubState
    global index
    global sub_index
    global GmainStateState
    global menuCurrentPos
    global GuserSetState
    global keypressed
    global menuMainState
    global menuSubSubState

    if menuSubSubState == 0:        
        lcd.home()
        lcd.message("  ADD  DEVICE  >")
        lcd.message("\n")
        lcd.message("                ")
        if keypressed == "B":
            keypressed = None
        menuSubSubState = menuPositionUpDn(0,2)

    if menuSubSubState == 1:        
        lcd.home()
        lcd.message("<  EDIT DEVICE >")
        lcd.message("\n")
        lcd.message("                ")
        if keypressed == "B":
            keypressed = None
        menuSubSubState = menuPositionUpDn(0,2)
        
    if menuSubSubState == 2:        
        lcd.home()
        lcd.message("<     EXIT      ")
        lcd.message("\n")
        lcd.message("    [ENTER]     ")
        menuSubSubState = menuPositionUpDn(0,2)
        if keypressed == "B":
            keypressed = None
            menuCurrentPos = 1
            menuSubState = 1
            lcd.clear()
            lcd.home()


def menuSubSubStateADVANCE_SETTINGS_PROG():
    
    global menuSubState
    global index
    global sub_index
    global GmainStateState
    global menuCurrentPos
    global GuserSetState
    global keypressed
    global menuMainState
    global menuSubSubState


    if menuSubSubState == 0:        
        
        setup_mode_value = system_settings_db.retrieve_element("setup_mode")
        
        if setup_mode_value == "enabled":
            lcd.home()
            lcd.message("<  SETUP MODE  >\n   [Enabled]   ")
            if keypressed == "B":                       
                keypressed = None
                system_settings_db.update_element("setup_mode", "disabled")
                
        elif setup_mode_value == "disabled":
            lcd.home()
            lcd.message("<  SETUP MODE  >\n   [Disabled]  ")
            if keypressed == "B":                       
                keypressed = None
                system_settings_db.update_element("setup_mode", "enabled")
                
        menuSubSubState = menuPositionUpDn(0,2)

    if menuSubSubState == 1:        

        reset_to_default_value = system_settings_db.retrieve_element("reset_to_default")
        
        if reset_to_default_value == "true":
            lcd.home()
            lcd.message("<RESET  DEFAULT>\n     [true]    ")
            if keypressed == "B":                       
                keypressed = None
                system_settings_db.update_element("reset_to_default", "false")
                
        elif reset_to_default_value == "false":
            lcd.home()
            lcd.message("<RESET  DEFAULT>\n     [ENTER]   ")
            if keypressed == "B":                       
                keypressed = None
                system_settings_db.update_element("reset_to_default", "true")
                rebootPanel()
            
        menuSubSubState = menuPositionUpDn(0,2)
                
    if menuSubSubState == 2:        
        lcd.home()
        lcd.message("<     EXIT      ")
        lcd.message("\n")
        lcd.message("    [ENTER]     ")
        menuSubSubState = menuPositionUpDn(0,2)
        if keypressed == "B":
            keypressed = None
            menuCurrentPos = 2
            menuSubState = 2
            lcd.clear()
            lcd.home()


def rebootPanel():

    global shiftRegister1Buffers
    global shiftRegister2Buffers
    global shiftRegister3Buffers
    global shiftRegister4Buffers
    global _reboot_in_progress

    if _reboot_in_progress:
        return
    _reboot_in_progress = True

    lcd.home()
    lcd.message("     System     \n  Rebooting...  ")

    # Clear all relay outputs (de-energize) — one write is sufficient
    shiftRegister1Buffers |= shiftRegSet['CLEAR']
    shiftRegister2Buffers |= shiftRegSet['CLEAR']
    shiftRegister3Buffers |= shiftRegSet['CLEAR']
    shiftRegister4Buffers |= shiftRegSet['CLEAR']
    sr.ssrWrite_4( shiftRegister4Buffers, shiftRegister3Buffers, shiftRegister2Buffers, shiftRegister1Buffers )

    time.sleep(3.0)

    # Do NOT call GPIO.cleanup() here — it resets GPIO lines and blanks the LCD
    # before the actual reboot, making the user see two apparent reboots.
    # The Pi reboot handles GPIO cleanup on its own.
    subprocess.call(["nsenter", "-t", "1", "-m", "-u", "-i", "-n", "-p", "--", "/sbin/reboot"])


def shutdownPanel():

    global shiftRegister1Buffers
    global shiftRegister2Buffers
    global shiftRegister3Buffers
    global shiftRegister4Buffers    
    
    lcd.home()
    lcd.message("     System     \n  Shutdown...  ")
    
   # time.sleep(30.0)
    
    shift_registers = [shiftRegister1Buffers, shiftRegister2Buffers, shiftRegister3Buffers, shiftRegister4Buffers]
    clear_value = shiftRegSet['CLEAR']

    for reg in shift_registers:
        reg |= clear_value

    shiftRegister1Buffers |= shiftRegSet['CLEAR']
    shiftRegister2Buffers |= shiftRegSet['CLEAR']
    shiftRegister3Buffers |= shiftRegSet['CLEAR']
    shiftRegister4Buffers |= shiftRegSet['CLEAR']
    
    sr.ssrWrite_4( shiftRegister4Buffers, shiftRegister3Buffers, shiftRegister2Buffers, shiftRegister1Buffers )        

    time.sleep(30.0)
    
    shiftRegister1Buffers |= shiftRegSet['CLEAR']
    shiftRegister2Buffers |= shiftRegSet['CLEAR']
    shiftRegister3Buffers |= shiftRegSet['CLEAR']
    shiftRegister4Buffers |= shiftRegSet['CLEAR']
    
    sr.ssrWrite_4( shiftRegister4Buffers, shiftRegister3Buffers, shiftRegister2Buffers, shiftRegister1Buffers )

    time.sleep(30.0)

    GPIO.cleanup()
    call("sudo shutdown -h now", shell=True)


def checkLithiumIonBatteryVoltage(input_voltage):
    if input_voltage == 1.0:
        shutdownPanel()
        return 1
    elif input_voltage == 0.0:
        # Do nothing
        return 0
    else:
        # For any other value, just return 0
        return 0

#---------------------------- -------------------------------- ------------------------------
# NETWORK_COMMUNICATION_SETTINGS_PROG
# -------------------------------------------------------------------------------------------
def progStateMachineSubSubStateNETWORK_COMMUNICATION_SETTINGS_PROG():

    global menuMainState
    global keypressed
    global GmainStateState
    global menuCurrentPos
    global GuserSetState 
    global index
    global menuSubState
    global menuCodeSelectState
    global menuSubPasswordState
    global clearKey
    global isMemoryCleared
    global toggleBit500mSecSec
    global isPasswordReseted
    global isLogCleared
    global menuSubSubState
                
    menuList = {'eSIM_SETTINGS':0,
                'GNSS_SETTINGS':1,
                'DEVICE_CREDENTIAL_SETUP': 2,
                'LAN_SETUP': 3,
                'GSM_SETTINGS': 4,                                
                'EXIT':5,
                'eSIM_SETTINGS_ZONE_PROG':6,
                'GNSS_SETTINGS_PROG':7,
                'DEVICE_CREDENTIAL_SETUP_PROG':8,
                'LAN_SETUP_PROG':9,
                'GSM_SETTINGS_PROG':10}

    MENU_MAX = 5
    MENU_MIN = 0
    
    if menuSubState == menuList['eSIM_SETTINGS']:                                   
        lcd.message("      eSIM     >\n    SETTINGS    ")
        menuSubState = menuPositionUpDnWithoutClear(MENU_MIN, MENU_MAX)
        menuMainStateHist = 0
        if keypressed == "B":           
            keypressed = None
            menuSubState = menuList['eSIM_SETTINGS_ZONE_PROG']
            rtcProgSetMenu = 0
            menuCurrentPos = 0
            menuSubSubState = 0
            lcd.clear()
            lcd.home()
            clearKey = 0
            keypadScanning(0,0,0,0,'clear')


    elif menuSubState == menuList['GNSS_SETTINGS']:                                 
        lcd.message("<     GNSS     >\n     SETTINGS   ")
        menuSubState = menuPositionUpDnWithoutClear(MENU_MIN, MENU_MAX)
        if keypressed == "B":           
            keypressed = None
            menuSubState = menuList['GNSS_SETTINGS_PROG']
            rtcProgSetMenu = 0
            menuCurrentPos = 0
            menuSubSubState = 0
            index = 0            
            lcd.clear()
            lcd.home()
            clearKey = 0
            keypadScanning(0,0,0,0,'clear')


    elif menuSubState == menuList['DEVICE_CREDENTIAL_SETUP']:        
        lcd.message("<    DEVICE    >\n   CREDENTIAL   ")        
        menuSubState = menuPositionUpDnWithoutClear(MENU_MIN, MENU_MAX)
        if keypressed == "B":           
            keypressed = None
            menuSubState = menuList['DEVICE_CREDENTIAL_SETUP_PROG']
            rtcProgSetMenu = 0
            menuCurrentPos = 0
            menuSubSubState = 0
            index = 0            
            lcd.clear()
            lcd.home()
            clearKey = 0
            keypadScanning(0,0,0,0,'clear')


    elif menuSubState == menuList['LAN_SETUP']:
        lcd.message("<      LAN     >\n      SETUP     ")
        menuSubState = menuPositionUpDnWithoutClear(MENU_MIN, MENU_MAX)
        if keypressed == "B":           
            keypressed = None
            menuSubState = menuList['LAN_SETUP_PROG']
            rtcProgSetMenu = 0
            menuCurrentPos = 0
            index = 0
            menuSubSubState = 0
            lcd.clear()
            lcd.home()
            clearKey = 0
            keypadScanning(0,0,0,0,'clear')

    elif menuSubState == menuList['GSM_SETTINGS']:                                 
        lcd.message("<     GSM      >\n    SETTINGS    ")        
        menuSubState = menuPositionUpDnWithoutClear(MENU_MIN, MENU_MAX)
        if keypressed == "B":           
            keypressed = None
            menuSubState = menuList['GSM_SETTINGS_PROG']
            rtcProgSetMenu = 0
            menuCurrentPos = 0
            zoneProgSetMenu = 0
            menuSubSubState = 0
            index = 0            
            lcd.clear()
            lcd.home()
            clearKey = 0
            keypadScanning(0,0,0,0,'clear')

        
    elif menuSubState == menuList['EXIT']:                                               
        lcd.message("<     EXIT      \n    [ENTER]     ")
        menuSubState = menuPositionUpDnWithoutClear(MENU_MIN, MENU_MAX)
        if keypressed == "B":
            keypressed = "CLEAR"
            menuCurrentPos = 2
            menuMainState = 2
            menuSubState = 0
            lcd.clear()
            lcd.home()
            keypadScanning(0,0,0,0,'clear')

    elif menuSubState == menuList['eSIM_SETTINGS_ZONE_PROG']:                    
        eSIMSettingseSIM_SETTINGS_ZONE_PROG()

    elif menuSubState == menuList['GNSS_SETTINGS_PROG']:                    
        GNSSSettingsGNSS_SETTINGS_PROG()
        
    elif menuSubState == menuList['DEVICE_CREDENTIAL_SETUP_PROG']:                    
        menuSubSubStateDEVICE_CREDENTIAL_SETUP_PROG()

    elif menuSubState == menuList['LAN_SETUP_PROG']:                    
        networkSettings()

    elif menuSubState == menuList['GSM_SETTINGS_PROG']:                    
       GSMSettingsGSM_SETTINGS_PROG()


def progRTCsettings():
    global rtcProgSetMenu
    global menuMainState
    global menuCurrentPos
    global keypressed
    global keyDetect
    global GuserSetState
    global menuSubState
    global menuSubSubState
    global GmainStateState
    global clearKey
    global toggleBit500mSecSec

    if rtcProgSetMenu == 0:
        keyDetect = keypadScanning(2,1,31,1)
        if clearKey == 0:
            clearKey = 1
            keypadScanning(0,0,0,0,'clear')
            keyDetect = 0
            lcd.clear()
            lcd.home()
            
        lcd.home()
        lcd.message("  Day  [1-31]  >")
        lcd.message("\n")
        lcd.message("    [")
        try:
            lcd.message(str(ds1307._read_date()))
        except ValueError:
            lcd.message(str(0))
        except IOError:
            lcd.message(str(0))
        lcd.message("]   ")    
        rtcSecound = 0
        if toggleBit500mSecSec:
            lcd.message(">")
        else:
            lcd.message(" ") 
        lcd.message(str(keyDetect))
        if keypressed == "B":
            keypressed = None
            try:
                ds1307.write_all(seconds=None, minutes=None, hours=None, day=None, date=keyDetect, month=None, year=None, save_as_24h=True)
                ds1307.write_now()
            except ValueError:
                print(" RTC Error ")
                logger.error(" RTC Error ")
            except IOError:
                print(" RTC Error ")
                logger.error(" RTC Error ")
            keypadScanning(0,0,0,0,'clear')
            lcd.clear()
            lcd.home()                
        rtcProgSetMenu = menuPositionUpDn(0, 5)
        
    elif rtcProgSetMenu == 1:
        keyDetect = keypadScanning(2,1,12,1)
        if clearKey == 1:
            clearKey = 0
            keypadScanning(0,0,0,0,'clear')
            keyDetect = 0
            lcd.clear()
            lcd.home()
            
        lcd.home()
        lcd.message("< Month [1-12] >")        
        lcd.message("\n")
        lcd.message("    [")
        try:
            lcd.message(str(ds1307._read_month()))
        except ValueError:
            lcd.message(str(0))
        except IOError:
            lcd.message(str(0))
        lcd.message("]    ")            
        if toggleBit500mSecSec:
            lcd.message(">")
        else:
            lcd.message(" ")
        lcd.message(str(keyDetect))
        if keypressed == "B":
            keypressed = None
            try:
                ds1307.write_all(seconds=None, minutes=None, hours=None, day=None, date=None, month=keyDetect, year=None, save_as_24h=True)
                ds1307.write_now()
            except ValueError:
                print(" RTC Error ")
                logger.error(" RTC Error ")
            except IOError:
                print(" RTC Error ")
                logger.error(" RTC Error ")
            keypadScanning(0,0,0,0,'clear')
            lcd.clear()
            lcd.home()                
        rtcProgSetMenu = menuPositionUpDn(0, 5)
        
    elif rtcProgSetMenu == 2:
        keyDetect = keypadScanning(2,0,99,0)
        if clearKey == 0:
            clearKey = 1
            keypadScanning(0,0,0,0,'clear')
            keyDetect = 0
            lcd.clear()
            lcd.home()
            
        lcd.home()
        lcd.message("< Year  [0-99] >")                
        lcd.message("\n")
        lcd.message("    [")        
        try:
            lcd.message(str(ds1307._read_year()))
        except ValueError:
            lcd.message(str(0))
        except IOError:
            lcd.message(str(0))
        lcd.message("]    ")            
        if toggleBit500mSecSec:
            lcd.message(">")
        else:
            lcd.message(" ")
        lcd.message(str(keyDetect))
        if keypressed == "B":
            keypressed = None
            try:
                ds1307.write_all(seconds=None, minutes=None, hours=None, day=None, date=None, month=None, year=keyDetect, save_as_24h=True)
                ds1307.write_now()
            except ValueError:
                print(" RTC Error ")
                logger.error(" RTC Error ")
            except IOError:
                print(" RTC Error ")
                logger.error(" RTC Error ")
            keypadScanning(0,0,0,0,'clear')
            lcd.clear()
            lcd.home()                
        rtcProgSetMenu = menuPositionUpDn(0, 5)
        
    elif rtcProgSetMenu == 3:
        keyDetect = keypadScanning(2,0,23,0)
        if clearKey == 1:
            clearKey = 0
            keypadScanning(0,0,0,0,'clear')
            keyDetect = 0
            lcd.clear()
            lcd.home()
            
        lcd.home()
        lcd.message("<  Hour [0-23] >")                
        lcd.message("\n")
        lcd.message("    [")                
        try:
            lcd.message(str(ds1307._read_hours()))
        except ValueError:
            lcd.message(str(0))
        except IOError:
            lcd.message(str(0))
        lcd.message("]    ")                    
        if toggleBit500mSecSec:
            lcd.message(">")
        else:
            lcd.message(" ")
        lcd.message(str(keyDetect))
        if keypressed == "B":
            keypressed = None
            try:
                ds1307.write_all(seconds=None, minutes=None, hours=keyDetect, day=None, date=None, month=None, year=None, save_as_24h=True)
                ds1307.write_now()
            except ValueError:
                print(" RTC Error ")
                logger.error(" RTC Error ")
            except IOError:
                print(" RTC Error ")
                logger.error(" RTC Error ")
            keypadScanning(0,0,0,0,'clear')
            lcd.clear()
            lcd.home()                
        rtcProgSetMenu = menuPositionUpDn(0, 5)
        
    elif rtcProgSetMenu == 4:
        keyDetect = keypadScanning(2,0,59,0)
        if clearKey == 0:
            clearKey = 1
            keypadScanning(0,0,0,0,'clear')
            keyDetect = 0
            lcd.clear()
            lcd.home()
            
        lcd.home()
        lcd.message("< Minute [0-59]>")                
        lcd.message("\n")
        lcd.message("    [")                        
        try:
            lcd.message(str(ds1307._read_minutes()))
        except ValueError:
            lcd.message(str(0))
        except IOError:
            lcd.message(str(0))
        lcd.message("]    ")                            
        if toggleBit500mSecSec:
            lcd.message(">")
        else:
            lcd.message(" ")
        lcd.message(str(keyDetect))
        if keypressed == "B":
            keypressed = None
            try:
                ds1307.write_all(seconds=None, minutes=keyDetect, hours=None, day=None, date=None, month=None, year=None, save_as_24h=True)
                ds1307.write_now()
            except ValueError:
                print(" RTC Error ")
                logger.error(" RTC Error ")
            except IOError:
                print(" RTC Error ")
                logger.error(" RTC Error ")
            keypadScanning(0,0,0,0,'clear')
            lcd.clear()
            lcd.home()                
        rtcProgSetMenu = menuPositionUpDn(0, 5)
        
    elif rtcProgSetMenu == 5:
        lcd.home()
        lcd.message("<     EXIT      ")
        lcd.message("\n")
        lcd.message("    [ENTER]     ")
        rtcProgSetMenu = menuPositionUpDn(0, 5)
        if keypressed == "B":
            keypressed = None
            global menuCodeSelectState
            rtcProgSetMenu = 0
            menuSubSubState = 0
            menuCurrentPos = 0
            keypadScanning(0,0,0,0,'clear')            
            lcd.clear()
            lcd.home()


def adminPassword():

    MASTER_1_PASS_CHECK, MASTER_1_PASS_CHANGE, SERVICE_1_PASS_CHECK, SERVICE_1_PASS_CHANGE, EXIT = range(5)
    
    MAX_POS = EXIT
    MIN_POS = MASTER_1_PASS_CHECK

    MAX_RANGE = 99999999

    global keypressed
    global value1
    global GmainStateState
    global menuCurrentPos
    global GuserSetState
    global menuSubState
    global menuSubSubState
    global adminPass
    global servicePass
    global menuMainState
    global toggleBit500mSecSec
    global beepOn1Sec
    global isPasswordMatched
    global menuSubSubSubState

    if menuSubSubSubState == MASTER_1_PASS_CHECK:        # 0
        lcd.home()
        lcd.message("< Set Password >")
        lcd.message("\n")
        lcd.message("      User      ")
        keypadScanning(0,0,0,0,'clear')
        isPasswordMatched = 0
        menuSubSubSubState = menuPositionUpDn(MIN_POS,MAX_POS)
        
    if menuSubSubSubState == MASTER_1_PASS_CHANGE:        # 0
        keyDetect = keypadScanning(8,0,99999999,0)
        adminPasswordFileRW('read')
        lcd.home()
        if isPasswordMatched == 0:
            lcd.message("< Old Password >")
        elif isPasswordMatched == 1:
            lcd.message("< New Password >")            
        lcd.message("\n")
        if toggleBit500mSecSec:
            lcd.message("    >")
        else:
            lcd.message("     ")
        keyDetect2Asterisk = numeric2Asterisk(keyDetect)
        lcd.message(str(keyDetect2Asterisk))                            
        if keypressed == "B":
            keypressed = None
            if isPasswordMatched == 0:
                if keyDetect == adminPass[1]:
                    isPasswordMatched = 1
            elif isPasswordMatched == 1:                
                if keyDetect > 9 and keyDetect <= MAX_RANGE: 
                    adminPass[1] = int(keyDetect) 
                    adminPasswordFileRW('write')
                    beepOn1Sec = 1
                    isPasswordMatched = 0
            keypadScanning(0,0,0,0,'clear')                    
            lcd.clear()
            lcd.home()
        menuSubSubSubState = menuPositionUpDn(MIN_POS,MAX_POS)

    if menuSubSubSubState == SERVICE_1_PASS_CHECK:        # 0
        lcd.home()
        lcd.message("< Set Password >")
        lcd.message("\n")
        lcd.message("     Service    ")
        keypadScanning(0,0,0,0,'clear')
        isPasswordMatched = 0
        menuSubSubSubState = menuPositionUpDn(MIN_POS,MAX_POS)
        
    if menuSubSubSubState == SERVICE_1_PASS_CHANGE:        # 0
        keyDetect = keypadScanning(8,0,99999999,0)
        servicePasswordFileRW('read')
        lcd.home()
        if isPasswordMatched == 0:
            lcd.message("< Old Password >")
        elif isPasswordMatched == 1:
            lcd.message("< New Password >")            
        lcd.message("\n")
        if toggleBit500mSecSec:
            lcd.message("    >")
        else:
            lcd.message("     ")
        keyDetect2Asterisk = numeric2Asterisk(keyDetect)
        lcd.message(str(keyDetect2Asterisk))              
        if keypressed == "B":
            keypressed = None
            if isPasswordMatched == 0:
                if keyDetect == servicePass[1]:
                    isPasswordMatched = 1
            elif isPasswordMatched == 1:                
                if keyDetect > 9 and keyDetect <= MAX_RANGE: 
                    servicePass[1] = int(keyDetect) 
                    servicePasswordFileRW('write')
                    beepOn1Sec = 1
                    isPasswordMatched = 0
            keypadScanning(0,0,0,0,'clear')                    
            lcd.clear()
            lcd.home()
        menuSubSubSubState = menuPositionUpDn(MIN_POS,MAX_POS)
            
    if menuSubSubSubState == EXIT:        # 1
        lcd.home()
        lcd.message("<     EXIT      ")
        lcd.message("\n")
        lcd.message("    [ENTER]     ")
        isPasswordMatched = 0
        menuSubSubSubState = menuPositionUpDn(MIN_POS,MAX_POS)
        if keypressed == "B":
            keypressed = None
            global menuCodeSelectState 
            menuSubSubState = 1
            menuCurrentPos = 1
            menuSubSubSubState = 0
            keypadScanning(0,0,0,0,'clear')                    
            lcd.clear()
            lcd.home()


def SubMenuBranchAddress():
  
  BRANCH_NAME, ADD_BRANCH_NAME, REG_BRANCH_NAME, EXIT, RETURN = range(5)            
  MAX_POS = EXIT
  MIN_POS = BRANCH_NAME
  
  global keypressed
  global GmainStateState
  global menuCurrentPos
  global GuserSetState
  global menuSubState
  global menuSubSubState
  global menuMainState

  global toggleBit500mSecSec
  global isPasswordMatched
  global beepOn1Sec

  global repeatCounter
  global multikey_Dic 
  global keyInputMultiMode
  global branchNameAddress
  global branchNameAddressBuffer
  global keyPos
  global clearKey
  
  global menuSubSubSubState

  if menuSubSubSubState == BRANCH_NAME:                                     # 1/[]

    if clearKey == 0:
      clearKey = 1
      keypadScanning(0,0,0,0,'clear')
      keyDetect = 0
      keyPos = 0 
      lcd.clear()
      lcd.home()        
    lcd.home()
    lcd.message(" Add Site Name >")
    lcd.message("\n")
    lcd.message("                ")
    
    menuSubSubSubState = menuPositionUpDn(MIN_POS,MAX_POS)    

  if menuSubSubSubState == ADD_BRANCH_NAME:                                 # 2/[0]

    if clearKey == 1:
      clearKey = 0
      keypadScanning(0,0,0,0,'clear')
      keyDetect = 0
      keyPos = 0 
      lcd.clear()
      lcd.home()
      
    keypadScanningMultiKey(15,0,None)
    
    lcd.home()

    lcd.message("\n")
    for index in range(0,16,1):
      lcd.message(str(branchNameAddressBuffer[0][index]))
    
    # Set the cursor position for user input
    lcd.setCursor(keyPos, 1)  # Row 1, Column `keyPos`
    lcd.cursor()  # Show cursor
 
    menuSubSubSubState = menuPositionUpDn(MIN_POS,MAX_POS)
    
  if menuSubSubSubState == REG_BRANCH_NAME:                                 # 3/[1]
    if clearKey == 0:
      clearKey = 1
      keypadScanning(0,0,0,0,'clear')
      keyDetect = 0
      keyPos = 0 
      lcd.clear()
      lcd.home()        
    lcd.home()
    lcd.noCursor()
    lcd.message("<  Update Site >")
    lcd.message("\n")
    if toggleBit500mSecSec:
      lcd.message("  >")
    else:
      lcd.message("   ")
    lcd.message("[UPDATE]")                
    if keypressed == "B":
      keypressed = None
      index = 0
      row = 0
      column = 0
      for index in range(0,16,1):
        branchNameAddress[0][index] = branchNameAddressBuffer[0][index]
      branchNameAddressFileRW('write')
      log = open("/home/pi/Test3/Branch.txt","w")
      for p in range(0,16,1):
        log.write(str(branchNameAddressBuffer[0][p]))
      log.write("\n")
      log.flush()
      log.close()
      beepOn1Sec = 1
      branchNameRead()
      lcd.clear()
      lcd.home()                        
    menuSubSubSubState = menuPositionUpDn(MIN_POS,MAX_POS)
    
  if menuSubSubSubState == EXIT:                                            # 4    
    lcd.home()
    isPasswordMatched = 0
    lcd.message("<     EXIT      ")
    lcd.message("\n")
    lcd.message("    [ENTER]     ")
    menuSubSubSubState = menuPositionUpDn(MIN_POS,MAX_POS)
    if keypressed == "B":
      keypressed = None
      global menuCodeSelectState
      menuSubSubState = 2 
      menuCurrentPos = 2
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()
      

def SubMenuBrandAddress():
  
  BRANCH_NAME, ADD_BRANCH_NAME, REG_BRANCH_NAME, EXIT = range(4)            
  MAX_POS = EXIT
  MIN_POS = BRANCH_NAME

  global keypressed
  global value1
  global GmainStateState
  global menuCurrentPos
  global GuserSetState
  global menuSubState
  global menuSubSubState
  global menuMainState

  global progPass
  global toggleBit500mSecSec
  global isPasswordMatched
  global beepOn1Sec

  global repeatCounter
  global multikey_Dic 
  global keyInputMultiMode
  global brandNameAddress
  global branchNameAddressBuffer
  global keyPos
  global clearKey
  
  global menuSubSubSubState

  if menuSubSubSubState == BRANCH_NAME:                                     # 1/[]

    if clearKey == 0:
      clearKey = 1
      keypadScanning(0,0,0,0,'clear')
      keyDetect = 0
      keyPos = 0 
      lcd.clear()
      lcd.home()        
    lcd.home()
    lcd.message(" Add Brand Name>")    
    lcd.message("\n")
    lcd.message("                ")
    
    menuSubSubSubState = menuPositionUpDn(MIN_POS,MAX_POS)    

  if menuSubSubSubState == ADD_BRANCH_NAME:                                 # 2/[0]

    if clearKey == 1:
      clearKey = 0
      keypadScanning(0,0,0,0,'clear')
      keyDetect = 0
      keyPos = 0 
      lcd.clear()
      lcd.home()
      
    keypadScanningMultiKey(15,0,None)
   
    lcd.home()

    lcd.message("\n")
    for index in range(0,16,1):
      lcd.message(str(branchNameAddressBuffer[0][index]))
    
    # Set the cursor position for user input
    lcd.setCursor(keyPos, 1)  # Row 1, Column `keyPos`
    lcd.cursor()  # Show cursor
    
    menuSubSubSubState = menuPositionUpDn(MIN_POS,MAX_POS)
    
  if menuSubSubSubState == REG_BRANCH_NAME:                                 # 3/[1]
    if clearKey == 0:
      clearKey = 1
      keypadScanning(0,0,0,0,'clear')
      keyDetect = 0
      keyPos = 0 
      lcd.clear()
      lcd.home()        
    lcd.home()
    lcd.noCursor()
    lcd.message("<  Update Site >")
    lcd.message("\n")
    if toggleBit500mSecSec:
      lcd.message("  >")
    else:
      lcd.message("   ")
    lcd.message("[UPDATE]")                
    if keypressed == "B":
      keypressed = None
      index = 0
      row = 0
      column = 0
      for index in range(0,16,1):
        brandNameAddress[0][index] = branchNameAddressBuffer[0][index]
      brandNameAddressFileRW('write')
      log = open("/home/pi/Test3/Brand.txt","w")
      for p in range(0,16,1):
        log.write(str(branchNameAddressBuffer[0][p]))
      log.write("\n")
      log.flush()
      log.close()
      beepOn1Sec = 1
      brandNameRead()
      lcd.clear()
      lcd.home()                        
    menuSubSubSubState = menuPositionUpDn(MIN_POS,MAX_POS)
    
  if menuSubSubSubState == EXIT:                                            # 4    
    lcd.home()
    isPasswordMatched = 0
    lcd.message("<      EXIT     ")
    lcd.message("\n")
    lcd.message("     [ENTER]    ")
    menuSubSubSubState = menuPositionUpDn(MIN_POS,MAX_POS)
    if keypressed == "B":
      keypressed = None
      global menuCodeSelectState
      menuSubSubState = 3
      menuCurrentPos = 3
      keypadScanning(0,0,0,0,'clear')
      lcd.clear()
      lcd.home()


def menuSubSubStateGENERAL_SETTINGS_PROG():
    
    global menuSubState
    global menuSubSubSubState
    global index
    global sub_index
    global GmainStateState
    global menuCurrentPos
    global GuserSetState
    global keypressed
    global menuMainState
    global menuSubSubState
    global clearKey

    global clearKey
                
    menuList = {'DATE_TIME':0,
                'PSWD_CHANGE':1,
                'SITE_NAME': 2,
                'BRAND_NAME': 3,
                'EXIT':4,
                'DATE_TIME_PROG':5,
                'PSWD_CHANGE_PROG':6,
                'SITE_NAME_PROG':7,
                'BRAND_NAME_PROG':8}

    MENU_MAX = 4
    MENU_MIN = 0
    
    if menuSubSubState == menuList['DATE_TIME']:
        
        lcd.message("  DATE & TIME  >")
        lcd.message("\n")
        lcd.message("                ")
        
        menuSubSubState = menuPositionUpDnWithoutClear(MENU_MIN, MENU_MAX)

        if keypressed == "B":           
            keypressed = None
            menuSubSubState = menuList['DATE_TIME_PROG']
            global rtcProgSetMenu
            global menuCurrentPos            
            rtcProgSetMenu = 0
            menuCurrentPos = 0
            clearKey = 0
            keypadScanning(0,0,0,0,'clear')
            lcd.clear()
            lcd.home()

    elif menuSubSubState == menuList['PSWD_CHANGE']:                                 
        lcd.message("< PSWD  CHANGE >")
        lcd.message("\n")
        lcd.message("                ")
        menuSubSubState = menuPositionUpDnWithoutClear(MENU_MIN, MENU_MAX)
        if keypressed == "B":           
            keypressed = None
            menuSubSubState = menuList['PSWD_CHANGE_PROG']
            
            menuCurrentPos = 0
            index = 0
            global menuSubSubSubState
            menuSubSubSubState = 0
            clearKey = 0
            keypadScanning(0,0,0,0,'clear')
            lcd.clear()

    elif menuSubSubState == menuList['SITE_NAME']:                                 
        lcd.message("<  SITE NAME   >")
        lcd.message("\n")
        lcd.message("                ")
        menuSubSubState = menuPositionUpDnWithoutClear(MENU_MIN, MENU_MAX)
        if keypressed == "B":           
            keypressed = None
            menuSubSubState = menuList['SITE_NAME_PROG']

            global branchNameAddressBuffer
            global branchNameAddress
            index = 0
            branchNameAddressFileRW('read')
            for row in range(0,8,1):    
                for column in range(0,16,1):
                    branchNameAddressBuffer[row][column] = branchNameAddress[row][column]

            rtcProgSetMenu = 0
            menuCurrentPos = 0
            menuSubSubSubState = 0
            index = 0            
            lcd.clear()
            lcd.home()
            clearKey = 0
            keypadScanning(0,0,0,0,'clear')

    elif menuSubSubState == menuList['BRAND_NAME']:
        lcd.message("<  BRAND NAME  >")
        lcd.message("\n")
        lcd.message("                ")
        menuSubSubState = menuPositionUpDnWithoutClear(MENU_MIN, MENU_MAX)
        if keypressed == "B":           
            keypressed = None

            menuSubSubState = menuList['BRAND_NAME_PROG']

            global brandNameAddress
            index = 0
            brandNameAddressFileRW('read')
            for row in range(0,8,1):    
                for column in range(0,16,1):
                    branchNameAddressBuffer[row][column] = brandNameAddress[row][column]

            rtcProgSetMenu = 0
            menuCurrentPos = 0
            menuSubSubSubState = 0
            index = 0            
            lcd.clear()
            lcd.home()
            clearKey = 0
            keypadScanning(0,0,0,0,'clear')

        
    elif menuSubSubState == menuList['EXIT']:                                               
        lcd.message("<     EXIT      \n    [ENTER]     ")
        menuSubSubState = menuPositionUpDnWithoutClear(MENU_MIN, MENU_MAX)
        if keypressed == "B":
            keypressed = "CLEAR"
            menuCurrentPos = 0
            menuCodeSelectState = 0
            menuSubState = 0
            lcd.clear()
            lcd.home()
            keypadScanning(0,0,0,0,'clear')
            
    elif menuSubSubState == menuList['DATE_TIME_PROG']:                    
        #eSIMSettingseSIM_SETTINGS_ZONE_PROG()
        progRTCsettings()
        
    elif menuSubSubState == menuList['PSWD_CHANGE_PROG']:                    
        #GNSSSettingsGNSS_SETTINGS_PROG()
        adminPassword()
            
    elif menuSubSubState == menuList['SITE_NAME_PROG']:                    
        SubMenuBranchAddress()
        
    elif menuSubSubState == menuList['BRAND_NAME_PROG']:                    
        SubMenuBrandAddress()

def menuSubSubStateMAINTENANCE_PROG():
    
    global menuSubState
    global index
    global sub_index
    global GmainStateState
    global menuCurrentPos
    global GuserSetState
    global keypressed
    global menuMainState
    global menuSubSubState
    
    global shiftRegister1Buffers
    global shiftRegister2Buffers
    global shiftRegister3Buffers
    global shiftRegister4Buffers

    global relayBuzzer
    global muxSelection
    global shiftRegSet                              		            		    

    if menuSubSubState == 0:        
        lcd.home()
        lcd.message("   SHUTDOWN    >")
        lcd.message("\n")
        lcd.message("                ")
        if keypressed == "B":
            keypressed = None
            
            lcd.message("     System     \n  Switched Off  ")
            
            shift_registers = [shiftRegister1Buffers, shiftRegister2Buffers, shiftRegister3Buffers, shiftRegister4Buffers]
            clear_value = shiftRegSet['CLEAR']

            for reg in shift_registers:
                reg |= clear_value

            shiftRegister1Buffers |= shiftRegSet['CLEAR']
            shiftRegister2Buffers |= shiftRegSet['CLEAR']
            shiftRegister3Buffers |= shiftRegSet['CLEAR']
            shiftRegister4Buffers |= shiftRegSet['CLEAR']
    
            sr.ssrWrite_4( shiftRegister4Buffers, shiftRegister3Buffers, shiftRegister2Buffers, shiftRegister1Buffers )        

            time.sleep(1.0)
            shiftRegister1Buffers |= shiftRegSet['CLEAR']
            shiftRegister2Buffers |= shiftRegSet['CLEAR']
            shiftRegister3Buffers |= shiftRegSet['CLEAR']
            shiftRegister4Buffers |= shiftRegSet['CLEAR']

            shiftRegister3Buffers  = shiftRegister3Buffers  & ~(frontPanelLED2['SYSTEM_HEALTHY_LED'])
            shiftRegister1Buffers = shiftRegister1Buffers & ~(relayBuzzer['LCD_BACK_ON'])                                		            		    
    
            sr.ssrWrite_4( shiftRegister4Buffers, shiftRegister3Buffers, shiftRegister2Buffers, shiftRegister1Buffers )
            
            sendData2TBSystemStatus("false", "false", "false", "false", "false", "false", 'NA', 0)
            time.sleep(60.0)

            sendData2TB("power_cut")
            time.sleep(60.0)
            
            GPIO.cleanup()
            call("sudo shutdown -h now", shell=True)
            
        menuSubSubState = menuPositionUpDn(0,3)

    if menuSubSubState == 1:        
        lcd.home()
        lcd.message("<    RESTART   >")
        lcd.message("\n")
        lcd.message("                ")
        if keypressed == "B":
            keypressed = None

            lcd.home()
            lcd.message("     System     \n Rebooting...   ")
            shift_registers = [shiftRegister1Buffers, shiftRegister2Buffers, shiftRegister3Buffers, shiftRegister4Buffers]
            clear_value = shiftRegSet['CLEAR']

            for reg in shift_registers:
                reg |= clear_value

            shiftRegister1Buffers |= shiftRegSet['CLEAR']
            shiftRegister2Buffers |= shiftRegSet['CLEAR']
            shiftRegister3Buffers |= shiftRegSet['CLEAR']
            shiftRegister4Buffers |= shiftRegSet['CLEAR']
    
            sr.ssrWrite_4( shiftRegister4Buffers, shiftRegister3Buffers, shiftRegister2Buffers, shiftRegister1Buffers )        

            time.sleep(1.0)
            shiftRegister1Buffers |= shiftRegSet['CLEAR']
            shiftRegister2Buffers |= shiftRegSet['CLEAR']
            shiftRegister3Buffers |= shiftRegSet['CLEAR']
            shiftRegister4Buffers |= shiftRegSet['CLEAR']
    
            sr.ssrWrite_4( shiftRegister4Buffers, shiftRegister3Buffers, shiftRegister2Buffers, shiftRegister1Buffers )        

            shiftRegister3Buffers  = shiftRegister3Buffers  & ~(frontPanelLED2['SYSTEM_HEALTHY_LED'])
            #shiftRegister1Buffers = shiftRegister1Buffers & ~(relayBuzzer['LCD_BACK_ON'])                                		            		    

            GPIO.cleanup()            
            call("sudo reboot -h now", shell=True)
            
        menuSubSubState = menuPositionUpDn(0,3)

    if menuSubSubState == 2:        
        lcd.home()
        lcd.message("<WATCHDOG TIMER>")
        lcd.message("\n")
        lcd.message("                ")
        if keypressed == "B":
            keypressed = None
        menuSubSubState = menuPositionUpDn(0,3)
        
    if menuSubSubState == 3:        
        lcd.home()
        lcd.message("<     EXIT      ")
        lcd.message("\n")
        lcd.message("    [ENTER]     ")
        menuSubSubState = menuPositionUpDn(0,3)
        if keypressed == "B":
            keypressed = None
            menuCurrentPos = 1
            menuSubState = 1
            lcd.clear()
            lcd.home()

# ---------------------------- Program State Machine Sub State ------------------------------
# DEF0007 / progStateMachineSubState() 
# -------------------------------------------------------------------------------------------
def progStateMachineSubState():

    #global GpSMSubStateMenu
    global menuMainState
    global keypressed
    global GmainStateState
    global menuCurrentPos
    global rtcProgSetMenu
    global GuserSetState 
    global index
    global menuSubState
    global menuCodeSelectState
    global menuSubPasswordState
    global clearKey
    global isMemoryCleared
    global toggleBit500mSecSec
    global isPasswordReseted
    global isLogCleared
                
    menuList = {'DEVICE_CONFIGURATION':0,
                'EVENT_LOG_MANAGEMENT':1,
                'NETWORK_COMMUNICATION_SETTINGS':2,
                'SECURITY_DEVICE_INTEGRATION':3,
                'POWER_MANAGEMENT':4,
                'SYSTEM_SETTINGS':5,
                'SYSTEM_TEST':6,
                'PROTOCOL_CONFIGURATION':7,
                'DEVICE_PROVISIONING':8,
                'OTA_UPDATE':9,
                'EXIT':10,
                'DEVICE_CONFIGURATION_PROG':11,
                'EVENT_LOG_MANAGEMENT_PROG':12,
                'NETWORK_COMMUNICATION_SETTINGS_PROG':13,
                'SECURITY_DEVICE_INTEGRATION_PROG':14,
                'POWER_MANAGEMENT_PROG':15,
                'SYSTEM_SETTINGS_PROG':16,
                'SYSTEM_TEST_PROG':17,
                'PROTOCOL_CONFIGURATION_PROG':18,
                'DEVICE_PROVISIONING_PROG':19,
                'OTA_UPDATE_PROG':20}

    MENU_MAX = 10
    MENU_MIN = 0
    
    if menuMainState == menuList['DEVICE_CONFIGURATION']:                                   
        lcd.message("      DEVICE   >\n  CONFIGURATION ")
        menuMainState = menuPositionUpDnWithoutClear(MENU_MIN, MENU_MAX)
        menuMainStateHist = 0
        if keypressed == "B":           
            keypressed = None
            menuMainState = menuList['DEVICE_CONFIGURATION_PROG']
            rtcProgSetMenu = 0
            menuCurrentPos = 0
            lcd.clear()
            lcd.home()
            clearKey = 0
            keypadScanning(0,0,0,0,'clear')

    elif menuMainState == menuList['EVENT_LOG_MANAGEMENT']:                                 
        lcd.message("<  EVENT & LOG >\n    MANAGEMENT  ")
        menuMainState = menuPositionUpDnWithoutClear(MENU_MIN, MENU_MAX)
        if keypressed == "B":           
            keypressed = None
            menuMainState = menuList['EVENT_LOG_MANAGEMENT_PROG']
            rtcProgSetMenu = 0
            menuCurrentPos = 0
            menuSubState = 0
            index = 0            
            lcd.clear()
            keypadScanning(0,0,0,0,'clear')

    elif menuMainState == menuList['NETWORK_COMMUNICATION_SETTINGS']:                      
        lcd.message("<    NETWORK   >\n    SETTINGS    ")
        menuMainState = menuPositionUpDnWithoutClear(MENU_MIN, MENU_MAX)
        if keypressed == "B":           
            keypressed = None
            menuMainState = menuList['NETWORK_COMMUNICATION_SETTINGS_PROG']
            menuCurrentPos = 0
            menuSubState = 0  
            index = 0            
            lcd.clear()
            keypadScanning(0,0,0,0,'clear')
        
    elif menuMainState == menuList['SECURITY_DEVICE_INTEGRATION']:                         
        lcd.message("<    DEVICE    >\n   INTEGRATION  ")
        menuMainState = menuPositionUpDnWithoutClear(MENU_MIN, MENU_MAX)        
        if keypressed == "B":           
            keypressed = None
            menuSubPasswordState = 0
            menuMainState = menuList['SECURITY_DEVICE_INTEGRATION_PROG']
            menuCurrentPos = 0
            lcd.clear()
            keypadScanning(0,0,0,0,'clear')
            
    elif menuMainState == menuList['POWER_MANAGEMENT']:                                    
        lcd.message("<    POWER     >\n   MANAGEMENT   ")        
        menuMainState = menuPositionUpDnWithoutClear(MENU_MIN, MENU_MAX)        
        if keypressed == "B":           
            keypressed = None
            menuMainState = menuList['POWER_MANAGEMENT_PROG']
            menuCurrentPos = 0
            index = 0
            clearKey = 0 
            lcd.clear()
            keypadScanning(0,0,0,0,'clear')
            
    elif menuMainState == menuList['SYSTEM_SETTINGS']:                                    
        lcd.message("<    SYSTEM    >\n    SETTINGS    ")        
        menuMainState = menuPositionUpDnWithoutClear(MENU_MIN, MENU_MAX)        
        if keypressed == "B":           
            keypressed = None
            menuMainState = menuList['SYSTEM_SETTINGS_PROG']
            menuCurrentPos = 0
            index = 0
            clearKey = 0
            lcd.clear()
            keypadScanning(0,0,0,0,'clear')
            
    elif menuMainState == menuList['SYSTEM_TEST']:                                        
        lcd.message("<    SYSTEM    >\n      TEST      ")                
        menuMainState = menuPositionUpDnWithoutClear(MENU_MIN, MENU_MAX)        
        if keypressed == "B":           
            keypressed = None
            menuMainState = menuList['SYSTEM_TEST_PROG']
            menuCurrentPos = 0
            index = 0
            menuSubState = 0
            clearKey = 0
            keypadScanning(0,0,0,0,'clear')
            lcd.clear()
            
    elif menuMainState == menuList['PROTOCOL_CONFIGURATION']:                        
        lcd.message("<   PROTOCOL   >\n  CONFIGURATION ")
        menuMainState = menuPositionUpDnWithoutClear(MENU_MIN, MENU_MAX)        
        if keypressed == "B":           
            keypressed = None
            menuMainState = menuList['PROTOCOL_CONFIGURATION_PROG']
            menuCurrentPos = 0
            index = 0
            menuSubState = 0
            clearKey = 0
            keypadScanning(0,0,0,0,'clear')
            lcd.clear()
            
    elif menuMainState == menuList['DEVICE_PROVISIONING']:                                
        lcd.message("<    DEVICE    >\n  PROVISIONING  ")
        menuMainState = menuPositionUpDnWithoutClear(MENU_MIN, MENU_MAX)
        if keypressed == "B":           
            keypressed = None
            menuSubState = 0
            menuCurrentPos = 0
            menuMainState = menuList['DEVICE_PROVISIONING_PROG']
            index = 0
            lcd.clear()
            keypadScanning(0,0,0,0,'clear')
            
    elif menuMainState == menuList['OTA_UPDATE']:                                         
        lcd.message("<     OTA      >\n     UPDATE     ")
        menuMainState = menuPositionUpDnWithoutClear(MENU_MIN, MENU_MAX)
        if keypressed == "B":           
            keypressed = None
            menuSubState = 0
            menuCurrentPos = 0
            menuMainState = menuList['OTA_UPDATE_PROG']
            index = 0
            lcd.clear()
            keypadScanning(0,0,0,0,'clear')
        
    elif menuMainState == menuList['EXIT']:                                               
        lcd.message("<     EXIT      \n     [ENTER]    ")
        menuMainState = menuPositionUpDnWithoutClear(MENU_MIN, MENU_MAX)
        if keypressed == "B":
            keypressed = "CLEAR"
            GmainStateState = 0
            menuCurrentPos = 0
            GuserSetState = 0
            menuCodeSelectState = 0
            lcd.clear()
            lcd.home()
            keypadScanning(0,0,0,0,'clear')
            
    elif menuMainState == menuList['DEVICE_CONFIGURATION_PROG']:                    
        progStateMachineSubSubStateDEVICE_CONFIGURATION_PROG()

    elif menuMainState == menuList['EVENT_LOG_MANAGEMENT_PROG']:
        progStateMachineSubSubStateEVENT_LOG_MANAGEMENT_PROG()
            
    elif menuMainState == menuList['NETWORK_COMMUNICATION_SETTINGS_PROG']:          
        progStateMachineSubSubStateNETWORK_COMMUNICATION_SETTINGS_PROG()
        
    elif menuMainState == menuList['SECURITY_DEVICE_INTEGRATION_PROG']:
        progStateMachineSubSubStateSECURITY_DEVICE_INTEGRATION_PROG()
        
    elif menuMainState == menuList['POWER_MANAGEMENT_PROG']:
        progStateMachineSubSubStatePOWER_MANAGEMENT_PROG()
        
    elif menuMainState == menuList['SYSTEM_SETTINGS_PROG']:
        progStateMachineSubSubStateSYSTEM_SETTINGS_PROG()
                
    elif menuMainState == menuList['SYSTEM_TEST_PROG']:                             
        progStateMachineSubSubStateSYSTEM_TEST_PROG()
        
    elif menuMainState == menuList['PROTOCOL_CONFIGURATION_PROG']:
        progStateMachineSubSubStatePROTOCOL_CONFIGURATION_PROG()

    elif menuMainState == menuList['DEVICE_PROVISIONING_PROG']:
        progStateMachineSubSubStateDEVICE_PROVISIONING_PROG()

    elif menuMainState == menuList['OTA_UPDATE_PROG']:                              
        progStateMachineSubSubStateOTA_UPDATE_PROG()


def progStateMachine():
    global GuserSetState
    global menuCurrentPos
    global keypressed
    global adminPass
    global servicePass
    global menuMainState        # Added 25/09/2017
    global beepOn1Sec
    global toggleBit500mSecSec
    global wrongPassEntered
    global wrongPassBuff

    if GuserSetState == 0:
        wrongPassEntered = 0
        wrongPassBuff = None

        GuserSetState = 1
        lcd.clear()
        lcd.home()

    elif GuserSetState == 1:

        lcd.home()
        lcd.message("    Password    ")
        lcd.message("\n")
        if toggleBit500mSecSec:
            lcd.message("    >")
        else:
            lcd.message("     ")
        if wrongPassEntered == 0:            
            keyDetect = keypadScanning(8,0,99999999,0)
            keyDetect2Asterisk = numeric2Asterisk(keyDetect)
            wrongPassBuff = keyDetect2Asterisk
            lcd.message(str(keyDetect2Asterisk))
        else:
            lcd.message(str(wrongPassBuff))
            keyDetect = 0
            if keypressed == "C":
                keypressed = None
                wrongPassEntered = 0
                keypadScanning(0,0,0,0,'clear')
                lcd.clear()
                lcd.home()
                
        if keypressed == "B":
            keypressed = None
            if wrongPassEntered == 0:
                adminPasswordFileRW('read')
                servicePasswordFileRW('read')
                if keyDetect > 9:
                    if adminPass[1] == keyDetect:  
                        GuserSetState = 2
                        menuCurrentPos = 0
                        menuMainState = 0
                        lcd.clear()
                        lcd.home()
                        beepOn1Sec = 1
                    elif adminPass[3] == keyDetect:  
                        GuserSetState = 2
                        menuCurrentPos = 0
                        menuMainState = 0
                        lcd.clear()
                        lcd.home()
                        beepOn1Sec = 1
                    elif servicePass[1] == keyDetect:  
                        GuserSetState = 2
                        menuCurrentPos = 0
                        menuMainState = 0
                        lcd.clear()
                        lcd.home()
                        beepOn1Sec = 1                    
                    else:
                        lcd.message("[W]")
                        wrongPassEntered = 1
                        wrongPassBuff = wrongPassBuff + "[W]"
            
    elif GuserSetState == 2:
        wrongPassEntered = 0        
        progStateMachineSubState()


def progMainStateMachine():

    global menuMainState        # progStateMachineSubState()
    global keypressed           # 
    global menuCurrentPos       #
    global index                #
    global menuCodeSelectState  #
    global GmainStateState      #

    MASTER_CODE, EXIT, MASTER_CODE_PRO = range(3)
    
    MENU_MAX = EXIT
    MENU_MIN = MASTER_CODE
        
    if menuCodeSelectState == MASTER_CODE:
        lcd.message("User  Interface\n              >>")
        menuCodeSelectState = menuPositionUpDnWithoutClear(MENU_MIN, MENU_MAX)
        if keypressed == "B":          
            keypressed = None
            menuCodeSelectState = MASTER_CODE_PRO
            menuCurrentPos = 0
            exitMenuAuto(1)
            lcd.clear()
            lcd.home()
            
            
    elif menuCodeSelectState == EXIT:
        lcd.message("<     EXIT      \n     [ENTER]    ")
        menuCodeSelectState = menuPositionUpDnWithoutClear(MENU_MIN, MENU_MAX)
        if keypressed == "B":
            keypressed = None
            menuCurrentPos = 0
            menuCodeSelectState = 0
            GmainStateState = 0
            lcd.clear()
            lcd.home()
            
    elif menuCodeSelectState == MASTER_CODE_PRO:
        progStateMachine()
        
    exitMenuAuto()

def send_tailscale_info():
    try:
        # Connect and fetch latest Tailscale entry
        # DB-FIX-2: create table if Tailscale has not been provisioned yet
        # (tailscale_setup.py creates it on first provisioning — before that
        #  the table does not exist and the SELECT would raise OperationalError)
        conn = sqlite3.connect(DB_TAILSCALE)  # DB-FIX: was hardcoded path
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS device_info (
                id                 INTEGER PRIMARY KEY AUTOINCREMENT,
                tailscale_hostname TEXT,
                tailscale_ip       TEXT,
                timestamp          DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.commit()
        cursor.execute("SELECT tailscale_hostname, tailscale_ip FROM device_info ORDER BY timestamp DESC LIMIT 1")
        row = cursor.fetchone()
        conn.close()

        if row:
            tailscale_hostname, tailscale_ip = row
            # Prepare structured data
            
            log_data = {
                    "tailscale_data": [
                        {
                            "tailscale_hostname": tailscale_hostname,
                            "tailscale_ip": tailscale_ip
                        }
                    ]
                }
            
            sendData2TB(log_data)

           # print("Tailscale data sent successfully.")

        else:
            logger.debug("[send_tailscale_info] No Tailscale data in DB yet")

    except Exception as ex:
        logger.error("[send_tailscale_info] %s", ex)


def get_ip_address():
    """
    Retrieves the IP address of the LAN interface.

    Returns:
        str: The IP address or 'N/A' if not found.
    """
    try:
        output = subprocess.check_output(
            ['nsenter', '-t', '1', '-m', '-n', '--', '/usr/bin/ip', 'addr', 'show', 'eth0'],
            stderr=subprocess.STDOUT
        )
        for line in output.decode('utf-8').splitlines():
            if 'inet ' in line:
                return line.split()[1].split('/')[0]
    except (subprocess.CalledProcessError, FileNotFoundError, IndexError):
        pass
    return 'N/A'

def get_mac_address():
    """
    Retrieves the MAC address of the LAN interface.

    Returns:
        str: The MAC address or 'N/A' if not found.
    """
    try:
        output = subprocess.check_output(
            ['nsenter', '-t', '1', '-m', '-n', '--', '/usr/bin/ip', 'addr', 'show', 'eth0'],
            stderr=subprocess.STDOUT
        )
        for line in output.decode('utf-8').splitlines():
            if 'link/ether ' in line:
                return line.split()[1]
    except (subprocess.CalledProcessError, FileNotFoundError, IndexError):
        pass
    return 'N/A'

def get_default_gateway():
    """
    Retrieves the default gateway.

    Returns:
        str: The default gateway or 'N/A' if not found.
    """
    try:
        output = subprocess.check_output(
            ['nsenter', '-t', '1', '-m', '-n', '--', '/usr/bin/ip', 'route', 'show'],
            stderr=subprocess.STDOUT
        )
        for line in output.decode('utf-8').splitlines():
            if 'default via' in line:
                return line.split()[2]
    except (subprocess.CalledProcessError, FileNotFoundError, IndexError):
        pass
    return 'N/A'

def get_dns_servers():
    """
    Retrieves the DNS servers.

    Returns:
        list: A list of DNS server addresses or ['N/A'] if none are found.
    """
    try:
        dns_servers = []
        with open('/etc/resolv.conf', 'r') as resolv_file:
            for line in resolv_file:
                if line.startswith('nameserver'):
                    dns_servers.append(line.split()[1])
        if dns_servers:
            return dns_servers
    except IOError:
        pass
    return ['N/A']


# ── Auto-failover: ethernet ↔ GSM (C16QS) ─────────────────────────────────────
# When eth0 loses internet connectivity, pon c16qs brings up ppp0 and the
# system transparently routes ThingsBoard traffic through the GSM modem.
# When eth0 recovers, poff c16qs drops ppp0 and ethernet takes over again.
# Only activates on devices configured as network_type=ethernet (type 1).
# ──────────────────────────────────────────────────────────────────────────────

_failover_gsm_active = False   # True while ppp0 is up due to eth0 failure
_eth_stable_count = 0          # consecutive eth0-up checks while in GSM failover
_ETH_STABLE_THRESHOLD = 6      # require 6 × 30 s = 3 min of continuous eth0 health before switch-back

def _eth0_has_connectivity():
    """Return True if eth0 has an IP address AND can reach 8.8.8.8."""
    try:
        out = subprocess.check_output(
            ['nsenter', '-t', '1', '-m', '-n', '--', '/usr/bin/ip', 'addr', 'show', 'eth0'],
            stderr=subprocess.DEVNULL, timeout=5
        ).decode('utf-8', errors='replace')
        if 'inet ' not in out:
            return False
        result = subprocess.run(
            ['nsenter', '-t', '1', '-m', '-n', '--',
             'ping', '-c', '1', '-W', '3', '-I', 'eth0', '8.8.8.8'],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10
        )
        return result.returncode == 0
    except Exception:
        return False


def _ppp0_has_connectivity():
    """Return True if ppp0 has an IP address AND can reach 8.8.8.8."""
    try:
        out = subprocess.check_output(
            ['nsenter', '-t', '1', '-m', '-n', '--', '/usr/bin/ip', 'addr', 'show', 'ppp0'],
            stderr=subprocess.DEVNULL, timeout=5
        ).decode('utf-8', errors='replace')
        if 'inet ' not in out:
            return False
        result = subprocess.run(
            ['nsenter', '-t', '1', '-m', '-n', '--',
             'ping', '-c', '1', '-W', '3', '-I', 'ppp0', '8.8.8.8'],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10
        )
        return result.returncode == 0
    except Exception:
        return False


def _pppd_is_running():
    """Return True if the pppd process is alive on the host."""
    try:
        return subprocess.run(
            ['nsenter', '-t', '1', '-m', '-u', '-i', '-n', '-p', '--', 'pgrep', '-x', 'pppd'],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        ).returncode == 0
    except Exception:
        return False


def _run_failover_monitor():
    # PURPOSE: Automatic ethernet failover for dynamic broadband mode only.
    # Only started when network_type='ethernet' (see bottom of file).
    # Never used in GSM-primary mode (static ethernet + user chose GSM).
    #
    # LOGIC:
    #   eth0 fails  → set DB network_type='gsm'  → dexter-mqtt exits cleanly
    #                  SerialCommunication.py was already running AT+MQTTPUBLM
    #                  via c16qs — no pon needed, it becomes sole data sender.
    #   eth0 restored → set DB network_type='ethernet' → restart dexter-mqtt
    #                  broadband resumes as primary path.
    #
    # NO pon/poff here — ppp0 is only used by ota_update.sh (daily, GSM mode)
    # and check_and_send() in SerialCommunication.py (config sync, GSM mode).
    global _failover_gsm_active, _eth_stable_count, network_type
    import http.client as _httpclient

    class _UnixHTTPConn(_httpclient.HTTPConnection):
        def __init__(self, sock_path):
            super().__init__("localhost")
            self._sock_path = sock_path
            self.sock = None
        def connect(self):
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.connect(self._sock_path)
            self.sock = s

    while True:
        time.sleep(30)
        try:
            eth_up = _eth0_has_connectivity()

            if not eth_up and not _failover_gsm_active:
                # eth0 lost — switch DB to gsm; dexter-mqtt will exit on next
                # restart cycle. SerialCommunication.py (always running) takes
                # over as sole ThingsBoard sender via AT+MQTTPUBLM (c16qs).
                logger.warning("[failover] eth0 lost — DB→gsm; dexter-mqtt exits; c16qs AT+MQTT takes over")
                _failover_gsm_active = True
                network_type = 2
                try:
                    modem_config_db.update_parameter('network_type', 'gsm')
                except Exception as _dbe:
                    logger.warning("[failover] DB update to gsm failed: %s", _dbe)
                try:
                    insert_with_cap(json.dumps({
                        "network_event": {
                            "status":    "over_gsm",
                            "timestamp": datetime.datetime.now().isoformat(),
                        }
                    }))
                except Exception as _te:
                    logger.warning("[failover] network_event telemetry failed: %s", _te)

            elif eth_up and _failover_gsm_active:
                # eth0 back up — require _ETH_STABLE_THRESHOLD consecutive healthy checks
                # before switching back to prevent flip-flopping on a flapping link.
                _eth_stable_count += 1
                if _eth_stable_count < _ETH_STABLE_THRESHOLD:
                    logger.info(
                        "[failover] eth0 up — stability %d/%d (need %ds continuous before switch-back)",
                        _eth_stable_count, _ETH_STABLE_THRESHOLD, _ETH_STABLE_THRESHOLD * 30
                    )
                else:
                    _eth_stable_count = 0
                    logger.info(
                        "[failover] eth0 stable for %ds — DB→ethernet; restarting dexter-mqtt",
                        _ETH_STABLE_THRESHOLD * 30
                    )
                    _failover_gsm_active = False
                    network_type = 1
                    try:
                        modem_config_db.update_parameter('network_type', 'ethernet')
                    except Exception as _dbe:
                        logger.warning("[failover] DB update to ethernet failed: %s", _dbe)
                    try:
                        _conn = _UnixHTTPConn("/var/run/docker.sock")
                        _conn.request("POST", "/containers/dexter-mqtt/restart?t=5")
                        _resp = _conn.getresponse()
                        _conn.close()
                        if _resp.status not in (204, 304):
                            logger.warning("[failover] dexter-mqtt restart HTTP %s", _resp.status)
                        else:
                            logger.info("[failover] dexter-mqtt restarted — publishing via broadband ethernet")
                    except Exception as _de:
                        logger.warning("[failover] dexter-mqtt restart failed: %s", _de)
                    try:
                        insert_with_cap(json.dumps({
                            "network_event": {
                                "status":    "over_ethernet",
                                "timestamp": datetime.datetime.now().isoformat(),
                            }
                        }))
                    except Exception as _te:
                        logger.warning("[failover] network_event telemetry failed: %s", _te)

            elif not eth_up and _failover_gsm_active:
                # Still in GSM failover, eth0 still down — if it had briefly come up
                # and started incrementing the stability counter, reset it now.
                if _eth_stable_count > 0:
                    logger.info("[failover] eth0 flapped — reset stability count")
                    _eth_stable_count = 0

        except Exception as _fe:
            logger.error("[failover] monitor error: %s", _fe)


menuSteps = 0
keyHoldHist = 0
keyHoldRunning = 0
onTime = 0
closingTimeEmg = 0
menuLedToggleBit = 0
emgAccessInProgress = 0
dateFormat = 0
timeFormat = 0
closingTimeNormalSchedule = 0
wrongPassRegistered = 0
lowBatteryDetectionWaitPeriod = 0
closingTimeLowBatSchedule = 0
accessIsRestrictedHOLIDAY = 0
accessIsRestrictedNationalHOLIDAY = 0
isOnMaintenanceMode = 0
rtcFaulty = 0


def dispStateMachine():
    
    global menuSteps, holdDispSCAN, keypressed, keyHoldHist, keyHoldRunning
    global onTime, closingTimeEmg
    global menuLedToggleBit, emgAccessInProgress, tamper, emgAccessWaitPeriodInProgress, tick3Sec1
    global rtcOptions, rtcParam, dateFormat, timeFormat
    global normalAccessWaitPeriodInProgress, closingTimeNormalSchedule
    global groupValidityCheck, tamperPassActivated, wrongPassRegistered
    global lowBatteryDetectionWaitPeriod, closingTimeLowBatSchedule
    global accessIsRestrictedHOLIDAY, accessIsRestrictedNationalHOLIDAY
    global isOnMaintenanceMode, toggleBit500mSecSec, rtcFaulty, accountStatusGrA, accountStatusGrB
    global LCDBackLightON, lowBatteryDetected, statusbox_battery_reverse, statusbox_battery_low
    global brandName, branchName #, gsmServiceProvider, connectedDevices  # Assuming connectedDevices is a global variable

    # Menu constants
    BRAND_NAME, DEVICE_NAME, TIME_DATE, BRANCH_NAME, SYSTEM_STATUS, BATTERY_STATUS, GSM_SERVICE_PROVIDER, CONNECTED_DEVICES, LAT_LONG, ACTIVE_INTEGRATION_HIK_NVR, ACTIVE_INTEGRATION_HIK_BACS, ACTIVE_INTEGRATION_DAHUA_NVR = range(12)

    # Handle button press
    if keypressed == "B":
        keypressed = None
        holdDispSCAN = 1 - holdDispSCAN

    # Function to format text to 16 characters
    def format_text(text, width=16):
        text = str(text)
        if len(text) >= width:
            return text[:width]
        return text + " " * (width - len(text))

    # Function to center text
    def center_text(text, width):
        text = str(text)
        if len(text) >= width:
            return text[:width]
        padding = (width - len(text)) // 2
        return " " * padding + text + " " * (width - len(text) - padding)

    # Display handling based on the current menu step
    if menuSteps == BRAND_NAME:
        lcd.home()
        lcd.message(format_text("     Brand     ") + "\n" + format_text(center_text(brandName, 16)))

    elif menuSteps == DEVICE_NAME:
        lcd.home()
        lcd.message(format_text("  DEXTER  V3.0  ") + "\n" + format_text(" Local Recv Stn "))

    elif menuSteps == BRANCH_NAME:
        lcd.home()
        lcd.message(format_text("     Branch     ") + "\n" + format_text(center_text(branchName, 16)))

    elif menuSteps == TIME_DATE:
        lcd.home()
        time_str = ""
        if timeFormat == 0:
            time_str = "%02d:%02d:%02d" % (rtcOptions[rtcParam['HOUR']], rtcOptions[rtcParam['MINUTE']], rtcOptions[rtcParam['SECOND']])
        else:
            hour = rtcOptions[rtcParam['HOUR']]
            am_pm = "AM" if hour < 12 else "PM"
            hour = hour % 12 if hour % 12 else 12
            time_str = "%02d:%02d %s" % (hour, rtcOptions[rtcParam['MINUTE']], am_pm)
        date_str = "%02d/%02d/%d" % (rtcOptions[rtcParam['DAY']], rtcOptions[rtcParam['MONTH']], rtcOptions[rtcParam['YEAR']]) if dateFormat else "%02d/%02d/%d" % (rtcOptions[rtcParam['MONTH']], rtcOptions[rtcParam['DAY']], rtcOptions[rtcParam['YEAR']])
        lcd.message(format_text("Time: " + time_str) + "\n" + format_text("Date: " + date_str))

    elif menuSteps == SYSTEM_STATUS:
        lcd.home()
        status_message = ""        
        if rtcFaulty:
            status_message = "   RTC Faulty   "
        elif isOnMaintenanceMode:
            status_message = " Maintenance On "
        elif lowBatteryDetected or statusbox_battery_low == 'true':
            status_message = "  Battery  Low  "
        else:
            status_message = "     Healthy    "
        lcd.message(format_text(" System  Status ") + "\n" + format_text(status_message))

    elif menuSteps == BATTERY_STATUS:
        lcd.home()
        if lowBatteryDetectionWaitPeriod:
            cth, ctm = numericToTime24HrsFormat(closingTimeLowBatSchedule)
            lcd.message(format_text("  Low Battery   ") + "\n" + format_text("Ends:  %dHr%dMn " % (cth, ctm)))
        elif statusbox_battery_low == "true" or lowBatteryDetected:
            lcd.message(format_text("     Battery    ") + "\n" + format_text("       Low      "))
        elif statusbox_battery_reverse == "true":
            lcd.message(format_text("     Battery    ") + "\n" + format_text("     Reverse    "))
        else:
            lcd.message(format_text("     Battery    ") + "\n" + format_text("     Healthy    "))

    elif menuSteps == GSM_SERVICE_PROVIDER:
        lcd.home()
        lcd.message(format_text(center_text("     GSM     ", 16)) + "\n" + format_text(center_text(cavli_database.get_service_provider(), 16)))

    elif menuSteps == CONNECTED_DEVICES:
        lcd.home()
        connectedDevices = calculate_zones_on()
        lcd.message(format_text(" Connected Devs ") + "\n" + format_text(center_text(connectedDevices, 16)))

    elif menuSteps == LAT_LONG:
        lcd.home()
        latitude = cavli_database.get_latitude()
        longitude = longitude = cavli_database.get_longitude()        
        lcd.message(format_text("Lat: " + str(latitude)[:7]) + "\n" + format_text("Lon: " + str(longitude)[:7]))
             
    #elif menuSteps == CONNECTED_DEVICES:
    #    lcd.home()
    #    lcd.message(format_text(" Connected Devs ") + "\n" + format_text(center_text(connectedDevices, 16)))

    #elif menuSteps == IP_ADDRESS:
    #    lcd.home()
    #    lcd.message(format_text("   IP  Address  ") + "\n" + format_text(center_text(get_ip_address(), 16)))
        
    #elif menuSteps == GATEWAY:
    #    lcd.home()
    #    lcd.message(format_text("     Gateway    ") + "\n" + format_text(center_text(get_default_gateway(), 16)))

    #elif menuSteps == DNS_SERVER:
    #    lcd.home()
    #    lcd.message(format_text("   DNS  Server  ") + "\n" + format_text(center_text(get_dns_servers(), 16)))


    # Menu step increment logic
    if tick3Sec1 == 1 and holdDispSCAN == 0:
        tick3Sec1 = 0
        menuSteps = (menuSteps + 1) % 12  # Update to match the new menu count

    # LCD backlight control
    LCDBackLightON = 1 if holdDispSCAN else 0

    # Override menu step in certain conditions
    if tamperPassActivated:
        menuSteps = SYSTEM_STATUS
        holdDispSCAN = 0
    elif lowBatteryDetectionWaitPeriod:
        menuSteps = BATTERY_STATUS
        holdDispSCAN = 0


GmainStateState = 0
GtaskManagerSTATE = 0
emergencyAccessSetState = 0 
groupValidityCheck = 0
emergencyAccessMainState = 0
tamper = 0
menuCurrentPos = 0
onTimeEmgAccess = 0
isUserValidationChecked = 0
normalAccessWaitPeriodInProgress = 0
emgAccessWaitPeriodInProgress = 0
tamperPassActivated = 0
sleepSwitch = 0
holdDispSCAN = 0
LCDBackLightON = 0
inAccessTimeProgMenu = 0


# ─────────────────────────────────────────────────────────────────────────────
# RELAY_1 COMMUNICATOR POWER-CYCLE RECOVERY
# ─────────────────────────────────────────────────────────────────────────────

def reset_communicator_relay():
    """
    Monitors Cavli communicator module health via cavliRunningParam.db
    (written by SerialCommunication.py). Implements 4-phase recovery:

    PROCESS 1 — Detect (t = 0 min)
      Called every 10 min by tick10Min_1.
      dataSending='Error' seen → _relay1_error_count = 1. Wait. Do nothing yet.
      systemd is already restarting SerialCommunication.py every 10s.

    PROCESS 2 — Confirm + Power-cycle (t = 10 min)
      dataSending still 'Error' → _relay1_error_count = 2 → confirmed stuck.
      Phase 1 : RELAY_1 OFF for 5s  (modem power removed)
      Phase 2 : RELAY_1 ON, wait 30s (modem boot)
      Phase 3 : Restart dexter-serial-comm service once via systemctl
                (gives SerialCommunication.py a clean start after modem is ready)
      _relay1_error_count reset to 0 after service restart.

    PROCESS 3 — Check recovery (t = 20 min, next poll)
      If dataSending = 'Success'/'Executing' → modem recovered ✓
        _sd_notify_watchdog() resumes in SerialCommunication.py → no reboot.
      If dataSending = 'Error' → relay reset + service restart did not help.
        Repeat Process-2 ONCE MORE (another power-cycle + service restart).
        If still Error → _relay1_error_count >= 3 → force RPi reboot (#1 of 2/day).

    PROCESS 4 — Post-reboot repeat (t ≈ 160 min after reboot)
      Same cycle repeats after reboot. If still stuck → reboot #2 of 2/day.
      If still stuck after 2 reboots → CRITICAL alert, manual intervention.

    Next day  — _relay1_reboot_date resets → counter back to 0, cycle restarts.

    Phases
    ------
      Phase 0 : idle — poll every 10 min via tick10Min_1
      Phase 1 : RELAY_1 OFF (5s)
      Phase 2 : RELAY_1 ON, wait 30s for modem boot
      Phase 3 : restart dexter-serial-comm service, then mark complete

    sr.ssrWrite_4() writes shiftRegister1Buffers to hardware every ~100ms,
    so relay changes take effect within one main loop iteration.
    """
    global shiftRegister1Buffers
    global _relay1_reset_in_progress
    global _relay1_reset_start_time
    global _relay1_reset_phase
    global _relay1_error_holdoff
    global _relay1_error_count
    global _relay1_reboot_count
    global _relay1_reboot_date

    import datetime as _dt
    import subprocess as _sp

    now   = time.time()
    today = _dt.date.today()

    # Reset daily reboot counter at midnight
    if _relay1_reboot_date != today:
        _relay1_reboot_date  = today
        _relay1_reboot_count = 0
        logger.info("[relay_reset] Daily reboot counter reset for %s", today)

    # ── Phase advance: drive an in-progress power-cycle sequence ─────────────
    if _relay1_reset_in_progress:

        # Phase 1: RELAY_1 OFF — hold for 5 seconds then restore power
        if _relay1_reset_phase == 1:
            if now - _relay1_reset_start_time >= 5.0:
                shiftRegister1Buffers    = shiftRegister1Buffers | relayBuzzer['RELAY_1']
                _relay1_reset_phase      = 2
                _relay1_reset_start_time = now
                logger.info("[relay_reset] RELAY_1 ON — modem power restored, waiting 30s for boot")
            return

        # Phase 2: wait 30 seconds for modem to fully boot
        if _relay1_reset_phase == 2:
            if now - _relay1_reset_start_time >= 30.0:
                _relay1_reset_phase      = 3
                _relay1_reset_start_time = now
                logger.info(
                    "[relay_reset] Modem boot wait done — "
                    "restarting dexter-serial-comm service"
                )
            return

        # Phase 3: restart dexter-serial-comm once so SerialCommunication.py
        # gets a clean start with the freshly booted modem
        if _relay1_reset_phase == 3:
            try:
                _sp.run(
                    ["sudo", "systemctl", "restart", "dexter-serial-comm"],
                    check=False, timeout=10
                )
                logger.info(
                    "[relay_reset] dexter-serial-comm restarted — "
                    "power-cycle sequence complete. Next poll in 10 min."
                )
            except Exception as _e:
                logger.error("[relay_reset] Service restart failed: %s", _e)

            # Sequence complete — reset flags, next 10-min poll confirms recovery
            _relay1_reset_in_progress = False
            _relay1_reset_phase       = 0
            _relay1_error_count       = 0
            _relay1_error_holdoff     = now
            return

        return  # safety — unknown phase

    # ── Phase 0: idle — called every 10 min by tick10Min_1 ───────────────────
    data_sending = cavli_database.get_data_sending()

    if data_sending != 'Error':
        # Modem healthy — clear error counter
        if _relay1_error_count > 0:
            logger.info(
                "[relay_reset] dataSending='%s' — modem recovered, "
                "clearing error count", data_sending
            )
        _relay1_error_count = 0
        return

    # dataSending == 'Error'
    _relay1_error_count += 1
    logger.warning(
        "[relay_reset] dataSending='Error' — error count: %d",
        _relay1_error_count
    )

    # ── Count 1: first error — wait one more poll to confirm not transient ───
    if _relay1_error_count == 1:
        logger.info("[relay_reset] First error — waiting 10 min to confirm stuck modem")
        return

    # ── Count >= 2: confirmed stuck — check if reboot limit reached ──────────
    # (count 2 = first confirmed trigger; count 3+ = relay reset did not help)

    if _relay1_error_count >= 3:
        # Previous relay reset + service restart did not recover the modem
        if _relay1_reboot_count >= _RELAY1_MAX_REBOOTS_PER_DAY:
            logger.critical(
                "[relay_reset] Modem UNRECOVERABLE — %d/%d reboots used today. "
                "MANUAL INTERVENTION REQUIRED. No further action.",
                _relay1_reboot_count, _RELAY1_MAX_REBOOTS_PER_DAY
            )
            return

        _relay1_reboot_count += 1
        logger.critical(
            "[relay_reset] Relay reset + service restart did NOT recover modem — "
            "forcing RPi reboot (%d/%d today)",
            _relay1_reboot_count, _RELAY1_MAX_REBOOTS_PER_DAY
        )
        _sp.run(["sudo", "reboot"], check=False)
        return

    # ── Count == 2: trigger RELAY_1 power-cycle + service restart sequence ───
    logger.warning(
        "[relay_reset] 2 consecutive errors (20 min stuck confirmed) — "
        "starting RELAY_1 power-cycle sequence"
    )
    _relay1_reset_in_progress = True
    _relay1_reset_start_time  = now
    _relay1_reset_phase       = 1

    # Phase 1 begins: cut modem power
    shiftRegister1Buffers = shiftRegister1Buffers & ~(relayBuzzer['RELAY_1'])
    logger.info("[relay_reset] RELAY_1 OFF — modem power removed (5s)")

def mainStateMachine():
    
    global GmainStateState
    global keypressed
    global toggleBit1Sec

    global menuCurrentPos # << Menu >>

    global holdDispSCAN
   
    global LCDBackLightON
    global GtaskManagerSTATE

    LCDBackLightON = 1

    if keypressed == "A":
        keypressed = None
        if GmainStateState == 0:        # Added on 04/10/2017
             GmainStateState = 1
             menuCurrentPos = 0      # Clear Menu Slide Buffer to 0
             lcd.clear()
             lcd.home()
        elif GmainStateState == 1:
            returnToDisplayScan()
            
        elif GmainStateState == 2:
            returnToDisplayScan()
        
        elif GmainStateState == 3:
            returnToDisplayScan()        

    elif keypressed == "D":
        keypressed = None
        if GmainStateState == 0:        # Added on 04/10/2017
            GmainStateState = 2         # Task Manager #Lamp Test button
            menuCurrentPos = 0          # Clear Menu Slide Buffer to 0
            lcd.clear()
            lcd.home()
    
    if GmainStateState == 0:                    # Display Scan
            
        dispStateMachine()
        
        if keypressed == "1":
            keypressed = None
            keypadScanning(0,0,0,0,'clear')            
        elif keypressed == "2":
            keypressed = None
            keypadScanning(0,0,0,0,'clear')            
        elif keypressed == "3":
            keypressed = None
            keypadScanning(0,0,0,0,'clear')            
        elif keypressed == "4":
            keypressed = None
            keypadScanning(0,0,0,0,'clear')            
        elif keypressed == "5":
            keypressed = None
            keypadScanning(0,0,0,0,'clear')            
        elif keypressed == "6":
            keypressed = None
            keypadScanning(0,0,0,0,'clear')            
        elif keypressed == "7":
            keypressed = None
            keypadScanning(0,0,0,0,'clear')            
        elif keypressed == "8":
            keypressed = None
            keypadScanning(0,0,0,0,'clear')            
        elif keypressed == "9":
            keypressed = None
            keypadScanning(0,0,0,0,'clear')            

        elif keypressed == "@":
            keypressed = None
            if GmainStateState == 0:      # Added on 12/03/2025
              GmainStateState = 3         # Password bassed Reboot Button
              menuCurrentPos = 0          # Clear Menu Slide Buffer to 0
              lcd.clear()
              lcd.home()
              keypadScanning(0,0,0,0,'clear')

        elif keypressed == "*":
            keypressed = None
            keypadScanning(0,0,0,0,'clear')            
                              
    elif GmainStateState == 1:
        progMainStateMachine()
        
    elif GmainStateState == 2:
        proLampTestExt()
    
    elif GmainStateState == 3:
        rebootButton()            # Password bassed Reboot Button
    
    elif GmainStateState == 4:
        pass



def rebootButton():
    global GuserSetState
    global menuCurrentPos
    global keypressed
    global adminPass
    global servicePass

    global menuMainState        # Added 25/09/2017

    global beepOn1Sec

    global toggleBit500mSecSec
    global wrongPassEntered
    global wrongPassBuff

    if GuserSetState == 0:
        wrongPassEntered = 0
        wrongPassBuff = None
        GuserSetState = 1
        lcd.clear()
        lcd.home()
    elif GuserSetState == 1:
        lcd.home()
        lcd.message("Reboot Password ")
        lcd.message("\n")
        if toggleBit500mSecSec:
            lcd.message("    >")
        else:
            lcd.message("     ")
        if wrongPassEntered == 0:            
            keyDetect = keypadScanning(8,0,99999999,0)
            keyDetect2Asterisk = numeric2Asterisk(keyDetect)
            wrongPassBuff = keyDetect2Asterisk
            lcd.message(str(keyDetect2Asterisk))
        else:
            lcd.message(str(wrongPassBuff))
            keyDetect = 0
            if keypressed == "C":
                keypressed = None
                wrongPassEntered = 0
                keypadScanning(0,0,0,0,'clear')
                lcd.clear()
                lcd.home()
                
        if keypressed == "B":
            keypressed = None 
            if wrongPassEntered == 0:
                adminPasswordFileRW('read')
                servicePasswordFileRW('read')
                if keyDetect > 9:
                    if adminPass[1] == keyDetect:  
                        GuserSetState = 2
                        menuCurrentPos = 0
                        menuMainState = 0
                        lcd.clear()
                        lcd.home()
                        beepOn1Sec = 1
                    elif adminPass[3] == keyDetect:  
                        GuserSetState = 2
                        menuCurrentPos = 0
                        menuMainState = 0
                        lcd.clear()
                        lcd.home()
                        beepOn1Sec = 1 
                    elif servicePass[1] == keyDetect:  
                        GuserSetState = 2
                        menuCurrentPos = 0
                        menuMainState = 0
                        lcd.clear()
                        lcd.home()
                        beepOn1Sec = 1                    
                    else:
                        lcd.message("[W]")
                        wrongPassEntered = 1
                        wrongPassBuff = wrongPassBuff + "[W]"

            
    elif GuserSetState == 2:
        wrongPassEntered = 0        
        rebootPanel()
  
  
# Example of a consumer program that reads and processes JSON objects
def consume_json():

    # Get the oldest JSON object from the database and delete it
    json_data = get_and_delete_json_from_db()

    if json_data:
        print("Consumed and processed JSON:", json_data)
        # Convert JSON string to dictionary
        incoming_json_obj = json_data
        msg_queue_buffer.add(incoming_json_obj)
    else:
        print("No more JSON objects in the buffer.")
        pass
        

def set_date_time(year, month, day, hour, minute, second):
    """
    Set the system date and time.
    Primary: timedatectl (systemd) — disable NTP, set time, re-enable NTP.
    Fallback: date -s — used inside Docker where systemd D-Bus is unavailable.
    Root (UID 0) skips sudo prefix; bare-metal pi user keeps it.
    """
    _sudo = [] if os.getuid() == 0 else ["sudo"]
    date_time_str = "{0:04d}-{1:02d}-{2:02d} {3:02d}:{4:02d}:{5:02d}".format(
        year, month, day, hour, minute, second)

    # Try timedatectl (requires systemd D-Bus — works on bare metal, not Docker)
    _ntp_disabled = False
    try:
        subprocess.check_call(_sudo + ["timedatectl", "set-ntp", "false"],
                              stderr=subprocess.DEVNULL)
        _ntp_disabled = True
        subprocess.check_call(_sudo + ["timedatectl", "set-time", date_time_str])
        logger.info("[set_date_time] System time set to %s via timedatectl", date_time_str)
        return
    except Exception:
        pass
    finally:
        if _ntp_disabled:
            try:
                subprocess.check_call(_sudo + ["timedatectl", "set-ntp", "true"])
            except Exception as e:
                logger.warning("[set_date_time] Could not re-enable NTP: %s", e)

    # Fallback: date -s (no systemd needed — works in Docker with root)
    try:
        subprocess.check_call(_sudo + ["date", "-s", date_time_str])
        logger.info("[set_date_time] System time set to %s via date -s", date_time_str)
    except Exception as e:
        logger.error("[set_date_time] Failed to set time to %s: %s", date_time_str, e)


def panelSlno():
    panel_sl_no_db = DeviceSerialNoInfoDB()

    # Retrieve parameters. If we want to use "get_parameter" function, then use below lines
    #panel = panel_sl_no_db.get_parameter('panel_number')  
    #batch = panel_sl_no_db.get_parameter('batch_number')
    
    # Get both panel and batch in one call
    panel, batch = panel_sl_no_db.fetch_device_info()

    log_data = {
        "panel_sl_no": [
            {
                "Serial_No": panel,
                "Batch_No": batch
            }
        ]
    }

    try:
        sendData2TB(log_data)
    except Exception as e:
        print("Failed to send serial number data:", e)
        logger.error("Failed to send serial number data:", e)


def Versionno():
   
    log_data = {
        "SHealth_fw_ver": "V-3.0"
    }

  
    try:
        print("VERSION")
        operator = cavli_database.get_OperatorNumber()
        print(operator)
        sendData2TB(log_data)
    except Exception as e:
        print("Failed to send version number data:", e)


def network_status():
    
    global statusbox_network
    global is_valid_network_available
    
    cavli_database.get_service_provider()

    statusbox_network = cavli_database.get_service_provider()
    
    if statusbox_network != "NA":
        #shiftRegister4Buffers = shiftRegister4Buffers | muxSelectionAndLED['NETWORK_LED']

        if is_valid_network_available == False:   # Only if it was previously False
            is_valid_network_available = True     # Mark it as now available
            sendData2TB("network")                # Sent only once when it becomes valid
        else:
            if is_valid_network_available == True:
                is_valid_network_available = False 
                sendData2TB("network_disconnect")     # Sent every time it goes from valid to invalid


if __name__ == '__main__':

    Adafruit_CharLCD()
    lcd.message("    Slink ON    ")
    lcd.message("\n")
    lcd.message("     Wait..      ")
    ds1307 = None
    try:
        ds1307 = SDL_DS1307.SDL_DS1307(1, 0x68)
        ds1307.write_now()
    except ValueError:
        logger.warning("[startup] RTC ValueError during hardware init")
    except IOError:
        logger.warning("[startup] RTC IOError during hardware init")

    # Inject ds1307 into panel_telemetry (msg_queue_buffer injected later after creation)
    try:
        from panel_telemetry import set_ds1307 as _set_ds1307
        _set_ds1307(ds1307)
    except Exception:
        pass


    try:        
        rtcYear = ds1307._read_year()
    except IOError:
        rtcYear = 0
    except ValueError:
        rtcYear = 0
    
    try:
        rtcMonth = ds1307._read_month()
    except IOError:
        rtcMonth = 0
    except ValueError:
        rtcMonth = 0

    try:
        rtcDate = ds1307._read_date()
    except IOError: 
        rtcDate = 0
    except ValueError:
        rtcDate = 0

    try:
        rtcHour = ds1307._read_hours()
    except IOError: 
        rtcHour = 0
    except ValueError:
        rtcHour = 0
        
    try:
        rtcMinute = ds1307._read_minutes()
        gTemp1 = rtcMinute
    except IOError:
        rtcMinute = 0
    except ValueError:
        rtcMinute = 0
        
    try:
        rtcSecound = ds1307._read_seconds()
    except IOError:
        rtcSecound = 0
    except ValueError:
        rtcSecound = 0


    rtcYear_t = rtcYear
    rtcYear_t += 2000    #To convert this 2-digit year into a 4-digit year, this line adds 2000 to rtcYear_t
    set_date_time(rtcYear_t,rtcMonth,rtcDate,rtcHour,rtcMinute,rtcSecound)

    shift_registers = [shiftRegister1Buffers, shiftRegister2Buffers, shiftRegister3Buffers, shiftRegister4Buffers]
    clear_value = shiftRegSet['CLEAR']

    for reg in shift_registers:
        reg |= clear_value

    shiftRegister1Buffers |= shiftRegSet['CLEAR']
    shiftRegister2Buffers |= shiftRegSet['CLEAR']
    shiftRegister3Buffers |= shiftRegSet['CLEAR']
    shiftRegister4Buffers |= shiftRegSet['CLEAR']

    shiftRegister1Buffers = shiftRegister1Buffers | relayBuzzer['LCD_BACK_ON']
    shiftRegister1Buffers = shiftRegister1Buffers | relayBuzzer['RELAY_1']
    #lcd.message("    Slink PWR ON  \n   ")
    sr.ssrWrite_4( shiftRegister4Buffers, shiftRegister3Buffers, shiftRegister2Buffers, shiftRegister1Buffers )

    msg_queue_buffer = MsgQueueBuffer(10000)  # Create a message queue buffer of size 5

    # Inject msg_queue_buffer now that it exists — sendData2TB() uses it
    from panel_telemetry import set_msg_queue_buffer as _set_mqb
    _set_mqb(msg_queue_buffer)

    # Run deferred schema migrations now that startup is underway
    run_all_migrations()
    verify_all_databases()

    system_settings_db = SystemSettingsDB()
    # Add elements
    # Force setup_mode to 'disabled' on every boot — ensures generateReportMsg()
    # fires correctly regardless of what value was left from a previous config session.
    # If a previous session left setup_mode='enabled', zone scan events would be
    # silently blocked. update_element overwrites unconditionally.
    system_settings_db.update_element("setup_mode", "disabled")
    system_settings_db.add_element("reset_to_default", "false")

    createDatabase()

    db_handler = DatabaseHandler()
    main_program = MainProgram(db_handler)

    # Inject into panel_telemetry so subprocess sender functions can use them
    from panel_telemetry import (set_main_program as _set_mp,
                                  set_db_handler   as _set_dbh)
    _set_mp(main_program)
    _set_dbh(db_handler)

    db_file = "/home/pi/Test3/network_settings.db"
    network_settings = NetworkSettings(db_file)

    # Inject network_settings into panel_telemetry for NetworkSettingsInit()
    from panel_telemetry import set_network_settings as _set_ns
    _set_ns(network_settings)

    # Add or update network settings
    #network_settings.update_setting("preferred_dns_server", "8.8.8.8")
    #network_settings.update_setting("alternate_dns_server", "8.8.4.4")
    #network_settings.update_setting("reset_to_dhcp", "True")

#    getNetowkStatus()

    network_info = NetworkInfo()

    NetworkSettingsInit()

    readBranchName()
    brandNameRead()
    rtcCheck()    

    zoneSettingsFileRW('read')
    powerZoneSettingsFileRW('read')

    cavli_database = CavliRunningStatusDatabase()
    cavli_database.update_modem_status("Ready")
    cavli_database.display_modem_status()

    # ── Location manager ──────────────────────────────────────────────────────
    # Sends India default (20.5937, 78.9629) to TB immediately — dashboard
    # never blank. Retries real GPS: 5x every 15min at startup, then every
    # 12hr forever. Once real GPS confirmed: sends every 12hr (twice a day).
    # SerialCommunication.py keeps cavli_database updated — no conflict.
    def _send_latlon_to_tb(lat, lon, is_default=False):
        payload = {"lat": lat, "lon": lon}
        if is_default:
            payload["lat_lon_default"] = True
        msg_queue_buffer.add(json.dumps(payload))

    location_manager.start(cavli_database, _send_latlon_to_tb)

    # ── IMEI manager ──────────────────────────────────────────────────────────
    # Sends IMEI immediately at startup, then every 12hr (twice a day).
    # Replaces the logTypeSysParam==12 direct call in scheduleSystemStatusUpload.
    def _send_imei_to_tb():
        send_imei_id(cavli_database.get_IMEI())

    imei_manager.start(_send_imei_to_tb)

    reset_to_default_value = system_settings_db.retrieve_element("reset_to_default")
    if reset_to_default_value == "true":
        resetToDefault()

    controller = ProcessController()
    
    controller_db_manager = ControllerDatabaseManager()
    controller_db_manager.create_table()  # ensure parameters table exists
   
   # lcd.message("     DEXTER     ")
   # lcd.message("\n")
   # lcd.message("    Booting...  ")
    def boot_dots(duration=100):
        global lcd_bar_running
        start_time = time.monotonic()
        dot_count = 0

        lcd.setCursor(0, 0)
        lcd.message(" SLink  Loading ")

        while lcd_bar_running and (time.monotonic() - start_time) < duration:
            elapsed = int(time.monotonic() - start_time)
            remaining = int(duration - elapsed)

            dots = '.' * ((dot_count % 3) + 1)  # 1 to 4 dots
            second_line = f"    {remaining:03d} SEC {dots}".ljust(16)

            lcd.setCursor(0, 1)  # Only second line
            lcd.message(second_line)

            dot_count += 1
            time.sleep(0.5)

        lcd.clear()
        lcd.message("   Slink Ready  \n")
        time.sleep(0.5)
        #lcd.message("   Boot done!   ")


    lcd.clear()
    # Start LCD boot bar in background
    lcd_bar_running = True
    lcd_thread = threading.Thread(target=boot_dots, args=(100,))

    lcd_thread.start()
    
    #time.sleep(30.0)
    shiftRegister1Buffers = shiftRegister1Buffers & ~(relayBuzzer['RELAY_1'])
    sr.ssrWrite_4( shiftRegister4Buffers, shiftRegister3Buffers, shiftRegister2Buffers, shiftRegister1Buffers ) 
    
    time.sleep(1.0)
    
    set_db_location("/home/pi/Test3/active_integration.db")
    initialize_active_integration_database()

    # Clear stale pending rows from previous session before inserting new events.
    # Keeps zone hardware events (alarms, door events etc.) but discards
    # heartbeats, system_on, NA and other startup/periodic data from old sessions.
    _stale = db_handler.startup_cleanup()
    if _stale:
        logger.info("[startup] Discarded %d stale non-zone payloads from previous session", _stale)

    sendData2TB("NA")
    logger.info("Mainicode_nitialized.")
    zoneScanInit(shiftRegister4Buffers, shiftRegister3Buffers, shiftRegister2Buffers, shiftRegister1Buffers)
    lcd_bar_running = False
    lcd_thread.join()
    
    lcd.clear()
    #boot_progress_seconds(duration=10, lcd_width=16)
    
    # System status is sent in STARTUP-FIX block below (after system_on)
    
    counter = Counter(180) # Low Battery Data Sending Counter
    dataBuffcounter = Counter(70) # Data Buff Sending Counter #Issue with Ethernet data sending
    #dataBuffcounter = Counter(150) # Data Buff Sending Counter
    dataBuffcounter.start_counter()

    modem_config_db = ModemConfigDatabase()

    # DB-MIG: migrate any plaintext device passwords in device_config.db
    # Safe to run every startup — already-encrypted rows are skipped.
    try:
        import device_parameters_module as _dpm_mig
        _dpm_mig.migrate_plaintext_passwords()
    except Exception as _mig_e:
        logger.error("[migrate_plaintext_passwords] %s", _mig_e)

    # CRED-GATE: load secret key from /etc/dexter/cred_auth.key
    # One-time permission setup (run once on RPi):
    #   sudo chown root:pi /etc/dexter/cred_auth.key
    #   sudo chmod 640     /etc/dexter/cred_auth.key
    _CRED_KEY_PATH = "/etc/dexter/cred_auth.key"
    try:
        with open(_CRED_KEY_PATH) as _kf:
            credential_auth.set_key(_kf.read().strip())
        logger.info("[credential_auth] Key loaded from %s", _CRED_KEY_PATH)
    except FileNotFoundError:
        logger.warning("[credential_auth] Key not found at %s -- "
                       "create: python3 -c \"import secrets; "
                       "print(secrets.token_hex(32))\" | "
                       "sudo tee /etc/dexter/cred_auth.key && "
                       "sudo chown root:pi /etc/dexter/cred_auth.key && "
                       "sudo chmod 640 /etc/dexter/cred_auth.key",
                       _CRED_KEY_PATH)
    except PermissionError:
        logger.error("[credential_auth] Permission denied reading %s -- "
                     "fix: sudo chown root:pi %s && sudo chmod 640 %s",
                     _CRED_KEY_PATH, _CRED_KEY_PATH, _CRED_KEY_PATH)
    except Exception as _ke:
        logger.error("[credential_auth] Key load error: %s", _ke)

    _db_network_type = str(modem_config_db.get_parameter('network_type'))
    if _db_network_type == 'gsm' and _eth0_has_connectivity():
        logger.info("[startup] eth0 has internet — overriding stale network_type='gsm' → 'ethernet'")
        modem_config_db.update_parameter('network_type', 'ethernet')
        _db_network_type = 'ethernet'

    if _db_network_type == 'ethernet':
        network_type = 1
    elif _db_network_type == 'gsm':
        network_type = 2

    if network_type == 1:
        _ft = threading.Thread(target=_run_failover_monitor, daemon=True, name="failover-monitor")
        _ft.start()
        logger.info("[failover] Auto-failover monitor started (eth0 → GSM on connectivity loss)")

    power_zone_active_device_counter = PowerZoneActiveDeviceCounter()

    # HB-01: initialise heartbeat manager
    hb_manager = HeartbeatManager(
        send_fn                  = sendData2TB,
        raw_send_fn              = lambda d: msg_queue_buffer.add(json.dumps(d)),
        device_counter           = power_zone_active_device_counter,
        power_zone_settings      = powerZoneSettings,
        get_active_integration_fn= get_active_integration,
        check_bacs_integration_fn= lambda: logical_params_module.get_parameter("active_integration_hikvision_biometric"),
        check_hikvision_status_fn= check_hikvision_status,
        check_hikvision_nvr_fn   = check_hikvision_nvr,
        check_dahua_nvr_fn       = check_dahua_nvr,
        check_cp_plus_nvr_fn     = check_cp_plus_nvr,
        check_texecom_bas_fn     = check_texecom_bas,
        check_amc_intg_fn        = lambda: logical_params_module.get_parameter("active_integration_amc_bas"),
        check_amc_bas_fn         = check_amc_bas,  # imported from amc_integration — reads in-memory state
    )


    power_zone_active_device_counter.update_device('BAS', False)
    power_zone_active_device_counter.update_device('FAS', False)
    power_zone_active_device_counter.update_device('TIME_LOCK', False)
    power_zone_active_device_counter.update_device('BACS', False)
    power_zone_active_device_counter.update_device('IAS', False)
    power_zone_active_device_counter.update_device('CCTV', False)

    power_zone_active_device_counter.update_device('BAS', True)
    power_zone_active_device_counter.update_device('FAS', True)
    power_zone_active_device_counter.update_device('TIME_LOCK', True)
    power_zone_active_device_counter.update_device('BACS', True)
    power_zone_active_device_counter.update_device('IAS', True)
    power_zone_active_device_counter.update_device('CCTV', True)    


    # STARTUP-FIX: send panel startup telemetry immediately on boot
    # These bypass the ACTIVE-INTEGRATION gate — they are panel events,
    # not NVR events, and must always reach ThingsBoard on startup.

    # 1.
    # system_on — spec format: {"log_type":"system_on","zone_no":null,"date":"DD:MM:YY","time":"HH:MM"}
    _s_date = (str(ds1307._read_date()).zfill(2)  + ":" +
               str(ds1307._read_month()).zfill(2) + ":" +
               str(ds1307._read_year()).zfill(2))
    _s_time = (str(ds1307._read_hours()).zfill(2) + ":" +
               str(ds1307._read_minutes()).zfill(2))
    msg_queue_buffer.add('{"log_type":"system_on","zone_no":null,"date":"' + _s_date + '","time":"' + _s_time + '"}' )

    # battery_low_restore — sent unconditionally at every startup.
    # When the panel shuts down due to low battery (battery_low → power_off),
    # it restarts when power/battery recovers. This single send tells the
    # dashboard the panel is back and battery is restored.
    msg_queue_buffer.add('{"log_type":"battery_low_restore","zone_no":null,"date":"' + _s_date + '","time":"' + _s_time + '"}' )

    # 2. system status — always send
    statusbox_network = cavli_database.get_service_provider()
    statusbox_no_of_connected_device = calculate_zones_on()
    sendData2TBSystemStatus(
        "true", "true",
        statusbox_mains_on, statusbox_battery_reverse,
        statusbox_battery_low, statusbox_sos_status,
        statusbox_network, statusbox_no_of_connected_device
    )

    # 3. mains_on or battery_on — spec format
    if statusbox_mains_on == "true":
        msg_queue_buffer.add('{"log_type":"mains_on","zone_no":null,"date":"' + _s_date + '","time":"' + _s_time + '"}' )
    else:
        msg_queue_buffer.add('{"log_type":"battery_on","zone_no":null,"date":"' + _s_date + '","time":"' + _s_time + '"}' )

    # HB-01: send each connected device heartbeat one-by-one on boot
    hb_manager.send_startup_sequence()

    init_db()  # Run this once to initialize the SQLite DB
    
    returnToDisplayScan()
    
    panelSlno()
    Versionno()

    send_tailscale_info()

    while True:

        if toggleBit1Sec == 1:
            shiftRegister3Buffers = shiftRegister3Buffers | frontPanelLED2['SYSTEM_HEALTHY_LED']
        else:
            shiftRegister3Buffers  = shiftRegister3Buffers  & ~(frontPanelLED2['SYSTEM_HEALTHY_LED'])

        realTimeClock()
        mainStateMachine()
        watchdog.reset()  # Reset watchdog after mainStateMachine
        _sd_notify_watchdog()  # feed systemd WatchdogSec=1800 countdown
        tickTimer()
        
        zoneScan()

        sr.ssrWrite_4( (shiftRegister4Buffers | muxSelection), shiftRegister3Buffers, shiftRegister2Buffers, shiftRegister1Buffers )        

        time.sleep(0.01)  # 10ms mux settling time — lets analog mux stabilise
                          # before GPIO read in muxSelectionZone1().
                          # Without this, transient glitches on mux input lines
                          # cause false state changes and repeated zone events.

        muxSelectionZone1()
       
        digitalInput()

        if dataBuffcounter.increment():

            dataBuffcounter.check_reset_counter()

            try:
                # Simulate adding elements to the queue
                controller.execute_process(network_type)
            except sqlite3.Error as e:
                print("An error occurred: {}".format(e))
                logger.error("An error occurred: {}".format(e))

        
        outputShiftRegLEDDisplay()

        # Advance in-progress RELAY_1 power-cycle phases (non-blocking)
        if _relay1_reset_in_progress:
            reset_communicator_relay()

        checkLithiumIonBatteryVoltage(controller_db_manager.get_lithium_ion_bat_volt_sense())

        scheduleSystemStatusUpload()
        
        if tick3MinTimer1 == 1:
            tick3MinTimer1 = 0
            Adafruit_CharLCD()

        if tick10Min_1 == 1:
            tick10Min_1 = 0
            reset_communicator_relay()   # RELAY_1 power-cycle if modem stuck (every 10 min)
