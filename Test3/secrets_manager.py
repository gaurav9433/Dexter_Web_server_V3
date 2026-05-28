# secrets_manager.py
# Fixes: SEC-01 — Hardcoded credentials across all modules
#        SEC-04 — Plaintext credentials stored in database
#
# pip install python-dotenv cryptography

"""
secrets_manager.py
Dexter HMS — Centralised secrets and credential management (SEC-01, SEC-04)

Responsibilities:
  - Reads all credentials from /etc/dexter/.env via python-dotenv
  - Raises KeyError on missing secrets — fails loudly at startup not silently at runtime
  - Provides Fernet symmetric encryption for SQLite-stored credentials
  - One-time migration utility to encrypt existing plaintext DB credentials

Key functions:
  - get_secret(name)                        — read from /etc/dexter/.env
  - encrypt_value(plaintext)                — Fernet encrypt a string
  - decrypt_value(ciphertext)               — Fernet decrypt a string
  - store_credential(db_path, key, value)   — encrypted write to DB
  - get_credential(db_path, key)            — decrypted read from DB
  - migrate_plaintext_credentials(db_path)  — one-time plaintext→encrypted migration

Dependencies:
  - python-dotenv, cryptography (pip3 install python-dotenv cryptography)
Author: Seple Novaedge Pvt. Ltd.
"""

import os
import sqlite3
import logging
from pathlib import Path
from dotenv import load_dotenv
from cryptography.fernet import Fernet, InvalidToken

log = logging.getLogger(__name__)

# ─── FERNET KEY ───────────────────────────────────────────────────────────────

def _load_or_create_key(key_path='/etc/dexter/fernet.key') -> bytes:
    """
    Loads existing Fernet key or generates a new one.
    Key file is chmod 600 — readable only by owner.
    IMPORTANT: Back up this key. If lost, all encrypted DB values
    become unreadable and credentials must be re-entered.
    """
    p = Path(key_path)
    if p.exists():
        return p.read_bytes().strip()
    p.parent.mkdir(parents=True, exist_ok=True)
    key = Fernet.generate_key()
    p.write_bytes(key)
    p.chmod(0o600)
    log.info(f"New Fernet key generated at {key_path}")
    return key


# Load .env and cipher at import time
load_dotenv(dotenv_path=os.environ.get('DEXTER_ENV_PATH', '/etc/dexter/.env'))
_cipher = Fernet(_load_or_create_key())


# ─── SECRET RETRIEVAL ─────────────────────────────────────────────────────────

def get_secret(name: str) -> str:
    """
    Read a secret from /etc/dexter/.env by key name.
    Raises KeyError if the key is missing — fails loudly so
    missing credentials are caught at startup, not silently at runtime.

    Usage in any module:
        from secrets_manager import get_secret
        TOKEN = get_secret('MQTT_TOKEN')
    """
    value = os.environ.get(name)
    if not value:
        raise KeyError(
            f"Required secret '{name}' not found in /etc/dexter/.env. "
            f"Add it and restart the service."
        )
    return value


# ─── DATABASE CREDENTIAL ENCRYPTION (SEC-04) ─────────────────────────────────

def encrypt_value(plaintext: str) -> str:
    """Encrypt a plaintext string using Fernet symmetric encryption."""
    return _cipher.encrypt(plaintext.encode()).decode()


def decrypt_value(ciphertext: str) -> str:
    """
    Decrypt a Fernet-encrypted string.
    Raises ValueError on key mismatch or corrupted data.
    """
    try:
        return _cipher.decrypt(ciphertext.encode()).decode()
    except InvalidToken:
        raise ValueError(
            "Decryption failed — Fernet key mismatch or corrupted value. "
            "Check /etc/dexter/fernet.key matches the key used to encrypt."
        )


def store_credential(db_path: str, key: str, plaintext: str) -> None:
    """
    Store an encrypted credential in the database.
    Replaces plaintext storage in device_params table.
    """
    encrypted = encrypt_value(plaintext)
    with sqlite3.connect(db_path) as conn:
        conn.execute('PRAGMA journal_mode=WAL;')
        conn.execute(
            'INSERT OR REPLACE INTO device_params (key, value) VALUES (?, ?)',
            (key, encrypted)
        )
        conn.commit()
    log.info(f"Credential '{key}' stored encrypted in {db_path}")


def get_credential(db_path: str, key: str) -> str:
    """
    Retrieve and decrypt a credential from the database.
    Raises KeyError if the key does not exist.
    """
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            'SELECT value FROM device_params WHERE key=?', (key,)
        ).fetchone()
    if not row:
        raise KeyError(f"Credential '{key}' not found in {db_path}")
    return decrypt_value(row[0])


# ─── ONE-TIME MIGRATION (SEC-04) ─────────────────────────────────────────────

def migrate_plaintext_credentials(db_path: str) -> None:
    """
    One-time migration: reads all plaintext rows from device_params
    and re-writes them as Fernet-encrypted values.

    Run once after deploying this file:
        python3 -c "from secrets_manager import migrate_plaintext_credentials;
                    migrate_plaintext_credentials('/var/dexter/device_params.db')"
    """
    encrypted_count = 0
    skipped_count = 0

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute('SELECT key, value FROM device_params').fetchall()
        for key, value in rows:
            try:
                # If already encrypted, decrypt will succeed — skip it
                _cipher.decrypt(value.encode())
                skipped_count += 1
            except InvalidToken:
                # Not encrypted — encrypt it now
                encrypted = encrypt_value(value)
                conn.execute(
                    'UPDATE device_params SET value=? WHERE key=?',
                    (encrypted, key)
                )
                encrypted_count += 1
        conn.commit()

    log.info("Migration complete: %s encrypted, %s already encrypted.", encrypted_count, skipped_count)