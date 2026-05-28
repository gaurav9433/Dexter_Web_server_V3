#!/usr/bin/env python3
#
# Decoder for Texecom Connect API/Protocol
#
# Copyright (C) 2018 Joseph Heenan
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

#Copyright (C) 2025 Souvik Saha


from __future__ import absolute_import, division, print_function

import socket
import subprocess
import time
import datetime
import os
import sys
import re

import crcmod
import hexdump

from socket import error as SocketError

import json

import schedule
from scheduler_utils import get_jitter_sec
import threading

# TS-01: Lock protecting globals shared between event_loop and scheduler threads
_state_lock = threading.Lock()

import logging
from logging.handlers import RotatingFileHandler  

import device_parameters_module

import logical_params_module

logical_params_module.initialize_database()

from buffer_manager import insert_json_to_db

# ---------------- EVENT CORRELATION BUFFER ----------------
EVENT_CONTEXT = {
    "zones": set(),
    "zone_states": {},      # zone_number → Active / Restore
    "areas": set(),
    "area_states": {},      # area_number → in alarm / Restore
    "last_update": 0.0
}

EVENT_CONTEXT_TIMEOUT = 2.0   # seconds


# ---------------- EVENT CLASSIFICATION ----------------
INCIDENT_EVENTS = {
    "Entry/Exit 1",
    "Entry/Exit 2",
    "Entry Started",
    "Interior",
    "Perimeter",
    "24hr Audible",
    "24hr Silent",
    "Audible PA",
    "Silent PA",
    "Fire Alarm",
    "Medical",
    "24Hr Gas Alarm",
    "Auxiliary Alarm",
    "24hr Tamper Alarm",
    "Exit Terminator",
    "Keyswitch - Momentary",
    "Keyswitch - Latching",
    "Security Key",
    "Omit Key",
    "Custom Alarm",
    "Confirmed PA Audible",
    "Confirmed PA Silent"
}

POWER_EVENTS = {
    "AC Fail",
    "Low Battery",
    "System Power Up",
    "PSU AC Fail",
    "PSU Battery Fail",
    "Battery Charger Fault"
}

IGNORE_EVENTS = {
    "Bell Active",
    "Bell Tamper"
}

OMIT_CONTEXT = {    # Track last Omit Key press
    "active": False,
    "timestamp": None
}

ZONE_TYPE_EVENTS = {
    "Interior",
    "Perimeter",
    "24hr Audible",
    "24hr Silent",
    "Fire Alarm",
    "Medical",
    "24Hr Gas Alarm",
    "Auxiliary Alarm",
    "Confirmed PA Audible",
    "Confirmed PA Silent",
    "Audible PA",
    "Auxiliary Alarm",
    "24hr Tamper Alarm"
}


PENDING_INCIDENT = None
INCIDENT_DELAY = 0.5  # seconds (500 ms)

texeNetZoneStatus_1 = [0]*64  # 1-64
texeNetZoneStatus_2 = [0]*64  # 65-128
texeNetZoneStatus_3 = [0]*64  # 129-192
texeNetZoneStatus_4 = [0]*64  # 193-256
texeNetZoneStatus_5 = [0]*64  # 257-320
texeNetZoneStatus_6 = [0]*64  # 321-384
texeNetZoneStatus_7 = [0]*64  # 385-448
texeNetZoneStatus_8 = [0]*64  # 449-512


BATTERY_ALARM_ACTIVE = False
BATTERY_CONFIRMED = False
BATTERY_VOLTAGE_HISTORY = []
BATTERY_HISTORY_LEN = 3


PANEL_POWER_STATE = {
    "mains": None,        # "ON" / "OFF"
    "battery": None,      # "ON" / "LOW"
    "panel": "UNKNOWN"
}

LAST_HEARTBEAT_TIME = time.time()

PANEL_SEEN_ONCE = False        # Has protocol ever connected?
STARTUP_OFF_SENT = False       # Startup OFF latch

TIME_SYNC_STATE = {
    "last_drift_alert": False
}

# PATH-01: Centralised path constants
BASE_DIR       = "/home/pi/Test3"
LOG_FILE       = f"{BASE_DIR}/texecom.txt"
CONN_STAT_FILE = f"{BASE_DIR}/texecomConnStat.txt"

logger = logging.getLogger("texecom")
logger.setLevel(logging.INFO)

handler = RotatingFileHandler(
    LOG_FILE,
    maxBytes=5 * 1024 * 1024,   # 5 MB per file
    backupCount=5              # keep last 5 files
)

