from __future__ import annotations

import re
import uuid

import pytest
from fastapi.testclient import TestClient

from src.services import chat_service
from tests.conftest import FakeAgent, FakeEmailSender
from tests.test_admin import login, make_member
from tests.test_registration import as_admin
from tests.test_turns import events, start

STEP = {"tool": "tool_x", "label": "X", "arguments": {"a": 1}, "ok": True, "result": "done"}

ANSWER = {
    "role": "assistant",
    "content": "a1",
    "model": "claude-test",
    "total_tokens": 100,
    "input_tokens": 70,
    "output_tokens": 30,
    "duration_s": 1.5,
    "context_tokens": 1000,
    "context_window": 200000,
    "steps": [STEP],
}

CONVERSATION = [
    {"role": "user", "content": "q1"},
    ANSWER,
    {"role": "user", "content": "q2"},
    {"role": "assistant", "content": "a2"},
]


def new_id() -> str:
    return str(uuid.uuid4())


def make_chat(client: TestClient, messages=None, title: str = "Deploy notes", agent_id: str | None = "claude-agent") -> str:
    chat_id = new_id()
    response = client.put(
        f"/api/chats/{chat_id}",
        json={"title": title, "agent_id": agent_id, "messages": messages if messages is not None else CONVERSATION},
    )
    assert response.status_code == 200
    return chat_id


def branch(client: TestClient, chat_id: str, upto: int):
    return client.post(f"/api/chats/{chat_id}/branch", json={"upto": upto})


def listing(client: TestClient) -> list[dict]:
    return client.get("/api/chats").json()


# --- access -------------------------------------------------------------------


def test_branching_needs_login_and_chat_use(client: TestClient, email: FakeEmailSender) -> None:
    assert branch(client, new_id(), 1).status_code == 401

    make_member(client, email, verify=False)
    login(client, "alice")
    assert branch(client, new_id(), 1).status_code == 403  # unverified: no permissions


def test_another_accounts_chat_cannot_be_branched(client_factory, email: FakeEmailSender) -> None:
    alice = client_factory()
    make_member(alice, email)
    make_member(alice, email, "bob")
    login(alice, "alice")
    chat_id = make_chat(alice)
    bob = client_factory()
    login(bob, "bob")

    assert branch(bob, chat_id, 1).status_code == 404
    assert listing(bob) == []


# --- what a branch is -----------------------------------------------------------


def test_branch_copies_up_to_and_including_the_answer(client: TestClient) -> None:
    as_admin(client)
    source = make_chat(client)

    response = branch(client, source, 1)

    assert response.status_code == 201
    created = response.json()
    assert created["id"] != source
    assert re.fullmatch(r"[A-Za-z0-9-]{8,64}", created["id"])
    assert created["title"] == "Branch of Deploy notes"
    assert created["agent_id"] == "claude-agent"
    assert created["message_count"] == 2
    assert created["running"] is False
    # Every field of the answer comes along: usage numbers and tool steps too.
    assert created["messages"] == CONVERSATION[:2]
    assert client.get(f"/api/chats/{created['id']}").json()["messages"] == CONVERSATION[:2]


def test_the_original_is_untouched_and_the_branch_is_listed(client: TestClient) -> None:
    as_admin(client)
    source = make_chat(client)
    before = client.get(f"/api/chats/{source}").json()

    created = branch(client, source, 1).json()

    after = client.get(f"/api/chats/{source}").json()
    assert after["messages"] == before["messages"]
    assert (after["title"], after["updated_at"]) == (before["title"], before["updated_at"])
    assert {c["id"] for c in listing(client)} == {source, created["id"]}


def test_branching_at_the_last_answer_copies_everything(client: TestClient) -> None:
    as_admin(client)
    source = make_chat(client)

    created = branch(client, source, 3).json()

    assert created["messages"] == CONVERSATION
    assert created["message_count"] == 4


def test_the_branch_and_its_source_do_not_share_anything(client: TestClient) -> None:
    as_admin(client)
    source = make_chat(client)
    created = branch(client, source, 1).json()

    client.patch(f"/api/chats/{created['id']}", json={"title": "Renamed branch"})
    client.put(
        f"/api/chats/{source}",
        json={"title": "Deploy notes", "agent_id": None, "messages": [{"role": "user", "content": "changed"}]},
    )

    assert client.get(f"/api/chats/{created['id']}").json()["messages"] == CONVERSATION[:2]
    assert client.get(f"/api/chats/{source}").json()["title"] == "Deploy notes"
    assert client.get(f"/api/chats/{created['id']}").json()["title"] == "Renamed branch"


