#!/usr/bin/python3
# externalDeviceConfig.py — CLI wrapper around device_parameters_module.
# Passwords are Fernet-encrypted via the module; this file never touches
# the DB directly so encryption is always applied consistently.

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import device_parameters_module as _dpm


def _list_devices() -> None:
    devices = _dpm.list_devices()
    if not devices:
        print("No devices found.")
        return
    for d in devices:
        print(f"ID: {d['id']}  Type: {d['device_type']}  IP: {d['ip_address']}"
              f"  User: {d['username']}  Port: {d['port']}")


def user_interface() -> None:
    while True:
        print("\n1. Add Device")
        print("2. Delete Device")
        print("3. Modify Device")
        print("4. List Devices")
        print("5. Exit")
        try:
            choice = int(input("Enter your choice: "))
        except ValueError:
            print("Invalid input.")
            continue

        if choice == 1:
            device_type = input("Device Type (e.g. HikvisionNVR1): ")
            ip_address  = input("IP Address: ")
            username    = input("Username: ")
            password    = input("Password: ")
            port        = int(input("Port: "))
            ok = _dpm.add_device(device_type, ip_address, username, password, port)
            print("Device added." if ok else "Failed to add device.")

        elif choice == 2:
            device_id = int(input("Device ID to delete: "))
            ok = _dpm.delete_device(device_id)
            print("Device deleted." if ok else "Device not found.")

        elif choice == 3:
            device_id   = int(input("Device ID to modify: "))
            device_type = input("Device Type: ")
            ip_address  = input("IP Address: ")
            username    = input("Username: ")
            password    = input("Password: ")
            port        = int(input("Port: "))
            ok = _dpm.modify_device(device_id, device_type, ip_address,
                                    username, password, port)
            print("Device updated." if ok else "Failed to update device.")

        elif choice == 4:
            _list_devices()

        elif choice == 5:
            break

        else:
            print("Invalid choice.")


if __name__ == "__main__":
    user_interface()