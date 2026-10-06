from __future__ import annotations

import hashlib
import re
import uuid
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update

from src.db import utcnow
from src.models import LogEntry, SharedChat
from src.services import share_service
from src.services.public_rate_limiter import PublicReadLimiter
from src.services.share_service import purge_expired_shares
from tests.conftest import FakeEmailSender
from tests.test_admin import login, make_member
from tests.test_registration import as_admin

FILE = '[[ATTACHMENT filename="report.txt" chars="9" truncated="false"]]\nsecretword\n[[/ATTACHMENT]]'

CONVERSATION = [
    {"role": "assistant", "kind": "summary", "content": "SUMMARY-SECRET"},
    {"role": "user", "content": f"please summarize\n\n{FILE}"},
    {
        "role": "assistant",
        "content": "Here you go.\n[[DOWNLOAD filename=\"out.csv\" bytes=\"1\" url=\"/internal/f\"]]",
        "model": "claude-test",
        "total_tokens": 100,
        "steps": [{"tool": "tool_x", "label": "X", "arguments": {"key": "TOOL-ARG"}, "ok": True, "result": "TOOL-RESULT"}],
    },
    {"role": "user", "kind": "command", "content": "/apps start"},
    {"role": "assistant", "kind": "command", "content": "COMMAND-RESULT"},
    {"role": "user", "content": "and again?"},
    {"role": "assistant", "content": "error: provider blew up at 10.0.0.5"},
]


def new_id() -> str:
    return str(uuid.uuid4())


def make_chat(client: TestClient, messages=None, title: str = "Quarterly report") -> str:
    chat_id = new_id()
    response = client.put(
        f"/api/chats/{chat_id}",
        json={"title": title, "agent_id": "claude-agent", "messages": messages if messages is not None else CONVERSATION},
    )
    assert response.status_code == 200
    return chat_id


def share(client: TestClient, chat_id: str, **body):
    return client.post(f"/api/chats/{chat_id}/shares", json=body)


def read(client: TestClient, token: str):
    return client.get(f"/api/shared/{token}")


def db(client: TestClient, work):
    """Runs `work(session)` against ember_api's own database."""

    async def run():
        async with client.app.state.database.sessions() as session:
            return await work(session)

    return client.portal.call(run)


def expire(client: TestClient, share_id: int) -> None:
    async def work(session):
        await session.execute(update(SharedChat).where(SharedChat.id == share_id).values(expires_at=utcnow() - timedelta(minutes=1)))
        await session.commit()

    db(client, work)


# --- access -------------------------------------------------------------------


def test_managing_links_needs_login_and_chat_use(client: TestClient, email: FakeEmailSender) -> None:
    assert share(client, new_id()).status_code == 401
    assert client.get("/api/shares").status_code == 401
    assert client.delete("/api/shares/1").status_code == 401

    make_member(client, email, verify=False)
    login(client, "alice")
    assert share(client, new_id()).status_code == 403  # unverified: no permissions
    assert client.get("/api/shares").status_code == 403
    assert client.delete("/api/shares/1").status_code == 403


def test_reading_a_link_needs_no_login(client_factory) -> None:
    owner = client_factory()
    as_admin(owner)
    token = share(owner, make_chat(owner)).json()["token"]

    stranger = client_factory()  # a browser that never logged in

    assert read(stranger, token).status_code == 200
    assert read(owner, token).status_code == 200  # and logging in changes nothing


# --- creating -----------------------------------------------------------------


def test_creating_a_link_returns_the_token_once(client: TestClient) -> None:
    as_admin(client)
    chat_id = make_chat(client)

    response = share(client, chat_id)

    assert response.status_code == 201
    body = response.json()
    assert re.fullmatch(r"[A-Za-z0-9_-]{43}", body["token"])
    assert (body["chat_id"], body["title"], body["message_count"]) == (chat_id, "Quarterly report", 3)
    created = _parse(body["created_at"])
    assert _parse(body["expires_at"]) - created == timedelta(days=7)  # the default


@pytest.mark.parametrize("days", [1, 7, 30])
def test_expiry_choices(client: TestClient, days: int) -> None:
    as_admin(client)

    body = share(client, make_chat(client), expires_in_days=days).json()

    assert _parse(body["expires_at"]) - _parse(body["created_at"]) == timedelta(days=days)


