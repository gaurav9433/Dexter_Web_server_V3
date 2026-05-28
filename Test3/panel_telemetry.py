# -*- coding: utf-8 -*-
# !/usr/local/bin/python
"""
panel_telemetry — ThingsBoard MQTT telemetry publish functions

Extracted from TLChronosProMAIN_391.py as part of Sprint C decomposition.
These functions had zero dependency on hardware globals (lcd, keypad,
shiftRegister buffers, zoneSettings) and could be safely moved.

Public functions:
#   send_to_cavli_subprocess()
#   send_to_ethernet_subprocess()
#   send_to_ethernet_subprocess_new()
#   NetworkSettingsInit()
#   send_imei_id()
#   sendData2TBbattery_voltage()
#   sendData2TBsmps_voltage()
#   sendData2TBsystem_current()
#   sendData2TBLatLong()
#   sendData2TBSystemStatus()
#   calculate_zones_on()
#   count_device_instances()
#   sendData2TB()

Sprint C: Option C — safe partial extraction of stand-alone utility functions.
          Full PanelController decomposition deferred to Sprint C2 (requires
          unit tests first — see OPEN-01).
"""
import json
import sqlite3
import subprocess
import logging
from db_connection import DB_PANEL

from syslog_file_logger import get_dual_logger
log = get_dual_logger(__name__)

# ── Injected at startup by TLChronosProMAIN ──────────────────────────────────
# Call all set_*() functions before using this module.
_mqtt_client      = None
_cavli_db         = None
_network_settings = None
_ds1307           = None       # SDL_DS1307 RTC hardware object
_msg_queue_buffer = None       # MsgQueueBuffer instance
_main_program     = None       # MainProgram instance
_db_handler       = None       # DatabaseHandler instance

def set_mqtt_client(client) -> None:
    """Inject the live MQTT client. Call once at startup."""
    global _mqtt_client
    _mqtt_client = client

def set_cavli_database(db) -> None:
    """Inject the CavliRunningStatusDatabase instance. Call once at startup."""
    global _cavli_db
    _cavli_db = db

def set_network_settings(ns) -> None:
    """Inject the NetworkSettings instance. Call once at startup."""
    global _network_settings
    _network_settings = ns

def set_ds1307(rtc) -> None:
    """Inject the SDL_DS1307 RTC object. Call once at startup."""
    global _ds1307
    _ds1307 = rtc

def set_msg_queue_buffer(buf) -> None:
    """Inject the MsgQueueBuffer instance. Call once at startup."""
    global _msg_queue_buffer
    _msg_queue_buffer = buf

def set_main_program(mp) -> None:
    """Inject the MainProgram instance. Call once at startup."""
    global _main_program
    _main_program = mp

def set_db_handler(dbh) -> None:
    """Inject the DatabaseHandler instance. Call once at startup."""
    global _db_handler
    _db_handler = dbh


def send_to_cavli_subprocess():
    """
    Sends data to the child process using the DatabaseHandler.
    """
    if not _main_program.get_child_status():
        # Child program is not ready. Waiting...
        pass  # This ensures we don't hog the CPU, waiting in a loop
    else:
        next_subtracted_element = _msg_queue_buffer.get_next_subtracted_element()
        if next_subtracted_element:
            # Child status check
            log.debug("[subprocess_new] child status: %s", _main_program.get_child_status() if _main_program else "not injected")
            _main_program.run(next_subtracted_element)
            _msg_queue_buffer.query_and_subtract_first()
        else:
            row_id, json_str = _db_handler.get_json_string()
            if row_id:
                # Child status check
                _main_program.run(json_str)
                _db_handler.mark_as_sent(row_id)
            else:
                # No pending JSON entries found
                pass



# Main function to send data to another process

def send_to_ethernet_subprocess():
    """
    Sends data to the child process using the DatabaseHandler.
    """
    if not _main_program.get_child_status():
        # Child program is not ready. Waiting...
        pass  # This ensures we don't hog the CPU, waiting in a loop
    else:
        next_subtracted_element = _msg_queue_buffer.get_next_subtracted_element()
        if next_subtracted_element:
            # Child status check
            log.debug("[subprocess_new] child status: %s", _main_program.get_child_status() if _main_program else "not injected")
            _main_program.run(next_subtracted_element)
            _msg_queue_buffer.query_and_subtract_first()
        else:
            row_id, json_str = _db_handler.get_json_string()
            if row_id:
                # Child status check
                _main_program.run(json_str)
                _db_handler.mark_as_sent(row_id)
            else:
                # No pending JSON entries found
                pass


