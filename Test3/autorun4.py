#!/usr/bin/env python3
"""
autorun4.py - Dexter HMS Service Manager
Testing engineer tool for managing all Docker containers.

Usage:
    python3 autorun4.py
"""

import subprocess
import time
import os
import sys

# -- All services managed by docker compose ------------------------------------
DOCKER_CONTAINERS = [
    # Core (restart: unless-stopped)
    ("dexter-core",                "Main Panel Controller        (TLChronosProMAIN_391.py)"),
    ("dexter-webserver",           "Flask Webserver              (seple.py - port 5001)"),
    ("dexter-serial-comm",         "Serial RS-232/485 Controller (SerialCommunication.py)"),
    ("dexter-serial-logger",       "Serial Data Logger           (serial_data_logger.py)"),
    ("dexter-rpi-task",            "RPi Health Monitor           (RPi_Task_Manager.py)"),
    ("dexter-exporter",            "Prometheus Debug Exporter    (port 8000)"),
    # Network-aware (restart: on-failure — exits 0 in GSM mode)
    ("dexter-mqtt",                "ThingsBoard MQTT Publisher   (thingsboard_mqtt_publisher.py)"),
    ("dexter-ota-restore",         "OTA Restore Pipeline         (ota_main_restore.py)"),
    # Integrations (restart: on-failure — exits 0 when disabled in DB)
    ("dexter-nvr-hikvision",       "Hikvision NVR Poller         (xml_parsing3.py)"),
    ("dexter-nvr-hikvision-field", "Hikvision Alert Stream       (xml_parsing_field_log.py)"),
    ("dexter-nvr-hikvision-bacs",  "Hikvision Biometric BACS     (hikvision1_biometric_14.py)"),
    ("dexter-nvr-hik-lite",        "Hikvision Recording Analytics(hiknvrlite7.py)"),
    ("dexter-rtc-hikvision",       "Hikvision RTC Sync           (hik_RTC_sync.py)"),
    ("dexter-sd-hikvision",        "Hikvision SD/HDD Recorder    (Hik_SD_Card.py)"),
    ("dexter-hik-bas",             "Hikvision BAS Integration    (hikvision_bas_integration.py)"),
    ("dexter-rtc-hik-bas",         "Hikvision BAS RTC Sync       (hik_bas_rtc_sync.py)"),
    ("dexter-nvr-dahua",           "Dahua NVR Poller             (dahua_nvr_dvr_information.py)"),
    ("dexter-extract-dahua",       "Dahua Event Log Extractor    (Extract_Logs_Dahua_41.py)"),
    ("dexter-rtc-dahua",           "Dahua RTC Sync               (dahua_RTC_sync.py)"),
    ("dexter-sd-dahua",            "Dahua SD/HDD Recorder        (Dahua_SD_Card_HDD_Recording.py)"),
    ("dexter-rec-dahua",           "Dahua NVR Recording Info     (dahua_nvr_rec7.py)"),
    ("dexter-nvr-cpplus",          "CP Plus NVR Poller           (cp_plus_nvr_dvr_information.py)"),
    ("dexter-extract-cpplus",      "CP Plus Event Log Extractor  (Extract_Logs_CP_Plus_42.py)"),
    ("dexter-rtc-cpplus",          "CP Plus RTC Sync             (cp_plus_RTC_sync.py)"),
    ("dexter-sd-cpplus",           "CP Plus SD/HDD Recorder      (CP_Plus_SD_Card_HDD_Recording.py)"),
    ("dexter-rec-cpplus",          "CP Plus NVR Recording Info   (cpplusNvrRec.py)"),
    ("dexter-texecom-bas",         "Texecom BAS Integration      (texecomConnect.py)"),
    ("dexter-amc",                 "AMC X412V BAS Integration    (amc_integration.py)"),
    ("dexter-dsc-neo-bas",         "DSC Neo BAS Integration      (dsc_neo_integration.py)"),
]

DOCKER_COMPOSE_FILE = "/home/pi/Test3/docker-compose.yml"

# -- Colours ------------------------------------------------------------------
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
RESET  = "\033[0m"
DIM    = "\033[2m"

