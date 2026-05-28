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
from datetime import datetime

import schedule

import sqlite3

import threading
import os
import sys

# Suppress SSL warnings
requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

# DB-03: insert_json_to_db enforces 50K row hard cap + TTL purge
from buffer_manager import insert_json_to_db, init_db

from scheduler_utils import get_jitter_sec, is_rpi_idle
init_db()  # Create buffer table if it does not exist yet
import device_parameters_module

import logical_params_module
# Initialize the database
logical_params_module.initialize_database()


#------------------------------------------------- Watchdog Timer-------------------------------------------
# CQ-01: SoftwareWatchdog centralised in watchdog_manager.py
from watchdog_manager import SoftwareWatchdog

from syslog_file_logger import get_dual_logger
log = get_dual_logger('dahua_nvr_dvr_information')
watchdog = SoftwareWatchdog(timeout=3600)
#-------------------------------------------------------------------------------------------------------------

#--------------------------------------Getting Parameters from Database---------------------------------------
# REC-FIX-3: credential fetch moved inside __main__ after integration flag check.
device_type = 'DahuaNVR1'
#-------------------------------------------------------------------------------------------------------------

#------------------------------------------- Dahua Make NVR Initilise-----------------------------------------
def initExternalDevice():

    print(" Initialise Devices ")

    def sendParameters():

        def checkHBRT():

            url = f"http://{ipaddress}/cgi-bin/magicBox.cgi?action=getVendor"

            def _send_linkfail(reason=""):
                hb_type = "DahuaNVR_LinkFail"
                hb_payload = "{\"DahuaNVR_Heartbeat\":\"" + hb_type + "\"}"
                log.error("DahuaNVR LinkFail — %s", reason)
                if logical_params_module.get_parameter("active_integration_dahua_nvr") == 1:
                    insert_json_to_db(hb_payload)

            try:
                response = requests.get(url, auth=HTTPDigestAuth(userid, password), verify=False, timeout=10)

                if response.status_code == 200:
                    Heartbeat_t = "DahuaNVR_on"
                    payload = "{\"DahuaNVR_Heartbeat\":\"" + Heartbeat_t + "\"}"
                    if logical_params_module.get_parameter("active_integration_dahua_nvr") == 1:
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
            # Initialize the Dahua NVR DVR
            try:
                url = f"http://{ipaddress}/cgi-bin/global.cgi?action=getCurrentTime"
                response = requests.get(url, auth=HTTPDigestAuth(userid, password), verify=False, timeout=10)
                log.error(response)
            except Exception as e:
#                print("Error while initializing the camera client:", e)
                pass

        checkHBRT()
        sendTime()

    sendParameters()
#-------------------------------------------------------------------------------------------------------------

#------------------------------------ Getting HDD Info from Dahua Make NVR------------------------------------
def dahua_get_hdd_info():
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

            payload[f"Dahua_NVR_Details[{i}]"] = {
                "Dahua_NVR_capacity": total_bytes,
                "Dahua_NVR_NoOfHDDSlots": path,
                "Dahua_NVR_freeSpace": used_bytes
            }
        # Final payload wrapper
        deviceAllInfo = {
            "Dahua_NVR_deviceAllInfo": payload
        }

        attributes_json = json.dumps(deviceAllInfo, indent=4)
        if logical_params_module.get_parameter("active_integration_dahua_nvr") == 1:
            insert_json_to_db(attributes_json)
        
        log.error(attributes_json)
#        return attributes_json

    except requests.exceptions.RequestException as e:
        log.error(f"Error fetching Dahua NVR info: {e}")
        return None
