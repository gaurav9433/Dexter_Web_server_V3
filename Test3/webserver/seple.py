import os
import sys
import socket
import logging
import os.path
import json
import sqlite3 
import time
import threading
from sqlite3 import Error
from datetime import datetime, timedelta
from typing import Optional
from flask import (
    Flask,
    flash,
    render_template,
    request,
    jsonify,
    session,
    url_for,   
    redirect
)

import psutil
import tarfile
import tempfile
import shutil
import subprocess as _sp

logging.basicConfig(level=logging.INFO)

sys.path.append('/home/pi/Test3')
from Lan_setting import resetDHCP, device_provisioning

# RTC DS1307 — initialized once at module load
# Must import from /home/pi/Test3 not webserver folder
# (webserver folder has a stub SDL_DS1307.py with no methods)
try:
    import importlib.util as _ilu
    _spec = _ilu.spec_from_file_location(
        "SDL_DS1307", "/home/pi/Test3/SDL_DS1307.py"
    )
    _sdl_ds1307 = _ilu.module_from_spec(_spec)
    _spec.loader.exec_module(_sdl_ds1307)
    sdlds1370 = _sdl_ds1307.SDL_DS1307(1, 0x68)
    sdlds1370.write_now()
except Exception as _rtc_e:
    import logging as _log
    _log.getLogger('seple').warning(
        "RTC DS1307 init failed — date_time route will return error: %s", _rtc_e
    )
    sdlds1370 = None

# Initialize Flask app
app = Flask(__name__)
app.secret_key = "SEPLe"  # set secret key for session
password_file = "/home/pi/Test3/AdminPass.txt"  # Full path to password file
db_file = "sepleDB.db"

hostname = socket.gethostname()


def create_connection(db_file):
    conn = None
    try:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        db_path = os.path.join(base_dir, db_file)
        conn = sqlite3.connect(db_path)
        return conn
    except:
        return None


@app.after_request
def add_header(response):
    response.headers["Cache-Control"] = (
        "no-store, no-cache, must-revalidate, post-check=0, pre-check=0"
    )
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(minutes=30)


def get_uptime():
    return time.time() - psutil.boot_time()


def check_user_access(required_permissions=None):
    """Check if user has required permissions for specific pages"""
    if "username" not in session:
        return False
    
    user_type = session.get("user_type", "user")
    
    # Site engineers have access to everything
    if user_type == "site_engineer":
        return True
    
    # Regular users have restricted access
    if user_type == "user":
        # Define restricted pages that users cannot access
        restricted_pages = [
            "provision",      # Device Provisioning
            "lan",            # LAN setup  
            "device_credential"  # Device credentials
        ]
        
        if required_permissions in restricted_pages:
            return False
        return True
    
    return False


@app.route("/home")
def home():
    if "username" in session:
        db = create_connection("sepleDB.db")
        cursor = db.cursor()
        cursor.execute("SELECT username FROM users ")
        user_data = cursor.fetchone()
        cursor.close()
        db.close()

        db2 = create_connection("/home/pi/Test3/dexterpanel2.db")
        db3 = create_connection("/home/pi/Test3/securelink.db")
        cursor3 = db3.cursor()
        cursor3.execute("Select batch_number from device_info")
        deviceinfo = cursor3.fetchone()
        cursor2 = db2.cursor()
        cursor2.execute("SELECT * FROM systemLogs")
        logss_data = cursor2.fetchall()
        cursor2.close()
        db2.close()

        # FIX-BUG05: use full path to Test3/modem_config.db
        token_data = []
        try:
            db3 = create_connection("/home/pi/Test3/modem_config.db")
            if db3:
                cursor3 = db3.cursor()
                cursor3.execute("SELECT * FROM modem_parameters")
                token_data = cursor3.fetchall()
                cursor3.close()
                db3.close()
        except Exception:
            pass
        return render_template(
            "landing.html", logg=logss_data, user=user_data, tokenData=token_data,deviceinfo = deviceinfo
        )
    return redirect(url_for("login"))


def get_cpu_freq():
    freq = psutil.cpu_freq()
    return freq.current


def get_ip_address():
    # interfaces = psutil.net_if_addrs()
    # for name, addrs in interfaces.items():
    # for addr in addrs:
    # print(addr)
    # if addr.family.name == 'AF_INET' and not addr.address.startswith('127.'):
    # return addr.address
    return "Not connected"


@app.route("/stats")
def stats():
    data = {
        "cpu": psutil.cpu_percent(interval=1),
        "memory_used": (psutil.virtual_memory().used / psutil.virtual_memory().total)
        * 100,
        #'memory_used': psutil.virtual_memory().used / (1024 * 1024),  # in MB
        "disk_used": (psutil.disk_usage("/").used / psutil.disk_usage("/").total) * 100,
        # 'disk_used': psutil.disk_usage('/').used / (1024 * 1024 * 1024),  # in GB
        "bytes_sent": psutil.net_io_counters().bytes_sent / (1024 * 1024),  # in MB
        "bytes_recv": psutil.net_io_counters().bytes_recv / (1024 * 1024),  # in MB
        "uptime": int(get_uptime()),  # in seconds
        "cpu_temp": (
            psutil.sensors_temperatures()
            .get(
                "cpu-thermal", psutil.sensors_temperatures().get("cpu_thermal", [None])
            )[0]
            .current
            if psutil.sensors_temperatures().get(
                "cpu-thermal", psutil.sensors_temperatures().get("cpu_thermal")
            )
            else None
        ),
        "freq": get_cpu_freq(),
        "network_interfaces": get_ip_address(),
    }
    print(jsonify(data))
    return jsonify(data)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/financial")
def financial():
    return render_template("financial.html")


@app.route("/delete", methods=["GET", "POST"])
def clear_logs():
    if "username" not in session:
        return redirect(url_for("login"))
   
    if request.method == "POST":
        
        username = session.get("username")
        
        # Verify password
        db = create_connection(db_file)
        
        if db:
            cursor = db.cursor()
            cursor.execute("SELECT password FROM users WHERE username=?", (username,))
            user_data = cursor.fetchone()
            cursor.close()
            db.close()
            print(request)
            if user_data :
                # Password verified - proceed with delete
                connection = sqlite3.connect("/home/pi/Test3/dexterpanel2.db")
                
                cursor = connection.cursor()
                cursor.execute("DELETE FROM systemLogs")
                connection.commit()
                connection.close()
                return redirect(url_for("logs"))
            else:
                return render_template("logs.html", delete_error="Invalid password")
    
    # GET request - show password prompt
    return render_template("logs.html", delete_prompt=True)

    # Initialize default users in database if they don't exist #

