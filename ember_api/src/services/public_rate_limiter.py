"""A per-IP request limit for the routes that need no login (shared chats).

In memory and synchronous: it does no I/O, and a restart forgetting the
counts only ever lets a burst through once. The table is bounded, so a flood
of addresses cannot grow it without limit.
"""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Callable
from time import monotonic


class PublicReadLimiter:
    def __init__(
        self,
        max_requests: int = 60,
        window_seconds: float = 60.0,
        *,
        max_tracked_ips: int = 10_000,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self._max = max_requests
        self._window = window_seconds
        self._max_tracked = max_tracked_ips
        self._clock = clock
        self._hits: dict[str, deque[float]] = {}

    def retry_after(self, ip: str) -> int | None:
        """Records this request and returns None, or, when `ip` has used up
        its window, returns the seconds to wait (and records nothing, so
        hammering during the wait does not extend it)."""
        now = self._clock()
        hits = self._hits.get(ip)
        if hits is None:
            self._make_room(now)
            hits = self._hits[ip] = deque()
        while hits and hits[0] <= now - self._window:
            hits.popleft()
        if len(hits) >= self._max:
            return max(1, math.ceil(hits[0] + self._window - now))
        hits.append(now)
        return None

    def _make_room(self, now: float) -> None:
        if len(self._hits) < self._max_tracked:
            return
        # Idle addresses first, then the oldest-seen ones.
        for ip in [ip for ip, hits in self._hits.items() if not hits or hits[-1] <= now - self._window]:
            del self._hits[ip]
        while len(self._hits) >= self._max_tracked:
            del self._hits[next(iter(self._hits))]
