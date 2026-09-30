"""Asking before tools run: the turn options that reach the agent, the
approvals route, what watchers see, and who may answer."""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from src.models import LogEntry
from tests.conftest import FakeAgent, FakeEmailSender
from tests.test_admin import login, make_member
from tests.test_registration import as_admin
from tests.test_turns import chat, events, new_id, start, wait_until

TOOL = "tool_srv_stopApp"


def approve(client: TestClient, chat_id: str, step_id: str = "step0", decision: str = "allow"):
    return client.post(f"/api/chats/{chat_id}/approvals", json={"step_id": step_id, "decision": decision})


def turn_of(client: TestClient, chat_id: str):
    (turn,) = [t for (_account, c), t in client.app.state.turns._turns.items() if c == chat_id]
    return turn


def wait_for_request(client: TestClient, chat_id: str, step_id: str = "step0") -> None:
    """Until the agent is waiting on the user for this step."""
    wait_until(lambda: step_id in turn_of(client, chat_id).pending_approvals)


def whole_stream(client: TestClient, chat_id: str) -> list[dict]:
    """The turn's events once it has finished. (A watcher that joins while it
    still runs gets a snapshot instead of the events already folded into it.)"""
    wait_until(lambda: turn_of(client, chat_id).status != "running")
    return events(client, chat_id)


def begin(client: TestClient, agent: FakeAgent, *tools: str, ask: bool = True, **extra) -> str:
    """Starts a turn whose agent wants to run `tools`; returns the chat id."""
    agent.tool_calls = list(tools or (TOOL,))
    chat_id = new_id()
    response = start(client, chat_id, "please stop it", ask_before_tools=ask, **extra)
    assert response.status_code == 202, response.text
    return chat_id


# --- what reaches the agent ------------------------------------------------------------------


def test_asking_is_off_unless_the_browser_turns_it_on(client: TestClient, agent: FakeAgent) -> None:
    as_admin(client)
    chat_id = new_id()

    start(client, chat_id, "hi")
    events(client, chat_id)

    assert agent.asks[0]["approval_mode"] == "off"


def test_the_options_are_passed_to_the_agent(client: TestClient, agent: FakeAgent) -> None:
    as_admin(client)
    chat_id = new_id()

    start(client, chat_id, "hi", ask_before_tools=True, allowed_tools=["tool_a", "tool_b", "tool_a"])
    events(client, chat_id)

    assert agent.asks[0]["approval_mode"] == "ask"
    assert agent.asks[0]["allowed_tools"] == ["tool_a", "tool_b"]  # asked once each


@pytest.mark.parametrize("names", [["has space"], ["x" * 121], [""], ["a/b"], ["ok", "not ok"]])
def test_allowed_tool_names_are_validated(client: TestClient, agent: FakeAgent, names: list[str]) -> None:
    as_admin(client)

    response = start(client, new_id(), "hi", ask_before_tools=True, allowed_tools=names)

    assert response.status_code == 422
    assert agent.asks == []


def test_at_most_200_allowed_tools(client: TestClient, agent: FakeAgent) -> None:
    as_admin(client)

    assert start(client, new_id(), "hi", allowed_tools=[f"t{i}" for i in range(201)]).status_code == 422
    assert start(client, new_id(), "hi", allowed_tools=[f"t{i}" for i in range(200)]).status_code == 202


# --- answering -------------------------------------------------------------------------------


def test_allow_lets_the_tool_run(client: TestClient, agent: FakeAgent) -> None:
    as_admin(client)
    chat_id = begin(client, agent)
    wait_for_request(client, chat_id)
    assert agent.ran == []  # nothing ran while it waited

    response = approve(client, chat_id, decision="allow")

    assert (response.status_code, response.json()) == (200, {"decided": True})
    stream = whole_stream(client, chat_id)
    assert agent.ran == [TOOL]
    kinds = [e["type"] for e in stream if e["type"] in ("step_start", "approval_request", "approval_resolved", "step_end", "final")]
    assert kinds == ["step_start", "approval_request", "approval_resolved", "step_end", "final"]
    request = next(e for e in stream if e["type"] == "approval_request")
    assert (request["id"], request["tool"], request["arguments"]) == ("step0", TOOL, {"a": 1})
    assert next(e for e in stream if e["type"] == "approval_resolved")["outcome"] == "allow"
    saved = chat(client, chat_id)["messages"][-1]
    assert saved["steps"][0]["ok"] is True
    assert agent.decisions == [(turn_request_id(agent), "step0", "allow")]