def initialize_users():
    """Initialize default users in database if they don't exist"""
    db = create_connection(db_file)
    if db is None:
        return False
    
    cursor = None
    try:
        cursor = db.cursor()

        # Create users table if it doesn't exist
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                user_type TEXT NOT NULL
            )
        """)
        
        # Check if default users exist, if not create them
        cursor.execute("SELECT COUNT(*) FROM users")
        user_count = cursor.fetchone()[0]
        
        if user_count == 0:
            # Insert default users
            default_users = [
                ("ADMIN", "123321", "site_engineer"),
                ("USER", "321321", "user")
            ]
            
            cursor.executemany(
                "INSERT INTO users (username, password, user_type) VALUES (?, ?, ?)",
                default_users
            )
            db.commit()
            print("Default users created successfully")
        
        cursor.close()
        db.close()
        return True
        
    except Exception as e:
        print(f"Error initializing users: {e}")
        if cursor:
            cursor.close()
        if db:
            db.close()
        return False


@app.route("/login", methods=["GET", "POST"])
def login():
    master_password = "SEPLe@1984"
    if request.method == "POST":
        username = request.form["username"]
        passwordvar = request.form["password"]
        
        user_type = request.form.get("user_type", "user")  # Default to user
        
        db = create_connection(db_file)
        if db is None:
            return "Failed to connect to database"
        
        cursor = db.cursor()
        try:
            # Check if it's a site engineer trying to use master password
            if user_type == "site_engineer" and passwordvar == master_password:
                print("ok")
                cursor.execute(
                    "SELECT * FROM users WHERE username=? AND user_type=?",
                    (username, user_type),
                )
                user_data = cursor.fetchone()
                if user_data:
                    
                    session["username"] = username
                    session["user_type"] = user_type
                    session["master_login"] = True
                    
                    # Log master password usage
                    try:
                        db2 = create_connection("dexterpanel2.db")
                        if db2:
                            cursor2 = db2.cursor()
                            log_message = f"Master password used for site engineer login: {username}"
                            cursor2.execute(
                                "INSERT INTO systemLogs (date, message) VALUES (datetime('now', 'localtime'), ?)",
                                (log_message,),
                            )
                            db2.commit()
                            cursor2.close()
                            db2.close()
                    except:
                        pass
                    
                    db.close()
                    return redirect(url_for("home"))
                db.close()
                return "Invalid site engineer username."

            # Check if user exists with correct credentials and user type
            cursor.execute(
                "SELECT * FROM users WHERE username=? AND password=? AND user_type=?",
                (username, passwordvar, user_type),
            )
            user_data = cursor.fetchone()
            print(user_data)
            
            if user_data:
                session["username"] = username
                session["user_type"] = user_type
                cursor.close()
                db.close()
                return redirect(url_for("home"))
            else:
                cursor.close()
                db.close()
                return render_template("index.html", alert_userpass=True)
                
        except Exception as e:
            if cursor:
                cursor.close()
            if db:
                db.close()
            return "Database error occurred"

    return render_template("index.html")



@app.route("/resetpassword", methods=["GET", "POST"])
def resetpassword():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        npassword = request.form["newpassword"]
        cpassword = request.form["cpassword"]
        user_type = request.form.get("user_type", "user")  # Get user type from form

        db = create_connection(db_file)
        if db is None:
            return "Failed to connect to database"

        cursor = db.cursor()
        try:
            # Check for master password access for site engineers
            if user_type == "site_engineer" and password == "SEPLe@1984":
                cursor.execute(
                    "SELECT * FROM users WHERE username=? AND user_type=?",
                    (username, user_type),
                )
                existing_user = cursor.fetchone()
                if existing_user:
                    if npassword == cpassword:
                        cursor.execute(
                            "UPDATE users SET password=? WHERE username=? AND user_type=?",
                            (npassword, username, user_type),
                        )
                        db.commit()
                        
                        # Log master password usage for password reset
                        try:
                            db2 = create_connection("dexterpanel2.db")
                            if db2:
                                cursor2 = db2.cursor()
                                log_message = f"Master password used for password reset: {username}"
                                cursor2.execute(
                                    "INSERT INTO systemLogs (date, message) VALUES (datetime('now', 'localtime'), ?)",
                                    (log_message,),
                                )
                                db2.commit()
                                cursor2.close()
                                db2.close()
                        except:
                            pass
                        
                        cursor.close()
                        db.close()
                        return render_template("index.html", reset_password=True)
                    else:
                        cursor.close()
                        db.close()
                        return render_template("reset.html", not_same=True)
                else:
                    cursor.close()
                    db.close()
                    return render_template("reset.html", wrong_password=True)
            
            # Check if user exists with correct username, password and user type
            cursor.execute(
                "SELECT * FROM users WHERE username=? AND password=? AND user_type=?",
                (username, password, user_type),
            )
            existing_user = cursor.fetchone()
            if existing_user:
                if npassword == cpassword:
                    cursor.execute(
                        "UPDATE users SET password=? WHERE username=? AND user_type=?",
                        (npassword, username, user_type),
                    )
                    db.commit()
                    cursor.close()
                    db.close()
                    return render_template("index.html", reset_password=True)
                else:
                    cursor.close()
                    db.close()
                    return render_template("reset.html", not_same=True)
            else:
                cursor.close()
                db.close()
                return render_template("reset.html", wrong_password=True)
        except Error as e:
            if cursor:
                cursor.close()
            if db:
                db.close()
            return "Error executing SQL query"

    return render_template("reset.html")



def restart_server():
    """Re-execute the current script (simulate restart)."""
    python = sys.executable
    os.execl(python, python, *sys.argv)


def session_clear():
    session.pop("username", None)


def _host_run(cmd, **kwargs):
    """Run a command on the HOST OS by entering PID 1's namespaces via nsenter.

    Required because the webserver runs inside a Docker container — direct
    calls to reboot/systemctl/date would only affect the container, not the
    host Raspberry Pi.  The container must have pid:host and privileged:true
    in docker-compose.yml for nsenter to work.
    """
    return _sp.run(
        ["nsenter", "-t", "1", "-m", "-u", "-i", "-n", "-p", "--"] + list(cmd),
        **kwargs
    )


def reboot_rpi():
    import threading
    def _do_reboot():
        _host_run(["/sbin/reboot"])
    threading.Timer(5.0, _do_reboot).start()
    return 0


@app.route("/restart", methods=["GET", "POST"])
def restart():
    if "username" not in session:
        return redirect(url_for("login"))

    if request.method == "POST":
        # Handle both JSON and form data
        if request.is_json:
            data = request.get_json()
            password = data.get("password", "") if data else ""
        else:
            password = request.form.get("password", "")

        username = session.get("username")
        user_type = session.get("user_type", "")
        master_password = "SEPLe@1984"

        # Verify password
        db = create_connection(db_file)
        if db:
            cursor = db.cursor()
            cursor.execute("SELECT password, user_type FROM users WHERE username=?", (username,))
            user_data = cursor.fetchone()
            cursor.close()
            db.close()

            if user_data:
                stored_pwd = user_data[0]
                db_user_type = user_data[1]
                # Allow master password for site engineers (same as login)
                if db_user_type == "site_engineer" and password == master_password:
                    reboot_rpi()
                    session_clear()
                    return jsonify({"status": "success", "message": "System restart initiated"})
                if stored_pwd == password:
                    reboot_rpi()
                    session_clear()
                    return jsonify({"status": "success", "message": "System restart initiated"})
            return jsonify({"status": "error", "message": "Invalid password"}), 401
    
    # GET request - show password prompt
    return render_template("maintenance.html", restart_prompt=True)


@app.route("/terminate", methods=["GET", "POST"])
def terminate():
    if "username" not in session:
        return redirect(url_for("login"))
    
    if request.method == "POST":
        # Handle both JSON and form data
        if request.is_json:
            data = request.get_json()
            password = data.get("password", "") if data else ""
        else:
            password = request.form.get("password", "")
        
        username = session.get("username")
        
        # Verify password
        db = create_connection(db_file)
        if db:
            cursor = db.cursor()
            cursor.execute("SELECT password FROM users WHERE username=?", (username,))
            user_data = cursor.fetchone()
            cursor.close()
            db.close()
            
            if user_data and user_data[0] == password:
                # Password verified - proceed with terminate
                session_clear()
                threading.Timer(1.0, lambda: terminate_server()).start()
                return jsonify({"status": "success", "message": "System shutdown initiated"})
            else:
                return jsonify({"status": "error", "message": "Invalid password"}), 401
    
    # GET request - show password prompt
    return render_template("maintenance.html", terminate_prompt=True)


def terminate_server():
    """Terminate the Flask application."""
    os._exit(0)


@app.route("/device_config")
def device_config():
    if "username" in session:
        username = session["username"]
        db = create_connection(db_file)
        if db:
            try:
                cursor = db.cursor()
                cursor.execute("SELECT * FROM users WHERE username=?", (username,))
                user_data = cursor.fetchone()
                cursor.close()
                db.close()

                db3 = create_connection("dexterpanel2.db")
                cursor3 = db3.cursor()
                cursor3.execute("SELECT * FROM systemLogs ")
                logss_data = cursor3.fetchall()
                cursor3.close()
                db3.close()
                return render_template(
                    "device_config.html", logg=logss_data, user=user_data
                )
            except:
                return redirect(url_for("login"))
    return redirect(url_for("login"))


@app.route("/get_zone", methods=["GET", "PUT"])
def get_zone():
    try:
        # Read from the Raspberry Pi file path
        file_path = "/home/pi/Test3/zoneSettings.txt"
        with open(file_path, "r") as file:
            lines = file.readlines()
            zones_data = []
            for i, line in enumerate(lines):
                if line.strip():  # Skip empty lines
                    activated, buzzer, device = map(int, line.strip().split())
                    # Convert numeric values to what frontend expects
                    device_name = None
                    if device == 1:
                        device_name = "BAS"
                    elif device == 2:
                        device_name = "FAS"
                    elif device == 3:
                        device_name = "Time Lock"
                    elif device == 4:
                        device_name = "BACS"
                    elif device == 5:
                        device_name = "CCTV"
                    elif device == 6:
                        device_name = "IAS"

                    buzzer_status = "on" if buzzer == 1 else "off"
                    zones_data.append([i + 1, activated, device_name, buzzer_status])

            return jsonify(zones_data)
    except:
        # If file read fails, try database as fallback
        db = create_connection(db_file)
        if db:
            cursor = db.cursor()
            cursor.execute("SELECT * FROM zone")
            zones_data = cursor.fetchall()
            cursor.close()
            db.close()
            return jsonify(zones_data)
        return jsonify([])


def read_zone_file(file_path):
    try:
        with open(file_path, "r") as file:
            return [line.strip() for line in file.readlines()]
    except:
        return []


def log_file_change(file_type):
    try:
        db = create_connection("dexterpanel2.db")
        if db:
            cursor = db.cursor()
            timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
            message = "%s file updated" % file_type
            cursor.execute(
                "INSERT INTO systemLogs (date, message) VALUES (?, ?)",
                (timestamp, message),
            )
            db.commit()
            cursor.close()
            db.close()
    except:
        pass


@app.route("/update_zone", methods=["PUT"])
def update_zone():
    if request.method == "PUT":
        data = request.json
        if not data:
            return redirect(url_for("device_config"))

        try:
            # Set the correct Raspberry Pi file path
            file_path = "/home/pi/Test3/zoneSettings.txt"

            # Read existing lines from zoneSettings.txt
            lines = ["0 0 0" for _ in range(16)]  # Initialize with defaults
            try:
                with open(file_path, "r") as file:
                    file_lines = file.readlines()
                    for i, line in enumerate(file_lines):
                        if i < 16:  # Only process up to 16 lines
                            lines[i] = line.strip()
            except:
                pass

            # Update database and text file
            db = create_connection(db_file)
            if db:
                cursor = db.cursor()
                try:
                    for zone_data in data:
                        zoneId = zone_data.get("zoneId")
                        if not zoneId or not isinstance(zoneId, int):
                            continue

                        activated = zone_data.get("activated", 0)
                        selectedDevice = zone_data.get("selectedDevice", "")
                        buzzerStatus = zone_data.get("buzzerStatus", "off")

                        if 1 <= zoneId <= 16:  # Validate zone ID
                            # Update database
                            cursor.execute(
                                "SELECT * FROM zone WHERE zoneId=?", (zoneId,)
                            )
                            existing_zone = cursor.fetchone()

                            if existing_zone:
                                cursor.execute(
                                    "UPDATE zone SET activated=?, selectedDevice=?, buzzerStatus=? WHERE zoneId=?",
                                    (activated, selectedDevice, buzzerStatus, zoneId),
                                )
                            else:
                                cursor.execute(
                                    "INSERT INTO zone (zoneId, activated, selectedDevice, buzzerStatus) VALUES (?, ?, ?, ?)",
                                    (zoneId, activated, selectedDevice, buzzerStatus),
                                )

                            # Convert values for text file
                            device_num = 0
                            if selectedDevice == "BAS":
                                device_num = 1
                            elif selectedDevice == "FAS":
                                device_num = 2
                            elif selectedDevice == "Time Lock":
                                device_num = 3
                            elif selectedDevice == "BACS":
                                device_num = 4
                            elif selectedDevice == "CCTV":
                                device_num = 5
                            elif selectedDevice == "IAS":
                                device_num = 6

                            buzzer_num = 1 if buzzerStatus == "on" else 0

                            # Update the corresponding line in the text file
                            lines[zoneId - 1] = "%d %d %d" % (
                                activated,
                                buzzer_num,
                                device_num,
                            )

                    # Write all updates to zoneSettings.txt
                    try:
                        # Create directory if it doesn't exist
                        directory = os.path.dirname(file_path)
                        if not os.path.exists(directory):
                            os.makedirs(directory)
                        with open(file_path, "w") as file:
                            file.write("\n".join(lines) + "\n")
                    except Exception as e:
                        logging.error("Error writing to zoneSettings.txt: {}".format(e))
                        # Still continue with database update even if file write fails

                    # Log the change
                    log_file_change("Zone")

                    db.commit()
                    cursor.close()
                    db.close()
                    return jsonify({"Message": "Done"})
                except:
                    if cursor:
                        cursor.close()
                    if db:
                        db.close()
                    return redirect(url_for("device_config"))
        except:
            return redirect(url_for("device_config"))
    return redirect(url_for("device_config"))


@app.route("/powerzone_config")
def powerzone_config():
    if "username" in session:
        username = session["username"]
        db = create_connection(db_file)
        if db:
            try:
                cursor = db.cursor()
                cursor.execute("SELECT * FROM users WHERE username=?", (username,))
                user_data = cursor.fetchone()
                cursor.close()
                db.close()
                db3 = create_connection("dexterpanel2.db")
                cursor3 = db3.cursor()
                cursor3.execute("SELECT * FROM systemLogs ")
                logss_data = cursor3.fetchall()
                cursor3.close()
                db3.close()
                return render_template(
                    "powerzone_config.html", logg=logss_data, user=user_data
                )
            except Error as e:
                # print(f"Database query error: {e}")
                return redirect(url_for("login"))
    return redirect(url_for("login"))


# Get power zone data route
@app.route("/get_powerzone", methods=["GET", "PUT"])
def get_powerzone():
    if "username" in session:
        try:
            # Read from the Raspberry Pi file path
            file_path = "/home/pi/Test3/powerZoneSettings.txt"
            with open(file_path, "r") as file:
                lines = file.readlines()
                zones_data = []
                for i, line in enumerate(lines):
                    if line.strip():  # Skip empty lines
                        activated, buzzer, device = map(int, line.strip().split())
                        # Convert numeric values to what frontend expects
                        device_name = None
                        if device == 1:
                            device_name = "BAS"
                        elif device == 2:
                            device_name = "FAS"
                        elif device == 3:
                            device_name = "Time Lock"
                        elif device == 4:
                            device_name = "BACS"
                        elif device == 5:
                            device_name = "NVR & DVR"
                        elif device == 6:
                            device_name = "IAS"

                        buzzer_status = "on" if buzzer == 1 else "off"
                        zones_data.append(
                            [i + 1, activated, device_name, buzzer_status]
                        )

                return jsonify(zones_data)
        except:
            # If file read fails, try database as fallback
            db = create_connection(db_file)
            if db:
                cursor = db.cursor()
                cursor.execute("SELECT * FROM powerzone")
                zones_data = cursor.fetchall()
                cursor.close()
                db.close()
                return jsonify(zones_data)
            return jsonify([])


# Update power zone data route


@app.route("/power_zone", methods=["PUT"])
def power_zone():
    if request.method == "PUT":
        data = request.json
        if not data:
            return redirect(url_for("powerzone_config"))

        try:
            # Set the correct Raspberry Pi file path
            file_path = "/home/pi/Test3/powerZoneSettings.txt"

            # Initialize 16 lines - first 8 for power zones, next 8 with zeros
            lines = ["0 0 0" for _ in range(16)]

            # Read existing lines from powerZoneSettings.txt
            try:
                with open(file_path, "r") as file:
                    file_lines = file.readlines()
                    for i, line in enumerate(file_lines):
                        if i < 16:  # Only process up to 16 lines
                            lines[i] = line.strip()
            except:
                pass

            # Update database and text file
            db = create_connection(db_file)
            if db:
                cursor = db.cursor()
                try:
                    # First update the power zones (first 8)
                    for zone_data in data:
                        zoneId = zone_data.get("zoneId")
                        if not zoneId or not isinstance(zoneId, int):
                            continue

                        activated = zone_data.get("activated", 0)
                        selectedDevice = zone_data.get("selectedDevice", "")
                        buzzerStatus = zone_data.get("buzzerStatus", "off")

                        if (
                            1 <= zoneId <= 8
                        ):  # Only process first 8 zones for power zones
                            # Update database
                            cursor.execute(
                                "SELECT * FROM powerzone WHERE zoneId=?", (zoneId,)
                            )
                            existing_zone = cursor.fetchone()
                            if existing_zone:
                                cursor.execute(
                                    "UPDATE powerzone SET activated=?, selectedDevice=?, buzzerStatus=? WHERE zoneId=?",
                                    (activated, selectedDevice, buzzerStatus, zoneId),
                                )
                            else:
                                cursor.execute(
                                    "INSERT INTO powerzone (zoneId, activated, selectedDevice, buzzerStatus) VALUES (?, ?, ?, ?)",
                                    (zoneId, activated, selectedDevice, buzzerStatus),
                                )

                            # Convert values for text file
                            device_num = 0
                            if selectedDevice == "BAS":
                                device_num = 1
                            elif selectedDevice == "FAS":
                                device_num = 2
                            elif selectedDevice == "Time Lock":
                                device_num = 3
                            elif selectedDevice == "BACS":
                                device_num = 4
                            elif selectedDevice == "NVR & DVR":
                                device_num = 5
                            elif selectedDevice == "IAS":
                                device_num = 6

                            buzzer_num = 1 if buzzerStatus == "on" else 0

                            # Update the corresponding line in the text file
                            lines[zoneId - 1] = "%d %d %d" % (
                                activated,
                                buzzer_num,
                                device_num,
                            )

                    # Ensure next 8 zones are zeros in both database and text file
                    for zoneId in range(9, 17):
                        # Update database for zones 9-16 with zeros
                        cursor.execute(
                            "SELECT * FROM powerzone WHERE zoneId=?", (zoneId,)
                        )
                        existing_zone = cursor.fetchone()
                        if existing_zone:
                            cursor.execute(
                                "UPDATE powerzone SET activated=0, selectedDevice='', buzzerStatus='off' WHERE zoneId=?",
                                (zoneId,),
                            )
                        else:
                            cursor.execute(
                                "INSERT INTO powerzone (zoneId, activated, selectedDevice, buzzerStatus) VALUES (?, 0, '', 'off')",
                                (zoneId,),
                            )

                        # Ensure text file lines 9-16 are zeros
                        lines[zoneId - 1] = "0 0 0"

                    # Write all updates to powerZoneSettings.txt
                    try:
                        # Create directory if it doesn't exist
                        directory = os.path.dirname(file_path)
                        if not os.path.exists(directory):
                            os.makedirs(directory)
                        with open(file_path, "w") as file:
                            file.write("\n".join(lines) + "\n")
                    except Exception as e:
                        logging.error(
                            "Error writing to powerZoneSettings.txt: {}".format(e)
                        )
                        # Still continue with database update even if file write fails

                    # Log the change
                    log_file_change("Power Zone")

                    db.commit()
                    cursor.close()
                    db.close()
                    return jsonify({"Message": "Done"})
                except:
                    if cursor:
                        cursor.close()
                    if db:
                        db.close()
                    return redirect(url_for("powerzone_config"))
        except:
            return redirect(url_for("powerzone_config"))
    return redirect(url_for("powerzone_config"))


@app.route("/advanced")
def advanced():
    if "username" in session:
        username = session["username"]
        db = create_connection("sepleDB.db")
        cursor = db.cursor()
        cursor.execute("SELECT * FROM users WHERE username=?", (username,))
        user_data = cursor.fetchone()
        cursor.close()
        db.close()

        db3 = create_connection("dexterpanel2.db")
        cursor3 = db3.cursor()
        cursor3.execute("SELECT * FROM systemLogs ")
        logss_data = cursor3.fetchall()
        cursor3.close()
        db3.close()
        return render_template("advanced.html", logg=logss_data, user=user_data)
    return redirect(url_for("login"))


# @app.route("/resettodefault")
# def resettodefault():
#     resetToDefault()
#     return redirect(url_for("advanced"))


def safe_read(file_path):
    if os.path.exists(file_path):
        with open(file_path, "r") as f:
            return f.read().strip()
    return ""


def safe_write(file_path, content):
    with open(file_path, "w") as f:
        f.write(content)


@app.route("/general")
def general():
    if "username" in session:
        username = session["username"]
        db = create_connection("sepleDB.db")
        cursor = db.cursor()
        cursor2 = db.cursor()
        cursor.execute("SELECT * FROM users WHERE username=?", (username,))
        cursor2.execute("SELECT * FROM general")
        user_data = cursor.fetchone()
        user_data2 = cursor2.fetchall()
        cursor.close()
        db.close()

        db3 = create_connection("dexterpanel2.db")
        cursor3 = db3.cursor()
        cursor3.execute("SELECT * FROM systemLogs ")
        logss_data = cursor3.fetchall()
        cursor3.close()
        db3.close()

        brand_name = safe_read("/home/pi/Test3/Brand.txt").replace("+", " ")
        branch_name = safe_read("/home/pi/Test3/Branch.txt").replace("+", " ")

        return render_template(
            "general.html",
            brand_name=brand_name,
            branch_name=branch_name,
            user=user_data,
            logg=logss_data,
            user2=user_data2,
        )
    return redirect(url_for("login"))


@app.route("/date_time", methods=["POST"])
def date_time():
    try:
        data = request.form
        date_str = data.get("setDate", "").strip()
        if not date_str:
            return jsonify({"status": "error", "message": "Date not provided"}), 400

        year_str = datetime.strptime(date_str, "%Y-%m-%d")
        second   = int(data.get("seconds",  0))
        minutes  = int(data.get("minutes",  0))
        hours    = int(data.get("hours",    0))
        day      = year_str.weekday() + 1
        date     = year_str.day
        month    = year_str.month
        year     = year_str.year % 100

        if sdlds1370 is not None:
            # RTC hardware available — write to DS1307 chip
            sdlds1370.write_all(
                seconds=second,
                minutes=minutes,
                hours=hours,
                day=day,
                date=date,
                month=month,
                year=year,
                save_as_24h=True,
            )
            sdlds1370.write_now()
        else:
            # No RTC hardware — set HOST system clock via nsenter
            # Format: MMDDHHmmYYYY.SS
            time_str = (
                f"{month:02d}{date:02d}"
                f"{hours:02d}{minutes:02d}"
                f"{year_str.year}"
                f".{second:02d}"
            )
            try:
                _host_run(["date", time_str], check=True, capture_output=True)
                _host_run(["hwclock", "--systohc"], capture_output=True)
            except Exception as _te:
                app.logger.warning("[date_time] System clock set failed: %s", _te)

        return redirect(url_for("general"))

    except ValueError as e:
        app.logger.error("[date_time] Invalid date/time format: %s", e)
        return jsonify({"status": "error", "message": f"Invalid date/time: {e}"}), 400
    except Exception as e:
        app.logger.error("[date_time] Error setting date/time: %s", e)
        return jsonify({"status": "error", "message": f"Failed to set date/time: {e}"}), 500


def format_and_center(text, width=32):
    text = text.strip().upper()
    chars = ["+" if c == " " else c for c in text]
    spaced_text = " ".join(chars)
    content_with_spaces = " " + spaced_text + " "
    content_len = len(content_with_spaces)

    if content_len > width:
        return "Text too long to fit", 400

    total_padding = width - content_len
    left_pad_count = total_padding // 2
    right_pad_count = total_padding - left_pad_count

    left_pad = ("+ " * (left_pad_count)).rstrip()
    right_pad = ("+ " * (right_pad_count)).rstrip()

    line = "{}{}{}".format(left_pad, content_with_spaces, right_pad)

    # Trim or pad to exact width
    if len(line) < width:
        line += "+" * (width - len(line))
    elif len(line) > width:
        line = line[:width]

    return line


def format_name_center(text, width=16):
    text = text.strip()
    text_len = len(text)

    if text_len > width:
        return "Text exceeds allowed width.", 400

    total_padding = width - text_len
    left_pad = " " * (total_padding // 2)
    right_pad = " " * (total_padding - len(left_pad))

    return "{}{}{}".format(left_pad, text, right_pad)


def add_zero_lines(base_text, total_lines=8, columns=16):
    lines = [base_text]  # First line is formatted with '+'
    zero_line = "0 " * columns  # Create the zero pattern

    for _ in range(total_lines - 1):
        lines.append(zero_line.strip())  # Maintain correct spacing

    return "\n".join(lines)


@app.route("/brandname", methods=["POST"])
def brandname():
    brand_name = request.form.get("brandName", "").strip()
    branch_name = request.form.get("siteName", "").strip()

    if not brand_name or not branch_name:
        return "Both brand name and branch name are required.", 400

    # Format data
    name_centered = format_name_center(brand_name)
    branch_name_centered = format_name_center(branch_name)
    address_centered = format_and_center(brand_name)
    branch_address_centered = format_and_center(branch_name)

    # Save basic files
    with open("/home/pi/Test3/Brand.txt", "w") as f:
        f.write(name_centered)

    with open("/home/pi/Test3/Branch.txt", "w") as f:
        f.write(branch_name_centered)

    # Save address files with zeros below
    with open("/home/pi/Test3/brandNameAddress.txt", "w") as f:
        f.write(add_zero_lines(address_centered))

    with open("/home/pi/Test3/branchNameAddress.txt", "w") as f:
        f.write(add_zero_lines(branch_address_centered))

    return redirect(url_for("general"))


@app.route("/general_data", methods=["GET", "POST"])
def general_data():
    success_message = None
    error_message = None
    if request.method == "POST":
        action = request.form.get("action")

        if action == "change_password":
            current_password = request.form.get("currentPassword")
            new_password = request.form.get("newPassword")
            confirm_password = request.form.get("confirmPassword")

            if not all([current_password, new_password, confirm_password]):
                error_message = "All password fields are required"
            elif new_password != confirm_password:
                error_message = "New passwords do not match"
            else:
                # Read from text file instead of database
                password_file_path = "/home/pi/Test3/AdminPass.txt"
                try:
                    # Read the entire file content
                    with open(password_file_path, "r") as file:
                        content = file.read()

                    # Split content into lines
                    lines = content.strip().split("\n")

                    # First line should contain: 0 [password]
                    # Second line should be: 0 0 (keep unchanged)
                    if len(lines) >= 1:
                        first_line_parts = lines[0].split(" ")
                        if len(first_line_parts) >= 2:
                            stored_password = first_line_parts[1]

                            # Verify current password
                            if stored_password == current_password:
                                # Update the password in first line, keep the rest unchanged
                                first_line_parts[1] = new_password
                                lines[0] = " ".join(first_line_parts)

                                # Write updated content back to file
                                with open(password_file_path, "w") as file:
                                    file.write("\n".join(lines))

                                success_message = "Password updated successfully"

                                # Log the password change
                                try:
                                    db2 = create_connection("dexterpanel2.db")
                                    if db2:
                                        cursor2 = db2.cursor()
                                        log_message = "Password changed successfully"
                                        cursor2.execute(
                                            "INSERT INTO systemLogs (date, message) VALUES (datetime('now', 'localtime'), ?)",
                                            (log_message,),
                                        )
                                        db2.commit()
                                        cursor2.close()
                                        db2.close()
                                except:
                                    pass
                            else:
                                error_message = "Current password is incorrect"
                        else:
                            error_message = "Invalid password file format"
                    else:
                        error_message = "Password file is empty or corrupted"

                except FileNotFoundError:
                    error_message = "Password file not found"
                except Exception as e:
                    error_message = "Error updating password"

        elif action == "save_date":
            new_date = request.form.get("setDate")
            if not new_date:
                error_message = "Please select a date"
            else:
                try:
                    success_message = "Date updated successfully"
                except Exception:
                    error_message = "Error updating date"

        else:
            brand_name = request.form.get("brandName")
            site_name = request.form.get("siteName")

            if not all([brand_name, site_name]):
                error_message = "Both brand name and site name are required"
            else:
                db = create_connection(db_file)
                if db:
                    cursor = None
                    try:
                        cursor = db.cursor()
                        cursor.execute("SELECT * FROM general WHERE ID=1")
                        existing = cursor.fetchall()
                        if existing:
                            cursor.execute(
                                "UPDATE general SET brand_name=?, site_name=? WHERE ID=1",
                                (brand_name, site_name),
                            )
                        else:
                            cursor.execute(
                                "INSERT INTO general (brand_name, site_name) VALUES (?,?)",
                                (brand_name, site_name),
                            )
                        db.commit()
                        success_message = (
                            "Brand and site information updated successfully"
                        )

                        try:
                            db2 = create_connection("dexterpanel2.db")
                            if db2:
                                cursor2 = db2.cursor()
                                log_message = "General settings updated"
                                cursor2.execute(
                                    "INSERT INTO systemLogs (date, message) VALUES (datetime('now', 'localtime'), ?)",
                                    (log_message,),
                                )
                                db2.commit()
                                cursor2.close()
                                db2.close()
                        except:
                            pass

                    except:
                        error_message = "Error updating settings"
                    finally:
                        if cursor:
                            cursor.close()
                        db.close()
                else:
                    error_message = "Database connection failed"

    return redirect(
        url_for("general", success_message=success_message, error_message=error_message)
    )


@app.route("/maintenance")
def maintenance():
    if "username" in session:
        username = session["username"]
        db = create_connection("sepleDB.db")
        cursor = db.cursor()
        cursor.execute("SELECT * FROM users WHERE username=?", (username,))
        user_data = cursor.fetchone()
        cursor.close()
        db.close()

        db3 = create_connection("dexterpanel2.db")
        cursor3 = db3.cursor()
        cursor3.execute("SELECT * FROM systemLogs ")
        logss_data = cursor3.fetchall()
        cursor3.close()
        db3.close()
        return render_template("maintenance.html", logg=logss_data, user=user_data)
    return redirect(url_for("login"))


@app.route("/system_test")
def system_test():
    if "username" in session:
        username = session["username"]
        db = create_connection("sepleDB.db")
        cursor = db.cursor()
        cursor.execute("SELECT * FROM users WHERE username=?", (username,))
        user_data = cursor.fetchone()
        cursor.close()
        db.close()

        db3 = create_connection("dexterpanel2.db")
        cursor3 = db3.cursor()
        cursor3.execute("SELECT * FROM systemLogs ")
        logss_data = cursor3.fetchall()
        cursor3.close()
        db3.close()

        # Initialize LED states if not exists
        led_states = {
            1: False,  # Lamp Test
            2: False,  # Relay Test
            3: False,  # Buzzer Test
        }

        return render_template(
            "systemTest.html", logg=logss_data, user=user_data, led_states=led_states
        )
    return redirect(url_for("login"))


@app.route("/control", methods=["POST"])
def control():
    if request.method == "POST":
        try:
            led_id = int(request.form["led"])
            return redirect(url_for("system_test"))
        except:
            return redirect(url_for("system_test"))


@app.route("/logs")
def logs():
    if "username" in session:
        username = session["username"]

        # Connect to the first database (sepleDB.db)
        db1 = create_connection("sepleDB.db")
        cursor1 = db1.cursor()
        cursor1.execute("SELECT * FROM users WHERE username=?", (username,))
        user_data = cursor1.fetchone()
        cursor1.close()
        db1.close()

        # Connect to the second database (dexterpanel2.db)
        db2 = create_connection("/home/pi/Test3/dexterpanel2.db")
        cursor2 = db2.cursor()
        cursor2.execute("SELECT * FROM systemLogs")
        logs_data = cursor2.fetchall()
        cursor2.close()
        db2.close()

        # Return the logs data in reverse order (newest first)
        logs_data = list(reversed(logs_data))

        # Get additional data
        db3 = create_connection("dexterpanel2.db")
        cursor3 = db3.cursor()
        cursor3.execute("SELECT * FROM systemLogs")
        logss_data = cursor3.fetchall()
        cursor3.close()
        db3.close()

        return render_template(
            "logs.html", user=user_data, logs=logs_data, logg=logss_data
        )

    # Handle unauthenticated requests
    return redirect(url_for("login"))


@app.route("/reports")
def reports():
    if "username" in session:
        username = session["username"]
        db = create_connection("sepleDB.db")
        cursor = db.cursor()
        cursor.execute("SELECT * FROM users WHERE username=?", (username,))
        user_data = cursor.fetchone()
        cursor.close()
        db.cursor()
        db3 = create_connection("dexterpanel2.db")
        cursor3 = db3.cursor()
        cursor3.execute("SELECT * FROM systemLogs ")
        logss_data = cursor3.fetchall()
        cursor3.close()
        db3.close()
        return render_template("reports.html", user=user_data, logg=logss_data)
    return redirect(url_for("login"))



@app.route("/connectivity_settings", methods=["GET", "POST"])
def connectivity_settings():
    if "username" not in session:
        return redirect(url_for("login"))

    # ---------- SAVE ----------
    if request.method == "POST":
        gsm_modem_mode = request.form.get("gsm_modem_mode")

        # network_type is the column TLChronosProMAIN reads to decide which
        # process runs (EthernetProcess vs ESIM_GSMProcess). gsm_modem_mode
        # stores the SIM sub-type. Both must be updated together.
        network_type = "ethernet" if gsm_modem_mode == "ethernet" else "gsm"

        # Write to modem_config.db
        # gsm_modem_mode is only meaningful for GSM sub-types (esim/physical).
        # On Ethernet, only network_type is updated so gsm_modem_mode stays intact.
        cursor = None
        db = None
        try:
            db = create_connection("/home/pi/Test3/modem_config.db")
            cursor = db.cursor()
            cursor.execute("SELECT id FROM modem_parameters WHERE id=1")
            exists = cursor.fetchone()
            if exists:
                if network_type == "ethernet":
                    cursor.execute(
                        "UPDATE modem_parameters SET network_type=? WHERE id=1",
                        (network_type,)
                    )
                else:
                    cursor.execute(
                        "UPDATE modem_parameters SET gsm_modem_mode=?, network_type=? WHERE id=1",
                        (gsm_modem_mode, network_type)
                    )
            else:
                cursor.execute(
                    "INSERT INTO modem_parameters (id, gsm_modem_mode, network_type) VALUES (1, ?, ?)",
                    (gsm_modem_mode if network_type != "ethernet" else "", network_type)
                )
            db.commit()
        except Exception as e:
            app.logger.warning("modem_config.db write error: %s", e)
        finally:
            try:
                cursor.close()
                db.close()
            except Exception:
                pass

        # Persist network_type to .env so _sync_network_type_from_env() on the
        # next container restart does not overwrite the DB back to the old value.
        try:
            _env_path = "/home/pi/Test3/.env"
            with open(_env_path, "r") as _ef:
                _env_lines = _ef.readlines()
            _written = False
            for _i, _line in enumerate(_env_lines):
                if _line.lstrip().startswith("NETWORK_TYPE") or (
                    _line.lstrip().startswith("#") and "NETWORK_TYPE" in _line
                ):
                    _env_lines[_i] = f"NETWORK_TYPE={network_type}\n"
                    _written = True
                    break
            if not _written:
                _env_lines.append(f"NETWORK_TYPE={network_type}\n")
            with open(_env_path, "w") as _ef:
                _ef.writelines(_env_lines)
        except Exception as _ee:
            app.logger.warning(".env NETWORK_TYPE update failed: %s", _ee)

        # Write to cavliRunningParam.db only for GSM SIM modes — not Ethernet
        if gsm_modem_mode in ("esim", "physical"):
            try:
                _cr_conn = create_connection("/home/pi/Test3/cavliRunningParam.db")
                if _cr_conn:
                    _cr_conn.execute(
                        "UPDATE cavliRunningParam SET simSwap=? WHERE id=1",
                        (gsm_modem_mode,)
                    )
                    _cr_conn.commit()
                    _cr_conn.close()
            except Exception as _ce:
                app.logger.warning("cavliRunningParam.db write error: %s", _ce)

        # Restart dexter-mqtt via Docker socket API so it picks up updated network_type.
        # docker CLI is not installed in the container; use the mounted socket directly.
        try:
            import http.client, socket as _sock

            class _UnixHTTPConnection(http.client.HTTPConnection):
                def __init__(self, sock_path):
                    super().__init__("localhost")
                    self._sock_path = sock_path
                    self.sock = None
                def connect(self):
                    s = _sock.socket(_sock.AF_UNIX, _sock.SOCK_STREAM)
                    s.connect(self._sock_path)
                    self.sock = s

            _conn = _UnixHTTPConnection("/var/run/docker.sock")
            _conn.request("POST", "/containers/dexter-mqtt/restart?t=5")
            _resp = _conn.getresponse()
            _conn.close()
            if _resp.status not in (204, 304):
                app.logger.warning("dexter-mqtt restart HTTP %s", _resp.status)
        except Exception as _de:
            app.logger.warning("dexter-mqtt restart failed: %s", _de)

        return redirect(url_for("connectivity_settings"))

    # ---------- FETCH ----------
    # The LCD menu writes network_type ("ethernet"/"gsm") and simSwap ("esim"/"physical")
    # but never writes gsm_modem_mode. Use network_type as the primary discriminator
    # so that LCD changes are always reflected.
    saved_gsm_mode = ""
    _network_type  = ""
    cursor = None
    db = None

    try:
        db = create_connection("/home/pi/Test3/modem_config.db")
        cursor = db.cursor()
        cursor.execute(
            "SELECT gsm_modem_mode, network_type FROM modem_parameters WHERE id=1"
        )
        row = cursor.fetchone()
        if row:
            saved_gsm_mode = row[0] or ""
            _network_type  = row[1] or ""
    except Exception as e:
        print("? Fetch Error:", e)
    finally:
        if cursor:
            cursor.close()
        if db:
            db.close()

    if _network_type == "ethernet":
        # LCD set NETWORK → Ethernet; trust it regardless of stale gsm_modem_mode
        saved_gsm_mode = "ethernet"
    elif _network_type == "gsm" or saved_gsm_mode not in ("ethernet", "esim", "physical"):
        # LCD set NETWORK → GSM (or gsm_modem_mode is stale/null); SIM sub-type
        # comes from cavliRunningParam.simSwap which the LCD eSIM screen writes.
        try:
            _cavli_conn = create_connection("/home/pi/Test3/cavliRunningParam.db")
            if _cavli_conn:
                _sim_row = _cavli_conn.execute(
                    "SELECT simSwap FROM cavliRunningParam WHERE id=1"
                ).fetchone()
                _cavli_conn.close()
                if _sim_row and _sim_row[0] in ("esim", "physical"):
                    saved_gsm_mode = _sim_row[0]
        except Exception as _se:
            app.logger.debug("sim_swap fetch failed: %s", _se)

    # ---------- USER & LOG ----------
    db2 = create_connection("sepleDB.db")
    cursor2 = db2.cursor()
    cursor2.execute("SELECT * FROM users WHERE username=?", (session["username"],))
    user_data = cursor2.fetchone()
    cursor2.close()
    db2.close()

    db3 = create_connection("dexterpanel2.db")
    cursor3 = db3.cursor()
    cursor3.execute("SELECT * FROM systemLogs")
    logss_data = cursor3.fetchall()
    cursor3.close()
    db3.close()

    return render_template(
        "connectivity_sett.html",
        user=user_data,
        logg=logss_data,
        saved_gsm_mode=saved_gsm_mode
    )

@app.route("/get_eSim")
def get_eSim():
    if "username" in session:
        db = create_connection(db_file)
        if db:
            cursor = db.cursor()
            cursor.execute("SELECT * FROM eSim")
            net_data = cursor.fetchall()
            cursor.close()
            db.close()
            return jsonify(net_data)
        else:
            return jsonify([])


@app.route("/neteSim_data", methods=["PUT"])
def neteSim_data():
    if request.method == "PUT":
        data = request.json
        eSim_activated = data.get("eSim_activated")
        select_network = data.get("select_network")
        id = 1
        db = create_connection(db_file)
        if db:
            cursor = db.cursor()
            cursor.execute("SELECT * from eSim WHERE ID=1")
            existing = cursor.fetchone()
            if existing:
                cursor.execute(
                    "UPDATE eSim SET eSim_activated=?, select_network=? WHERE ID=1",
                    (eSim_activated, select_network),
                )
            else:
                cursor.execute(
                    "INSERT INTO eSim (eSim_activated, select_network, ID) VALUES (?, ?, ?)",
                    (eSim_activated, select_network, id),
                )
            db.commit()
            cursor.close()
            db.close()
        return {"done": "data"}


@app.route("/gnss")
def gnss():
    if "username" in session:
        username = session["username"]
        db = create_connection("sepleDB.db")
        cursor = db.cursor()
        cursor.execute("SELECT * FROM users WHERE username=?", (username,))
        user_data = cursor.fetchone()
        cursor.close()
        db.cursor()

        db3 = create_connection("dexterpanel2.db")
        cursor3 = db3.cursor()
        cursor3.execute("SELECT * FROM systemLogs ")
        logss_data = cursor3.fetchall()
        cursor3.close()
        db3.close()
        return render_template("net_Gnss.html", logg=logss_data, user=user_data)
    return redirect(url_for("login"))


@app.route("/get_gnss")
def get_gnss():
    if "username" in session:
        db = create_connection(db_file)
        if db:
            cursor = db.cursor()
            cursor.execute("SELECT * FROM gnss")
            gnss_data = cursor.fetchall()
            cursor.close()
            db.close()
            return jsonify(gnss_data)
        else:
            return jsonify([])


@app.route("/net_gnss", methods=["PUT"])
def net_gnss():
    if request.method == "PUT":
        data = request.json
        gnss_activated = data.get("gnss_activated")
        db = create_connection(db_file)
        if db:
            cursor = db.cursor()
            cursor.execute("SELECT * FROM gnss WHERE ID=1")
            existing = cursor.fetchone()
            if existing:
                cursor.execute(
                    "UPDATE gnss SET gnss_activated=? WHERE ID=1", (gnss_activated,)
                )
            else:
                cursor.execute(
                    "INSERT INTO gnss (gnss_activated) VALUES (?)", (gnss_activated,)
                )
            db.commit()
            cursor.close()
            db.close()
        return {"data": "done"}


@app.route("/lan")
def lan():
    if "username" not in session:
        return redirect(url_for("login"))

    if not check_user_access("lan"):
        return render_template("index.html", access_denied=True)

    username = session["username"]

    # ---------- USER DB ----------
    db = create_connection("sepleDB.db")
    cursor = db.cursor()
    cursor.execute("SELECT * FROM users WHERE username = ?", (username,))
    user_data = cursor.fetchone()
    cursor.close()
    db.close()

    # ---------- NETWORK SETTINGS DB ----------
    db2 = create_connection("/home/pi/Test3/network_settings.db")
    cursor2 = db2.cursor()
    cursor2.execute("SELECT setting_name, setting_value FROM Settings")
    rows = cursor2.fetchall()
    cursor2.close()
    db2.close()

    # Convert rows to dictionary
    lan = {name: value for name, value in rows} if rows else {}

    # ---------- DEFAULTS ----------
    # Derive network_mode from the key Configure_Network_7 actually reads.
    # "network_mode" is never stored in Settings; "Enable/Disable Static/dynamic"
    # is the authoritative key — "dynamic" means DHCP, anything else means Static.
    if "network_mode" not in lan:
        static_dynamic = lan.get("Enable/Disable Static/dynamic", "")
        lan["network_mode"] = "dynamic" if static_dynamic == "dynamic" else "static"
    lan.setdefault("Set IP Address", "")
    lan.setdefault("Set Port Number", "")
    lan.setdefault("Subnet mask", "")
    lan.setdefault("Gateway", "")
    lan.setdefault("preferred_dns_server", "")
    lan.setdefault("alternate_dns_server", "")
    lan.setdefault("APN Settings", "")

    return render_template(
        "Lan.html",
        user=user_data,
        lan=lan
    )





@app.route("/data2_lan", methods=["PUT"])
def data2_lan():
    if request.method == "PUT":
        data = request.json
        network_led_sts = data.get("network_led_sts")
        wireless_lan = data.get("wireless_lan")
        ip_module = data.get("ip_module")
        static_or_dynamic = data.get("static_or_dynamic")
        db = create_connection(db_file)
        if db:
            cursor = db.cursor()
            cursor.execute("SELECT * FROM lan WHERE ID=1")

            existing = cursor.fetchone()
            if existing:
                cursor.execute(
                    "UPDATE lan SET network_led_sts=?, wireless_lan=?,ip_module=?, static_or_dynamic=? WHERE ID=1",
                    (network_led_sts, wireless_lan, ip_module, static_or_dynamic),
                )
            else:
                cursor.execute(
                    "INSERT INTO lan (network_led_sts,wireless_lan,ip_module,static_or_dynamic) VALUES (?,?,?,?)",
                    (network_led_sts, wireless_lan, ip_module, static_or_dynamic),
                )
            db.commit()
            cursor.close()
            db.close()
        return jsonify([])


@app.route("/get_data2lan")
def get_data2lan():
    if "username" in session:
        db = create_connection(db_file)
        if db:
            cursor = db.cursor()
            cursor.execute(
                "SELECT network_led_sts,wireless_lan,ip_module,static_or_dynamic  FROM lan"
            )
            get_data = cursor.fetchall()
            cursor.close()
            db.close()
            return jsonify(get_data)



@app.route("/data_lan", methods=["POST"])
def data_lan():
    if "username" not in session:
        return redirect(url_for("login"))

    data = request.form.to_dict()

    db = create_connection("/home/pi/Test3/network_settings.db")
    cursor = db.cursor()

    try:
        for setting_name, setting_value in data.items():
            cursor.execute(
                "SELECT 1 FROM Settings WHERE setting_name = ?",
                (setting_name,)
            )
            exists = cursor.fetchone()

            if exists:
                cursor.execute(
                    "UPDATE Settings SET setting_value = ? WHERE setting_name = ?",
                    (setting_value, setting_name)
                )
            else:
                cursor.execute(
                    "INSERT INTO Settings (setting_name, setting_value) VALUES (?, ?)",
                    (setting_name, setting_value)
                )

        db.commit()

    except Exception as e:
        db.rollback()
        print("DB ERROR:", e)
        return "Internal Server Error", 500

    finally:
        db.close()

    return redirect(url_for("lan"))






@app.route("/net_gsm")
def net_gsm():
    if "username" in session:
        username = session["username"]
        db = create_connection("sepleDB.db")
        cursor = db.cursor()
        cursor.execute("SELECT * FROM users WHERE username=?", (username,))
        user_data = cursor.fetchone()
        cursor.close()
        db.cursor()

        db3 = create_connection("dexterpanel2.db")
        cursor3 = db3.cursor()
        cursor3.execute("SELECT * FROM systemLogs ")
        logss_data = cursor3.fetchall()
        cursor3.close()
        db3.close()
        return render_template("net_Gsm.html", logg=logss_data, user=user_data)
    return redirect(url_for("login"))


@app.route("/get_gsm")
def get_gsm():
    if "username" in session:
        db = create_connection(db_file)
        if db:
            cursor = db.cursor()
            cursor.execute("SELECT * FROM gsm")
            gsm_data = cursor.fetchall()
            cursor.close()
            db.close()
            return jsonify(gsm_data)
        else:
            return jsonify({"data": "error"})


@app.route("/netdata_gsm", methods=["PUT"])
def netdata_gsm():
    if request.method == "PUT":
        data = request.json
        gsm_activated = data.get("gsm_activated")
        db = create_connection(db_file)
        if db:
            cursor = db.cursor()
            cursor.execute("SELECT * FROM gsm WHERE ID=1")
            existing = cursor.fetchall()
            if existing:
                cursor.execute(
                    "UPDATE gsm SET gsm_activated=? WHERE ID=1", (gsm_activated,)
                )
            else:
                cursor.execute(
                    "INSERT INTO gsm (gsm_activated) VALUES (?)", (gsm_activated,)
                )
            db.commit()
            cursor.close()
            db.close()
        return {"data": "send"}


@app.route("/come_soon")
def come_soon():
    if "username" in session:
        username = session["username"]
        db = create_connection("sepleDB.db")
        cursor = db.cursor()
        cursor.execute("SELECT * FROM users WHERE username=?", (username,))
        user = cursor.fetchone()
        cursor.close()
        db.close()

        db3 = create_connection("dexterpanel2.db")
        cursor3 = db3.cursor()
        cursor3.execute("SELECT * FROM systemLogs ")
        logss_data = cursor3.fetchall()
        cursor3.close()
        db3.close()

        return render_template("coming_soon.html", logg=logss_data, user=user)
    return redirect(url_for("login"))


@app.route("/logout")
def logout():
    session.pop("username", None)
    return redirect(url_for("login"))


@app.route("/connection")
def connection():
    if "username" in session:

        username = session["username"]
        db = create_connection("sepleDB.db")
        db2 = create_connection("/home/pi/Test3/modem_config.db")
        cursor = db2.cursor()
        cursor.execute("SELECT * FROM modem_parameters")
        data = cursor.fetchall()
        cursor2 = db.cursor()
        cursor2.execute("SELECT * FROM users WHERE username=?", (username,))
        user_data = cursor2.fetchone()
        cursor.close()
        db.close()

        db3 = create_connection("dexterpanel2.db")
        cursor3 = db3.cursor()
        cursor3.execute("SELECT * FROM systemLogs ")
        logss_data = cursor3.fetchall()
        cursor3.close()
        db3.close()
        return render_template(
            "Connection.html", data=data, logg=logss_data, user=user_data
        )
    return redirect(url_for("login"))


@app.route("/acces_token", methods=["POST"])
def acces_token():
    if request.method == "POST":
        access_token = request.form["access_token"]
        db = create_connection("/home/pi/Test3/modem_config.db")
        if db:
            cursor = db.cursor()
            cursor.execute("SELECT * FROM modem_parameters WHERE id=1")
            existing = cursor.fetchall()
            if existing:
                cursor.execute(
                    "UPDATE modem_parameters SET access_token=? WHERE id=1",
                    (access_token,),
                )
            else:

                cursor.execute(
                    "INSERT INTO modem_parameters (access_token) VALUES (?)",
                    (access_token,),
                )
            db.commit()
            cursor.close()
            db.close()
    return redirect(url_for("connection"))


@app.route("/x509", methods=["POST"])
def x509():
    if request.method == "POST":
        x509 = request.form.get("x509")
        db = create_connection("/home/pi/Test3/modem_config.db")
        if db:
            cursor = db.cursor()
            cursor.execute("SELECT * FROM modem_parameters WHERE id=1")
            existing = cursor.fetchall()
            if existing:
                cursor.execute("UPDATE modem_parameters SET x509=? WHERE id=1", (x509,))
            else:

                cursor.execute(
                    "INSERT INTO modem_parameters (x509) VALUES (?)", (x509,)
                )
            db.commit()
            cursor.close()
            db.close()
    return redirect(url_for("connection"))


@app.route("/mqtt_basic", methods=["POST"])
def mqtt_basic():

    if request.method == "POST":

        clintId = request.form.get("client_id")
        username = request.form.get("user_name")
        password = request.form.get("password")

        db = create_connection("/home/pi/Test3/modem_config.db")
        if db:
            cursor = db.cursor()
            cursor.execute("SELECT * FROM modem_parameters WHERE id=1")
            existing = cursor.fetchall()
            if existing:
                cursor.execute(
                    "UPDATE modem_parameters SET client_id=?,user_name=?,password=?  WHERE id=1",
                    (clintId, username, password),
                )
            else:
                cursor.execute(
                    "INSERT INTO modem_parameters (client_id, user_name, password) VALUES (?,?,?)",
                    (clintId, username, password),
                )
            db.commit()
            cursor.close()
            db.close()
    return redirect(url_for("connection"))


@app.route("/SOL")
def SOL():
    if "username" in session:
        username = session["username"]
        db = create_connection("sepleDB.db")
        cursor = db.cursor()
        cursor.execute("SELECT * FROM users WHERE username=?", (username,))
        user_data = cursor.fetchone()
        cursor.close()
        db.cursor()

        db2 = create_connection("dexterpanel2.db")
        cursor2 = db2.cursor()
        cursor2.execute("SELECT * FROM systemLogs ")
        logss_data = cursor2.fetchall()
        cursor2.close()
        db2.close()

        db3 = create_connection("sepleDB.db")
        cursor3 = db3.cursor()
        cursor3.execute("SELECT * FROM provision ")
        data = cursor3.fetchall()
        cursor3.close()
        db3.close()

        return render_template(
            "sol_id.html", user=user_data, data=data, logg=logss_data
        )
    return redirect(url_for("login"))


@app.route("/provision", methods=["GET", "POST"])
def provision():
    if "username" not in session:
        return redirect(url_for("login"))
    
    # Check if user has access to Device Provisioning
    if not check_user_access("provision"):
        return render_template("index.html", alert_userpass=True, access_denied=True)

    try:
        # Here we need to add the logic to provision the device
        db3 = create_connection("dexterpanel2.db")
        if db3:
            cursor3 = db3.cursor()
            log_message = "Device provisioning initiated"
            cursor3.execute(
                "INSERT INTO systemLogs (date, message) VALUES (datetime('now', 'localtime'), ?)",
                (log_message,),
            )
            db3.commit()
            cursor3.close()
            db3.close()
    except:
        pass

    # Get user data
    db = create_connection("sepleDB.db")
    cursor = db.cursor()
    cursor.execute("SELECT * FROM users WHERE username=?", (session["username"],))
    user = cursor.fetchone()
    cursor.close()
    db.close()

    # Get system logs
    db3 = create_connection("dexterpanel2.db")
    cursor3 = db3.cursor()
    cursor3.execute("SELECT * FROM systemLogs ")
    logss_data = cursor3.fetchall()
    cursor3.close()
    db3.close()

    return render_template("provisioning.html", logg=logss_data, user=user)


@app.route("/setprovisiondevice", methods=["POST"])
def setprovisiondevice():
    try:
        data = device_provisioning()
    except Exception as e:
        # flash("Provisioning faild due to error: "+str(e))
        return jsonify({"status":"error", "message":"Device Provisioning failed, Please try again"})
    
    if data == "success":
        # flash("Device provisioned successfully!")
        return jsonify({"status":"success", "message":"Device Provisioning successfully! "})
    else:
        # flash("Device provisioning failed. Please try again.")
        return jsonify({"status":"error", "message":"Device Provisioning failed, Please try again"})


@app.route("/send_data", methods=["GET", "POST"])
def sendData(): 
    if request.method == "POST":
        deviceName = request.form["deviceName"]
        id = request.form["id"]
        userName = request.form["userName"]
        password = request.form["password"]

        db = create_connection(db_file)
        if db:
            cursor = db.cursor()
            cursor.execute("SELECT * FROM provision")
            existing = cursor.fetchall()
            if existing:
                cursor.execute(
                    "UPDATE provision SET E_deviceName=?, E_id=?,E_userName=?,E_passWord=?",
                    (deviceName, id, userName, password),
                )
            else:
                cursor.execute(
                    "INSERT INTO provision (E_deviceName, E_id,E_userName,E_passWord) VALUES(?,?,?,?)",
                    (deviceName, id, userName, password),
                )
            db.commit()
            cursor.close()
            db.close()
    return redirect(url_for("provision"))
    # return ({"data":"send"})


@app.route("/send_data2", methods=["GET", "POST"])
def sendData2():
    if request.method == "POST":
        ethernetDeviceName = request.form["ethernetDeviceName"]

        db = create_connection(db_file)
        if db:
            cursor = db.cursor()
            cursor.execute("SELECT * FROM provision")
            existing = cursor.fetchall()
            if existing:
                cursor.execute(
                    "UPDATE provision SET etn_deviceName=?", (ethernetDeviceName,)
                )
            else:
                cursor.execute(
                    "INSERT INTO provision (etn_deviceName) VALUES(?)",
                    (ethernetDeviceName,),
                )
            db.commit()
            cursor.close()
            db.close()
    return redirect(url_for("provision"))
    # return ({"data":"send"})


@app.route("/output_controls")
def output_controls():
    if "username" in session:
        username = session["username"]
        db = create_connection("sepleDB.db")
        cursor = db.cursor()
        cursor.execute("SELECT * FROM users WHERE username=?", (username,))
        user = cursor.fetchone()
        cursor.close()
        db.close()

        db3 = create_connection("dexterpanel2.db")
        cursor3 = db3.cursor()
        cursor3.execute("SELECT * FROM systemLogs ")
        logss_data = cursor3.fetchall()
        cursor3.close()
        db3.close()

        return render_template("output_controls.html", logg=logss_data, user=user)
    return redirect(url_for("login"))

def _docker_action(containers, start: bool):
    """Start or stop a list of Docker containers via the mounted socket.

    Stop path: set restart policy to 'no' BEFORE stopping so that
    on-failure policy does not immediately relaunch the container after
    the SIGKILL (exit 137) that docker stop sends.
    Start path: restore restart policy to 'on-failure' so the container
    auto-recovers from crashes while the integration is active.
    """
    try:
        import docker as _docker_sdk
        client = _docker_sdk.from_env()
        action = "start" if start else "stop"
        for name in containers:
            try:
                c = client.containers.get(name)
                if start:
                    c.update(restart_policy={"Name": "on-failure", "MaximumRetryCount": 0})
                    c.start()
                else:
                    c.update(restart_policy={"Name": "no"})
                    c.stop(timeout=10)
            except _docker_sdk.errors.NotFound:
                app.logger.warning("[docker_action] container %s not found", name)
            except Exception as exc:
                app.logger.warning("[docker_action] %s %s failed: %s", action, name, exc)
    except Exception as exc:
        app.logger.warning("[docker_action] cannot connect to Docker daemon: %s", exc)


@app.route("/get_activeIntegration")
def get_activeIntegration():
    if "username" in session:
        db = create_connection("/home/pi/Test3/active_integration.db")
        if db:
            cursor = db.cursor()
            cursor.execute("SELECT * FROM active_integration_external_device")
            ac_data = cursor.fetchall()
            cursor.close()
            db.close()
            return jsonify(ac_data)
        else:
            return jsonify({"data": "error"})


@app.route("/data_active_integration", methods=["PUT"])
def data_active_integration():
    if request.method == "PUT":
        data = request.json
        active_integration_external = data.get("active_integration_external_device")
        # Convert JS boolean true/false to DB integer 0/1
        val = 1 if active_integration_external in (True, 1, "1", "true", "True") else 0
        db = create_connection("/home/pi/Test3/active_integration.db")
        if db:
            cursor = db.cursor()
            cursor.execute(
                "SELECT * FROM active_integration_external_device WHERE ID=1"
            )
            existing = cursor.fetchall()
            if existing:
                cursor.execute(
                    "UPDATE active_integration_external_device SET active_integration_on_off_bit=? WHERE ID=1",
                    (val,),
                )
            else:
                cursor.execute(
                    "INSERT INTO active_integration_external_device (active_integration_on_off_bit) VALUES (?)",
                    (val,),
                )
            db.commit()
            cursor.close()
            db.close()
        return {"data": "send"}

@app.route("/get_active_integration_hikvidion")
def get_active_integration_hikvidion():
    if "username" in session:
        db = create_connection("/home/pi/Test3/logical_params_active_integration.db")
        if db:
            cursor = db.cursor()
            cursor.execute("SELECT * FROM parameters WHERE name='active_integration_hikvision_nvr'")
            ac_data = cursor.fetchall()
            cursor.close()
            db.close()
            return jsonify(ac_data)
        else:
            return jsonify({"data": "error"})


@app.route("/data_active_integration_hikvidion", methods=["PUT"])
def data_active_integration_hikvidion():
    if request.method == "PUT":
        data = request.json
        active_integration_external_hk = data.get("active_integration_hikvision")
        # Convert JS boolean to DB integer
        active_integration_external_hk = 1 if active_integration_external_hk in (True, 1, "1", "true", "True") else 0
        db = create_connection("/home/pi/Test3/logical_params_active_integration.db")
        if db:
            cursor = db.cursor()
            cursor.execute("SELECT * FROM parameters WHERE name='active_integration_hikvision_nvr'")
            existing = cursor.fetchall()
            if existing:
                cursor.execute(
                    "UPDATE parameters SET value=? WHERE name='active_integration_hikvision_nvr'",
                    (active_integration_external_hk,),
                )
            else:
                cursor.execute(
                    "INSERT OR REPLACE INTO parameters (name, value) VALUES ('active_integration_hikvision_nvr', ?)",
                    (active_integration_external_hk,),
                )
            db.commit()
            cursor.close()
            db.close()
        _docker_action(
            ["dexter-nvr-hikvision", "dexter-nvr-hikvision-field",
             "dexter-nvr-hik-lite", "dexter-rtc-hikvision", "dexter-sd-hikvision"],
            start=bool(int(active_integration_external_hk))
        )
        return {"data": "send"}


@app.route("/get_active_integration_ac")
def get_active_integration_ac():
    if "username" in session:
        db = create_connection("/home/pi/Test3/logical_params_active_integration.db")
        if db:
            cursor = db.cursor()
            cursor.execute("SELECT * FROM parameters WHERE name='active_integration_hikvision_biometric'")
            ac_data = cursor.fetchall()
            cursor.close()
            db.close()
            return jsonify(ac_data)
        else:
            return jsonify({"data": "error"})
        

@app.route("/data_active_integration_ac", methods=["PUT"])
def data_active_integration_ac():
    if request.method == "PUT":
        data = request.json
        active_integration_external_ac = data.get("active_integration_ac")
        # Convert JS boolean to DB integer
        active_integration_external_ac = 1 if active_integration_external_ac in (True, 1, "1", "true", "True") else 0
        db = create_connection("/home/pi/Test3/logical_params_active_integration.db")
        if db:
            cursor = db.cursor()
            cursor.execute("SELECT * FROM parameters WHERE name='active_integration_hikvision_biometric'")
            existing = cursor.fetchall()
            if existing:
                cursor.execute(
                    "UPDATE parameters SET value=? WHERE name='active_integration_hikvision_biometric'",
                    (active_integration_external_ac,),
                )
            else:
                cursor.execute(
                    "INSERT OR REPLACE INTO parameters (name, value) VALUES ('active_integration_hikvision_biometric', ?)",
                    (active_integration_external_ac,),
                )
            db.commit()
            cursor.close()
            db.close()
        _docker_action(["dexter-nvr-hikvision-bacs"], start=bool(int(active_integration_external_ac)))
        return {"data": "send"}


@app.route("/get_active_integration_dh")
def get_active_integration_dh():
    if "username" in session:
        db = create_connection("/home/pi/Test3/logical_params_active_integration.db")
        if db:
            cursor = db.cursor()
            cursor.execute("SELECT * FROM parameters WHERE name='active_integration_dahua_nvr'")
            ac_data = cursor.fetchall()
            cursor.close()
            db.close()
            return jsonify(ac_data)
        else:
            return jsonify({"data": "error"})
        

@app.route("/data_active_integration_dh", methods=["PUT"])
def data_active_integration_dh():
    if request.method == "PUT":
        data = request.json
        active_integration_external_dh = data.get("active_integration_dh")
        # Convert JS boolean to DB integer
        active_integration_external_dh = 1 if active_integration_external_dh in (True, 1, "1", "true", "True") else 0
        db = create_connection("/home/pi/Test3/logical_params_active_integration.db")
        if db:
            cursor = db.cursor()
            cursor.execute("SELECT * FROM parameters WHERE name='active_integration_dahua_nvr'")
            existing = cursor.fetchall()
            if existing:
                cursor.execute(
                    "UPDATE parameters SET value=? WHERE name='active_integration_dahua_nvr'",
                    (active_integration_external_dh,),
                )
            else:
                cursor.execute(
                    "INSERT OR REPLACE INTO parameters (name, value) VALUES ('active_integration_dahua_nvr', ?)",
                    (active_integration_external_dh,),
                )
            db.commit()
            cursor.close()
            db.close()
        _docker_action(
            ["dexter-nvr-dahua", "dexter-extract-dahua", "dexter-sd-dahua",
             "dexter-rtc-dahua", "dexter-rec-dahua"],
            start=bool(int(active_integration_external_dh))
        )
        return {"data": "send"}


# CP PLUS NVR Routes
@app.route("/get_active_integration_cp")
def get_active_integration_cp():
    if "username" in session:
        db = create_connection("/home/pi/Test3/logical_params_active_integration.db")
        if db:
            cursor = db.cursor()
            cursor.execute("SELECT * FROM parameters WHERE name='active_integration_cp_plus_nvr'")
            ac_data = cursor.fetchall()
            cursor.close()
            db.close()
            return jsonify(ac_data)
        else:
            return jsonify({"data": "error"})
        

@app.route("/data_active_integration_cp", methods=["PUT"])
def data_active_integration_cp():
    if request.method == "PUT":
        data = request.json
        active_integration_external_cp = data.get("active_integration_cp")
        # Convert JS boolean to DB integer
        active_integration_external_cp = 1 if active_integration_external_cp in (True, 1, "1", "true", "True") else 0
        db = create_connection("/home/pi/Test3/logical_params_active_integration.db")
        if db:
            cursor = db.cursor()
            cursor.execute("SELECT * FROM parameters WHERE name='active_integration_cp_plus_nvr'")
            existing = cursor.fetchall()
            if existing:
                cursor.execute(
                    "UPDATE parameters SET value=? WHERE name='active_integration_cp_plus_nvr'",
                    (active_integration_external_cp,),
                )
            else:
                cursor.execute(
                    "INSERT OR REPLACE INTO parameters (name, value) VALUES ('active_integration_cp_plus_nvr', ?)",
                    (active_integration_external_cp,),
                )
            db.commit()
            cursor.close()
            db.close()
        _docker_action(
            ["dexter-nvr-cpplus", "dexter-extract-cpplus", "dexter-sd-cpplus",
             "dexter-rtc-cpplus", "dexter-rec-cpplus"],
            start=bool(int(active_integration_external_cp))
        )
        return {"data": "send"}


# SPARS NVR Routes
@app.route("/get_active_integration_sp")
def get_active_integration_sp():
    if "username" in session:
        db = create_connection("/home/pi/Test3/logical_params_active_integration.db")
        if db:
            cursor = db.cursor()
            cursor.execute("SELECT * FROM parameters WHERE name='active_integration_sparsh_nvr'")
            ac_data = cursor.fetchall()
            cursor.close()
            db.close()
            return jsonify(ac_data)
        else:
            return jsonify({"data": "error"})


# ── HIKVISION BAS (Burglar Alarm Panel) ──────────────────────────────────────
@app.route("/get_active_integration_hik_bas")
def get_active_integration_hik_bas():
    if "username" in session:
        db = create_connection("/home/pi/Test3/logical_params_active_integration.db")
        if db:
            cursor = db.cursor()
            cursor.execute("SELECT * FROM parameters WHERE name='active_integration_hik_bas'")
            ac_data = cursor.fetchall()
            cursor.close()
            db.close()
            return jsonify(ac_data)
        return jsonify({"data": "error"})
    return jsonify({"data": "error"})


@app.route("/data_active_integration_hik_bas", methods=["PUT"])
def data_active_integration_hik_bas():
    if request.method == "PUT":
        data = request.json
        val  = data.get("active_integration_hik_bas")
        val  = 1 if val in (True, 1, "1", "true", "True") else 0
        val  = 1 if val in (True, 1, "1", "true", "True") else 0
        db   = create_connection("/home/pi/Test3/logical_params_active_integration.db")
        if db:
            cursor = db.cursor()
            cursor.execute("SELECT * FROM parameters WHERE name='active_integration_hik_bas'")
            existing = cursor.fetchall()
            if existing:
                cursor.execute(
                    "UPDATE parameters SET value=? WHERE name='active_integration_hik_bas'",
                    (val,),
                )
            else:
                cursor.execute(
                    "INSERT INTO parameters (name, value) VALUES ('active_integration_hik_bas', ?)",
                    (val,),
                )
            db.commit()
            cursor.close()
            db.close()
        _docker_action(["dexter-hik-bas", "dexter-rtc-hik-bas"], start=bool(int(val)))
        return {"data": "send"}


# ── AMC BAS ──────────────────────────────────────────────────────────────────
@app.route("/get_active_integration_amc_bas")
def get_active_integration_amc_bas():
    if "username" in session:
        db = create_connection("/home/pi/Test3/logical_params_active_integration.db")
        if db:
            cursor = db.cursor()
            cursor.execute("SELECT * FROM parameters WHERE name='active_integration_amc_bas'")
            ac_data = cursor.fetchall()
            cursor.close()
            db.close()
            return jsonify(ac_data)
        return jsonify({"data": "error"})
    return jsonify({"data": "error"})


@app.route("/data_active_integration_amc_bas", methods=["PUT"])
def data_active_integration_amc_bas():
    if request.method == "PUT":
        data = request.json
        val  = data.get("active_integration_amc_bas")
        val  = 1 if val in (True, 1, "1", "true", "True") else 0
        val  = 1 if val in (True, 1, "1", "true", "True") else 0
        db   = create_connection("/home/pi/Test3/logical_params_active_integration.db")
        if db:
            cursor = db.cursor()
            cursor.execute("SELECT * FROM parameters WHERE name='active_integration_amc_bas'")
            existing = cursor.fetchall()
            if existing:
                cursor.execute(
                    "UPDATE parameters SET value=? WHERE name='active_integration_amc_bas'",
                    (val,),
                )
            else:
                cursor.execute(
                    "INSERT INTO parameters (name, value) VALUES ('active_integration_amc_bas', ?)",
                    (val,),
                )
            db.commit()
            cursor.close()
            db.close()
        _docker_action(["dexter-amc"], start=bool(int(val)))
        return {"data": "send"}


# ── TEXECOM BAS ───────────────────────────────────────────────────────────────
@app.route("/get_active_integration_texecom_bas")
def get_active_integration_texecom_bas():
    if "username" in session:
        db = create_connection("/home/pi/Test3/logical_params_active_integration.db")
        if db:
            cursor = db.cursor()
            cursor.execute("SELECT * FROM parameters WHERE name='active_integration_texecom_bas'")
            ac_data = cursor.fetchall()
            cursor.close()
            db.close()
            return jsonify(ac_data)
        return jsonify({"data": "error"})
    return jsonify({"data": "error"})


@app.route("/data_active_integration_texecom_bas", methods=["PUT"])
def data_active_integration_texecom_bas():
    if request.method == "PUT":
        data = request.json
        val  = data.get("active_integration_texecom_bas")
        val  = 1 if val in (True, 1, "1", "true", "True") else 0
        val  = 1 if val in (True, 1, "1", "true", "True") else 0
        db   = create_connection("/home/pi/Test3/logical_params_active_integration.db")
        if db:
            cursor = db.cursor()
            cursor.execute("SELECT * FROM parameters WHERE name='active_integration_texecom_bas'")
            existing = cursor.fetchall()
            if existing:
                cursor.execute(
                    "UPDATE parameters SET value=? WHERE name='active_integration_texecom_bas'",
                    (val,),
                )
            else:
                cursor.execute(
                    "INSERT INTO parameters (name, value) VALUES ('active_integration_texecom_bas', ?)",
                    (val,),
                )
            db.commit()
            cursor.close()
            db.close()
        _docker_action(["dexter-texecom-bas"], start=bool(int(val)))
        return {"data": "send"}




@app.route("/data_active_integration_sp", methods=["PUT"])
def data_active_integration_sp():
    if request.method == "PUT":
        data = request.json
        active_integration_external_sp = data.get("active_integration_sp")
        # Convert JS boolean to DB integer
        active_integration_external_sp = 1 if active_integration_external_sp in (True, 1, "1", "true", "True") else 0
        db = create_connection("/home/pi/Test3/logical_params_active_integration.db")
        if db:
            cursor = db.cursor()
            cursor.execute("SELECT * FROM parameters WHERE name='active_integration_sparsh_nvr'")
            existing = cursor.fetchall()
            if existing:
                cursor.execute(
                    "UPDATE parameters SET value=? WHERE name='active_integration_sparsh_nvr'",
                    (active_integration_external_sp,),
                )
            else:
                cursor.execute(
                    "INSERT OR REPLACE INTO parameters (name, value) VALUES ('active_integration_sparsh_nvr', ?)",
                    (active_integration_external_sp,),
                )
            db.commit()
            cursor.close()
            db.close()
        return {"data": "send"}


@app.route("/device_management")
def device_management():
    if "username" in session:
        username = session["username"]
        db = create_connection("sepleDB.db")
        cursor = db.cursor()
        cursor.execute("SELECT * FROM users WHERE username=?", (username,))
        user = cursor.fetchone()
        cursor.close()
        db.close()

        db3 = create_connection("dexterpanel2.db")
        cursor3 = db3.cursor()
        cursor3.execute("SELECT * FROM systemLogs ")
        logss_data = cursor3.fetchall()
        cursor3.close()
        db3.close()

        return render_template("deviceManagement.html", logg=logss_data, user=user)
    return redirect(url_for("login"))


@app.route("/protocol_config")
def protocol_config():
    if "username" in session:
        username = session["username"]
        db = create_connection("sepleDB.db")
        cursor = db.cursor()
        cursor.execute("SELECT * FROM users WHERE username=?", (username,))
        user = cursor.fetchone()
        cursor.close()
        db.close()

        db3 = create_connection("dexterpanel2.db")
        cursor3 = db3.cursor()
        cursor3.execute("SELECT * FROM systemLogs ")
        logss_data = cursor3.fetchall()
        cursor3.close()
        db3.close()

        return render_template("protocol_config.html", logg=logss_data, user=user)
    return redirect(url_for("login"))


@app.route("/OTA")
def OTA():
    if "username" in session:
        username = session["username"]
        db = create_connection("sepleDB.db")
        cursor = db.cursor()
        cursor.execute("SELECT * FROM users WHERE username=?", (username,))
        user = cursor.fetchone()
        cursor.close()
        db.close()

        db3 = create_connection("dexterpanel2.db")
        cursor3 = db3.cursor()
        cursor3.execute("SELECT * FROM systemLogs ")
        logss_data = cursor3.fetchall()
        cursor3.close()
        db3.close()

        return render_template("ota.html", logg=logss_data, user=user)
    return redirect(url_for("login"))


@app.route("/device_credential")
def device_credential():
    if "username" in session:
        # Check if user has access to Device Credentials
        if not check_user_access("device_credential"):
            return render_template("index.html", alert_userpass=True, access_denied=True)
        username = session["username"]
        db = create_connection("sepleDB.db")
        cursor = db.cursor()
        cursor.execute("SELECT * FROM users WHERE username=?", (username,))
        user = cursor.fetchone()


        db2 = create_connection("/home/pi/Test3/modem_config.db")
        cursor2 = db2.cursor()
        cursor2.execute("SELECT * FROM modem_parameters")
        mparameters = cursor2.fetchall()
        print(mparameters)
        # FIX-BUG04: Credentials are Fernet-encrypted in DB.
        # Decrypt before passing to template so page shows real values.
        try:
            sys.path.insert(0, "/home/pi/Test3")
            from secrets_manager import decrypt_value as _dec_v
        except Exception:
            def _dec_v(v): return v

        def _safe_dec(v):
            try:
                return _dec_v(v) if v else v
            except Exception:
                return v

        mpdata = {
            "accessToken": _safe_dec(mparameters[0][1]),
            "clintId"    : _safe_dec(mparameters[0][2]),
            "userName"   : _safe_dec(mparameters[0][3]),
            "Pass"       : _safe_dec(mparameters[0][4]),
            "dvName"     : mparameters[0][7]
        }

        

        # Get system logs
        db3 = create_connection("dexterpanel2.db")
        cursor3 = db3.cursor()
        cursor3.execute("SELECT * FROM systemLogs ")
        logss_data = cursor3.fetchall()
        cursor3.close()
        db3.close()

        # Get success/error messages from query parameters if they exist
        success_message = request.args.get("success_message")
        error_message = request.args.get("error_message")

        return render_template(
            "deviceCredential.html",
            logg=logss_data,
            user=user,
            mpdata=mpdata,
            success_message=success_message,
            error_message=error_message,
        )
    return redirect(url_for("login"))


@app.route("/device_credentials", methods=["POST"])
def save_device_credentials():

    if "username" not in session:
        return redirect(url_for("login"))

    referrer = request.referrer or ""

    redirect_target = (
        "quick_settings" if "quick_setting" in referrer else "device_credential"
    )

    try:
        sol = request.form.get("solId")

        if sol:
            access_token = request.form.get("access_token")
            client_id = request.form.get("clientId")
            username = request.form.get("user_name")
            password = request.form.get("password")
            device_name = sol

            db = create_connection("/home/pi/Test3/modem_config.db")
            if not db:
                return redirect(url_for(redirect_target))

            # FIX-BUG01: Encrypt credentials before writing.
            # SerialCommunication.py and TLChronosProMAIN read these fields
            # using decrypt_value(). Plaintext values cause decryption failure.
            try:
                sys.path.insert(0, "/home/pi/Test3")
                from secrets_manager import encrypt_value as _enc
            except Exception:
                def _enc(v): return v  # fallback: no encryption

            enc_access_token = _enc(access_token) if access_token else access_token
            enc_client_id    = _enc(client_id)    if client_id    else client_id
            enc_username     = _enc(username)      if username     else username
            enc_password     = _enc(password)      if password     else password

            cursor = db.cursor()
            try:
                # FIX-BUG02: Don't recreate table with only 8 columns.
                # Use ADD COLUMN to extend existing schema safely.
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS modem_parameters (
                        id INTEGER PRIMARY KEY,
                        access_token TEXT,
                        client_id TEXT,
                        user_name TEXT,
                        password TEXT,
                        gsm_modem_mode TEXT,
                        network_type TEXT,
                        device_name TEXT
                    )
                """)
                # Ensure all required columns exist (safe if already present)
                for col_def in [
                    "swatch_host TEXT",
                    "swatch_username TEXT",
                    "swatch_password TEXT",
                ]:
                    try:
                        cursor.execute(f"ALTER TABLE modem_parameters ADD COLUMN {col_def}")
                    except Exception:
                        pass  # Column already exists

                cursor.execute("SELECT * FROM modem_parameters WHERE id=1")
                existing = cursor.fetchone()

                _sim_mode = "esim"  # safe default
                try:
                    _cavli_conn = create_connection("/home/pi/Test3/cavliRunningParam.db")
                    if _cavli_conn:
                        _sim_row = _cavli_conn.execute(
                            "SELECT simSwap FROM cavliRunningParam WHERE id=1"
                        ).fetchone()
                        _cavli_conn.close()
                        if _sim_row and _sim_row[0] in ("esim", "physical"):
                            _sim_mode = _sim_row[0]
                except Exception as _se:
                    app.logger.warning("sim_swap read failed: %s — using default 'esim'", _se)

                if existing:
                    cursor.execute("""
                        UPDATE modem_parameters
                        SET access_token=?, client_id=?, user_name=?, password=?,
                            gsm_modem_mode=?, network_type=?, device_name=?
                        WHERE id=1
                    """, (
                        enc_access_token,
                        enc_client_id,
                        enc_username,
                        enc_password,
                        _sim_mode,
                        "gsm",
                        device_name,
                    ))
                else:
                    cursor.execute("""
                        INSERT INTO modem_parameters
                        VALUES (1, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        enc_access_token,
                        enc_client_id,
                        enc_username,
                        enc_password,
                        _sim_mode,
                        "gsm",
                        device_name,
                    ))

                db.commit()

            finally:
                cursor.close()
                db.close()

        # Redirect back
        return redirect(url_for(redirect_target))

    except Exception as e:
        app.logger.error("save_device_credentials error: %s", e)
        return redirect(url_for(redirect_target))



@app.route("/dhcp", methods=["POST"])
def dhcp():
    resetDHCP()
    # Persist mode so GET route and Configure_Network_7 see the correct value
    try:
        _db = create_connection("/home/pi/Test3/network_settings.db")
        if _db:
            for _key, _val in [
                ("Enable/Disable Static/dynamic", "dynamic"),
                ("network_mode", "dynamic"),
            ]:
                _row = _db.execute(
                    "SELECT 1 FROM Settings WHERE setting_name=?", (_key,)
                ).fetchone()
                if _row:
                    _db.execute(
                        "UPDATE Settings SET setting_value=? WHERE setting_name=?",
                        (_val, _key)
                    )
                else:
                    _db.execute(
                        "INSERT INTO Settings (setting_name, setting_value) VALUES (?,?)",
                        (_key, _val)
                    )
            _db.commit()
            _db.close()
    except Exception as _e:
        app.logger.warning("DHCP mode save error: %s", _e)
    reboot_rpi()
    return jsonify({"status": "success", "message": "Switched to DHCP. Device will reboot in a few seconds."})


@app.route("/integration_settings")
def integration_settings():
    if "username" not in session:
        return redirect(url_for("login"))

    username = session["username"]

    # ---------- USER ----------
    db_user = create_connection("sepleDB.db")
    cursor_user = db_user.cursor()
    cursor_user.execute("SELECT * FROM users WHERE username=?", (username,))
    user = cursor_user.fetchone()
    cursor_user.close()
    db_user.close()

    # ---------- DEVICE CONFIG ----------
    db = create_connection("/home/pi/Test3/device_config.db")
    cursor = db.cursor()

    # Safe defaults (VERY IMPORTANT)
    hikvision_nvr_data = {"camera_ip": []}
    hikvision_bacs_data = {"camera_ip": []}
    dahua_nvr_data = {"camera_ip": []}
    cpplus_nvr_data = {"camera_ip": []}
    spars_nvr_data = {"camera_ip": []}

    def load_device(device_type):
        try:
            cursor.execute(
                "SELECT ip_address, username, password, port, camera_ip FROM device_parameters WHERE device_type=?",
                (device_type,)
            )
            result = cursor.fetchone()

            if not result:
                return {"camera_ip": []}

            camera_ip = result[4]
            if camera_ip is None:
                camera_ip = []
            elif isinstance(camera_ip, str):
                try:
                    camera_ip = json.loads(camera_ip)
                    if not isinstance(camera_ip, list):
                        camera_ip = []
                except json.JSONDecodeError:
                    camera_ip = []

            raw_pwd = result[2] or ""
            try:
                from secrets_manager import decrypt_value as _dec_v
                plain_pwd = _dec_v(raw_pwd) if raw_pwd else ""
            except Exception:
                plain_pwd = raw_pwd  # fallback: plaintext (legacy row)

            return {
                "ip_address": result[0],
                "username": result[1],
                "password": plain_pwd,
                "port_number": result[3],
                "camera_ip": camera_ip
            }
        except Exception as e:
            print(f"{device_type} ERROR:", e)
            return {"camera_ip": []}

    # ---------- LOAD ALL DEVICES ----------
    hikvision_nvr_data   = load_device("HikvisionNVR1")
    hikvision_bacs_data  = load_device("HikvisionBioMetric1")
    dahua_nvr_data       = load_device("DahuaNVR1")
    cpplus_nvr_data      = load_device("CP_PlusNVR1")
    spars_nvr_data       = load_device("SparshNVR1")  # ✅ FIXED
    hik_bas_data         = load_device("HikvisionBAS1")
    texecom_bas_data     = load_device("TexecomBAS1")

    cursor.close()
    db.close()

    # ---------- SYSTEM LOGS ----------
    db_logs = create_connection("dexterpanel2.db")
    cursor_logs = db_logs.cursor()
    cursor_logs.execute("SELECT * FROM systemLogs")
    logss_data = cursor_logs.fetchall()
    cursor_logs.close()
    db_logs.close()

    # ---------- RENDER ----------
    return render_template(
        "integrationSettings.html",
        user=user,
        logg=logss_data,

        hikvision_nvr_data=hikvision_nvr_data,
        hikvision_bacs_data=hikvision_bacs_data,
        dahua_nvr_data=dahua_nvr_data,
        cpplus_nvr_data=cpplus_nvr_data,
        spars_nvr_data=spars_nvr_data,
        hik_bas_data=hik_bas_data,
        texecom_bas_data=texecom_bas_data,

        c1=json.dumps(hikvision_nvr_data["camera_ip"]),
        c2=json.dumps(hikvision_bacs_data["camera_ip"]),
        c3=json.dumps(dahua_nvr_data["camera_ip"]),
        c4=json.dumps(cpplus_nvr_data["camera_ip"]),
        c5=json.dumps(spars_nvr_data["camera_ip"]),
    )

@app.route("/senddata", methods=["POST"])
def sendata():
    data = request.form.to_dict()
    print(data)  # Now this will print the actual key-value pairs
    return jsonify(data)


from flask import request, redirect, url_for, session

@app.route("/save_integration_hiknvr", methods=["POST"])
def save_integration_hiknvr():
    if "username" not in session:
        return redirect(url_for("login"))

    try:
        device_type = request.form.get("device_type_d")
        ip_address = request.form.get("ip_address")
        username = request.form.get("username")
        password = request.form.get("password")
        port_number = request.form.get("port_number")
        camera_ip = request.form.get("cameras_json")

        db = create_connection("/home/pi/Test3/device_config.db")
        if not db:
            return redirect(url_for("integration_settings"))

        cursor = db.cursor()

        try:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS device_parameters(
                    id INTEGER PRIMARY KEY,
                    device_type TEXT NOT NULL,
                    ip_address TEXT NOT NULL,
                    username TEXT NOT NULL,
                    password TEXT,
                    port TEXT,
                    camera_ip JSON
                )
            """)

            cursor.execute(
                "SELECT 1 FROM device_parameters WHERE device_type=?",
                (device_type,)
            )
            existing = cursor.fetchone()

            if existing:
                cursor.execute(
                    """
                    UPDATE device_parameters
                    SET ip_address=?, username=?, password=?, port=?, camera_ip=?
                    WHERE device_type=?
                    """,
                    (ip_address, username, password, port_number, camera_ip, device_type)
                )
            else:
                cursor.execute(
                    """
                    INSERT INTO device_parameters
                    (device_type, ip_address, username, password, port, camera_ip)
                    VALUES (?,?,?,?,?,?)
                    """,
                    (device_type, ip_address, username, password, port_number, camera_ip)
                )

            db.commit()

        finally:
            cursor.close()
            db.close()

    except Exception as e:
        print("Save error:", e)
        return redirect(url_for("integration_settings"))

    # 🔥 SMART REDIRECT BASED ON SOURCE PAGE
    referrer = request.referrer or ""

    if "quick_setting" in referrer:
        return redirect(url_for("quick_settings"))
    elif "integration_setting" in referrer:
        return redirect(url_for("integration_settings"))

    # fallback
    return redirect(url_for("integration_settings"))


