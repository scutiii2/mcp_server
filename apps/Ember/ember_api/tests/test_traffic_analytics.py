from __future__ import annotations

from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from src.models import TrafficBucket
from src.services.traffic_analytics import LATENCY_CAP_MS, TrafficAnalytics, percentile
from tests.conftest import FakeEmailSender
from tests.test_admin import login, make_member, role_by_name
from tests.test_registration import as_admin

# A Monday, 13:30 UTC: the 24h window is 2026-10-04 14:00 .. 2026-10-05 14:00,
# the one before it 2026-10-03 14:00 .. 2026-10-04 14:00.
NOW = datetime(2026, 10, 5, 13, 30)

# Bands: 0 <=50ms, 1 <=100, 2 <=250, 3 <=500, 4 <=1000, 5 <=2500, 6 <=5000, 7 slower.
# (hour, kind, name, status, band, count)
ROWS = [
    # GET /api/chats: 100 requests, one of them a slow 5xx.
    (datetime(2026, 10, 5, 13), "http", "GET /api/chats", "2xx", 0, 90),
    (datetime(2026, 10, 5, 13), "http", "GET /api/chats", "2xx", 2, 9),
    (datetime(2026, 10, 5, 13), "http", "GET /api/chats", "5xx", 7, 1),
    (datetime(2026, 10, 5, 12), "http", "POST /api/chats/{chat_id}/turns", "2xx", 1, 4),
    (datetime(2026, 10, 5, 12), "http", "POST /api/chats/{chat_id}/turns", "4xx", 1, 2),
    (datetime(2026, 10, 4, 20), "http", "GET /api/usage", "2xx", 3, 3),  # too few to be ranked slowest
    # The previous 24h.
    (datetime(2026, 10, 4, 10), "http", "GET /api/chats", "2xx", 0, 50),
    (datetime(2026, 10, 4, 10), "http", "GET /api/chats", "5xx", 0, 50),
    # Outside both windows.
    (datetime(2026, 1, 1, 0), "http", "GET /api/old", "2xx", 0, 999),
    # Upstream calls.
    (datetime(2026, 10, 5, 13), "upstream", "ai_agent ask", "ok", 4, 8),
    (datetime(2026, 10, 5, 13), "upstream", "ai_agent ask", "failed", 7, 2),
    (datetime(2026, 10, 5, 13), "upstream", "ai_agent status", "ok", 0, 20),
    (datetime(2026, 10, 5, 12), "upstream", "mcp_server options_templates", "ok", 1, 3),
    (datetime(2026, 10, 4, 10), "upstream", "ai_agent ask", "failed", 4, 1),
]


def seed(client: TestClient) -> None:
    async def add() -> None:
        async with client.app.state.database.sessions() as session:
            session.add_all(
                TrafficBucket(hour=h, kind=k, name=n, status=s, band=b, count=c, total_ms=0) for h, k, n, s, b, c in ROWS
            )
            await session.commit()

    client.portal.call(add)


def report(client: TestClient, period: str = "24h"):
    async def run():
        async with client.app.state.database.sessions() as session:
            return await TrafficAnalytics(session).report(period, now=NOW)  # type: ignore[arg-type]

    return client.portal.call(run)


# --- percentiles -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("histogram", "fraction", "expected"),
    [
        ({}, 0.95, None),
        ({0: 1}, 0.5, 50),
        ({0: 90, 2: 9, 7: 1}, 0.5, 50),
        ({0: 90, 2: 9, 7: 1}, 0.95, 250),
        ({0: 90, 2: 9, 7: 1}, 1.0, LATENCY_CAP_MS),
        ({7: 3}, 0.5, LATENCY_CAP_MS),  # the slowest band has no bound: shown as the cap
        ({1: 2, 4: 2}, 0.5, 100),  # exactly half: still the lower band
        ({1: 2, 4: 2}, 0.51, 1000),
    ],
)
def test_percentile_is_the_upper_bound_of_its_band(histogram: dict[int, int], fraction: float, expected) -> None:
    assert percentile(histogram, fraction) == expected


def test_the_cap_is_the_last_bound() -> None:
    assert LATENCY_CAP_MS == 5000


# --- the report --------------------------------------------------------------------


def test_totals_compare_with_the_previous_period(client: TestClient) -> None:
    as_admin(client)
    seed(client)

    totals = report(client).totals

    assert (totals.requests.current, totals.requests.previous) == (109, 100)
    assert totals.error_rate.current == pytest.approx(1 / 109)
    assert totals.error_rate.previous == 0.5
    assert (totals.p95_ms.current, totals.p95_ms.previous) == (250, 50)
    assert (totals.upstream_failures.current, totals.upstream_failures.previous) == (2, 1)


def test_the_series_is_zero_filled_with_every_status_class(client: TestClient) -> None:
    as_admin(client)
    seed(client)

    series = report(client).series

    assert len(series) == 24
    assert series[0].bucket == "2026-10-04T14:00:00" and series[-1].bucket == "2026-10-05T13:00:00"
    by_bucket = {p.bucket: p for p in series}
    last = by_bucket["2026-10-05T13:00:00"]
    assert last.requests == {"2xx": 99, "3xx": 0, "4xx": 0, "5xx": 1}
    assert (last.p50_ms, last.p95_ms) == (50, 250)
    assert by_bucket["2026-10-05T12:00:00"].requests == {"2xx": 4, "3xx": 0, "4xx": 2, "5xx": 0}
    assert (by_bucket["2026-10-05T12:00:00"].p50_ms, by_bucket["2026-10-05T12:00:00"].p95_ms) == (100, 100)
    assert by_bucket["2026-10-04T20:00:00"].p50_ms == 500
    empty = by_bucket["2026-10-05T05:00:00"]
    assert empty.requests == {"2xx": 0, "3xx": 0, "4xx": 0, "5xx": 0} and empty.p50_ms is None and empty.p95_ms is None
    assert sum(sum(p.requests.values()) for p in series) == 109


