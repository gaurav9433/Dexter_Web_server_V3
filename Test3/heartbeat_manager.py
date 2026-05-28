# -*- coding: utf-8 -*-
"""
heartbeat_manager.py — Centralised heartbeat logic for Dexter HMS

Implements four heartbeat behaviours:

  1. STARTUP SEQUENCE
     Called once after system_on is sent.
     Sends each connected device heartbeat one-by-one via sendData2TB(),
     with a 0.5s gap between each so ThingsBoard timestamps are distinct.

  2. PERIODIC GROUP BURST (every 5 minutes)
     Sends ALL connected device heartbeats in ONE single payload via
     raw_send_fn() so the publisher delivers them in a single MQTT message.
     Payload format: {"heartbeat_BAS":"online","heartbeat_FAS":"online",...}

  3. OFFLINE HEARTBEAT ON POWER-OFF
     Called immediately after generateReportMsg(PZx,'alarm_system_off').
     Sends heartbeat_<TYPE>_offline via sendData2TB() — one message, immediate.

  4. ONLINE HEARTBEAT ON POWER-RESTORE
     Called immediately after generateReportMsg(PZx,'alarm_system_on').
     Sends heartbeat_<TYPE> via sendData2TB() — one message, immediate.

Why behaviours 1/3/4 use sendData2TB and behaviour 2 uses raw_send_fn:
  - Startup: individual timestamps are intentional (0.5s apart)
  - Offline/Online: single device event, fires immediately
  - Periodic: ALL devices in ONE payload → ONE MQTT publish → no 30s delay

Integration in TLChronosProMAIN_391.py
---------------------------------------
  # 1. Import:
      from heartbeat_manager import HeartbeatManager

  # 2. After power_zone_active_device_counter (~line 21210):
      hb_manager = HeartbeatManager(
          send_fn                  = sendData2TB,
          raw_send_fn              = lambda d: msg_queue_buffer.add(json.dumps(d)),
          device_counter           = power_zone_active_device_counter,
          power_zone_settings      = powerZoneSettings,
          get_active_integration_fn= get_active_integration,
          check_bas_integration_fn = lambda: logical_params_module.get_parameter("active_integration_texecom_bas"),
          check_bacs_integration_fn= lambda: logical_params_module.get_parameter("active_integration_hikvision_biometric"),
          check_hikvision_status_fn= check_hikvision_status,
          check_hikvision_nvr_fn   = check_hikvision_nvr,
          check_dahua_nvr_fn       = check_dahua_nvr,
          check_cp_plus_nvr_fn     = check_cp_plus_nvr,
          check_texecom_bas_fn     = check_texecom_bas,
      )

  # 3. After sendData2TB("system_on"):
      hb_manager.send_startup_sequence()

  # 4. Inside scheduleSystemStatusUpload(), tick1Sec4 block:
      hb_manager.tick()

  # 5. After every generateReportMsg(PZx,'alarm_system_off') — 16 sites:
      hb_manager and hb_manager.send_offline_heartbeat(PZx)

  # 6. After every generateReportMsg(PZx,'alarm_system_on') — 16 sites:
      hb_manager and hb_manager.send_online_heartbeat(PZx)

Author: Seple Novaedge Pvt. Ltd.
"""

from __future__ import annotations

import json
import logging
from typing import Callable, Dict, Optional

log = logging.getLogger(__name__)

# ── Timing ───────────────────────────────────────────────────────────────────
# tick1Sec4 fires every 0.5 s (DELAY_1SEC=4 → 5 × 0.1 s = 0.5 s).
# 5 min = 300 s  →  300 / 0.5 = 600 ticks.
HEARTBEAT_PERIODIC_TICKS = 600      # 600 × 0.5 s = 300 s = 5 min
# ── Device type → heartbeat key maps ─────────────────────────────────────────
# Used by sendData2TB path (startup, offline, online)
_ONLINE_HB: Dict[str, str] = {
    'BAS':       'heartbeat_BAS',
    'FAS':       'heartbeat_FAS',
    'TIME_LOCK': 'heartbeat_time_lock',
    'BACS':      'heartbeat_access_control',
    'CCTV':      'heartbeat_CCTV',
    'IAS':       'heartbeat_IAS',
}

