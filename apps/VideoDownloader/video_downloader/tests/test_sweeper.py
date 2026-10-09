import asyncio

from src.store.sweeper import run_sweeper


class FakeService:
    def __init__(self):
        self.calls = 0

    async def sweep(self) -> int:
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("boom")  # must not stop the loop
        return 0


async def test_sweeper_runs_repeatedly_and_survives_errors():
    service = FakeService()
    stop = asyncio.Event()
    task = asyncio.create_task(run_sweeper(service, 0.01, stop))
    await asyncio.sleep(0.1)
    stop.set()
    await task
    assert service.calls >= 2
