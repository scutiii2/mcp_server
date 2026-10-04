"""Usage rows keep which agent, provider and gateway spent tokens and when."""

from __future__ import annotations

from datetime import datetime

from fastapi.testclient import TestClient

from src.services.usage_service import usage_rows
from tests.conftest import FakeAgent
from tests.test_registration import as_admin
from tests.test_turns import chat, events, new_id, start

ORCH_ROW = {
    "agent_id": "claude-agent", "agent_label": "Ember", "provider_id": "anthropic", "gateway": "openrouter",
    "model": "claude-sonnet-5-5", "input_tokens": 70, "output_tokens": 30, "total_tokens": 100,
    "started_at": "2026-10-04T09:12:03.512Z", "finished_at": "2026-10-04T09:12:07.044Z", "delegated_by": None,
}
CALC_ROW = {
    "agent_id": "calc", "agent_label": "Calculator", "provider_id": "openai", "gateway": None,
    "model": "gpt-x", "input_tokens": 20, "output_tokens": 5, "total_tokens": 25,
    "started_at": "2026-10-04T09:12:04.000Z", "finished_at": "2026-10-04T09:12:05.250Z", "delegated_by": "claude-agent",
}


def test_rows_carry_the_new_fields_and_name_the_agent_by_id() -> None:
    rows = usage_rows({"agent_usage": [ORCH_ROW, CALC_ROW]})

    assert [r["agent"] for r in rows] == ["claude-agent", "calc"]
    assert rows[0]["provider_id"] == "anthropic" and rows[0]["gateway"] == "openrouter"
    assert rows[0]["started_at"] == datetime(2026, 10, 4, 9, 12, 3, 512000)
    assert rows[0]["finished_at"] == datetime(2026, 10, 4, 9, 12, 7, 44000)
    assert rows[1]["delegated_by"] == "claude-agent" and rows[1]["gateway"] is None
    assert rows[1]["agent_label"] == "Calculator"


def test_an_older_row_without_the_fields_still_works() -> None:
    rows = usage_rows({"agent_usage": [{"provider_id": "claude", "model": "m", "total_tokens": 9}]})

    assert rows[0]["agent"] == "claude"
    assert rows[0]["agent_id"] is None and rows[0]["started_at"] is None


def test_bad_times_are_dropped_not_fatal() -> None:
    rows = usage_rows({"agent_usage": [{**ORCH_ROW, "started_at": "yesterday", "finished_at": 5}]})

    assert rows[0]["started_at"] is None and rows[0]["finished_at"] is None


def test_a_turn_stores_the_detail_and_the_answer_lists_each_agent(client: TestClient, agent: FakeAgent) -> None:
    as_admin(client)
    agent.result_extra = {"total_tokens": 125, "agent_usage": [ORCH_ROW, CALC_ROW]}
    chat_id = new_id()

    assert start(client, chat_id).status_code == 202
    events(client, chat_id)

    answer = [m for m in chat(client, chat_id)["messages"] if m["role"] == "assistant"][-1]
    assert [u["agent"] for u in answer["agent_usage"]] == ["claude-agent", "calc"]
    calc = answer["agent_usage"][1]
    assert (calc["agent_label"], calc["provider_id"], calc["total_tokens"]) == ("Calculator", "openai", 25)
    assert calc["started_at"] == "2026-10-04T09:12:04.000Z"
    assert calc["finished_at"] == "2026-10-04T09:12:05.250Z"
    # The saved answer must round-trip through a normal PUT.
    saved = chat(client, chat_id)
    put = client.put(
        f"/api/chats/{chat_id}",
        json={"title": saved["title"], "agent_id": saved["agent_id"], "messages": saved["messages"]},
    )
    assert put.status_code == 200, put.text
