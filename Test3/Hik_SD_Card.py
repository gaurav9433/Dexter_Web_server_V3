import requests
from requests.auth import HTTPDigestAuth
#from requests.packages.urllib3.exceptions import InsecureRequestWarning
from urllib3.exceptions import InsecureRequestWarning
import warnings
import json
import time  # Importing time module for delay
import re  # Importing regex for extracting object_id
import schedule  # Import schedule
from datetime import datetime, timedelta
from datetime import datetime, timezone
from requests.exceptions import ConnectionError  # Import ConnectionError

import xml.etree.ElementTree as ET

import threading
import os
import sys

# DB-03: insert_json_to_db enforces 50K row hard cap + TTL purge
from buffer_manager import insert_json_to_db, init_db
init_db()  # Create buffer table if it does not exist yet

import logical_params_module
import device_parameters_module as _dpm

# ── Shared scheduling helpers (jitter + load-gate) ───────────────────────────
from scheduler_utils import get_jitter_sec, is_rpi_idle


# Suppress SSL warnings
requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

# Initialize the database
logical_params_module.initialize_database()

#---------------------------- Watchdog Timer------------------------------------
# CQ-01: SoftwareWatchdog centralised in watchdog_manager.py
from watchdog_manager import SoftwareWatchdog

from syslog_file_logger import get_dual_logger
log = get_dual_logger('Hik_SD_Card')
watchdog = SoftwareWatchdog(timeout=3600)
#--------------------------------------------------------------------------------------

def get_camera_info_list(device_type):
    return _dpm.get_camera_ips_by_type(device_type)

#-----------------------------------------------------------------------------------------------------------

#---------------------------- Getting SD Card Recording Info from Dahua Make Camera------------------------------------
def dahua_get_sd_card_recording_info(camera_info):
    try:
        ip = camera_info.get("ip_address", "unknown")
        user = camera_info["username"]
        pwd = camera_info["password"]
        
        # Step 1: Call the first API to get the object value
        url1 = f"http://{ip}/cgi-bin/mediaFileFind.cgi?action=factory.create"
        response1 = requests.get(url1, auth=HTTPDigestAuth(user, pwd), verify=False)
        response1.raise_for_status()

        # Extract the object ID from the response
        object_id = response1.text.strip().split("=")[-1]

        # Get the current date and time for EndTime
        end_time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Set the StartTime (Fixed value)
        start_time_str = "2012-01-01 12:00:00"  # Fixed start time, could be dynamic if needed

        # Step 2: Call findFile API
        url2 = (
            f"http://{ip}/cgi-bin/mediaFileFind.cgi?"
            f"action=findFile&object={object_id}"
            f"&condition.Channel=1"
            f"&condition.StartTime={start_time_str.replace(' ', '%20')}"
            f"&condition.EndTime={end_time_str.replace(' ', '%20')}"
            f"&condition.VideoStream=Main"
        )

        requests.get(url2, auth=HTTPDigestAuth(user, pwd), verify=False).raise_for_status()

        # Step 3: Call findNextFile API to get file details
        recorded_dates = set()
        total_recording_days = 0
        start_date = 'N/A'
        end_date = 'N/A'
        while True:
            url3 = f"http://{ip}/cgi-bin/mediaFileFind.cgi?action=findNextFile&object={object_id}&count=100"
            response3 = requests.get(url3, auth=HTTPDigestAuth(user, pwd), verify=False)
            response3.raise_for_status()
  
            lines = response3.text.splitlines()
            if not any("FilePath=" in line for line in lines):  # Stop if no more files
               break             
         
            # Extract recording dates
            for line in lines:
                if "FilePath=" in line:
                    date_part = line.split("=")[-1].split("/")[3]  # Extract YYYY-MM-DD
                    recorded_dates.add(date_part)
        
            total_recording_days = len(recorded_dates)
        
            # Format the start and end dates for the output
            start_date = min(recorded_dates) if recorded_dates else 'N/A'
            end_date = max(recorded_dates) if recorded_dates else 'N/A'
        
