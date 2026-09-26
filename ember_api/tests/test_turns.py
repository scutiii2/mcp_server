from __future__ import annotations

import json
import threading
import time
import uuid

import pytest
from fastapi.testclient import TestClient

from src.config import UsageSettings
from tests.conftest import AGENTS, FakeAgent, FakeEmailSender
from tests.test_admin import login, make_member
from tests.test_registration import as_admin

AGENT_ID = AGENTS[0]["id"]


def new_id() -> str:
    return str(uuid.uuid4())


def start(client: TestClient, chat_id: str, question: str = "hi there", **extra):
    return client.post(f"/api/chats/{chat_id}/turns", json={"question": question, "agent_id": AGENT_ID, **extra})


def events(client: TestClient, chat_id: str, after: int = 0) -> list[dict]:
    with client.stream("GET", f"/api/chats/{chat_id}/events", params={"after": after}) as response:
        assert response.status_code == 200, response.read()
        assert response.headers["content-type"].startswith("text/event-stream")
        body = b"".join(response.iter_bytes()).decode()
    return [json.loads(line[6:]) for line in body.splitlines() if line.startswith("data: ")]


def streamed_text(stream: list[dict]) -> str:
    """The answer as a watcher sees it: a late subscriber gets the text so
    far as one snapshot, then the remaining tokens."""
    return "".join(e.get("text", "") for e in stream if e["type"] in ("snapshot", "token"))


def wait_until(predicate, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.02)


def chat(client: TestClient, chat_id: str) -> dict:
    return client.get(f"/api/chats/{chat_id}").json()


# --- a whole turn -------------------------------------------------------------


def test_turn_creates_chat_answers_and_saves(client: TestClient, agent: FakeAgent) -> None:
    as_admin(client)
    chat_id = new_id()

    response = start(client, chat_id, "What is up?", caveman=True)

    assert response.status_code == 202
    assert response.json()["chat"]["title"] == "What is up?"
    stream = events(client, chat_id)
    assert [e["type"] for e in stream][-1] == "final"
    assert streamed_text(stream) == "Hello!"
    saved = chat(client, chat_id)
    assert saved["running"] is False
    assert saved["agent_id"] == AGENT_ID
    assert saved["messages"] == [
        {"role": "user", "content": "What is up?"},
        {
            "role": "assistant",
            "content": "Hello!",
            "model": "claude-test",
            "total_tokens": 100,
            "context_tokens": 1000,
            "context_window": 200000,
        },
    ]
    asked = agent.asks[0]
    assert (asked["question"], asked["history"], asked["caveman"]) == ("What is up?", [], True)
    assert asked["url"] == AGENTS[0]["url"]
    assert asked["caller"].username == "root"


def test_second_turn_sends_history_without_raw_logs(client: TestClient, agent: FakeAgent) -> None:
    as_admin(client)
    chat_id = new_id()
    client.put(
        f"/api/chats/{chat_id}",
        json={
            "title": "t",
            "messages": [
                {"role": "assistant", "kind": "summary", "content": "S"},
                {"role": "assistant", "kind": "log_attachment", "content": "raw"},
                {"role": "user", "content": "q1"},
                {"role": "assistant", "content": "a1"},
            ],
        },
    )

    start(client, chat_id, "q2")
    events(client, chat_id)

    assert agent.asks[0]["history"] == [
        {"role": "assistant", "content": "S"},
        {"role": "user", "content": "q1"},
        {"role": "assistant", "content": "a1"},
    ]
    assert chat(client, chat_id)["message_count"] == 6


def test_turn_needs_chat_use_and_a_known_agent(client: TestClient, email: FakeEmailSender) -> None:
    assert start(client, new_id()).status_code == 401
    as_admin(client)
    response = client.post(f"/api/chats/{new_id()}/turns", json={"question": "hi", "agent_id": "nope"})
    assert response.status_code == 404
    client.post("/api/auth/logout", json={})

    make_member(client, email, verify=False)
    login(client, "alice")
    assert start(client, new_id()).status_code == 403


def test_agent_error_is_saved_and_streamed(client: TestClient, agent: FakeAgent) -> None:
    agent.fail = "provider is down"
    as_admin(client)
    chat_id = new_id()
    start(client, chat_id)

    stream = events(client, chat_id)

    assert stream[-1] == {"type": "error", "message": "provider is down", "sequence": stream[-1]["sequence"]}
    assert chat(client, chat_id)["messages"][-1] == {"role": "assistant", "content": "error: provider is down"}
    assert client.get("/api/usage").json()["six_hour"]["used"] == 0


# --- while running --------------------------------------------------------------


