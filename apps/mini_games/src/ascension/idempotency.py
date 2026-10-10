"""Exactly-once mutations.

Every mutation carries an idempotency key. The response is stored in the same
transaction as the change, so a retry returns the original result and never
repeats the change or rerolls its randomness. Reusing a key for a different
request is a conflict.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Awaitable, Callable

from src.ascension.errors import IdempotencyConflict, InvalidRequest
from src.ascension.repository import AscendedRepository, AscendedTransaction
from src.ascension.runtime import Clock

MAX_KEY_LENGTH = 200


class IdempotentWriter:
    def __init__(self, repository: AscendedRepository, clock: Clock) -> None:
        self._repo, self._clock = repository, clock

    @staticmethod
    def _check_key(key: str) -> None:
        if not key or len(key) > MAX_KEY_LENGTH:
            raise InvalidRequest(f"the idempotency key must be 1 to {MAX_KEY_LENGTH} characters")

    @staticmethod
    def fingerprint(operation: str, payload: Any) -> str:
        text = json.dumps({"operation": operation, "payload": payload}, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    @staticmethod
    def _match(cached, fingerprint: str) -> dict[str, Any] | None:
        if cached is None:
            return None
        if cached.request_hash != fingerprint:
            raise IdempotencyConflict("this idempotency key was already used for a different request")
        return cached.response

    async def lookup(self, owner: str, key: str, operation: str, payload: Any) -> dict[str, Any] | None:
        """The stored response for this exact request, or None if it has not run."""
        self._check_key(key)
        async with self._repo.transaction() as tx:
            return self._match(await tx.get_idempotent(owner, key), self.fingerprint(operation, payload))

    async def commit(
        self, owner: str, key: str, operation: str, payload: Any,
        work: Callable[[AscendedTransaction], Awaitable[dict[str, Any]]],
    ) -> dict[str, Any]:
        """Run `work` and store its response in one transaction (or replay the stored one)."""
        self._check_key(key)
        fingerprint = self.fingerprint(operation, payload)
        async with self._repo.transaction() as tx:
            cached = self._match(await tx.get_idempotent(owner, key), fingerprint)
            if cached is not None:
                return cached
            response = await work(tx)
            await tx.put_idempotent(owner, key, fingerprint, response, self._clock.now())
            return response
