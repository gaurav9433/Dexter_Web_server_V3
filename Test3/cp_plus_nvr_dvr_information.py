# -*- coding: utf-8 -*-
# !/usr/local/bin/python
# New Code for Dahua NVR Info (7i)

import requests
from requests.auth import HTTPDigestAuth
from urllib3.exceptions import InsecureRequestWarning
from requests.exceptions import ConnectionError  # Import ConnectionError

import warnings
import json
import time
from datetime import datetime, timedelta
from datetime import datetime, timezone

import schedule 
import sqlite3
from scheduler_utils import get_jitter_sec, is_rpi_idle
from datetime import date

import threading
import os
import sys
from datetime import datetime

# Suppress SSL warnings
requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

# DB-03: insert_json_to_db enforces 50K row hard cap + TTL purge
from buffer_manager import insert_json_to_db, init_db
init_db()  # Create buffer table if it does not exist yet
import device_parameters_module

import logical_params_module
# Initialize the database
logical_params_module.initialize_database()


#------------------------------------------------- Watchdog Timer-------------------------------------------
# CQ-01: SoftwareWatchdog centralised in watchdog_manager.py
from watchdog_manager import SoftwareWatchdog

from syslog_file_logger import get_dual_logger
log = get_dual_logger('cp_plus_nvr_dvr_information')
watchdog = SoftwareWatchdog(timeout=3600)
#-------------------------------------------------------------------------------------------------------------

#--------------------------------------Getting Parameters from Database---------------------------------------
device_type = 'CP_PlusNVR1'
devices = device_parameters_module.get_device_parameters(device_type)

if not devices:
    log.error("No device credentials found for 'CP_PlusNVR1' "
              "— add device via device_parameters_module")
    sys.exit(1)
ipaddress = devices[0]['ip_address']
userid = devices[0]['username']
password = devices[0]['password']

#print("IP Address: {}".format(ipaddress))
#print("User Name: {}".format(userid))
#print("Password: {}".format(password))
#---------------------------------------------------------------------------------------------------------------

#------------------------------------------- CP Plus Make NVR Initilise-----------------------------------------
def initExternalDevice():

    def sendParameters():

        def checkHBRT():

            url = f"http://{ipaddress}/cgi-bin/magicBox.cgi?action=getVendor"

            def _send_linkfail(reason=""):
                hb_type = "CP_PlusNVR_LinkFail"
                hb_payload = "{\"CP_PlusNVR_Heartbeat\":\"" + hb_type + "\""  + "}"
                log.error("CP_PlusNVR LinkFail — %s", reason)
                if logical_params_module.get_parameter("active_integration_cp_plus_nvr") == 1:
                    insert_json_to_db(hb_payload)

            try:
                response = requests.get(url, auth=HTTPDigestAuth(userid, password), verify=False, timeout=10)

                if response.status_code == 200:
                    Heartbeat_t = "CP_PlusNVR_on"
                    payload = "{\"CP_PlusNVR_Heartbeat\":\"" + Heartbeat_t + "\"}"
                    if logical_params_module.get_parameter("active_integration_cp_plus_nvr") == 1:
                        insert_json_to_db(payload)
                    print(payload)

                elif response.status_code == 401:
                    _send_linkfail("HTTP 401 — authentication failed")
                elif response.status_code == 403:
                    _send_linkfail("HTTP 403 — access forbidden")
                else:
                    _send_linkfail(f"HTTP {response.status_code}")

            except requests.RequestException as e:
                _send_linkfail(str(e))
        
        def sendTime():
            time.sleep(30.0)        
            # Initialize the CP Plus NVR DVR
            try:
                url = f"http://{ipaddress}/cgi-bin/global.cgi?action=getCurrentTime"
                response = requests.get(url, auth=HTTPDigestAuth(userid, password), verify=False, timeout=10)
                #print(response)
            except Exception as e:
#                print("Error while initializing the camera client:", e)
                pass

        checkHBRT()
        sendTime()

    sendParameters()
#-------------------------------------------------------------------------------------------------------------

