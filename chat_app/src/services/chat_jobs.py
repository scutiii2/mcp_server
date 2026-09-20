"""Process-local, user-owned response workers and bounded event replay.

The turn runner owns provider calls and terminal persistence. It runs once
on a server thread, independently of any number of browser subscriptions.
Workers survive browser disconnects, but not an application restart.
"""

from __future__ import annotations

from collections import deque
from contextlib import nullcontext
from dataclasses import dataclass, field
from datetime import datetime, timezone
from itertools import count
from pathlib import Path
from threading import Condition, RLock, Thread, Timer
from time import monotonic
from typing import Callable, Iterator
from uuid import uuid4

from src.services import agent_registry, ai_agent_client, chats_store
from src.utils.catalog import catalog


class ChatAlreadyRunning(Exception):
    """Only one writer may append a response to a chat at a time."""


@dataclass
class ChatJob:
    username: str
    chat_id: str
    provider_id: str | None
    request_id: str
    question: str
    history: list[dict]
    provider_request_id: str = field(default_factory=lambda: uuid4().hex)
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    status: str = "running"
    sequence: int = 0
    cancel_requested: bool = False
    provider_started: bool = False
    removed: bool = False
    completed_at: float | None = None
    events: deque = field(default_factory=lambda: deque(maxlen=256))
    condition: Condition = field(default_factory=Condition)
    thread: Thread | None = None
    retention_timer: Timer | None = None

    def begin_provider(self) -> bool:
        """Atomically hand cancellation responsibility to the provider."""
        with self.condition:
            if self.cancel_requested:
                return False
            self.provider_started = True
            return True