#        print "Total Recording Days for Camera {}: {}".format(camera_ip, len(recorded_dates))

        # Store the data for this camera in the result list in the requested format
        Dahua_SD_card_rec_info = {
            "camera_ip": ip,
            "start_date": start_date,
            "end_date": end_date,
            "total_recording_days": total_recording_days
        }
        
        # Create a list with one element for this camera
        Dahua_SD_card_rec_info_list = {
            "Dahua_SD_card_rec_info": [
                Dahua_SD_card_rec_info
            ]
        }
        
        # Convert the dictionary to JSON
        #attributes_json = json.dumps(Dahua_SD_card_rec_info_list)

        # Insert into the database (Buffer Manager)
        #if logical_params_module.get_parameter("active_integration_dahua_nvr") == 1:
           #insert_json_to_db(attributes_json)  # Insert into the database

        # Print confirmation message
        #print "SD Card Record info sent to the database for camera:", camera_ip
#        print "Please check LATEST TELEMETRY field of SD Card Record Info"
#        print attributes_json
        
        return Dahua_SD_card_rec_info_list  # Return in the correct format

    except requests.exceptions.RequestException as e:  # Python 3 exception handling
        #print(f"An error occurred while fetching recording info for camera {ip}: {e}")
        return None


def dahua_main_SDcard_Record_Info():
    
    camera_info_list = get_camera_info_list("HikvisionNVR1")
    if camera_info_list:
        print("Camera IPs extracted:", camera_info_list)
    else:
        print("No camera IPs found.")
        return


    # Initialize the list to hold all recording info
    combined_recording_info_list = []

    # Loop through all cameras and collect data
    for cam in camera_info_list:
        recording_info = dahua_get_sd_card_recording_info(cam)
        if recording_info and "Dahua_SD_card_rec_info" in recording_info:
            combined_recording_info_list.extend(recording_info["Dahua_SD_card_rec_info"])

    # Wrap the combined list into a dictionary
    final_result = {
        "Dahua_SD_card_rec_info_list": combined_recording_info_list
    }

    # Convert to JSON string and print
    #final_json = json.dumps(final_result, indent=2)
    attributes_json = json.dumps(final_result)
    print(attributes_json)

    if logical_params_module.get_parameter("active_integration_hikvision_nvr") == 1:
        insert_json_to_db(attributes_json)

    return final_result
#---------------------------------------------------------------------------------------------------------

#---------------------------- Getting SD Card Recording Info from Hikvision Make Camera------------------------------------    

def hik_get_sd_card_recording_info(camera_info):
    
    try:
        #ip = camera_info.get("ip_address", "unknown")
        ip = camera_info["ip_address"]
        user = camera_info["username"]
        pwd = camera_info["password"]
        
        #current_utc_time = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')
        current_utc_time = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        url = f"http://{ip}/ISAPI/ContentMgmt/search"
        search_result_position = 1
        recording_dates = set()  # Store unique recording dates
        MAX_RESULTS = 30  # Number of results per request
        first_recording_date = None  # To track the first recording date
        last_recording_date = None   # To track the last recording date

        for i in range(1, 17):
            track_id = 100 * i + 1
            first_recording_time = None

            while True:
                start_time = "2000-01-01T00:00:00Z" if first_recording_time is None else first_recording_time

                xml_body = f"""<?xml version="1.0" encoding="utf-8"?>
                <CMSearchDescription>
                    <searchID>88C2CD4D-D3FA-4AD4-BD80-555C18205DCC</searchID>
                    <trackList>
                        <trackID>{track_id}</trackID>
                    </trackList>
                    <timeSpanList>
                        <timeSpan>
                            <startTime>{start_time}</startTime>
                            <endTime>{current_utc_time}</endTime>
                        </timeSpan>
                    </timeSpanList>
                    <maxResults>{MAX_RESULTS}</maxResults>
                    <searchResultPostion>{search_result_position}</searchResultPostion>
                    <metadataList>
                        <metadataDescriptor>//recordType.meta.std-cgi.com</metadataDescriptor>
                    </metadataList>
                </CMSearchDescription>"""

                headers = {"Content-Type": "application/xml"}
                
                try:
                    response = requests.post(url, auth=HTTPDigestAuth(user, pwd), data=xml_body, headers=headers, verify=False, timeout=30)
                    response.raise_for_status()  # Raises an HTTPError for bad responses

                except requests.exceptions.Timeout:
