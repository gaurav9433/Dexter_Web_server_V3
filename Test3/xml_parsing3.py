# -*- coding: utf-8 -*-
# !/usr/local/bin/python


import requests
from hikvisionapi import Client
import xml.etree.ElementTree as ET
import json
import re
import time

import sys

import schedule
import datetime

from scheduler_utils import get_jitter_sec, is_rpi_idle

# DB-03: insert_json_to_db enforces 50K row hard cap + TTL purge
from buffer_manager import insert_json_to_db, init_db
init_db()  # Create buffer table if it does not exist yet
import device_parameters_module  

from requests.auth import HTTPDigestAuth
from requests.exceptions import ConnectionError
from syslog_file_logger import get_dual_logger
log = get_dual_logger('xml_parsing3')

# CQ-01: SoftwareWatchdog centralised in watchdog_manager.py
from watchdog_manager import SoftwareWatchdog
watchdog = SoftwareWatchdog(timeout=3600)

# Define a global variable for the desired structure
camera_info = {
    "cameraInfo": {}
}


device_type = 'HikvisionNVR1'
devices = device_parameters_module.get_device_parameters(device_type)
if not devices:
    log.error("No device credentials found for 'HikvisionNVR1' "
              "— add device via device_parameters_module")
    sys.exit(1)
ipaddress = devices[0]['ip_address']
userid = devices[0]['username']
passowrd = devices[0]['password']

print(ipaddress)
print(userid)
print(passowrd)


import logical_params_module
# Initialize the database
logical_params_module.initialize_database()


# Function to strip namespace from tag
def strip_namespace(tag):
    return re.sub(r'\{.*?\}', '', tag)

# Function to convert an XML element into a dictionary
def xml_to_dict(element):
    data_dict = {}
    
    # If element has attributes, add them
    if element.attrib:
        data_dict['attributes'] = element.attrib

    # If element has children, recurse
    if list(element):
        data_dict['data'] = {}
        for child in element:
            tag = strip_namespace(child.tag)
            data_dict['data'][tag] = xml_to_dict(child)
    else:
        # If element has no children, just add its text value
        data_dict = element.text or ""
    
    return data_dict

# Function to parse XML string to dictionary
def parse_xml_to_dict(xml_string):
    root = ET.fromstring(xml_string)
    return {strip_namespace(root.tag): xml_to_dict(root)}

# Generalized function to extract fields from any unknown structure
def extract_fields(data_dict):
    extracted_data = {}

    # Recursive function to traverse through the dictionary
    def traverse_dict(d, parent_key=''):
        if isinstance(d, dict):
            for key, value in d.items():
                if isinstance(value, dict):
                    # Recur for nested dictionaries
                    traverse_dict(value, key)
                else:
                    # If value is not a dictionary, add it to the extracted data
                    extracted_data[key] = value
        elif isinstance(d, list):
            for item in d:
                # Traverse each item in a list (if needed)
                traverse_dict(item)
        else:
            # If it is a string or other base type, add directly
            extracted_data[parent_key] = d

    # Call recursive function starting from the root of the data_dict
    traverse_dict(data_dict)

    return extracted_data


# Function to parse XML string and convert it to JSON
def parse_and_convert_to_json(xml_data):
    try:
        # Parse the XML string
        root = ET.fromstring(xml_data)
        
        # Convert the XML tree to a dictionary
        xml_dict = {root.tag: xml_to_dict(root)}
        
        # Convert the dictionary to JSON format
        json_data = json.dumps(xml_dict, indent=4)
        
        return json_data

    except ET.ParseError as e:
        log.error("Error parsing XML:", e)
        return None


def parse_and_convert_to_json_hdd(xml_data):
    try:
        # Parse the XML string
        root = ET.fromstring(xml_data)
        
        # Iterate through each <hdd> element and extract details
        hdd_list = []
        for hdd in root.findall('{http://www.hikvision.com/ver20/XMLSchema}hdd'):
            hdd_info = {
                'id': hdd.find('{http://www.hikvision.com/ver20/XMLSchema}id').text,
                'hddName': hdd.find('{http://www.hikvision.com/ver20/XMLSchema}hddName').text,
                'hddPath': hdd.find('{http://www.hikvision.com/ver20/XMLSchema}hddPath').text,
                'hddType': hdd.find('{http://www.hikvision.com/ver20/XMLSchema}hddType').text,
                'status': hdd.find('{http://www.hikvision.com/ver20/XMLSchema}status').text,
                'capacity': hdd.find('{http://www.hikvision.com/ver20/XMLSchema}capacity').text,
                'freeSpace': hdd.find('{http://www.hikvision.com/ver20/XMLSchema}freeSpace').text,
                'property': hdd.find('{http://www.hikvision.com/ver20/XMLSchema}property').text
            }
            hdd_list.append(hdd_info)
        
        # Create the JSON data structure
        json_data = {
            "hddList": {
                "version": root.attrib.get("version", ""),
                "hdds": hdd_list
            }
        }
        
        return json.dumps(json_data, indent=4)
    
    except ET.ParseError as e:
        log.error("Error parsing XML:", e)
        log.error("Error parsing XML:", e)
        return None