@catalog
class ChatJobRegistry:
    """One registry per Flask app; all access is scoped to a username.

    ``run_turn`` yields events after applying the route's terminal save.
    ``context_factory`` supplies an application context, never a request
    context, so neither persistence nor work depends on an open response.
    """

    def __init__(self, db_path: Path, *, context_factory=nullcontext, event_buffer_size: int = 256,
                 completed_retention_seconds: float = 300, max_completed_jobs: int = 128):
        if event_buffer_size < 1:
            raise ValueError("event_buffer_size must be positive")
        if completed_retention_seconds <= 0 or max_completed_jobs < 1:
            raise ValueError("completed job retention must be positive")
        self.db_path = db_path
        self.context_factory = context_factory
        self.event_buffer_size = event_buffer_size
        self.completed_retention_seconds = completed_retention_seconds
        self.max_completed_jobs = max_completed_jobs
        self._jobs: dict[str, ChatJob] = {}
        self._lock = RLock()
        # A registry-wide counter keeps cursors increasing after an old job
        # has expired, without retaining a per-chat sequence map forever.
        self._sequences = count(1)

    def start(self, username, chat_id, provider_id, request_id, question, history,
              *, run_turn: Callable[[ChatJob], Iterator[dict]]) -> ChatJob:
        with self._lock:
            if chats_store.get_chat(self.db_path, username, chat_id) is None:
                raise chats_store.UnknownChat(chat_id)
            previous = self._jobs.get(chat_id)
            if previous is not None and previous.username != username:
                raise chats_store.UnknownChat(chat_id)
            if previous is not None and previous.status == "running":
                raise ChatAlreadyRunning(chat_id)
            job = ChatJob(username, chat_id, provider_id, request_id or uuid4().hex, question, list(history))
            job.sequence = previous.sequence if previous else 0
            if previous is not None:
                self._forget(previous)
            job.events = deque(maxlen=self.event_buffer_size)
            self._jobs[chat_id] = job
            job.thread = Thread(target=self._run, args=(job, run_turn), daemon=True)
            job.thread.start()
            return job

    def get(self, username: str, chat_id: str) -> ChatJob | None:
        with self._lock:
            job = self._jobs.get(chat_id)
            return job if job is not None and job.username == username else None

    def status_for_user(self, username: str) -> dict[str, dict]:
        with self._lock:
            jobs = [job for job in self._jobs.values() if job.username == username]
        result = {}
        for job in jobs:
            with job.condition:
                result[job.chat_id] = {
                    "status": job.status, "started_at": job.started_at,
                    "request_id": job.request_id, "provider_id": job.provider_id,
                    "sequence": job.sequence, "cancel_requested": job.cancel_requested,
                }
        return result

    def subscribe(self, username: str, chat_id: str, after_sequence: int = 0) -> Iterator[dict]:
        job = self.get(username, chat_id)
        if job is None:
            raise chats_store.UnknownChat(chat_id)

        def events():
            cursor = after_sequence
            while True:
                with job.condition:
                    # A returned iterator may not be consumed until after
                    # its completed-job retention window has elapsed.  Do
                    # not turn that expired replay into an empty stream.
                    if job.removed:
                        raise chats_store.UnknownChat(chat_id)
                    batch = [dict(event) for event in job.events if event["sequence"] > cursor]
                    terminal = job.status != "running"
                    if not batch and not terminal:
                        job.condition.wait()
                        continue
                for event in batch:
                    cursor = event["sequence"]
                    yield event
                if terminal:
                    return
        return events()

    def cancel(self, username: str, chat_id: str) -> bool:
        job = self.get(username, chat_id)
        if job is None:
            return False
        with job.condition:
            if job.status != "running":
                return False
            job.cancel_requested = True
            provider_started = job.provider_started
        agent = agent_registry.get_agent(job.provider_id)
        if provider_started and agent is not None:
            try:
                ai_agent_client.cancel(agent["url"], job.provider_request_id)
            except Exception:
                # Cancellation is cooperative; an unavailable agent must
                # not prevent deleting the caller's own stored chat.
                pass
        return True

    def discard(self, username: str, chat_id: str) -> None:
        """Release a deleted chat's replay immediately, including live jobs."""
        with self._lock:
            job = self._jobs.get(chat_id)
            if job is not None and job.username == username:
                self._forget(job)

    def _forget(self, job: ChatJob) -> None:
        # Callers hold _lock; subscriptions only hold the job condition.
        with job.condition:
            if self._jobs.get(job.chat_id) is job:
                del self._jobs[job.chat_id]
            job.removed = True
            job.events.clear()
            job.history.clear()
            job.question = ""
            if job.retention_timer is not None:
                job.retention_timer.cancel()
                job.retention_timer = None
            job.condition.notify_all()

    def _expire(self, job: ChatJob) -> None:
        with self._lock:
            self._forget(job)

    def _publish(self, job: ChatJob, event: dict) -> None:
        with self._lock, job.condition:
            job.sequence = next(self._sequences)
            if not job.removed:
                job.events.append({**event, "sequence": job.sequence, "request_id": job.request_id})
            if event.get("type") in {"final", "error"}:
                # Cancellation is cooperative.  A request records intent while
                # the provider is running, but the provider's terminal event
                # remains the source of truth for the completed outcome.
                job.status = ("cancelled" if event.get("cancelled")
                              else "failed" if event.get("failed") or event["type"] == "error"
                              else "completed")
                job.completed_at = monotonic()
                job.history.clear()
                job.question = ""
                if not job.removed:
                    # Keep a bounded reconnect window; persisted transcripts
                    # remain authoritative once replay has expired or filled.
                    completed = sorted(
                        (item for item in self._jobs.values() if item.completed_at is not None),
                        key=lambda item: item.completed_at,
                    )
                    for old in completed[:-self.max_completed_jobs]:
                        self._forget(old)
                    job.retention_timer = Timer(self.completed_retention_seconds, self._expire, args=(job,))
                    job.retention_timer.daemon = True
                    job.retention_timer.start()
            job.condition.notify_all()

    def _run(self, job: ChatJob, run_turn: Callable[[ChatJob], Iterator[dict]]) -> None:
        try:
            with self.context_factory():
                iterator = run_turn(job)
                try:
                    for event in iterator:
                        self._publish(job, event)
                        if event.get("type") in {"final", "error"}:
                            return
                finally:
                    close = getattr(iterator, "close", None)
                    if close is not None:
                        close()
                raise RuntimeError("Response stream ended without a terminal event")
        except Exception:
            self._publish(job, {
                "type": "error", "message": "The response could not be completed.",
                "chat_id": job.chat_id,
            })