def turn_request_id(agent: FakeAgent) -> str:
    return agent.asks[0]["request_id"]


def test_deny_keeps_the_tool_from_running(client: TestClient, agent: FakeAgent) -> None:
    as_admin(client)
    chat_id = begin(client, agent)
    wait_for_request(client, chat_id)

    assert approve(client, chat_id, decision="deny").status_code == 200

    events(client, chat_id)
    assert agent.ran == []
    assert chat(client, chat_id)["messages"][-1]["steps"][0]["ok"] is False


def test_always_is_passed_on_to_the_agent(client: TestClient, agent: FakeAgent) -> None:
    as_admin(client)
    chat_id = begin(client, agent)
    wait_for_request(client, chat_id)

    approve(client, chat_id, decision="always")

    events(client, chat_id)
    assert agent.decisions[0][2] == "always"
    assert agent.ran == [TOOL]


def test_tools_already_allowed_for_the_chat_do_not_ask(client: TestClient, agent: FakeAgent) -> None:
    as_admin(client)
    chat_id = begin(client, agent, TOOL, allowed_tools=[TOOL])

    events(client, chat_id)

    assert agent.ran == [TOOL]
    assert agent.decisions == []


def test_each_tool_of_a_turn_asks_in_turn(client: TestClient, agent: FakeAgent) -> None:
    as_admin(client)
    chat_id = begin(client, agent, "tool_one", "tool_two")

    wait_for_request(client, chat_id, "step0")
    approve(client, chat_id, "step0", "allow")
    wait_for_request(client, chat_id, "step1")
    approve(client, chat_id, "step1", "deny")

    events(client, chat_id)
    assert agent.ran == ["tool_one"]
    assert [s["ok"] for s in chat(client, chat_id)["messages"][-1]["steps"]] == [True, False]


def test_the_late_joiner_snapshot_lists_what_is_waiting(client: TestClient, agent: FakeAgent) -> None:
    as_admin(client)
    chat_id = begin(client, agent)
    wait_for_request(client, chat_id)

    snapshot = turn_of(client, chat_id).snapshot()

    assert snapshot["approvals"] == [{"id": "step0", "tool": TOOL, "label": TOOL.upper(), "arguments": {"a": 1}}]
    assert snapshot["activity"] == "waiting for your approval"
    approve(client, chat_id)
    events(client, chat_id)
    assert turn_of(client, chat_id).snapshot()["approvals"] == []


def test_stop_ends_the_wait_and_the_tool_never_runs(client: TestClient, agent: FakeAgent) -> None:
    as_admin(client)
    chat_id = begin(client, agent)
    wait_for_request(client, chat_id)

    assert client.post(f"/api/chats/{chat_id}/cancel", json={}).json() == {"cancelled": True}

    stream = whole_stream(client, chat_id)
    assert agent.ran == []
    assert stream[-1]["type"] == "final" and stream[-1]["cancelled"] is True
    assert next(e for e in stream if e["type"] == "approval_resolved")["outcome"] == "cancelled"
    assert turn_of(client, chat_id).pending_approvals == {}


# --- who may answer ---------------------------------------------------------------------------


def test_answering_needs_login_and_chat_use(client: TestClient, email: FakeEmailSender) -> None:
    assert approve(client, new_id()).status_code == 401

    make_member(client, email, verify=False)
    login(client, "alice")
    assert approve(client, new_id()).status_code == 403


def test_nothing_running_is_404(client: TestClient, agent: FakeAgent) -> None:
    as_admin(client)

    assert approve(client, new_id()).status_code == 404
    chat_id = new_id()
    start(client, chat_id, "hi")
    events(client, chat_id)
    assert approve(client, chat_id).status_code == 404  # finished


def test_another_account_cannot_answer_for_a_running_turn(client_factory, email: FakeEmailSender, agent: FakeAgent) -> None:
    alice = client_factory()
    make_member(alice, email)
    make_member(alice, email, "bob")
    login(alice, "alice")
    chat_id = begin(alice, agent)
    wait_for_request(alice, chat_id)
    bob = client_factory()
    login(bob, "bob")

    response = approve(bob, chat_id, decision="allow")

    assert response.status_code == 404
    assert agent.decisions == []
    assert agent.ran == []
    approve(alice, chat_id, decision="deny")
    events(alice, chat_id)


