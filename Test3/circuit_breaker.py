# -*- coding: utf-8 -*-
"""
circuit_breaker.py — Per-integration circuit breaker for Dexter HMS

ARCH-04 FIX: NVR/DVR polling modules previously retried failed HTTP calls
indefinitely with no state tracking. When a vendor NVR is offline, each
poll cycle wastes network resources and blocks the watchdog reset.

This module provides a lightweight CircuitBreaker class with four states:

    HEALTHY     — Normal operation. All requests pass through.
    DEGRADED    — failure_count >= degraded_threshold.
                  Requests still pass through but alerts are raised.
    DISCONNECTED — failure_count >= open_threshold.
                  Requests are blocked immediately (fail-fast).
                  The breaker waits half_open_timeout_sec then probes.
    RECOVERING  — One probe attempt allowed.
                  Success → HEALTHY. Failure → back to DISCONNECTED.

Configuration via settings.yaml:
    nvr.circuit_breaker_degraded_threshold     (default: 2)
    nvr.circuit_breaker_open_threshold         (default: 5)
    nvr.circuit_breaker_half_open_timeout_sec  (default: 60)
    nvr.circuit_breaker_recovery_timeout_sec   (default: 300)

Usage:
    from circuit_breaker import CircuitBreaker

    cb = CircuitBreaker(name="HikvisionNVR1")

    if cb.allow_request():
        try:
            result = call_nvr_api()
            cb.record_success()
        except Exception as e:
            cb.record_failure(str(e))
    else:
        log.warning("Circuit open for HikvisionNVR1 — skipping poll")
"""

from __future__ import annotations

import logging
import threading
import time
from enum import Enum, auto
from typing import Optional

log = logging.getLogger(__name__)

# ── Load thresholds from settings.yaml ───────────────────────────────────────
try:
    from dexter_config import settings as _cfg
    _DEGRADED_THRESHOLD    = _cfg.nvr.circuit_breaker_degraded_threshold
    _OPEN_THRESHOLD        = _cfg.nvr.circuit_breaker_open_threshold
    _HALF_OPEN_TIMEOUT     = _cfg.nvr.circuit_breaker_half_open_timeout_sec
    _RECOVERY_TIMEOUT      = _cfg.nvr.circuit_breaker_recovery_timeout_sec
except Exception:
    # Sensible defaults if settings.yaml is not yet deployed
    _DEGRADED_THRESHOLD    = 2
    _OPEN_THRESHOLD        = 5
    _HALF_OPEN_TIMEOUT     = 60
    _RECOVERY_TIMEOUT      = 300


class CBState(Enum):
    HEALTHY      = auto()
    DEGRADED     = auto()
    DISCONNECTED = auto()
    RECOVERING   = auto()


