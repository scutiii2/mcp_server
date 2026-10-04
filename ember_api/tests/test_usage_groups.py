"""Usage grouped by agent, provider, gateway or model, filtered, and listed
row by row with their times."""

from __future__ import annotations

from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from tests.conftest import FakeAgent
from tests.test_registration import as_admin
from tests.test_turns import events, new_id, start
from tests.test_usage_report import Clock, clock  # noqa: F401 - the fixture

NOW = datetime(2026, 3, 15, 10, 0, 0)

ROWS = [
    {"agent_id": "claude-agent", "provider_id": "anthropic", "gateway": "openrouter", "model": "m1",
     "input_tokens": 60, "output_tokens": 40, "total_tokens": 100,
     "started_at": "2026-03-15T09:00:00.000Z", "finished_at": "2026-03-15T09:00:04.000Z"},
    {"agent_id": "calc", "provider_id": "openai", "gateway": "azure", "model": "m2",
     "input_tokens": 20, "output_tokens": 10, "total_tokens": 30, "delegated_by": "claude-agent",
     "started_at": "2026-03-15T09:00:01.000Z", "finished_at": "2026-03-15T09:00:02.000Z"},
]


def run_turn(client: TestClient, agent: FakeAgent) -> None:
    agent.result_extra = {"total_tokens": 130, "agent_usage": ROWS}
    chat_id = new_id()
    assert start(client, chat_id).status_code == 202
    events(client, chat_id)


def report(client: TestClient, **params) -> dict:
    response = client.get("/api/usage", params=params)
    assert response.status_code == 200, response.text
    return response.json()["report"]


@pytest.mark.parametrize(
    ("group_by", "expected"),
    [
        ("agent", {"claude-agent": 100, "calc": 30}),
        ("provider", {"anthropic": 100, "openai": 30}),
        ("gateway", {"openrouter": 100, "azure": 30}),
        ("model", {"m1": 100, "m2": 30}),
    ],
)
def test_groups(client: TestClient, agent: FakeAgent, clock, group_by, expected) -> None:  # noqa: F811
    as_admin(client)
    run_turn(client, agent)

    result = report(client, group_by=group_by)

    assert result["group_by"] == group_by
    assert {g["key"]: g["tokens"] for g in result["groups"]} == expected
    assert [g["tokens"] for g in result["groups"]] == sorted((g["tokens"] for g in result["groups"]), reverse=True)
    assert result["groups"][0]["turns"] == 1


def test_by_agent_is_unchanged_and_default_group_is_agent(client: TestClient, agent: FakeAgent, clock) -> None:  # noqa: F811
    as_admin(client)
    run_turn(client, agent)

    result = report(client)

    assert result["group_by"] == "agent"
    assert {(a["agent"], a["model"]): a["tokens"] for a in result["by_agent"]} == {
        ("claude-agent", "m1"): 100, ("calc", "m2"): 30,
    }


def test_filters_apply_to_totals_and_groups(client: TestClient, agent: FakeAgent, clock) -> None:  # noqa: F811
    as_admin(client)
    run_turn(client, agent)

    by_agent = report(client, agent="calc")
    by_provider = report(client, provider="anthropic", group_by="provider")

    assert by_agent["total_tokens"] == 30
    assert [g["key"] for g in by_provider["groups"]] == ["anthropic"]
    assert by_provider["total_tokens"] == 100


def test_unknown_group_by_is_422(client: TestClient) -> None:
    as_admin(client)

    assert client.get("/api/usage", params={"group_by": "colour"}).status_code == 422


def test_old_rows_without_detail_group_as_unknown(client: TestClient, agent: FakeAgent, clock) -> None:  # noqa: F811
    as_admin(client)
    agent.result_extra = {"total_tokens": 9, "agent_usage": [{"provider_id": "claude", "model": "m", "total_tokens": 9}]}
    chat_id = new_id()
    start(client, chat_id)
    events(client, chat_id)

    assert [g["key"] for g in report(client, group_by="gateway")["groups"]] == ["unknown"]
    assert [g["key"] for g in report(client, group_by="agent")["groups"]] == ["claude"]


def test_records_list_rows_newest_first_with_their_times(client: TestClient, agent: FakeAgent, clock) -> None:  # noqa: F811
    as_admin(client)
    run_turn(client, agent)

    response = client.get("/api/usage/records")

    assert response.status_code == 200
    rows = response.json()
    assert {r["agent_id"] for r in rows} == {"claude-agent", "calc"}
    calc = next(r for r in rows if r["agent_id"] == "calc")
    assert calc["provider_id"] == "openai" and calc["gateway"] == "azure"
    assert calc["delegated_by"] == "claude-agent"
    assert calc["started_at"].startswith("2026-03-15T09:00:01")
    assert calc["created_at"].startswith("2026-03-15T10:00:00")
    assert client.get("/api/usage/records", params={"agent": "calc"}).json() == [calc]
    assert len(client.get("/api/usage/records", params={"limit": 1}).json()) == 1


def test_records_need_login_and_a_sane_limit(client: TestClient) -> None:
    assert client.get("/api/usage/records").status_code == 401
    as_admin(client)
    assert client.get("/api/usage/records", params={"limit": 0}).status_code == 422
    assert client.get("/api/usage/records", params={"limit": 501}).status_code == 422