def test_a_link_can_be_made_without_expiry(client: TestClient) -> None:
    as_admin(client)

    body = share(client, make_chat(client), expires_in_days=None).json()

    assert body["expires_at"] is None
    assert read(client, body["token"]).json()["expires_at"] is None


@pytest.mark.parametrize("days", [0, 2, 365, -1, "7", 7.5, "forever"])
def test_other_expiries_are_refused(client: TestClient, days) -> None:
    as_admin(client)
    chat_id = make_chat(client)

    assert share(client, chat_id, expires_in_days=days).status_code == 422
    assert client.get("/api/shares").json() == []


def test_every_link_gets_its_own_token(client: TestClient) -> None:
    as_admin(client)
    chat_id = make_chat(client)

    tokens = {share(client, chat_id).json()["token"] for _ in range(5)}

    assert len(tokens) == 5


def test_unknown_and_foreign_chats_are_404(client_factory, email: FakeEmailSender) -> None:
    alice = client_factory()
    make_member(alice, email)
    make_member(alice, email, "bob")
    login(alice, "alice")
    chat_id = make_chat(alice)
    bob = client_factory()
    login(bob, "bob")

    assert share(alice, new_id()).status_code == 404
    assert share(bob, chat_id).status_code == 404
    assert bob.get("/api/shares").json() == []
    assert share(alice, "x").status_code == 422  # not even an id


def test_a_chat_with_nothing_shareable_is_refused(client: TestClient) -> None:
    as_admin(client)
    only_private_parts = [
        {"role": "assistant", "kind": "summary", "content": "S"},
        {"role": "assistant", "kind": "log_attachment", "content": "raw"},
        {"role": "user", "kind": "command", "content": "/x y"},
        {"role": "assistant", "kind": "command", "content": "result"},
        {"role": "assistant", "content": "error: down"},
    ]

    assert share(client, make_chat(client, only_private_parts)).status_code == 422
    assert share(client, make_chat(client, [])).status_code == 422
    assert client.get("/api/shares").json() == []


# --- what is stored ---------------------------------------------------------------


def test_the_token_is_not_stored_only_its_hash(client: TestClient) -> None:
    as_admin(client)
    body = share(client, make_chat(client)).json()

    async def rows(session):
        found = list(await session.scalars(select(SharedChat)))
        return [(r.token_hash, r.title, r.messages, r.chat_id) for r in found]

    (stored,) = db(client, rows)

    assert stored[0] == hashlib.sha256(body["token"].encode()).hexdigest()
    assert all(body["token"] not in str(column) for column in stored)


def test_lists_never_contain_a_token(client: TestClient) -> None:
    as_admin(client)
    chat_id = make_chat(client)
    share(client, chat_id)

    listed = client.get("/api/shares").json()

    assert len(listed) == 1
    assert "token" not in listed[0]
    assert set(listed[0]) == {"id", "chat_id", "title", "message_count", "created_at", "expires_at"}


# --- reading ------------------------------------------------------------------------


def test_a_link_shows_only_the_sanitized_conversation(client_factory) -> None:
    owner = client_factory()
    as_admin(owner)
    token = share(owner, make_chat(owner)).json()["token"]

    response = read(client_factory(), token)

    assert response.status_code == 200
    shared = response.json()
    assert shared["title"] == "Quarterly report"
    assert shared["messages"] == [
        {"role": "user", "content": "please summarize\n\n📎 report.txt"},
        {"role": "assistant", "content": "Here you go."},
        {"role": "user", "content": "and again?"},
    ]
    everything = response.text
    for secret in ("SUMMARY-SECRET", "secretword", "TOOL-ARG", "TOOL-RESULT", "COMMAND-RESULT", "10.0.0.5", "/internal/f", "claude-test"):
        assert secret not in everything
    assert set(shared) == {"title", "messages", "created_at", "expires_at"}


def test_a_link_is_a_frozen_copy(client: TestClient, client_factory) -> None:
    as_admin(client)
    chat_id = make_chat(client)
    token = share(client, chat_id).json()["token"]
    anon = client_factory()
    before = read(anon, token).json()

    client.put(
        f"/api/chats/{chat_id}",
        json={"title": "Renamed", "agent_id": None, "messages": [{"role": "user", "content": "something else entirely"}]},
    )

    assert read(anon, token).json() == before


def test_the_public_response_is_never_cached_or_indexed(client: TestClient, client_factory) -> None:
    as_admin(client)
    token = share(client, make_chat(client)).json()["token"]

    response = read(client_factory(), token)

    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-robots-tag"] == "noindex, nofollow"


