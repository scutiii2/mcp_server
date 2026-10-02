"""Merge jobs: a global concurrency limit, a timeout, and replayable progress events.

A job's events are kept in a list so a late subscriber (the browser opening
the SSE stream after POST /merge returned) still sees everything. All
publish() calls happen on the event loop thread; worker threads report
progress through loop.call_soon_threadsafe.

A timed-out merge stops being awaited, but its worker thread runs to
completion in the background (Python cannot kill threads). The semaphore
slot is released at the timeout, so a stuck merge cannot block the queue.
"""

from __future__ import annotations

import asyncio
import logging
import secrets
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field

from src.errors import ErrorCode, MergerError

logger = logging.getLogger(__name__)

ProgressFn = Callable[[int], None]
Work = Callable[[ProgressFn], Awaitable[dict]]


@dataclass
class Job:
    id: str
    session: str
    created_at: float
    events: list[dict] = field(default_factory=list)
    finished: bool = False
    _changed: asyncio.Event = field(default_factory=asyncio.Event, repr=False)

    def publish(self, event: dict, *, final: bool = False) -> None:
        """Append an event. Events after the final one are dropped."""
        if self.finished:
            return
        self.events.append(event)
        self.finished = final
        self._changed.set()

    async def stream(self) -> AsyncIterator[dict]:
        """Every event so far, then new ones as they arrive, ending after the final event."""
        index = 0
        while True:
            while index < len(self.events):
                yield self.events[index]
                index += 1
            if self.finished:
                return
            self._changed.clear()
            await self._changed.wait()


class JobQueue:
    """Runs submitted merge work under a concurrency limit and a timeout."""

    def __init__(self, max_concurrent: int, timeout_seconds: float, clock: Callable[[], float] = time.time) -> None:
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._timeout = timeout_seconds
        self._clock = clock
        self._jobs: dict[str, Job] = {}
        self._tasks: set[asyncio.Task] = set()

    def submit(self, session: str, total_pages: int, work: Work) -> Job:
        job = Job(id="j_" + secrets.token_hex(12), session=session, created_at=self._clock())
        self._jobs[job.id] = job
        task = asyncio.create_task(self._run(job, total_pages, work))
        self._tasks.add(task)  # keep a reference so the task is not garbage-collected
        task.add_done_callback(self._tasks.discard)
        return job

    async def _run(self, job: Job, total: int, work: Work) -> None:
        loop = asyncio.get_running_loop()

        def progress(done: int) -> None:
            loop.call_soon_threadsafe(job.publish, {"type": "progress", "done": done, "total": total})

        job.publish({"type": "queued", "total": total})
        try:
            async with self._semaphore:
                job.publish({"type": "progress", "done": 0, "total": total})
                result = await asyncio.wait_for(work(progress), self._timeout)
        except MergerError as error:
            job.publish({"type": "error", "code": str(error.code), "message": error.message}, final=True)
        except TimeoutError:
            job.publish(
                {
                    "type": "error",
                    "code": str(ErrorCode.MERGE_TIMEOUT),
                    "message": f"The merge took longer than {self._timeout:g} seconds and was stopped. Try fewer pages.",
                },
                final=True,
            )
        except Exception:
            logger.exception("Merge job %s failed", job.id)
            job.publish(
                {"type": "error", "code": str(ErrorCode.INTERNAL), "message": "The merge failed unexpectedly. Try again."},
                final=True,
            )
        else:
            job.publish({"type": "done", **result}, final=True)

    def get(self, job_id: str, session: str | None) -> Job:
        job = self._jobs.get(job_id)
        if job is None or (session is not None and job.session != session):
            raise MergerError(ErrorCode.JOB_NOT_FOUND, f"Job {job_id} wasn't found.")
        return job

    async def wait(self, job: Job) -> dict:
        final: dict = {}
        async for event in job.stream():
            final = event
        return final

    def prune(self, older_than: float) -> int:
        """Forget finished jobs created before ``older_than``."""
        stale = [job_id for job_id, job in self._jobs.items() if job.finished and job.created_at < older_than]
        for job_id in stale:
            del self._jobs[job_id]
        return len(stale)
