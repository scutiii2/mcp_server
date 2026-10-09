from __future__ import annotations

import asyncio

from src.store.sweeper import run_sweeper


class FakeService:
    def __init__(self) -> None:
        self.calls = 0

    async def sweep(self) -> int:
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("disk hiccup")  # must not kill the loop
        return 0


async def test_sweeper_runs_until_stopped_and_survives_errors():
    service = FakeService()
    stop = asyncio.Event()

    task = asyncio.create_task(run_sweeper(service, 0.01, stop))
    await asyncio.sleep(0.05)
    stop.set()
    await asyncio.wait_for(task, 1)

    assert service.calls >= 2
