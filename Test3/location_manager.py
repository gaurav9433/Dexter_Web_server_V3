#!/usr/bin/env python3
"""
location_manager.py — Dexter HMS GPS Location Manager
Seple Novaedge Pvt. Ltd.

Logic:
  ON STARTUP (immediately):
    1. Send DEFAULT lat/lon (India centroid) to TB straight away.
       Dashboard is never blank — always shows something from second 1.
    2. Attempt to get real GPS from Cavli modem (attempt 1 of 5).

  STARTUP RETRY PHASE (attempts 1-5, 15 min apart):
    - If valid GPS obtained → send real coords to TB immediately.
      Switch to 12hr scheduled sends forever. Done.
    - If invalid after all 5 attempts → switch to 12hr retry phase.

  12HR RETRY PHASE (after 5 startup failures):
    - Keep retrying every 12 hours forever.
    - Modem may acquire GPS signal hours or days later — never give up.
    - When valid GPS finally obtained → send real coords to TB immediately.
      Switch to 12hr scheduled sends with real data.

  12HR SCHEDULED SEND PHASE (after valid GPS obtained):
    - Send real lat/lon to TB every 12 hours (twice a day).
    - Never send default again once real GPS is confirmed.

  STATE SUMMARY:
    STARTUP_RETRY   → trying every 15 min (up to 5 attempts)
    LONG_RETRY      → trying every 12 hr (after 5 startup failures, forever)
    CONFIRMED       → sending real GPS every 12 hr

  VALID DATA:
    lat/lon is valid if not None, not 0, in range, not exactly the default value.

  DEFAULTS (India geographic centroid):
    latitude  = 20.5937
    longitude = 78.9629

  TB PAYLOADS:
    Real GPS:    {"lat": 12.9716, "lon": 77.5946}
    Default:     {"lat": 20.5937, "lon": 78.9629, "lat_lon_default": true}

  INTEGRATION IN TLChronosProMAIN:
    At startup:
        import location_manager
        def _send_latlon(lat, lon, is_default=False):
            payload = {"lat": lat, "lon": lon}
            if is_default:
                payload["lat_lon_default"] = True
            msg_queue_buffer.add(json.dumps(payload))
        location_manager.start(cavli_database, _send_latlon)

    In scheduleSystemStatusUpload() logTypeSysParam==5 block, replace:
        OLD:
            latitude  = cavli_database.get_latitude()
            longitude = cavli_database.get_longitude()
            sendData2TBLatLong(latitude, longitude)
        NEW:
            location_manager.tick()

    On shutdown:
        location_manager.stop()
"""

import threading
import time
import logging

log = logging.getLogger("dexter-location")

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────
DEFAULT_LAT             = 20.5937   # India geographic centroid
DEFAULT_LON             = 78.9629

MAX_STARTUP_ATTEMPTS    = 5         # Fast retries at startup
STARTUP_RETRY_INTERVAL  = 900       # 15 minutes between startup retries (sec)
SCHEDULED_SEND_INTERVAL = 43200     # 12 hours — both long retry and confirmed send (sec)

# ─────────────────────────────────────────────────────────────────────────────
# States
# ─────────────────────────────────────────────────────────────────────────────
_STATE_STARTUP_RETRY = "STARTUP_RETRY"   # trying every 15 min (up to 5x)
_STATE_LONG_RETRY    = "LONG_RETRY"      # trying every 12 hr (forever)
_STATE_CONFIRMED     = "CONFIRMED"       # real GPS confirmed, sending every 12 hr

# ─────────────────────────────────────────────────────────────────────────────
# Module state
# ─────────────────────────────────────────────────────────────────────────────
_state           = _STATE_STARTUP_RETRY
_startup_attempt = 0        # how many startup attempts made so far
_lat             = None     # confirmed real latitude
_lon             = None     # confirmed real longitude
_last_sent       = 0.0      # timestamp of last TB send (any kind)
_timer           = None     # active threading.Timer
_lock            = threading.Lock()

# Injected dependencies
_cavli_db        = None
_send_fn         = None     # callable(lat, lon, is_default=False)