# XML string input (replace this with any unknown XML string)
xml_string = '''<StreamingChannelList version="1.0" xmlns="http://www.hikvision.com/ver20/XMLSchema">
    <StreamingChannel version="2.0" xmlns="http://www.isapi.org/ver20/XMLSchema">
        <enabled>true</enabled>
        <channelName>102</channelName>
        <Audio>
            <audioInputChannelID>1</audioInputChannelID>
            <enabled>true</enabled>
            <audioCompressionType>G.711ulaw</audioCompressionType>
        </Audio>
        <Transport>
            <ControlProtocolList>
                <ControlProtocol>
                    <streamingTransport>RTSP</streamingTransport>
                </ControlProtocol>
            </ControlProtocolList>
        </Transport>
        <id>102</id>
        <Video>
            <enabled>true</enabled>
            <dynVideoInputChannelID>1</dynVideoInputChannelID>
            <maxFrameRate>0</maxFrameRate>
            <SmartCodec>
                <enabled>true</enabled>
            </SmartCodec>
            <vbrLowerCap>32</vbrLowerCap>
            <snapShotImageType>JPEG</snapShotImageType>
            <GovLength>50</GovLength>
            <fixedQuality>60</fixedQuality>
            <vbrUpperCap>512</vbrUpperCap>
            <videoScanType>progressive</videoScanType>
            <videoCodecType>H.265</videoCodecType>
            <videoResolutionHeight>360</videoResolutionHeight>
            <videoQualityControlType>VBR</videoQualityControlType>
            <videoResolutionWidth>640</videoResolutionWidth>
        </Video>
    </StreamingChannel>
</StreamingChannelList>'''


# Update the payload with mandatory fields
payload1 = {
    "UserInfoSearchCond": {
        "searchID": "1",  # Unique ID for the search request
        "searchResultPosition": 0,  # Start position for the search results
        "maxResults": 10  # Maximum number of results to return
        # You can add more filters here, like "EmployeeNo", etc.
    }
}

# Update the payload with mandatory fields
payload2 = {
    "UserInfoSearchCond": {
        "searchID": "1",  # Unique ID for the search request
        "searchResultPosition": 0,  # Start position for the search results
        "maxResults": 10  # Maximum number of results to return
        # You can add more filters here, like "EmployeeNo", etc.
    }
}

# Payload for searching card information
payload3 = {
    "CardInfoSearchCond": {
        "searchID": "1",  # Unique ID for the search request
        "searchResultPosition": 0,  # Start position for the search results
        "maxResults": 10  # Maximum number of results to return
        # You can add specific filters for the card information search here
    }
}


# Update the payload with mandatory fields
payload4a = {
    "UserInfoSearchCond": {
        "searchID": "1",  # Unique ID for the search request
        "searchResultPosition": 0,  # Start position for the search results
        "maxResults": 10  # Maximum number of results to return
        # You can add more filters here, like "EmployeeNo", etc.
    }
}



def dict_to_xml(tag, d):  # nnnnnnnnnnnnnnnnnnnnnnnnnnaaaaaaaaaaaa
    """Convert a dictionary to an XML string with a single root tag."""
    element = ET.Element(tag)
    for key, val in d.items():
        child = ET.Element(key)
        child.text = str(val)
        element.append(child)
    return ET.tostring(element, encoding='utf8', method='xml')

# Sample payload dictionary
payload4 = {
    "SearchID": "12345",
    "MaxResults": "10",
    "StartTime": "2024-11-01T00:00:00Z",
    "EndTime": "2024-11-01T23:59:59Z"
}


