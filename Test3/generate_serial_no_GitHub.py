import sys
import datetime
import time
import os
import base64
import subprocess
import requests
import pandas as pd
import sqlite3
from io import BytesIO
from dotenv import load_dotenv

# === Load environment variables from .env file ===
load_dotenv()

# cd ~/Test3
# ls –l
# nano .env
#GITHUB_TOKEN = <set in .env>
#REPO_OWNER = seple_admin
#REPO_NAME = Dexter-Serial-No.
#FILE_PATH = Dexter Serial no.xlsx
#BRANCH = main

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
REPO_OWNER = os.getenv("REPO_OWNER")
REPO_NAME = os.getenv("REPO_NAME")
FILE_PATH = os.getenv("FILE_PATH")
BRANCH = os.getenv("BRANCH")

print("DEBUG:", os.getenv("GITHUB_TOKEN"))
print("DEBUG:", os.getenv("REPO_OWNER"))
print("DEBUG:", os.getenv("REPO_NAME"))
print("DEBUG:", os.getenv("FILE_PATH"))

# === GitHub API URL ===
API_URL = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/{FILE_PATH}"

# === Auth Header ===
HEADERS = {
    'Authorization': f'token {GITHUB_TOKEN}',
    'Accept': 'application/vnd.github.v3+json'
}

# File paths
#SERIAL_FILE = '/etc/securelink_serial.txt'    
DB_FILE = '/home/pi/Test3/securelink.db' 
#EXCEL_URL = "https://seplsecurity-my.sharepoint.com/personal/rnd_seple_in/_layouts/15/download.aspx?share=EXwrhky8-zhNukCbOyQHGhoBE7r-LAVT6VED0wbDgqp8pg"

def init_db():
    """Create DB and table if not exists."""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS device_info (
                   id INTEGER PRIMARY KEY,
                   panel_number TEXT,
                   batch_number TEXT
                 )''')
    conn.commit()
    conn.close()

def store_device_info(panel, batch):
    """Insert panel and batch info into DB (once)."""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM device_info")
    if c.fetchone()[0] == 0:
        c.execute("INSERT INTO device_info (panel_number, batch_number) VALUES (?, ?)", (panel, batch))
        conn.commit()
    conn.close()

def fetch_device_info():
    """Fetch panel and batch info from DB."""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT panel_number, batch_number FROM device_info LIMIT 1")
    row = c.fetchone()
    conn.close()
    return row if row else ('XX', 'BNXXX')

#def download_and_parse_excel():
#    try:
#        response = requests.get(EXCEL_URL)
#        if response.status_code == 200:
#            df = pd.read_excel(BytesIO(response.content))
#            if 'panel_number' in df.columns and 'batch_number' in df.columns:
                #panel = str(df.iloc[0]['panel_number']).zfill(2)
                #batch = str(df.iloc[0]['batch_number'])
                
                # Clean float conversion (e.g., 1.0 -> '1')
#                panel_raw = df.iloc[0]['panel_number']
#                batch_raw = df.iloc[0]['batch_number']
                
                # Convert to str and remove decimal if present
#                panel = str(int(panel_raw)).zfill(2) if pd.notnull(panel_raw) else 'XX'  
                #batch = str(int(batch_raw)) if pd.notnull(batch_raw) else 'BXXXX'
#                batch = str(batch_raw).split('.')[0]  # Strip any ".0" if present                
                
                # Remove the first row
#                df = df.iloc[1:]
                
#                return panel, batch
#    except Exception as e:
#        print("Error downloading Excel:", e)
#    return 'XX', 'BXXXX'

def download_and_parse_excel():
    try:
        response = requests.get(API_URL, headers=HEADERS)
        response.raise_for_status()
        content = base64.b64decode(response.json()['content'])
        file_sha = response.json()['sha']

        df = pd.read_excel(BytesIO(content))
        if 'panel_number' in df.columns and 'batch_number' in df.columns:
            panel_raw = df.iloc[0]['panel_number']
            batch_raw = df.iloc[0]['batch_number']
            panel = str(int(panel_raw)).zfill(2) if pd.notnull(panel_raw) else 'XX'
            batch = str(batch_raw).split('.')[0] if pd.notnull(batch_raw) else 'BNXXX'

            updated_df = df.iloc[1:]
            buffer = BytesIO()
            updated_df.to_excel(buffer, index=False)
            buffer.seek(0)

            encoded_content = base64.b64encode(buffer.read()).decode('utf-8')

            payload = {
                "message": "Deleted first row after serial generation",
                "content": encoded_content,
                "branch": BRANCH,
                "sha": file_sha
            }

            upload_response = requests.put(API_URL, headers=HEADERS, json=payload)
            upload_response.raise_for_status()
            print("Successfully updated Excel on GitHub")

            return panel, batch
    except Exception as e:
        print("Error processing Excel file:", e)

    return 'XX', 'BNXXX'

def ensure_device_info():
    init_db()
    panel, batch = fetch_device_info()
    if panel == 'XX' and batch == 'BNXXX':
        panel, batch = download_and_parse_excel()
        store_device_info(panel, batch)

def get_model_year():
    year = datetime.datetime.now().year
    return f"SL{str(year)[-2:]}"

def get_rpi_model():
    try:
        with open('/proc/device-tree/model') as f:
            model = f.read()
        if 'Raspberry Pi 3' in model:
            return 'R3'
        elif 'Raspberry Pi 4' in model:
            return 'R4'
        elif 'Raspberry Pi 5' in model:
            return 'R5'
    except:
        pass
    return 'R?'

def get_python_version():
    return f'P{sys.version_info.major}'

def generate_serial():
    model_prefix = get_model_year()
    rpi = get_rpi_model()
    pyv = get_python_version()
    panel, batch = fetch_device_info()
    return f"{model_prefix}{rpi}{pyv}{panel}{batch}"

def get_or_create_serial():
    #if os.path.exists(SERIAL_FILE):
    #    with open(SERIAL_FILE) as f:
    #        return f.read().strip()
    ensure_device_info()
    return generate_serial()
    #serial = generate_serial()
    #with open(SERIAL_FILE, 'w') as f:
    #    f.write(serial)
    #return serial

def generate_serial_no():
    subprocess.call(["sudo", "pon", "c16qs"])
    time.sleep(20.0)
    get_or_create_serial()
    time.sleep(10)  # Wait for 10 seconds
    subprocess.call(["sudo", "poff", "c16qs"])
    time.sleep(5.0)
#    subprocess.call(["sudo", "reboot"])


if __name__ == "__main__":
    #serial = generate_serial_no()
    serial = get_or_create_serial()
    print("System Serial Number:", serial)
