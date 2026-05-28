#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify_modem_db_encryption.py
Dexter HMS — modem_config.db encryption verification and migration tool

Run on the Raspberry Pi:
    cd /home/pi/Test3
    python3 verify_modem_db_encryption.py

What this script does:
  1. Opens modem_config.db and reads all 4 credential fields
  2. For each field: checks whether value is Fernet-encrypted or plaintext
  3. Reports current status clearly
  4. If any plaintext fields found: asks for confirmation then migrates them
  5. Re-reads and confirms all fields are now encrypted
"""

import os
import sys
import sqlite3

# ── Paths ─────────────────────────────────────────────────────────────────────
DB_PATH  = os.path.join(os.path.dirname(__file__), 'modem_config.db')
KEY_PATH = '/etc/dexter/fernet.key'

CREDENTIAL_FIELDS = ['access_token', 'client_id', 'user_name', 'password',
                     'swatch_username', 'swatch_password', 'swatch_host']

# ── Colours ───────────────────────────────────────────────────────────────────
GREEN  = '\033[92m'
RED    = '\033[91m'
YELLOW = '\033[93m'
CYAN   = '\033[96m'
RESET  = '\033[0m'
BOLD   = '\033[1m'


def ok(msg):    print(f"  {GREEN}✓{RESET}  {msg}")
def fail(msg):  print(f"  {RED}✗{RESET}  {msg}")
def warn(msg):  print(f"  {YELLOW}!{RESET}  {msg}")
def info(msg):  print(f"  {CYAN}·{RESET}  {msg}")


# ── Step 1: Check DB exists ───────────────────────────────────────────────────
print(f"\n{BOLD}=== Dexter HMS — modem_config.db Encryption Check ==={RESET}\n")

if not os.path.exists(DB_PATH):
    fail(f"modem_config.db not found at: {DB_PATH}")
    print(f"\n  Run this script from /home/pi/Test3/")
    sys.exit(1)
ok(f"Found: {DB_PATH}")


# ── Step 2: Check Fernet key ──────────────────────────────────────────────────
if not os.path.exists(KEY_PATH):
    fail(f"Fernet key not found at: {KEY_PATH}")
    print(f"\n  The key is created automatically when secrets_manager.py")
    print(f"  is first imported. Run the main system once, then retry.")
    sys.exit(1)
ok(f"Fernet key found: {KEY_PATH}")


# ── Step 3: Load Fernet cipher ────────────────────────────────────────────────
cipher = None
try:
    from cryptography.fernet import Fernet, InvalidToken
    key    = open(KEY_PATH, 'rb').read().strip()
    cipher = Fernet(key)
    ok("Fernet cipher loaded")
except Exception as e:
    fail(f"Failed to load Fernet cipher: {e}")
    sys.exit(1)


# ── Step 4: Read all credential fields from DB ────────────────────────────────
print(f"\n{BOLD}── Credential field status ──{RESET}")

# Check which columns actually exist in this DB (swatch columns may not exist yet
# on devices that haven't run db_schema_migration.py with the new modem_config fix)
existing_cols = set()
try:
    conn = sqlite3.connect(DB_PATH)
    existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(modem_parameters)").fetchall()}
    conn.close()
except sqlite3.Error as e:
    fail(f"Could not read schema: {e}")
    sys.exit(1)

# Only select columns that actually exist — avoids OperationalError on older schema
fields_to_select = [f for f in CREDENTIAL_FIELDS if f in existing_cols]
missing_cols     = [f for f in CREDENTIAL_FIELDS if f not in existing_cols]

if missing_cols:
    warn(f"Columns not yet in DB (run db_schema_migration.py first): {', '.join(missing_cols)}")

row = None
try:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    select_cols = ", ".join(fields_to_select) if fields_to_select else "id"
    row = conn.execute(
        f"SELECT {select_cols} FROM modem_parameters WHERE id = 1"
    ).fetchone()
    conn.close()
except sqlite3.Error as e:
    fail(f"DB read failed: {e}")
    sys.exit(1)

if not row:
    warn("No row found in modem_parameters (id=1) — DB may be empty")
    sys.exit(0)


# ── Step 5: Check each field ──────────────────────────────────────────────────
def check_field(field, value):
    """Returns ('encrypted'|'plaintext'|'empty', decoded_value_or_None)"""
    if not value or str(value).strip() == '':
        return 'empty', None
    try:
        decoded = cipher.decrypt(value.encode()).decode()
        return 'encrypted', decoded
    except (InvalidToken, Exception):
        return 'plaintext', value


statuses   = {}
needs_migration = False

for field in CREDENTIAL_FIELDS:
    # Column missing from DB entirely — not yet migrated
    if field not in fields_to_select:
        warn(f"{field:<20} → {YELLOW}COLUMN MISSING{RESET}  (run db_schema_migration.py)")
        continue

    raw    = row[field]
    status, decoded = check_field(field, raw)
    statuses[field] = (status, raw, decoded)

    if status == 'encrypted':
        ok(f"{field:<20} → {GREEN}ENCRYPTED{RESET}  "
           f"(decrypts to: {'*' * min(len(decoded), 8) if decoded else '(empty)'})")
    elif status == 'plaintext':
        fail(f"{field:<20} → {RED}PLAINTEXT{RESET}  "
             f"(value: {'*' * min(len(raw), 8) if raw else '(empty)'})")
        needs_migration = True
    else:
        warn(f"{field:<20} → {YELLOW}EMPTY{RESET}   (not set yet — set via LCD menu)")


# ── Step 6: Summary and migration ────────────────────────────────────────────
print(f"\n{BOLD}── Summary ──{RESET}")

if not needs_migration:
    all_empty     = all(s == 'empty'     for s, _, _ in statuses.values())
    all_encrypted = all(s == 'encrypted' for s, _, _ in statuses.values())
    some_empty    = any(s == 'empty'     for s, _, _ in statuses.values())

    if all_empty:
        warn("All credential fields are empty — no tokens set yet.")
        warn("Set access_token, client_id, user_name, password via the LCD menu.")
        warn("They will be automatically encrypted when saved.")
    elif all_encrypted:
        ok(f"{GREEN}{BOLD}All credential fields are encrypted. DB is secure.{RESET}")
    elif some_empty:
        ok("Set fields are encrypted. Empty fields are not yet configured.")
        warn("Set remaining fields via LCD menu — they will be encrypted on save.")
    sys.exit(0)

# Plaintext fields found — offer migration
print()
warn(f"{RED}Plaintext credentials found in modem_config.db!{RESET}")
warn("This means the SEC-04 fix has not yet migrated this DB.")
print()

answer = ''
try:
    answer = input("  Migrate now? Encrypts all plaintext fields in-place. [y/N]: ").strip().lower()
except KeyboardInterrupt:
    print("\n  Cancelled.")
    sys.exit(0)

if answer != 'y':
    print("  Skipped. Re-run after deploying the updated files.")
    sys.exit(0)


# ── Step 7: Run migration ─────────────────────────────────────────────────────
print(f"\n{BOLD}── Migrating ──{RESET}")

try:
    conn = sqlite3.connect(DB_PATH)
    migrated = 0
    for field, (status, raw, _) in statuses.items():
        if status == 'plaintext':
            encrypted = cipher.encrypt(raw.encode()).decode()
            conn.execute(
                f"UPDATE modem_parameters SET {field} = ? WHERE id = 1",
                (encrypted,)
            )
            ok(f"Encrypted: {field}")
            migrated += 1
    conn.commit()
    conn.close()
    ok(f"Migration complete — {migrated} field(s) encrypted")
except Exception as e:
    fail(f"Migration failed: {e}")
    sys.exit(1)


# ── Step 8: Re-verify after migration ────────────────────────────────────────
print(f"\n{BOLD}── Re-verification ──{RESET}")

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row
select_cols2 = ", ".join(fields_to_select) if fields_to_select else "id"
row2 = conn.execute(
    f"SELECT {select_cols2} FROM modem_parameters WHERE id = 1"
).fetchone()
conn.close()

all_good = True
for field in CREDENTIAL_FIELDS:
    if field not in fields_to_select:
        warn(f"{field:<20} → {YELLOW}COLUMN MISSING{RESET} (run db_schema_migration.py)")
        continue
    status, decoded = check_field(field, row2[field])
    if status == 'encrypted':
        ok(f"{field:<20} → {GREEN}ENCRYPTED{RESET}")
    elif status == 'empty':
        warn(f"{field:<20} → {YELLOW}EMPTY{RESET} (not set)")
    else:
        fail(f"{field:<20} → {RED}STILL PLAINTEXT — migration failed!{RESET}")
        all_good = False

print()
if all_good:
    print(f"  {GREEN}{BOLD}✓ All set fields are now encrypted. DB is secure.{RESET}\n")
else:
    print(f"  {RED}{BOLD}✗ Some fields still plaintext. Check errors above.{RESET}\n")
    sys.exit(1)