#------------------------------------ Getting HDD Info from CP_Plus Make NVR------------------------------------
def cp_plus_get_hdd_info():
    # Ensure these are always initialized
    total_bytes = "NA"
    used_bytes = "NA"
    serial_number = None
    device_type = None
    
    payload = {}
    
    try:
        # First URL - Fetch SD card details
        url_1 = f"http://{ipaddress}/cgi-bin/storageDevice.cgi?action=getDeviceAllInfo"
        response_sd = requests.get(url_1, auth=HTTPDigestAuth(userid, password), verify=False)
    
        # Check if the response_sd status is OK (200)
        response_sd.raise_for_status()

        # Manually parse the plain-text response_sd (not JSON)
        response_text = response_sd.text

        # Initialize a dictionary to store parsed SD card information
        parsed_info = {}

        # Split the response_sd into lines and process each line
        lines = response_text.splitlines()

        for line in lines:
            # Skip empty lines
            if not line.strip():
                continue

            # Split the line by '=' to extract key-value pairs
            key_value = line.split('=')
            if len(key_value) == 2:
                key = key_value[0].strip()
                value = key_value[1].strip()

                # Store the key-value pairs in the dictionary
                parsed_info[key] = value


        # Process each slot (assuming 0 to 3 for 4 HDD slots)
        for i in range(4):
            total_bytes_key = f'list.info[{i}].Detail[0].TotalBytes'
            used_bytes_key = f'list.info[{i}].Detail[0].UsedBytes'
            path_key = f'list.info[{i}].Path'  # Optional key for slot identification

            total_bytes = parsed_info.get(total_bytes_key, "NA")
            used_bytes = parsed_info.get(used_bytes_key, "NA")
            path = parsed_info.get(path_key, f"Slot_{i+1}")  # Use default slot name if path not available

            try:
                total_bytes = str(float(total_bytes))
            except (ValueError, TypeError):
                total_bytes = "NA"

            try:
                used_bytes = str(float(used_bytes))
            except (ValueError, TypeError):
                used_bytes = "NA"
            
            payload[f"CP_Plus_NVR_Details[{i}]"] = {
                "CP_Plus_NVR_capacity": total_bytes,
                "CP_Plus_NVR_NoOfHDDSlots": path,
                "CP_Plus_NVR_freeSpace": used_bytes
            }
            
        # Final payload wrapper
        deviceAllInfo = {
            "CP_Plus_NVR_deviceAllInfo": payload
        }

        attributes_json = json.dumps(deviceAllInfo, indent=4)
        if logical_params_module.get_parameter("active_integration_cp_plus_nvr") == 1:
            
            insert_json_to_db(attributes_json)
        
        log.info(attributes_json)
#        return attributes_json

    except requests.exceptions.RequestException as e:
        #print(f"Error fetching cp_plus NVR info: {e}")
        return None