#                    print("Timeout occurred while connecting to camera: {}".format(camera_ip))
                    return None
                except requests.exceptions.RequestException as e:
                    #print("Error during request to camera {}: {}".format(camera_ip, e))
                    return None

                # Check if the response is empty
                if not response.text.strip():
#                    print("Empty response received from camera: {}".format(camera_ip))
                    return None

                try:
                    # Parse XML
                    root = ET.fromstring(response.text)

                    # Check if there are more results
                    response_status_strg = root.find(".//{http://www.hikvision.com/ver20/XMLSchema}responseStatusStrg")
                    if response_status_strg is not None and response_status_strg.text != "MORE":
                        #print("All results fetched. Exiting loop.")
                        break  # Stop if no more results

                    # Extract unique recording dates
                    for item in root.findall(".//{http://www.hikvision.com/ver20/XMLSchema}searchMatchItem"):
                        start_time = item.find(".//{http://www.hikvision.com/ver20/XMLSchema}timeSpan/{http://www.hikvision.com/ver20/XMLSchema}startTime")
                        if start_time is not None:
                            recording_date = start_time.text[:10]  # Extract YYYY-MM-DD
                            recording_dates.add(recording_date)

                            # Update the first and last recording dates
                            recording_date_obj = datetime.strptime(recording_date, "%Y-%m-%d")
                            if first_recording_date is None or recording_date_obj < first_recording_date:
                                first_recording_date = recording_date_obj
                            if last_recording_date is None or recording_date_obj > last_recording_date:
                                last_recording_date = recording_date_obj

                    # Move to the next batch of results
                    search_result_position += MAX_RESULTS
                    time.sleep(1)  # Prevent API spam

                except ET.ParseError as e:
                    #print("XML Parsing Error:", e)
                    break

        # After collecting all the dates, calculate total recording days
        if first_recording_date and last_recording_date:
            continuous_days = (last_recording_date - first_recording_date).days + 1
        else:
            continuous_days = 0  # In case no recordings were found

        # Construct the Hik_SD_card_rec_info dictionary
        Hik_SD_card_rec_info = {
            "camera_ip": ip,
            "start_date": first_recording_date.strftime("%Y-%m-%dT%H:%M:%SZ") if first_recording_date else None,
            "end_date": last_recording_date.strftime("%Y-%m-%dT%H:%M:%SZ") if last_recording_date else None,
            #"total_recording_days": continuous_days
            "total_recording_days": len(recording_dates)
        }

        return Hik_SD_card_rec_info

    except requests.exceptions.RequestException as e:
       # print("Error fetching SD card recordings for {}: {}".format(camera_ip, e))
        return None



def hik_main_SDcard_Record_Info():
    
    camera_info_list = get_camera_info_list("HikvisionNVR1")
    if camera_info_list:
        print("Camera IPs extracted:", camera_info_list)
    else:
        print("No camera IPs found.")
        return

    Hik_SD_card_rec_info_list = []  # Initialize the list to hold all camera SD card info

    for cam in camera_info_list:
        #recording_info = get_sd_card_recording_info(camera_ip)
        recording_info = hik_get_sd_card_recording_info(cam)
        if recording_info:
            Hik_SD_card_rec_info_list.append(recording_info)
        else:
            # If the camera does not return any valid data, append a default entry
            Hik_SD_card_rec_info_list.append({
                "camera_ip": cam["ip_address"],
                "total_recording_days": 0,
                "start_date": None,
                "end_date": None
            })
    
    # Prepare the final output in the desired format
    final_output = {
        "Hik_SD_card_rec_info_list": Hik_SD_card_rec_info_list
    }

    # Convert the result to a JSON string
    attributes_json = json.dumps(final_output)

    # Insert the JSON into the database (if necessary)
    if logical_params_module.get_parameter("active_integration_hikvision_nvr") == 1:
        insert_json_to_db(attributes_json)
       # print("SD Card Record info sent to database: {}".format(attributes_json))
    print(attributes_json)
#    print "Final SD Card Record Info: {}".format(attributes_json)
#---------------------------------------------------------------------------------------------------------

#------------------------------------ Getting SD Card Info from Dahua Make Camera------------------------------------