def clr(text, colour): return f"{colour}{text}{RESET}"
def ok(t):   return clr(t, GREEN)
def err(t):  return clr(t, RED)
def warn(t): return clr(t, YELLOW)
def info(t): return clr(t, CYAN)
def bold(t): return clr(t, BOLD)

# -- Helpers ------------------------------------------------------------------
def run(cmd, capture=True):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=capture, text=True)
        return (r.stdout + r.stderr).strip()
    except Exception as e:
        return str(e)

def get_docker_status(container):
    r = subprocess.run(
        ["docker", "inspect", "--format={{.State.Status}}|{{.State.ExitCode}}", container],
        capture_output=True, text=True
    )
    if r.returncode != 0:
        return "not found"
    parts = r.stdout.strip().split("|")
    state = parts[0] if parts else "unknown"
    try:
        code = int(parts[1]) if len(parts) > 1 else -1
    except ValueError:
        code = -1
    if state == "exited":
        if code == 0:
            return "disabled"       # integration off in DB - expected
        if code in (137, 143):
            return "stopped"        # docker stop (SIGKILL/SIGTERM) - manual
        return "crashed"            # unexpected non-zero - needs attention
    return state

def docker_status_icon(container):
    s = get_docker_status(container)
    if s == "running":    return ok("[ON]  running ")
    if s == "disabled":   return info("[ ]   disabled")
    if s == "stopped":    return warn("[ ]   stopped ")
    if s == "crashed":    return err("[!]   crashed ")
    if s == "restarting": return err("[~]   restart ")
    if s == "not found":  return err("[!]   missing ")
    return DIM + s.ljust(10) + RESET

def press_enter():
    input(f"\n{DIM}Press Enter to continue...{RESET}")

def clear():
    os.system("clear")

def header(title):
    clear()
    w = 60
    print(bold("=" * w))
    print(bold(f"  DEXTER HMS -- {title}"))
    print(bold("=" * w))
    print()

# -- Menu functions -----------------------------------------------------------

CORE_COUNT = 8   # first 8 entries in DOCKER_CONTAINERS are core services

def show_all_status():
    header("SERVICE STATUS")
    core = DOCKER_CONTAINERS[:CORE_COUNT]
    integrations = DOCKER_CONTAINERS[CORE_COUNT:]
    print(bold(f"  -- Core Containers ({len(core)}) " + "-" * 45))
    print(f"  {'Container':<35} {'Status':<15} Description")
    print(f"  {'-'*35} {'-'*15} {'-'*28}")
    for name, desc in core:
        icon = docker_status_icon(name)
        short_desc = desc.split("(")[0].strip()
        print(f"  {name:<35} {icon}  {short_desc}")
    print()
    print(bold(f"  -- Integration Containers ({len(integrations)}) " + "-" * 38))
    print(f"  {'Container':<35} {'Status':<15} Description")
    print(f"  {'-'*35} {'-'*15} {'-'*28}")
    for name, desc in integrations:
        icon = docker_status_icon(name)
        short_desc = desc.split("(")[0].strip()
        print(f"  {name:<35} {icon}  {short_desc}")
    print()
    press_enter()


def start_all():
    header("START ALL CONTAINERS")
    print("Starting all Docker containers (docker compose up -d)...")
    out = run(f"cd /home/pi/Test3 && docker compose up -d")
    if out: print(out)
    time.sleep(3)
    running = sum(1 for name, _ in DOCKER_CONTAINERS if get_docker_status(name) == "running")
    print(ok(f"\n  {running} containers running")) if running > 0 else print(err("\n  No containers started"))
    press_enter()


def stop_all():
    header("STOP ALL CONTAINERS")
    print(warn("Stopping all Docker containers (docker compose down)..."))
    out = run(f"cd /home/pi/Test3 && docker compose down")
    if out: print(out)
    time.sleep(2)
    running = sum(1 for name, _ in DOCKER_CONTAINERS if get_docker_status(name) == "running")
    print(ok("\n  All containers stopped") if running == 0 else err(f"\n  {running} still running"))
    press_enter()