# ─────────────────────────────────────────────────────────────────────────────
# Validation
# ─────────────────────────────────────────────────────────────────────────────
def _valid(lat, lon) -> bool:
    """Return True if lat/lon are genuine GPS coordinates."""
    try:
        lat = float(lat)
        lon = float(lon)
    except (TypeError, ValueError):
        return False
    if lat == 0.0 or lon == 0.0:
        return False
    if not (-90.0 < lat < 90.0):
        return False
    if not (-180.0 < lon < 180.0):
        return False
    # Reject if exactly equal to default — modem returning placeholder
    if lat == DEFAULT_LAT and lon == DEFAULT_LON:
        return False
    return True


# ─────────────────────────────────────────────────────────────────────────────
# Send helpers
# ─────────────────────────────────────────────────────────────────────────────
def _send(lat, lon, is_default=False):
    global _last_sent
    try:
        if _send_fn:
            _send_fn(lat, lon, is_default)
        _last_sent = time.time()
        tag = "DEFAULT" if is_default else "GPS"
        log.info("[LOC] Sent %s to TB: lat=%.6f lon=%.6f", tag, lat, lon)
    except Exception as exc:
        log.error("[LOC] Send failed: %s", exc)


def _cancel_timer():
    global _timer
    with _lock:
        if _timer is not None:
            _timer.cancel()
            _timer = None


def _schedule_next(interval_sec, fn):
    global _timer
    _cancel_timer()
    with _lock:
        _timer = threading.Timer(interval_sec, fn)
        _timer.daemon = True
        _timer.name   = "loc-timer"
        _timer.start()


# ─────────────────────────────────────────────────────────────────────────────
# GPS fetch and state machine
# ─────────────────────────────────────────────────────────────────────────────
def _fetch_gps() -> tuple:
    """Pull lat/lon from Cavli DB. Returns (lat, lon) or (None, None)."""
    try:
        if _cavli_db:
            lat = _cavli_db.get_latitude()
            lon = _cavli_db.get_longitude()
            log.debug("[LOC] Cavli returned: lat=%s lon=%s", lat, lon)
            return lat, lon
    except Exception as exc:
        log.warning("[LOC] Cavli DB error: %s", exc)
    return None, None