def dahua_get_sd_card_info(camera_info):
    
    ip = camera_info["ip_address"]
    user = camera_info["username"]
    pwd = camera_info["password"]
    # Ensure these are always initialized
    total_bytes = "NA"
    used_bytes = "NA"
    serial_number = None
    device_type = None
    
    try:
        # First URL - Fetch SD card details
        sd_card_url = f"http://{ip}/cgi-bin/storageDevice.cgi?action=getDeviceAllInfo"
        response_sd = requests.get(sd_card_url, auth=HTTPDigestAuth(user, pwd), verify=False)
    
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

        try:
            # Now, you can extract specific information from the parsed_info dictionary
            # For example, extracting TotalBytes and UsedBytes:
            total_bytes = float(parsed_info.get('list.info[0].Detail[0].TotalBytes', 0))
            used_bytes = float(parsed_info.get('list.info[0].Detail[0].UsedBytes', 0))
        except (TypeError, ValueError):
            total_bytes = "NA"
            used_bytes = "NA"
    
    except requests.exceptions.RequestException:
        # Set to NA if error occurs
        #total_bytes = "NA"
        #used_bytes = "NA"
        pass  # total_bytes and used_bytes remain "NA"
        
    # Try to fetch device info regardless of SD info success
    try:
        device_info_url = f"http://{ip}/cgi-bin/magicBox.cgi?action=getSystemInfo"
        response_device = requests.get(device_info_url, auth=HTTPDigestAuth(user, pwd), verify=False)

        response_device.raise_for_status()

        for line in response_device.text.splitlines():
            line = line.strip()
            if "serialNumber=" in line:
                serial_number = line.split("=", 1)[1].strip()
            elif "deviceType=" in line:
                device_type = line.split("=", 1)[1].strip()

    except requests.exceptions.RequestException:
        pass  # serial_number and device_type remain None

    Dahua_SD_card_info = {
        "camera_ip": ip,
        "TotalBytes": total_bytes,
        "UsedBytes": used_bytes,
        "serialNumber": serial_number,
        "deviceType": device_type
    }

    return {
        "Dahua_SD_card_info": [Dahua_SD_card_info]
    }    


def dahua_main_SDcard_Info():
    
    camera_info_list = get_camera_info_list("HikvisionNVR1")
    if camera_info_list:
        print("Camera IPs extracted:", camera_info_list)
    else:
        #print("No camera IPs found.")
        return

    # Aggregate all SD card info here
    all_sd_card_entries = []

    for cam in camera_info_list:
        sd_card_info = dahua_get_sd_card_info(cam)
        if sd_card_info and "Dahua_SD_card_info" in sd_card_info:
            all_sd_card_entries.extend(sd_card_info["Dahua_SD_card_info"])

    # Insert once if data is collected and integration is enabled
    if all_sd_card_entries:
        combined_data = {
            "Dahua_SD_card_info": all_sd_card_entries
        }

        attributes_json = json.dumps(combined_data)
        if logical_params_module.get_parameter("active_integration_hikvision_nvr") == 1:
            insert_json_to_db(attributes_json)

        #print("All SD card info has been sent to the database.")
        print(attributes_json)
    else:
        print("No SD card info was found for any camera.")

#---------------------------------------------------------------------------------------------------------

#------------------------------------ Getting SD Card Info from Hikvision Make Camera------------------------------------
def hik_get_sd_card_info(camera_info):
    
    ip = camera_info["ip_address"]
    user = camera_info["username"]
    pwd = camera_info["password"]
    
    try:
        # First URL - Fetch SD card details
        sd_card_url = f"http://{ip}/ISAPI/ContentMgmt/storage/hdd/capabilities"

        # Define the XML namespace
        namespaces = {"ns10": "http://www.hikvision.com/ver10/XMLSchema", "ns20": "http://www.hikvision.com/ver20/XMLSchema"}
        
        # Set to store unique HDD details
        hdd_info_list = []

        while True:
            # Send API request
            response = requests.get(
                sd_card_url,
                auth=HTTPDigestAuth(user, pwd),
                headers={"Content-Type": "application/xml"},
                timeout=10
            )
        
#            print "Status Code: {}, Response Length: {}".format(response.status_code, len(response.text))
            
            if response.status_code != 200 or not response.text.strip():