def test_only_reading_is_possible_without_login(client_factory) -> None:
    anon = client_factory()

    for method in ("post", "put", "patch", "delete"):
        assert getattr(anon, method)("/api/shared/" + "a" * 43).status_code in (401, 403, 405, 415, 422)


def test_unknown_malformed_expired_and_revoked_links_all_look_the_same(client: TestClient, client_factory) -> None:
    as_admin(client)
    chat_id = make_chat(client)
    expired = share(client, chat_id).json()
    revoked = share(client, chat_id).json()
    expire(client, expired["id"])
    assert client.delete(f"/api/shares/{revoked['id']}").status_code == 204
    anon = client_factory()

    attempts = [
        "A" * 43,  # well-formed, never issued
        "short",
        "x" * 200,
        "has spaces and !!",
        expired["token"],
        revoked["token"],
    ]
    answers = [read(anon, t) for t in attempts]

    assert {r.status_code for r in answers} == {404}
    assert len({r.text for r in answers}) == 1  # nothing tells the cases apart


def test_a_link_with_no_expiry_or_a_future_one_keeps_working(client: TestClient, client_factory) -> None:
    as_admin(client)
    chat_id = make_chat(client)
    forever = share(client, chat_id, expires_in_days=None).json()["token"]
    week = share(client, chat_id, expires_in_days=7).json()["token"]
    anon = client_factory()

    assert read(anon, forever).status_code == 200
    assert read(anon, week).status_code == 200


def test_reading_is_rate_limited_per_address(client: TestClient, client_factory) -> None:
    as_admin(client)
    token = share(client, make_chat(client)).json()["token"]
    anon = client_factory()  # its own app instance over the same database
    anon.app.state.share_limiter = PublicReadLimiter(max_requests=3, window_seconds=60)

    codes = [read(anon, token).status_code for _ in range(3)]
    refused = read(anon, "A" * 43)  # guesses count too

    assert codes == [200, 200, 200]
    assert refused.status_code == 429
    assert int(refused.headers["retry-after"]) >= 1
    assert read(anon, token).status_code == 429


# --- listing and revoking ---------------------------------------------------------------


def test_listing_is_newest_first_and_can_be_narrowed_to_one_chat(client: TestClient) -> None:
    as_admin(client)
    first, second = make_chat(client, title="First"), make_chat(client, title="Second")
    a = share(client, first).json()
    b = share(client, second).json()
    c = share(client, first).json()

    assert [s["id"] for s in client.get("/api/shares").json()] == [c["id"], b["id"], a["id"]]
    assert [s["id"] for s in client.get("/api/shares", params={"chat_id": first}).json()] == [c["id"], a["id"]]
    assert client.get("/api/shares", params={"chat_id": "no way"}).status_code == 422


def test_expired_links_drop_out_of_the_list(client: TestClient) -> None:
    as_admin(client)
    chat_id = make_chat(client)
    old = share(client, chat_id).json()
    kept = share(client, chat_id).json()

    expire(client, old["id"])

    assert [s["id"] for s in client.get("/api/shares").json()] == [kept["id"]]


def test_links_are_private_per_account(client_factory, email: FakeEmailSender) -> None:
    alice = client_factory()
    make_member(alice, email)
    make_member(alice, email, "bob")
    login(alice, "alice")
    mine = share(alice, make_chat(alice)).json()
    bob = client_factory()
    login(bob, "bob")

    assert bob.get("/api/shares").json() == []
    assert bob.delete(f"/api/shares/{mine['id']}").status_code == 404
    assert read(bob, mine["token"]).status_code == 200  # a link is readable by anyone who has it
    assert len(alice.get("/api/shares").json()) == 1  # ... but only its owner can revoke it


def test_revoking_kills_the_link_at_once(client: TestClient, client_factory) -> None:
    as_admin(client)
    made = share(client, make_chat(client)).json()
    anon = client_factory()
    assert read(anon, made["token"]).status_code == 200

    assert client.delete(f"/api/shares/{made['id']}").status_code == 204

    assert read(anon, made["token"]).status_code == 404
    assert client.get("/api/shares").json() == []
    assert client.delete(f"/api/shares/{made['id']}").status_code == 404


def test_share_ids_are_validated(client: TestClient) -> None:
    as_admin(client)

    assert client.delete("/api/shares/0").status_code == 422
    assert client.delete("/api/shares/abc").status_code == 422
    assert client.delete("/api/shares/99999").status_code == 404


