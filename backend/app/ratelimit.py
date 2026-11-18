"""
ratelimit.py
In-memory sliding-window rate limiting that protects the shared embedding-provider quota.

  * per-client  -- fairness: one visitor cannot use the whole allowance.
  * global      -- the real quota guard: caps provider-bound analyses for the whole service,
                   whatever the number of distinct clients.

State is per process (the app runs a single worker on Render Free). Allowance is consumed
only when a provider call is imminent, so rejected/invalid uploads do not burn it.
"""

import ipaddress
import time
from collections import deque
from typing import Deque, Dict, Optional

from .config import MAX_TRACKED_CLIENTS, RateLimitSettings, load_rate_limit_settings

_OVERFLOW_KEY = "__overflow__"


class RateLimitExceeded(Exception):
    def __init__(self, scope: str, retry_after: float):
        super().__init__(scope)
        self.scope = scope  # "client" or "global"
        self.retry_after = max(1.0, retry_after)


def client_key(forwarded_for: Optional[str], peer: Optional[str], trusted_proxies: int) -> str:
    """
    Identify the caller. With N trusted proxies in front of us, the real client is the Nth
    entry from the right of X-Forwarded-For (entries further left are client-supplied and
    forgeable). Anything unparsable falls back to the socket peer. IPv6 groups by /64.
    """
    candidates = []
    if trusted_proxies > 0 and forwarded_for:
        parts = [p.strip() for p in forwarded_for.split(",")]
        if len(parts) >= trusted_proxies:
            candidates.append(parts[-trusted_proxies])
    if peer:
        candidates.append(peer)  # fallback when the header is absent, short or unparsable
    for candidate in candidates:
        try:
            addr = ipaddress.ip_address(candidate)
        except ValueError:
            continue
        if isinstance(addr, ipaddress.IPv6Address):
            if addr.ipv4_mapped:
                return str(addr.ipv4_mapped)
            return str(ipaddress.ip_network(f"{addr}/64", strict=False).network_address) + "/64"
        return str(addr)
    return "unknown"


class SlidingWindowLimiter:
    def __init__(self, settings: Optional[RateLimitSettings] = None, clock=time.monotonic):
        self.settings = settings or load_rate_limit_settings()
        self._clock = clock
        self._clients: Dict[str, Deque[float]] = {}
        self._global: Deque[float] = deque()

    @staticmethod
    def _prune(dq: Deque[float], cutoff: float) -> None:
        while dq and dq[0] <= cutoff:
            dq.popleft()

    def _evict_expired(self, cutoff: float) -> None:
        for k in [k for k, dq in self._clients.items() if not dq or dq[-1] <= cutoff]:
            del self._clients[k]

    def check(self, key: str) -> None:
        """Consume one unit for `key`, or raise RateLimitExceeded (consuming nothing)."""
        cfg = self.settings
        now = self._clock()
        cutoff = now - cfg.window_seconds

        if cfg.global_limit:
            self._prune(self._global, cutoff)
            if len(self._global) >= cfg.global_limit:
                raise RateLimitExceeded("global", self._global[0] + cfg.window_seconds - now)

        dq = None
        if cfg.per_client:
            if key not in self._clients and len(self._clients) >= MAX_TRACKED_CLIENTS:
                self._evict_expired(cutoff)
                if len(self._clients) >= MAX_TRACKED_CLIENTS:
                    key = _OVERFLOW_KEY  # table full: new clients share one bucket
            dq = self._clients.setdefault(key, deque())
            self._prune(dq, cutoff)
            if len(dq) >= cfg.per_client:
                raise RateLimitExceeded("client", dq[0] + cfg.window_seconds - now)

        if dq is not None:
            dq.append(now)
        if cfg.global_limit:
            self._global.append(now)


_limiter: Optional[SlidingWindowLimiter] = None


def get_rate_limiter() -> SlidingWindowLimiter:
    global _limiter
    if _limiter is None:
        _limiter = SlidingWindowLimiter()
    return _limiter


def reset_rate_limiter() -> None:
    global _limiter
    _limiter = None