#                print "Error: No valid response received. Stopping."
                break
                
            try:
                # Parse XML
                root = ET.fromstring(response.text)

                # Extract HDD information
                for hdd in root.findall(".//ns20:hdd", namespaces):
                    hdd_name = hdd.find("ns20:hddName", namespaces)
                    capacity = hdd.find("ns20:capacity", namespaces)
                    free_space = hdd.find("ns20:freeSpace", namespaces)
                    status = hdd.find("ns20:status", namespaces)

                    hdd_info = {
                        "HDD Name": hdd_name.text if hdd_name is not None else "Unknown",
                        "Capacity (MB)": capacity.text if capacity is not None else "Unknown",
                        "Free Space (MB)": free_space.text if free_space is not None else "Unknown",
                        "Status": status.text if status is not None else "Unknown",
                    }
                    
                    hdd_info_list.append(hdd_info)
                    
                break  # Exit after fetching HDD info
                
            except ET.ParseError as e:
                #print "XML Parsing Error: {}".format(e)
                break

        # Print results
#        print "\nHDD Storage Information:"
        if not hdd_info_list:
            log.error("No HDD info found.")
        else:
            for hdd_info in hdd_info_list:
                log.error("HDD Name: {}".format(hdd_info['HDD Name']))
#                print "Capacity: {} MB".format(hdd_info['Capacity (MB)'])
#                print "Free Space: {} MB".format(hdd_info['Free Space (MB)'])
#                print "Status: {}".format(hdd_info['Status'])
#                print "=" * 40

        # Second URL - Fetch device details (camera device info)
        device_info_url = f"http://{ip}/ISAPI/System/deviceInfo"
        response_device = requests.get(device_info_url, auth=HTTPDigestAuth(user, pwd), verify=False)
        response_device.raise_for_status()  # Raises an HTTPError for bad responses
        
        # Check if the response_device status is OK (200)
        if response_device.status_code == 200:
            # Parse the XML response for device details
            root_device = ET.fromstring(response_device.text)

            # Extract required information from the device XML (with correct namespace 'ns20')
            model = root_device.find('.//ns20:model', namespaces=namespaces)
            serial_number = root_device.find('.//ns20:serialNumber', namespaces=namespaces)
            manufacturer = root_device.find('.//ns20:manufacturer', namespaces=namespaces)

            model = model.text if model is not None else None
            serial_number = serial_number.text if serial_number is not None else None
            manufacturer = manufacturer.text if manufacturer is not None else None
            
            # Construct the device info dictionary
            device_info = {
               "model": model,
               "serialNumber": serial_number,
               "manufacturer": manufacturer
            }

            # Ensure there is HDD info before merging
            if hdd_info_list:
                # Merging data
                Hik_SD_card_info = {
                    "camera_ip": ip,
                    "TotalBytes": hdd_info_list[0].get('Capacity (MB)', 0),  # Use first HDD entry for capacity
                    "UsedBytes": hdd_info_list[0].get('Free Space (MB)', 0),  # Use first HDD entry for free space
                    "model": model,
                    "serialNumber": serial_number,
                    "manufacturer": manufacturer
                }
            else:
                Hik_SD_card_info = {
                    "camera_ip": ip,
                    "TotalBytes": "NA",
                    "UsedBytes": "NA",
                    "model": model,
                    "serialNumber": serial_number,
                    "manufacturer": manufacturer
                }

            return Hik_SD_card_info  # Return the SD card info
        
        else:
#            print("Failed to get device info from Camera Info", camera_ip)
            return None
        
    except requests.exceptions.RequestException as e:
        #print("An error occurred while fetching SD Card info for camera {}: {}".format(ip, e))
        return None


def hik_main_SDcard_Info():
    
    camera_info_list = get_camera_info_list("HikvisionNVR1")
    if camera_info_list:
        print("Camera IPs extracted:", camera_info_list)
    else:
        #print("No camera IPs found.")
        return

    # For each camera, extract SD card recording information
    all_sd_card_info = []
    for cam in camera_info_list:
        sd_card_info = hik_get_sd_card_info(cam)
        if sd_card_info:
            all_sd_card_info.append(sd_card_info)
    
    if all_sd_card_info:
        Hik_SD_card_info_list = {
            "Hik_SD_card_info": all_sd_card_info
        }

        attributes_json = json.dumps(Hik_SD_card_info_list)
        if logical_params_module.get_parameter("active_integration_hikvision_nvr") == 1:
            insert_json_to_db(attributes_json)
        print(attributes_json)
        #print("Final payload inserted for all cameras:", attributes_json)
    else:
        print("No SD card info was found for any camera.")
