from __future__ import annotations

import asyncio
import time

import pytest

from src.errors import ErrorCode, MergerError
from src.jobs.job_queue import JobQueue


async def collect(job) -> list[dict]:
    return [event async for event in job.stream()]


async def test_successful_job_streams_queued_progress_done():
    queue = JobQueue(max_concurrent=1, timeout_seconds=5)

    async def work(progress, cancel):
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

    async def work(progress, cancel):
        raise MergerError(ErrorCode.CORRUPT_FILE, "Broken.")

    final = await queue.wait(queue.submit("web:1", 1, work))

    assert final == {"type": "error", "code": "corrupt_file", "message": "Broken."}


async def test_unexpected_error_hides_details():
    queue = JobQueue(max_concurrent=1, timeout_seconds=5)

    async def work(progress, cancel):
        raise RuntimeError("secret internals")

    final = await queue.wait(queue.submit("web:1", 1, work))

    assert final["code"] == "internal_error"
    assert "secret" not in final["message"]


async def test_timeout():
    queue = JobQueue(max_concurrent=1, timeout_seconds=0.05)

    async def work(progress, cancel):
        while not cancel.is_set():
            await asyncio.sleep(0.01)
        raise MergerError(ErrorCode.MERGE_TIMEOUT, "stopped")

    final = await queue.wait(queue.submit("web:1", 1, work))

    assert final["code"] == "merge_timeout"


async def test_concurrency_limit():
    queue = JobQueue(max_concurrent=1, timeout_seconds=5)
    release = asyncio.Event()
    running = 0
    peak = 0

    async def work(progress, cancel):
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

    async def work(progress, cancel):
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

    async def work(progress, cancel):
        return {}

    job = queue.submit("web:1", 1, work)
    await queue.wait(job)

    assert queue.prune(older_than=50.0) == 0
    assert queue.prune(older_than=101.0) == 1


def _blocking_until_cancelled(state: dict, delay: float = 0.0) -> callable:
    def blocking(cancel):
        while not cancel.is_set():
            time.sleep(0.01)
        time.sleep(delay)
        state["exited"] = True
        raise MergerError(ErrorCode.MERGE_TIMEOUT, "stopped")

    return blocking


async def test_thread_backed_timeout_waits_for_thread_exit():
    queue = JobQueue(max_concurrent=1, timeout_seconds=0.05)
    state = {"exited": False}

    async def work(progress, cancel):
        return await asyncio.to_thread(_blocking_until_cancelled(state), cancel)

    final = await queue.wait(queue.submit("web:1", 1, work))

    assert final["code"] == "merge_timeout"
    assert state["exited"] is True


async def test_slot_is_held_until_timed_out_thread_exits():
    queue = JobQueue(max_concurrent=1, timeout_seconds=0.05)
    state = {"exited": False}
    second_started = []

    async def slow(progress, cancel):
        return await asyncio.to_thread(_blocking_until_cancelled(state, delay=0.2), cancel)

    async def second(progress, cancel):
        second_started.append(state["exited"])
        return {}

    first_job = queue.submit("web:1", 1, slow)
    second_job = queue.submit("web:1", 1, second)
    await queue.wait(first_job)
    await queue.wait(second_job)

    assert second_started == [True]


async def test_work_finishing_despite_timeout_reports_done():
    queue = JobQueue(max_concurrent=1, timeout_seconds=0.02)

    async def work(progress, cancel):
        await asyncio.to_thread(time.sleep, 0.1)
        return {"file_id": "f_x"}

    final = await queue.wait(queue.submit("web:1", 1, work))

    assert final == {"type": "done", "file_id": "f_x"}


async def test_cancelled_queued_job_never_runs_its_work():
    queue = JobQueue(max_concurrent=1, timeout_seconds=5)
    release = asyncio.Event()
    ran = []

    async def blocker(progress, cancel):
        await release.wait()
        return {}

    async def work(progress, cancel):
        ran.append(True)
        return {}

    first = queue.submit("web:1", 1, blocker)
    second = queue.submit("web:1", 1, work)
    await asyncio.sleep(0.01)
    queue.cancel(second)
    release.set()
    await queue.wait(first)
    final = await queue.wait(second)

    assert ran == []
    assert final["code"] == "merge_timeout"
