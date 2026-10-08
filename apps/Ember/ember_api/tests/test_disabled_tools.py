"""Tools an account switched off for its own chats: what the browser may send
and what reaches the agent."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.conftest import FakeAgent
from tests.test_registration import as_admin
from tests.test_turns import events, new_id, start


def test_nothing_is_switched_off_unless_the_browser_says_so(client: TestClient, agent: FakeAgent) -> None:
    as_admin(client)
    chat_id = new_id()

    start(client, chat_id, "hi")
    events(client, chat_id)

    assert agent.asks[0]["disabled_tools"] == []


def test_the_switched_off_tools_are_passed_to_the_agent_once_each(client: TestClient, agent: FakeAgent) -> None:
    as_admin(client)
    chat_id = new_id()

    start(client, chat_id, "hi", disabled_tools=["tool_pdf_merge", "tool_calc", "tool_pdf_merge"])
    events(client, chat_id)

    assert agent.asks[0]["disabled_tools"] == ["tool_pdf_merge", "tool_calc"]


def test_a_tool_name_must_look_like_one(client: TestClient, agent: FakeAgent) -> None:
    as_admin(client)

    assert start(client, new_id(), "hi", disabled_tools=["not a tool!"]).status_code == 422
    assert start(client, new_id(), "hi", disabled_tools=["x" * 121]).status_code == 422


def test_at_most_2000_tools_can_be_switched_off(client: TestClient, agent: FakeAgent) -> None:
    as_admin(client)

    assert start(client, new_id(), "hi", disabled_tools=[f"t{i}" for i in range(2001)]).status_code == 422
    assert start(client, new_id(), "hi", disabled_tools=[f"t{i}" for i in range(2000)]).status_code == 202
