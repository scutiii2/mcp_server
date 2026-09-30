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


# --- search -------------------------------------------------------------------


def search(client: TestClient, q: str):
    return client.get("/api/chats/search", params={"q": q})


def test_search_needs_login_and_a_query(client: TestClient) -> None:
    assert search(client, "hello").status_code == 401
    as_admin(client)

    assert client.get("/api/chats/search").status_code == 422
    assert search(client, "a").status_code == 422
    assert search(client, "x" * 101).status_code == 422
    assert search(client, "   ").json() == []


def test_search_finds_titles_and_messages_case_insensitively(client: TestClient) -> None:
    as_admin(client)
    by_title, by_message, neither = new_id(), new_id(), new_id()
    put(client, by_title, title="Docker Compose notes", messages=[{"role": "user", "content": "unrelated"}])
    put(
        client,
        by_message,
        title="Deploy",
        messages=[
            {"role": "user", "content": "how do I restart the service?"},
            {"role": "assistant", "content": "Use systemctl to RESTART it, then restart the timer."},
        ],
    )
    put(client, neither, title="Other", messages=[{"role": "user", "content": "nothing here"}])

    hits = {h["id"]: h for h in search(client, "restart").json()}
    title_hits = {h["id"]: h for h in search(client, "docker").json()}

    assert set(hits) == {by_message}
    hit = hits[by_message]
    assert (hit["message_index"], hit["message_matches"], hit["title_match"]) == (0, 2, None)
    text = hit["snippet"]["text"]
    assert text[hit["snippet"]["start"] : hit["snippet"]["start"] + hit["snippet"]["length"]] == "restart"
    assert set(title_hits) == {by_title}
    assert title_hits[by_title]["title_match"] == {"start": 0, "length": 6}
    assert title_hits[by_title]["snippet"] is None


def test_search_snippet_is_one_line_with_ellipses(client: TestClient) -> None:
    as_admin(client)
    long = ("word " * 30) + "NEEDLE\nnext line " + ("tail " * 40)
    put(client, new_id(), messages=[{"role": "user", "content": long}])

    snippet = search(client, "needle").json()[0]["snippet"]

    assert snippet["text"].startswith("…") and snippet["text"].endswith("…")
    assert "\n" not in snippet["text"]
    assert snippet["text"][snippet["start"] : snippet["start"] + snippet["length"]] == "NEEDLE"


def test_search_is_literal_and_handles_non_ascii_and_quotes(client: TestClient) -> None:
    as_admin(client)
    percent, ascii_only, german, quoted = new_id(), new_id(), new_id(), new_id()
    put(client, percent, messages=[{"role": "user", "content": "discount 50% today"}])
    put(client, ascii_only, messages=[{"role": "user", "content": "about 500 things a_b"}])
    put(client, german, messages=[{"role": "user", "content": "Das war ein großer ÄRGER"}])
    put(client, quoted, messages=[{"role": "user", "content": 'she said "hi there"\nand left'}])

    assert [h["id"] for h in search(client, "50%").json()] == [percent]
    assert [h["id"] for h in search(client, "a_b").json()] == [ascii_only]
    assert [h["id"] for h in search(client, "ärger").json()] == [german]
    assert [h["id"] for h in search(client, '"hi there"').json()] == [quoted]
    assert [h["id"] for h in search(client, "hi there").json()] == [quoted]


def test_search_skips_attachment_bodies_and_matches_the_typed_text(client: TestClient) -> None:
    as_admin(client)
    chat_id = new_id()
    content = (
        "please summarize\n\n"
        '[[ATTACHMENT filename="report.txt" chars="9" truncated="false"]]\nsecretword\n[[/ATTACHMENT]]'
    )
    put(client, chat_id, messages=[{"role": "user", "content": content}])

    assert search(client, "secretword").json() == []
    assert [h["id"] for h in search(client, "summarize").json()] == [chat_id]


def test_search_is_private_per_account(client_factory, email: FakeEmailSender) -> None:
    alice = client_factory()
    make_member(alice, email)
    make_member(alice, email, "bob")
    login(alice, "alice")
    put(alice, new_id(), title="Alice's plan", messages=[{"role": "user", "content": "private plan"}])
    bob = client_factory()
    login(bob, "bob")

    assert len(search(alice, "plan").json()) == 1
    assert search(bob, "plan").json() == []


def test_search_is_newest_first_and_capped(client: TestClient) -> None:
    as_admin(client)
    first = new_id()
    put(client, first, title="match 0")
    ids = [first]
    for i in range(1, 52):
        ids.append(new_id())
        put(client, ids[-1], title=f"match {i}")

    hits = search(client, "match").json()

    assert len(hits) == 50
    assert hits[0]["id"] == ids[-1]


# --- usage fields on saved answers --------------------------------------------


def test_put_keeps_the_usage_fields_of_an_answer(client: TestClient) -> None:
    as_admin(client)
    chat_id = new_id()
    answer = {
        "role": "assistant",
        "content": "ok",
        "model": "m",
        "total_tokens": 10,
        "input_tokens": 7,
        "output_tokens": 3,
        "duration_s": 1.5,
    }

    assert put(client, chat_id, messages=[{"role": "user", "content": "q"}, answer]).status_code == 200

    assert client.get(f"/api/chats/{chat_id}").json()["messages"][1] == answer


def test_put_refuses_negative_usage_fields(client: TestClient) -> None:
    as_admin(client)
    bad = {"role": "assistant", "content": "x", "duration_s": -1}

    assert put(client, new_id(), messages=[bad]).status_code == 422
    assert put(client, new_id(), messages=[{**bad, "duration_s": 1, "input_tokens": -5}]).status_code == 422
