"""Live agent activity: agent_start / agent_end / agent_token are relayed, a
late joiner's snapshot lists who is working, nested steps keep their agent, and
nothing of it is saved with the answer except the steps' agent."""

from __future__ import annotations

import threading

from fastapi.testclient import TestClient

from tests.conftest import FakeAgent
from tests.test_registration import as_admin
from tests.test_turns import chat, events, new_id, start, wait_until

ORCH = {"agent_id": "claude-agent", "agent_label": "Ember"}
CALC = {"agent_id": "calc", "agent_label": "Calculator"}


def delegation_events() -> list[dict]:
    return [
        {"type": "step_start", "id": "d1", "tool": "delegate_to_agent", "label": "Delegate", "arguments": {}, **ORCH},
        {
            "type": "agent_start", "agent_id": "calc", "agent_label": "Calculator", "delegated_by": "claude-agent",
            "question": "q" * 900, "step_id": "d1", "at": "2026-10-04T09:12:03.512Z",
        },
        {"type": "agent_token", "step_id": "d1", "text": "t" * 5000, **CALC},
        # Same step id as the orchestrator's own step: only agent_id tells them apart.
        {"type": "step_start", "id": "d1", "tool": "tool_calc", "label": "Calc", "arguments": {"x": 1}, **CALC},
        {"type": "step_end", "id": "d1", "ok": True, "result": "4", **CALC},
        {"type": "agent_end", "agent_id": "calc", "agent_label": "Calculator", "ok": True, "step_id": "d1", "at": "2026-10-04T09:12:07.044Z"},
        {"type": "step_end", "id": "d1", "ok": True, "result": "Delegated to calc", **ORCH},
        {"type": "token", "text": "Done."},
    ]


def test_agent_events_are_relayed_with_their_caps(client: TestClient, agent: FakeAgent) -> None:
    as_admin(client)
    agent.events = delegation_events()
    agent.answer = "Done."
    chat_id = new_id()

    assert start(client, chat_id).status_code == 202
    # Join once the turn is over: a watcher that joins while it runs gets a
    # snapshot instead of the buffered events, which would make this racy.
    wait_until(lambda: (turn := client.app.state.turns.get(1, chat_id)) is not None and turn.status != "running")
    stream = events(client, chat_id)

    kinds = [e["type"] for e in stream]
    assert kinds.count("agent_start") == kinds.count("agent_end") == kinds.count("agent_token") == 1
    started = next(e for e in stream if e["type"] == "agent_start")
    assert (started["agent_id"], started["agent_label"], started["delegated_by"]) == ("calc", "Calculator", "claude-agent")
    assert len(started["question"]) == 500
    assert len(next(e for e in stream if e["type"] == "agent_token")["text"]) == 4000


def test_nested_steps_are_kept_apart_and_labelled_with_their_agent(client: TestClient, agent: FakeAgent) -> None:
    as_admin(client)
    agent.events = delegation_events()
    chat_id = new_id()
    start(client, chat_id)
    events(client, chat_id)

    steps = [m for m in chat(client, chat_id)["messages"] if m["role"] == "assistant"][-1]["steps"]

    assert [(s["tool"], s["agent_id"], s["ok"], s["result"]) for s in steps] == [
        ("delegate_to_agent", "claude-agent", True, "Delegated to calc"),
        ("tool_calc", "calc", True, "4"),
    ]
    assert steps[1]["agent_label"] == "Calculator"


def test_agent_tokens_are_not_saved_with_the_answer(client: TestClient, agent: FakeAgent) -> None:
    as_admin(client)
    agent.events = delegation_events()
    chat_id = new_id()
    start(client, chat_id)
    events(client, chat_id)

    saved = chat(client, chat_id)["messages"][-1]

    assert "ttt" not in saved["content"]
    assert "active_agents" not in saved


def test_a_late_joiner_is_told_who_is_working(client: TestClient, agent: FakeAgent) -> None:
    as_admin(client)
    agent.events = delegation_events()[:3]  # delegation started, specialist streaming
    agent.hold = True
    chat_id = new_id()
    start(client, chat_id)
    wait_until(lambda: agent.gate is not None)

    # TestClient hands over a streamed body only once it is complete, so the
    # turn is let go from another thread while the subscription waits.
    timer = threading.Timer(0.3, agent.release)
    timer.start()
    snapshot = events(client, chat_id)[0]
    timer.join()

    assert snapshot["type"] == "snapshot"
    assert snapshot["active_agents"] == [
        {"agent_id": "calc", "label": "Calculator", "since": "2026-10-04T09:12:03.512Z", "step_id": "d1"}
    ]


def test_the_stack_is_empty_when_the_turn_ends_without_agent_end(client: TestClient, agent: FakeAgent) -> None:
    as_admin(client)
    agent.events = delegation_events()[:2]  # started, never ended (specialist crashed)
    chat_id = new_id()
    start(client, chat_id)

    stream = events(client, chat_id)

    assert stream[-1]["type"] == "final"
    registry = client.app.state.turns
    turn = registry.get(1, chat_id)
    assert turn is not None and turn.active_agents == []