#--------------------------------------------------------------------------------------------------------------

#--------------------------------------------Dahua Make camera Status------------------------------------------ 

def get_dahua_cam_status(camera_info):  
    
    ip = camera_info["ip_address"]
    user = camera_info["username"]
    pwd = camera_info["password"]
    sd_card_info_url = f"http://{ip}/cgi-bin/global.cgi?action=getCurrentTime"

    try:       
        response_sd = requests.get(sd_card_info_url, auth=HTTPDigestAuth(user, pwd), verify=False)
        response_sd.raise_for_status()

        if response_sd.status_code == 200:
            print("Dahua NVR Camera is active.")
        return "Active"

    except requests.exceptions.ConnectionError as e:
        #print("Connection error to Dahua NVR at IP:", ip, "Error:", e)
        return "Inactive"

    except Exception as e:
        #print("Error initializing Dahua NVR:", e)
        return "Inactive"


def main_dahua_cam_status():
          
    camera_info_list = get_camera_info_list("HikvisionNVR1")
    if camera_info_list:
        print("Camera IPs extracted:", camera_info_list)
    else:
       # print("No camera IPs found.")
        return
    # For each camera, extract camera status information
    dahua_camera_status = []
    
    for cam in camera_info_list:
        camera_status = get_dahua_cam_status(cam)
        if camera_status == 'Active':
            dahua_camera_status.append({
                "camera_ip": cam["ip_address"],
                "camera_status": 'Active'
            })
        else:
            dahua_camera_status.append({
                "camera_ip": cam["ip_address"],
                "camera_status": None
            })
    # Prepare the final output in the desired format
    final_output = {
        "dahua_camera_status": dahua_camera_status
    }

    # Convert the result to a JSON string
    attributes_json = json.dumps(final_output)

    # Insert the JSON into the database (if necessary)
    if logical_params_module.get_parameter("active_integration_hikvision_nvr") == 1:
        insert_json_to_db(attributes_json)
#        print "Camera uptime status sent to database: {}".format(attributes_json)    
    print(attributes_json)
#    print "Final Camera uptime status Info: {}".format(attributes_json)
#---------------------------------------------------------------------------------------------------------

#------------------------------------------Hikvision Make camera Status----------------------------------------

def get_hikvision_cam_status(camera_info):
    
    ip = camera_info["ip_address"]
    user = camera_info["username"]
    pwd = camera_info["password"]
    url = f'http://{ip}/ISAPI/System/time'

    try:
        # Send request to fetch camera data
        response = requests.get(url, auth=HTTPDigestAuth(user, pwd), verify=False)
        response.raise_for_status()
        
        if response.status_code == 200:
            print("Hikvision NVR Camera is active.")
        return "Active" 

#    except ConnectionError as e:
    except requests.exceptions.ConnectionError as e:
#        print("Connection error to Hikvision NVR Camera at IP:", camera_ip, "Error:", e)
        return "Inactive"

    except Exception as e:
#        print("Error initializing Hikvision NVR:", e)
        return "Inactive"


def main_hik_cam_status():

    camera_info_list = get_camera_info_list("HikvisionNVR1")
    if camera_info_list:
        print("Camera IPs extracted:", camera_info_list)
    else:
        #print("No camera IPs found.")
        return
        
    #if get_hikvision_cam_status() == 'Active':
                
    # For each camera, extract camera status information
    hikvision_camera_status = []
    
    for cam in camera_info_list:
        camera_status = get_hikvision_cam_status(cam)
        if camera_status == 'Active':
            hikvision_camera_status.append({
                "camera_ip": cam["ip_address"],
                "camera_status": 'Active'
            })
        else:
            hikvision_camera_status.append({
                "camera_ip": cam["ip_address"],
                "camera_status": None
            })
    # Prepare the final output in the desired format
    final_output = {
        "hikvision_camera_status": hikvision_camera_status
    }

    # Convert the result to a JSON string
    attributes_json = json.dumps(final_output)
    print(attributes_json)
    # Insert the JSON into the database (if necessary)
    if logical_params_module.get_parameter("active_integration_hikvision_nvr") == 1:
        insert_json_to_db(attributes_json)
