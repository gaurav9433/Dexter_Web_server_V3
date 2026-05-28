"""
Lan_setting.py
Dexter HMS — Network configuration orchestrator

Responsibilities:
  - Orchestrates static IP configuration and DHCP reset operations
  - Calls Configure_Network_7 and reset_to_dhcp via direct import (SEC-05)
    replacing previous subprocess sudo pattern
  - Triggers device provisioning and Tailscale setup after network changes

Key functions:
  - configureStaticNetwork() — apply static IP via Configure_Network_7.main()
  - resetDHCP()              — restore DHCP via reset_to_dhcp.reset_dhcp()

Dependencies:
  - Configure_Network_7, reset_to_dhcp — direct imports (not subprocess)
Author: Seple Novaedge Pvt. Ltd.
"""

import subprocess
import time
import json
import sqlite3
import os
import uuid
import logging
from webdone import send_webdone
from tailscale_setup import setup_tailscale_and_save_info
from DeviceProvisioning_Module import form_basic
from cavlidata import send_cavlidata_status
from stopser import stop_autorun

# FIX: Import directly instead of calling via subprocess
import Configure_Network_7
import reset_to_dhcp          # for DHCP reset

log = logging.getLogger(__name__)

# Portainer Server — set in .env as PORTAINER_SERVER and PORTAINER_API_TOKEN
_PORTAINER_SERVER  = os.environ.get("PORTAINER_SERVER", "https://3.111.214.115:9443")
_PORTAINER_TOKEN   = os.environ.get("PORTAINER_API_TOKEN", "")
_ENV_FILE          = "/home/pi/Test3/.env"
_COMPOSE_FILE      = "/home/pi/Test3/docker-compose.yml"

def configureStaticNetwork():
    """
    FIXED: Previously called Configure_Network_7.py as an external subprocess.
    Now imports and calls main() directly — no subprocess overhead,
    no blind trust in a file on disk running as sudo.
    All IP values are read from network_settings.db inside Configure_Network_7.main().
    """
    try:
        Configure_Network_7.main()
        log.info("Static IP configuration successful.")
    except Exception as e:
        log.error("Static IP configuration failed:", str(e))


def resetDHCP():
    """
    FIXED: Previously called reset_to_dhcp.py as an external subprocess.
    Now calls switch_to_dhcp() and restart_dhcpcd() directly from Configure_Network_7,
    which is the same logic reset_to_dhcp.py would use.
    """
    try:
        reset_to_dhcp.reset_dhcp()
        log.info("DHCP reset successful.")
    except Exception as e:
        log.error("DHCP reset failed:", str(e))



#-------------------------------------------
# ======== Mask ip   ========



def mask_all_ips_json(
    db_path="/home/pi/Test3/device_config.db",
    table_name="device_parameters",
    column_name="camera_ip"
):
    conn = None
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        cursor.execute(f"SELECT rowid, {column_name} FROM {table_name}")
        rows = cursor.fetchall()

        updated_count = 0

        for rowid, json_data in rows:
            try:
                # Skip real SQL NULLs
                if json_data is None:
                    log.info("[Skip] row %s: value is NULL", rowid)
                    continue

                # If plain string that looks like an IP
                if isinstance(json_data, str) and json_data.strip().count(".") == 3:
                    cursor.execute(
                        f"UPDATE {table_name} SET {column_name} = ? WHERE rowid = ?",
                        (None, rowid)   # set real NULL
                    )
                    updated_count += 1
                    log.info("[Mask] row %s: plain IP string masked → NULL", rowid)
                    continue

                # Otherwise, try parsing as JSON
                if not isinstance(json_data, (str, bytes, bytearray)):
                    #log.error("[Skip] row %s: invalid type -> %s, value=%s", rowid, type(json_data).__name__, json_data!r)
                    log.error("[Skip] row %s: invalid type -> %s, value=%r", rowid, type(json_data).__name__, json_data)
                    continue

                data = json.loads(json_data)

                # Replace IPs in list
                if isinstance(data, list):
                    for obj in data:
                        if isinstance(obj, dict) and "ip_address" in obj:
                            obj["ip_address"] = None

                # Replace IP in dict
                elif isinstance(data, dict):
                    if "ip_address" in data:
                        data["ip_address"] = None

                new_json = json.dumps(data)

                cursor.execute(
                    f"UPDATE {table_name} SET {column_name} = ? WHERE rowid = ?",
                    (new_json, rowid)
                )
                updated_count += 1

            except json.JSONDecodeError:
                #log.debug("[Skip] row %s: not valid JSON -> %s", rowid, json_data!r)
                log.debug("[Skip] row %s: not valid JSON -> %s", rowid, json_data)
                continue

        conn.commit()
        log.info("Masked IPs in %s rows of %s", updated_count, table_name)

    except sqlite3.Error as e:
        log.error("Error:", e)

    finally:
        if conn:
            conn.close()