#new add on quick setting it's a combination of output management, active integration abnd device credential.
@app.route("/quick_settings")
def quick_settings():
    if "username" not in session:
        return redirect(url_for("login"))

    username = session["username"]

    # ---------------- USER ----------------
    db = create_connection("sepleDB.db")
    cursor = db.cursor()
    cursor.execute("SELECT * FROM users WHERE username=?", (username,))
    user = cursor.fetchone()
    cursor.close()
    db.close()

    # ---------------- LOGS ----------------
    db3 = create_connection("dexterpanel2.db")
    cursor3 = db3.cursor()
    cursor3.execute("SELECT * FROM systemLogs")
    logss_data = cursor3.fetchall()
    cursor3.close()
    db3.close()

    # ---------------- eSIM DATA ----------------
    mpdata = {"clintId": "", "userName": "", "Pass": "", "dvName": ""}
    try:
        db2 = create_connection("/home/pi/Test3/modem_config.db")
        cursor2 = db2.cursor()
        cursor2.execute("SELECT * FROM modem_parameters WHERE id=1")
        m = cursor2.fetchone()
        if m:
            mpdata = {
                "clintId": m[2],
                "userName": m[3],
                "Pass": m[4],
                "dvName": m[7]
            }
        cursor2.close()
        db2.close()
    except:
        pass

    # ---------------- DEVICE INTEGRATIONS ----------------
    def get_device(device_type):
        try:
            db = create_connection("/home/pi/Test3/device_config.db")
            cursor = db.cursor()
            cursor.execute(
                "SELECT ip_address, username, password, port, camera_ip FROM device_parameters WHERE device_type=?",
                (device_type,)
            )
            r = cursor.fetchone()
            cursor.close()
            db.close()

            if r:
                raw = r[4]
                if raw is None:
                    camera_ip = []
                elif isinstance(raw, str):
                    try:
                        camera_ip = json.loads(raw)
                        if not isinstance(camera_ip, list):
                            camera_ip = []
                    except (json.JSONDecodeError, ValueError):
                        camera_ip = []
                else:
                    camera_ip = raw if isinstance(raw, list) else []
                raw_pwd = r[2] or ""
                try:
                    from secrets_manager import decrypt_value as _dec_v
                    plain_pwd = _dec_v(raw_pwd) if raw_pwd else ""
                except Exception:
                    plain_pwd = raw_pwd
                return {
                    "ip_address": r[0],
                    "username": r[1],
                    "password": plain_pwd,
                    "port_number": r[3],
                    "camera_ip": camera_ip
                }
        except:
            pass

        return {
            "ip_address": "",
            "username": "",
            "password": "",
            "port_number": "",
            "camera_ip": []
        }

    hikvision_nvr_data  = get_device("HikvisionNVR1")
    hikvision_bacs_data = get_device("HikvisionBioMetric1")
    dahua_nvr_data      = get_device("DahuaNVR1")
    cpplus_nvr_data     = get_device("CP_PlusNVR1")
    spars_nvr_data      = get_device("SparshNVR1")
    hik_bas_data        = get_device("HikvisionBAS1")
    texecom_bas_data    = get_device("TexecomBAS1")

    # ---------------- CAMERA JSON (JS SAFE) ----------------
    c1 = json.dumps(hikvision_nvr_data["camera_ip"])
    c2 = json.dumps(hikvision_bacs_data["camera_ip"])
    c3 = json.dumps(dahua_nvr_data["camera_ip"])
    c4 = json.dumps(cpplus_nvr_data["camera_ip"])
    c5 = json.dumps(spars_nvr_data["camera_ip"])

    return render_template(
        "quick_settings.html",
        user=user,
        logg=logss_data,
        mpdata=mpdata,
        hikvision_nvr_data=hikvision_nvr_data,
        hikvision_bacs_data=hikvision_bacs_data,
        dahua_nvr_data=dahua_nvr_data,
        cpplus_nvr_data=cpplus_nvr_data,
        spars_nvr_data=spars_nvr_data,
        hik_bas_data=hik_bas_data,
        texecom_bas_data=texecom_bas_data,
        c1=c1, c2=c2, c3=c3, c4=c4, c5=c5
    )

    # =============================================================================