_OFFLINE_HB: Dict[str, str] = {
    'BAS':       'heartbeat_BAS_offline',
    'FAS':       'heartbeat_FAS_offline',
    'TIME_LOCK': 'heartbeat_time_lock_offline',
    'BACS':      'heartbeat_access_control_offline',
    'CCTV':      'heartbeat_CCTV_offline',
    'IAS':       'heartbeat_IAS_offline',
}

# Canonical send order
DEVICE_ORDER = ('BAS', 'FAS', 'TIME_LOCK', 'BACS', 'CCTV', 'IAS')


class HeartbeatManager:
    """
    Manages all four heartbeat behaviours for Dexter HMS.

    Parameters
    ----------
    send_fn : callable
        sendData2TB — used for startup, offline, and online heartbeats.
        Wraps the value in the standard payload envelope
        {branch, log_type, zone_no, date, time}.

    raw_send_fn : callable
        Accepts a dict and pushes it directly to msg_queue_buffer as JSON.
        Used ONLY for the periodic group burst so all devices go in one
        MQTT message.
        Pass: lambda d: msg_queue_buffer.add(json.dumps(d))

    device_counter : PowerZoneActiveDeviceCounter
        Tracks which devices are currently online (counter > 0 = online).

    power_zone_settings : list
        Live reference to the global powerZoneSettings list.

    get_active_integration_fn / check_hikvision_status_fn /
    check_hikvision_nvr_fn / check_dahua_nvr_fn / check_cp_plus_nvr_fn :
        Optional callables for IP integration liveness checks.

    check_bas_integration_fn :
        lambda: logical_params_module.get_parameter("active_integration_texecom_bas")
        Returns 1 when Texecom BAS active integration is enabled in the DB.

    check_texecom_bas_fn :
        check_texecom_bas — TCP socket probe to Texecom panel.
        Returns "Online" / "Offline" / "Disabled" / "No Config".
    """

    def __init__(
        self,
        send_fn:                    Callable[[str], None],
        raw_send_fn:                Callable[[dict], None],
        device_counter,
        power_zone_settings:        list,
        get_active_integration_fn:  Optional[Callable[[], int]]    = None,
        check_bas_integration_fn:   Optional[Callable[[], int]]    = None,
        check_bacs_integration_fn:  Optional[Callable[[], int]]    = None,
        check_hikvision_status_fn:  Optional[Callable[[str], str]] = None,
        check_hikvision_nvr_fn:     Optional[Callable[[], str]]    = None,
        check_dahua_nvr_fn:         Optional[Callable[[], str]]    = None,
        check_cp_plus_nvr_fn:       Optional[Callable[[], str]]    = None,
        check_texecom_bas_fn:       Optional[Callable[[], str]]    = None,
        check_amc_intg_fn:          Optional[Callable[[], int]]    = None,
        check_amc_bas_fn:           Optional[Callable[[], str]]    = None,
    ) -> None:
        self._send               = send_fn
        self._raw_send           = raw_send_fn
        self._counter            = device_counter
        self._pz_settings        = power_zone_settings
        self._get_integration    = get_active_integration_fn
        self._check_bas_intg     = check_bas_integration_fn
        self._check_bacs_intg    = check_bacs_integration_fn
        self._check_hik_status   = check_hikvision_status_fn
        self._check_hik_nvr      = check_hikvision_nvr_fn
        self._check_dahua_nvr    = check_dahua_nvr_fn
        self._check_cp_plus_nvr  = check_cp_plus_nvr_fn
        self._check_texecom_bas  = check_texecom_bas_fn
        self._check_amc_intg     = check_amc_intg_fn
        self._check_amc_bas      = check_amc_bas_fn

        self._tick_count    = 0
        self._startup_done  = False

        log.info(
            "[HeartbeatManager] Initialised — periodic interval=%d ticks (%.0fs)",
            HEARTBEAT_PERIODIC_TICKS, HEARTBEAT_PERIODIC_TICKS * 0.5,
        )

    # ── Public API ────────────────────────────────────────────────────────────

    def send_startup_sequence(self) -> None:
        """
        Behaviour 1 — Startup burst (same format as 5-min periodic).

        Sends ONE flat dict containing the gateway + all connected devices
        in a single raw_send_fn() call — identical payload structure to
        _send_periodic_heartbeats(). No individual sends, no gap.

        Payload example:
            {"heartbeat": "online", "heartbeat_BAS": "online", "heartbeat_CCTV": "online"}
        """
        if self._startup_done:
            log.warning("[HeartbeatManager] send_startup_sequence() called more than once — ignored")
            return

        self._startup_done = True
        device_counts = self._count_device_instances()
        log.info("[HeartbeatManager] Startup burst — device_counts=%s", device_counts)

        payload: Dict[str, str] = {"heartbeat": "online"}
        for device_type in DEVICE_ORDER:
            if self._is_connected(device_type, device_counts):
                payload[_ONLINE_HB[device_type]] = 'online'

        log.info("[HeartbeatManager] Startup burst → %s", list(payload.keys()))
        self._raw_send(payload)

    def tick(self) -> None:
        """
        Behaviour 2 driver — call once per tick1Sec4 pulse (every 0.5s).
        Fires _send_periodic_heartbeats() every 5 minutes.
        """
        self._tick_count += 1
        if self._tick_count >= HEARTBEAT_PERIODIC_TICKS:
            self._tick_count = 0
            self._send_periodic_heartbeats()

    def send_offline_heartbeat(self, device_type: str) -> None:
        """
        Behaviour 3 — Immediate offline heartbeat on power-off.

        Uses raw_send_fn() with flat key so TB stores the dedicated key
        (e.g. "heartbeat_BAS_offline" = "offline"), consistent with the
        periodic burst format. Fires in the same loop tick as the power-off event.

        Payload: {"heartbeat_BAS_offline": "offline"}
        """
        if not isinstance(device_type, str):
            return
        key = _OFFLINE_HB.get(device_type)
        if key:
            self._raw_send({key: 'offline'})
            log.info("[HeartbeatManager] Offline HB → %s = offline (device: %s)", key, device_type)
        else:
            log.debug("[HeartbeatManager] send_offline_heartbeat: unknown type=%r", device_type)

    def send_online_heartbeat(self, device_type: str) -> None:
        """
        Behaviour 4 — Immediate online heartbeat on power-restore.

        Uses raw_send_fn() with flat key so TB stores the dedicated key
        (e.g. "heartbeat_BAS" = "online"), consistent with the periodic burst
        format. Fires in the same loop tick as the power-restore event.

        Payload: {"heartbeat_BAS": "online"}
        """
        if not isinstance(device_type, str):
            return
        key = _ONLINE_HB.get(device_type)
        if key:
            self._raw_send({key: 'online'})
            log.info("[HeartbeatManager] Online HB → %s = online (device: %s)", key, device_type)
        else:
            log.debug("[HeartbeatManager] send_online_heartbeat: unknown type=%r", device_type)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _send_periodic_heartbeats(self) -> None:
        """
        Behaviour 2 — 5-min group burst.

        Builds ONE flat dict with a unique key per connected device and pushes
        it via raw_send_fn() — ONE msg_queue_buffer entry — ONE MQTT publish.

        ThingsBoard receives the dict on v1/devices/me/telemetry. Because
        every key is unique, all devices are stored simultaneously.

        Payload example (3 devices connected):
            {
                "heartbeat_BAS":   "online",
                "heartbeat_FAS":   "online",
                "heartbeat_CCTV":  "online"
            }

        Why NOT a log_type array:
            A JSON array [{"log_type":"heartbeat_BAS"},{"log_type":"heartbeat_FAS"},...]
            has the same key "log_type" repeated. ThingsBoard processes elements
            sequentially and the last value overwrites all previous ones — only
            "heartbeat_IAS" would be stored. The flat dict avoids this entirely.

        Devices that are offline (counter == 0 or NVR unreachable) are omitted.
        """
        device_counts = self._count_device_instances()

        # Gateway (panel) heartbeat is always first in the burst
        payload: Dict[str, str] = {"heartbeat": "online"}

        for device_type in DEVICE_ORDER:
            if self._is_connected(device_type, device_counts):
                key = _ONLINE_HB[device_type]   # e.g. "heartbeat_BAS"
                payload[key] = 'online'

        log.info("[HeartbeatManager] Periodic burst → %s", list(payload.keys()))
        self._raw_send(payload)

    def _count_device_instances(self) -> Dict[str, int]:
        """Mirror count_device_instances(powerZoneSettings) from main file."""
        _PZ_TYPE_MAP = {1:'BAS', 2:'FAS', 3:'TIME_LOCK', 4:'BACS', 5:'CCTV', 6:'IAS'}
        counts = {dt: 0 for dt in DEVICE_ORDER}
        try:
            pzs = self._pz_settings
            for i in range(0, len(pzs) - 2, 3):
                status      = pzs[i]
                device_code = pzs[i + 2]
                if status == 1 and device_code in _PZ_TYPE_MAP:
                    counts[_PZ_TYPE_MAP[device_code]] = 1
        except (IndexError, TypeError) as exc:
            log.error("[HeartbeatManager] powerZoneSettings scan error: %s", exc)
        return counts

    def _is_connected(self, device_type: str, device_counts: Dict[str, int]) -> bool:
        """Double-guard: hardware config + live status. Mirrors steps 6-11 logic."""
        if device_counts.get(device_type, 0) == 0:
            return False

        integration_active = (
            self._get_integration() == 1
            if self._get_integration else False
        )

        if device_type == 'BAS':
            # BAS covers BOTH Texecom and AMC X412B intrusion panels.
            # A site will have ONE of them, not both.
            # Logic:
            #   1. global integration ON?              — get_active_integration()
            #   2a. Texecom integration ON?            — active_integration_texecom_bas
            #       → live TCP probe: check_texecom_bas() == 'Online'
            #   2b. AMC integration ON?                — active_integration_amc_bas
            #       → passive flag: check_amc_bas() == 'Online' (set by amc dexter_state_hook)
            #   fallback: hardware counter (no active integration configured)

            if integration_active:
                # Check Texecom BAS
                texecom_intg_on = (
                    self._check_bas_intg() == 1
                    if self._check_bas_intg else False
                )
                if texecom_intg_on and self._check_texecom_bas:
                    return self._check_texecom_bas() == 'Online'

                # Check AMC BAS
                amc_intg_on = (
                    self._check_amc_intg() == 1
                    if self._check_amc_intg else False
                )
                if amc_intg_on and self._check_amc_bas:
                    return self._check_amc_bas() == 'Online'

            return self._counter.get_counter('BAS') > 0

        if device_type == 'BACS':
            # BACS needs TWO flags:
            #   1. get_active_integration() == 1  — global integration switch
            #   2. active_integration_hikvision_biometric == 1  — BACS-specific switch
            bacs_integration_on = (
                self._check_bacs_intg() == 1
                if self._check_bacs_intg else False
            )
            if integration_active and bacs_integration_on:
                return bool(self._check_hik_status and
                            self._check_hik_status('HikvisionBioMetric1') == 'Active')
            return self._counter.get_counter('BACS') > 0

        if device_type == 'CCTV':
            if integration_active:
                if self._check_hik_nvr and self._check_hik_nvr() == 'Active':
                    return True
                if self._check_dahua_nvr and self._check_dahua_nvr() == 'Active':
                    return True
                if self._check_cp_plus_nvr and self._check_cp_plus_nvr() == 'Active':
                    return True
                return False
            return self._counter.get_counter('CCTV') > 0

        return self._counter.get_counter(device_type) > 0