class CircuitBreaker:
    """
    Thread-safe circuit breaker for a single named integration.

    Parameters:
        name:                  Human-readable integration name (e.g. "HikvisionNVR1").
                               Used in log messages and telemetry.
        degraded_threshold:    Consecutive failures before DEGRADED.
        open_threshold:        Consecutive failures before DISCONNECTED.
        half_open_timeout_sec: Seconds to wait in DISCONNECTED before probing.
        recovery_timeout_sec:  Max backoff seconds in DISCONNECTED state.
    """

    def __init__(
        self,
        name:                  str  = "integration",
        degraded_threshold:    int  = _DEGRADED_THRESHOLD,
        open_threshold:        int  = _OPEN_THRESHOLD,
        half_open_timeout_sec: int  = _HALF_OPEN_TIMEOUT,
        recovery_timeout_sec:  int  = _RECOVERY_TIMEOUT,
    ) -> None:
        self.name                  = name
        self.degraded_threshold    = degraded_threshold
        self.open_threshold        = open_threshold
        self.half_open_timeout    = half_open_timeout_sec
        self.recovery_timeout      = recovery_timeout_sec

        self._state:          CBState   = CBState.HEALTHY
        self._failure_count:  int       = 0
        self._last_failure:   float     = 0.0
        self._opened_at:      float     = 0.0
        self._lock:           threading.Lock = threading.Lock()

    # ── Public API ────────────────────────────────────────────────────────────

    @property
    def state(self) -> CBState:
        return self._state

    def allow_request(self) -> bool:
        """
        Returns True if the request should proceed, False if it should be
        blocked (circuit is DISCONNECTED and probe window has not opened yet).
        """
        with self._lock:
            if self._state == CBState.HEALTHY:
                return True

            if self._state == CBState.DEGRADED:
                return True   # degrade gracefully — still pass requests

            if self._state == CBState.DISCONNECTED:
                elapsed = time.time() - self._opened_at
                if elapsed >= self.half_open_timeout:
                    log.info("[CB:%s] Half-open probe window — allowing one request",
                             self.name)
                    self._state = CBState.RECOVERING
                    return True
                log.debug("[CB:%s] Circuit DISCONNECTED — blocking request (%ds remaining)",
                          self.name, int(self.half_open_timeout - elapsed))
                return False

            if self._state == CBState.RECOVERING:
                # Only one probe at a time; further requests blocked until result
                return False

            return True

    def record_success(self) -> None:
        """Call after a successful API response."""
        with self._lock:
            prev_state = self._state
            self._failure_count = 0
            self._state = CBState.HEALTHY

            if prev_state != CBState.HEALTHY:
                log.info("[CB:%s] RECOVERED — state %s → HEALTHY",
                         self.name, prev_state.name)

    def record_failure(self, reason: str = "") -> None:
        """Call after a failed API response."""
        with self._lock:
            self._failure_count += 1
            self._last_failure = time.time()

            prev_state = self._state

            if self._state == CBState.RECOVERING:
                # Probe failed — back to DISCONNECTED with extended backoff
                backoff = min(self.half_open_timeout * 2, self.recovery_timeout)
                self._opened_at = time.time() - self.half_open_timeout + backoff
                self._state = CBState.DISCONNECTED
                log.warning("[CB:%s] Recovery probe FAILED — back to DISCONNECTED "
                            "(next probe in %ds). Reason: %s",
                            self.name, backoff, reason)
                return

            if self._failure_count >= self.open_threshold:
                if self._state != CBState.DISCONNECTED:
                    self._state = CBState.DISCONNECTED
                    self._opened_at = time.time()
                    log.error("[CB:%s] OPENED — %d consecutive failures → DISCONNECTED. "
                              "Reason: %s", self.name, self._failure_count, reason)
                return

            if self._failure_count >= self.degraded_threshold:
                if self._state != CBState.DEGRADED:
                    self._state = CBState.DEGRADED
                    log.warning("[CB:%s] %d failures → DEGRADED. Reason: %s",
                                self.name, self._failure_count, reason)
                return

            log.debug("[CB:%s] failure_count=%d. Reason: %s",
                      self.name, self._failure_count, reason)

    def reset(self) -> None:
        """Manually force the breaker back to HEALTHY (admin/test use)."""
        with self._lock:
            self._state         = CBState.HEALTHY
            self._failure_count = 0
            log.info("[CB:%s] Manually reset to HEALTHY", self.name)

    def status(self) -> dict:
        """Return a serialisable status snapshot (for ThingsBoard telemetry)."""
        with self._lock:
            return {
                "name":          self.name,
                "state":         self._state.name,
                "failure_count": self._failure_count,
                "last_failure":  self._last_failure,
            }


# ── Module-level registry ─────────────────────────────────────────────────────
# One breaker per integration, shared across polling functions.
_REGISTRY: dict[str, CircuitBreaker] = {}
_REG_LOCK = threading.Lock()


def get_breaker(name: str) -> CircuitBreaker:
    """
    Return the CircuitBreaker for the given integration name.
    Creates one on first call.

    Usage:
        cb = get_breaker("HikvisionNVR1")
        cb = get_breaker("DahuaNVR1")
        cb = get_breaker("CP_PlusNVR1")
        cb = get_breaker("HikvisionBioMetric1")
    """
    with _REG_LOCK:
        if name not in _REGISTRY:
            _REGISTRY[name] = CircuitBreaker(name=name)
            log.info("[CB registry] Created breaker for '%s'", name)
        return _REGISTRY[name]


def all_statuses() -> list[dict]:
    """Return status snapshots for all registered breakers (for health telemetry)."""
    with _REG_LOCK:
        return [cb.status() for cb in _REGISTRY.values()]
