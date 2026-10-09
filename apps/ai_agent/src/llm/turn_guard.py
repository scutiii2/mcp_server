"""Shared per-turn budgets and repeated-call detection for tool loops."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from src.core.catalog import catalog


class TurnStopped(Exception):
    """A guard ended the turn with an explanation safe to show the user."""


@catalog
class TurnGuard:
    """Bound elapsed time, reported tokens, and identical calls within one turn.

    Usage is reported at round boundaries, so a token cap may overshoot by
    one response. Timeouts interrupt async waits; synchronous tools already
    running on a worker cannot be forcibly undone.
    """

    def __init__(self, max_tokens: int = 100_000, max_seconds: float = 300) -> None:
        self.max_tokens = max_tokens
        self.max_seconds = max_seconds
        self._last_call: str | None = None
        self._repetitions = 0

    def timeout(self) -> asyncio.Timeout:
        """Apply the turn deadline to the entire provider loop."""
        return asyncio.timeout(self.max_seconds)

    def check_tokens(self, total: int | None) -> None:
        if total is not None and total >= self.max_tokens:
            raise TurnStopped(f"Stopped: this turn reached its token budget ({self.max_tokens:,} tokens).")

    def check_call(self, name: str, arguments: Any) -> None:
        key = json.dumps([name, arguments], sort_keys=True, separators=(",", ":"))
        self._repetitions = self._repetitions + 1 if key == self._last_call else 1
        self._last_call = key
        if self._repetitions >= 3:
            raise TurnStopped(f"Stopped: tool '{name}' repeated the same arguments three times without progress.")

    def time_message(self) -> str:
        return f"Stopped: this turn reached its time budget ({self.max_seconds:g} seconds)."