def deviceInfo(response):

    print(response)
    
    json_output_raw = parse_and_convert_to_json(response)
    print(json_output_raw)


    #Step 1: Parse the XML string into a dictionary
    parsed_dict = parse_xml_to_dict(response)

    #Step 2: Extract key fields from the dictionary (automated for unknown structure)
    extracted_data = extract_fields(parsed_dict)

    print(extracted_data)

    #Output the result
    print("Extracted Data:")
    print(json.dumps(extracted_data, indent=4))


    # Optional: Store the extracted data in a Python variable
    attributes = extracted_data

    # Print the attributes
    print("Attributes Dictionary:")
    print(attributes)

    # Convert attributes to JSON string
    attributes_json = json.dumps(attributes)

    data = attributes

    #print(device_data)

    #print("Device Name:", device_data['deviceName'])

    # Access individual elements
    device_name = data.get('deviceName', 'NA')
    hardware_version = data.get('hardwareVersion', 'NA')
    mac_address = data.get('macAddress', 'NA')
    serial_number = data.get('serialNumber', 'NA')
    telecontrol_id = data.get('telecontrolID', 'NA')
    encoder_version = data.get('encoderVersion', 'NA')
    version = data.get('version', 'NA')
    device_type = data.get('deviceType', 'NA')
    device_id = data.get('deviceID', 'NA')
    firmware_released_date = data.get('firmwareReleasedDate', 'NA')
    model = data.get('model', 'NA')
    manufacturer = data.get('manufacturer', 'Hikvision')
    encoder_released_date = data.get('encoderReleasedDate', 'NA')
    firmware_version = data.get('firmwareVersion', 'NA')

    # Print individual values
    print("Device Name:", device_name)
    print("Hardware Version:", hardware_version)
    print("MAC Address:", mac_address)
    print("Serial Number:", serial_number)
    print("Telecontrol ID:", telecontrol_id)
    print("Encoder Version:", encoder_version)
    print("Version:", version)
    print("Device Type:", device_type)
    print("Device ID:", device_id)
    print("Firmware Released Date:", firmware_released_date)
    print("Model:", model)
    print("Manufacturer:", manufacturer)
    print("Encoder Released Date:", encoder_released_date)
    print("Firmware Version:", firmware_version)


    payload = "{"
    payload += "\"Hikvision_NVR_deviceName\":\"" + str(data.get("deviceName", "NA")) + "\","
    payload += "\"Hikvision_NVR_deviceID\":\"" + str(data.get("deviceID", "NA")) + "\","
    payload += "\"Hikvision_NVR_model\":\"" + str(data.get("model", "NA")) + "\","

    payload += "\"Hikvision_NVR_serialNumber\":\"" + str(data.get("serialNumber", "NA")) + "\","
    payload += "\"Hikvision_NVR_macAddress\":\"" + str(data.get("macAddress", "NA")) + "\","
    payload += "\"Hikvision_NVR_firmwareVersion\":\"" + str(data.get("firmwareVersion", "NA")) + "\","

    payload += "\"Hikvision_NVR_deviceType\":\"" + str(data.get("deviceType", "NA")) + "\","
    payload += "\"Hikvision_NVR_Processor\":\"NA\","
    payload += "\"Hikvision_NVR_hardwareVersion\":\"" + str(data.get("hardwareVersion", "NA")) + "\","

    payload += "\"Hikvision_NVR_Manufacturer\":\"" + str(data.get("manufacturer", "Hikvision")) + "\""
    payload += "}"

    attributes_json = payload

    #ret= client1.publish("v1/devices/me/telemetry",attributes_json)             #topic-v1/devices/me/telemetry
    #ret= client1.publish("v1/devices/me/attributes",attributes_json)             #topic-v1/devices/me/telemetry
    if logical_params_module.get_parameter("active_integration_hikvision_nvr") == 1:
        insert_json_to_db(attributes_json)
    print("Please check LATEST ATTRIBUTE field of your device")
    print(attributes_json)
    
    print("\n")