#----------------------------------------------------------------------------------------------------------------
def dahua_get_hdd_info2():

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

            payload[f"Dahua_NVR_Details[{i}]"] = {
                "Dahua_NVR_SlotNumber": i + 1,
                "Dahua_NVR_Total_Bytes": total_bytes_sum,
                "Dahua_NVR_Used_Bytes": used_bytes_sum,
                "Dahua_NVR_Free_Bytes": free_bytes
            }

        # -------------------------
        # Final JSON Wrapper
        # -------------------------
        deviceAllInfo = {
            "Dahua_NVR_deviceAllInfo": payload
        }

        attributes_json = json.dumps(deviceAllInfo, indent=4)
        log.error(attributes_json)

        if logical_params_module.get_parameter("active_integration_dahua_nvr") == 1:
            insert_json_to_db(attributes_json)

    except requests.exceptions.RequestException:
        return None
#------------------------------------ Getting Camera Info from Dahua Make NVR------------------------------------
def dahua_get_camera_info():

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
                    raw_fps = video_config.get("FPS", "NA")
                    try:
                        clean_fps = str(int(float(raw_fps)))
                    except (ValueError, TypeError):
                        clean_fps = raw_fps
                    encode_data[i] = {
                        "resolution": video_config.get("resolution", "NA"),
                        "fps": clean_fps
                    }
                except KeyError:
                    log.error(f"Missing or invalid data for {encode_key}")
                    encode_data[i] = {"resolution": "NA", "fps": "NA"}

            # Print each encode's resolution and FPS
            for i, v in encode_data.items():
                log.error(f"Encode[{i}] - Resolution: {v['resolution']}, FPS: {v['fps']}")

            # Optionally, show Encode[1] resolution
            log.error("\nEncode[1] Resolution: %s", encode_data[1]["resolution"])

            # Set global resolution and FPS arrays
            resolutions = [encode_data[i]["resolution"] for i in range(16)]
            fps_values = [encode_data[i]["fps"] for i in range(16)]

            # Construct JSON payload
            payload_dict = {
                f"DahuaNVR_Encode[{i}]": {
                    "resolutions": resolutions[i],
                    "fps": fps_values[i]
                } for i in range(16)
            }

            payload = json.dumps(payload_dict, indent=4)
            log.error(payload)

            # insert_json_to_db(payload)  # Uncomment if needed

        elif response.status_code == 401:
            log.error("Authentication failed. Please check your credentials.")
        elif response.status_code == 403:
            log.error("Access forbidden. The digest authorization information is incorrect.")
        else:
            log.error("Failed to get a valid response. Status code: %s", response.status_code)

    except requests.RequestException as e:
        log.error("An error occurred: %s", e)

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
        log.error("Camera info error: %s", e)

    # ----------- Final Combined Payload -----------
    payload_dict = {}
    for cam_num in range(1, 17):
        i = cam_num - 1
        payload_dict[str(cam_num)] = {
            "Dahua_NVR_Address": camera_info.get(i, {}).get("address", "NA"),
            "Dahua_NVR_Resolutions": resolutions[i],
            "Dahua_NVR_FPS_Values": fps_values[i],
            "Dahua_NVR_Name": camera_info.get(i, {}).get("name", "NA")
        }

    # Send all 16 channels in a single payload
    deviceCamInfo = {
        "Dahua_NVR_cameraInfo": payload_dict
    }
    attributes_json = json.dumps(deviceCamInfo)
    if logical_params_module.get_parameter("active_integration_dahua_nvr") == 1:
        insert_json_to_db(attributes_json)
    log.info(attributes_json)
#----------------------------------------
#----------------------------------------------------------------------------------------------------------------

#------------------------------------ Getting Device Name from Dahua Make NVR------------------------------------
def dahua_get_device_name():
    url_1 = f'http://{ipaddress}/cgi-bin/magicBox.cgi?action=getMachineName'  # Device Name

    try:
        response = requests.get(url_1, auth=HTTPDigestAuth(userid, password), verify=False, timeout=10)
        
        if response.status_code == 200:
            device_name = "NA"
            for line in response.text.strip().splitlines():
                if line.startswith("name="):
                    device_name = line.split("=", 1)[1].strip()

                    print("Device Name:", device_name)
                    return device_name

            # Final payload wrapper
            deviceName = {
                "Dahua_NVR_deviceName": device_name
            }

            attributes_json = json.dumps(deviceName)
            if logical_params_module.get_parameter("active_integration_dahua_nvr") == 1:
                insert_json_to_db(attributes_json)
        
            print(attributes_json)
            
        else:
            print("Failed to get device name. Status:", response.status_code)

    except Exception as e:
        log.error("Error while getting device name: %s", str(e))

    return "NA"