# ======== clear all  ========


def clear_all_data(db_path):
    total_deleted = 0
    conn = None
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

    
        

        # Get all non-system tables
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';")
        tables = [row[0] for row in cursor.fetchall()]

        pass_count = 0
        while True:
            pass_count += 1
            deleted_this_round = 0

            for table in tables:
                cursor.execute(f"SELECT COUNT(*) FROM {table}")
                count_before = cursor.fetchone()[0]

                if count_before > 0:
                    cursor.execute(f"DELETE FROM {table}")
                    deleted_this_round += count_before
                    log.info("[Pass %s] Cleared %s rows from: %s", pass_count, count_before, table)

            conn.commit()
            total_deleted += deleted_this_round

            # Stop if nothing deleted this pass
            if deleted_this_round == 0:
                break

        log.info(" %s: Total %s rows cleared.", db_path, total_deleted)

    except sqlite3.Error as e:
        log.error("Error clearing %s: %s", db_path, e)

    finally:
        if conn:
            conn.close()

    return total_deleted



def clear_both_databases():
    db_paths = [
        '/home/pi/Test3/payloads.db',
        '/home/pi/Test3/buffer.db'
    ]

    max_passes = 10  # safety limit
    for pass_num in range(1, max_passes + 1):
        log.info("\n=== Cleanup Pass %s ===", pass_num)
        all_empty = True

        for db_path in db_paths:
            rows_cleared = clear_all_data(db_path)
            if rows_cleared > 0:
                all_empty = False

        if all_empty:
            log.info("\n All databases are empty. Stopping early.")
            break

        time.sleep(2)

    else:
        log.info("\n Max passes reached. Some data may still remain.")




# ======== Portainer auto-registration ========

def _get_device_name_from_db() -> str:
    """Read device_name set by form_basic() during provisioning."""
    try:
        conn = sqlite3.connect("/home/pi/Test3/modem_config.db")
        row = conn.execute(
            "SELECT device_name FROM modem_parameters WHERE id = 1"
        ).fetchone()
        conn.close()
        return (row[0] or "").strip() if row else ""
    except Exception as e:
        log.error("_get_device_name_from_db failed — %s", e)
        return ""


def _update_env_file(edge_id: str, edge_key: str, device_name: str) -> None:
    """Write DEVICE_NAME, PORTAINER_EDGE_ID, and PORTAINER_EDGE_KEY into .env."""
    lines = []
    if os.path.exists(_ENV_FILE):
        with open(_ENV_FILE, "r") as f:
            lines = f.readlines()

    keys_written = {"DEVICE_NAME": False, "PORTAINER_EDGE_ID": False, "PORTAINER_EDGE_KEY": False}
    new_lines = []
    for line in lines:
        if line.startswith("DEVICE_NAME="):
            new_lines.append(f"DEVICE_NAME={device_name}\n")
            keys_written["DEVICE_NAME"] = True
        elif line.startswith("PORTAINER_EDGE_ID="):
            new_lines.append(f"PORTAINER_EDGE_ID={edge_id}\n")
            keys_written["PORTAINER_EDGE_ID"] = True
        elif line.startswith("PORTAINER_EDGE_KEY="):
            new_lines.append(f"PORTAINER_EDGE_KEY={edge_key}\n")
            keys_written["PORTAINER_EDGE_KEY"] = True
        else:
            new_lines.append(line)

    if not keys_written["DEVICE_NAME"]:
        new_lines.append(f"DEVICE_NAME={device_name}\n")
    if not keys_written["PORTAINER_EDGE_ID"]:
        new_lines.append(f"PORTAINER_EDGE_ID={edge_id}\n")
    if not keys_written["PORTAINER_EDGE_KEY"]:
        new_lines.append(f"PORTAINER_EDGE_KEY={edge_key}\n")

    with open(_ENV_FILE, "w") as f:
        f.writelines(new_lines)
    log.info("portainer_register: .env updated — DEVICE_NAME=%s EDGE_ID=%s", device_name, edge_id)


