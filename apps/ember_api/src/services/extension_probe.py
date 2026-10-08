"""The live status of a private extension: connected or not, and its tools.

`ai_agent` makes the connection (it holds the address guard); this asks it
through the gateway and remembers the answer for a minute per account and
extension, keyed by what was asked (url and headers), so an edit is probed at
once. At most `concurrency` probes run at a time. A probe that could not be
asked at all (`unknown`) is not remembered.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections.abc import Callable
from dataclasses import dataclass

from src.services.agent_gateway import AgentCallError, AgentGateway, Caller
from src.services.user_extension_service import UNREADABLE_MESSAGE, StoredExtension

TTL_SECONDS = 60.0
CONCURRENCY = 5
UNKNOWN_MESSAGE = "Couldn't check right now"


@dataclass(frozen=True)
class ProbeResult:
    # "connected", "error" (the agent tried and could not), or "unknown" (not tried).
    status: str
    error: str | None
    tools: tuple[str, ...]


NO_AGENT = ProbeResult("unknown", "No agent is running", ())


def _fingerprint(stored: StoredExtension) -> str:
    payload = json.dumps([stored.row.url, sorted((stored.headers or {}).items())])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class ExtensionProbe:
    def __init__(
        self,
        gateway: AgentGateway,
        *,
        ttl: float = TTL_SECONDS,
        concurrency: int = CONCURRENCY,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._gateway = gateway
        self._ttl = ttl
        self._clock = clock
        self._semaphore = asyncio.Semaphore(concurrency)
        self._cache: dict[tuple[int, str], tuple[str, float, ProbeResult]] = {}

    async def check(
        self, agent_url: str | None, caller: Caller, account_id: int, stored: StoredExtension
    ) -> ProbeResult:
        if not stored.readable:
            return ProbeResult("error", UNREADABLE_MESSAGE, ())
        if agent_url is None:
            return NO_AGENT
        key = (account_id, stored.row.slug)
        fingerprint = _fingerprint(stored)
        cached = self._cache.get(key)
        if cached is not None and cached[0] == fingerprint and cached[1] > self._clock():
            return cached[2]
        try:
            async with self._semaphore:
                answer = await self._gateway.probe_extension(
                    agent_url, caller, extension_url=stored.row.url, headers=stored.headers or None
                )
        except AgentCallError:
            return ProbeResult("unknown", UNKNOWN_MESSAGE, ())
        status = answer.get("status") if answer.get("status") in ("connected", "error") else "unknown"
        result = ProbeResult(status, answer.get("error"), tuple(answer.get("tools") or ()))
        if status != "unknown":
            self._cache[key] = (fingerprint, self._clock() + self._ttl, result)
        return result

    def forget(self, account_id: int, slug: str) -> None:
        self._cache.pop((account_id, slug), None)