def test_running_turn_blocks_writes_and_a_second_turn(client: TestClient, agent: FakeAgent) -> None:
    agent.hold = True
    as_admin(client)
    chat_id = new_id()
    start(client, chat_id)
    wait_until(lambda: agent.gate is not None)

    assert chat(client, chat_id)["running"] is True
    assert client.get("/api/chats").json()[0]["running"] is True
    assert start(client, chat_id).status_code == 409
    assert client.put(f"/api/chats/{chat_id}", json={"title": "x", "messages": []}).status_code == 409
    assert client.post(f"/api/chats/{chat_id}/clear", json={}).status_code == 409
    assert client.patch(f"/api/chats/{chat_id}", json={"title": "Renamed"}).status_code == 200

    agent.release()
    events(client, chat_id)
    saved = chat(client, chat_id)
    assert saved["title"] == "Renamed"  # the answer didn't undo the rename
    assert saved["messages"][-1]["content"] == "Hello!"


def test_late_subscriber_gets_a_snapshot_then_the_rest(client: TestClient, agent: FakeAgent) -> None:
    agent.hold = True
    as_admin(client)
    chat_id = new_id()
    start(client, chat_id)
    wait_until(lambda: agent.gate is not None)

    # TestClient hands over a streamed body only once it's complete, so the
    # turn is let go from another thread while the subscription waits.
    timer = threading.Timer(0.3, agent.release)
    timer.start()
    stream = events(client, chat_id)
    timer.join()

    snapshot, rest = stream[0], stream[1:]
    assert (snapshot["type"], snapshot["text"]) == ("snapshot", "Hello!")
    assert rest[-1]["type"] == "final"
    assert not any(e["type"] == "token" for e in rest)


def test_cancel_keeps_what_streamed(client: TestClient, agent: FakeAgent) -> None:
    agent.hold = True
    as_admin(client)
    chat_id = new_id()
    start(client, chat_id)
    wait_until(lambda: agent.gate is not None)

    assert client.post(f"/api/chats/{chat_id}/cancel", json={}).json() == {"cancelled": True}
    stream = events(client, chat_id)

    assert stream[-1]["type"] == "final" and stream[-1]["cancelled"] is True
    assert chat(client, chat_id)["messages"][-1]["content"] == "Hello!\n\nCancelled."
    assert client.post(f"/api/chats/{chat_id}/cancel", json={}).json() == {"cancelled": False}


def test_deleting_a_running_chat_stops_it(client: TestClient, agent: FakeAgent) -> None:
    agent.hold = True
    as_admin(client)
    chat_id = new_id()
    start(client, chat_id)
    wait_until(lambda: agent.gate is not None)

    assert client.delete(f"/api/chats/{chat_id}").status_code == 204

    assert agent.cancels  # ai_agent was told to stop
    assert client.get(f"/api/chats/{chat_id}").status_code == 404
    assert client.get(f"/api/chats/{chat_id}/events").status_code == 404


def test_turns_are_private(client_factory, email: FakeEmailSender, agent: FakeAgent) -> None:
    agent.hold = True
    alice = client_factory()
    make_member(alice, email)
    login(alice, "alice")
    chat_id = new_id()
    start(alice, chat_id)
    wait_until(lambda: agent.gate is not None)

    admin = as_admin(client_factory())
    assert admin.get(f"/api/chats/{chat_id}/events").status_code == 404
    assert admin.post(f"/api/chats/{chat_id}/cancel", json={}).json() == {"cancelled": False}
    agent.release()


def test_no_turn_to_watch_is_404(client: TestClient) -> None:
    as_admin(client)
    assert client.get(f"/api/chats/{new_id()}/events").status_code == 404


# --- usage --------------------------------------------------------------------


def test_usage_is_recorded_and_reported(client: TestClient, agent: FakeAgent) -> None:
    as_admin(client)
    chat_id = new_id()
    start(client, chat_id)
    events(client, chat_id)

    usage = client.get("/api/usage").json()

    assert usage["six_hour"]["used"] == 100
    assert usage["weekly"]["limit"] == 5_000_000
    report = usage["report"]
    assert (report["total_tokens"], report["turns"], report["chats"]) == (100, 1, 1)
    assert report["by_agent"] == [{"agent": "claude", "model": "claude-test", "tokens": 100}]
    assert len(report["daily"]) == 1
    admin_view = client.get("/api/admin/usage").json()
    assert [(r["username"], r["tokens"], r["turns"]) for r in admin_view] == [("root", 100, 1)]