def test_an_unknown_step_is_refused_and_nothing_changes(client: TestClient, agent: FakeAgent) -> None:
    as_admin(client)
    chat_id = begin(client, agent)
    wait_for_request(client, chat_id)

    response = approve(client, chat_id, "made-up-step", "allow")

    assert response.status_code == 409
    assert agent.decisions == []
    assert "step0" in turn_of(client, chat_id).pending_approvals
    approve(client, chat_id, "step0", "deny")
    events(client, chat_id)


def test_a_step_that_was_answered_cannot_be_answered_again(client: TestClient, agent: FakeAgent) -> None:
    as_admin(client)
    chat_id = begin(client, agent, "tool_one", "tool_two")
    wait_for_request(client, chat_id, "step0")
    assert approve(client, chat_id, "step0", "deny").status_code == 200
    wait_for_request(client, chat_id, "step1")  # the turn moved on to the next tool

    again = approve(client, chat_id, "step0", "allow")

    assert again.status_code == 409
    assert agent.ran == []
    approve(client, chat_id, "step1", "deny")
    events(client, chat_id)


def test_the_agent_saying_nothing_is_waiting_is_a_conflict(client: TestClient, agent: FakeAgent) -> None:
    as_admin(client)
    chat_id = begin(client, agent)
    wait_for_request(client, chat_id)
    agent.decide_result = False

    response = approve(client, chat_id, decision="allow")

    assert response.status_code == 409
    agent.decide_result = None
    approve(client, chat_id, decision="deny")
    events(client, chat_id)


def test_an_unreachable_agent_is_a_bad_gateway_and_the_tool_stays_blocked(client: TestClient, agent: FakeAgent) -> None:
    as_admin(client)
    chat_id = begin(client, agent)
    wait_for_request(client, chat_id)
    agent.decide_error = "Could not reach the agent: refused"

    response = approve(client, chat_id, decision="allow")

    assert response.status_code == 502
    assert "Could not reach the agent" in response.json()["detail"]
    assert agent.ran == []
    agent.decide_error = None
    approve(client, chat_id, decision="deny")
    events(client, chat_id)


@pytest.mark.parametrize(
    "body",
    [
        {"step_id": "step0", "decision": "yes"},
        {"step_id": "step0", "decision": "ALLOW"},
        {"step_id": "step0"},
        {"decision": "allow"},
        {"step_id": "", "decision": "allow"},
        {"step_id": "x" * 201, "decision": "allow"},
        {"step_id": 5, "decision": "allow"},
    ],
)
def test_the_answer_is_validated(client: TestClient, agent: FakeAgent, body: dict) -> None:
    as_admin(client)

    assert client.post(f"/api/chats/{new_id()}/approvals", json=body).status_code == 422


def test_answers_are_posted_as_json_only(client: TestClient) -> None:
    as_admin(client)

    response = client.post(
        f"/api/chats/{new_id()}/approvals", content="step_id=step0&decision=allow", headers={"Content-Type": "text/plain"}
    )

    assert response.status_code == 415


def test_answers_are_written_to_the_activity_log(client: TestClient, agent: FakeAgent) -> None:
    as_admin(client)
    chat_id = begin(client, agent)
    wait_for_request(client, chat_id)
    approve(client, chat_id, decision="allow")
    events(client, chat_id)

    async def entries(session):
        rows = await session.scalars(select(LogEntry).where(LogEntry.source == "tool.approval"))
        return [r.message for r in rows]

    async def read():
        async with client.app.state.database.sessions() as session:
            return await entries(session)

    assert client.portal.call(read) == [f'allow: "{TOOL}"']


def test_a_turn_that_ended_leaves_nothing_pending(client: TestClient, agent: FakeAgent) -> None:
    as_admin(client)
    chat_id = begin(client, agent)
    wait_for_request(client, chat_id)
    approve(client, chat_id, decision="allow")
    events(client, chat_id)
    deadline = time.monotonic() + 2

    while turn_of(client, chat_id).status == "running":
        assert time.monotonic() < deadline
        time.sleep(0.02)

    assert turn_of(client, chat_id).pending_approvals == {}