# BACKUP & RESTORE ROUTES
# Backup: GET  /backup_download  → streams dexter_backup.tar.gz to browser
# Restore: POST /backup_restore   → accepts uploaded .tar.gz, extracts it
# =============================================================================



# Files included in every backup
_BACKUP_FILES = [
    #"/etc/dexter/fernet.key", 
    #"/etc/dexter/cred_auth.key",
    "/home/pi/Test3/device_config.db",
    "/home/pi/Test3/modem_config.db",
    "/home/pi/Test3/logical_params_active_integration.db",
    "/home/pi/Test3/network_settings.db",
    "/home/pi/Test3/operator_codes.db",
    "/home/pi/Test3/dexterpanel2.db",
    "/home/pi/Test3/parameters.db",
    "/home/pi/Test3/cavliRunningParam.db",
    "/home/pi/Test3/cavliPositionParameter.db",
    "/home/pi/Test3/nvr_dvr_bacs_integration.db",
    "/home/pi/Test3/active_integration.db",
]


@app.route("/backup_download")
def backup_download():
    """
    Create a backup archive of all site-specific DB and key files,
    then send it directly to the engineer phone as a download.
    Only site_engineer role can access this.
    """
    from flask import send_file
    import io

    if not check_user_access("site_engineer"):
        return jsonify({"status": "error", "message": "Access denied — site engineer login required"}), 403

    try:
        # Build archive in memory
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            for filepath in _BACKUP_FILES:
                if os.path.isfile(filepath):
                    # Store with full absolute path preserved
                    tar.add(filepath, arcname=filepath.lstrip("/"))
                else:
                    app.logger.warning("Backup: skipping missing file: %s", filepath)
        buf.seek(0)

        hostname = socket.gethostname()
        ts       = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"dexter_backup_{hostname}_{ts}.tar.gz"

        app.logger.info("Backup created: %s", filename)
        return send_file(
            buf,
            mimetype="application/gzip",
            as_attachment=True,
            download_name=filename
        )

    except Exception as e:
        app.logger.error("Backup failed: %s", e)
        return jsonify({"status": "error", "message": str(e)}), 500
        