formatter = logging.Formatter(
    "%(asctime)s : %(levelname)s : %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

handler.setFormatter(formatter)
logger.addHandler(handler)

# Prevent duplicate logs if imported elsewhere
logger.propagate = False



def texeNetZoneStatus(zone, status):

    ACTIVE = 1
    SECURE = 0
    
    if zone > 0 and zone < 65:
        OFFSET = 1
        if status == 'secure':
            texeNetZoneStatus_1[zone-OFFSET] =  SECURE
        elif status == 'active':
            texeNetZoneStatus_1[zone-OFFSET] =  ACTIVE

#        try:
#            with open("/home/pi/Test3/texeNetZoneStatus_1.txt","w") as log:
#                for x in range(0,64):
#                    log.write(str(texeNetZoneStatus_1[x])+"\n")
#        except (ValueError, IOError):
#            pass

    if zone > 64 and zone < 129:
        OFFSET = 64 + 1
        if status == 'secure':
            texeNetZoneStatus_2[zone-OFFSET] =  SECURE
        elif status == 'active':
            texeNetZoneStatus_2[zone-OFFSET] =  ACTIVE

#        try:
#            with open("/home/pi/Test3/texeNetZoneStatus_2.txt","w") as log:
#                for x in range(0,63):
#                    log.write(str(texeNetZoneStatus_2[x])+"\n")
#        except (ValueError, IOError):
#            pass

    if zone > 128 and zone < 193:
        OFFSET = 128 + 1
        if status == 'secure':
            texeNetZoneStatus_3[zone-OFFSET] =  SECURE
        elif status == 'active':
            texeNetZoneStatus_3[zone-OFFSET] =  ACTIVE

#        try:
#            with open("/home/pi/Test3/texeNetZoneStatus_3.txt","w") as log:
#                for x in range(0,63):
#                    log.write(str(texeNetZoneStatus_3[x])+"\n")
#        except (ValueError, IOError):
#            pass

    if zone > 192 and zone < 257:
        OFFSET = 192 + 1
        if status == 'secure':
            texeNetZoneStatus_4[zone-OFFSET] =  SECURE
        elif status == 'active':
            texeNetZoneStatus_4[zone-OFFSET] =  ACTIVE

#        try:
#            with open("/home/pi/Test3/texeNetZoneStatus_4.txt","w") as log:
#                for x in range(0,63):
#                    log.write(str(texeNetZoneStatus_4[x])+"\n")
#        except (ValueError, IOError):
#            pass
        
    if zone > 256 and zone < 321:
        OFFSET = 256 + 1
        if status == 'secure':
            texeNetZoneStatus_5[zone-OFFSET] =  SECURE
        elif status == 'active':
            texeNetZoneStatus_5[zone-OFFSET] =  ACTIVE

#        try:
#            with open("/home/pi/Test3/texeNetZoneStatus_5.txt","w") as log:
#                for x in range(0,63):
#                    log.write(str(texeNetZoneStatus_5[x])+"\n")
#        except (ValueError, IOError):
#            pass

    if zone > 320 and zone < 385:
        OFFSET = 320 + 1
        if status == 'secure':
            texeNetZoneStatus_6[zone-OFFSET] =  SECURE
        elif status == 'active':
            texeNetZoneStatus_6[zone-OFFSET] =  ACTIVE

#        try:
#            with open("/home/pi/Test3/texeNetZoneStatus_6.txt","w") as log:
#                for x in range(0,63):
#                    log.write(str(texeNetZoneStatus_6[x])+"\n")
#        except (ValueError, IOError):
#            pass

    if zone > 384 and zone < 449:
        OFFSET = 384 + 1
        if status == 'secure':
            texeNetZoneStatus_7[zone-OFFSET] =  SECURE
        elif status == 'active':
            texeNetZoneStatus_7[zone-OFFSET] =  ACTIVE
#        try:
#            with open("/home/pi/Test3/texeNetZoneStatus_7.txt","w") as log:
#                for x in range(0,63):
#                    log.write(str(texeNetZoneStatus_7[x])+"\n")
#        except (ValueError, IOError):
#            pass

    if zone > 448 and zone < 513:
        OFFSET = 448 + 1
        if status == 'secure':
            texeNetZoneStatus_8[zone-OFFSET] =  SECURE
        elif status == 'active':
            texeNetZoneStatus_8[zone-OFFSET] =  ACTIVE

#        try:
#            with open("/home/pi/Test3/texeNetZoneStatus_8.txt","w") as log:
#                for x in range(0,63):
#                    log.write(str(texeNetZoneStatus_8[x])+"\n")
#        except (ValueError, IOError):
#            pass

class User(object):
    def __init__(self):
        self.passcode = None
        self.tag = None

    def valid(self):
        return self.passcode != '' or self.tag != ''

class Area(object):
    def __init__(self):
        self.name = "unknown"
        self.state = "unknown"

class Zone(object):
    """Information about a zone and it's current state
    """
    def __init__(self, zone_number):
        self.number = zone_number
        self.text = ""
        self.__active = False
        self.active_func = None
        self.active_since = None
        self.last_active = None
        self.__smoothed_active = False
        self.smoothed_active_delay = 30 # how long 'smoothed_active' will stay after last activation
        self.smoothed_active_func = None
        self.smoothed_active_since = None
        self.smoothed_last_active = None
        pass

    def update(self):
        if self.smoothed_active and not self.active:
            time_since_last_active = time.time() - self.last_active
            if time_since_last_active > self.smoothed_active_delay:
                self.smoothed_active = False
        if self.smoothed_active and self.smoothed_active_func is not None:
            # Run the handler on every update whilst 'smoothed active' is true
            self.smoothed_active_func(self, True, True)
        if self.active and self.active_func is not None:
            self.active_func(self, True, True)


    @property
    def smoothed_active(self):
        return self.__smoothed_active

    @smoothed_active.setter
    def smoothed_active(self, smoothed_active):
        if smoothed_active == self.__smoothed_active:
            return
        if self.smoothed_active_func is not None:
            self.smoothed_active_func(self, self.__smoothed_active, smoothed_active)
        self.__smoothed_active = smoothed_active
        if smoothed_active:
            self.smoothed_active_since = time.time()
        else:
            self.smoothed_active_since = None
            self.smoothed_last_active = time.time()


    @property
    def active(self):
        return self.__active

    @active.setter
    def active(self, active):
        if active == self.__active:
            return
        if self.active_func is not None:
            self.active_func(self, self.__active, active)
        self.__active = active
        if active:
            self.active_since = time.time()
            self.smoothed_active = True
        else:
            self.last_active = time.time()
            self.active_since = None

class TexecomConnect(object):
    LENGTH_HEADER = 4
    HEADER_START = ord('t')
    HEADER_TYPE_COMMAND = ord('C')
    HEADER_TYPE_RESPONSE = ord('R')
    HEADER_TYPE_MESSAGE = ord('M')  # unsolicited message

    CMD_LOGIN = 1
    CMD_GETZONEDETAILS = 3
    CMD_GETLCDDISPLAY = 13
    CMD_GETLOGPOINTER = 15
    CMD_GETPANELIDENTIFICATION = 22
    CMD_GETDATETIME = 23
    CMD_GETSYSTEMPOWER = 25
    CMD_GETUSER = 27
    CMD_GETAREADETAILS = 35
    CMD_SETEVENTMESSAGES = 37
    
    MAX_TIME_DRIFT_SECONDS = 120   # 2 minutes

    CMD_TIMEOUT = 2
    CMD_RETRIES = 3

    ZONETYPE_UNUSED = 0

    CMD_RESPONSE_ACK = 0x06
    CMD_RESPONSE_NAK = 0x15

    MSG_DEBUG = 0
    MSG_ZONEEVENT = 1
    MSG_AREAEVENT = 2
    MSG_OUTPUTEVENT = 3
    MSG_USEREVENT = 4
    MSG_LOGEVENT = 5

    zone_types = {}
    zone_types[1] = "Entry/Exit 1"
    zone_types[2] = "Entry/Exit 2"
    zone_types[3] = "Interior"
    zone_types[4] = "Perimeter"
    zone_types[5] = "24hr Audible"
    zone_types[6] = "24hr Silent"
    zone_types[7] = "Audible PA"
    zone_types[8] = "Silent PA"
    zone_types[9] = "Fire Alarm"
    zone_types[10] = "Medical"
    zone_types[11] = "24Hr Gas Alarm"
    zone_types[12] = "Auxiliary Alarm"
    zone_types[13] = "24hr Tamper Alarm"
    zone_types[14] = "Exit Terminator"
    zone_types[15] = "Keyswitch - Momentary"
    zone_types[16] = "Keyswitch - Latching"
    zone_types[17] = "Security Key"
    zone_types[18] = "Omit Key"
    zone_types[19] = "Custom Alarm"
    zone_types[20] = "Confirmed PA Audible"
    zone_types[21] = "Confirmed PA Silent"

    log_event_types = {}
    log_event_types[1] = "Entry/Exit 1"
    log_event_types[2] = "Entry/Exit 2"
    log_event_types[3] = "Interior"
    log_event_types[4] = "Perimeter"
    log_event_types[5] = "24hr Audible"
    log_event_types[6] = "24hr Silent"
    log_event_types[7] = "Audible PA"
    log_event_types[8] = "Silent PA"
    log_event_types[9] = "Fire Alarm"
    log_event_types[10] = "Medical"
    log_event_types[11] = "24Hr Gas Alarm"
    log_event_types[12] = "Auxiliary Alarm"
    log_event_types[13] = "24hr Tamper Alarm"
    log_event_types[14] = "Exit Terminator"
    log_event_types[15] = "Keyswitch - Momentary"
    log_event_types[16] = "Keyswitch - Latching"
    log_event_types[17] = "Security Key"
    log_event_types[18] = "Omit Key"
    log_event_types[19] = "Custom Alarm"
    log_event_types[20] = "Confirmed PA Audible"
    log_event_types[21] = "Confirmed PA Audible"
    log_event_types[22] = "Keypad Medical"
    log_event_types[23] = "Keypad Fire"
    log_event_types[24] = "Keypad Audible PA"
    log_event_types[25] = "Keypad Silent PA"
    log_event_types[26] = "Duress Code Alarm"
    log_event_types[27] = "Alarm Active"
    log_event_types[28] = "Bell Active"
    log_event_types[29] = "Re-arm"
    log_event_types[30] = "Verified Cross Zone Alarm"
    log_event_types[31] = "User Code"
    log_event_types[32] = "Exit Started"
    log_event_types[33] = "Exit Error (Arming Failed)"
    log_event_types[34] = "Entry Started"
    log_event_types[35] = "Part Arm Suite"
    log_event_types[36] = "Armed with Line Fault"
    log_event_types[37] = "Open/Close (Away Armed)"
    log_event_types[38] = "Part Armed"
    log_event_types[39] = "Auto Open/Close"
    log_event_types[40] = "Auto Arm Deferred"
    log_event_types[41] = "Open After Alarm (Alarm Abort)"
    log_event_types[42] = "Remote Open/Close"
    log_event_types[43] = "Quick Arm"
    log_event_types[44] = "Recent Closing"
    log_event_types[45] = "Reset After Alarm"
    log_event_types[46] = "Power O/P Fault"
    log_event_types[47] = "AC Fail"
    log_event_types[48] = "Low Battery"
    log_event_types[49] = "System Power Up"
    log_event_types[50] = "Mains Over Voltage"
    log_event_types[51] = "Telephone Line Fault"
    log_event_types[52] = "Fail to Communicate"
    log_event_types[53] = "Download Start"
    log_event_types[54] = "Download End"
    log_event_types[55] = "Log Capacity Alert (80%)"
    log_event_types[56] = "Date Changed"
    log_event_types[57] = "Time Changed"
    log_event_types[58] = "Installer Programming Start"
    log_event_types[59] = "Installer Programming End"
    log_event_types[60] = "Panel Box Tamper"
    log_event_types[61] = "Bell Tamper"
    log_event_types[62] = "Auxiliary Tamper"
    log_event_types[63] = "Expander Tamper"
    log_event_types[64] = "Keypad Tamper"
    log_event_types[65] = "Expander Trouble (Network error)"
    log_event_types[66] = "Remote Keypad Trouble (Network error)"
    log_event_types[67] = "Fire Zone Tamper"
    log_event_types[68] = "Zone Tamper"
    log_event_types[69] = "Keypad Lockout"
    log_event_types[70] = "Code Tamper Alarm"
    log_event_types[71] = "Soak Test Alarm"
    log_event_types[72] = "Manual Test Transmission"
    log_event_types[73] = "Automatic Test Transmission"
    log_event_types[74] = "User Walk Test Start/End"
    log_event_types[75] = "NVM Defaults Loaded"
    log_event_types[76] = "First Knock"
    log_event_types[77] = "Door Access"
    log_event_types[78] = "Part Arm 1"
    log_event_types[79] = "Part Arm 2"
    log_event_types[80] = "Part Arm 3"
    log_event_types[81] = "Auto Arming Started"
    log_event_types[82] = "Confirmed Alarm"
    log_event_types[83] = "Prox Tag"
    log_event_types[84] = "Access Code Changed/Deleted"
    log_event_types[85] = "Arm Failed"
    log_event_types[86] = "Log Cleared"
    log_event_types[87] = "iD Loop Shorted"
    log_event_types[88] = "Communication Port"
    log_event_types[89] = "TAG System Exit (Batt. OK)"
    log_event_types[90] = "TAG System Exit (Batt. LOW)"
    log_event_types[91] = "TAG System Entry (Batt. OK)"
    log_event_types[92] = "TAG System Entry (Batt. LOW)"
    log_event_types[93] = "Microphone Activated"
    log_event_types[94] = "AV Cleared Down"
    log_event_types[95] = "Monitored Alarm"
    log_event_types[96] = "Expander Low Voltage"
    log_event_types[97] = "Supervision Fault"
    log_event_types[98] = "PA from Remote FOB"
    log_event_types[99] = "RF Device Low Battery"
    log_event_types[100] = "Site Data Changed"
    log_event_types[101] = "Radio Jamming"
    log_event_types[102] = "Test Call Passed"
    log_event_types[103] = "Test Call Failed"
    log_event_types[104] = "Zone Fault"
    log_event_types[105] = "Zone Masked"
    log_event_types[106] = "Faults Overridden"
    log_event_types[107] = "PSU AC Fail"
    log_event_types[108] = "PSU Battery Fail"
    log_event_types[109] = "PSU Low Output Fail"
    log_event_types[110] = "PSU Tamper"
    log_event_types[111] = "Door Access"
    log_event_types[112] = "CIE Reset"
    log_event_types[113] = "Remote Command"
    log_event_types[114] = "User Added"
    log_event_types[115] = "User Deleted"
    log_event_types[116] = "Confirmed PA"
    log_event_types[117] = "User Acknowledged"
    log_event_types[118] = "Power Unit Failure"
    log_event_types[119] = "Battery Charger Fault"
    log_event_types[120] = "Confirmed Intruder"
    log_event_types[121] = "GSM Tamper"
    log_event_types[122] = "Radio Config. Failure"

    log_event_group_type = {}
    log_event_group_type[0] = "Not Reported"
    log_event_group_type[1] = "Priority Alarm"
    log_event_group_type[2] = "Priority Alarm Restore"
    log_event_group_type[3] = "Alarm"
    log_event_group_type[4] = "Restore"
    log_event_group_type[5] = "Open"
    log_event_group_type[6] = "Close"
    log_event_group_type[7] = "Bypassed"
    log_event_group_type[8] = "Unbypassed"
    log_event_group_type[9] = "Maintenance Alarm"
    log_event_group_type[10] = "Maintenance Restore"
    log_event_group_type[11] = "Tamper Alarm"
    log_event_group_type[12] = "Tamper Restore"
    log_event_group_type[13] = "Test Start"
    log_event_group_type[14] = "Test End"
    log_event_group_type[15] = "Disarmed"
    log_event_group_type[16] = "Armed"
    log_event_group_type[17] = "Tested"
    log_event_group_type[18] = "Started"
    log_event_group_type[19] = "Ended"
    log_event_group_type[20] = "Fault"
    log_event_group_type[21] = "Omitted"
    log_event_group_type[22] = "Reinstated"
    log_event_group_type[23] = "Stopped"
    log_event_group_type[24] = "Start"
    log_event_group_type[25] = "Deleted"
    log_event_group_type[26] = "Active"
    log_event_group_type[27] = "Not Used"
    log_event_group_type[28] = "Changed"
    log_event_group_type[29] = "Low Battery"
    log_event_group_type[30] = "Radio"
    log_event_group_type[31] = "Deactivated"
    log_event_group_type[32] = "Added"
    log_event_group_type[33] = "Bad Action"
    log_event_group_type[34] = "PA Timer Reset"
    log_event_group_type[35] = "PA Zone Lockout"

    def __init__(self, host, port, udl_password, message_handler_func):
        self.host = host
        self.port = port
        self.udlpassword = udl_password
        self.crc8_func = crcmod.mkCrcFun(poly=0x185, rev=False, initCrc=0xff)
        self.nextseq = 0
        self.message_handler_func = message_handler_func
        self.print_network_traffic = False
        self.last_command_time = 0
        self.last_received_seq = -1
        self.last_sequence_int = -1
        self.last_command = None
        self.panelType = None
        self.firmwareVersion = None
        self.numberOfZones = -1
        self.zone = {}
        self.user = {}
        self.area = {}
        self.s = None
        # used to record which of our idle commands we last sent to the panel
        self.lastIdleCommand = 0
        # Set to true if the idle loop should reread the site data
        self.siteDataChanged = False
        self.time_synced_once = False

    @staticmethod
    def hexstr(s):
        """Convert a binary string into a hex representation suitable for logging payloads etc"""
        if s is None:
            return ""
        # s expected to be bytes-like
        return " ".join("{:02x}".format(b) for b in s)

    def connect(self):
        self.s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.s.settimeout(self.CMD_TIMEOUT)
        self.s.connect((self.host, self.port))
        # if we send the login message too fast the panel ignores it; texecom
        # recommend 500ms
        time.sleep(0.5)

    def getnextseq(self):
        if self.nextseq == 256:
            self.nextseq = 0
        nextseq = self.nextseq
        self.nextseq += 1
        return nextseq

    def closesocket(self):
        if self.s is not None:
            try:
                self.s.shutdown(socket.SHUT_RDWR)
            except socket.error:
                pass
            self.s.close()
            self.s = None

    def recvresponse(self):
        """Receive a response to a command. Automatically handles any
        messages that arrive first"""
        startTime = time.time()
        while True:
            if time.time() - startTime > self.CMD_TIMEOUT:
                # if we have had multiple event messages, we may get to the timeout time without the recv timing out
                raise socket.timeout
            assert self.last_command_time > 0
            time_since_last_command = time.time() - self.last_command_time
            if time_since_last_command > 30:
                # send any message to reset the panel's 60 second timeout
                if self.lastIdleCommand == 0:
                    result = self.get_date_time()
                    logger.info(f"Idle CMD get_date_time result: {result}")
#                    try:
#                        with open("/home/pi/Test3/texecom.txt","a") as log:
#                            log.write(str(result))
#                            log.write("\n")
#                    except Exception:
#                        pass
                elif self.lastIdleCommand == 1:
                    result = self.get_log_pointer()
                    logger.info(f"Idle CMD get_date_time result: {result}")
#                    try:
#                        with open("/home/pi/Test3/texecom.txt","a") as log:
#                            log.write(str(result))
#                            log.write("\n")
#                    except Exception:
#                        pass
                else:
                    result = self.get_system_power()
                    logger.info(f"Idle CMD get_date_time result: {result}")
#                    try:
#                        with open("/home/pi/Test3/texecom.txt","a") as log:
#                            log.write(str(result))
#                            log.write("\n")
#                    except Exception:
#                        pass
                self.lastIdleCommand += 1
                if self.lastIdleCommand == 3:
                    self.lastIdleCommand = 0
                if result is None:
                    self.log("idle command failed; closing socket")
                    self.closesocket()
                    logger.info("idle command failed; closing socket")
#                    try:
#                        with open("/home/pi/Test3/texecom.txt","a") as log:
#                            log.write(str("idle command failed; closing socket"))
#                            log.write("\n")
#                    except Exception:
#                        pass
                    return None
            
            header = self.s.recv(self.LENGTH_HEADER)
            
            if self.print_network_traffic:
                self.log("Received message header:")
                hexdump.hexdump(header)
            if header == b"+++":
                self.log("Panel has forcibly dropped connection, possibly due to inactivity")
                self.closesocket()
                return None
            if header == b"+++A":
                self.log("Panel is trying to hangup modem; probably connected too soon")
                self.closesocket()
                return None
            if len(header) == 0:
                self.log("Panel has closed connection")
                self.closesocket()
                return None
            if len(header) < self.LENGTH_HEADER:
                self.log("Header received from panel is too short, only {:d} bytes, ignoring - contents {}".format(
                    len(header), self.hexstr(header)))
                hexdump.hexdump(header)
                continue

            # header bytes as ints
            msg_start = header[0]
            msg_type = header[1]
            msg_length = header[2]
            msg_sequence = header[3]

            if msg_start != self.HEADER_START:
#                self.log("unexpected msg start: " + hex(msg_start))
                self.log(f"Unexpected msg start: {hex(msg_start)}")
                hexdump.hexdump(header)
                return None
            expected_len = msg_length - self.LENGTH_HEADER
            payload = self.s.recv(expected_len)
            if self.print_network_traffic:
                self.log("Received message payload:")
                hexdump.hexdump(payload)
            if len(payload) < expected_len:
                self.log(
                    "Ignoring message, payload shorter than expected - got {:d} bytes, expected {:d} - contents {}".format(
                        len(payload), expected_len, self.hexstr(payload)))
                hexdump.hexdump(header)
                hexdump.hexdump(payload)
                continue

            payload_bytes = payload[:-1]
            msg_crc = payload[-1]
            expected_crc = self.crc8_func(header + payload_bytes)
            if msg_crc != expected_crc:
#                self.log("crc: expected=" + str(expected_crc) + " actual=" + str(msg_crc))
                self.log(f"CRC error: expected={expected_crc} actual={msg_crc}")
                return None

            if msg_type == self.HEADER_TYPE_RESPONSE:
                if msg_sequence != self.last_sequence_int:
                    self.log(
                        "incorrect response seq: expected=" + str(self.last_sequence_int) + " actual=" + str(msg_sequence))
                    # recv again - either we receive the correct reply in the next packet, or we'll time out and retry the command
                    continue
            elif msg_type == self.HEADER_TYPE_MESSAGE:
                if self.last_received_seq != -1:
                    next_msg_seq = self.last_received_seq + 1
                    if next_msg_seq == 256:
                        next_msg_seq = 0
                    if msg_sequence == self.last_received_seq:
                        self.log("ignoring message, sequence number is the same as last message: expected=" + str(
                            next_msg_seq) + " actual=" + str(msg_sequence))
                        continue
                    if msg_sequence != next_msg_seq:
                        self.log("message seq incorrect - processing message anyway: expected=" + str(
                            next_msg_seq) + " actual=" + str(msg_sequence))
                        # process message anyway; perhaps we missed one or they arrived out of order
                self.last_received_seq = msg_sequence

            if msg_type == self.HEADER_TYPE_COMMAND:
                self.log("received command unexpectedly")
                return None
            elif msg_type == self.HEADER_TYPE_RESPONSE:
                return payload_bytes
            elif msg_type == self.HEADER_TYPE_MESSAGE:
                # FIXME: for "Site Data Changed" we should re-read the zone names etc - need to decode message
                # self.siteDataChanged = True
                self.message_handler_func(payload_bytes)

    def sendcommandbody(self, body):
        # body expected bytes
        self.last_sequence_int = self.getnextseq()
        header_prefix = bytes([self.HEADER_START, self.HEADER_TYPE_COMMAND, (len(body) + 5) & 0xFF, self.last_sequence_int])
        data_wo_crc = header_prefix + body
        crc_val = self.crc8_func(data_wo_crc)
        data = data_wo_crc + bytes([crc_val])
        if self.print_network_traffic:
            self.log("Sending command:")
            hexdump.hexdump(data)
        self.s.send(data)
        self.last_command = data

    def login(self):
#        response = self.sendcommand(self.CMD_LOGIN.to_bytes(1, 'little'), None)
        response = self.sendcommand(self.CMD_LOGIN, self.udlpassword)
        if response is None:
            self.log("sendcommand returned None for login")
            return False
        if len(response) == 1 and response[0] == self.CMD_RESPONSE_NAK:
            self.log("NAK response from panel")
            return False
        elif len(response) == 1 and response[0] != self.CMD_RESPONSE_ACK:
            self.log("unexpected ack payload: " + hex(response[0]))
            return False
        return True

    def set_event_messages(self):
        DEBUG_FLAG = 1
        ZONE_EVENT_FLAG = 1 << 1
        AREA_EVENT_FLAG = 1 << 2
        OUTPUT_EVENT_FLAG = 1 << 3
        USER_EVENT_FLAG = 1 << 4
        LOG_FLAG = 1 << 5
        events = ZONE_EVENT_FLAG | AREA_EVENT_FLAG | OUTPUT_EVENT_FLAG | USER_EVENT_FLAG | LOG_FLAG
        body = bytes([events & 0xff, (events >> 8) & 0xff])
        response = self.sendcommand(self.CMD_SETEVENTMESSAGES.to_bytes(1,'little'), body)
        if response is None:
            return False
        if len(response) == 1 and response[0] == self.CMD_RESPONSE_NAK:
            self.log("NAK response from panel")
            return False
        elif len(response) == 1 and response[0] != self.CMD_RESPONSE_ACK:
            self.log("unexpected ack payload: " + hex(response[0]))
            return False
        return True

    @staticmethod
    def log(string):
        
        logger.info(string) # NEW LOGGER (SAFE, ROTATING)
        
#        timestamp = time.strftime("%Y-%m-%d %X")
#        try:
#            with open("/home/pi/Test3/texecom.txt","a") as log:
#                log.write(str(timestamp))
#                log.write(" : ")
#                log.write(str(string))
#                log.write("\n")
#        except Exception:
#            pass

    def sendcommand(self, cmd, body):
        # cmd expected bytes
        if isinstance(cmd, int):
            cmd = cmd.to_bytes(1, 'little')
        if isinstance(body, str):
            body = body.encode('utf-8')
        
        if body is not None:
            body = cmd + body
        else:
            body = cmd
        self.sendcommandbody(body)
        self.last_command_time = time.time()
        retries = self.CMD_RETRIES
        response = None
        while retries > 0:
            retries -= 1
            try:
                response = self.recvresponse()
                break
            except socket.timeout:
                self.log("Timeout waiting for response, resending last command")
                # NB: sequence number will be the same as last attempt
                self.last_command_time = time.time()
                try:
                    self.s.send(self.last_command)
                except Exception as e:
                    logger.warning("[recvresponse] send retry failed: %s", e)
            except SocketError:
                pass
            except KeyboardInterrupt:
                pass

        self.last_command = None
        if response is None:
            return None

        # response is bytes
        commandid = response[0:1]  # bytes length 1
        payload = response[1:]
        if commandid != cmd:
            # check for login NAK condition
            if commandid == self.CMD_LOGIN.to_bytes(1,'little') and len(payload) > 0 and payload[0] == self.CMD_RESPONSE_NAK:
                self.log("Received 'Log on NAK' from panel - session has timed out and needs to be restarted")
                return None
            # log mismatch
            self.log("Got response for wrong command id: Expected " + hex(cmd[0]) + ", got " + hex(commandid[0]))
            self.log("Payload: " + self.hexstr(payload))
            return None
        return payload

    def get_date_time_1(self):
        datetimeresp = self.sendcommand(self.CMD_GETDATETIME.to_bytes(1,'little'), None)
        if datetimeresp is None:
            return None
        if len(datetimeresp) < 6:
            self.log("GETDATETIME: response too short")
            self.log("Payload: " + self.hexstr(datetimeresp))
            return None
        datetimeresp = bytearray(datetimeresp)
        datetimestr = '20{2:02d}-{1:02d}-{0:02d} {3:02d}:{4:02d}:{5:02d}'.format(*datetimeresp)
        paneltime = datetime.datetime(2000 + datetimeresp[2], datetimeresp[1], datetimeresp[0], *datetimeresp[3:])
        seconds = int((paneltime - datetime.datetime.now()).total_seconds())
        if seconds > 0:
            diff = " (panel is ahead by {:d} seconds)".format(seconds)
        else:
            diff = " (panel is behind by {:d} seconds)".format(-seconds)
        self.log("Panel date/time: " + datetimestr + diff)
        return datetimestr
        
    def get_date_time(self):
        datetimeresp = self.sendcommand(self.CMD_GETDATETIME.to_bytes(1,'little'), None)
        if datetimeresp is None or len(datetimeresp) < 6:
            return None

        datetimeresp = bytearray(datetimeresp)

        paneltime = datetime.datetime(
            2000 + datetimeresp[2],
            datetimeresp[1],
            datetimeresp[0],
            datetimeresp[3],
            datetimeresp[4],
            datetimeresp[5]
        )

        system_time = datetime.datetime.now()
        drift = (system_time - paneltime).total_seconds()

        self.log(f"Panel date/time: {paneltime} (drift {int(drift)} sec)")

#        if abs(drift) > self.MAX_TIME_DRIFT_SECONDS and not self.time_synced_once:
#            self.log("Panel time drift detected — syncing once")
#            if self.set_date_time():
#                self.time_synced_once = True
        if abs(drift) > self.MAX_TIME_DRIFT_SECONDS and not self.time_synced_once:
            self.log("Panel time drift detected — panel does not allow remote time set")
            self.time_synced_once = True

        return paneltime.strftime("%Y-%m-%d %H:%M:%S")


    def set_date_time(self):
        """
        Sync Texecom panel time with system time.
        Uses undocumented but functional datetime write.
        """
        now = datetime.datetime.now()

        body = bytes([
            now.day,
            now.month,
            now.year - 2000,
            now.hour,
            now.minute,
            now.second
        ])

        response = self.sendcommand(self.CMD_GETDATETIME.to_bytes(1, 'little'), body)

        if response is None:
            self.log("SETDATETIME failed (no response)")
            return False

        if len(response) == 1 and response[0] == self.CMD_RESPONSE_ACK:
            self.log("Panel date/time successfully updated")
            return True

        self.log("SETDATETIME unexpected response: " + self.hexstr(response))
        return False


    def get_lcd_display(self):
        lcddisplay = self.sendcommand(self.CMD_GETLCDDISPLAY.to_bytes(1,'little'), None)
        if lcddisplay is None:
            return None
        if len(lcddisplay) != 32:
            self.log("GETLCDDISPLAY: response wrong length")
            self.log("Payload: " + self.hexstr(lcddisplay))
            return None
        # decode bytes to string preserving bytes -> latin1
        try:
            display_text = lcddisplay.decode('latin1')
        except Exception:
            display_text = str(lcddisplay)
        self.log("Panel LCD display: " + display_text)
        return display_text

    def get_log_pointer(self):
        logpointerresp = self.sendcommand(self.CMD_GETLOGPOINTER.to_bytes(1,'little'), None)
        if logpointerresp is None:
            return None
        if len(logpointerresp) != 2:
            self.log("GETLOGPOINTER: response wrong length")
            self.log("Payload: " + self.hexstr(logpointerresp))
            return None
        logpointer = logpointerresp[0] + (logpointerresp[1] << 8)
        self.log("Log pointer: {:d}".format(logpointer))
        return logpointer

    def get_number_zones(self):
        idstr = self.get_panel_identification()
        if idstr is None:
            return None
        # idstr is bytes -> decode and split
        try:
            id_decoded = idstr.decode('latin1')
            parts = id_decoded.split()
            self.panelType, numberOfZones, something, self.firmwareVersion = parts
            self.numberOfZones = int(numberOfZones)
        except Exception as e:
            logger.error("[get_number_zones] parse failed: %s", e)
            return None

    def get_panel_identification(self):
        panelid = self.sendcommand(self.CMD_GETPANELIDENTIFICATION.to_bytes(1,'little'), None)
        if panelid is None:
            return None
        if len(panelid) != 32:
            self.log("GETPANELIDENTIFICATION: response wrong length")
            self.log("Payload: " + self.hexstr(panelid))
            return None
        try:
            panelid_str = panelid.decode('latin1')
        except Exception:
            panelid_str = str(panelid)
        self.log("Panel identification: " + panelid_str)
        return panelid

    def get_zone(self, zone_number):
        if zone_number not in self.zone:
            self.zone[zone_number] = Zone(zone_number)
        return self.zone[zone_number]

    def get_zone_details(self, zone_number):
        # zone is two bytes on 680 - here we only send one byte like original
        body = bytes([zone_number & 0xff])
        details = self.sendcommand(self.CMD_GETZONEDETAILS.to_bytes(1,'little'), body)
        if details is None:
            return None
        zone = self.get_zone(zone_number)
        if len(details) == 34:
            zone.zoneType = details[0]
            zone.areaBitmap = details[1]
            zone_text_bytes = details[2:]
        elif len(details) == 35:
            zone.zoneType = details[0]
            zone.areaBitmap = details[1] + (details[2] << 8)
            zone_text_bytes = details[3:]
        elif len(details) == 41:
            zone.zoneType = details[0]
            zone.areaBitmap = (details[1] + (details[2] << 8) + (details[3] << 16) + (details[4] << 24) +
                              (details[5] << 32) + (details[6] << 40) + (details[7] << 48) + (details[8] << 56))
            zone_text_bytes = details[9:]
        else:
            self.log("GETZONEDETAILS: response wrong length")
            self.log("Payload: " + self.hexstr(details))
            return None

        try:
            zone.text = zone_text_bytes.decode('latin1').replace("\x00", " ")
        except Exception as e:
            logger.debug("[get_zone_details] text decode fallback: %s", e)
            zone.text = str(zone_text_bytes)
        zone.text = re.sub(r'\W+', ' ', zone.text)
        zone.text = zone.text.strip()
        if zone.zoneType != self.ZONETYPE_UNUSED:
            self.log("zone {:d} type {} name '{}'".
                     format(zone.number, self.zone_types.get(zone.zoneType, "unknown"), zone.text))
        return zone

    def get_area(self, areaNumber):
        if areaNumber not in self.zone:
            self.area[areaNumber] = Area(areaNumber)
        return self.area[areaNumber]

    def get_area_details(self, areaNumber):
        details = self.sendcommand(self.CMD_GETAREADETAILS.to_bytes(1,'little'), bytes([areaNumber & 0xff]))
        if details is None:
            return None
        area = Area()
        if len(details) == 25:
            # first byte is area number
            areatext = details[1:17]
            try:
                areatext = areatext.decode('latin1').replace("\x00", " ")
            except Exception as e:
                logger.debug("[get_area_details] text decode fallback: %s", e)
                areatext = str(areatext)
            areatext = re.sub(r'\W+', ' ', areatext)
            areatext = areatext.strip()
            area.name = areatext
            area.exitDelay = details[17] + (details[18] << 8)
            area.entry1Delay = details[19] + (details[20] << 8)
            area.entry2Delay = details[21] + (details[22] << 8)
            area.secondEntry = details[23] + (details[24] << 8)
        else:
            self.log("GETAREADETAILS: response wrong length")
            self.log("Payload: " + self.hexstr(details))
            return None
        self.log("area {:d} text '{}' exitDelay {:d} entry1 {:d} entry2 {:d} secondEntry {:d}".
                 format(areaNumber, area.name, area.exitDelay, area.entry1Delay, area.entry1Delay, area.secondEntry))
        return area

    @staticmethod
    def bcdDecode(bcd):
        result = ""
        for byte in bcd:
            high = (byte >> 4) & 0xF
            low = byte & 0xF
            for val in (high, low):
                if val <= 9:
                    result += str(val)
        return result

    def get_user(self, usernumber):
        # panel may support more than 255 users, in which case this needs 2 bytes
        body = bytes([usernumber & 0xff])
        details = self.sendcommand(self.CMD_GETUSER.to_bytes(1,'little'), body)
        if details is None:
            return None
        user = User()
        if len(details) == 23:
            username = details[0:8]
            try:
                username = username.decode('latin1').replace("\x00", " ")
            except Exception as e:
                logger.debug("[get_user] username decode fallback: %s", e)
                username = str(username)
            username = re.sub(r'\W+', ' ', username)
            username = username.strip()
            user.name = username
            user.passcode = self.bcdDecode(details[8:11])
            user.areas = details[11]
            user.modifiers = details[12]
            user.locks = details[13]
            user.doors = details[14:17]
            user.tag = self.bcdDecode(details[17:21])  # last byte always 0xff
            user.config = details[21] + (details[22] << 8)
        else:
            # there are other lengths but I have no way to test
            self.log("GETUSER: unexpected response length {:d}".format(len(details)))
            self.log("Payload: " + self.hexstr(details))
            return None

        if user.valid():
            self.log("user {:d} name '{}'".
                     format(usernumber, user.name))
        return user

    def get_system_power(self):
        details = self.sendcommand(self.CMD_GETSYSTEMPOWER.to_bytes(1,'little'), None)
        if details is None:
            return None
        if len(details) != 5:
            self.log("GETSYSTEMPOWER: response wrong length")
            self.log("Payload: " + self.hexstr(details))
            return None
        ref_v = details[0]
        sys_v = details[1]
        bat_v = details[2]
        sys_i = details[3]
        bat_i = details[4]

        system_voltage = 13.7 + ((sys_v - ref_v) * 0.070)
        battery_voltage = 13.7 + ((bat_v - ref_v) * 0.070)

        system_current = sys_i * 9
        battery_current = bat_i * 9

        self.log("System power: system voltage {:f} battery voltage {:f} system current {:d} battery current {:d}".
                 format(system_voltage, battery_voltage, system_current, battery_current))
        
        # Battery decision logic
        try:
            evaluate_battery_state(
                battery_voltage,
                datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            )
        except Exception as e:
            self.log(f"Battery evaluation error: {e}")

        return (system_voltage, battery_voltage, system_current, battery_current)

    def get_all_zones(self):
        for zoneNumber in range(1, self.numberOfZones + 1):
            zone = self.get_zone_details(zoneNumber)
            self.zone[zoneNumber] = zone

    def get_all_users(self):
        panel_users = {12: 8, 24: 25, 48: 50, 64: 50, 88: 100, 168: 200, 640: 1000}
        for usernumber in range(1, panel_users.get(self.numberOfZones, 0)):
            user = self.get_user(usernumber)
            if user and user.valid():
                self.user[usernumber] = user
        user = User()
        user.name = "Engineer"
        self.user[0] = user

    def get_all_areas(self):
        panel_areas = {12: 2, 24: 2, 48: 4, 64: 4, 88: 8, 168: 16, 640: 64}
        for areanumber in range(1, panel_areas.get(self.numberOfZones, 0)):
            area = self.get_area_details(areanumber)
            self.area[areanumber] = area

    def get_site_data(self):
        self.get_all_areas()
        self.get_all_zones()
        self.get_all_users()

    def event_loop(self):
        
        lastConnectedAt = time.time()
        notifiedConnectionLoss = False
        connected = False
        panel_info_sent = False
        _retry_count = 0   # ensure panel info is sent only once per connection
        
        while True:
            
            if connected:
                lastConnectedAt = time.time()
                connected = False
                notifiedConnectionLoss = False
                panel_info_sent = False 
                self.log("Connection lost")
                try:
                    with open(CONN_STAT_FILE,"w") as log:
                        log.write(str(0))
                except Exception as e:
                    logger.debug("[event_loop] conn_stat write failed: %s", e)
                
            connectionLostTime = time.time() - lastConnectedAt
            
            if connectionLostTime >= 60 and not notifiedConnectionLoss:
                self.log("Connection lost for over 60 seconds - calling send-message.sh")
                # subprocess.run(["./send-message.sh", "connection lost"], check=False)
                notifiedConnectionLoss = True
            
            # ---------------- TRY CONNECT ----------------
            try:
                self.connect()
            except socket.error as e:
                self.log(f"Connect failed - {e}; sleeping for 5 seconds")

                # ================= PANEL POWER OFF (STRONG SIGNAL) =================
                if PANEL_POWER_STATE["panel"] != "OFF":
                    PANEL_POWER_STATE["panel"] = "OFF"

                    payload = {
                        "texecom_event": {
                            "event_name": "Panel Power",
                            "state": "OFF",
                            "reason": "TCP connection refused",
                            "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        }
                    }

                    if logical_params_module.get_parameter("active_integration_texecom_bas") == 1:
                        insert_json_to_db(json.dumps(payload))
                        TexecomConnect.log("Panel Power OFF detected (connect failed)")
                        send_texecom_heartbeat(self)

                try:
                    with open(CONN_STAT_FILE,"w") as log:
                        log.write(str(0))
                except Exception as e:
                    logger.debug("[event_loop] conn_stat write failed: %s", e)

                # RE-01: Exponential backoff — 5s → 10s → 20s → ... → 300s max
                _backoff = min(5 * (2 ** _retry_count), 300)
                logger.info("[reconnect] retry in %ds (attempt %d)", _backoff, _retry_count + 1)
                time.sleep(_backoff)
                _retry_count += 1
                continue
            
            # ---------------- LOGIN ----------------
            if not self.login():
                self.log(
                    "Login failed - udl password incorrect, pre-v4 panel, or trying to connect too soon: closing socket, try again 5 in seconds")
                _backoff = min(5 * (2 ** _retry_count), 300)
                time.sleep(_backoff)
                _retry_count += 1
                self.closesocket()
                continue
            
            self.log("login successful")
            _retry_count = 0  # RE-01: reset backoff on successful connection
            
            try:
                with open(CONN_STAT_FILE,"w") as log:
                    log.write(str(1))
            except Exception as e:
                logger.debug("[event_loop] conn_stat write failed: %s", e)
            
            
            if not self.set_event_messages():
                self.log("Set event messages failed, closing socket")
                self.closesocket()
                continue
            connected = True
            
            if notifiedConnectionLoss:
                self.log("Connection regained - calling send-message.sh")
                # subprocess.run(["./send-message.sh", "connection regained"], check=False)
                notifiedConnectionLoss = False
            
            # ---------------- PANEL INITIALIZATION ----------------
            try:                 
                self.get_number_zones()
                self.get_date_time()
                self.get_system_power()
                self.get_log_pointer()

                # ==================================================
                # PANEL POWER ON (PROTOCOL CONFIRMED) 
                # ==================================================
                if PANEL_POWER_STATE["panel"] != "ON":
                    PANEL_POWER_STATE["panel"] = "ON"
                    PANEL_SEEN_ONCE = True
                    STARTUP_OFF_SENT = False

                    payload = {
                        "texecom_event": {
                            "event_name": "Panel Power",
                            "state": "ON",
                            "reason": "Protocol initialized",
                            "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        }
                    }

                    if logical_params_module.get_parameter(
                            "active_integration_texecom_bas") == 1:
                        insert_json_to_db(json.dumps(payload))
                        TexecomConnect.log("Panel Power ON detected")

                # --------------------------------------------------
                # Other one-time telemetry after panel is ON
                # --------------------------------------------------
                send_texecom_heartbeat(self)
                
                send_texecom_power_status(self)
                
                send_texecom_time_status(tc)

                self.log("Got all areas/zones/users; waiting for events")

            except Exception as e:
                self.log(f"Initialization failed: {e}")
                self.closesocket()
                continue
                       
            # ---------------- PANEL POWER STATE ----------------
            init_power_state_from_voltage(tc)
                        
            send_texecom_power_state_once(tc)
            
            # ---------------- SEND PANEL INFO (ONCE) ----------------
            if not panel_info_sent:
                try:
                    send_texecom_panel_info()                   
                    panel_info_sent = True
                except Exception as e:
                    self.log(f"Failed to send panel info: {e}")

            self.log("Panel initialized; waiting for events")
                       
            # ---------------- MAIN RECEIVE LOOP ----------------           
            while self.s is not None:
                try:
                    for zone in self.zone.values():
                        zone.update()
                    
                    if self.siteDataChanged:
                        self.siteDataChanged = False
                        self.get_site_data()
                    
                    # This blocks until message / timeout
                    self.recvresponse()

                except socket.timeout:
                    # we didn't send any command, so a timeout is the expected result, continue our loop
                    continue
                except socket.error as e:
                    self.log(f"Socket error: {e}")
                    self.closesocket()
                    break

                except Exception as e:
                    self.log(f"Unexpected error in event loop: {e}")
                    self.closesocket()
                    break                

    def decode_message_to_text(self, payload):
        # payload is bytes
        if not payload:
            return "empty payload"
        msg_type = payload[0]
        payload_rest = payload[1:]
        
        if msg_type == self.MSG_DEBUG:
            return "Debug message: " + self.hexstr(payload_rest)
        
        elif msg_type == self.MSG_ZONEEVENT:
            if len(payload_rest) == 2:
                zone_number = payload_rest[0]
                zone_bitmap = payload_rest[1]
            elif len(payload_rest) == 3:
                zone_number = payload_rest[0] + (payload_rest[1] << 8)
                zone_bitmap = payload_rest[2]
            else:
                return "unknown zone event message payload length"
            zone_state = zone_bitmap & 0x3
            zone_str = ["secure", "active", "tamper", "short"][zone_state]
            if zone_bitmap & (1 << 2):
                zone_str += ", fault"
            if zone_bitmap & (1 << 3):
                zone_str += ", failed test"
            if zone_bitmap & (1 << 4):
                zone_str += ", alarmed"
            if zone_bitmap & (1 << 5):
                zone_str += ", manual bypassed"
            if zone_bitmap & (1 << 6):
                zone_str += ", auto bypassed"
            if zone_bitmap & (1 << 7):
                zone_str += ", zone masked"
            if zone_number in self.zone:
                zone_text = self.zone[zone_number].text
            else:
                zone_text = "unknown zone"

            zoneActive = "active"
            zoneSecure = "secure"
            
            try:
#                with open("/home/pi/Test3/texecom_d.txt","a") as log:
#                    log.write(str(zone_number))
#                    log.write(" ")
                    if zoneActive in zone_str:
#                        log.write("active")
                        texeNetZoneStatus(zone_number, 'active')
                    if zoneSecure in zone_str:
#                        log.write("secure")
                        texeNetZoneStatus(zone_number, 'secure')
#                    log.write("\n")
            except Exception as e:
                logger.error("[decode_message] zone event processing failed: %s", e)
                
            return "Zone event message: zone {:d} '{}' {}". \
                format(zone_number, zone_text, zone_str)
        
        elif msg_type == self.MSG_AREAEVENT:
            area_number = payload_rest[0]
            area_state = payload_rest[1]
            area_state_str = ["disarmed", "in exit", "in entry", "armed", "part armed", "in alarm"][area_state]
            if area_number in self.area:
                areaname = self.area[area_number].name
            else:
                areaname = "unknown"
            return "Area event message: area {:d} {} {}".format(area_number, areaname, area_state_str)
        
        elif msg_type == self.MSG_OUTPUTEVENT:
            locations = ["Panel outputs",
                         "Digi outputs",
                         "Digi Channel low 8",
                         "Digi Channel high 8",
                         "Redcare outputs",
                         "Custom outputs 1",
                         "Custom outputs 2",
                         "Custom outputs 3",
                         "Custom outputs 4",
                         "X-10 outputs"]
            output_location = payload_rest[0]
            output_state = payload_rest[1]
            if output_location < len(locations):
                output_name = locations[output_location]
            elif (output_location & 0xf) == 0:
                output_name = "Network {:d} keypad outputs". \
                    format(output_location >> 4, output_location & 0xf)
            else:
                output_name = "Network {:d} expander {:d} outputs". \
                    format(output_location >> 4, output_location & 0xf)
            return "Output event message: location {:d}['{}'] now 0x{:02x}". \
                format(output_location, output_name, output_state)
        
        elif msg_type == self.MSG_USEREVENT:
            user_number = payload_rest[0]
            user_state = payload_rest[1]
            user_state_str = ["code", "tag", "code+tag"][user_state]
            if user_number in self.user:
                name = self.user[user_number].name
            else:
                name = "unknown"
            return "User event message: logon by user '{}' {:d} {}". \
                format(name, user_number, user_state_str)
        
        elif msg_type == self.MSG_LOGEVENT:
            if len(payload_rest) == 8:
                parameter = payload_rest[2]
                areas = payload_rest[3]
                timestamp = payload_rest[4:8]
            elif len(payload_rest) == 9:
                # Premier 168 - longer message as 16 bits of area info
                parameter = payload_rest[2]
                areas = payload_rest[3] + (payload_rest[8] << 8)
                timestamp = payload_rest[4:8]
            elif len(payload_rest) == 10:
                # Premier 640
                parameter = payload_rest[2] + (payload_rest[3] << 8)
                areas = payload_rest[4] + (payload_rest[5] << 8)
                timestamp = payload_rest[6:10]
            else:
                return "unknown log event message payload length"

            event_type = payload_rest[0]
            group_type_msg = payload_rest[1]
            timestamp_int = timestamp[0] + (timestamp[1] << 8) + (timestamp[2] << 16) + (timestamp[3] << 24)
            seconds = timestamp_int & 63
            minutes = (timestamp_int >> 6) & 63
            month = (timestamp_int >> 12) & 15
            hours = (timestamp_int >> 16) & 31
            day = (timestamp_int >> 21) & 31
            year = 2000 + ((timestamp_int >> 26) & 63)
            timestamp_str = "{:04d}-{:02d}-{:02d} {:02d}:{:02d}:{:02d}".format(year, month, day, hours, minutes,
                                                                               seconds)

            if event_type in self.log_event_types:
                event_str = self.log_event_types[event_type]
            else:
                event_str = "Unknown log event type {:d}".format(event_type)

            group_type = group_type_msg & 0b00111111
            comm_delayed = group_type_msg & 0b01000000
            communicated = group_type_msg & 0b10000000

            if group_type in self.log_event_group_type:
                group_type_str = self.log_event_group_type[group_type]
            else:
                group_type_str = "Unknown log event group type {:d}".format(group_type)

            if comm_delayed:
                group_type_str += " [comm delayed]"
            if communicated:
                group_type_str += " [communicated]"

            return "Log event message: {} {}, {}  parameter: {:d}   areas: {:d}".format(timestamp_str, event_str,
                                                                                        group_type_str, parameter,
                                                                                        areas)
        else:
            return "unknown message type " + str(msg_type) + ": " + self.hexstr(payload_rest)

# New function added for sending texecom Panel Info to dB
def send_texecom_panel_info():
    """
    Send Texecom panel static information once after successful login.
    This should NOT be sent with every event.
    """
    try:
        payload = {
            "texecom_panel_info": {
                "ip": getattr(tc, "host", None),
                "model": f"{tc.panelType} {tc.numberOfZones}" if tc.panelType and tc.numberOfZones else None,
                "zones_supported": tc.numberOfZones,
                "firmware": getattr(tc, "firmwareVersion", None)
            }
        }

        attributes_json = json.dumps(payload, indent=4)

        if logical_params_module.get_parameter("active_integration_texecom_bas") == 1:
            insert_json_to_db(attributes_json)
            TexecomConnect.log("Texecom panel info sent to DB")

    except Exception as e:
        TexecomConnect.log(f"Failed to send Texecom panel info: {e}")    


def send_texecom_power_state_once_1():
    """
    Send logical power state ONCE when panel turns ON.
    """
    try:
        payload = {
            "texecom_power_state": {
                "mains": PANEL_POWER_STATE.get("mains"),
                "battery": PANEL_POWER_STATE.get("battery"),
                "panel": PANEL_POWER_STATE.get("panel"),
                "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
        }

        if logical_params_module.get_parameter("active_integration_texecom_bas") == 1:
            insert_json_to_db(json.dumps(payload))
            TexecomConnect.log("Texecom power STATE sent")

    except Exception as e:
        TexecomConnect.log(f"Failed to send power state: {e}")

POWER_STATE_SENT = False

def send_texecom_power_state_once(tc):
    global POWER_STATE_SENT

    if POWER_STATE_SENT:
        return

    # Ensure keys exist
    PANEL_POWER_STATE.setdefault("mains", "UNKNOWN")
    PANEL_POWER_STATE.setdefault("battery", "UNKNOWN")

    # Try voltage (best effort, NOT authoritative)
    result = tc.get_system_power()
    if result:
        system_voltage, battery_voltage, _, _ = result

        if system_voltage is not None:
            PANEL_POWER_STATE["mains"] = "ON" if system_voltage >= 13.0 else "OFF"

        # DO NOT infer battery presence from voltage
        if PANEL_POWER_STATE["battery"] == "UNKNOWN":
            PANEL_POWER_STATE["battery"] = "ON"

    # BLOCK sending if still UNKNOWN
    if PANEL_POWER_STATE["mains"] == "UNKNOWN" and PANEL_POWER_STATE["battery"] == "UNKNOWN":
        TexecomConnect.log("Power state not ready yet – skipping initial send")
        return

    payload = {
        "texecom_power_state": {
#            "event_name": "Initial Power State",
            "mains": PANEL_POWER_STATE["mains"],
            "battery": PANEL_POWER_STATE["battery"],
            "panel": PANEL_POWER_STATE.get("panel"),
            "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
    }

    attributes_json = json.dumps(payload)

    if logical_params_module.get_parameter("active_integration_texecom_bas") == 1:
        insert_json_to_db(attributes_json)
        TexecomConnect.log("Sent initial power state")

    POWER_STATE_SENT = True

def evaluate_battery_state(battery_voltage, timestamp_str):
    global BATTERY_ALARM_ACTIVE, BATTERY_VOLTAGE_HISTORY

    if not BATTERY_ALARM_ACTIVE:
        return

    if battery_voltage is None:
        return

    BATTERY_VOLTAGE_HISTORY.append(battery_voltage)

    if len(BATTERY_VOLTAGE_HISTORY) < BATTERY_HISTORY_LEN:
        return

    BATTERY_VOLTAGE_HISTORY = BATTERY_VOLTAGE_HISTORY[-BATTERY_HISTORY_LEN:]

    drop = BATTERY_VOLTAGE_HISTORY[0] - BATTERY_VOLTAGE_HISTORY[-1]

    # Falling voltage → real LOW
    if drop > 0.15:
        battery_state = "LOW"
        PANEL_POWER_STATE["battery"] = battery_state
        BATTERY_ALARM_ACTIVE = False

    # Stable voltage → battery disconnected
    elif min(BATTERY_VOLTAGE_HISTORY) >= 11.9:
        battery_state = "DISCONNECTED"
        PANEL_POWER_STATE["battery"] = battery_state
        BATTERY_ALARM_ACTIVE = False

    else:
        return  # not enough info yet

    payload = {
        "texecom_event": {
            "event_name": "Battery Power",
            "status": battery_state,
            "timestamp": timestamp_str
        }
    }

    attributes_json = json.dumps(payload)

    if logical_params_module.get_parameter("active_integration_texecom_bas") == 1:
        insert_json_to_db(attributes_json)
        TexecomConnect.log(f"Sent to DB: Battery Power → {battery_state}")


def init_power_state_from_voltage(tc):
    result = tc.get_system_power()
    if result is None:
        return

    system_voltage, battery_voltage, _, _ = result

    PANEL_POWER_STATE["mains"] = "ON" if system_voltage >= 13.0 else "OFF"
    PANEL_POWER_STATE["battery"] = "ON" if battery_voltage >= 12.0 else "LOW"


def scheduler_loop():
    logger.info("[scheduler_loop] started")
    while True:
        try:
            schedule.run_pending()
        except Exception as e:
            logger.error("[scheduler_loop] exception: %s", e)
        time.sleep(1)


def send_texecom_power_status(tc):
    """
    Pull current system power values from Texecom panel
    and send them as a structured power status record.
    Intended to be called periodically (e.g. every 1 hour).
    """
    try:
        result = tc.get_system_power()
        if result is None:
            TexecomConnect.log("Power status read failed")
            return

        system_voltage, battery_voltage, system_current, battery_current = result

        payload = {
            "texecom_power_status": {
                "system_voltage": round(system_voltage, 2),
                "battery_voltage": round(battery_voltage, 2),
                "system_current": int(system_current),
                "battery_current": int(battery_current),
                "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
        }

        attributes_json = json.dumps(payload, indent=4)

        if logical_params_module.get_parameter("active_integration_texecom_bas") == 1:
            insert_json_to_db(attributes_json)
            TexecomConnect.log("Texecom power status sent to DB")

    except Exception as e:
        TexecomConnect.log(f"Failed to send power status: {e}")


def send_texecom_heartbeat(tc):
    global LAST_HEARTBEAT_TIME

    try:
        panel_state = PANEL_POWER_STATE.get("panel")

        # heartbeat reflects PANEL FSM, not socket
        status = "online" if panel_state == "ON" else "LinkFail"

        # update heartbeat time ONLY when panel is truly ON
        if panel_state == "ON":
            LAST_HEARTBEAT_TIME = time.time()

        payload = {
            "texecom_heartbeat": {
                "status": status,
                "panel_ip": tc.host if tc else None,
                "panel_state": panel_state,
                "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
        }

        if logical_params_module.get_parameter("active_integration_texecom_bas") == 1:
            insert_json_to_db(json.dumps(payload))
            TexecomConnect.log(f"Heartbeat sent: {status}")

    except Exception as e:
        TexecomConnect.log(f"Heartbeat error: {e}")



def send_texecom_power_on_off(tc):
    """
    Detect PANEL OFF only (protocol-based).
    ON is detected ONLY inside event_loop after successful init.
    """
    global PANEL_SEEN_ONCE, STARTUP_OFF_SENT

    try:
        now_ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        protocol_alive = bool(tc and tc.s)

        # ==================================================
        # STARTUP: protocol never connected → OFF once
        # ==================================================
        if not protocol_alive and not PANEL_SEEN_ONCE:
            if not STARTUP_OFF_SENT:
                STARTUP_OFF_SENT = True
                PANEL_POWER_STATE["panel"] = "OFF"

                payload = {
                    "texecom_event": {
                        "event_name": "Panel Power",
                        "state": "OFF",
                        "reason": "Protocol unreachable at startup",
                        "timestamp": now_ts
                    }
                }

                if logical_params_module.get_parameter(
                        "active_integration_texecom_bas") == 1:
                    insert_json_to_db(json.dumps(payload))
                    TexecomConnect.log("Panel Power OFF (startup)")
            return

        # ==================================================
        # RUNTIME: panel was ON → protocol lost
        # ==================================================
        if PANEL_SEEN_ONCE and not protocol_alive:
            if PANEL_POWER_STATE["panel"] != "OFF":
                PANEL_POWER_STATE["panel"] = "OFF"

                payload = {
                    "texecom_event": {
                        "event_name": "Panel Power",
                        "state": "OFF",
                        "reason": "Protocol connection lost",
                        "timestamp": now_ts
                    }
                }

                if logical_params_module.get_parameter(
                        "active_integration_texecom_bas") == 1:
                    insert_json_to_db(json.dumps(payload))
                    TexecomConnect.log("Panel Power OFF detected")

    except Exception as e:
        TexecomConnect.log(f"Panel power detection error: {e}")


def send_texecom_time_status(tc):
    """
    Periodic task: read panel time, calculate drift,
    send status and raise error if drift > 10 minutes.
    """
    try:
        panel_time_str = tc.get_date_time()
        if panel_time_str is None:
            TexecomConnect.log("Panel time read failed")
            return

        panel_time = datetime.datetime.strptime(
            panel_time_str, "%Y-%m-%d %H:%M:%S"
        )
        system_time = datetime.datetime.now()

        drift_seconds = int((system_time - panel_time).total_seconds())

        # ---------------- SEND TIME STATUS ----------------
        payload = {
            "texecom_time_status": {
                "panel_time": panel_time_str,
                "system_time": system_time.strftime("%Y-%m-%d %H:%M:%S"),
                "drift_seconds": drift_seconds,
                "timestamp": system_time.strftime("%Y-%m-%d %H:%M:%S")
            }
        }
        
        attributes_json = json.dumps(payload)
        
        if logical_params_module.get_parameter("active_integration_texecom_bas") == 1:
            insert_json_to_db(attributes_json)
            TexecomConnect.log("Texecom time status sent")

        # ---------------- DRIFT ERROR LOGIC ----------------
        # ---------------- DRIFT ERROR (STATE / TELEMETRY) ----------------
        if abs(drift_seconds) > 600:  # 10 minutes
            if not TIME_SYNC_STATE["last_drift_alert"]:

                event_name = "Panel Time Error"

                payload = {
                    "texecom_event": {
                        "event_name": event_name,
                        "state": "ERROR",
                        "drift_seconds": drift_seconds,
                        "panel_time": panel_time_str,
                        "system_time": system_time.strftime("%Y-%m-%d %H:%M:%S"),
                        "timestamp": system_time.strftime("%Y-%m-%d %H:%M:%S")
                    }
                }

                attributes_json = json.dumps(payload)

                if logical_params_module.get_parameter("active_integration_texecom_bas") == 1:
                    insert_json_to_db(attributes_json)
                    TexecomConnect.log(f"Sent to DB: {event_name}")

                TIME_SYNC_STATE["last_drift_alert"] = True

        else:
            # Drift back to normal → reset alert latch
            TIME_SYNC_STATE["last_drift_alert"] = False
        
    except Exception as e:
        TexecomConnect.log(f"Time status error: {e}")


def handle_switch_event(event_name, group_type_str, parameter, areas, timestamp):

    payload = {
        "event_name": event_name,
        "timestamp": timestamp
    }

    # ---------------- KEYSWITCH LATCHING ----------------
    if event_name == "Keyswitch - Latching":
        #if "Fault" in group_type_str:
        if "Close" in group_type_str:
            payload["state"] = "Armed"
        #elif "Close" in group_type_str:
        elif "Open" in group_type_str:
            payload["state"] = "Disarmed"
        else:
            return

    # ---------------- KEYSWITCH MOMENTARY ----------------
    elif event_name == "Keyswitch - Momentary":
        #payload["state"] = "Triggered"
        if "Fault" in group_type_str:
            payload["state"] = "Activate"
        #elif "Close" in group_type_str:
        #    payload["state"] = "Armed"
        elif "Open" in group_type_str:
            payload["state"] = "Disarmed"
        else:
            return

    # ---------------- SECURITY KEY ----------------
    elif event_name == "Security Key":
        if "Open" in group_type_str:
            payload["state"] = "Open"
        elif "Close" in group_type_str:
            payload["state"] = "Closed"
        else:
            return
        payload["zone_states"] = f"Zone {parameter} {payload['state']}"

    # ---------------- OMIT KEY ----------------
    elif event_name == "Omit Key":
        payload["state"] = "Active"

#    insert_json_to_db(json.dumps({"texecom_event": payload}))
    attributes_json = json.dumps({"texecom_event": payload})
    if logical_params_module.get_parameter("active_integration_texecom_bas") == 1:
        insert_json_to_db(attributes_json)
        TexecomConnect.log(f"Sent to DB: {event_name}")


def finalize_incident():
    global PENDING_INCIDENT, EVENT_CONTEXT

    if not PENDING_INCIDENT:
        return

    event_name = PENDING_INCIDENT["event_name"]
    bell = PENDING_INCIDENT["bell"]
    timestamp = PENDING_INCIDENT["timestamp"]

    zone_text = None
    area_text = None

    if EVENT_CONTEXT["zone_states"]:
        z, z_state = sorted(EVENT_CONTEXT["zone_states"].items())[0]
        zone_text = f"Zone {z} {z_state}"

    if EVENT_CONTEXT["area_states"]:
        a, a_state = sorted(EVENT_CONTEXT["area_states"].items())[0]
        area_text = f"Area {a} {a_state}"

    payload = {
        "texecom_event": {
            "event_name": event_name,
            "bell": bell,
            "zone_states": zone_text,
            "area_states": area_text,
            "timestamp": timestamp
        }
    }

    insert_json_to_db(json.dumps(payload))
    TexecomConnect.log(f"Unified incident sent: {event_name}")

    # clear everything
    PENDING_INCIDENT = None
    EVENT_CONTEXT["zones"].clear()
    EVENT_CONTEXT["zone_states"].clear()
    EVENT_CONTEXT["areas"].clear()
    EVENT_CONTEXT["area_states"].clear()
    EVENT_CONTEXT["last_update"] = 0


def message_handler(payload):
    global EVENT_CONTEXT, PANEL_POWER_STATE
    global BATTERY_ALARM_ACTIVE, BATTERY_VOLTAGE_HISTORY, BATTERY_CONFIRMED

    try:
        tc.log(tc.decode_message_to_text(payload))
    except Exception as e:
        logger.debug("[message_handler] decode_message_to_text failed: %s", e)

    if not payload:
        return

    now = time.time()

    # TS-01: Lock protects EVENT_CONTEXT / PANEL_POWER_STATE shared with scheduler thread
    with _state_lock:
        # ---------------- AUTO-CLEAR STALE CONTEXT ----------------
        if now - EVENT_CONTEXT["last_update"] > EVENT_CONTEXT_TIMEOUT:
            EVENT_CONTEXT["zones"].clear()
            EVENT_CONTEXT["zone_states"].clear()
            EVENT_CONTEXT["areas"].clear()
            EVENT_CONTEXT["area_states"].clear()

    msg_type = payload[0]
    payload_rest = payload[1:]

    # ==========================================================
    # ZONE EVENT → STORE ONLY
    # ==========================================================
    if msg_type == tc.MSG_ZONEEVENT:

        if len(payload_rest) == 2:
            zone_number = payload_rest[0]
            zone_bitmap = payload_rest[1]
        elif len(payload_rest) == 3:
            zone_number = payload_rest[0] + (payload_rest[1] << 8)
            zone_bitmap = payload_rest[2]
        else:
            return

        zone_state = "Active" if (zone_bitmap & 0x3) == 1 else "Restore"

        EVENT_CONTEXT["zones"].add(zone_number)
        EVENT_CONTEXT["zone_states"][zone_number] = zone_state
        EVENT_CONTEXT["last_update"] = now
        return

    # ==========================================================
    # AREA EVENT → STORE ONLY
    # ==========================================================
    elif msg_type == tc.MSG_AREAEVENT:

        if len(payload_rest) < 2:
            return

        area_number = payload_rest[0]
        area_state = payload_rest[1]

        area_text = "in alarm" if area_state == 5 else "Restore"

        EVENT_CONTEXT["areas"].add(area_number)
        EVENT_CONTEXT["area_states"][area_number] = area_text
        EVENT_CONTEXT["last_update"] = now
        return

    # ==========================================================
    # LOG EVENT → FINAL DECISION
    # ==========================================================
    elif msg_type == tc.MSG_LOGEVENT:

        try:
            # -------- Decode payload variants --------
            if len(payload_rest) == 8:
                parameter = payload_rest[2]
                areas = payload_rest[3]
                ts = payload_rest[4:8]
            elif len(payload_rest) == 9:
                parameter = payload_rest[2]
                areas = payload_rest[3] + (payload_rest[8] << 8)
                ts = payload_rest[4:8]
            elif len(payload_rest) == 10:
                parameter = payload_rest[2] + (payload_rest[3] << 8)
                areas = payload_rest[4] + (payload_rest[5] << 8)
                ts = payload_rest[6:10]
            else:
                return

            event_type = payload_rest[0]
            group_type_msg = payload_rest[1]
            group_type = group_type_msg & 0x3F

            event_name = tc.log_event_types.get(event_type, f"Event_{event_type}")
            group_type_str = tc.log_event_group_type.get(group_type, "")

            bell_state = "Restore" if "Restore" in group_type_str else "Active"

            ts_int = ts[0] + (ts[1] << 8) + (ts[2] << 16) + (ts[3] << 24)
            timestamp_str = (
                f"{2000 + ((ts_int >> 26) & 63):04d}-"
                f"{(ts_int >> 12) & 15:02d}-"
                f"{(ts_int >> 21) & 31:02d} "
                f"{(ts_int >> 16) & 31:02d}:"
                f"{(ts_int >> 6) & 63:02d}:"
                f"{ts_int & 63:02d}"
            )

            # --------------------------------------------------
            # IGNORE NOISE EVENTS
            # --------------------------------------------------
            if event_name in IGNORE_EVENTS:
                return

            # --------------------------------------------------
            # POWER EVENTS → SEND IMMEDIATELY
            # --------------------------------------------------
            if event_name in POWER_EVENTS:

                if event_name == "AC Fail":
                    mains_state = "ON" if "Restore" in group_type_str else "OFF"

                    if PANEL_POWER_STATE["mains"] != mains_state:
                        PANEL_POWER_STATE["mains"] = mains_state

                        payload = {
                            "texecom_event": {
                                "event_name": "Mains Power",
                                "status": mains_state,
                                "timestamp": timestamp_str
                            }
                        }

                        if logical_params_module.get_parameter("active_integration_texecom_bas") == 1:
                            insert_json_to_db(json.dumps(payload))
                            TexecomConnect.log(f"Sent to DB: {event_name}")

                    return

                # -----------------------------
                # PANEL LOW BATTERY ONLY
                # -----------------------------
                elif event_name == "Low Battery" and parameter == 0:

                    # ===== MAINTENANCE RESTORE =====
                    if group_type_str == "Maintenance Restore":

                        # First real confirmation of battery presence
                        if not BATTERY_CONFIRMED:
                            PANEL_POWER_STATE["battery"] = "ON"
                            BATTERY_CONFIRMED = True
                            BATTERY_ALARM_ACTIVE = False
                            BATTERY_VOLTAGE_HISTORY.clear()

                            payload = {
                                "texecom_event": {
                                    "event_name": "Battery Power",
                                    "status": "ON",
                                    "timestamp": timestamp_str
                                }
                            }

                            if logical_params_module.get_parameter("active_integration_texecom_bas") == 1:
                                insert_json_to_db(json.dumps(payload))
                                TexecomConnect.log("Sent to DB: Battery Power → ON (confirmed)")

                        return

                    # ===== MAINTENANCE ALARM =====
                    elif group_type_str == "Maintenance Alarm":

                        BATTERY_ALARM_ACTIVE = True
                        BATTERY_CONFIRMED = False
                        BATTERY_VOLTAGE_HISTORY.clear()

                        TexecomConnect.log("Low Battery alarm → monitoring voltage")
                        return

                    # ===== IGNORE OTHER RESTORES =====
                    else:
                        TexecomConnect.log(
                            f"Ignored Low Battery event with group type: {group_type_str}"
                        )
                        return

                # -----------------------------
                # OTHER POWER EVENTS (RAW SEND)
                # -----------------------------
                else:
                    payload = {
                        "texecom_event": {
                            "event_name": event_name,
                            "group": group_type_str,
                            "timestamp": timestamp_str
                        }
                    }

                    if logical_params_module.get_parameter("active_integration_texecom_bas") == 1:
                        insert_json_to_db(json.dumps(payload))
                        TexecomConnect.log(f"Sent to DB: {event_name}")

                    return
           
            # ==========================================================
            # SWITCH / CONTROL EVENTS (ADD HERE)
            # ==========================================================
            if event_name in {
                "Keyswitch - Latching",
                "Keyswitch - Momentary",
                "Security Key"
            }:
                handle_switch_event(
                    event_name=event_name,
                    group_type_str=group_type_str,
                    parameter=parameter,
                    areas=areas,
                    timestamp=timestamp_str
                )
                return 
            
            # Handle Omit Key separately
            #===========================
            if event_name == "Omit Key":
                
                # Avoid duplicate Omit Key spam
                if OMIT_CONTEXT.get("active"):
                    return
                
                OMIT_CONTEXT["active"] = True
                OMIT_CONTEXT["timestamp"] = time.time()

                if logical_params_module.get_parameter("active_integration_texecom_bas") == 1:
                    insert_json_to_db(json.dumps({
                        "texecom_event": {
                            "event_name": "Omit Key",
                            "state": "Active",
                            "timestamp": timestamp_str
                        }
                    }))
                return
            
            # ==================================================
            # HANDLE ZONE BYPASS / UNBYPASS (ALL ZONE TYPES)
            # ==================================================
            if event_name in ZONE_TYPE_EVENTS and group_type_str in ("Bypassed", "Unbypassed"):

                zone_number = parameter
                state = "Bypassed" if group_type_str == "Bypassed" else "Unbypassed"

                # ---- accumulate context (multi-zone safe) ----
                EVENT_CONTEXT["zones"].add(zone_number)
                EVENT_CONTEXT["zone_states"][zone_number] = state
                EVENT_CONTEXT["last_update"] = time.time()
                
                # -------- emit formatted bypass payload --------
                zone_number = parameter
                zone_state_text = f"Zone {zone_number} {state}"
                
                # ---- emit unified payload (optional delay-based flush) ----
                if logical_params_module.get_parameter("active_integration_texecom_bas") == 1:
                    insert_json_to_db(json.dumps({
                        "texecom_event": {
                            "event_name": event_name,          # ← use actual zone type (Interior, Perimeter, etc.)
                            "zones": zone_number,              # ← single zone, not list
                            "zone_states": zone_state_text,    # ← human readable
                            "timestamp": timestamp_str
                        }
                    }))

                # ---- clear omit-key context once applied ----
                if OMIT_CONTEXT.get("active"):
                    OMIT_CONTEXT["active"] = False
                    OMIT_CONTEXT["timestamp"] = None

                return
            
            # ==================================================
            # PANEL ARM / DISARM (AWAY ARMED)
            # ==================================================
            if event_name == "Open/Close (Away Armed)":

                if "Close" in group_type_str:
                    arm_state = "ARMED"
                elif "Open" in group_type_str:
                    arm_state = "DISARMED"
                else:
                    return

                payload = {
                    "texecom_event": {
                        "event_name": "Panel Arm State",
                        "state": arm_state,
                        "area": areas,
                        "timestamp": timestamp_str
                    }
                }

                if logical_params_module.get_parameter("active_integration_texecom_bas") == 1:
                    insert_json_to_db(json.dumps(payload))
                    TexecomConnect.log(f"Sent to DB: Panel {arm_state}")

                return
           
            # --------------------------------------------------
            # INCIDENT EVENTS → DELAYED UNIFICATION
            # --------------------------------------------------
            if event_name in INCIDENT_EVENTS:

                global PENDING_INCIDENT

                PENDING_INCIDENT = {
                    "event_name": event_name,
                    "bell": bell_state,
                    "timestamp": timestamp_str
                }

                # schedule delayed finalize
                threading.Timer(INCIDENT_DELAY, finalize_incident).start()
                return


        except Exception as e:
            tc.log(f"ERROR decoding LOGEVENT: {e}")
            return

   
class Unbuffered(object):
    def __init__(self, stream):
        self.stream = stream

    def write(self, data):
        self.stream.write(data)
        self.stream.flush()

    def writelines(self, datas):
        self.stream.writelines(datas)
        self.stream.flush()

    def __getattr__(self, attr):
        return getattr(self.stream, attr)


def runTexecomConnect():
    texhost = os.getenv('TEXHOST','192.168.0.25')
    texport = int(os.getenv('TEXPORT',10001))
    udlpassword = os.getenv('UDLPASSWORD','12345')

    sys.stdout = Unbuffered(sys.stdout)
    tc = TexecomConnect(texhost, texport, udlpassword, message_handler)
    tc.event_loop()


if __name__ == '__main__':

    # ACTIVE-INTEGRATION-GUARD: check flag before doing any work
    # If integration is disabled from the menu, exit cleanly.
    # systemd sees exit(0) as success and will NOT restart the service.
    # Service stays enabled — to re-activate, enable from menu then:
    #   sudo systemctl restart dexter-amc-bas
    if logical_params_module.get_parameter("active_integration_texecom_bas") != 1:
        import logging as _lg, sys as _sys
        _lg.getLogger(__name__).info(
            "[texecomConnect.py] active_integration_texecom_bas=0"
            " — integration disabled, exiting cleanly"
        )
        _sys.exit(0)

    # Load Texecom configuration from DB
    device_type = 'TexecomBAS1'
    devices = device_parameters_module.get_device_parameters(device_type)

    if not devices:
        # DEV-01: TexecomBAS1 not in device_config.db.
        # TEX-FIX-1: exit(0) not exit(1) — missing entry is a not-yet-configured
        # state, not a crash. exit(1) triggers Restart=on-failure in the systemd
        # service file, causing the service to restart every 10s indefinitely and
        # flood update.log with the same error message.
        # exit(0) tells systemd the service finished cleanly — no restart.
        # To add the entry: Settings → Active Integration → TEXECOM BAS → Set IP/Port/Pass
        # Or from shell:
        #   python3 -c "import device_parameters_module as d; d.add_device('TexecomBAS1','192.168.0.242','TAXICOM','12345',10001)"
        import logging as _lg
        _lg.getLogger(__name__).warning(
            "[texecomConnect.py] TexecomBAS1 not found in device_config.db "
            "— integration not configured yet. Add it via LCD menu. Exiting cleanly."
        )
        sys.exit(0)

    # DEV-02: get_device_parameters() returns dicts — use key names not index positions.
    # Old code used devices[0][2], devices[0][4], devices[0][5] — broken with dict return.
    texhost     = devices[0]['ip_address']   # Texecom panel IP
    texport     = int(devices[0]['port'])     # TCP port (default 10001)
    udlpassword = devices[0]['password']      # UDL password
    
    print("Texecom IP Address:", texhost)
    print("Texecom Port:", texport)
    logger.info("Texecom credentials loaded — device_type=%s ip=%s port=%d", device_type, texhost, texport)
    
    # Start Texecom client
    sys.stdout = Unbuffered(sys.stdout)
    tc = TexecomConnect(texhost, texport, udlpassword, message_handler)
    
    # SL-01: Deterministic per-panel startup jitter
    # Spreads 5,000 panels across a 300s window — same panel = same delay every reboot.
    jitter = get_jitter_sec(window_sec=300)
    print(f"[startup] Texecom jitter delay = {jitter}s")
    time.sleep(jitter)

    # ---------------- SCHEDULER SETUP ----------------
    # SL-03: Interval tasks — use seconds not .minutes/.hours so jitter applies cleanly.
    # BUG-FIX: schedule.every(20).minutes → every(1200).seconds
    #          schedule.every(10).minutes → every(600).seconds
    #          schedule.every(18).minutes → every(1080).seconds
    schedule.every(1200).seconds.do(lambda: send_texecom_power_status(tc))  # every 20 min
    schedule.every(600).seconds.do(lambda: send_texecom_heartbeat(tc))      # every 10 min
    schedule.every(1080).seconds.do(lambda: send_texecom_time_status(tc))   # every 18 min

    threading.Thread(
        target=scheduler_loop,
        daemon=True
    ).start()
    
    # ---------- START TEXECOM EVENT LOOP ----------
    tc.event_loop()