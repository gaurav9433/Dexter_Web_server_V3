"""
Docker health check for Dexter HMS.
Exits 0 (healthy) if the panel SQLite DB is reachable.
Exits 1 (unhealthy) otherwise — Docker will restart the container.
"""
import sys
import os
import sqlite3

DB_PATH = "/home/pi/Test3/dexterpanel2.db"

if not os.path.exists(DB_PATH):
    sys.exit(1)

try:
    conn = sqlite3.connect(DB_PATH, timeout=5)
    conn.execute("SELECT 1")
    conn.close()
    sys.exit(0)
except Exception:
    sys.exit(1)