#--------------------------------------------------------------------------------------------------------------------

#------------------------------------ Getting Device Type, Sl No, processor, Model Name from Dahua Make NVR----------
def dahua_get_device_info():

    url = f'http://{ipaddress}/cgi-bin/magicBox.cgi?action=getSystemInfoNew'

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
                "serialNumber": "Dahua_NVR_SerialNumber",
                "deviceType": "Dahua_NVR_DeviceType",
                "processor": "Dahua_NVR_Processor",
                "updateSerial": "Dahua_NVR_Model"
            }

            for sys_key, tb_key in device_info_map.items():
                value = info.get(sys_key, "NA")
                attributes_json = json.dumps({tb_key: value})
                if logical_params_module.get_parameter("active_integration_dahua_nvr") == 1:
                    insert_json_to_db(attributes_json)
                print(attributes_json)

            return info
        else:
            print(f"Failed to get system info. Status: {response.status_code}")
    except Exception as e:
        log.error("Error while getting system info: %s", str(e))

    return {}
#--------------------------------------------------------------------------------------------------------------------

#------------------------------------ Getting Firmware version & mfg date from Dahua Make NVR------------------------
def dahua_get_firmware_version():
    
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
                "Dahua_NVR_Firmware_Version": version_part,
                "Dahua_NVR_mfg": build_part
            }

            for key, value in payloads.items():
                attributes_json = json.dumps({key: value})
                if logical_params_module.get_parameter("active_integration_dahua_nvr") == 1:
                    insert_json_to_db(attributes_json)
                print(attributes_json)

            return info
        else:
            print(f"Failed to get version info. Status: {response.status_code}")
    except Exception as e:
        log.error("Error while getting version info: %s", str(e))

    return {}
#---------------------------------------------------------------------------------------------------------------------

#------------------------------------ Getting Hardware Version from Dahua Make NVR------------------------------------
def dahua_get_hardware_version():
    
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
                "Dahua_NVR_Hardware_Version": info.get("version", "NA")
            })

            if logical_params_module.get_parameter("active_integration_dahua_nvr") == 1:
                insert_json_to_db(attributes_json)

            print(attributes_json)
            return info
        else:
            print(f"Failed to get version info. Status: {response.status_code}")
    except Exception as e:
        log.error("Error while getting version info: %s", str(e))

    return {}
#-----------------------------------------------------------------------------------------------------------------

#------------------------------------ Getting Manufacturar from Dahua Make NVR------------------------------------
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
                "Dahua_NVR_Manufacturer": info.get("vendor", "NA")
            })

            if logical_params_module.get_parameter("active_integration_dahua_nvr") == 1:
                insert_json_to_db(attributes_json)

            print(attributes_json)
            return info
        else:
            print(f"Failed to get vendor Status: {response.status_code}")
    except Exception as e:
        log.error("Error while getting vendor: %s", str(e))

    return {}
#----------------------------------------------------------------------------------------------------------------

#------------------------------------ Getting Date & Time from Dahua Make NVR------------------------------------
def dahua_get_current_time():
    
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
                "Dahua_NVR_Date": date_part,
                "Dahua_NVR_Time": time_part
            }

            for key, value in payloads.items():
                attributes_json = json.dumps({key: value})
                if logical_params_module.get_parameter("active_integration_dahua_nvr") == 1:
                    insert_json_to_db(attributes_json)
                print(attributes_json)

            return info
        else:
            print(f"Failed to get current time. Status: {response.status_code}")
    except Exception as e:
        log.error("Error while getting current time: %s", str(e))

    return {}