def restart_all():
    header("RESTART ALL CONTAINERS")
    print(warn("  This stops all containers, waits 5s, then starts them again."))
    print(warn("  (5s gap prevents GPIO busy error on dexter-core)"))
    print()
    confirm = input("  Confirm restart? [Y/n]: ").strip().lower()
    if confirm == "n":
        return
    print("\n  Stopping...")
    run(f"cd /home/pi/Test3 && docker compose down")
    print("  Waiting 5 seconds...")
    time.sleep(5)
    print("  Starting...")
    out = run(f"cd /home/pi/Test3 && docker compose up -d")
    if out: print(out)
    time.sleep(3)
    running = sum(1 for name, _ in DOCKER_CONTAINERS if get_docker_status(name) == "running")
    print(ok(f"\n  Restarted -- {running} containers running"))
    press_enter()


def individual_service_menu():
    while True:
        header("INDIVIDUAL CONTAINER CONTROL")
        print(f"  {'#':<4} {'Container':<35} Status")
        print(f"  {'-'*4} {'-'*35} {'-'*15}")
        for i, (name, desc) in enumerate(DOCKER_CONTAINERS, 1):
            icon = docker_status_icon(name)
            print(f"  {str(i)+'.':<4} {name:<35} {icon}")
        print()
        print(f"  {bold('0.')} Back to main menu")
        print()
        choice = input("  Select container number: ").strip()

        if choice == "0":
            break

        try:
            idx = int(choice) - 1
            if idx < 0 or idx >= len(DOCKER_CONTAINERS):
                raise ValueError
        except ValueError:
            print(err("  Invalid choice"))
            time.sleep(1)
            continue

        name, desc = DOCKER_CONTAINERS[idx]
        container_action_menu(name, desc)


def container_action_menu(name, desc):
    while True:
        header(f"CONTAINER: {name}")
        icon = docker_status_icon(name)
        print(f"  Container : {bold(name)}")
        print(f"  Script    : {DIM}{desc.split('(')[-1].rstrip(')')}{RESET}")
        print(f"  Status    : {icon}")
        print()
        print(f"  1. Start")
        print(f"  2. Stop")
        print(f"  3. Restart")
        print(f"  4. View last 50 log lines")
        print(f"  5. Watch live logs (Ctrl+C to stop)")
        print(f"  0. Back")
        print()
        choice = input("  Choice: ").strip()

        if choice == "0":
            break
        elif choice == "1":
            out = run(f"docker start {name}")
            time.sleep(2)
            s = get_docker_status(name)
            print(ok(f"  Started -- {s}") if s == "running" else err(f"  Failed: {s}"))
            if out: print(out)
            press_enter()
        elif choice == "2":
            out = run(f"docker stop {name}")
            time.sleep(1)
            s = get_docker_status(name)
            print(ok("  Stopped") if s != "running" else err("  Still running"))
            if out: print(out)
            press_enter()
        elif choice == "3":
            out = run(f"docker restart {name}")
            time.sleep(3)
            s = get_docker_status(name)
            print(ok(f"  Restarted -- {s}") if s == "running" else err(f"  Failed: {s}"))
            if out: print(out)
            press_enter()
        elif choice == "4":
            clear()
            print(bold(f"=== Last 50 lines: {name} ===\n"))
            out = run(f"docker logs {name} --tail 50")
            print(out)
            press_enter()
        elif choice == "5":
            clear()
            print(bold(f"=== Live logs: {name} (Ctrl+C to stop) ===\n"))
            try:
                subprocess.run(f"docker logs -f {name}", shell=True)
            except KeyboardInterrupt:
                pass
            press_enter()
        else:
            print(err("  Invalid choice"))
            time.sleep(1)


