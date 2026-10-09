"""Background task that deletes expired files on a fixed interval."""

from __future__ import annotations

import asyncio
import logging
from typing import Protocol

logger = logging.getLogger(__name__)


class Sweepable(Protocol):
    async def sweep(self) -> int: ...


async def run_sweeper(service: Sweepable, interval_seconds: float, stop: asyncio.Event) -> None:
    """Sweep, then sleep until the interval passes or ``stop`` is set. Errors are logged, never fatal."""
    while not stop.is_set():
        try:
            removed = await service.sweep()
            if removed:
                logger.info("Swept %d expired file(s)", removed)
        except Exception:
            logger.exception("Sweep failed")
        try:
            await asyncio.wait_for(stop.wait(), interval_seconds)
        except TimeoutError:
            pass
