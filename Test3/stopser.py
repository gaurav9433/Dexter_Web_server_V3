
import os
import signal
import subprocess

def stop_autorun(script_name="/home/pi/Test3/SerialCommunication.py"):
    try:
        # Find PID of the running script
        pids = subprocess.check_output(["pgrep", "-f", script_name]).decode().splitlines()
        for pid in pids:
            os.kill(int(pid), signal.SIGTERM)  # send kill signal
        print(f"Stopped {script_name}. It will start again on next reboot.")
    except (subprocess.CalledProcessError, FileNotFoundError):
        # CalledProcessError: process not running
        # FileNotFoundError: pgrep not available (Docker container — serial runs in dexter-serial-comm)
        print(f"{script_name} not running.")

#stop_autorun()