def view_logs_menu():
    while True:
        header("VIEW LOGS")
        print(f"  {'#':<4} {'Container':<35} Status")
        print(f"  {'-'*4} {'-'*35} {'-'*15}")
        for i, (name, desc) in enumerate(DOCKER_CONTAINERS, 1):
            icon = docker_status_icon(name)
            print(f"  {str(i)+'.':<4} {name:<35} {icon}")
        print()
        print(f"  {bold('A.')}  All containers -- live stream (Ctrl+C to stop)")
        print(f"  {bold('0.')}  Back")
        print()
        choice = input("  Select container number (or A/0): ").strip().upper()

        if choice == "0":
            return

        if choice == "A":
            clear()
            print(bold("=== All containers live (Ctrl+C to stop) ===\n"))
            try:
                subprocess.run(
                    f"docker compose -f {DOCKER_COMPOSE_FILE} logs -f",
                    shell=True
                )
            except KeyboardInterrupt:
                pass
            press_enter()
            continue

        try:
            idx = int(choice) - 1
            if idx < 0 or idx >= len(DOCKER_CONTAINERS):
                raise ValueError
        except ValueError:
            print(err("  Invalid choice"))
            time.sleep(1)
            continue

        name, _ = DOCKER_CONTAINERS[idx]
        clear()
        print(bold(f"=== Last 50 lines: {name} ===\n"))
        print(run(f"docker logs {name} --tail 50"))
        press_enter()


def boot_diagnosis():
    header("BOOT DIAGNOSIS")
    script = "/home/pi/systemd_final/dexter_boot_diagnose.sh"
    if not os.path.exists(script):
        print(warn(f"  Script not found: {script}"))
        press_enter()
        return
    print("Running boot diagnosis...\n")
    out = run(f"sudo bash {script}")
    print(out)
    press_enter()


def wifi_check():
    header("WIFI HOTSPOT STATUS")
    print("Checking WiFi hotspot components...\n")
    checks = [
        ('ip addr show wlan0 | grep "inet "',                          "wlan0 IP (expect 192.168.5.1)"),
        ('ss -tlnp | grep 5001',                                        "Port 5001 (webserver)"),
        ('systemctl is-active hostapd',                                 "hostapd (WiFi broadcast)"),
        ('systemctl is-active dnsmasq',                                 "dnsmasq (DHCP for phones)"),
        ('docker inspect dexter-webserver --format={{.State.Status}}',  "dexter-webserver (Docker)"),
    ]
    all_ok = True
    for cmd, label in checks:
        out = run(cmd)
        if out and out not in ("inactive", "failed", "unknown"):
            print(ok(f"  [OK] {label}"))
            print(f"       {DIM}{out}{RESET}")
        else:
            print(err(f"  [!]  {label} -- NOT FOUND / INACTIVE"))
            all_ok = False
    print()
    if all_ok:
        print(ok("  ALL OK -- connect phone to Dexter WiFi and open http://192.168.5.1:5001"))
    else:
        print(warn("  Some checks failed -- see above"))
    press_enter()


def reboot_system():
    header("REBOOT")
    print(warn("  System will reboot in 5 seconds..."))
    print(warn("  Press Ctrl+C to cancel\n"))
    try:
        for i in range(5, 0, -1):
            print(f"  Rebooting in {i}...", end="\r")
            time.sleep(1)
        run("sudo reboot", capture=False)
    except KeyboardInterrupt:
        print(warn("\n  Reboot cancelled"))
        press_enter()


# -- Clear Database menu ------------------------------------------------------
def clear_database_menu():
    header("CLEAR ALL DATABASE")
    print(warn("  This will permanently delete ALL rows from:"))
    print(warn("    /home/pi/Test3/payloads.db  (queued MQTT payloads)"))
    print(warn("    /home/pi/Test3/buffer.db    (event buffer)"))
    print()
    print(warn("  Table structures are preserved. Only row data is removed."))
    print(warn("  VACUUM will run after clearing to reclaim SD card space."))
    print()
    print(err("  WARNING: This cannot be undone. Unsent data will be lost."))
    print()
    confirm = input("  Type YES to confirm, anything else to cancel: ").strip()
    if confirm != "YES":
        print(info("  Cancelled -- no data was deleted."))
        press_enter()
        return
    print()
    print("  Running clear_all_data.py...")
    clear()
    print(bold("=== Clear All Data ===\n"))
    run("sudo python3 /home/pi/Test3/clear_all_data.py", capture=False)
    press_enter()


