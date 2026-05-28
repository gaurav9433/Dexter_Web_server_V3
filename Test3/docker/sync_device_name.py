#!/usr/bin/env python3
"""Sync DEVICE_NAME in .env from modem_config.db before Docker starts."""
import sqlite3
import os
import re

DB = '/home/pi/Test3/modem_config.db'
ENV = '/home/pi/Test3/.env'

try:
    if not os.path.exists(DB):
        raise SystemExit(0)
    row = sqlite3.connect(DB).execute(
        'SELECT device_name FROM modem_parameters WHERE id=1'
    ).fetchone()
    name = (row[0] or '').strip() if row else ''
    if not name:
        raise SystemExit(0)
    content = open(ENV).read() if os.path.exists(ENV) else ''
    if re.search(r'^DEVICE_NAME=', content, re.MULTILINE):
        content = re.sub(r'^DEVICE_NAME=.*$', f'DEVICE_NAME={name}', content, flags=re.MULTILINE)
    else:
        content += f'\nDEVICE_NAME={name}'
    open(ENV, 'w').write(content)
except SystemExit:
    raise
except Exception:
    pass  # Never block Docker startup on sync failure