def test_shares_are_posted_as_json_only(client: TestClient) -> None:
    as_admin(client)
    chat_id = make_chat(client)

    response = client.post(f"/api/chats/{chat_id}/shares", content="expires_in_days=7", headers={"Content-Type": "text/plain"})

    assert response.status_code == 415


# --- limits ----------------------------------------------------------------------------


def test_active_link_limit(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(share_service, "MAX_ACTIVE_SHARES_PER_ACCOUNT", 2)
    as_admin(client)
    chat_id = make_chat(client)
    first = share(client, chat_id).json()
    second = share(client, chat_id).json()

    refused = share(client, chat_id)

    assert refused.status_code == 409
    assert "At most 2" in refused.json()["detail"]
    # Revoking frees a slot, and so does a link expiring.
    client.delete(f"/api/shares/{first['id']}")
    assert share(client, chat_id).status_code == 201
    expire(client, second["id"])
    assert share(client, chat_id).status_code == 201


# --- audit -----------------------------------------------------------------------------


def test_creating_and_revoking_are_logged_without_the_token(client: TestClient) -> None:
    as_admin(client)
    made = share(client, make_chat(client), expires_in_days=30).json()
    client.delete(f"/api/shares/{made['id']}")

    async def entries(session):
        rows = list(await session.scalars(select(LogEntry).where(LogEntry.source.in_(["share.create", "share.revoke"]))))
        return sorted((r.source, r.message) for r in rows)

    logged = db(client, entries)

    assert [source for source, _ in logged] == ["share.create", "share.revoke"]
    assert "Quarterly report" in logged[0][1] and "30 days" in logged[0][1]
    assert all(made["token"] not in message for _, message in logged)


# --- what removes links -------------------------------------------------------------------


def _share_count(client: TestClient) -> int:
    async def work(session):
        return len(list(await session.scalars(select(SharedChat))))

    return db(client, work)


def test_deleting_a_chat_revokes_its_links_and_only_its_links(client: TestClient, client_factory) -> None:
    as_admin(client)
    doomed, kept = make_chat(client, title="Doomed"), make_chat(client, title="Kept")
    gone = share(client, doomed).json()["token"]
    stays = share(client, kept).json()["token"]
    anon = client_factory()

    assert client.delete(f"/api/chats/{doomed}").status_code == 204

    assert read(anon, gone).status_code == 404
    assert read(anon, stays).status_code == 200
    assert _share_count(client) == 1


def test_deleting_all_chats_revokes_every_link_of_the_account(client: TestClient, client_factory) -> None:
    as_admin(client)
    tokens = [share(client, make_chat(client)).json()["token"] for _ in range(3)]

    assert client.delete("/api/chats").status_code == 204

    assert all(read(client_factory(), t).status_code == 404 for t in tokens)
    assert _share_count(client) == 0


def test_deleting_all_chats_leaves_other_accounts_links_alone(client_factory, email: FakeEmailSender) -> None:
    alice = client_factory()
    make_member(alice, email)
    make_member(alice, email, "bob")
    login(alice, "alice")
    bob = client_factory()
    login(bob, "bob")
    alice_token = share(alice, make_chat(alice)).json()["token"]
    share(bob, make_chat(bob))

    bob.delete("/api/chats")

    assert read(client_factory(), alice_token).status_code == 200


def test_links_go_with_their_account(client: TestClient, email: FakeEmailSender) -> None:
    alice_id = make_member(client, email)
    login(client, "alice")
    token = share(client, make_chat(client)).json()["token"]
    client.post("/api/auth/logout", json={})

    as_admin(client)
    client.delete(f"/api/admin/accounts/{alice_id}")

    assert _share_count(client) == 0
    assert read(client, token).status_code == 404


def test_startup_purges_expired_links(client: TestClient) -> None:
    as_admin(client)
    chat_id = make_chat(client)
    old = share(client, chat_id).json()
    keep = share(client, chat_id).json()
    forever = share(client, chat_id, expires_in_days=None).json()
    expire(client, old["id"])

    async def purge(session):
        await purge_expired_shares(session)

    db(client, purge)

    async def ids(session):
        return {r.id for r in await session.scalars(select(SharedChat))}

    assert db(client, ids) == {keep["id"], forever["id"]}


def _parse(text: str):
    from datetime import datetime

    return datetime.fromisoformat(text)
