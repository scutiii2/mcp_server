"""The usage report: the busiest-hour histogram and the `since` period."""

from __future__ import annotations

from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from src.services import usage_service
from src.routes import usage as usage_routes
from tests.conftest import FakeAgent
from tests.test_registration import as_admin
from tests.test_turns import events, new_id, start

NOW = datetime(2026, 3, 15, 10, 0, 0)


class Clock:
    """What the usage code reads as "now" (naive UTC)."""

    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    clock = Clock()
    monkeypatch.setattr(usage_service, "utcnow", clock)
    monkeypatch.setattr(usage_routes, "utcnow", clock)
    return clock


def answer_at(client: TestClient, agent: FakeAgent, clock: Clock, when: datetime, tokens: int = 100) -> None:
    """One finished answer that spent `tokens`, recorded at `when`."""
    agent.result_extra = {
        "total_tokens": tokens,
        "agent_usage": [{"provider_id": "claude", "model": "m", "total_tokens": tokens}],
    }
    clock.now = when
    chat_id = new_id()
    assert start(client, chat_id).status_code == 202
    events(client, chat_id)
    clock.now = NOW


def report(client: TestClient, **params) -> dict:
    response = client.get("/api/usage", params=params)
    assert response.status_code == 200, response.text
    return response.json()["report"]


# --- hourly -------------------------------------------------------------------


def test_hourly_has_24_buckets_that_are_empty_without_usage(client: TestClient, clock: Clock) -> None:
    as_admin(client)

    assert report(client)["hourly"] == [0] * 24


def test_hourly_sums_tokens_by_utc_hour(client: TestClient, agent: FakeAgent, clock: Clock) -> None:
    as_admin(client)
    answer_at(client, agent, clock, datetime(2026, 3, 14, 3, 10), 100)
    answer_at(client, agent, clock, datetime(2026, 3, 14, 3, 50), 50)
    answer_at(client, agent, clock, datetime(2026, 3, 14, 14, 0), 25)

    hourly = report(client)["hourly"]

    assert len(hourly) == 24
    assert hourly[3] == 150
    assert hourly[14] == 25
    assert sum(hourly) == 175 == report(client)["total_tokens"]


def test_hourly_puts_midnight_and_the_last_hour_at_the_ends(client: TestClient, agent: FakeAgent, clock: Clock) -> None:
    as_admin(client)
    answer_at(client, agent, clock, datetime(2026, 3, 14, 0, 0), 7)
    answer_at(client, agent, clock, datetime(2026, 3, 14, 23, 59), 9)

    hourly = report(client)["hourly"]

    assert (hourly[0], hourly[23]) == (7, 9)


# --- since --------------------------------------------------------------------


def test_since_begins_at_midnight_of_that_day(client: TestClient, agent: FakeAgent, clock: Clock) -> None:
    as_admin(client)
    answer_at(client, agent, clock, datetime(2026, 2, 28, 23, 30), 1000)  # the day before
    answer_at(client, agent, clock, datetime(2026, 3, 1, 0, 30), 10)  # just after midnight on the 1st
    answer_at(client, agent, clock, datetime(2026, 3, 14, 12, 0), 5)

    result = report(client, since="2026-03-01")

    assert result["total_tokens"] == 15
    assert result["since"].startswith("2026-03-01T00:00:00")
    assert [d["date"] for d in result["daily"]] == ["2026-03-01", "2026-03-14"]


def test_since_replaces_days(client: TestClient, agent: FakeAgent, clock: Clock) -> None:
    as_admin(client)
    answer_at(client, agent, clock, datetime(2026, 3, 2, 12, 0), 10)

    assert report(client, days=1, since="2026-03-01")["total_tokens"] == 10
    assert report(client, days=1)["total_tokens"] == 0


def test_days_in_the_report_is_how_many_days_it_spans(client: TestClient, clock: Clock) -> None:
    as_admin(client)

    assert report(client, since="2026-03-01")["days"] == 15  # the 1st at midnight to the 15th at 10:00
    assert report(client, since="2026-03-15")["days"] == 1
    assert report(client, days=7)["days"] == 7


def test_since_today_covers_only_today(client: TestClient, agent: FakeAgent, clock: Clock) -> None:
    as_admin(client)
    answer_at(client, agent, clock, datetime(2026, 3, 14, 23, 59), 10)
    answer_at(client, agent, clock, datetime(2026, 3, 15, 0, 1), 4)

    assert report(client, since="2026-03-15")["total_tokens"] == 4


def test_the_oldest_allowed_since_works(client: TestClient, clock: Clock) -> None:
    as_admin(client)

    response = client.get("/api/usage", params={"since": "2025-03-14"})  # exactly 366 days back

    assert response.status_code == 200
    assert response.json()["report"]["days"] == 366


def test_since_older_than_the_longest_report_is_refused(client: TestClient, clock: Clock) -> None:
    as_admin(client)

    response = client.get("/api/usage", params={"since": "2025-03-13"})

    assert response.status_code == 422
    assert "366 days" in response.json()["detail"]


def test_since_in_the_future_is_refused(client: TestClient, clock: Clock) -> None:
    as_admin(client)

    response = client.get("/api/usage", params={"since": "2026-03-16"})

    assert response.status_code == 422
    assert "future" in response.json()["detail"]


def test_since_must_be_a_date(client: TestClient, clock: Clock) -> None:
    as_admin(client)

    assert client.get("/api/usage", params={"since": "last month"}).status_code == 422


def test_the_admin_totals_follow_since_too(client: TestClient, agent: FakeAgent, clock: Clock) -> None:
    as_admin(client)
    answer_at(client, agent, clock, datetime(2026, 2, 20, 12, 0), 1000)
    answer_at(client, agent, clock, datetime(2026, 3, 3, 12, 0), 10)

    everyone = client.get("/api/admin/usage", params={"since": "2026-03-01"}).json()

    assert [(row["username"], row["tokens"], row["turns"]) for row in everyone] == [("root", 10, 1)]
    assert client.get("/api/admin/usage", params={"since": "2026-03-16"}).status_code == 422


def test_without_since_nothing_changes(client: TestClient, agent: FakeAgent, clock: Clock) -> None:
    as_admin(client)
    answer_at(client, agent, clock, datetime(2026, 3, 10, 12, 0), 10)

    result = report(client, days=30)

    assert (result["total_tokens"], result["days"]) == (10, 30)
