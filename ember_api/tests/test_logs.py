from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from src.services.chat_service import ChatService
from tests.conftest import AGENTS, FakeAgent, FakeEmailSender
from tests.test_admin import login, make_member, role_by_name
from tests.test_registration import as_admin
from tests.test_turns import events


def my_id(client: TestClient) -> int:
    return client.get("/api/auth/me").json()["id"]


def messages(client: TestClient, kind: str, actor: str | int) -> list[str]:
    response = client.get(f"/api/logs/{kind}", params={"actor": str(actor)})
    assert response.status_code == 200, response.text
    return [e["message"] for e in response.json()]


def test_account_and_admin_actions_are_logged(client: TestClient, email: FakeEmailSender) -> None:
    alice = make_member(client, email)
    as_admin(client)
    client.post("/api/admin/roles", json={"name": "Ops"})
    root = my_id(client)

    assert messages(client, "action", alice) == [
        "Logged out",
        "Verified email alice@example.com",
        "Registered with an invite code",
    ]
    admin_lines = messages(client, "action", root)
    assert admin_lines[0] == "Created role 'Ops'"
    assert admin_lines[1].startswith("Logged in from ")
    assert any(line.startswith("Created invite #") for line in admin_lines)
    # Nothing the server did on its own yet.
    assert messages(client, "action", "server") == []


def test_logs_page_needs_a_logs_permission_per_kind(client: TestClient, email: FakeEmailSender) -> None:
    make_member(client, email)
    login(client, "alice")
    assert client.get("/api/logs").status_code == 403
    assert client.get("/api/logs/action").status_code == 403

    client.post("/api/auth/logout", json={})
    as_admin(client)
    everything = client.get("/api/logs").json()
    assert everything["kinds"] == ["action", "error", "chat_trace"]
    assert [a["username"] for a in everything["accounts"]] == ["alice", "root"]
    member_role = role_by_name(client, "Member")["id"]
    assert client.put(f"/api/admin/roles/{member_role}/permissions/logs.view").status_code == 200
    client.post("/api/auth/logout", json={})

    login(client, "alice")
    assert client.get("/api/logs").json()["kinds"] == ["action"]
    assert client.get("/api/logs/action", params={"actor": "server"}).status_code == 200
    assert client.get("/api/logs/error").status_code == 403
    assert client.get("/api/logs/chat_trace").status_code == 403
    assert client.get("/api/logs/action", params={"actor": "everyone"}).status_code == 422
    assert client.get("/api/logs/secrets").status_code == 422


def test_chat_turns_are_traced_and_agent_failures_logged(client: TestClient, agent: FakeAgent) -> None:
    as_admin(client)
    root = my_id(client)
    chat_id = str(uuid.uuid4())
    body = {"question": "What is up?", "agent_id": AGENTS[0]["id"], "enabled_extensions": ["notes"]}
    assert client.post(f"/api/chats/{chat_id}/turns", json=body).status_code == 202
    events(client, chat_id)

    traces = client.get("/api/logs/chat_trace", params={"actor": root}).json()
    assert len(traces) == 1
    assert traces[0]["message"].startswith(f"What is up? → {AGENTS[0]['id']}/claude-test, ")
    assert '"enabled_extensions": [\n    "notes"\n  ]' in traces[0]["details"]
    assert '"response": "Hello!"' in traces[0]["details"]

    agent.fail = "provider rate limited"
    other = str(uuid.uuid4())
    client.post(f"/api/chats/{other}/turns", json={**body, "enabled_extensions": []})
    events(client, other)
    assert messages(client, "error", root) == [f"{AGENTS[0]['id']}: provider rate limited"]


def test_unexpected_errors_are_logged_under_the_account(client: TestClient, monkeypatch) -> None:
    as_admin(client)
    root = my_id(client)

    async def broken(self):
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(ChatService, "list", broken)
    with pytest.raises(RuntimeError):  # TestClient re-raises what the app didn't handle
        client.get("/api/chats")

    entries = client.get("/api/logs/error", params={"actor": root}).json()
    assert entries[0]["message"] == "RuntimeError: disk on fire"
    assert entries[0]["source"] == "http GET /api/chats"
    assert "Traceback" in entries[0]["details"]