#------------------------------------------------------------------------------------------------------------------
def cp_plus_get_hdd_info2():

    import re
    payload = {}

    try:
        url_1 = f"http://{ipaddress}/cgi-bin/storageDevice.cgi?action=getDeviceAllInfo"
        response_sd = requests.get(
            url_1,
            auth=HTTPDigestAuth(userid, password),
            verify=False
        )

        response_sd.raise_for_status()

        response_text = response_sd.text
        parsed_info = {}

        # -------------------------
        # Parse Plain Text Response
        # -------------------------
        for line in response_text.splitlines():
            if not line.strip():
                continue

            key_value = line.split('=')
            if len(key_value) == 2:
                key = key_value[0].strip()
                value = key_value[1].strip()
                parsed_info[key] = value

        # -------------------------
        # Detect all list.info[x]
        # -------------------------
        info_indexes = set()

        for key in parsed_info.keys():
            match = re.match(r'list\.info\[(\d+)\]', key)
            if match:
                info_indexes.add(int(match.group(1)))

        info_indexes = sorted(info_indexes)

        # -------------------------
        # Loop Only Main Slot
        # -------------------------
        for i in info_indexes:

            total_bytes_sum = 0
            used_bytes_sum = 0

            # Find all Detail[y] under this slot
            for key in parsed_info.keys():
                match = re.match(rf'list\.info\[{i}\]\.Detail\[(\d+)\]\.TotalBytes', key)
                if match:
                    j = match.group(1)

                    total_key = f'list.info[{i}].Detail[{j}].TotalBytes'
                    used_key = f'list.info[{i}].Detail[{j}].UsedBytes'

                    try:
                        total_bytes_sum += int(float(parsed_info.get(total_key, 0)))
                        used_bytes_sum += int(float(parsed_info.get(used_key, 0)))
                    except:
                        continue

            free_bytes = total_bytes_sum - used_bytes_sum

            payload[f"CP_Plus_NVR_Details[{i}]"] = {
                "CP_Plus_NVR_SlotNumber": i + 1,
                "CP_Plus_NVR_Total_Bytes": total_bytes_sum,
                "CP_Plus_NVR_Used_Bytes": used_bytes_sum,
                "CP_Plus_NVR_Free_Bytes": free_bytes
            }

        # -------------------------
        # Final JSON Wrapper
        # -------------------------
        deviceAllInfo = {
            "CP_Plus_NVR_deviceAllInfo": payload
        }

        attributes_json = json.dumps(deviceAllInfo, indent=4)
        log.info(attributes_json)

        if logical_params_module.get_parameter("active_integration_cp_plus_nvr") == 1:
            insert_json_to_db(attributes_json)

    except requests.exceptions.RequestException:
        return None
#------------------------------------ Getting Camera Info from CP_Plus Make NVR------------------------------------
def cp_plus_get_camera_info():

    url_1 = f'http://{ipaddress}/cgi-bin/configManager.cgi?action=getConfig&name=Encode'
    url_2 = f'http://{ipaddress}/cgi-bin/LogicDeviceManager.cgi?action=getCameraAll'

    resolutions = ["NA"] * 16
    fps_values = ["NA"] * 16
    
    encode_data = {}
    camera_info = {}

    # ----------- Parse Encode Info -----------
    try:
        response = requests.get(url_1, auth=HTTPDigestAuth(userid, password), verify=False, timeout=10)

        if response.status_code == 200:
            raw_lines = response.text.strip().splitlines()
            parsed_data = {}

            for line in raw_lines:
                if '=' in line:
                    key, value = line.split('=', 1)
                    key_parts = key.strip().split('.')
                    current_level = parsed_data

                    # Build nested dictionaries based on key parts
                    for part in key_parts[:-1]:
                        current_level = current_level.setdefault(part, {})
                    current_level[key_parts[-1]] = value.strip()

            encode_data = {}
            for i in range(16):
                encode_key = f"Encode[{i}]"
                try:
                    video_config = parsed_data["table"][encode_key]["MainFormat[0]"]["Video"]
                    encode_data[i] = {
                        "resolution": video_config.get("resolution", "NA"),
                        "fps": video_config.get("FPS", "NA")
                    }
                except KeyError:
                   # print(f"Missing or invalid data for {encode_key}")
                    encode_data[i] = {"resolution": "NA", "fps": "NA"}

            # Print each encode's resolution and FPS
            for i, v in encode_data.items():
                log.info(f"Encode[{i}] - Resolution: {v['resolution']}, FPS: {v['fps']}")

            # Optionally, show Encode[1] resolution
            #print("\nEncode[1] Resolution:", encode_data[1]["resolution"])

            # Set global resolution and FPS arrays
            resolutions = [encode_data[i]["resolution"] for i in range(16)]
            fps_values = [encode_data[i]["fps"] for i in range(16)]

            # Construct JSON payload
            payload_dict = {
                #f"DahuaNVR_Encode[{i}]": {
                f"CP_PlusNVR_Encode[{i}]": {
                    "resolutions": resolutions[i],
                    "fps": fps_values[i]
                } for i in range(16)
            }

            payload = json.dumps(payload_dict, indent=4)
           # print(payload)

            # insert_json_to_db(payload)  # Uncomment if needed

        elif response.status_code == 401:
            log.error("Authentication failed. Please check your credentials.")
        elif response.status_code == 403:
            log.error("Access forbidden. The digest authorization information is incorrect.")
        else:
            log.error("Failed to get a valid response. Status code:", response.status_code)

    except requests.RequestException as e:
        log.error("An error occurred:", e)

    # ----------- Parse Camera Info -----------
    try:
        response = requests.get(url_2, auth=HTTPDigestAuth(userid, password), verify=False, timeout=10)
        if response.status_code == 200:
            raw_lines = response.text.strip().splitlines()
            parsed_data = {}

            for line in raw_lines:
                if '=' in line:
                    key, value = line.split('=', 1)
                    parsed_data[key.strip()] = value.strip()

            for i in range(16):
                name_key = f"camera[{i}].DeviceInfo.Name"
                address_key = f"camera[{i}].DeviceInfo.Address"
                name = parsed_data.get(name_key, "NA")
                address = parsed_data.get(address_key, "NA")
                camera_info[i] = {
                    "name": name,
                    "address": address
                }
    except Exception as e:
        log.error("Camera info error:", e)

    # ----------- Final Combined Payload -----------
    payload_dict = {}
    attributes_json = None
    for cam_num in range(1, 17):
        i = cam_num - 1
        payload_dict[str(cam_num)] = {
            "CP_Plus_NVR_Address": camera_info.get(i, {}).get("address", "NA"),
            "CP_Plus_NVR_Resolutions": resolutions[i],
            "CP_Plus_NVR_FPS_Values": fps_values[i],
            "CP_Plus_NVR_Name": camera_info.get(i, {}).get("name", "NA")
        }
    # Final payload wrapper
        deviceCamInfo = {
            "CP_Plus_NVR_cameraInfo": payload_dict
        }

        attributes_json = json.dumps(deviceCamInfo)
    if logical_params_module.get_parameter("active_integration_cp_plus_nvr") == 1: 
        insert_json_to_db(attributes_json)
        
        log.info(attributes_json)
