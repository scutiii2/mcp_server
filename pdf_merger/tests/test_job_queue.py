from __future__ import annotations

import asyncio

import pytest

from src.errors import ErrorCode, MergerError
from src.jobs.job_queue import JobQueue


async def collect(job) -> list[dict]:
    return [event async for event in job.stream()]


async def test_successful_job_streams_queued_progress_done():
    queue = JobQueue(max_concurrent=1, timeout_seconds=5)

    async def work(progress):
        progress(1)
        progress(2)
        await asyncio.sleep(0)
        return {"file_id": "f_x"}

    job = queue.submit("web:1", 2, work)
    events = await collect(job)

    assert events[0] == {"type": "queued", "total": 2}
    assert {"type": "progress", "done": 2, "total": 2} in events
    assert events[-1] == {"type": "done", "file_id": "f_x"}
    assert job.finished


async def test_merger_error_becomes_error_event():
    queue = JobQueue(max_concurrent=1, timeout_seconds=5)

    async def work(progress):
        raise MergerError(ErrorCode.CORRUPT_FILE, "Broken.")

    final = await queue.wait(queue.submit("web:1", 1, work))

    assert final == {"type": "error", "code": "corrupt_file", "message": "Broken."}


async def test_unexpected_error_hides_details():
    queue = JobQueue(max_concurrent=1, timeout_seconds=5)

    async def work(progress):
        raise RuntimeError("secret internals")

    final = await queue.wait(queue.submit("web:1", 1, work))

    assert final["code"] == "internal_error"
    assert "secret" not in final["message"]


async def test_timeout():
    queue = JobQueue(max_concurrent=1, timeout_seconds=0.05)

    async def work(progress):
        await asyncio.sleep(1)
        return {}

    final = await queue.wait(queue.submit("web:1", 1, work))

    assert final["code"] == "merge_timeout"


async def test_concurrency_limit():
    queue = JobQueue(max_concurrent=1, timeout_seconds=5)
    release = asyncio.Event()
    running = 0
    peak = 0

    async def work(progress):
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await release.wait()
        running -= 1
        return {}

    first = queue.submit("web:1", 1, work)
    second = queue.submit("web:1", 1, work)
    await asyncio.sleep(0.01)
    release.set()
    await queue.wait(first)
    await queue.wait(second)

    assert peak == 1


async def test_get_respects_session():
    queue = JobQueue(max_concurrent=1, timeout_seconds=5)

    async def work(progress):
        return {}

    job = queue.submit("web:1", 1, work)

    assert queue.get(job.id, "web:1") is job
    assert queue.get(job.id, None) is job
    with pytest.raises(MergerError) as caught:
        queue.get(job.id, "web:2")
    assert caught.value.code == ErrorCode.JOB_NOT_FOUND
    await queue.wait(job)


async def test_prune_drops_old_finished_jobs():
    now = [100.0]
    queue = JobQueue(max_concurrent=1, timeout_seconds=5, clock=lambda: now[0])

    async def work(progress):
        return {}

    job = queue.submit("web:1", 1, work)
    await queue.wait(job)

    assert queue.prune(older_than=50.0) == 0
    assert queue.prune(older_than=101.0) == 1
