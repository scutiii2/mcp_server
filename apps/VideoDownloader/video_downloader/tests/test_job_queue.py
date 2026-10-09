from __future__ import annotations

import asyncio
import threading

import pytest

from src.errors import DownloaderError, ErrorCode
from src.jobs.job_queue import JobQueue


async def ok_work(emit, cancel):
    emit({"type": "progress", "percent": 50.0})
    return {"file_id": "f_1"}


async def test_job_publishes_queued_progress_done():
    queue = JobQueue(2, 4, 5.0)
    job = queue.submit("s", ok_work)
    final = await queue.wait(job)
    assert [e["type"] for e in job.events] == ["queued", "progress", "done"]
    assert final == {"type": "done", "file_id": "f_1"}


async def test_late_subscriber_replays_all_events():
    queue = JobQueue(2, 4, 5.0)
    job = queue.submit("s", ok_work)
    await queue.wait(job)
    seen = [e async for e in job.stream()]
    assert len(seen) == 3


async def test_downloader_error_becomes_error_event():
    async def work(emit, cancel):
        raise DownloaderError(ErrorCode.UNSUPPORTED_SITE, "nope")

    queue = JobQueue(2, 4, 5.0)
    final = await queue.wait(queue.submit("s", work))
    assert final == {"type": "error", "code": "unsupported_site", "message": "nope"}


async def test_unexpected_error_is_internal_and_hides_details():
    async def work(emit, cancel):
        raise RuntimeError("secret path C:\\x")

    queue = JobQueue(2, 4, 5.0)
    final = await queue.wait(queue.submit("s", work))
    assert final["code"] == "internal_error"
    assert "secret" not in final["message"]


async def test_concurrency_limit_and_queue_full():
    gate = asyncio.Event()
    running = 0
    peak = 0

    async def work(emit, cancel):
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await gate.wait()
        running -= 1
        return {}

    queue = JobQueue(max_concurrent=1, max_queued=1, timeout_seconds=5.0)
    first = queue.submit("s", work)
    second = queue.submit("s", work)
    with pytest.raises(DownloaderError) as error:
        queue.submit("s", work)
    assert error.value.code == ErrorCode.QUEUE_FULL
    await asyncio.sleep(0.05)
    assert peak == 1
    gate.set()
    await queue.wait(first)
    await queue.wait(second)
    assert peak == 1


async def test_cancel_running_job_ends_with_cancelled():
    started = asyncio.Event()

    async def work(emit, cancel):
        started.set()
        while not cancel.is_set():
            await asyncio.sleep(0.01)
        raise DownloaderError(ErrorCode.CANCELLED, "The download was cancelled.")

    queue = JobQueue(1, 1, 5.0)
    job = queue.submit("s", work)
    await started.wait()
    queue.cancel(job)
    final = await queue.wait(job)
    assert final["code"] == "cancelled"


async def test_cancel_while_queued_never_starts_work():
    gate = asyncio.Event()
    started: list[str] = []

    async def blocker(emit, cancel):
        await gate.wait()
        return {}

    async def work(emit, cancel):
        started.append("ran")
        return {}

    queue = JobQueue(1, 2, 5.0)
    first = queue.submit("s", blocker)
    second = queue.submit("s", work)
    await asyncio.sleep(0.02)
    queue.cancel(second)
    gate.set()
    await queue.wait(first)
    final = await queue.wait(second)
    assert final["code"] == "cancelled" and started == []


async def test_cancel_all_stops_running_and_queued_jobs():
    async def work(emit, cancel):
        while not cancel.is_set():
            await asyncio.sleep(0.01)
        raise DownloaderError(ErrorCode.CANCELLED, "The download was cancelled.")

    queue = JobQueue(1, 2, 5.0)
    done = queue.submit("s", ok_work)
    await queue.wait(done)
    running = queue.submit("s", work)
    queued = queue.submit("t", work)
    await asyncio.sleep(0.02)
    queue.cancel_all()
    assert running.cancel_event.is_set() and queued.cancel_event.is_set()
    assert not done.cancel_event.is_set()  # finished jobs are left alone
    assert (await queue.wait(running))["code"] == "cancelled"
    assert (await queue.wait(queued))["code"] == "cancelled"


async def test_timeout_sets_cancel_and_reports_timeout():
    async def work(emit, cancel):
        while not cancel.is_set():
            await asyncio.sleep(0.01)
        raise DownloaderError(ErrorCode.CANCELLED, "x")

    queue = JobQueue(1, 1, 0.05)
    final = await queue.wait(queue.submit("s", work))
    assert final["code"] == "timeout"


async def test_emit_works_from_a_worker_thread():
    async def work(emit, cancel):
        await asyncio.to_thread(emit, {"type": "progress", "percent": 10.0})
        return {}

    queue = JobQueue(1, 1, 5.0)
    job = queue.submit("s", work)
    await queue.wait(job)
    assert {"type": "progress", "percent": 10.0} in job.events


async def test_get_is_scoped_to_session_and_prune_forgets_old_jobs():
    now = [100.0]
    queue = JobQueue(1, 1, 5.0, clock=lambda: now[0])
    job = queue.submit("alice", ok_work)
    await queue.wait(job)
    assert queue.get(job.id, "alice") is job
    assert queue.get(job.id, None) is job
    with pytest.raises(DownloaderError) as error:
        queue.get(job.id, "bob")
    assert error.value.code == ErrorCode.JOB_NOT_FOUND
    assert queue.prune(older_than=200.0) == 1
    with pytest.raises(DownloaderError):
        queue.get(job.id, "alice")
