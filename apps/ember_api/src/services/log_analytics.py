"""Aggregates behind the Analytics page (the charts over `log_entries`).

Everything is counted in SQL, over fixed windows ending at the current
hour/day, so the series, the totals and the heatmap always agree. Times
are naive UTC like every stored time. The bucket and weekday/hour grouping
use SQLite's `strftime`, as the rest of ember_api's storage is SQLite.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal, get_args

from sqlalchemy import Select, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db import utcnow
from src.models import Account, LogEntry
from src.services.log_service import LogKind

Period = Literal["24h", "7d", "30d", "90d"]
BucketSize = Literal["hour", "day"]

KINDS: tuple[str, ...] = get_args(LogKind)
TOP_LIMIT = 10

_HOUR = timedelta(hours=1)
_DAY = timedelta(days=1)
# period -> (bucket size, bucket length, bucket count). The current window is
# `count` buckets; the previous one is the `count` buckets before it.
WINDOWS: dict[str, tuple[BucketSize, timedelta, int]] = {
    "24h": ("hour", _HOUR, 24),
    "7d": ("day", _DAY, 7),
    "30d": ("day", _DAY, 30),
    "90d": ("day", _DAY, 90),
}
BUCKET_FORMAT: dict[str, str] = {"hour": "%Y-%m-%dT%H:00:00", "day": "%Y-%m-%dT00:00:00"}


@dataclass(frozen=True)
class Window:
    """The current window (`count` buckets ending at the current one) and the
    one before it, which totals are compared with."""

    bucket: BucketSize
    starts: list[datetime]
    start: datetime
    end: datetime
    previous_start: datetime


def window(period: Period, now: datetime | None = None) -> Window:
    bucket, length, count = WINDOWS[period]
    floor = (now or utcnow()).replace(minute=0, second=0, microsecond=0)
    if bucket == "day":
        floor = floor.replace(hour=0)
    end = floor + length
    start = end - length * count
    return Window(bucket, [start + length * i for i in range(count)], start, end, start - length * count)


@dataclass(frozen=True)
class KindTotal:
    current: int
    previous: int


@dataclass(frozen=True)
class SeriesPoint:
    """One bucket; `bucket` is its naive-UTC start, "YYYY-MM-DDTHH:MM:SS"."""

    bucket: str
    counts: dict[str, int]


@dataclass(frozen=True)
class SourceCount:
    source: str
    count: int


@dataclass(frozen=True)
class AccountCount:
    """account_id None = the server itself; username None = a deleted account."""

    account_id: int | None
    username: str | None
    count: int


@dataclass(frozen=True)
class HeatCell:
    """weekday 0 = Sunday ... 6 = Saturday, hour 0-23, both UTC."""

    weekday: int
    hour: int
    count: int


@dataclass(frozen=True)
class AnalyticsReport:
    period: str
    bucket: BucketSize
    kinds: list[str]
    totals: dict[str, KindTotal]
    series: list[SeriesPoint]
    top_sources: dict[str, list[SourceCount]]
    accounts: dict[str, list[AccountCount]]
    heatmap: list[HeatCell]


class LogAnalytics:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def report(self, period: Period, kinds: Sequence[str], now: datetime | None = None) -> AnalyticsReport:
        """Counts for the `kinds` the caller may read, in the canonical kind order."""
        wanted = [k for k in KINDS if k in kinds]
        span = window(period, now)
        bucket, start, end, previous_start = span.bucket, span.start, span.end, span.previous_start
        counts: dict[str, dict[str, int]] = {s.isoformat(): {k: 0 for k in wanted} for s in span.starts}
        totals = {k: KindTotal(current=0, previous=0) for k in wanted}
        if not wanted:
            return AnalyticsReport(period, bucket, wanted, totals, self._points(counts), {}, {}, [])

        bucket_of = func.strftime(BUCKET_FORMAT[bucket], LogEntry.created_at)
        series = await self._session.execute(
            select(LogEntry.kind, bucket_of, func.count())
            .where(*self._within(wanted, start, end))
            .group_by(LogEntry.kind, bucket_of)
        )
        current: dict[str, int] = dict.fromkeys(wanted, 0)
        for kind, key, n in series:
            counts[key][kind] = n
            current[kind] += n

        before = await self._session.execute(
            select(LogEntry.kind, func.count())
            .where(*self._within(wanted, previous_start, start))
            .group_by(LogEntry.kind)
        )
        previous = dict(before.all())
        totals = {k: KindTotal(current=current[k], previous=previous.get(k, 0)) for k in wanted}

        top_sources = {k: await self._top_sources(k, start, end) for k in wanted}
        accounts = {k: await self._top_accounts(k, start, end) for k in wanted}
        return AnalyticsReport(
            period=period,
            bucket=bucket,
            kinds=wanted,
            totals=totals,
            series=self._points(counts),
            top_sources=top_sources,
            accounts=accounts,
            heatmap=await self._heatmap(wanted, start, end),
        )

    @staticmethod
    def _points(counts: dict[str, dict[str, int]]) -> list[SeriesPoint]:
        return [SeriesPoint(bucket=key, counts=by_kind) for key, by_kind in counts.items()]

    @staticmethod
    def _within(kinds: Sequence[str], start: datetime, end: datetime) -> list:
        return [LogEntry.kind.in_(kinds), LogEntry.created_at >= start, LogEntry.created_at < end]

    async def _top_sources(self, kind: str, start: datetime, end: datetime) -> list[SourceCount]:
        n = func.count().label("n")
        query: Select = (
            select(LogEntry.source, n)
            .where(*self._within([kind], start, end))
            .group_by(LogEntry.source)
            .order_by(desc(n), LogEntry.source)
            .limit(TOP_LIMIT)
        )
        return [SourceCount(source=source, count=c) for source, c in await self._session.execute(query)]

    async def _top_accounts(self, kind: str, start: datetime, end: datetime) -> list[AccountCount]:
        n = func.count().label("n")
        rows = (
            await self._session.execute(
                select(LogEntry.account_id, n)
                .where(*self._within([kind], start, end))
                .group_by(LogEntry.account_id)
                .order_by(desc(n), LogEntry.account_id)
                .limit(TOP_LIMIT)
            )
        ).all()
        ids = [account_id for account_id, _ in rows if account_id is not None]
        names: dict[int, str] = {}
        if ids:
            names = dict((await self._session.execute(select(Account.id, Account.username).where(Account.id.in_(ids)))).all())
        return [AccountCount(account_id=a, username=names.get(a) if a is not None else None, count=c) for a, c in rows]

    async def _heatmap(self, kinds: Sequence[str], start: datetime, end: datetime) -> list[HeatCell]:
        weekday = func.strftime("%w", LogEntry.created_at)
        hour = func.strftime("%H", LogEntry.created_at)
        rows = await self._session.execute(
            select(weekday, hour, func.count()).where(*self._within(kinds, start, end)).group_by(weekday, hour)
        )
        return [HeatCell(weekday=int(w), hour=int(h), count=c) for w, h, c in rows]
