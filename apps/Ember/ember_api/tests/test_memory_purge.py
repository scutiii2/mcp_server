"""Deleting an account tells mcp_server to delete its memory notes (best effort)."""

from __future__ import annotations

import logging

import httpx
from fastapi.testclient import TestClient

from tests.conftest import ADMIN_USERNAME, FakeEmailSender, FakeUpstream
from tests.test_account_uid import uids
from tests.test_admin import make_member
from tests.test_registration import as_admin


def purges(upstream: FakeUpstream) -> list[httpx.Request]:
    return [r for r in upstream.requests if r.method == "DELETE" and r.url.path.startswith("/memory/owners/")]


def test_deleting_an_account_purges_its_notes_once(client: TestClient, email: FakeEmailSender, upstream: FakeUpstream, caplog) -> None:
    alice = make_member(client, email, "alice")
    as_admin(client)
    uid = uids(client)["alice"]
    upstream.requests.clear()
    caplog.set_level(logging.INFO)

    assert client.delete(f"/api/admin/accounts/{alice}").status_code == 204

    sent = purges(upstream)
    assert [r.url.path for r in sent] == [f"/memory/owners/{uid}"]
    assert "x-internal-token" not in sent[0].headers  # none configured in this test
    assert uid not in caplog.text
    assert "/memory/owners/[redacted]" in caplog.text


def test_the_internal_token_is_sent_when_configured(client_factory, email: FakeEmailSender, upstream: FakeUpstream) -> None:
    client = client_factory(internal_token="secret-token")
    alice = make_member(client, email, "alice")
    as_admin(client)
    upstream.requests.clear()

    assert client.delete(f"/api/admin/accounts/{alice}").status_code == 204

    assert purges(upstream)[0].headers["x-internal-token"] == "secret-token"


def test_a_failing_purge_never_blocks_the_deletion(client: TestClient, email: FakeEmailSender, upstream: FakeUpstream, caplog) -> None:
    accounts = {name: make_member(client, email, name) for name in ("alice", "bob", "charlie")}
    identities = uids(client)
    as_admin(client)
    root = client.get("/api/auth/me").json()["id"]
    caplog.set_level(logging.INFO)

    def broken(request):
        raise RuntimeError(f"transport failed for {request.url}")

    handlers = [
        lambda request: httpx.Response(500, json={"error": "boom"}),
        lambda request: httpx.Response(307, headers={"location": "http://third-party.invalid" + request.url.path}),
        broken,
    ]
    for (name, account_id), handler in zip(accounts.items(), handlers):
        upstream.handler = handler
        upstream.requests.clear()
        # A caller's client setting must not let the uid follow a redirect.
        if name == "bob":
            client.app.state.memory_purger._client.follow_redirects = True
        assert client.delete(f"/api/admin/accounts/{account_id}").status_code == 204
        assert name not in uids(client)
        sent = purges(upstream)
        assert len(sent) == 1 and sent[0].url.host == "mcp-server.internal"
        errors = client.get("/api/logs/error", params={"actor": root}).json()
        assert errors[0]["source"] == "admin.memory_purge"
        assert f"deleted account '{name}'" in errors[0]["message"]
        assert identities[name] not in str(errors)
        assert identities[name] not in caplog.text


def test_an_unreachable_mcp_server_never_blocks_the_deletion(client: TestClient, email: FakeEmailSender, upstream: FakeUpstream, caplog) -> None:
    alice = make_member(client, email, "alice")
    as_admin(client)
    uid = uids(client)["alice"]
    root = client.get("/api/auth/me").json()["id"]

    def unreachable(request):
        raise httpx.ConnectError(f"connection refused for {request.url}", request=request)

    upstream.handler = unreachable

    assert client.delete(f"/api/admin/accounts/{alice}").status_code == 204
    assert "alice" not in uids(client)
    errors = client.get("/api/logs/error", params={"actor": root}).json()
    assert errors[0]["source"] == "admin.memory_purge"
    assert uid not in str(errors)
    assert uid not in caplog.text


def test_a_refused_deletion_does_not_purge(client: TestClient, upstream: FakeUpstream) -> None:
    as_admin(client)
    root_id = next(a["id"] for a in client.get("/api/admin/accounts").json() if a["username"] == ADMIN_USERNAME)
    upstream.requests.clear()

    assert client.delete(f"/api/admin/accounts/{root_id}").status_code == 409  # protected and your own account
    assert purges(upstream) == []
