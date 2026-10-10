"""Account.uid: created with the account, never changes, never leaves the server."""

from __future__ import annotations

import re
import sqlite3
from contextlib import closing

from fastapi.testclient import TestClient

from tests.conftest import FakeEmailSender
from tests.test_admin import make_member
from tests.test_registration import as_admin


def uids(client: TestClient) -> dict[str, str]:
    path = client.app.state.settings.database_path
    with closing(sqlite3.connect(path)) as conn:
        return dict(conn.execute("SELECT username, uid FROM accounts"))


def test_every_account_gets_its_own_32_hex_uid(client: TestClient, email: FakeEmailSender) -> None:
    make_member(client, email, "alice")
    make_member(client, email, "bob")

    found = uids(client)

    assert set(found) == {"root", "alice", "bob"}
    assert all(re.fullmatch(r"[0-9a-f]{32}", uid) for uid in found.values())
    assert len(set(found.values())) == 3


def test_the_uid_survives_a_rename_and_a_role_change(client: TestClient, email: FakeEmailSender) -> None:
    alice = make_member(client, email, "alice")
    as_admin(client)
    before = uids(client)["alice"]

    assert client.patch(f"/api/admin/accounts/{alice}", json={"username": "alicia"}).status_code == 200
    viewer = client.post("/api/admin/roles", json={"name": "Viewer"}).json()
    assert client.put(f"/api/admin/accounts/{alice}/roles/{viewer['id']}").status_code == 200

    assert uids(client)["alicia"] == before


def test_the_uid_is_never_returned_by_the_api(client: TestClient, email: FakeEmailSender) -> None:
    make_member(client, email, "alice")
    as_admin(client)
    secret = uids(client)["alice"]

    for path in ("/api/admin/accounts", "/api/auth/me"):
        body = client.get(path).text
        assert secret not in body
        assert '"uid"' not in body