def test_delegated_agents_count_separately(client: TestClient, agent: FakeAgent) -> None:
    agent.result_extra = {
        "agent_usage": [
            {"provider_id": "claude", "model": "a", "total_tokens": 100},
            {"provider_id": "openai", "model": "b", "total_tokens": 50},
        ]
    }
    as_admin(client)
    chat_id = new_id()
    start(client, chat_id)
    events(client, chat_id)

    report = client.get("/api/usage").json()["report"]

    assert (report["total_tokens"], report["turns"]) == (150, 1)
    assert {r["agent"] for r in report["by_agent"]} == {"claude", "openai"}


def test_usage_limit_blocks_new_turns(client_factory, agent: FakeAgent) -> None:
    client = as_admin(client_factory(usage=UsageSettings(six_hour_token_limit=100)))
    chat_id = new_id()
    start(client, chat_id)
    events(client, chat_id)

    response = start(client, chat_id, "again")

    assert response.status_code == 429
    assert "6-hour token limit" in response.json()["detail"]
    assert int(response.headers["Retry-After"]) > 0
    assert len(agent.asks) == 1
    assert chat(client, chat_id)["message_count"] == 2  # the refused question wasn't saved


def test_usage_needs_login(client: TestClient) -> None:
    assert client.get("/api/usage").status_code == 401


# --- summarize / clear ----------------------------------------------------------


def seed(client: TestClient, chat_id: str, context_tokens: int = 1000) -> None:
    client.put(
        f"/api/chats/{chat_id}",
        json={
            "title": "t",
            "agent_id": AGENT_ID,
            "messages": [
                {"role": "user", "content": "q1"},
                {"role": "assistant", "content": "a1", "context_tokens": context_tokens, "context_window": 200000},
            ],
        },
    )


def test_manual_summarize(client: TestClient, agent: FakeAgent) -> None:
    as_admin(client)
    chat_id = new_id()
    seed(client, chat_id)

    response = client.post(f"/api/chats/{chat_id}/summarize", json={})

    assert response.status_code == 200
    messages = response.json()["messages"]
    assert [m.get("kind") for m in messages] == ["summary", "log_attachment"]
    assert messages[0]["content"] == "SUMMARY"
    assert "--- user ---\nq1" in messages[1]["content"]
    assert "q1" in agent.interprets[0]
    assert client.get("/api/usage").json()["report"]["summary_tokens"] == 10
    # Nothing new since: no second agent call.
    client.post(f"/api/chats/{chat_id}/summarize", json={})
    assert len(agent.interprets) == 1


def test_failed_summarize_changes_nothing(client: TestClient, agent: FakeAgent) -> None:
    agent.fail = "agent offline"
    as_admin(client)
    chat_id = new_id()
    seed(client, chat_id)

    response = client.post(f"/api/chats/{chat_id}/summarize", json={})

    assert response.status_code == 502
    assert "agent offline" in response.json()["detail"]
    assert chat(client, chat_id)["message_count"] == 2


def test_clear_keeps_one_raw_log(client: TestClient, agent: FakeAgent) -> None:
    as_admin(client)
    chat_id = new_id()
    seed(client, chat_id)

    messages = client.post(f"/api/chats/{chat_id}/clear", json={}).json()["messages"]

    assert [m["kind"] for m in messages] == ["log_attachment"]
    assert agent.interprets == []
    start(client, chat_id, "fresh start")
    events(client, chat_id)
    assert agent.asks[0]["history"] == []


def test_auto_summarize_when_context_nearly_full(client: TestClient, agent: FakeAgent) -> None:
    as_admin(client)
    chat_id = new_id()
    seed(client, chat_id, context_tokens=100_000)  # >= 0.6 of the 150k cap

    start(client, chat_id, "q2")
    stream = events(client, chat_id)

    types = [e["type"] for e in stream]
    assert "summarized" in types or ("snapshot" in types and len(agent.interprets) == 1)
    assert agent.asks[0]["history"] == [{"role": "assistant", "content": "SUMMARY"}]
    kinds = [m.get("kind") for m in chat(client, chat_id)["messages"]]
    assert kinds == ["summary", "log_attachment", None, None]


def test_auto_summarize_failure_still_answers(client: TestClient, agent: FakeAgent) -> None:
    as_admin(client)
    chat_id = new_id()
    seed(client, chat_id, context_tokens=100_000)
    agent.summary = ""  # empty summary = failure

    start(client, chat_id, "q2")
    events(client, chat_id)

    assert len(agent.asks[0]["history"]) == 2
    assert chat(client, chat_id)["messages"][-1]["content"] == "Hello!"


@pytest.mark.parametrize("ratio", [0.0, 1.5])
def test_bad_summarize_ratio_is_refused(ratio: float) -> None:
    with pytest.raises(ValueError):
        UsageSettings.from_config({"auto_summarize_ratio": ratio})