#-------------------------------------------------------------------------------------------------------------
#-------------------------------------------------------------------------------------------------------------
def dahua_collect_all_system_info():
    try:
        if logical_params_module.get_parameter("active_integration_dahua_nvr") != 1:
            print("Integration not active.")
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
                            payloads["Dahua_NVR_Device_Name"] = value.strip()
        except Exception as e:
            log.error("Device Name Error: %s", str(e))

        # Device Info (serial, type, processor, model)
        try:
           # url = f"http://{ipaddress}/cgi-bin/magicBox.cgi?action=getSystemInfoNew"
            url = f"http://{ipaddress}/cgi-bin/magicBox.cgi?action=getSystemInfo"
            response = requests.get(url, auth=HTTPDigestAuth(userid, password), verify=False, timeout=10)
            if response.status_code == 200:
                info = {}
                for line in response.text.strip().splitlines():
                    if '=' in line:
                        key, value = line.strip().split('=', 1)
                        info[key] = value

                payloads["Dahua_NVR_SerialNumber"] = info.get("serialNumber", "NA")
                payloads["Dahua_NVR_DeviceType"] = info.get("deviceType", "NVR")
                payloads["Dahua_NVR_Processor"] = info.get("processor", "NA")
                payloads["Dahua_NVR_Model"] = info.get("updateSerial", "NA")
        except Exception as e:
            log.error("Device Info Error: %s", str(e))

        # Firmware Version
        try:
            #url = f"http://{ipaddress}/cgi-bin/magicBox.cgi?action=getSystemVersion"
            url = f"http://{ipaddress}/cgi-bin/magicBox.cgi?action=getSoftwareVersion"
           # /cgi-bin/magicBox.cgi?action=getSoftwareVersion

            response = requests.get(url, auth=HTTPDigestAuth(userid, password), verify=False, timeout=10)
            log.error(response)

            if response.status_code == 200:
                    for line in response.text.strip().splitlines():
                        if '=' in line:
                            key, value = line.strip().split('=', 1)
                            if key.strip() == "version":
                                version_full = value.strip()
                                version_clean = version_full.split(",build:")[0]  # Remove build part
                                payloads["Dahua_NVR_Firmware_Version"] = version_clean
                                if "build:" in version_full:
                                    build_date = version_full.split("build:")[-1]
                                    payloads["Dahua_NVR_mfg"] = build_date


        #    if response.status_code == 200:
        #        for line in response.text.strip().splitlines():
        #            if '=' in line:
        #                key, value = line.strip().split('=', 1)
        #                if key.strip() == "BuildDate":
        #                    payloads["Dahua_NVR_Firmware_Version"] = value.strip()
        except Exception as e:
            log.error("Firmware Version Error: %s", str(e))

        # Hardware Version
        try:
            #url = f"http://{ipaddress}/cgi-bin/magicBox.cgi?action=getSoftwareVersion"
            url = f"http://{ipaddress}/cgi-bin/magicBox.cgi?action=getHardwareVersion"

            response = requests.get(url, auth=HTTPDigestAuth(userid, password), verify=False, timeout=10)
            log.error(response)
            if response.status_code == 200:
                for line in response.text.strip().splitlines():
                    if '=' in line:
                        key, value = line.strip().split('=', 1)
                        if key.strip() == "version":
                            version_full = value.strip()
                            version_clean = version_full.split(",build:")[0]  # Remove build part
                            payloads["Dahua_NVR_Hardware_Version"] = version_clean
                            if "build:" in version_full:
                                build_date = version_full.split("build:")[-1]
                                payloads["Dahua_NVR_mfg"] = build_date
        except Exception as e:
            log.error("Hardware Version Error: %s", str(e))

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
                            payloads["Dahua_NVR_Manufacturer"] = vendor
        except Exception as e:
            log.error("Time Info Error: %s", str(e))

        # --- Send Each Key Individually ---
        for key, value in payloads.items():
            attributes_json = json.dumps({key: value})
            insert_json_to_db(attributes_json)
            log.error(attributes_json)

    except Exception as e:
        log.error("Unexpected Error in collection: %s", str(e))