@app.route("/get_reboot_schedule", methods=["GET"])
def get_reboot_schedule():
    timer_file = "dexter-weekly-reboot"
    try:
        with open(timer_file, "r") as f:
            for line in f:
                if line.startswith("OnCalendar="):
                    # Format: OnCalendar=Sunday *-*-* 12:00
                    parts = line.split("=", 1)[1].strip().split()
                    day      = parts[0] if len(parts) > 0 else "Sunday"
                    time_val = parts[2] if len(parts) > 2 else "12:00"
                    return jsonify({"day": day, "time": time_val})
        return jsonify({"status": "error", "message": "Schedule not found in file"}), 404
    except FileNotFoundError:
        return jsonify({"status": "error", "message": "No schedule configured yet"}), 404
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/set_reboot_schedule",methods=["POST"])
def set_reboot_schedule():
    _SYSTEMD_TIMER = "/etc/systemd/system/dexter-weekly-reboot.timer"
    local_timer_file = "dexter-weekly-reboot"
    data = request.json
    day_data = data["day"]
    time_data = data["time"]

    new_line = "OnCalendar=" + str(day_data) + " *-*-* " + str(time_data) + "\n"

    try:
        with open(local_timer_file, "r") as file:
            lines = file.readlines()
    except FileNotFoundError:
        lines = []

    if len(lines) < 4:
        lines = ["[Unit]\n",
                 "Description=Dexter HMS Scheduled Weekly Reboot\n",
                 "\n",
                 "[Timer]\n",
                 new_line,
                 "Persistent=false\n",
                 "RandomizedDelaySec=60\n",
                 "Unit=dexter-weekly-reboot.service\n",
                 "\n",
                 "[Install]\n",
                 "WantedBy=timers.target\n"]
    else:
        for i, line in enumerate(lines):
            if line.startswith("OnCalendar="):
                lines[i] = new_line
                break

    content = "".join(lines)

    # Save local copy (used by get_reboot_schedule for display)
    with open(local_timer_file, "w") as f:
        f.write(content)

    # Apply to systemd on the HOST: write timer file into host mount namespace,
    # then reload and restart the timer unit.
    try:
        _sp.run(
            ["nsenter", "-t", "1", "-m", "--", "tee", _SYSTEMD_TIMER],
            input=content.encode(), stdout=_sp.DEVNULL,
            check=True, timeout=10
        )
        _host_run(["systemctl", "daemon-reload"], check=True, timeout=10)
        _host_run(["systemctl", "enable", "dexter-weekly-reboot.timer"], check=True, timeout=10)
        _host_run(["systemctl", "restart", "dexter-weekly-reboot.timer"], check=True, timeout=10)
    except Exception as e:
        app.logger.error("set_reboot_schedule: systemd update failed: %s", e)

    return {"success": "200", "message": "Data Saved"}