def hDDInfo(response):

    print(response)
    
    #json_output_raw = parse_and_convert_to_json(response)
    json_output_raw = parse_and_convert_to_json_hdd(response)
    print("json_output_raw:")
    print(json_output_raw)

    # Parse the JSON string
    parsed_data = json.loads(json_output_raw)

    # Extracting the version
    version = parsed_data['hddList']['version']

    # Extract HDD information dynamically
    hdds = parsed_data['hddList'].get('hdds', [])
    max_slots = 4
    slot_mapping = {}

    # Create slot mapping for available HDDs
    available_hdds = []
    for i, hdd in enumerate(hdds):
        available_hdds.append({
            'id': hdd.get('id', str(i + 1)),
            'status': hdd.get('status', 'notexist'),
            'freeSpace': hdd.get('freeSpace', 0),
            'capacity': hdd.get('capacity', 0),
            'hddName': hdd.get('hddName', 'Unknown'),
            'hddPath': hdd.get('hddPath', 'Unknown'),
            'property': hdd.get('property', 'Unknown'),
            'hddType': hdd.get('hddType', 'Unknown')
        })

    # Map available HDDs to slots
    for i, hdd in enumerate(available_hdds):
        slot_mapping[i] = hdd['id']

    # Build payload dynamically
    payload = "{"
    for slot, hdd in enumerate(available_hdds):
        payload += "\"Hikvision_NVR_NoOfHDDSlots{}\":\"{}\",".format(slot + 1, hdd['id'])
        payload += "\"Hikvision_NVR_Status{}\":\"{}\",".format(slot + 1, hdd['status'])
        payload += "\"Hikvision_NVR_capacity{}\":\"{}\",".format(slot + 1, hdd['capacity'])
        payload += "\"Hikvision_NVR_freeSpace{}\":\"{}\",".format(slot + 1, hdd['freeSpace'])

    # Remove trailing comma and close JSON object
    if payload.endswith(","):
        payload = payload[:-1]
    payload += "}"

    # Payload
    print(payload)

    # Wrap the payload in "Hikvision_NVR_HDDInfo"
    hdd_info = "{\"Hikvision_NVR_HDDInfo\":" + payload + "}"

    #attributes_json = payload

    attributes_json = hdd_info

    if logical_params_module.get_parameter("active_integration_hikvision_nvr") == 1:     
        insert_json_to_db(attributes_json)
    print("Please check LATEST ATTRIBUTE field of your device")
    print(attributes_json)
    
    print("\n")


def dataTime(response):

    from datetime import datetime

    print(response)
    
    json_output_raw = parse_and_convert_to_json(response)
    print(json_output_raw)


    #Step 1: Parse the XML string into a dictionary
    parsed_dict = parse_xml_to_dict(response)

    #Step 2: Extract key fields from the dictionary (automated for unknown structure)
    extracted_data = extract_fields(parsed_dict)

    print(extracted_data)

    #Output the result
    print("Extracted Data:")
    print(json.dumps(extracted_data, indent=4))


    # Optional: Store the extracted data in a Python variable
    attributes = extracted_data

    # Print the attributes
    print("Telemetry Dictionary:")
    print(attributes)

    # Convert attributes to JSON string
    attributes_json = json.dumps(attributes)

    data = attributes


    # Get the localTime value
    local_time_str = data['localTime']

    # Parse the localTime string into a datetime object
    local_time_obj = datetime.strptime(local_time_str[:19], "%Y-%m-%dT%H:%M:%S")

    # Store date and time separately
    date_part = local_time_obj.date()  # Get the date part
    time_part = local_time_obj.time()  # Get the time part

    # Print the separated date and time
    print("Date:", date_part)
    print("Time:", time_part)


    payload = "{"
    payload += "\"Hikvision_NVR_Date\":\"" + str(date_part) + "\","
    payload += "\"Hikvision_NVR_Time\":\"" + str(time_part) + "\""
    payload += "}"

    attributes_json = payload

    #ret= client1.publish("v1/devices/me/telemetry",attributes_json)             #topic-v1/devices/me/telemetry
    if logical_params_module.get_parameter("active_integration_hikvision_nvr") == 1:     
        insert_json_to_db(attributes_json)
    print("Please check LATEST TELEMETRY field of your device")
    print(attributes_json)
    
    print("\n")



def parse_xml_to_json_t(xml_string):
    # Function to strip namespace from tag
    def strip_namespace(tag):
        return re.sub(r'\{.*?\}', '', tag)

    # Recursive function to convert an XML element into a dictionary
    def xml_to_dict(element):
        data_dict = {}
        
        # If element has attributes, add them
        if element.attrib:
            data_dict['attributes'] = element.attrib

        # If element has children, recurse
        if list(element):
            # Check if the same tag appears multiple times, if so, store as a list
            data_dict['data'] = {}
            for child in element:
                tag = strip_namespace(child.tag)
                if tag not in data_dict['data']:
                    # If this tag appears for the first time
                    data_dict['data'][tag] = xml_to_dict(child)
                else:
                    # If this tag appears multiple times, convert to a list
                    if not isinstance(data_dict['data'][tag], list):
                        data_dict['data'][tag] = [data_dict['data'][tag]]  # Convert to list if it's not already
                    data_dict['data'][tag].append(xml_to_dict(child))
        else:
            # If element has no children, just add its text value
            data_dict = element.text or ""
        
        return data_dict

    try:
        # Parse the XML string
        root = ET.fromstring(xml_string)
        
        # Convert the XML tree to a dictionary
        xml_dict = {strip_namespace(root.tag): xml_to_dict(root)}
        
        # Convert the dictionary to JSON format
        json_data = json.dumps(xml_dict, indent=4)
        
        return json_data

    except ET.ParseError as e:
        log.error("Error parsing XML:", e)
        return None