#        print "Camera uptime status sent to database: {}".format(attributes_json)    

#    print "Final Camera uptime status Info: {}".format(attributes_json)
#---------------------------------------------------------------------------------------------------------

#--------------------------------------------CP Plus camera SD Card Info------------------------------------
def cpplus_get_sd_card_info(camera_info):

    ip = camera_info["ip_address"]
    user = camera_info["username"]
    pwd = camera_info["password"]

    total_bytes = "NA"
    used_bytes = "NA"
    serial_number = None
    device_type = None

    try:
        url = f"https://{ip}/cpapi/storageDevice.cgi?action=getDeviceAllInfo"
        r = requests.get(url, auth=HTTPDigestAuth(user, pwd), verify=False, timeout=5)
        if r.status_code == 200:
            parsed = {}
            for line in r.text.splitlines():
                if "=" in line:
                    k, v = line.split("=", 1)
                    parsed[k.strip()] = v.strip()
            total_bytes = float(parsed.get('list.info[0].Detail[0].TotalBytes', 0))
            used_bytes = float(parsed.get('list.info[0].Detail[0].UsedBytes', 0))
    except Exception:
        pass

    try:
        url = f"https://{ip}/cpapi/magicBox.cgi?action=getDeviceType"
        r = requests.get(url, auth=HTTPDigestAuth(user, pwd), verify=False, timeout=5)
        for line in r.text.splitlines():
            if "type=" in line:
                device_type = line.split("=", 1)[1].strip()
    except Exception:
        pass

    try:
        url = f"https://{ip}/cpapi/magicBox.cgi?action=getSerialNo"
        r = requests.get(url, auth=HTTPDigestAuth(user, pwd), verify=False, timeout=5)
        for line in r.text.splitlines():
            if "sn=" in line:
                serial_number = line.split("=", 1)[1].strip()
    except Exception:
        pass

    return {
        "camera_ip": ip,
        "TotalBytes": total_bytes,
        "UsedBytes": used_bytes,
        "serialNumber": serial_number,
        "deviceType": device_type
    }


def cpplus_main_SDcard_Info():

    camera_info_list = get_camera_info_list("CP_PlusNVR1")
    if not camera_info_list:
        print("No camera IPs found.")
        return

    all_sd_card_entries = []
    for cam in camera_info_list:
        try:
            result = cpplus_get_sd_card_info(cam)
            if result:
                all_sd_card_entries.append(result)
        except Exception as e:
            print(f"Error processing camera {cam['ip_address']}: {e}")

    if all_sd_card_entries:
        combined_data = {"Cpplus_SD_card_info": all_sd_card_entries}
        attributes_json = json.dumps(combined_data)
        if logical_params_module.get_parameter("active_integration_hikvision_nvr") == 1:
            insert_json_to_db(attributes_json)
        print(attributes_json)
    else:
        print("No SD card info found.")


#--------------------------------------------CP Plus camera Status------------------------------------------
def get_cpplus_cam_status(camera_info):

    ip = camera_info["ip_address"]
    user = camera_info["username"]
    pwd = camera_info["password"]
    url = f"https://{ip}/cpapi/global.cgi?action=getCurrentTime"

    try:
        response = requests.get(
            url,
            auth=HTTPDigestAuth(user, pwd),
            headers={"Content-Type": "application/json"},
            verify=False,
            timeout=5
        )
        response.raise_for_status()
        if response.status_code == 200:
            return "Active"
    except requests.exceptions.Timeout:
        return "Inactive"
    except requests.exceptions.ConnectionError:
        return "Inactive"
    except requests.exceptions.HTTPError:
        return "Inactive"
    except Exception:
        return "Inactive"
    return "Inactive"