@app.route("/backup_restore", methods=["POST"])
def backup_restore():
    """
    Accept an uploaded dexter_backup_*.tar.gz file, stop Dexter services,
    extract the archive restoring all files to their original paths,
    fix permissions, then restart services.
    Only site_engineer role can access this.
    """
    app.logger.info("backup_restore: request received from %s", request.remote_addr)
    try:
        return _backup_restore_inner()
    except Exception as _exc:
        app.logger.exception("backup_restore: unhandled exception: %s", _exc)
        return jsonify({"status": "error", "message": "Internal server error during restore"}), 500


def _backup_restore_inner():
    if not check_user_access("site_engineer"):
        return jsonify({"status": "error", "message": "Access denied — site engineer login required"}), 403

    if "backup_file" not in request.files:
        app.logger.warning("backup_restore: no file in request.files; keys=%s", list(request.files.keys()))
        return jsonify({"status": "error", "message": "No file uploaded"}), 400

    f = request.files["backup_file"]
    app.logger.info("backup_restore: received file '%s', size hint=%s", f.filename, request.content_length)
    if not f.filename.endswith(".tar.gz"):
        return jsonify({"status": "error", "message": "File must be a .tar.gz backup archive"}), 400

    # Save upload to temp file (close handle first so f.save() can open by name)
    tmp = tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False)
    tmp_name = tmp.name
    tmp.close()
    try:
        f.save(tmp_name)
    except Exception as _save_exc:
        app.logger.error("backup_restore: f.save() failed: %s", _save_exc)
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        return jsonify({"status": "error", "message": "Failed to save upload to disk"}), 500
    app.logger.info("backup_restore: file saved to %s", tmp_name)

    # Validate it is a real tar.gz before handing off to background thread
    if not tarfile.is_tarfile(tmp_name):
        os.unlink(tmp_name)
        return jsonify({"status": "error", "message": "Invalid archive file"}), 400

    def _do_restore(tmp_path):
        try:
            with tarfile.open(tmp_path, "r:gz") as tar:
                for member in tar.getmembers():
                    dest = "/" + member.name
                    if not member.isfile():
                        continue
                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                    src = tar.extractfile(member)
                    if src is None:
                        continue
                    with src, open(dest, "wb") as dst:
                        dst.write(src.read())
            os.unlink(tmp_path)
            for db_path in _BACKUP_FILES:
                if db_path.endswith(".db") and os.path.exists(db_path):
                    try:
                        os.chmod(db_path, 0o660)
                        _sp.run(["sudo", "chown", "pi:pi", db_path],
                                capture_output=True, timeout=5)
                    except Exception:
                        pass
            app.logger.info("Restore complete, triggering reboot.")
        except Exception as exc:
            app.logger.error("Restore failed: %s", exc)
        finally:
            app.logger.info("Restore: firing host reboot via nsenter.")
            try:
                _sp.Popen(
                    ["nsenter", "-t", "1", "-m", "-u", "-i", "-n", "-p",
                     "--", "/sbin/reboot"],
                    stdin=_sp.DEVNULL, stdout=_sp.DEVNULL,
                    stderr=_sp.DEVNULL, start_new_session=True,
                )
            except Exception as _e:
                app.logger.warning("Restore: nsenter reboot failed: %s", _e)

    # Do NOT stop dexter.target before extraction — that kills the Flask
    # process and with it this thread, so the reboot never fires.
    # Overwriting DB files while services run is safe here because we
    # reboot immediately after, loading the restored files from scratch.
    threading.Thread(target=_do_restore, args=(tmp_name,), daemon=False).start()

    return jsonify({
        "status": "success",
        "message": "Restore started. Device will reboot in a few seconds — wait 60–90 seconds, then reconnect.",
    })

 


