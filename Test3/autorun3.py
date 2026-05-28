#!/usr/bin/env python
import subprocess
import time

# Paths and services
INTERNAL_SERVICE = "internal_device_active_integration.service"
EXTERNAL_SERVICE = "external_device_active_integration.service"
WEBSERVER_SERVICE = "webserver_V3_integration.service"
INTERNAL_SCRIPT = "/home/pi/Test3/internal_device_active_integration.sh"
EXTERNAL_SCRIPT = "/home/pi/Test3/external_device_active_integration.sh"
WEBSERVER_SCRIPT = "/home/pi/Test3/webserver/webserver_V3_integration.sh"

def run_cmd(cmd):
    try:
        output = subprocess.check_output(cmd, shell=True, stderr=subprocess.STDOUT).decode()
        return output
    except subprocess.CalledProcessError as e:
        return e.output.decode()

def perform_one_time_setup():
    print("\nPerforming one-time setup (chmod + daemon-reload)...\n")
    print(run_cmd(f"sudo chmod +x {INTERNAL_SCRIPT}"))
    print(run_cmd(f"sudo chmod +x {EXTERNAL_SCRIPT}"))
    print(run_cmd("sudo systemctl daemon-reload"))

def enable_both_services():
    print("\nEnabling both services...\n")
    print(run_cmd(f"sudo systemctl enable {INTERNAL_SERVICE}"))
    print(run_cmd(f"sudo systemctl start {INTERNAL_SERVICE}"))
    print(run_cmd(f"sudo systemctl enable {EXTERNAL_SERVICE}"))
    print(run_cmd(f"sudo systemctl start {EXTERNAL_SERVICE}"))

def disable_both_services():
    print("\nDisabling both services...\n")
    print(run_cmd(f"sudo systemctl disable {INTERNAL_SERVICE}"))
    print(run_cmd(f"sudo systemctl stop {INTERNAL_SERVICE}"))
    print(run_cmd(f"sudo systemctl disable {EXTERNAL_SERVICE}"))
    print(run_cmd(f"sudo systemctl stop {EXTERNAL_SERVICE}"))

def check_both_status():
    print("\nChecking status of both services...\n")
    print(f"--- {INTERNAL_SERVICE} ---")
    print(run_cmd(f"sudo systemctl status {INTERNAL_SERVICE}"))
    print(f"--- {EXTERNAL_SERVICE} ---")
    print(run_cmd(f"sudo systemctl status {EXTERNAL_SERVICE}"))

def perform_one_time_websetup():
    print("\nPerforming one-time setup (chmod + daemon-reload)...\n")
    print(run_cmd(f"sudo chmod +x {WEBSERVER_SCRIPT}"))
    print(run_cmd("sudo systemctl daemon-reload"))    

def enable_webserver_service():
    print("\nEnabling webserver service...\n")
    print(run_cmd(f"sudo systemctl enable {WEBSERVER_SERVICE}"))
    print(run_cmd(f"sudo systemctl start {WEBSERVER_SERVICE}"))

def disable_webserver_service():
    print("\nDisabling webserver service...\n")
    print(run_cmd(f"sudo systemctl disable {WEBSERVER_SERVICE}"))
    print(run_cmd(f"sudo systemctl stop {WEBSERVER_SERVICE}"))

def check_webserver_status():
    print("\nChecking webserver service status...\n")
    print(run_cmd(f"sudo systemctl status {WEBSERVER_SERVICE}"))

def show_menu():
    print("\n===== Manage Integration Services =====")
    print("1. One-Time Setup (chmod + daemon-reload)")
    print("2. Enable Both Services (internal + external)")
    print("3. Disable Both Services (internal + external)")
    print("4. Check Status of Both Services")
    print("5. One-Time webSetup (chmod + daemon-reload)")
    print("6. Enable Webserver Service")
    print("7. Disable Webserver Service")
    print("8. Status of Webserver Service")
    print("9. Exit and Reboot")
    print("10. Exit Without Reboot")
    print("========================================")

def main():
    while True:
        show_menu()
        choice = input("Enter your choice (1-10): ").strip()
        if choice == "1":
            perform_one_time_setup()
        elif choice == "2":
            enable_both_services()
        elif choice == "3":
            disable_both_services()
        elif choice == "4":
            check_both_status()
        elif choice == "5":
            perform_one_time_websetup()    
        elif choice == "6":
            enable_webserver_service()
        elif choice == "7":
            disable_webserver_service()
        elif choice == "8":
            check_webserver_status()
        elif choice == "9":
            print("Rebooting system in 3 seconds...")
            time.sleep(3)
            run_cmd("sudo reboot")
            break
        elif choice == "10":
            print("Exiting without reboot...")
            break
        else:
            print("Invalid input. Please enter a number from 1 to 9.")

if __name__ == "__main__":
    main()
