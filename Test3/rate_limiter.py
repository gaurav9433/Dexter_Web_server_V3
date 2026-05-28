# rate_limiter.py
# Fixes: SEC-08 — No rate limiting on critical RPC commands
# Prevents DoS via command flooding (e.g. triggering OTA or reboot repeatedly)

"""
rate_limiter.py
Dexter HMS — Sliding window RPC rate limiter (SEC-08)

Responsibilities:
  - Prevents OTA/reboot flooding via compromised ThingsBoard or accidental RPC storm
  - Thread-safe sliding window using deque + threading.Lock
  - Pre-configured limiters: ota_limiter, reboot_limiter, debug_limiter, network_limiter

Key classes:
  - RateLimiter — configurable max_calls per window_seconds

Pre-configured limits:
  - ota_limiter     : 1 per hour
  - reboot_limiter  : 3 per hour
  - debug_limiter   : 5 per hour
  - network_limiter : 3 per hour

Dependencies: None (stdlib only)
Author: Seple Novaedge Pvt. Ltd.
"""

import time
import logging
from collections import deque
from threading import Lock

log = logging.getLogger(__name__)


class RateLimiter:
    """
    Thread-safe sliding window rate limiter.
    Tracks how many times an action was called within a rolling time window.

    Example: max_calls=1, window_seconds=3600
    → Only 1 OTA update allowed per hour.
    """

    def __init__(self, name: str, max_calls: int, window_seconds: int):
        self.name           = name
        self.max_calls      = max_calls
        self.window_seconds = window_seconds
        self._calls         = deque()
        self._lock          = Lock()

    def allow(self) -> bool:
        """
        Returns True if the action is allowed, False if rate limit is exceeded.
        Always call this BEFORE executing the protected action.
        """
        with self._lock:
            now = time.time()
            # Remove calls older than the window
            while self._calls and now - self._calls[0] > self.window_seconds:
                self._calls.popleft()

            if len(self._calls) >= self.max_calls:
                log.warning(
                    f"Rate limit exceeded for '{self.name}': "
                    f"{self.max_calls} calls already in last {self.window_seconds}s"
                )
                return False

            self._calls.append(now)
            return True

    def remaining(self) -> int:
        """Returns how many calls are still allowed in the current window."""
        with self._lock:
            now = time.time()
            while self._calls and now - self._calls[0] > self.window_seconds:
                self._calls.popleft()
            return max(0, self.max_calls - len(self._calls))


# ─── PRE-CONFIGURED LIMITERS FOR DEXTER HMS ──────────────────────────────────

# OTA update: max 1 per hour — prevents repeated firmware flash attempts
ota_limiter = RateLimiter('OTA update', max_calls=1, window_seconds=3600)

# Reboot: max 3 per hour — prevents reboot loop attacks
reboot_limiter = RateLimiter('Device reboot', max_calls=3, window_seconds=3600)

# Debug shell: max 5 per hour
debug_limiter = RateLimiter('Debug shell', max_calls=5, window_seconds=3600)

# Network config: max 3 per hour
network_limiter = RateLimiter('Network config', max_calls=3, window_seconds=3600)