# ═══════════════════════════════════════════════════════════════════════════════
# NETWORK DEVICE AUTO-SCANNER ROUTES
# ═══════════════════════════════════════════════════════════════════════════════
_SCANNER_PATH     = "/home/pi/Test3/auto_ip_scanner.py"
_SCAN_STATUS_FILE = "/home/pi/Test3/scan_status.json"
_scan_process: Optional[_sp.Popen] = None
_scan_lock        = threading.Lock()


@app.route("/scan_start", methods=["POST"])
def scan_start():
    if "username" not in session:
        return jsonify({"status": "error", "message": "Not logged in"}), 401
    global _scan_process
    data     = request.get_json(silent=True) or {}
    device   = data.get("device", "").strip().lower()
    if device not in ("nvr", "access", "burglar", "texecom"):
        return jsonify({"status": "error", "message": f"Invalid device type: '{device}'"}), 400
    brand    = data.get("brand",    "all").strip().lower()
    if device == "texecom":
        brand = "texecom"
    user     = data.get("user",     "").strip()
    password = data.get("password", "").strip()
    tex_pass = data.get("tex_pass", "12345").strip() or "12345"
    cidr     = data.get("cidr",     "").strip()
    if device in ("nvr", "access", "burglar") and (not user or not password):
        return jsonify({"status": "error", "message": "Username and password required"}), 400
    with _scan_lock:
        if _scan_process is not None and _scan_process.poll() is None:
            return jsonify({"status": "error",
                            "message": "A scan is already running."}), 409
    try:
        with open(_SCAN_STATUS_FILE, "w") as f:
            json.dump({"status": "running",
                       "message": f"Starting scan for {device}...",
                       "found": [], "error": ""}, f)
    except Exception:
        pass
    # nsenter -n: run scanner in the HOST network namespace so netifaces
    # sees eth0/wlan0 (192.168.x.x) instead of the Docker bridge (172.18.x.x).
    # Only the network stack changes — container Python and files are still used.
    cmd = ["nsenter", "-t", "1", "-n", "--",
           "python3", _SCANNER_PATH,
           "--device", device, "--brand", brand,
           "--user", user, "--pass", password,
           "--tex-pass", tex_pass, "--status-file", _SCAN_STATUS_FILE]
    if cidr:
        cmd += ["--cidr", cidr]
    try:
        with _scan_lock:
            _scan_process = _sp.Popen(cmd, stdout=_sp.PIPE, stderr=_sp.STDOUT,
                                       cwd="/home/pi/Test3")
    except Exception as e:
        return jsonify({"status": "error", "message": f"Failed to start scan: {e}"}), 500
    return jsonify({"status": "started",
                    "message": f"Scan launched for {device}/{brand}"}), 202


