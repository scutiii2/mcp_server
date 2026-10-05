"""Network traffic counters for the Analytics page's Traffic tab.

Nothing is written per request. TrafficRecorder counts in memory (recording
is a dict update, no await) and a background task adds the counters to the
`traffic_buckets` table every 30 seconds and on shutdown. A crash loses at
most the last interval. Only the route template, method, status class and
duration are kept, never a body, query string, IP or account.

Two kinds are counted: "http" (requests ember_api served, via
TrafficMiddleware) and "upstream" (calls ember_api made to ai_agent or
mcp_server, via TrafficRecorder.timed).
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta

from sqlalchemy import delete
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from src.db import Database, utcnow
from src.models import TrafficBucket

logger = logging.getLogger(__name__)

# A request's duration lands in the first band whose upper bound it does not
# pass; the last band (no bound) is everything slower.
LATENCY_BANDS_MS: tuple[int | None, ...] = (50, 100, 250, 500, 1000, 2500, 5000, None)
NAME_MAX = 200
FLUSH_EVERY_SECONDS = 30.0
# Older buckets are deleted on startup, like log entries.
RETENTION_DAYS = 90

HTTP = "http"
UPSTREAM = "upstream"
# What a request that matched no route is counted under, so scanners probing
# random paths cannot create endless names.
UNMATCHED = "unmatched"

_Key = tuple[datetime, str, str, str, int]


def latency_band(duration_ms: float) -> int:
    for index, bound in enumerate(LATENCY_BANDS_MS):
        if bound is None or duration_ms <= bound:
            return index
    return len(LATENCY_BANDS_MS) - 1


def status_class(status_code: int) -> str:
    return f"{status_code // 100}xx"


class Timing:
    """Handed out by TrafficRecorder.timed. An exception leaving the block
    counts the call as failed unless `ok` was set first (a refusal such as
    a 4xx answer is the server working, not an upstream failure)."""

    def __init__(self) -> None:
        self.ok: bool | None = None


class TrafficRecorder:
    def __init__(
        self,
        database: Database | None = None,
        flush_every: float = FLUSH_EVERY_SECONDS,
        clock: Callable[[], datetime] = utcnow,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        """Without a database the counters stay in memory (what a client or
        gateway built without the app gets by default)."""
        self._database = database
        self._flush_every = flush_every
        self._clock = clock
        self._sleep = sleep
        self._counts: dict[_Key, list[int]] = {}
        self._task: asyncio.Task[None] | None = None

    def record(self, kind: str, name: str, status: str, duration_ms: float) -> None:
        hour = self._clock().replace(minute=0, second=0, microsecond=0)
        key = (hour, kind, name[:NAME_MAX], status, latency_band(duration_ms))
        cell = self._counts.setdefault(key, [0, 0])
        cell[0] += 1
        cell[1] += max(0, round(duration_ms))

    def record_http(self, method: str, route: str, status_code: int, duration_ms: float) -> None:
        self.record(HTTP, f"{method} {route}", status_class(status_code), duration_ms)

    @contextmanager
    def timed(self, target: str, tool: str) -> Iterator[Timing]:
        """Times one call to an upstream server: `with traffic.timed("ai_agent", "ask"):`.
        A cancelled call (the user stopped a turn) is not counted."""
        timing = Timing()
        started = time.perf_counter()
        cancelled = False
        try:
            yield timing
        except asyncio.CancelledError:
            cancelled = True
            raise
        except BaseException:
            if timing.ok is None:
                timing.ok = False
            raise
        finally:
            if timing.ok is None:
                timing.ok = True
            if not cancelled:
                self.record(UPSTREAM, f"{target} {tool}", "ok" if timing.ok else "failed", _ms_since(started))

    def pending(self) -> dict[tuple[str, str, str, int], tuple[int, int]]:
        """What is counted but not saved yet, summed over hours:
        {(kind, name, status, band): (count, total_ms)}."""
        merged: dict[tuple[str, str, str, int], tuple[int, int]] = {}
        for (_hour, kind, name, status, band), (count, total) in self._counts.items():
            old_count, old_total = merged.get((kind, name, status, band), (0, 0))
            merged[(kind, name, status, band)] = (old_count + count, old_total + total)
        return merged

    async def flush(self) -> None:
        """Adds the counters to the table. On a failure they are kept for the next try."""
        if self._database is None or not self._counts:
            return
        pending, self._counts = self._counts, {}
        rows = [
            {"hour": hour, "kind": kind, "name": name, "status": status, "band": band, "count": cell[0], "total_ms": cell[1]}
            for (hour, kind, name, status, band), cell in pending.items()
        ]
        table = TrafficBucket.__table__
        statement = sqlite_insert(table)
        statement = statement.on_conflict_do_update(
            index_elements=[table.c.hour, table.c.kind, table.c.name, table.c.status, table.c.band],
            set_={
                "count": table.c.count + statement.excluded.count,
                "total_ms": table.c.total_ms + statement.excluded.total_ms,
            },
        )
        try:
            async with self._database.sessions() as session:
                await session.execute(statement, rows)
                await session.commit()
        except Exception:  # noqa: BLE001 - counting traffic must never break a request or shutdown
            logger.exception("saving %d traffic counters failed; keeping them for the next flush", len(rows))
            self._merge_back(pending)

    def _merge_back(self, pending: dict[_Key, list[int]]) -> None:
        for key, cell in pending.items():
            current = self._counts.setdefault(key, [0, 0])
            current[0] += cell[0]
            current[1] += cell[1]

    async def purge_old(self) -> int:
        if self._database is None:
            return 0
        cutoff = self._clock() - timedelta(days=RETENTION_DAYS)
        async with self._database.sessions() as session:
            result = await session.execute(delete(TrafficBucket).where(TrafficBucket.hour < cutoff))
            await session.commit()
            return result.rowcount or 0

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._loop(), name="traffic-flush")

    async def stop(self) -> None:
        """Stops the background task and saves what is left."""
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        await self.flush()

    async def _loop(self) -> None:
        while True:
            await self._sleep(self._flush_every)
            await self.flush()


def _ms_since(started: float) -> float:
    return (time.perf_counter() - started) * 1000


class TrafficMiddleware:
    """Pure ASGI: counts every HTTP request by route template, method and
    status class, timed to the first response byte (a streamed answer, such
    as an SSE stream, is counted when it starts, not when it ends)."""

    # Polled by the process supervisor; not traffic worth charting.
    SKIPPED = frozenset({"/api/health"})

    def __init__(self, app) -> None:
        self._app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http" or scope.get("path") in self.SKIPPED:
            await self._app(scope, receive, send)
            return
        # The recorder is made when the app starts, after the middleware is built.
        recorder: TrafficRecorder | None = getattr(scope["app"].state, "traffic", None) if "app" in scope else None
        if recorder is None:
            await self._app(scope, receive, send)
            return
        started = time.perf_counter()
        recorded = False

        def record(status_code: int) -> None:
            nonlocal recorded
            if recorded:
                return
            recorded = True
            # Set by the router once a route matched, so read after the app ran.
            route = getattr(scope.get("route"), "path", None) or UNMATCHED
            method = scope["method"] if route != UNMATCHED else "ANY"
            recorder.record_http(method, route, status_code, _ms_since(started))

        async def send_wrapper(message) -> None:
            if message["type"] == "http.response.start":
                record(message["status"])
            await send(message)

        try:
            await self._app(scope, receive, send_wrapper)
        except Exception:
            record(500)
            raise