# -- SD Card Lock -------------------------------------------------------------
def sd_card_lock_menu():
    header("SD CARD LOCK")
    lock_out = run("cat /sys/block/mmcblk0/ro 2>/dev/null").strip()
    if lock_out == "1":
        current = err("LOCKED (read-only)")
        current_val = 1
    elif lock_out == "0":
        current = ok("UNLOCKED (read-write)")
        current_val = 0
    else:
        current = warn(f"Unknown ({lock_out})")
        current_val = -1

    print(f"  SD card status : {current}")
    print()
    print(f"  {bold('1.')} Lock SD card   (read-only  -- protects against corruption)")
    print(f"  {bold('2.')} Unlock SD card (read-write -- required for normal operation)")
    print(f"  {bold('0.')} Back")
    print()
    choice = input("  Choice: ").strip()

    if choice == "0":
        return
    elif choice == "1":
        if current_val == 1:
            print(warn("  SD card is already locked."))
            press_enter()
            return
        print(warn("  Stopping all Docker containers before locking..."))
        run(f"cd /home/pi/Test3 && docker compose down")
        time.sleep(2)
        out = run("sudo bash -c 'echo 1 > /sys/block/mmcblk0/ro'")
        if out: print(out)
        result = run("cat /sys/block/mmcblk0/ro").strip()
        if result == "1":
            print(ok("  SD card locked (read-only). Reboot to remount filesystems."))
            print(warn("  Note: Start services after unlocking and rebooting."))
        else:
            print(err(f"  Lock failed -- current state: {result}"))
        press_enter()
    elif choice == "2":
        if current_val == 0:
            print(warn("  SD card is already unlocked."))
            press_enter()
            return
        out = run("sudo bash -c 'echo 0 > /sys/block/mmcblk0/ro'")
        if out: print(out)
        result = run("cat /sys/block/mmcblk0/ro").strip()
        if result == "0":
            print(ok("  SD card unlocked (read-write)."))
            print(info("  Reboot recommended to remount filesystems in read-write mode."))
        else:
            print(err(f"  Unlock failed -- current state: {result}"))
        press_enter()
    else:
        print(err("  Invalid choice"))
        time.sleep(1)


# -- RPi Hardening ------------------------------------------------------------
def harden_rpi_menu():
    header("HARDEN RPi SYSTEM")
    print(warn("  This will apply the following security settings:"))
    print()
    print(f"  {'Setting':<40} Action")
    print(f"  {'-'*40} {'-'*30}")
    print(f"  {'Boot target':<40} CLI only (no desktop)")
    print(f"  {'Console autologin':<40} Disabled")
    print(f"  {'SSH':<40} Disabled")
    print(f"  {'VNC':<40} Disabled")
    print()
    print(warn("  Dexter webserver is still accessible via WiFi hotspot."))
    print()
    confirm = input("  Type YES to apply, anything else to cancel: ").strip()
    if confirm != "YES":
        print(info("  Cancelled -- no changes made."))
        press_enter()
        return
    print()
    steps = [
        ("Boot to CLI",              "sudo raspi-config nonint do_boot_behaviour B1"),
        ("Disable console autologin","sudo raspi-config nonint do_boot_behaviour B1"),
        ("Disable SSH",              "sudo raspi-config nonint do_ssh 1"),
        ("Disable VNC",              "sudo raspi-config nonint do_vnc 1"),
    ]
    all_ok = True
    for label, cmd in steps:
        out = run(cmd)
        if "error" in out.lower() or "failed" in out.lower():
            print(err(f"  [!] {label}"))
            if out: print(f"      {DIM}{out}{RESET}")
            all_ok = False
        else:
            print(ok(f"  [OK] {label}"))
    print()
    if all_ok:
        print(ok("  All hardening steps applied successfully."))
        print(info("  Reboot for changes to take full effect."))
    else:
        print(warn("  Some steps failed -- check output above."))
    press_enter()