@app.route("/scan_status", methods=["GET"])
def scan_status():
    if "username" not in session:
        return jsonify({"status": "error", "message": "Not logged in"}), 401
    if not os.path.exists(_SCAN_STATUS_FILE):
        return jsonify({"status": "idle", "message": "No scan run yet.", "found": []}), 200
    try:
        with open(_SCAN_STATUS_FILE, "r") as f:
            data = json.load(f)
        with _scan_lock:
            proc = _scan_process
        if data.get("status") == "running" and proc is not None and proc.poll() is not None:
            data["status"]  = "done"
            data["message"] = data.get("message", "") + " (process exited)"
        return jsonify(data), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e), "found": []}), 500


@app.route("/scan_cancel", methods=["POST"])
def scan_cancel():
    if "username" not in session:
        return jsonify({"status": "error", "message": "Not logged in"}), 401
    global _scan_process
    with _scan_lock:
        proc = _scan_process
        if proc is None or proc.poll() is not None:
            return jsonify({"status": "ok", "message": "No scan running."}), 200
        try:
            proc.terminate()
            _scan_process = None
            try:
                with open(_SCAN_STATUS_FILE, "w") as f:
                    json.dump({"status": "done", "message": "Scan cancelled.",
                               "found": [], "error": "cancelled"}, f)
            except Exception:
                pass
            return jsonify({"status": "ok", "message": "Scan cancelled."}), 200
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == "__main__":
    # Initialize default users in database
    initialize_users()
    app.run(debug=False, host="0.0.0.0", port=5001, threaded=True, ssl_context=('cert.pem', 'key.pem'))
    
