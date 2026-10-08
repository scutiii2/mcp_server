from __future__ import annotations

from datetime import datetime

from fastapi.testclient import TestClient
from sqlalchemy import delete

from src.models import LogEntry
from src.services.log_analytics import LogAnalytics
from tests.conftest import FakeEmailSender
from tests.test_admin import login, make_member, role_by_name
from tests.test_logs import my_id
from tests.test_registration import as_admin

# A Monday, 13:30 UTC: the 24h window is 2026-10-04 14:00 .. 2026-10-05 14:00.
NOW = datetime(2026, 10, 5, 13, 30)
GHOST = 9999


def seed(client: TestClient, root: int) -> None:
    entries = [
        ("action", root, "auth.login", datetime(2026, 10, 5, 13, 10)),
        ("action", root, "auth.login", datetime(2026, 10, 5, 12, 50)),
        ("action", None, "backup.run", datetime(2026, 10, 4, 20, 0)),  # Sunday 20:00
        ("error", root, "http GET /api/chats", datetime(2026, 10, 5, 13, 5)),
        ("chat_trace", GHOST, "chat.turn", datetime(2026, 10, 3, 9, 0)),  # in 7d, not in 24h
        ("action", root, "auth.login", datetime(2026, 10, 4, 10, 0)),  # the previous 24h
        ("action", root, "auth.login", datetime(2026, 1, 1, 0, 0)),  # outside every window
    ]

    async def add() -> None:
        async with client.app.state.database.sessions() as session:
            # Drop the real entries (the admin's login) so only the seeded ones are counted.
            await session.execute(delete(LogEntry))
            session.add_all(
                LogEntry(kind=k, account_id=a, source=s, message="m", created_at=t) for k, a, s, t in entries
            )
            await session.commit()

    client.portal.call(add)


def report(client: TestClient, period: str, kinds: list[str]):
    async def run():
        async with client.app.state.database.sessions() as session:
            return await LogAnalytics(session).report(period, kinds, now=NOW)  # type: ignore[arg-type]

    return client.portal.call(run)


def test_24h_report_counts_every_chart(client: TestClient) -> None:
    as_admin(client)
    seed(client, my_id(client))

    r = report(client, "24h", ["action", "error", "chat_trace"])

    assert r.bucket == "hour" and r.kinds == ["action", "error", "chat_trace"]
    assert (r.totals["action"].current, r.totals["action"].previous) == (3, 1)
    assert (r.totals["error"].current, r.totals["error"].previous) == (1, 0)
    assert (r.totals["chat_trace"].current, r.totals["chat_trace"].previous) == (0, 0)

    # Zero-filled: 24 hourly buckets ending at the current hour.
    assert len(r.series) == 24
    assert r.series[0].bucket == "2026-10-04T14:00:00" and r.series[-1].bucket == "2026-10-05T13:00:00"
    by_bucket = {p.bucket: p.counts for p in r.series}
    assert by_bucket["2026-10-05T13:00:00"] == {"action": 1, "error": 1, "chat_trace": 0}
    assert by_bucket["2026-10-05T12:00:00"]["action"] == 1
    assert by_bucket["2026-10-04T20:00:00"]["action"] == 1
    assert sum(p.counts["action"] for p in r.series) == r.totals["action"].current

    assert [(s.source, s.count) for s in r.top_sources["action"]] == [("auth.login", 2), ("backup.run", 1)]
    assert [(a.username, a.count) for a in r.accounts["action"]] == [("root", 2), (None, 1)]
    assert r.accounts["action"][1].account_id is None  # the server itself

    cells = {(c.weekday, c.hour): c.count for c in r.heatmap}
    assert cells == {(1, 13): 2, (1, 12): 1, (0, 20): 1}


def test_week_report_uses_daily_buckets_and_a_deleted_account_has_no_name(client: TestClient) -> None:
    as_admin(client)
    seed(client, my_id(client))

    r = report(client, "7d", ["action", "error", "chat_trace"])

    assert r.bucket == "day" and len(r.series) == 7
    assert r.series[0].bucket == "2026-09-29T00:00:00" and r.series[-1].bucket == "2026-10-05T00:00:00"
    assert r.totals["chat_trace"].current == 1
    ghost = r.accounts["chat_trace"][0]
    assert (ghost.account_id, ghost.username, ghost.count) == (GHOST, None, 1)
    assert len(report(client, "90d", ["action"]).series) == 90


def test_only_the_asked_kinds_are_counted(client: TestClient) -> None:
    as_admin(client)
    seed(client, my_id(client))

    r = report(client, "24h", ["action"])

    assert r.kinds == ["action"] and list(r.totals) == ["action"]
    assert all(list(p.counts) == ["action"] for p in r.series)
    assert list(r.top_sources) == ["action"] and list(r.accounts) == ["action"]
    assert {(c.weekday, c.hour): c.count for c in r.heatmap} == {(1, 13): 1, (1, 12): 1, (0, 20): 1}
    assert report(client, "24h", []).series[0].counts == {}


def test_analytics_route_needs_a_logs_permission_and_hides_unreadable_kinds(
    client: TestClient, email: FakeEmailSender
) -> None:
    assert client.get("/api/logs/analytics").status_code == 401

    make_member(client, email)
    login(client, "alice")
    assert client.get("/api/logs/analytics").status_code == 403

    client.post("/api/auth/logout", json={})
    as_admin(client)
    member_role = role_by_name(client, "Member")["id"]
    assert client.put(f"/api/admin/roles/{member_role}/permissions/logs.view").status_code == 200
    everything = client.get("/api/logs/analytics")
    assert everything.status_code == 200
    assert everything.json()["kinds"] == ["action", "error", "chat_trace"]
    assert everything.json()["period"] == "7d" and len(everything.json()["series"]) == 7
    assert len(client.get("/api/logs/analytics", params={"range": "24h"}).json()["series"]) == 24
    client.post("/api/auth/logout", json={})

    login(client, "alice")
    body = client.get("/api/logs/analytics").json()
    assert body["kinds"] == ["action"]
    assert list(body["totals"]) == ["action"]
    assert client.get("/api/logs/analytics", params={"range": "1y"}).status_code == 422