# -- Load Certificate ---------------------------------------------------------
def load_certificate_menu():
    header("LOAD CERTIFICATE")
    SCRIPT = "/home/pi/Test3/loadCertificate.py"
    CERT   = "/home/pi/Test3/ca.crt"
    print(f"  Script : {DIM}{SCRIPT}{RESET}")
    print(f"  Cert   : {DIM}{CERT}{RESET}")
    print()
    missing = []
    if not os.path.exists(SCRIPT): missing.append(SCRIPT)
    if not os.path.exists(CERT):   missing.append(CERT)
    if missing:
        for f in missing:
            print(err(f"  [!] Not found: {f}"))
        print()
        print(warn("  Copy loadCertificate.py and ca.crt to /home/pi/Test3/ before running."))
        press_enter()
        return
    print(warn("  This will send ca.crt to the IP Communicator module via serial port."))
    print(warn("  Ensure no other process is using /dev/ttyS0 (stop dexter-serial-comm first)."))
    print()
    stop_first = input("  Stop dexter-serial-comm first? [Y/n]: ").strip().lower()
    if stop_first != "n":
        run("docker stop dexter-serial-comm")
        print(info("  dexter-serial-comm stopped."))
        print()
    print("  Running loadCertificate.py...\n")
    clear()
    print(bold("=== Load Certificate ===\n"))
    try:
        subprocess.run(["sudo", "python3", SCRIPT], cwd="/home/pi/Test3")
    except KeyboardInterrupt:
        print(warn("\n  Interrupted."))
    print()
    restart = input("  Restart dexter-serial-comm now? [Y/n]: ").strip().lower()
    if restart != "n":
        run("docker start dexter-serial-comm")
        time.sleep(2)
        s = get_docker_status("dexter-serial-comm")
        print(ok(f"  dexter-serial-comm {s}") if s == "running" else err(f"  [!] {s}"))
    press_enter()


# -- Serial Number ------------------------------------------------------------
SECURELINK_DB = "/home/pi/Test3/securelink.db"

def serial_number_menu():
    import sqlite3 as _sql

    def _get():
        try:
            conn = _sql.connect(SECURELINK_DB)
            row = conn.execute("SELECT panel_number, batch_number FROM device_info LIMIT 1").fetchone()
            conn.close()
            return row
        except Exception as e:
            return None

    def _set(panel, batch):
        conn = _sql.connect(SECURELINK_DB)
        conn.execute("""CREATE TABLE IF NOT EXISTS device_info (
                            id INTEGER PRIMARY KEY,
                            panel_number TEXT,
                            batch_number TEXT)""")
        count = conn.execute("SELECT COUNT(*) FROM device_info").fetchone()[0]
        if count == 0:
            conn.execute("INSERT INTO device_info (panel_number, batch_number) VALUES (?, ?)", (panel, batch))
        else:
            conn.execute("UPDATE device_info SET panel_number=?, batch_number=? WHERE id=(SELECT id FROM device_info LIMIT 1)", (panel, batch))
        conn.commit()
        conn.close()

    header("DEVICE SERIAL NUMBER")
    row = _get()
    if row:
        panel_cur, batch_cur = row
        print(f"  Current panel_number : {bold(panel_cur)}")
        print(f"  Current batch_number : {bold(batch_cur)}")
    else:
        print(warn("  No serial number set yet."))
        panel_cur, batch_cur = "", ""
    print()

    panel = input(f"  Enter panel_number (4-digit, e.g. 0001) [{panel_cur}]: ").strip()
    if not panel:
        panel = panel_cur
    batch = input(f"  Enter batch_number (e.g. B001)          [{batch_cur}]: ").strip()
    if not batch:
        batch = batch_cur

    if not panel and not batch:
        print(warn("  No values entered — nothing changed."))
        press_enter()
        return

    panel = panel.zfill(4) if panel.isdigit() else panel
    _set(panel, batch)

    import sys as _sys, datetime as _dt, platform as _pl
    year = _dt.datetime.now().year
    model_year = f"SecureLink{str(year)[-2:]}"
    try:
        with open('/proc/device-tree/model') as f:
            m = f.read()
        rpi = 'R4' if 'Raspberry Pi 4' in m else ('R5' if 'Raspberry Pi 5' in m else ('R3' if 'Raspberry Pi 3' in m else 'R?'))
    except Exception:
        rpi = 'R?'
    pyv = f"P{_sys.version_info.major}"
    serial = f"{model_year}{rpi}{pyv}{panel}{batch}"

    print()
    print(ok(f"  Saved. Generated serial: {bold(serial)}"))

    # Send serial number to ThingsBoard once now that panel/batch are set.
    try:
        import importlib, importlib.util as _ilu
        _spec = _ilu.spec_from_file_location(
            "generate_serial_no_GitHub",
            os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "generate_serial_no_GitHub.py")
        )
        _gsg = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(_gsg)
        print(info("  Sending serial number to ThingsBoard..."))
        _sent = _gsg.run_once()
        if _sent:
            print(ok("  Serial number sent to ThingsBoard successfully."))
        else:
            print(warn("  Failed to send serial number to ThingsBoard — check MQTT credentials."))
    except Exception as _e:
        print(warn(f"  Could not send serial to ThingsBoard: {_e}"))

    press_enter()