def test_a_branch_can_be_branched_and_each_gets_its_own_id(client: TestClient) -> None:
    as_admin(client)
    source = make_chat(client)

    first = branch(client, source, 1).json()
    second = branch(client, source, 1).json()
    nested = branch(client, first["id"], 1).json()

    assert len({source, first["id"], second["id"], nested["id"]}) == 4
    assert nested["title"] == "Branch of Branch of Deploy notes"


def test_a_source_without_an_agent_gives_a_branch_without_one(client: TestClient) -> None:
    as_admin(client)
    source = make_chat(client, agent_id=None)

    assert branch(client, source, 1).json()["agent_id"] is None


def test_a_long_title_is_cut_to_the_column_size(client: TestClient) -> None:
    as_admin(client)
    source = make_chat(client, title="t" * 120)

    title = branch(client, source, 1).json()["title"]

    assert len(title) == 120
    assert title.startswith("Branch of t") and title.endswith("…")


def test_a_branch_can_carry_on_the_conversation(client: TestClient, agent: FakeAgent) -> None:
    as_admin(client)
    source = make_chat(client)
    created = branch(client, source, 1).json()

    assert start(client, created["id"], "a different follow-up").status_code == 202
    events(client, created["id"])

    assert [m["content"] for m in client.get(f"/api/chats/{created['id']}").json()["messages"]] == [
        "q1",
        "a1",
        "a different follow-up",
        "Hello!",
    ]
    # The agent saw only the shared part as history.
    assert [m["content"] for m in agent.asks[0]["history"]] == ["q1", "a1"]
    assert len(client.get(f"/api/chats/{source}").json()["messages"]) == 4


# --- where a branch may end -----------------------------------------------------


@pytest.mark.parametrize("upto", [0, 2])
def test_a_question_is_not_a_branch_point(client: TestClient, upto: int) -> None:
    as_admin(client)
    source = make_chat(client)

    assert branch(client, source, upto).status_code == 422
    assert len(listing(client)) == 1


def test_summaries_logs_and_command_results_are_not_branch_points(client: TestClient) -> None:
    as_admin(client)
    source = make_chat(
        client,
        [
            {"role": "assistant", "kind": "summary", "content": "S"},
            {"role": "assistant", "kind": "log_attachment", "content": "raw"},
            {"role": "user", "kind": "command", "content": "/x y"},
            {"role": "assistant", "kind": "command", "content": "result"},
            {"role": "user", "content": "q"},
            {"role": "assistant", "content": "a"},
        ],
    )

    for upto in range(4):
        assert branch(client, source, upto).status_code == 422
    assert len(listing(client)) == 1

    created = branch(client, source, 5).json()
    assert [m["content"] for m in created["messages"]] == ["S", "raw", "/x y", "result", "q", "a"]


@pytest.mark.parametrize("upto", [4, 99])
def test_an_index_past_the_end_is_refused(client: TestClient, upto: int) -> None:
    as_admin(client)
    source = make_chat(client)

    assert branch(client, source, upto).status_code == 422


def test_a_bad_request_body_is_refused(client: TestClient) -> None:
    as_admin(client)
    source = make_chat(client)

    assert branch(client, source, -1).status_code == 422
    assert client.post(f"/api/chats/{source}/branch", json={}).status_code == 422
    assert client.post(f"/api/chats/{source}/branch", json={"upto": "one"}).status_code == 422
    assert client.post(f"/api/chats/{source}/branch", json={"upto": 1.5}).status_code == 422
    assert client.post(f"/api/chats/{source}/branch", content="upto=1", headers={"Content-Type": "text/plain"}).status_code == 415
    assert len(listing(client)) == 1


def test_an_unknown_chat_is_404(client: TestClient) -> None:
    as_admin(client)

    assert branch(client, new_id(), 1).status_code == 404
    assert branch(client, "x", 1).status_code == 422  # not even an id


def test_the_chat_count_limit_applies(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(chat_service, "MAX_CHATS_PER_ACCOUNT", 1)
    as_admin(client)
    source = make_chat(client)

    response = branch(client, source, 1)

    assert response.status_code == 413
    assert len(listing(client)) == 1


# --- while the source is answering ------------------------------------------------


def test_a_chat_can_be_branched_while_it_is_answering(client: TestClient, agent: FakeAgent) -> None:
    as_admin(client)
    source = make_chat(client)
    agent.hold = True
    assert start(client, source, "q3").status_code == 202

    response = branch(client, source, 1)

    try:
        assert response.status_code == 201
        # Only saved messages are copied, and the source keeps running.
        assert [m["content"] for m in response.json()["messages"]] == ["q1", "a1"]
        assert client.get(f"/api/chats/{source}").json()["running"] is True
        assert response.json()["running"] is False
    finally:
        agent.release()
    events(client, source)
    assert len(client.get(f"/api/chats/{source}").json()["messages"]) == 6