# Simulated cloud sending function

def send_to_ethernet_subprocess_new():
    """
    Sends data to the child process using the DatabaseHandler.
    """
    if not _main_program.get_child_status():
        pass  # Child program is not ready. Waiting...
    else:
        next_subtracted_element = _msg_queue_buffer.get_next_subtracted_element()
        if next_subtracted_element:
            # Structural: replaced subprocess.Popen(['python', 'helper_script.py', ...])
            # with direct import and function call.
            try:
                import helper_script
                helper_script.run(next_subtracted_element)
            except Exception as e:
                log.error("[send_to_ethernet_subprocess_new] %s", e)

            # Query and subtract the first added element
            _msg_queue_buffer.query_and_subtract_first()            
            log.debug("[subprocess_new] child status: %s", _main_program.get_child_status() if _main_program else "not injected")
            _main_program.run(next_subtracted_element)
            _msg_queue_buffer.query_and_subtract_first()
        else:
            row_id, json_str = _db_handler.get_json_string()
            if row_id:
                # Child status check
                _main_program.run(json_str)
                _db_handler.mark_as_sent(row_id)
            else:
                # No pending JSON entries found
                pass




def NetworkSettingsInit():
    # BUG-03 FIX: network_settings was a local variable in TLChronosProMAIN __main__.
    # It is now injected via set_network_settings() and accessed as _network_settings.
    if _network_settings is None:
        log.error("[NetworkSettingsInit] network_settings not injected — call set_network_settings() at startup")
        return
    network_settings = _network_settings  # local alias for readability

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


    # Print or use the variables as needed



def send_imei_id(value):

        
    '''
    {
        "imei_id":{
				    "dev_id":double	    //double integer data, Range 0-30					
			}
    }

    '''
    # TEL-FIX-3: removed nested "imei_id" wrapper — flat key for ThingsBoard.
    _msg_queue_buffer.add(json.dumps({"dev_id": value}))



def sendData2TBbattery_voltage(value):

        
    '''
    {
        "battery_status":{
				    "battery_voltage":double	    //double integer data, Range 0-30					
			}
    }

    '''
    # TEL-FIX-3: removed nested "battery_status" wrapper — flat key for ThingsBoard.
    _msg_queue_buffer.add(json.dumps({"battery_voltage": value}))
    


def sendData2TBsmps_voltage(value):

    '''
    {
        "ac_status":{
                            "ac_voltage":double,		//double integer data, Range 0-30
                    }
    }
    '''

    # TEL-FIX-3: removed nested "ac_status" wrapper — flat key for ThingsBoard.
    _msg_queue_buffer.add(json.dumps({"ac_voltage": value}))



def sendData2TBsystem_current(value):

    '''
    {
        "current_status":{
					"system_current":double		//double integer data, Range 0-5
			}
    }
    '''

    # TEL-FIX-3: removed nested "current_status" wrapper — flat key for ThingsBoard.
    _msg_queue_buffer.add(json.dumps({"system_current": value}))
    


def sendData2TBLatLong(lat, lon):
        
    payload="{"
    payload+="\"lat\":"
    payload+=str(lat)
    payload+=","
    payload+="\"lon\":"
    payload+=str(lon)
    payload+="}"
        
    _msg_queue_buffer.add(payload)



def sendData2TBSystemStatus(    statusbox_system_on_t = "false",
                                statusbox_system_healthy_t = "false",
                                statusbox_mains_on_t = "false",
                                statusbox_battery_reverse_t = "false",
                                statusbox_battery_low_t = "false",
                                statusbox_sos_status_t = "false",
                                statusbox_network_t_t = 'NA',
                                statusbox_no_of_connected_device_t = 0):


    #statusbox_system_on_t = "false"
    #statusbox_system_healthy_t = "false"
    #statusbox_mains_on_t = "false"
    #password_tamper_sms_t = "false"
    #statusbox_battery_reverse_t = "false"
    #statusbox_battery_low_t = "false"
    #statusbox_sos_status_t = "false"
    #statusbox_network_t = "false"
    #statusbox_no_of_connected_device_t = "false"

    # TEL-FIX-1: removed nested "system_status" wrapper.
    # Each statusbox_* key must be a flat top-level ThingsBoard time-series key.
    # The old nested payload {"system_status": {...}} caused ThingsBoard to store
    # a single JSON-object value instead of individual keys in Latest Telemetry.
    # Matches the flat-dict format already used in TLChronosProMAIN_391.py.
    payload = json.dumps({
        "statusbox_system_on":              statusbox_system_on_t,
        "statusbox_system_healthy":         statusbox_system_healthy_t,
        "statusbox_mains_on":               statusbox_mains_on_t,
        "statusbox_battery_reverse":        statusbox_battery_reverse_t,
        "statusbox_battery_low":            statusbox_battery_low_t,
        "statusbox_sos_status":             statusbox_sos_status_t,
        "statusbox_network":                statusbox_network_t_t,
        "statusbox_no_of_connected_device": statusbox_no_of_connected_device_t,
    })

    _msg_queue_buffer.add(payload)

    #cloudDataSendingOptions(dataSendingOption, payload)