#        return attributes_json
#----------------------------------------------------------------------------------------------------------------

#------------------------------------ Getting Device Name from CP_Plus Make NVR------------------------------------
def cp_plus_get_device_name():
    url_1 =f'http://{ipaddress}/cgi-bin/magicBox.cgi?action=getMachineName'  # Device Name

    try:
        response = requests.get(url_1, auth=HTTPDigestAuth(userid, password), verify=False, timeout=10)
        
        if response.status_code == 200:
            device_name = "NA"
            for line in response.text.strip().splitlines():
                if line.startswith("name="):
                    device_name = line.split("=", 1)[1].strip()

                    #print("Device Name:", device_name)
                    return device_name

            # Final payload wrapper
            deviceName = {
                "CP_Plus_NVR_deviceName": device_name
            }

            attributes_json = json.dumps(deviceName)
            if logical_params_module.get_parameter("active_integration_cp_plus_nvr") == 1:
                insert_json_to_db(attributes_json)
        
            print(attributes_json)   #
            
        else:
            print("Failed to get device name. Status:", response.status_code)

    except Exception as e:
        log.error("Error while getting device name:", str(e))

    return "NA"
#--------------------------------------------------------------------------------------------------------------------

#------------------------------------ Getting Device Type, Sl No, processor, Model Name from CP_Plus Make NVR----------
#def dahua_get_device_info():
def cp_plus_get_device_info():
    url = f'http://{ipaddress}/cgi-bin/magicBox.cgi?action=getSystemInfo'

    try:
        response = requests.get(url, auth=HTTPDigestAuth(userid, password), verify=False, timeout=10)

        if response.status_code == 200:
            info = {}
            for line in response.text.strip().splitlines():
                if '=' in line:
                    key, value = line.strip().split('=', 1)
                    info[key] = value
            
             # Map system keys to TB attribute keys
            device_info_map = {
                "serialNumber": "CP_Plus_NVR_SerialNumber",
                "deviceType": "CP_Plus_NVR_DeviceType",
                "processor": "CP_Plus_NVR_Processor",
                "updateSerial": "CP_Plus_NVR_Model"
            }

            for sys_key, tb_key in device_info_map.items():
                value = info.get(sys_key, "NA")
                attributes_json = json.dumps({tb_key: value})
                if logical_params_module.get_parameter("active_integration_cp_plus_nvr") == 1:
                    insert_json_to_db(attributes_json)
                print(attributes_json)     

            return info
        else:
            print(f"Failed to get system info. Status: {response.status_code}")
    except Exception as e:
        log.error("Error while getting system info:", str(e))

    return {}