def test_routes_rank_busiest_and_slowest(client: TestClient) -> None:
    as_admin(client)
    seed(client)

    routes = report(client).routes

    assert [(r.name, r.count) for r in routes.busiest] == [
        ("GET /api/chats", 100),
        ("POST /api/chats/{chat_id}/turns", 6),
        ("GET /api/usage", 3),
    ]
    assert routes.busiest[0].error_rate == pytest.approx(0.01)
    # GET /api/usage has 3 requests, under the minimum for the slowest list.
    assert [(r.name, r.p95_ms) for r in routes.slowest] == [
        ("GET /api/chats", 250),
        ("POST /api/chats/{chat_id}/turns", 100),
    ]


def test_upstream_is_grouped_by_target_with_failure_rates(client: TestClient) -> None:
    as_admin(client)
    seed(client)

    upstream = report(client).upstream

    assert [(u.target, u.calls, u.failures) for u in upstream] == [("ai_agent", 30, 2), ("mcp_server", 3, 0)]
    agent = upstream[0]
    assert agent.failure_rate == pytest.approx(2 / 30)
    assert agent.p95_ms == LATENCY_CAP_MS  # 2 of 30 calls were in the slowest band
    assert [(t.name, t.calls, t.failures, t.p95_ms) for t in agent.tools] == [
        ("status", 20, 0, 50),
        ("ask", 10, 2, LATENCY_CAP_MS),
    ]
    assert upstream[1].tools[0].name == "options_templates" and upstream[1].p95_ms == 100


def test_a_longer_range_uses_daily_buckets_and_reaches_further_back(client: TestClient) -> None:
    as_admin(client)
    seed(client)

    week = report(client, "7d")

    assert week.bucket == "day" and len(week.series) == 7
    assert week.series[0].bucket == "2026-09-29T00:00:00" and week.series[-1].bucket == "2026-10-05T00:00:00"
    assert week.totals.requests.current == 109 + 100  # the previous-24h rows are inside 7d now
    assert len(report(client, "90d").series) == 90
    assert report(client, "90d").totals.requests.current == 209  # January is past even 90 days


def test_with_no_traffic_everything_is_empty_not_missing(client: TestClient) -> None:
    as_admin(client)

    empty = report(client)

    assert (empty.totals.requests.current, empty.totals.requests.previous) == (0, 0)
    assert empty.totals.error_rate.current is None and empty.totals.p95_ms.current is None
    assert empty.totals.upstream_failures.current == 0
    assert len(empty.series) == 24 and all(sum(p.requests.values()) == 0 for p in empty.series)
    assert empty.routes.busiest == [] and empty.routes.slowest == [] and empty.upstream == []
    assert empty.latency_cap_ms == LATENCY_CAP_MS


# --- the route ---------------------------------------------------------------------


def test_the_route_returns_the_report_as_json(client: TestClient) -> None:
    as_admin(client)
    seed(client)

    response = client.get("/api/traffic/analytics", params={"range": "90d"})

    assert response.status_code == 200
    body = response.json()
    assert body["period"] == "90d" and body["bucket"] == "day" and body["latency_cap_ms"] == 5000
    assert len(body["series"]) == 90
    assert set(body["totals"]) == {"requests", "error_rate", "p95_ms", "upstream_failures"}
    assert body["totals"]["requests"]["current"] >= 109
    assert {u["target"] for u in body["upstream"]} == {"ai_agent", "mcp_server"}
    assert set(body["routes"]) == {"busiest", "slowest"}
    # What the page reads, and no more: nothing that names a person.
    assert "account" not in str(body).lower()


def test_the_default_range_is_a_week_and_a_bad_range_is_422(client: TestClient) -> None:
    as_admin(client)

    body = client.get("/api/traffic/analytics").json()

    assert body["period"] == "7d" and len(body["series"]) == 7
    assert len(client.get("/api/traffic/analytics", params={"range": "24h"}).json()["series"]) == 24
    assert client.get("/api/traffic/analytics", params={"range": "1y"}).status_code == 422


def test_the_route_needs_login_and_traffic_view(client: TestClient, email: FakeEmailSender) -> None:
    assert client.get("/api/traffic/analytics").status_code == 401

    make_member(client, email)
    login(client, "alice")
    denied = client.get("/api/traffic/analytics")
    assert denied.status_code == 403 and "traffic.view" in denied.json()["detail"]

    client.post("/api/auth/logout", json={})
    as_admin(client)  # the Administrator role holds it without being granted
    assert client.get("/api/traffic/analytics").status_code == 200
    member_role = role_by_name(client, "Member")["id"]
    assert client.put(f"/api/admin/roles/{member_role}/permissions/traffic.view").status_code == 200
    client.post("/api/auth/logout", json={})

    login(client, "alice")
    assert client.get("/api/traffic/analytics").status_code == 200


def test_a_new_member_role_does_not_get_traffic_view_by_default(client: TestClient) -> None:
    as_admin(client)

    assert "traffic.view" not in role_by_name(client, "Member")["permissions"]
    assert "traffic.view" in role_by_name(client, "Administrator")["permissions"]