def _on_startup_retry():
    """Called for each startup retry attempt (1–5), 15 min apart."""
    global _state, _startup_attempt, _lat, _lon

    with _lock:
        _startup_attempt += 1
        attempt = _startup_attempt

    log.info("[LOC] Startup GPS attempt %d/%d", attempt, MAX_STARTUP_ATTEMPTS)
    lat, lon = _fetch_gps()

    if _valid(lat, lon):
        # Real GPS obtained — confirmed state
        with _lock:
            _lat   = float(lat)
            _lon   = float(lon)
            _state = _STATE_CONFIRMED
        log.info("[LOC] Real GPS confirmed on attempt %d: lat=%.6f lon=%.6f",
                 attempt, _lat, _lon)
        _send(_lat, _lon, is_default=False)
        # Schedule 12hr repeat
        _schedule_next(SCHEDULED_SEND_INTERVAL, _on_scheduled_send)

    else:
        log.warning("[LOC] Attempt %d/%d: no valid GPS", attempt, MAX_STARTUP_ATTEMPTS)

        if attempt < MAX_STARTUP_ATTEMPTS:
            # More startup retries remaining — wait 15 min
            log.info("[LOC] Retry in %d min (attempt %d/%d coming up)",
                     STARTUP_RETRY_INTERVAL // 60, attempt + 1, MAX_STARTUP_ATTEMPTS)
            _schedule_next(STARTUP_RETRY_INTERVAL, _on_startup_retry)
        else:
            # All startup attempts exhausted — switch to long retry every 12hr
            with _lock:
                _state = _STATE_LONG_RETRY
            log.warning("[LOC] All %d startup attempts failed. "
                        "Switching to 12hr retry — will keep trying forever.",
                        MAX_STARTUP_ATTEMPTS)
            _schedule_next(SCHEDULED_SEND_INTERVAL, _on_long_retry)


def _on_long_retry():
    """
    Called every 12 hours after startup attempts exhausted.
    Keeps trying until real GPS is obtained. Never gives up.
    """
    global _state, _lat, _lon

    log.info("[LOC] Long-retry GPS attempt (12hr cycle)")
    lat, lon = _fetch_gps()

    if _valid(lat, lon):
        # Finally got real GPS
        with _lock:
            _lat   = float(lat)
            _lon   = float(lon)
            _state = _STATE_CONFIRMED
        log.info("[LOC] Real GPS finally confirmed: lat=%.6f lon=%.6f", _lat, _lon)
        _send(_lat, _lon, is_default=False)
        # Switch to 12hr confirmed sends
        _schedule_next(SCHEDULED_SEND_INTERVAL, _on_scheduled_send)
    else:
        # Still no GPS — send default again to keep TB current, retry in 12hr
        log.warning("[LOC] Long-retry: still no valid GPS — re-sending default, retry in 12hr")
        _send(DEFAULT_LAT, DEFAULT_LON, is_default=True)
        _schedule_next(SCHEDULED_SEND_INTERVAL, _on_long_retry)


def _on_scheduled_send():
    """Called every 12 hours once real GPS is confirmed."""
    global _state
    with _lock:
        lat = _lat
        lon = _lon

    log.info("[LOC] 12hr scheduled send: lat=%.6f lon=%.6f", lat, lon)
    _send(lat, lon, is_default=False)
    _schedule_next(SCHEDULED_SEND_INTERVAL, _on_scheduled_send)


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────
def start(cavli_db, send_latlon_fn):
    """
    Initialise and start the location manager. Call once at system startup.

    Args:
        cavli_db:       cavli_database instance (has get_latitude/get_longitude)
        send_latlon_fn: callable(lat, lon, is_default=False) — sends to TB.
                        Typically wraps msg_queue_buffer.add() with JSON payload.
    """
    global _cavli_db, _send_fn, _state, _startup_attempt

    _cavli_db        = cavli_db
    _send_fn         = send_latlon_fn
    _state           = _STATE_STARTUP_RETRY
    _startup_attempt = 0

    log.info("[LOC] Location manager starting.")
    log.info("[LOC]   Startup retries:  %d x every %d min",
             MAX_STARTUP_ATTEMPTS, STARTUP_RETRY_INTERVAL // 60)
    log.info("[LOC]   Long retry:       every %d hr after startup fails",
             SCHEDULED_SEND_INTERVAL // 3600)
    log.info("[LOC]   Confirmed send:   every %d hr once real GPS obtained",
             SCHEDULED_SEND_INTERVAL // 3600)
    log.info("[LOC]   Default fallback: lat=%.4f lon=%.4f", DEFAULT_LAT, DEFAULT_LON)

    # Step 1: Send default immediately — dashboard never blank
    _send(DEFAULT_LAT, DEFAULT_LON, is_default=True)

    # Step 2: Begin GPS fetch attempts in background thread
    t = threading.Thread(target=_on_startup_retry, daemon=True, name="loc-init")
    t.start()


def tick():
    """
    Called from scheduleSystemStatusUpload() logTypeSysParam==5 block.
    Replaces the old direct cavli_database.get_latitude() call.

    This function is a NO-OP because all sending is timer-driven internally.
    It exists so the integration point in the main module stays clean —
    the main module does not need to know about internal state.

    The location manager drives its own schedule via threading.Timer.
    The main module's 12hr tick (logTypeSysParam==5 every ~25min cycle)
    is NOT used for timing — internal timers are more precise.
    """
    with _lock:
        state = _state
        lat   = _lat
        lon   = _lon
    log.debug("[LOC] tick() called — state=%s lat=%s lon=%s", state, lat, lon)


def get_current() -> tuple:
    """
    Returns (lat, lon, is_confirmed).
    Useful for displaying current location in Dexter webserver or logs.
    """
    with _lock:
        if _state == _STATE_CONFIRMED and _lat is not None:
            return (_lat, _lon, True)
    return (DEFAULT_LAT, DEFAULT_LON, False)


def is_confirmed() -> bool:
    """Returns True if real GPS coordinates have been confirmed."""
    with _lock:
        return _state == _STATE_CONFIRMED


def stop():
    """Cancel all timers. Call on clean system shutdown."""
    _cancel_timer()
    log.info("[LOC] Location manager stopped.")