#--------------------------------------------------------------------------------------------------------------------

#------------------------------------ Getting Firmware version & mfg date from CP_Plus Make NVR------------------------
def cp_plus_get_firmware_version():
    
    url = f'http://{ipaddress}/cgi-bin/magicBox.cgi?action=getSoftwareVersion'

    try:
        response = requests.get(url, auth=HTTPDigestAuth(userid, password), verify=False, timeout=10)

        if response.status_code == 200:
            info = {}
            for line in response.text.strip().splitlines():
                if '=' in line:
                    key, value = line.strip().split('=', 1)
                    info[key] = value

            version_string = info.get("version", "")
            version_part = "NA"
            build_part = "NA"

            if ',' in version_string:
                parts = version_string.split(',')
                version_part = parts[0].strip()
                for part in parts:
                    if part.strip().startswith("build:"):
                        build_part = part.strip().split("build:")[1]

            # Construct payloads one-by-one
            payloads = {
                "CP_Plus_NVR_Firmware_Version": version_part,
                "CP_Plus_NVR_mfg": build_part
            }

            for key, value in payloads.items():
                attributes_json = json.dumps({key: value})
                if logical_params_module.get_parameter("active_integration_cp_plus_nvr") == 1:
                    insert_json_to_db(attributes_json)
                print(attributes_json)    #

            return info
        else:
            print(f"Failed to get version info. Status: {response.status_code}")
    except Exception as e:
        log.error("Error while getting version info:", str(e))

    return {}
#---------------------------------------------------------------------------------------------------------------------

#------------------------------------ Getting Hardware Version from CP_Plus Make NVR------------------------------------
#def dahua_get_hardware_version():
def cp_plus_get_hardware_version():
    
    url = f'http://{ipaddress}/cgi-bin/magicBox.cgi?action=getHardwareVersion'

    try:
        response = requests.get(url, auth=HTTPDigestAuth(userid, password), verify=False, timeout=10)

        if response.status_code == 200:
            info = {}
            for line in response.text.strip().splitlines():
                if '=' in line:
                    key, value = line.strip().split('=', 1)
                    info[key] = value

            # Create payload with specific key
            attributes_json = json.dumps({
                "CP_Plus_NVR_Hardware_Version": info.get("version", "NA")
            })

            if logical_params_module.get_parameter("active_integration_cp_plus_nvr") == 1:
                insert_json_to_db(attributes_json)

            print(attributes_json)    #
            return info
        else:
            print(f"Failed to get version info. Status: {response.status_code}")
    except Exception as e:
        log.error("Error while getting version info:", str(e))

    return {}
#-----------------------------------------------------------------------------------------------------------------

#------------------------------------ Getting Manufacturar from CP_Plus Make NVR------------------------------------
def dahua_get_manufacturar():
    
    url = f'http://{ipaddress}/cgi-bin/magicBox.cgi?action=getVendor'

    try:
        response = requests.get(url, auth=HTTPDigestAuth(userid, password), verify=False, timeout=10)

        if response.status_code == 200:
            info = {}
            for line in response.text.strip().splitlines():
                if '=' in line:
                    key, value = line.strip().split('=', 1)
                    info[key] = value

            # Create payload with specific key
            attributes_json = json.dumps({
                "CP_Plus_NVR_Manufacturer": info.get("vendor", "NA")
            })

            if logical_params_module.get_parameter("active_integration_cp_plus_nvr") == 1:
                insert_json_to_db(attributes_json)

            #print(attributes_json)
            return info
        else:
            print(f"Failed to get vendor Status: {response.status_code}")
    except Exception as e:
        log.error("Error while getting vendor:", str(e))

    return {}
#----------------------------------------------------------------------------------------------------------------