def main_cpplus_cam_status():

    camera_info_list = get_camera_info_list("CP_PlusNVR1")
    if not camera_info_list:
        print("No camera IPs found.")
        return

    cpplus_camera_status = []
    for cam in camera_info_list:
        try:
            status = get_cpplus_cam_status(cam)
            cpplus_camera_status.append({
                "camera_ip": cam["ip_address"],
                "camera_status": status
            })
        except Exception:
            cpplus_camera_status.append({
                "camera_ip": cam["ip_address"],
                "camera_status": "Inactive"
            })

    final_output = {"cpplus_camera_status": cpplus_camera_status}
    attributes_json = json.dumps(final_output)
    if logical_params_module.get_parameter("active_integration_hikvision_nvr") == 1:
        insert_json_to_db(attributes_json)
    print(attributes_json)

#----------------------------------------------------------------------------------------------------------


if __name__ == "__main__":

    # ACTIVE-INTEGRATION-GUARD: check flag before doing any work
    # If integration is disabled from the menu, exit cleanly.
    # systemd sees exit(0) as success and will NOT restart the service.
    # Service stays enabled — to re-activate, enable from menu then:
    #   sudo systemctl restart dexter-sd-hikvision
    if logical_params_module.get_parameter("active_integration_hikvision_nvr") != 1:
        import logging as _lg, sys as _sys
        _lg.getLogger(__name__).info(
            "[Hik_SD_Card.py] active_integration_hikvision_nvr=0 — integration disabled, exiting cleanly"
        )
        _sys.exit(0)

    # ── JITTER: deterministic per-panel startup delay (Strategy A) ────────────
    # Spreads 5,000 panels across a 300s window → ~17 panels/sec instead of
    # 5,000 at once. Same panel always gets the same offset on every reboot.
    # Applied once here — all subsequent interval fires inherit the offset.
    jitter = get_jitter_sec(window_sec=300)
    log.info("[startup] jitter delay = %ds", jitter)
    time.sleep(jitter)

    # ── Run all tasks once at startup ─────────────────────────────────────────
    hik_main_SDcard_Info()
    dahua_main_SDcard_Info()
    cpplus_main_SDcard_Info()

    main_hik_cam_status()
    main_dahua_cam_status()
    main_cpplus_cam_status()

    hik_main_SDcard_Record_Info()
    dahua_main_SDcard_Record_Info()

    # ── INTERVAL tasks: jitter already applied via startup delay ──────────────
    # Camera status checks are lightweight heartbeat-style polls — must remain
    # regular so we detect camera outages promptly. Jitter at startup ensures
    # these intervals are already spread across panels permanently.
    schedule.every(300).seconds.do(main_hik_cam_status)    # was every(1).hours — aligned to 5 min with other heartbeats
    schedule.every(300).seconds.do(main_dahua_cam_status)  # was every(63).minutes — aligned to 5 min
    schedule.every(300).seconds.do(main_cpplus_cam_status)

    # ── DAILY tasks: load-gated (Strategy B) — replaces fixed clock times ─────
    # Replaces four schedule.every().day.at() entries (17:15, 17:17, 17:20, 17:22).
    # Fixed clock times caused all 5,000 panels to flood ThingsBoard simultaneously.
    # Now each panel sends once per day only when its RPi CPU < 70% and
    # RAM < 75%, checked every 60s. Natural panel load variation produces
    # organic spread — no coordination required.
    import datetime as _dt
    _daily_sent_date_sdcard = None

    def maybe_send_daily_sdcard():
        global _daily_sent_date_sdcard
        today = _dt.date.today()
        if _daily_sent_date_sdcard == today:
            return  # already sent today
        if not is_rpi_idle():
            log.debug("[daily] RPi busy — deferring SD card / recording daily tasks")
            return
        # RPi is idle — send all daily bulk data
        log.info("[daily] RPi idle — sending SD card info and recording data")
        hik_main_SDcard_Record_Info()    # was 17:15
        dahua_main_SDcard_Record_Info()  # was 17:17
        hik_main_SDcard_Info()           # was 17:20
        dahua_main_SDcard_Info()         # was 17:22
        cpplus_main_SDcard_Info()
        _daily_sent_date_sdcard = today

    schedule.every(60).seconds.do(maybe_send_daily_sdcard)

    try:
        while True:
            time.sleep(10)
            schedule.run_pending()
            watchdog.reset()
    except KeyboardInterrupt:
        log.error("\nExiting program...")
 