def portainer_register() -> bool:
    """
    Called at the end of device_provisioning() after form_basic() has set
    the unique device_name in modem_config.db.

    1. Reads device_name from modem_config.db
    2. Deletes any existing Portainer environment with this name (409 guard)
    3. Calls Portainer API to create a new Edge environment with that name
    4. Writes DEVICE_NAME + PORTAINER_EDGE_ID + PORTAINER_EDGE_KEY to .env
    5. Restarts portainer-agent so it picks up the new credentials
    6. Recreates dexter-prometheus so it picks up the new DEVICE_NAME
    """
    if not _PORTAINER_TOKEN:
        log.warning("portainer_register: PORTAINER_API_TOKEN not set in .env — skipping")
        return False

    device_name = _get_device_name_from_db()
    if not device_name:
        log.error("portainer_register: device_name empty — provisioning may not be complete")
        return False

    try:
        import urllib.request
        import urllib.parse
        import ssl

        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        # Delete any existing environment with this device name before creating.
        # Portainer returns HTTP 409 Conflict if a same-named environment exists,
        # which prevents _update_env_file() from being called and leaves stale
        # credentials in .env — breaking the agent on re-provisioning.
        try:
            list_req = urllib.request.Request(
                f"{_PORTAINER_SERVER}/api/endpoints?limit=100",
                headers={"X-API-Key": _PORTAINER_TOKEN},
                method="GET",
            )
            with urllib.request.urlopen(list_req, context=ctx, timeout=30) as resp:
                endpoints = json.loads(resp.read())
            for ep in (endpoints if isinstance(endpoints, list) else []):
                if ep.get("Name") == device_name:
                    del_req = urllib.request.Request(
                        f"{_PORTAINER_SERVER}/api/endpoints/{ep['Id']}",
                        headers={"X-API-Key": _PORTAINER_TOKEN},
                        method="DELETE",
                    )
                    with urllib.request.urlopen(del_req, context=ctx, timeout=30) as _:
                        pass
                    log.info("portainer_register: deleted existing environment '%s' (id=%s)", device_name, ep['Id'])
        except Exception as _del_err:
            log.warning("portainer_register: pre-delete check failed (continuing) — %s", _del_err)

        # Portainer API: create Edge Agent endpoint (EndpointCreationType=4).
        # URL must be the Portainer server address — Portainer encodes it into
        # the EdgeKey so the agent knows where to dial. Using the Pi's address
        # here causes the agent to poll itself (unsupported protocol scheme error).
        form_data = urllib.parse.urlencode({
            "Name":                  device_name,
            "EndpointCreationType":  "4",
            "URL":                   _PORTAINER_SERVER,
        }).encode()

        req = urllib.request.Request(
            f"{_PORTAINER_SERVER}/api/endpoints",
            data=form_data,
            headers={
                "X-API-Key":     _PORTAINER_TOKEN,
                "Content-Type":  "application/x-www-form-urlencoded",
            },
            method="POST",
        )

        with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
            body = json.loads(resp.read())

        edge_key = body.get("EdgeKey", "")
        # Use the EdgeID assigned by Portainer — NOT a locally-generated UUID.
        # A mismatched EDGE_ID causes "invalid Edge identifier" errors because
        # the agent sends this ID on every poll and Portainer rejects it.
        edge_id  = body.get("EdgeID", "")
        endpoint_id = body.get("Id", "")
        if not edge_key or not edge_id:
            log.error("portainer_register: missing EdgeKey/EdgeID in response — %s", body)
            return False

        # Auto-trust the new environment so the agent can connect immediately.
        # Without this the agent gets "device has not been trusted yet" on every poll.
        trust_req = urllib.request.Request(
            f"{_PORTAINER_SERVER}/api/endpoints/{endpoint_id}",
            data=json.dumps({"UserTrusted": True}).encode(),
            headers={
                "X-API-Key":    _PORTAINER_TOKEN,
                "Content-Type": "application/json",
            },
            method="PUT",
        )
        with urllib.request.urlopen(trust_req, context=ctx, timeout=30) as _:
            pass
        log.info("portainer_register: environment %s trusted", endpoint_id)

        _update_env_file(edge_id, edge_key, device_name)

        # nsenter required: 'docker' binary is not installed inside the container.
        # Running via nsenter executes docker from the host's mount namespace.
        _nsenter = ["nsenter", "-t", "1", "-m", "-u", "-i", "-n", "-p", "--"]
        subprocess.call(
            _nsenter + ["docker", "compose", "-f", _COMPOSE_FILE, "up", "-d", "--no-deps", "portainer-agent"],
            cwd="/home/pi/Test3"
        )
        subprocess.call(
            _nsenter + ["docker", "compose", "-f", _COMPOSE_FILE, "--env-file", _ENV_FILE,
                        "up", "-d", "--no-deps", "dexter-prometheus"],
            cwd="/home/pi/Test3"
        )
        # Restart dexter-mqtt so it reloads ACCESS_TOKEN + THINGSBOARD_HOST from
        # modem_config.db — these are read at module import and won't refresh otherwise
        subprocess.call(
            ["docker", "compose", "-f", _COMPOSE_FILE, "up", "-d", "--no-deps", "dexter-mqtt"],
            cwd="/home/pi/Test3"
        )
        log.info("portainer_register: '%s' registered, agent, prometheus and mqtt restarted", device_name)
        return True

    except Exception as e:
        log.error("portainer_register failed — %s", e)
        return False