#------------------------------------ Getting Date & Time from CP_Plus Make NVR------------------------------------
def cp_plus_get_current_time():
    
    url = f'http://{ipaddress}/cgi-bin/global.cgi?action=getCurrentTime'

    try:
        response = requests.get(url, auth=HTTPDigestAuth(userid, password), verify=False, timeout=10)

        if response.status_code == 200:
            info = {}
            for line in response.text.strip().splitlines():
                if '=' in line:
                    key, value = line.strip().split('=', 1)
                    info[key] = value

            datetime_str = info.get("result", "")
            date_part = "NA"
            time_part = "NA"

            if ' ' in datetime_str:
                date_part, time_part = datetime_str.split(' ', 1)

            payloads = {
                "CP_Plus_NVR_Date": date_part,
                "CP_Plus_NVR_Time": time_part
            }

            for key, value in payloads.items():
                attributes_json = json.dumps({key: value})
                if logical_params_module.get_parameter("active_integration_cp_plus_nvr") == 1:
                    insert_json_to_db(attributes_json)
                print(attributes_json) #

            return info
        else:
            print(f"Failed to get current time. Status: {response.status_code}")
    except Exception as e:
        log.error("Error while getting current time:", str(e))

    return {}
#-------------------------------------------------------------------------------------------------------------
#-------------------------------------------------------------------------------------------------------------
def cp_plus_collect_all_system_info():
    try:
        if logical_params_module.get_parameter("active_integration_cp_plus_nvr") != 1:
            #print("Integration not active.")
            return

        payloads = {}

        # Device Name
        try:
            url = f"http://{ipaddress}/cgi-bin/magicBox.cgi?action=getMachineName"
            response = requests.get(url, auth=HTTPDigestAuth(userid, password), verify=False, timeout=10)
            if response.status_code == 200:
                for line in response.text.strip().splitlines():
                    if '=' in line:
                        key, value = line.strip().split('=', 1)
                        if key.strip() == "name":
                            payloads["CP_Plus_NVR_Device_Name"] = value.strip()
        except Exception as e:
            log.error("Device Name Error:", str(e))

        # Device Info (serial, type, processor, model)
        try:
            url = f"http://{ipaddress}/cgi-bin/magicBox.cgi?action=getSystemInfoNew"
            response = requests.get(url, auth=HTTPDigestAuth(userid, password), verify=False, timeout=10)
            if response.status_code == 200:
                info = {}
                for line in response.text.strip().splitlines():
                    if '=' in line:
                        key, value = line.strip().split('=', 1)
                        info[key] = value

                payloads["CP_Plus_NVR_SerialNumber"] = info.get("serialNumber", "NA")
                payloads["CP_Plus_NVR_DeviceType"] = info.get("deviceType", "NA")
                payloads["CP_Plus_NVR_Processor"] = info.get("processor", "NA")
                payloads["CP_Plus_NVR_Model"] = info.get("updateSerial", "NA")
        except Exception as e:
            log.error("Device Info Error:", str(e))

        # Firmware Version
        try:
            #url = f"http://{ipaddress}/cgi-bin/magicBox.cgi?action=getSystemVersion"
            url = f"http://{ipaddress}/cgi-bin/magicBox.cgi?action=getSoftwareVersion"
           # /cgi-bin/magicBox.cgi?action=getSoftwareVersion

            response = requests.get(url, auth=HTTPDigestAuth(userid, password), verify=False, timeout=10)

            if response.status_code == 200:
                    for line in response.text.strip().splitlines():
                        if '=' in line:
                            key, value = line.strip().split('=', 1)
                            if key.strip() == "version":
                                version_full = value.strip()
                                version_clean = version_full.split(",build:")[0]  # Remove build part
                                payloads["CP_Plus_NVR_Firmware_Version"] = version_clean
                                if "build:" in version_full:
                                    build_date = version_full.split("build:")[-1]
                                    payloads["CP_Plus_NVR_mfg"] = build_date


        #    if response.status_code == 200:
        #        for line in response.text.strip().splitlines():
        #            if '=' in line:
        #                key, value = line.strip().split('=', 1)
        #                if key.strip() == "BuildDate":
        #                    payloads["Dahua_NVR_Firmware_Version"] = value.strip()
        except Exception as e:
            log.error("Firmware Version Error:", str(e))

        # Hardware Version
        try:
            #url = f"http://{ipaddress}/cgi-bin/magicBox.cgi?action=getSoftwareVersion"
            url = f"http://{ipaddress}/cgi-bin/magicBox.cgi?action=getHardwareVersion"

            response = requests.get(url, auth=HTTPDigestAuth(userid, password), verify=False, timeout=10)
            if response.status_code == 200:
                for line in response.text.strip().splitlines():
                    if '=' in line:
                        key, value = line.strip().split('=', 1)
                        if key.strip() == "version":
                            version_full = value.strip()
                            version_clean = version_full.split(",build:")[0]  # Remove build part
                            payloads["CP_Plus_NVR_Hardware_Version"] = version_clean
                            if "build:" in version_full:
                                build_date = version_full.split("build:")[-1]
                                payloads["CP_Plus_NVR_mfg"] = build_date
        except Exception as e:
            log.error("Hardware Version Error:", str(e))

        # Current Time (Date and Time separately)
        try:
            url = f"http://{ipaddress}/cgi-bin/magicBox.cgi?action=getVendor"
            response = requests.get(url, auth=HTTPDigestAuth(userid, password), verify=False, timeout=10)
            if response.status_code == 200:
                for line in response.text.strip().splitlines():
                    if '=' in line:
                        key, value = line.strip().split('=', 1)
                        if key.strip() == "vendor":
                            vendor = value.strip()
                            payloads["CP_Plus_NVR_Manufacturer"] = vendor
        except Exception as e:
            log.error("Time Info Error:", str(e))

        # --- Send Each Key Individually ---
        for key, value in payloads.items():
            attributes_json = json.dumps({key: value})
            insert_json_to_db(attributes_json)
            log.info(attributes_json)

    except Exception as e:
        log.error("Unexpected Error in collection:", str(e))