def calculate_zones_on():
    

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
    
    # Database path — absolute DB_PANEL from db_connection.py
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

    # BUG FIX: powerZoneSettingsOnCounter was a bare global from TLChronosProMAIN.
    # This function already calculates zones_on from the DB query above
    # (total_power_on_counts). Using the DB result removes the global dependency
    # and is architecturally correct — the function queries the DB, it returns the DB result.
    zones_on = total_power_on_counts

    # Closing the connection
    connection.close()

    return zones_on

    # Example usage
    #zones_on = calculate_zones_on()


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




#def check_hikvision_nvr():
#    device_type = 'HikvisionNVR1'
#    devices = device_parameters_module.get_device_parameters(device_type)
#    ipaddress = devices[0][2]
#    userid = devices[0][3]
#    password = devices[0][4]

#    try:
        # Using the hikvisionapi.Client to connect
#        cam = Client('http://{}'.format(ipaddress), userid, password)
        # Testing a basic API endpoint
#        response = cam.System.deviceInfo(method='get')
#        if response and response.status_code == 200:
#            return "Active"
#        else:
#            return "Inactive"

#    except requests.exceptions.RequestException as e:
#        return "Inactive"

#    except Exception as e:
#        return "Inactive"

# Example usage


def sendData2TB(log_type):
    # BUG FIX: ds1307 was referenced as a bare global from TLChronosProMAIN __main__ block.
    # It is now injected via set_ds1307(). Falls back to datetime.now() if not injected.
    _rtc = _ds1307

    if _rtc is not None:
        try:
            rtcYear = _rtc._read_year()
        except (IOError, ValueError):
            rtcYear = 0
        try:
            rtcMonth = _rtc._read_month()
        except (IOError, ValueError):
            rtcMonth = 0
        try:
            rtcDate = _rtc._read_date()
        except (IOError, ValueError):
            rtcDate = 0
        try:
            rtcHour = _rtc._read_hours()
        except (IOError, ValueError):
            rtcHour = 0
        try:
            rtcMinute = _rtc._read_minutes()
        except (IOError, ValueError):
            rtcMinute = 0
        try:
            rtcSecound = _rtc._read_seconds()
        except (IOError, ValueError):
            rtcSecound = 0
    else:
        # Fallback: use system clock when RTC hardware not available
        from datetime import datetime as _dt
        _now = _dt.now()
        rtcYear   = _now.year % 100
        rtcMonth  = _now.month
        rtcDate   = _now.day
        rtcHour   = _now.hour
        rtcMinute = _now.minute
        rtcSecound = _now.second

    zone_no_t = "null"

    # TEL-FIX-2: zero-pad date and time to match TLChronosProMAIN_391.py format.
    # Old code produced "1:4:24" — ThingsBoard and dashboard parsers expect "01:04:24".
    # Removed dead random day/month/year/hr/mn variables — they were never used.
    # Removed "branch" key — not part of Telemetry Format Spec v1.0 Category 1 Event Log.
    date    = (str(rtcDate).zfill(2)   + ":" +
               str(rtcMonth).zfill(2)  + ":" +
               str(rtcYear).zfill(2))
    timenow = (str(rtcHour).zfill(2)   + ":" +
               str(rtcMinute).zfill(2))

    if isinstance(log_type, (dict, list)):
        log_type_t = json.dumps(log_type)
    else:
        log_type_t = '"' + str(log_type) + '"'

    payload = ('{"log_type":' + log_type_t +
               ',"zone_no":null' +
               ',"date":"'  + date    + '"' +
               ',"time":"'  + timenow + '"}')

    _msg_queue_buffer.add(payload)