def _get_network_type() -> str:
    """Return network_type from modem_config.db ('gsm' or 'ethernet')."""
    try:
        conn = sqlite3.connect("/home/pi/Test3/modem_config.db")
        row = conn.execute(
            "SELECT network_type FROM modem_parameters WHERE id = 1"
        ).fetchone()
        conn.close()
        return (row[0] or "").strip().lower() if row else ""
    except Exception as e:
        log.warning("_get_network_type failed — %s", e)
        return ""


_ECR    = "901178127457.dkr.ecr.ap-south-1.amazonaws.com"
_REGION = "ap-south-1"
_NSENTER = ["nsenter", "-t", "1", "-m", "-u", "-i", "-n", "-p", "--"]


def _ecr_login() -> None:
    """Refresh ECR auth token on the host so the OTA cron can pull images."""
    try:
        subprocess.call(
            _NSENTER + ["bash", "-c",
                f"aws ecr get-login-password --region {_REGION} "
                f"| docker login --username AWS --password-stdin {_ECR}"],
            timeout=30
        )
        log.info("_ecr_login: ECR token refreshed")
    except Exception as e:
        log.warning("_ecr_login: failed — %s", e)


def _trigger_stack_restart() -> None:
    """Restart the full stack in background so containers pick up new .env values.

    15-second delay lets provisioning return and the LCD show success before
    dexter-core is restarted.
    """
    try:
        subprocess.Popen(
            _NSENTER + ["bash", "-c",
                "sleep 15 && cd /home/pi/Test3 "
                "&& docker compose up -d --remove-orphans "
                ">> /var/log/dexter/post_provision.log 2>&1"],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True
        )
        log.info("_trigger_stack_restart: stack restart scheduled in 15 s")
    except Exception as e:
        log.warning("_trigger_stack_restart: could not schedule — %s", e)


# ======== device provisionning with clear all,cavlidatause_on and mask ip ========

def device_provisioning():
    max_retries = 3
    attempt = 0

    while attempt < max_retries:
        try:
            # Ethernet-only Pis must skip pon/poff — peer config (c16qs) won't exist.
            use_modem = _get_network_type() == "gsm"

            # Step 1
            stop_autorun()
            time.sleep(5)

            # Step 2 - dial modem (GSM only)
            # nsenter required: pppd must run in the host network namespace so
            # ppp0 is created on the host, not trapped in the container.
            if use_modem:
                if subprocess.call(["nsenter", "-t", "1", "-m", "-u", "-i", "-n", "-p", "--", "pon", "c16qs"]) != 0:
                    raise RuntimeError("pon c16qs failed")
                time.sleep(20)

            # Step 3
            form_basic()
            time.sleep(5)

            # Step 4
            setup_tailscale_and_save_info()
            time.sleep(5)

            # Step 5
            send_webdone()
            time.sleep(2)

            # Step 6
            send_cavlidata_status()
            time.sleep(2)

            # Step 7 — Portainer registration while internet is still up (before poff)
            portainer_register()
            time.sleep(2)

            # Step 7.5 — Refresh ECR token while internet is still up (before poff).
            # Stores token in ~/.docker/config.json for the OTA cron to use.
            _ecr_login()
            time.sleep(1)

            # Step 8 - hang up modem (GSM only)
            if use_modem:
                if subprocess.call(["nsenter", "-t", "1", "-m", "-u", "-i", "-n", "-p", "--", "poff", "c16qs"]) != 0:
                    raise RuntimeError("poff c16qs failed")
                time.sleep(1)

            # Step 9
            clear_both_databases()
            time.sleep(1)

            # Step 10
            mask_all_ips_json()
            time.sleep(1)

            # Signal next send_dexter_config to mask credentials (provisioning just done)
            try:
                with open("/home/pi/Test3/.provisioning_done", "w") as _f:
                    _f.write("1")
            except OSError as _e:
                log.warning("device_provisioning: could not write provisioning flag — %s", _e)

            # Step 10.5 — Restart the full stack in background so all containers
            # pick up the new .env (DEVICE_NAME, PORTAINER keys). Runs after 15 s
            # so the LCD shows success before dexter-core is restarted.
            _trigger_stack_restart()

            return "success"  # all steps passed

        except Exception as e:
            attempt += 1
            log.error("Provisioning failed (attempt %s/%s). Error: %s", attempt, max_retries, e)
            time.sleep(10)

    log.error("Provisioning failed after %s attempts.", max_retries)
    return "failed"