#-------------------------------------------------------------------------------------------------------------
#-------------------------------------------------------------------------------------------------------------
if __name__ == '__main__':

    # Exit 0 immediately if integration is disabled — Docker restart:on-failure
    # will not relaunch on exit 0, keeping the container in "disabled" state.
    if logical_params_module.get_parameter("active_integration_cp_plus_nvr") != 1:
        import logging as _log
        _log.getLogger(__name__).info(
            "[cp_plus_nvr_dvr_information.py] active_integration_cp_plus_nvr=0 "
            "-- integration disabled, exiting cleanly"
        )
        import sys as _sys
        _sys.exit(0)

    initExternalDevice()
    # JITTER: deterministic per-panel startup delay
    jitter = get_jitter_sec(window_sec=300)
    time.sleep(jitter)

    # Run interval tasks once at startup
    initExternalDevice()
    cp_plus_get_device_info()
    cp_plus_get_current_time()
    cp_plus_get_camera_info()
    cp_plus_get_hdd_info2()
    cp_plus_collect_all_system_info()

    # BUG FIX: was every(2).minutes — changed to every(300).seconds (5 min)
    # INTERVAL tasks
    schedule.every(300).seconds.do(initExternalDevice)      # heartbeat — every 5 min
    schedule.every(900).seconds.do(cp_plus_get_current_time) # time sync — every 15 min

    # DAILY tasks — load-gated (replaces fixed 17:25, 17:30, 17:45)
    _daily_sent_date_cp = [None]

    def maybe_send_daily_cp():
        today = date.today()
        if _daily_sent_date_cp[0] == today:
            return
        if not is_rpi_idle():
            log.debug("[daily] CP Plus — RPi busy, deferring")
            return
        log.info("[daily] CP Plus — running daily tasks")
        cp_plus_get_camera_info()
        cp_plus_get_hdd_info2()
        cp_plus_collect_all_system_info()
        _daily_sent_date_cp[0] = today

    schedule.every(60).seconds.do(maybe_send_daily_cp)

    try:
        while True:
            time.sleep(10)
            schedule.run_pending()
            watchdog.reset()
    except KeyboardInterrupt:
        log.info("\nExiting program...")
