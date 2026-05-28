# -*- coding: utf-8 -*-
# !/usr/local/bin/python
"""
nvr_health — NVR/BACS vendor health check functions

Extracted from TLChronosProMAIN_391.py as part of Sprint C decomposition.
These functions had zero dependency on hardware globals (lcd, keypad,
shiftRegister buffers, zoneSettings) and could be safely moved.

Public functions:
#   check_hikvision_nvr()
#   check_dahua_nvr()
#   check_cp_plus_nvr()
#   check_hikvision_biometric()
#   check_hikvision_status()
#   get_device_credentials()

Sprint C: Option C — safe partial extraction of stand-alone utility functions.
          Full PanelController decomposition deferred to Sprint C2 (requires
          unit tests first — see OPEN-01).
"""
import requests
from requests.auth import HTTPDigestAuth
from requests.exceptions import ConnectionError as RequestsConnectionError
from hikvisionapi import Client
import logging

from syslog_file_logger import get_dual_logger
log = get_dual_logger(__name__)


def check_hikvision_nvr(): 
    device_type = 'HikvisionNVR1'
    devices = device_parameters_module.get_device_parameters(device_type)
    ipaddress = devices[0][2]
    userid = devices[0][3]
    password = devices[0][4]

    try:
        # Simulating a client connection to Hikvision NVR
        cam = Client('http://' + ipaddress, userid, password)
        return "Active"

    except ConnectionError as e:
        return "Inactive"

    except Exception as e:
        return "Inactive"



def check_dahua_nvr():
    device_type = 'DahuaNVR1'
    devices = device_parameters_module.get_device_parameters(device_type)
    ipaddress = devices[0][2]
    username = devices[0][3]
    password = devices[0][4]

    url = 'http://{}/cgi-bin/magicBox.cgi?action=getVendor'.format(ipaddress)

    try:
        response = requests.get(url, auth=HTTPDigestAuth(username, password), verify=False, timeout=10)

        if response.status_code == 200:
            return "Active"
        else:
            print("Unexpected status code from Dahua NVR:", response.status_code)

    except requests.RequestException as e:
        return "Inactive"


def check_cp_plus_nvr():
    device_type = 'CP_PlusNVR1'
    devices = device_parameters_module.get_device_parameters(device_type)
    ipaddress = devices[0][2]
    username = devices[0][3]
    password = devices[0][4]

    url = 'http://{}/cgi-bin/magicBox.cgi?action=getVendor'.format(ipaddress)

    try:
        response = requests.get(url, auth=HTTPDigestAuth(username, password), verify=False, timeout=10)

        if response.status_code == 200:
            return "Active"
        else:
            print("Unexpected status code from CP_PLUS NVR:", response.status_code)

    except requests.RequestException as e:
        return "Inactive"


def check_hikvision_biometric():
    device_type = 'HikvisionBioMetric1'
    devices = device_parameters_module.get_device_parameters(device_type)

    if not devices or len(devices[0]) < 5:
        return "Inactive"

    ipaddress = devices[0][2]
    username = devices[0][3]
    password = devices[0][4]
    url = 'http://{}/ISAPI/System/deviceInfo'.format(ipaddress)

    try:
        response = requests.get(url, auth=(username, password), timeout=10)

        if response.status_code == 200:
            return "Active"
        else:
            print("Unexpected response from Hikvision Biometric:", response.status_code)

    except requests.RequestException as e:
        return "Inactive"

# Example usage:
import requests
from requests.auth import HTTPDigestAuth
import device_parameters_module  # Assuming the second script is named 'device_parameters_module.py'


def check_hikvision_status(device_type):
    """
    Check the connection status of a Hikvision biometric device.

    :param device_type: The type of the device (e.g., 'HikvisionBioMetric1').
    :return: "Active" if the connection is established, "Inactive" otherwise.
    """
    server_ip, username, password = get_device_credentials(device_type)

    # Validate the credentials retrieved
    if not server_ip or not username or not password:
        return "Inactive"

    try:
        # Form the URL to check device status
        url = 'http://{}/ISAPI/System/deviceInfo'.format(server_ip)

        # Send GET request with HTTP Digest Authentication
        response = requests.get(url, auth=HTTPDigestAuth(username, password), verify=False, timeout=10)

        # Evaluate the response status code
        if response.status_code == 200:
            return "Active"
        elif response.status_code in (401, 403):
            return "Inactive"
        else:
            return "Inactive"

    except requests.RequestException as e:
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
        server_ip = devices[0][2]
        username = devices[0][3]
        password = devices[0][4]

        # Return the extracted credentials.
        return server_ip, username, password

    except Exception as e:
        print("Error retrieving device credentials: {}".format(str(e)))
        logger.error("Error retrieving device credentials: {}".format(str(e)))
        return None, None, None

# Example usage
#device_type = 'HikvisionBioMetric1'
#status = check_hikvision_status(device_type)


counterTimer1Sec4 = 0
counterTimer1Sec5 = 0
SCHEDULE_UPDATE_2_TB = 300
SCHEDULE_UPDATE_2_ACTIVE_DEVICE_TB = 30
logTypeSysParam = 0

battery_voltage = 0
panel_current = 0
ac_voltage = 0
is_valid_network_available = False
