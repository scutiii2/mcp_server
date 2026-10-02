"""HMAC-signed, expiring download links. A link works without a cookie, so
Ember's download cards and other machines can open it, but only until it expires."""

from __future__ import annotations

import hashlib
import hmac
import time
from collections.abc import Callable


class LinkSigner:
    def __init__(self, key: bytes, ttl_seconds: int, clock: Callable[[], float] = time.time) -> None:
        self._key = key
        self._ttl = ttl_seconds
        self._clock = clock

    def _digest(self, file_id: str, exp: int) -> str:
        return hmac.new(self._key, f"{file_id}.{exp}".encode("utf-8"), hashlib.sha256).hexdigest()

    def sign(self, file_id: str) -> tuple[int, str]:
        """(expiry as unix seconds, hex signature)."""
        exp = int(self._clock() + self._ttl)
        return exp, self._digest(file_id, exp)

    def verify(self, file_id: str, exp: int, sig: str) -> bool:
        if exp < self._clock():
            return False
        return hmac.compare_digest(
            self._digest(file_id, exp).encode("ascii"),
            sig.encode("utf-8", "replace"),
        )
