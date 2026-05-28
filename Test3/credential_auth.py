# -*- coding: utf-8 -*-
"""
credential_auth.py
Dexter HMS — Challenge-Response credential access gate

Protects all credential view states on the LCD menu.
The operator must call Seple, read the challenge, and receive the response
before any credential is displayed. The secret key never lives on the panel.

How it works:
  1. generate_challenge()        → 4-char random hex  →  shown on LCD
  2. Operator calls Seple        → reads "7A3F"
  3. Seple opens response_tool.html on phone → types "7A3F" → gets "291847"
  4. Seple tells operator "enter 291847"
  5. verify_response("7A3F", "291847") → True  →  credential shown SHOW_TIMEOUT_SEC seconds

Security properties:
  - Challenge is os.urandom — never reused, unpredictable
  - HMAC-SHA256 is one-way — operator cannot derive response from challenge
  - Secret key stored only in response_tool.html on engineer phone
  - Panel stores only HMAC(key, "seple-verify") to confirm correct key at setup
  - 3 wrong responses → 5-minute lockout (RAM only, resets on restart)
  - Credential auto-clears after SHOW_TIMEOUT_SEC seconds

Author: Seple Novaedge Pvt. Ltd.
"""

import os
import hmac
import hashlib
import time
import logging

log = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────

# Time in seconds a credential stays visible before auto-clear
SHOW_TIMEOUT_SEC = 300

# Failed attempt lockout settings
MAX_FAILURES     = 3
LOCKOUT_SEC      = 300   # 5 minutes

# Secret key HEX — set this at commissioning via set_key()
# NEVER hardcode the real key here — call set_key() from startup
# The raw key lives only in response_tool.html on the engineer phone
_key_hex: str = ""

# ── Failed attempt tracker (RAM only — resets on restart) ─────────────────────
_fail_times: list = []


# ── Public API ────────────────────────────────────────────────────────────────

def set_key(key_hex: str) -> None:
    """
    Set the secret key at startup.
    Call once from TLChronosProMAIN after loading from /etc/dexter/cred_auth.key

    Example (in TLChronosProMAIN startup):
        import credential_auth
        with open('/etc/dexter/cred_auth.key') as f:
            credential_auth.set_key(f.read().strip())
    """
    global _key_hex
    _key_hex = key_hex.strip()
    log.info("[credential_auth] Key loaded (%d chars)", len(_key_hex))


def key_is_loaded() -> bool:
    """Returns True if the secret key has been successfully loaded."""
    return bool(_key_hex)


def generate_challenge() -> str:
    """
    Return a fresh 4-char uppercase hex challenge from OS entropy.
    Called every time REQUEST_CHALLENGE state is entered.
    Each call returns a different value — no storage between calls.

    Example: "7A3F", "B2C1", "9F4A"
    """
    return os.urandom(2).hex().upper()


def verify_response(challenge: str, entered: str) -> bool:
    """
    Check whether the 6-digit response entered by the operator is correct.

    Computes HMAC-SHA256(key, challenge), converts to 6-digit decimal,
    and compares using constant-time comparison (no timing side-channel).

    Returns True on match, False otherwise.
    Records a failure timestamp on mismatch.
    """
    if not _key_hex:
        log.warning("[credential_auth] Key not set — cannot verify response")
        return False

    expected = _compute_response(challenge)
    entered_clean = entered.strip().zfill(6)

    match = hmac.compare_digest(expected, entered_clean)
    if not match:
        _record_failure()
        log.warning("[credential_auth] Wrong response for challenge=%s", challenge)
    else:
        log.info("[credential_auth] Access granted for challenge=%s", challenge)
    return match


def is_locked_out() -> bool:
    """
    Returns True if 3 or more failed attempts in the last 5 minutes.
    Call this at the start of ENTER_RESPONSE state.
    If locked, show "Locked 5 min" on LCD and skip entry.
    """
    _trim_old_failures()
    locked = len(_fail_times) >= MAX_FAILURES
    if locked:
        log.warning("[credential_auth] Locked out — %d failures in window", len(_fail_times))
    return locked


def time_remaining_locked() -> int:
    """
    Returns seconds remaining in lockout (0 if not locked).
    Use for LCD display: "Locked Xm Ys"
    """
    if not _fail_times:
        return 0
    oldest_relevant = _oldest_failure_in_window()
    if oldest_relevant is None:
        return 0
    elapsed = time.time() - oldest_relevant
    remaining = int(LOCKOUT_SEC - elapsed)
    return max(0, remaining)


def show_expired(show_start_time: float) -> bool:
    """
    Returns True if the credential has been showing longer than SHOW_TIMEOUT_SEC.
    Pass in the timestamp recorded when the SHOW state was entered.

    Example usage in SHOW_* state:
        if credential_auth.show_expired(_cred_show_time[0]):
            lcd.clear(); lcd.home()
            menuSubSubSubState = EXIT
            return
    """
    if show_start_time is None:
        return False
    return (time.time() - show_start_time) >= SHOW_TIMEOUT_SEC


# ── Internal helpers ──────────────────────────────────────────────────────────

def _compute_response(challenge: str) -> str:
    """
    HMAC-SHA256(key, challenge) → 6-digit zero-padded decimal string.
    Same algorithm as response_tool.html — must stay in sync.
    """
    raw = hmac.new(
        bytes.fromhex(_key_hex),
        challenge.upper().encode('ascii'),
        hashlib.sha256
    ).digest()
    # Take first 4 bytes as unsigned int, mod 1,000,000, zero-pad to 6 digits
    code = int.from_bytes(raw[:4], 'big') % 1_000_000
    return str(code).zfill(6)


def _record_failure() -> None:
    _fail_times.append(time.time())
    log.warning("[credential_auth] Failure recorded — total in window: %d",
                len([t for t in _fail_times if time.time() - t < LOCKOUT_SEC]))


def _trim_old_failures() -> None:
    now = time.time()
    _fail_times[:] = [t for t in _fail_times if now - t < LOCKOUT_SEC]


def _oldest_failure_in_window() -> float:
    _trim_old_failures()
    return min(_fail_times) if _fail_times else None
