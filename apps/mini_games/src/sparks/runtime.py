"""Time and randomness behind small interfaces, so tests control both.

`SeededRandom` is stateless apart from (seed, counter): draw n is derived from
the seed and n alone, so a battle's random stream is saved as two integers and
a restart or retry replays the same draws instead of rerolling.
"""

from __future__ import annotations

import random
import secrets
import time
from typing import Protocol


class Clock(Protocol):
    def now(self) -> float:
        """Seconds since the epoch, UTC."""


class RandomSource(Protocol):
    def next(self) -> float:
        """A float in [0, 1)."""


class SystemClock:
    def now(self) -> float:
        return time.time()


class SystemRandom:
    """Unseeded randomness for rolls that need no replay (encounters, awards)."""

    def __init__(self) -> None:
        self._random = random.SystemRandom()

    def next(self) -> float:
        return self._random.random()


class SeededRandom:
    def __init__(self, seed: int, counter: int = 0) -> None:
        self.seed = seed
        self.counter = counter

    def next(self) -> float:
        value = random.Random(f"{self.seed}:{self.counter}").random()
        self.counter += 1
        return value


class RecordingRandom:
    """Wraps a source and remembers every draw, to store with a round result."""

    def __init__(self, inner: RandomSource) -> None:
        self._inner = inner
        self.draws: list[float] = []

    def next(self) -> float:
        value = self._inner.next()
        self.draws.append(value)
        return value


def new_seed() -> int:
    return secrets.randbits(62)


def new_id() -> str:
    """A server-created identifier; clients never choose ids."""
    return secrets.token_urlsafe(9)
