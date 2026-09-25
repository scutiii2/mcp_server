from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from src.services import chat_service
from tests.conftest import FakeEmailSender
from tests.test_admin import login, make_member
from tests.test_registration import as_admin


def new_id() -> str:
    return str(uuid.uuid4())


def put(client: TestClient, chat_id: str, title: str = "Hello", messages=None, agent_id: str | None = "claude-agent"):
    body = {
        "title": title,
        "agent_id": agent_id,
        "messages": messages if messages is not None else [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello!"},
        ],
    }
    return client.put(f"/api/chats/{chat_id}", json=body)


# --- access -------------------------------------------------------------------


def test_chats_need_login_and_chat_use(client: TestClient, email: FakeEmailSender) -> None:
    assert client.get("/api/chats").status_code == 401

    make_member(client, email, verify=False)
    login(client, "alice")
    assert client.get("/api/chats").status_code == 403  # unverified: no permissions


def test_chats_are_private_per_account(client_factory, email: FakeEmailSender) -> None:
    alice = client_factory()
    make_member(alice, email)
    make_member(alice, email, "bob")
    login(alice, "alice")
    chat_id = new_id()
    assert put(alice, chat_id).status_code == 200

    bob = client_factory()
    login(bob, "bob")

    assert bob.get("/api/chats").json() == []
    assert bob.get(f"/api/chats/{chat_id}").status_code == 404
    assert bob.patch(f"/api/chats/{chat_id}", json={"title": "mine"}).status_code == 404
    assert bob.delete(f"/api/chats/{chat_id}").status_code == 404
    # Bob using the same id makes his own chat; Alice's is untouched.
    assert put(bob, chat_id, title="Bob's").status_code == 200
    assert alice.get(f"/api/chats/{chat_id}").json()["title"] == "Hello"


# --- CRUD ---------------------------------------------------------------------


def test_put_creates_then_replaces(client: TestClient) -> None:
    as_admin(client)
    chat_id = new_id()

    created = put(client, chat_id)
    assert created.status_code == 200
    assert created.json()["message_count"] == 2

    put(client, chat_id, title="Renamed", messages=[{"role": "user", "content": "only"}], agent_id=None)
    chat = client.get(f"/api/chats/{chat_id}").json()

    assert (chat["title"], chat["agent_id"], chat["message_count"]) == ("Renamed", None, 1)
    assert chat["messages"] == [{"role": "user", "content": "only"}]
    assert chat["created_at"] == created.json()["created_at"]


def test_list_is_newest_first_without_messages(client: TestClient) -> None:
    as_admin(client)
    first, second = new_id(), new_id()
    put(client, first, title="First")
    put(client, second, title="Second")
    put(client, first, title="First again")  # most recently updated

    listing = client.get("/api/chats").json()

    assert [c["title"] for c in listing] == ["First again", "Second"]
    assert "messages" not in listing[0]


def test_rename_trims_and_rejects_blank(client: TestClient) -> None:
    as_admin(client)
    chat_id = new_id()
    put(client, chat_id)

    assert client.patch(f"/api/chats/{chat_id}", json={"title": "  New   name "}).json()["title"] == "New name"
    assert client.patch(f"/api/chats/{chat_id}", json={"title": "   "}).status_code == 422
    assert client.patch(f"/api/chats/{chat_id}", json={"title": "x" * 121}).status_code == 422


def test_delete_one_and_all(client: TestClient) -> None:
    as_admin(client)
    ids = [new_id() for _ in range(3)]
    for chat_id in ids:
        put(client, chat_id)

    assert client.delete(f"/api/chats/{ids[0]}").status_code == 204
    assert client.get(f"/api/chats/{ids[0]}").status_code == 404
    assert client.delete("/api/chats").status_code == 204
    assert client.get("/api/chats").json() == []


def test_validation(client: TestClient) -> None:
    as_admin(client)

    assert put(client, "bad id!").status_code == 422
    assert put(client, "short").status_code == 422
    assert put(client, new_id(), messages=[{"role": "system", "content": "x"}]).status_code == 422
    assert put(client, new_id(), title="").status_code == 422


# --- limits -------------------------------------------------------------------


def test_chat_over_size_limit_is_refused(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(chat_service, "MAX_CHAT_BYTES", 1000)
    as_admin(client)

    response = put(client, new_id(), messages=[{"role": "user", "content": "x" * 2000}])

    assert response.status_code == 413


def test_chat_count_limit(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(chat_service, "MAX_CHATS_PER_ACCOUNT", 2)
    as_admin(client)
    first = new_id()
    put(client, first)
    put(client, new_id())

    assert put(client, new_id()).status_code == 413
    assert put(client, first, title="Updating is fine").status_code == 200


def test_oversized_request_body_is_refused_before_parsing(client: TestClient) -> None:
    as_admin(client)
    too_big = 32 * 1024 * 1024 + 1

    response = client.put(
        f"/api/chats/{new_id()}",
        content=b"{}",
        headers={"Content-Type": "application/json", "Content-Length": str(too_big)},
    )

    assert response.status_code == 413


# --- import -------------------------------------------------------------------


def import_item(chat_id: str, title: str = "Old chat", updated: int = 1_700_000_000_000) -> dict:
    return {
        "id": chat_id,
        "title": title,
        "agent_id": "claude-agent",
        "messages": [{"role": "user", "content": "from the browser"}],
        "created_at": updated - 60_000,
        "updated_at": updated,
    }


def test_import_keeps_timestamps_and_skips_existing(client: TestClient) -> None:
    as_admin(client)
    existing = new_id()
    put(client, existing, title="On the server")
    fresh = new_id()

    response = client.post(
        "/api/chats/import",
        json={"chats": [import_item(fresh), import_item(existing, title="Local copy"), import_item(fresh)]},
    )

    assert response.json() == {"imported": 1, "skipped": 2}
    imported = client.get(f"/api/chats/{fresh}").json()
    assert imported["updated_at"].startswith("2023-11-14T22:13:20")
    assert client.get(f"/api/chats/{existing}").json()["title"] == "On the server"


def test_import_respects_count_limit(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(chat_service, "MAX_CHATS_PER_ACCOUNT", 1)
    as_admin(client)

    response = client.post("/api/chats/import", json={"chats": [import_item(new_id()), import_item(new_id())]})

    assert response.status_code == 413
    assert client.get("/api/chats").json() == []


# --- account deletion ---------------------------------------------------------


def test_chats_go_with_their_account(client: TestClient, email: FakeEmailSender) -> None:
    alice_id = make_member(client, email)
    login(client, "alice")
    put(client, new_id())
    client.post("/api/auth/logout", json={})

    as_admin(client)
    client.delete(f"/api/admin/accounts/{alice_id}")

    async def remaining() -> int:
        from sqlalchemy import func, select

        from src.models import Chat

        async with client.app.state.database.sessions() as session:
            return await session.scalar(select(func.count()).select_from(Chat))

    assert client.portal.call(remaining) == 0
