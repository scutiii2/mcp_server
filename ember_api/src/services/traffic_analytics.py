"""Aggregates behind the Analytics page's Traffic tab (read from `traffic_buckets`).

The same windows as the log analytics (`log_analytics.window`). Latency is
only known as a band (services.traffic.LATENCY_BANDS_MS), so a percentile is
the upper bound of the band that holds it: accurate to the band, not to the
millisecond. A percentile in the slowest band is reported as the cap
(LATENCY_CAP_MS), meaning "at least that".
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from math import ceil

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import TrafficBucket
from src.services.log_analytics import BUCKET_FORMAT, Period, window
from src.services.traffic import HTTP, LATENCY_BANDS_MS, UPSTREAM

TOP_LIMIT = 10
# A route needs this many requests to be ranked among the slowest: one slow
# request would otherwise top the list.
SLOWEST_MIN_REQUESTS = 5
STATUS_CLASSES: tuple[str, ...] = ("2xx", "3xx", "4xx", "5xx")
# The last band has no bound; a percentile in it is reported as this.
LATENCY_CAP_MS: int = max(bound for bound in LATENCY_BANDS_MS if bound is not None)

# band index -> request count
_Histogram = dict[int, int]


def percentile(histogram: _Histogram, fraction: float) -> int | None:
    """The upper bound (ms) of the band holding the `fraction` quantile; None with no requests."""
    total = sum(histogram.values())
    if total == 0:
        return None
    needed = ceil(total * fraction)
    seen = 0
    for band in sorted(histogram):
        seen += histogram[band]
        if seen >= needed:
            bound = LATENCY_BANDS_MS[band]
            return LATENCY_CAP_MS if bound is None else bound
    return LATENCY_CAP_MS  # unreachable: seen reaches total


@dataclass(frozen=True)
class CountPair:
    current: int
    previous: int


@dataclass(frozen=True)
class ValuePair:
    """None means there was nothing to measure (no requests in that window)."""

    current: float | None
    previous: float | None


@dataclass(frozen=True)
class TrafficTotals:
    requests: CountPair
    # Share of requests answered 5xx, 0..1.
    error_rate: ValuePair
    p95_ms: ValuePair
    upstream_failures: CountPair


@dataclass(frozen=True)
class TrafficPoint:
    """One bucket (naive-UTC start, "YYYY-MM-DDTHH:MM:SS"); `requests` has every status class."""

    bucket: str
    requests: dict[str, int]
    p50_ms: int | None
    p95_ms: int | None


@dataclass(frozen=True)
class RouteStat:
    name: str
    count: int
    error_rate: float
    p95_ms: int | None


@dataclass(frozen=True)
class Routes:
    busiest: list[RouteStat]
    slowest: list[RouteStat]


@dataclass(frozen=True)
class ToolStat:
    name: str
    calls: int
    failures: int
    p95_ms: int | None


@dataclass(frozen=True)
class UpstreamStat:
    target: str
    calls: int
    failures: int
    failure_rate: float
    p95_ms: int | None
    tools: list[ToolStat]


@dataclass(frozen=True)
class TrafficReport:
    period: str
    bucket: str
    latency_cap_ms: int
    totals: TrafficTotals
    series: list[TrafficPoint]
    routes: Routes
    upstream: list[UpstreamStat]


class _Tally:
    """Counts for one thing (a route, a tool, a bucket): status counts and a latency histogram."""

    def __init__(self) -> None:
        self.by_status: dict[str, int] = defaultdict(int)
        self.latency: _Histogram = defaultdict(int)

    def add(self, status: str, band: int, count: int) -> None:
        self.by_status[status] += count
        self.latency[band] += count

    @property
    def count(self) -> int:
        return sum(self.by_status.values())

    @property
    def failed(self) -> int:
        """5xx for an http route, "failed" for an upstream call."""
        return self.by_status.get("5xx", 0) + self.by_status.get("failed", 0)

    @property
    def failure_rate(self) -> float:
        return self.failed / self.count if self.count else 0.0

    def p(self, fraction: float) -> int | None:
        return percentile(self.latency, fraction)


class TrafficAnalytics:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def report(self, period: Period, now: datetime | None = None) -> TrafficReport:
        span = window(period, now)
        current = await self._tallies(HTTP, span.start, span.end)
        previous = await self._tallies(HTTP, span.previous_start, span.start)
        current_up = await self._tallies(UPSTREAM, span.start, span.end)
        previous_up = await self._tallies(UPSTREAM, span.previous_start, span.start)

        now_all, before_all = _merge(current.values()), _merge(previous.values())
        totals = TrafficTotals(
            requests=CountPair(now_all.count, before_all.count),
            error_rate=ValuePair(_rate(now_all), _rate(before_all)),
            p95_ms=ValuePair(now_all.p(0.95), before_all.p(0.95)),
            upstream_failures=CountPair(
                sum(t.failed for t in current_up.values()), sum(t.failed for t in previous_up.values())
            ),
        )
        return TrafficReport(
            period=period,
            bucket=span.bucket,
            latency_cap_ms=LATENCY_CAP_MS,
            totals=totals,
            series=await self._series(span.bucket, [s.isoformat() for s in span.starts], span.start, span.end),
            routes=_routes(current),
            upstream=_upstream(current_up),
        )

    async def _tallies(self, kind: str, start: datetime, end: datetime) -> dict[str, _Tally]:
        """Per name, over [start, end)."""
        rows = await self._session.execute(
            select(TrafficBucket.name, TrafficBucket.status, TrafficBucket.band, func.sum(TrafficBucket.count))
            .where(TrafficBucket.kind == kind, TrafficBucket.hour >= start, TrafficBucket.hour < end)
            .group_by(TrafficBucket.name, TrafficBucket.status, TrafficBucket.band)
        )
        tallies: dict[str, _Tally] = defaultdict(_Tally)
        for name, status, band, count in rows:
            tallies[name].add(status, band, count)
        return tallies

    async def _series(self, bucket: str, keys: list[str], start: datetime, end: datetime) -> list[TrafficPoint]:
        key = func.strftime(BUCKET_FORMAT[bucket], TrafficBucket.hour)
        rows = await self._session.execute(
            select(key, TrafficBucket.status, TrafficBucket.band, func.sum(TrafficBucket.count))
            .where(TrafficBucket.kind == HTTP, TrafficBucket.hour >= start, TrafficBucket.hour < end)
            .group_by(key, TrafficBucket.status, TrafficBucket.band)
        )
        tallies: dict[str, _Tally] = {k: _Tally() for k in keys}
        for bucket_key, status, band, count in rows:
            tallies[bucket_key].add(status, band, count)
        return [
            TrafficPoint(
                bucket=k,
                requests={status: t.by_status.get(status, 0) for status in STATUS_CLASSES},
                p50_ms=t.p(0.5),
                p95_ms=t.p(0.95),
            )
            for k, t in tallies.items()
        ]


def _merge(tallies) -> _Tally:
    merged = _Tally()
    for tally in tallies:
        for status, count in tally.by_status.items():
            merged.by_status[status] += count
        for band, count in tally.latency.items():
            merged.latency[band] += count
    return merged


def _rate(tally: _Tally) -> float | None:
    return tally.failure_rate if tally.count else None


def _routes(tallies: dict[str, _Tally]) -> Routes:
    stats = [RouteStat(name, t.count, t.failure_rate, t.p(0.95)) for name, t in tallies.items()]
    busiest = sorted(stats, key=lambda s: (-s.count, s.name))[:TOP_LIMIT]
    ranked = [s for s in stats if s.count >= SLOWEST_MIN_REQUESTS and s.p95_ms is not None]
    slowest = sorted(ranked, key=lambda s: (-(s.p95_ms or 0), -s.count, s.name))[:TOP_LIMIT]
    return Routes(busiest=busiest, slowest=slowest)


def _upstream(tallies: dict[str, _Tally]) -> list[UpstreamStat]:
    """Names are "<target> <tool>"; grouped by target, the busiest first."""
    by_target: dict[str, dict[str, _Tally]] = defaultdict(dict)
    for name, tally in tallies.items():
        target, _, tool = name.partition(" ")
        by_target[target][tool] = tally
    result = []
    for target, tools in by_target.items():
        whole = _merge(tools.values())
        tool_stats = [ToolStat(tool, t.count, t.failed, t.p(0.95)) for tool, t in tools.items()]
        result.append(
            UpstreamStat(
                target=target,
                calls=whole.count,
                failures=whole.failed,
                failure_rate=whole.failure_rate,
                p95_ms=whole.p(0.95),
                tools=sorted(tool_stats, key=lambda s: (-s.calls, s.name))[:TOP_LIMIT],
            )
        )
    return sorted(result, key=lambda s: (-s.calls, s.target))