#-------------------------------------------------------------------------------------------------------------
#-------------------------------------------------------------------------------------------------------------
if __name__ == '__main__':
 
    # ACTIVE-INTEGRATION-GUARD: check flag before doing any work
    # If integration is disabled from the menu, exit cleanly.
    # systemd sees exit(0) as success and will NOT restart the service.
    # Service stays enabled — to re-activate, enable from menu then:
    #   sudo systemctl restart dexter-nvr-dahua
    if logical_params_module.get_parameter("active_integration_dahua_nvr") != 1:
        import logging as _lg, sys as _sys
        _lg.getLogger(__name__).info(
            "[dahua_nvr_dvr_information.py] active_integration_dahua_nvr=0 — integration disabled, exiting cleanly"
        )
        _sys.exit(0)

    # REC-FIX-3: credentials fetched here after integration flag confirmed ON.
    # Was at module level — ran before this guard — exit(1) if missing device
    # triggered Restart=on-failure restart loop.
    devices = device_parameters_module.get_device_parameters(device_type)
    if not devices:
        log.error(
            "[dahua_nvr_dvr_information.py] No DahuaNVR1 entry in device_config.db "
            "— add via LCD menu. Exiting cleanly."
        )
        import sys as _sys; _sys.exit(0)
    ipaddress = devices[0]['ip_address']
    userid    = devices[0]['username']
    password  = devices[0]['password']
    log.info("[init] Dahua NVR target: %s", ipaddress)

    # ── JITTER: deterministic per-panel startup delay (Strategy A) ────────────
    # Spreads 5,000 panels across a 300s window → ~17 panels/sec instead of
    # 5,000 at once. Same panel always gets the same offset on every reboot.
    jitter = get_jitter_sec(window_sec=300)
    log.info("[startup] jitter delay = %ds", jitter)
    time.sleep(jitter)

    initExternalDevice()
    dahua_get_current_time()
    dahua_get_camera_info()
    dahua_get_hdd_info2()
    dahua_collect_all_system_info()

    # ── INTERVAL tasks ────────────────────────────────────────────────────────
    # BUG-1 FIX: was schedule.every(300).minutes (5 hours!) — corrected to 300s
    schedule.every(300).seconds.do(initExternalDevice)         # heartbeat — every 5 min
    # BUG-2 FIX: was schedule.every(600).minutes (10 hours!) — corrected to 600s
    schedule.every(900).seconds.do(dahua_get_current_time)     # time sync  — every 15 min

    # ── DAILY tasks: load-gated (Strategy B) — replaces fixed clock times ─────
    # Consolidates dahua_get_camera_info, dahua_get_hdd_info2, and
    # dahua_collect_all_system_info into one load-gated daily call.
    # Eliminates the 17:25 / 17:30 / 17:45 simultaneous spikes.
    _daily_sent_date_dahua = None

    def maybe_send_daily_dahua():
        global _daily_sent_date_dahua
        today = datetime.today().date()
        if _daily_sent_date_dahua == today:
            return  # already sent today
        if not is_rpi_idle():
            log.debug("[daily] RPi busy — deferring Dahua NVR daily tasks")
            return
        # RPi is idle — send all daily bulk data
        log.info("[daily] RPi idle — sending Dahua NVR daily data")
        dahua_get_camera_info()            # camera details
        dahua_get_hdd_info2()              # HDD storage info
        dahua_collect_all_system_info()    # full system snapshot
        _daily_sent_date_dahua = today

    schedule.every(60).seconds.do(maybe_send_daily_dahua)

    try:
        while True:
            time.sleep(10)
            schedule.run_pending()
            watchdog.reset()
    except KeyboardInterrupt:
        log.error("\nExiting program...")
#-------------------------------------------------------------------------------------------------------------