# -- Main menu ----------------------------------------------------------------
def main_menu():
    while True:
        header("MAIN MENU")

        core_statuses  = [get_docker_status(name) for name, _ in DOCKER_CONTAINERS[:CORE_COUNT]]
        intg_statuses  = [get_docker_status(name) for name, _ in DOCKER_CONTAINERS[CORE_COUNT:]]
        core_running   = core_statuses.count("running")
        core_crashed   = core_statuses.count("crashed") + core_statuses.count("restarting")
        intg_running   = intg_statuses.count("running")
        intg_disabled  = intg_statuses.count("disabled")
        intg_crashed   = intg_statuses.count("crashed")
        c_clr = RED if core_crashed else (GREEN if core_running else YELLOW)
        core_parts = [f"{clr(str(core_running), c_clr)} running"]
        if core_crashed:
            core_parts.append(f"{clr(str(core_crashed), RED)} crashed")
        print(f"  Core   : {'  '.join(core_parts)}  {DIM}({CORE_COUNT} total){RESET}")
        i_clr = RED if intg_crashed else (GREEN if intg_running else CYAN)
        intg_parts = [f"{clr(str(intg_running), i_clr)} running",
                      f"{clr(str(intg_disabled), CYAN)} disabled"]
        if intg_crashed:
            intg_parts.append(f"{clr(str(intg_crashed), RED)} crashed")
        print(f"  Integr : {'  '.join(intg_parts)}  {DIM}({len(DOCKER_CONTAINERS)-CORE_COUNT} total){RESET}")
        print()

        print(f"  {bold('1.')}  Show all container status")
        print(f"  {bold('2.')}  Start ALL containers")
        print(f"  {bold('3.')}  Stop ALL containers")
        print(f"  {bold('4.')}  Restart ALL containers")
        print(f"  {bold('5.')}  Individual container control")
        print(f"  {bold('6.')}  View logs")
        print(f"  {bold('7.')}  WiFi hotspot check")
        print(f"  {bold('8.')}  Boot diagnosis")
        print(f"  {bold('9.')}  Reboot system")
        print(f"  {bold('10.')} Clear all database (payloads.db + buffer.db)")
        print(f"  {bold('11.')} SD card lock / unlock")
        print(f"  {bold('12.')} Harden RPi system  (CLI boot, disable SSH & VNC)")
        print(f"  {bold('13.')} Load certificate to IP Communicator module")
        print(f"  {bold('14.')} Set device serial number (securelink.db)")
        print(f"  {bold('0.')}  Exit without reboot")
        print()

        choice = input("  Enter choice (0-14): ").strip()

        if   choice == "1":  show_all_status()
        elif choice == "2":  start_all()
        elif choice == "3":  stop_all()
        elif choice == "4":  restart_all()
        elif choice == "5":  individual_service_menu()
        elif choice == "6":  view_logs_menu()
        elif choice == "7":  wifi_check()
        elif choice == "8":  boot_diagnosis()
        elif choice == "9":  reboot_system(); break
        elif choice == "10": clear_database_menu()
        elif choice == "11": sd_card_lock_menu()
        elif choice == "12": harden_rpi_menu()
        elif choice == "13": load_certificate_menu()
        elif choice == "14": serial_number_menu()
        elif choice == "0":
            print(info("\n  Exiting. Services continue running.\n"))
            break
        else:
            print(err("  Invalid choice -- enter 0 to 14"))
            time.sleep(1)


if __name__ == "__main__":
    if os.geteuid() != 0:
        print(warn("\n  Run as root for full control: sudo python3 autorun4.py\n"))
        print(warn("  Some options (start/stop/restart) will fail without sudo.\n"))
        time.sleep(2)
    main_menu()