def cameraInfo(response):

    json_output = parse_xml_to_json_t(response)
    print(json_output)

    # Parse the JSON string
    data = json.loads(json_output)

    input_proxy_channels = data['InputProxyChannelList']['data']['InputProxyChannel']
            
    channel_details = {}

    for channel in input_proxy_channels:
        channel_id = channel['data']['id']
        channel_details[channel_id] = {
            'Channel Name': channel['data']['name'],
            'Device Index': channel['data'].get('devIndex', 'N/A'),
            'IP Address': channel['data']['sourceInputPortDescriptor']['data']['ipAddress'],
            'Proxy Protocol': channel['data']['sourceInputPortDescriptor']['data']['proxyProtocol']
        }

    cam = Client('http://'+ipaddress, userid, passowrd)
    # Fetch and parse StreamingChannelList data
    response = cam.Streaming.channels(method='get', present='text')
    print(response)

    json_output = parse_xml_to_json_t(response)
    print(json_output)

    # Parse the JSON string
    data = json.loads(json_output)


    # List of specific channel IDs to process
    valid_channel_ids = ['101', '201', '301', '401', '501', '601', '701', '801', '901', '1001', '1101', '1201', '1301', '1401', '1501', '1601']


    streaming_channels = data['StreamingChannelList']['data']['StreamingChannel']

    for channel in streaming_channels:
        channel_id = channel['data']['id']
    
        # Check if the channel ID is in the valid_channel_ids list before processing
        if channel_id in valid_channel_ids:
            channel_key = str((int(channel_id) - 1) // 100)


           # raw_fps = int(channel['data']['Video']['data']['maxFrameRate'])
            video_data = channel.get('data', {}).get('Video', {}).get('data', {})
            try:
             raw_fps = int(video_data.get('maxFrameRate', 0))
            except:
             raw_fps = 0

            fps = 25 if raw_fps == 0 else raw_fps // 100

            #width=int(channel['data']['Video']['data']['videoResolutionWidth'])
            #height=int(channel['data']['Video']['data']['videoResolutionHeight'])

            try:
                width = int(video_data.get('videoResolutionWidth', 0))
                height = int(video_data.get('videoResolutionHeight', 0))
            except:
                width, height = 0, 0

            if width == 0 or height == 0:
                resolution = "1920x1080"
            else:
                resolution = "{}x{}".format(width, height)

            # Ensure the channel_key exists in channel_details before updating
            if channel_key in channel_details:
                channel_details[channel_key].update({
                    'Streaming Channel Name': channel['data'].get('channelName', 'NA'),
                    'Video Resolution': resolution,
                    'Max Frame Rate': fps
                })
            


            # ---- FILL DEFAULTS FOR MISSING STREAMS ----
    for key in channel_details:

        if 'Streaming Channel Name' not in channel_details[key]:
            channel_details[key].update({
                'Streaming Channel Name': 'NA',
                'Video Resolution': '1920x1080',
                'Max Frame Rate': 25
            })
            '''
            streaming_channels = data['StreamingChannelList']['data']['StreamingChannel']

            for channel in streaming_channels:
                channel_id = channel['data']['id']
                # Check if the channel ID exists, then add streaming details
                channel_id = str( ( ( int(channel_id)  - 1 ) / 100 ) )
                
                #print(channel_details)
                if channel_id in channel_details:
                    channel_details[channel_id].update({
                        'Streaming Channel Name': channel['data']['channelName'],
                        'Video Resolution': "{}x{}".format(
                            channel['data']['Video']['data']['videoResolutionWidth'],
                            channel['data']['Video']['data']['videoResolutionHeight']
                        ),
                        'Max Frame Rate': channel['data']['Video']['data']['maxFrameRate']
                    })

            '''                    

    # Combine everything under "cameraInfo"
    camera_info = {
        "Hikvision_NVR_cameraInfo": channel_details
        }

    log.error(camera_info)

    # Convert channel details to a JSON string
    channel_details_json = json.dumps(camera_info)
            
    # Output the JSON string
    log.error("Channel details JSON:", channel_details_json)

    # Now you can use channel_details_json to send to another API
    attributes_json = channel_details_json
    if logical_params_module.get_parameter("active_integration_hikvision_nvr") == 1: 
        insert_json_to_db(attributes_json)
    log.error("Please check LATEST ATTRIBUTE field of your device")
    log.error(attributes_json)
    
    log.error("\n")


def initExternalDevice():
    print(" Initialise Devices ")
    # Startup heartbeat — uses HTTP so offline NVR is detected correctly
    condition_2()

# -*- coding: utf-8 -*-
from collections import defaultdict
from dateutil.relativedelta import relativedelta


# NVR credentials and API endpoint
device_type = 'HikvisionNVR1'
devices = device_parameters_module.get_device_parameters(device_type)
if not devices:
    log.error("No device credentials found for 'HikvisionNVR1'")
    sys.exit(1)
nvr_ip = devices[0]['ip_address']
username_nvr = devices[0]['username']
password_nvr = devices[0]['password']

url = f"http://{nvr_ip}/ISAPI/ContentMgmt/search"

# Initialize the database once
logical_params_module.initialize_database()

# Retry-enabled POST request
def safe_post(url, data, headers, auth, retries=3, timeout=20):
    for attempt in range(1, retries + 1):
        try:
            return requests.post(url, data=data, headers=headers, auth=auth, timeout=timeout)
        except requests.exceptions.RequestException as e:
            if attempt == retries:
                raise
            time.sleep(1)

# Process a single camera with smart chunking
def process_camera(cam_index, months_back=60):
    track_id = 100 * cam_index + 1
    track_id_str = str(track_id)

    monthly_unique_days = defaultdict(set)
    all_days = set()
    all_day_times = set()
    now = datetime.utcnow()

    def fetch_for_range(start_dt, end_dt, month_key, level="month"):
        start_str = start_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        end_str = end_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

        search_position = 0
        loop_counter = 0
        total_matches = 0

        while True:
            xml_body = f"""<?xml version="1.0" encoding="utf-8"?>
<CMSearchDescription>
    <searchID>88C2CD4D-D3FA-4AD4-BD80-555C18205DCC</searchID>
    <trackList><trackID>{track_id}</trackID></trackList>
    <timeSpanList><timeSpan><startTime>{start_str}</startTime><endTime>{end_str}</endTime></timeSpan></timeSpanList>
    <maxResults>500</maxResults>
    <searchResultPostion>{search_position}</searchResultPostion>
    <metadataList><metadataDescriptor>//recordType.meta.std-cgi.com</metadataDescriptor></metadataList>
</CMSearchDescription>"""

            headers = {'Content-Type': 'application/xml', 'Connection': 'Keep-Alive'}
            try:
                response = safe_post(url, data=xml_body, headers=headers,
                                     auth=HTTPDigestAuth(username_nvr, password_nvr))
                if response.status_code != 200:
                    print(f"Camera {cam_index}: HTTP {response.status_code} error")
                    break

                try:
                    root = ET.fromstring(response.content)
                except ET.ParseError:
                    log.error(f"Camera {cam_index}: XML Parse Error")
                    break

                ns_uri = root.tag.split("}")[0].strip("{")
                namespace = {"ns": ns_uri}

                match_list = root.findall('.//ns:matchList/ns:searchMatchItem', namespace)
                if not match_list:
                    break

                for match in match_list:
                    start_elem = match.find('.//ns:timeSpan/ns:startTime', namespace)
                    if start_elem is not None:
                        dt = datetime.strptime(start_elem.text, "%Y-%m-%dT%H:%M:%SZ")
                        day_key = dt.strftime("%Y-%m-%d")
                        day_keyy = dt.strftime("%Y-%m-%d %H:%M:%S")
                        correct_month_key = dt.strftime("%Y-%m")

                        monthly_unique_days[correct_month_key].add(day_key)
                        all_days.add(day_key)
                        all_day_times.add(day_keyy)

                total_matches += len(match_list)
                search_position += len(match_list)
                loop_counter += 1

                response_status_elem = root.find('.//ns:responseStatusStrg', namespace)
                response_status = response_status_elem.text if response_status_elem is not None else ""
                if response_status != "MORE":
                    break

                if loop_counter > 1000:
                    log.error(f"Camera {cam_index}: Too many pages in {month_key} ({level}), stopping.")
                    break

                time.sleep(0.5)

            except Exception as e:
                log.error(f"Camera {cam_index}: Exception in {level} range - {str(e)}")
                break

        return total_matches

    MAX_RECURSION_DEPTH = 5

    def process_in_chunks(start_dt, end_dt, month_key, chunk_days=7, depth=0):
        if depth > MAX_RECURSION_DEPTH and chunk_days > 1:
            log.error(f" Reached max depth in recursion at {start_dt.date()} → {end_dt.date()}, skipping deeper split.")
            return

        chunk_start = start_dt
        while chunk_start < end_dt:
            chunk_end = min(chunk_start + relativedelta(days=chunk_days), end_dt)
            total = fetch_for_range(chunk_start, chunk_end, month_key, f"{chunk_days}-day")

            if total >= 10000:
                if chunk_days > 1:
                    log.error(f"Camera {cam_index}: High volume in chunk {chunk_start.date()} → {chunk_end.date()}, splitting into 1-day chunks.")
                    process_in_chunks(chunk_start, chunk_end, month_key, chunk_days=1, depth=depth+1)
                else:
                    log.error(f" Camera {cam_index}: Single day {chunk_start.date()} has >10,000 records — possible truncation.")

            chunk_start = chunk_end

    try:
        for i in range(months_back):
            start_dt = (now - relativedelta(months=i)).replace(day=1, hour=0, minute=0, second=0)
            end_dt = (start_dt + relativedelta(months=1))
            month_key = start_dt.strftime("%Y-%m")

            log.error(f"Camera {cam_index}: Processing month {month_key}")
            total = fetch_for_range(start_dt, end_dt, month_key, "month")

            if total >= 10000:
                log.error(f"Camera {cam_index}: Heavy month {month_key}, switching to weekly chunks")
                process_in_chunks(start_dt, end_dt, month_key, chunk_days=7)

    except Exception as e:
        log.error(f"Camera {cam_index}: Fatal Error - {str(e)}")
        log.error(f"Camera {cam_index}: Fatal Error - {str(e)}")

    sorted_day_counts = {month: len(days) for month, days in sorted(monthly_unique_days.items())}
    return {
        "camera_id": track_id_str,
        "recording_days_per_month": sorted_day_counts,
        "total_duration": len(all_days),
        "start_time": min(all_day_times) if all_day_times else None,
        "end_time": max(all_day_times) if all_day_times else None
    }

# Run all cameras sequentially
def run_all_cameras(camera_ids, months_back=60):
    results = []
    for cam_index in camera_ids:
        print(f"\n Processing Camera {cam_index}...\n")
        results.append(process_camera(cam_index, months_back))
    return results

# === Customize ===
camera_ids = range(1, 17)  # Cameras 1 to 16
months_back = 60           # Past 5 years

def getTrackIDInfo():
    camera_data = run_all_cameras(camera_ids, months_back)

    print("\n Monthly Unique Recording Days Per Camera:")
    for camera in camera_data:
        print(f"\n Camera ID: {camera['camera_id']}")
        for month, count in camera['recording_days_per_month'].items():
            print(f"  {month}: {count} recorded days")
        print(f"  Total Recorded Days: {camera['total_duration']}")
        print(f"  Start Recording Day: {camera['start_time']}")
        print(f"  End Recording Day:   {camera['end_time']}")

    # Remove 'recording_days_per_month' before sending to DB/cloud
    cleaned_camera_data = []
    for cam in camera_data:
        cam_cleaned = dict(cam)
        cam_cleaned.pop("recording_days_per_month", None)
        cleaned_camera_data.append(cam_cleaned)

    final_result = {
        "Hikvision_NVR_CameraRecInfo": cleaned_camera_data
    }

    attributes_json = json.dumps(final_result)
    print("\n Final JSON Payload:")
    print(attributes_json)

    if logical_params_module.get_parameter("active_integration_hikvision_nvr") == 1:
        insert_json_to_db(attributes_json)

    return final_result

#if __name__ == "__main__":
#    getTrackIDInfo()









def condition_1():
    print("[Scheduler] Condition 1")
    try:
        cam = Client('http://' + ipaddress, userid, passowrd)
        response = cam.System.deviceInfo(method='get', present='text')
        deviceInfo(response)
    except Exception as e:
        log.error("Error in Condition 1:", e)
        log.error("Error in Condition 1:", e)
        pass
    except ConnectionError as e:
        log.error("Failed to connect to the device at IP:", ipaddress)
        log.error("Error details:", e)
        log.error("Error details:", e)
        pass


def condition_2():
    print("[Scheduler] Condition 2")

    def _send_hb(status, reason=""):
        payload = json.dumps({"Hikvision_NVR_Heartbeat": status})
        if reason:
            log.error("Hikvision NVR %s — %s", status, reason)
        if logical_params_module.get_parameter("active_integration_hikvision_nvr") == 1:
            insert_json_to_db(payload)

    device_info_url = f"http://{ipaddress}/ISAPI/System/deviceInfo"
    try:
        response = requests.get(device_info_url, auth=HTTPDigestAuth(userid, passowrd),
                                verify=False, timeout=10)
        if response.status_code == 200:
            _send_hb("hikvision_nvr_on")
        elif response.status_code == 401:
            _send_hb("hikvision_nvr_LinkFail", "HTTP 401 — authentication failed")
        elif response.status_code == 403:
            _send_hb("hikvision_nvr_LinkFail", "HTTP 403 — access forbidden")
        else:
            _send_hb("hikvision_nvr_LinkFail", f"HTTP {response.status_code}")
    except requests.RequestException as e:
        _send_hb("hikvision_nvr_LinkFail", str(e))


def condition_3():
    print("[Scheduler] Condition 3")
    try:
        cam = Client('http://' + ipaddress, userid, passowrd)
        response = cam.System.time(method='get', present='text')
        dataTime(response)
    except Exception as e:
        log.error("Error in Condition 3:", e)
        log.error("Error in Condition 3:", e)
        pass
    except ConnectionError as e:
        log.error("Failed to connect to the device at IP:", ipaddress)
        log.error("Error details:", e)
        pass       


def condition_4():
    print("[Scheduler] Condition 4")
    try:
        cam = Client('http://' + ipaddress, userid, passowrd)
        response = cam.ContentMgmt.Storage.hdd(method='get', present='text')
        hDDInfo(response)
    except Exception as e:
        log.error("Error in Condition 4:", e)
        pass
    except ConnectionError as e:
        log.error("Failed to connect to the device at IP:", ipaddress)
        log.error("Error details:", e)
        pass


def condition_5():
    print("[Scheduler] Condition 5")
    try:
        cam = Client('http://' + ipaddress, userid, passowrd)
        response = cam.ContentMgmt.InputProxy.channels(method='get', present='text')
        cameraInfo(response) 
    except Exception as e:
        log.error("Error in Condition 5:", e)
        log.error("Error in Condition 5:", e)
        pass
    except ConnectionError as e:
        log.error("Failed to connect to the device at IP:", ipaddress)
        log.error("Error details:", e)
        log.error("Error details:", e)
        pass


def condition_6():
    print("[Scheduler] Condition 6")
    try:
        getTrackIDInfo()
    except Exception as e:
        log.error("Error in Condition 6:", e)
        log.error("Error in Condition 6:", e)
        pass
    except ConnectionError as e:
        log.error("Failed to connect to the device at IP:", ipaddress)
        log.error("Error details:", e)
        log.error("Error details:", e)
        pass      
        

if __name__ == "__main__":
    
    # ACTIVE-INTEGRATION-GUARD: check flag before doing any work
    # If disabled from menu, exit cleanly — systemd will NOT restart (exit 0)
    if logical_params_module.get_parameter("active_integration_hikvision_nvr") != 1:
        import logging as _lg
        _lg.getLogger(__name__).info(
            "[xml_parsing3.py] active_integration_hikvision_nvr=0 — integration disabled, exiting cleanly"
        )
        sys.exit(0)
    # ── JITTER: deterministic per-panel startup delay (Strategy A) ────────────
    # Spreads 5,000 panels across a 300s window → ~17 panels/sec instead of
    # 5,000 at once. Same panel always gets the same offset on every reboot.
    jitter = get_jitter_sec(window_sec=300)
    log.info("[startup] jitter delay = %ds", jitter)
    time.sleep(jitter)

    initExternalDevice()

    condition_1()
    condition_2()
    condition_3()
    condition_4()
    condition_5()

    # ── INTERVAL tasks: jitter is already applied via startup delay ───────────
    schedule.every(300).seconds.do(condition_2)   # NVR heartbeat — every 5 min
    schedule.every(900).seconds.do(condition_3)   # NVR time sync  — every 15 min

    # ── DAILY tasks: load-gated (Strategy B) — replaces fixed clock times ─────
    # Fires condition_1, condition_4, condition_5 once per day only when the
    # RPi CPU < 70% and RAM < 75%, checked every 60s. Natural per-panel spread
    # eliminates the 17:05–17:22 thundering herd across all 5,000 panels.
    _daily_sent_date_xml3 = None

    def maybe_send_daily_xml3():
        global _daily_sent_date_xml3
        today = datetime.date.today()
        if _daily_sent_date_xml3 == today:
            return  # already sent today
        if not is_rpi_idle():
            log.debug("[daily] RPi busy — deferring Hikvision NVR daily tasks")
            return
        # RPi is idle — send all daily bulk data
        log.info("[daily] RPi idle — sending Hikvision NVR daily data")
        condition_1()   # camera / device info
        condition_4()   # HDD storage info
        condition_5()   # channel / camera list
        _daily_sent_date_xml3 = today

    schedule.every(60).seconds.do(maybe_send_daily_xml3)

    try:
        while True:
            time.sleep(1)
            schedule.run_pending()
            watchdog.reset()
    except KeyboardInterrupt:
        log.error("\nExiting program...")
