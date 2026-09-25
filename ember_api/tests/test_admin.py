from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.conftest import ADMIN_USERNAME, FakeEmailSender
from tests.test_registration import as_admin, new_invite, register

MEMBER_PASSWORD = "long enough pw"


def make_member(client: TestClient, email: FakeEmailSender, username: str = "alice", verify: bool = True) -> int:
    """Registers `username` (verified unless told not to), logs out, returns its id."""
    response = register(client, new_invite(client), username=username, email=f"{username}@example.com")
    assert response.status_code == 201, response.text
    if verify:
        assert client.post("/api/auth/verify-email", json={"code": email.last_code("verify")}).status_code == 200
    client.post("/api/auth/logout", json={})
    return response.json()["account"]["id"]


def login(client: TestClient, username: str, password: str = MEMBER_PASSWORD) -> None:
    assert client.post("/api/auth/login", json={"username": username, "password": password}).status_code == 200


def account_by_name(client: TestClient, username: str) -> dict:
    return next(a for a in client.get("/api/admin/accounts").json() if a["username"] == username)


def role_by_name(client: TestClient, name: str) -> dict:
    return next(r for r in client.get("/api/admin/roles").json() if r["name"] == name)


# --- access -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/api/admin/accounts"),
        ("get", "/api/admin/roles"),
        ("get", "/api/admin/permissions"),
        ("delete", "/api/admin/accounts/1"),
        ("delete", "/api/admin/roles/1"),
        ("delete", "/api/admin/invites/1"),
    ],
)
def test_admin_routes_need_login_and_admin_manage(
    client: TestClient, email: FakeEmailSender, method: str, path: str
) -> None:
    assert getattr(client, method)(path).status_code == 401

    make_member(client, email)
    login(client, "alice")
    assert getattr(client, method)(path).status_code == 403


# --- listing ------------------------------------------------------------------


def test_lists_accounts_roles_and_permissions(client: TestClient, email: FakeEmailSender) -> None:
    make_member(client, email)
    as_admin(client)

    accounts = client.get("/api/admin/accounts").json()
    assert [a["username"] for a in accounts] == ["alice", ADMIN_USERNAME]
    root = accounts[1]
    assert root["is_protected"] is True and [r["name"] for r in root["roles"]] == ["Administrator"]

    roles = {r["name"]: r for r in client.get("/api/admin/roles").json()}
    assert roles["Administrator"]["is_protected"] is True
    assert roles["Administrator"]["permissions"] == ["admin.manage", "chat.use", "tools.use"]
    assert roles["Member"]["account_count"] == 1

    names = [p["name"] for p in client.get("/api/admin/permissions").json()]
    assert names == ["admin.manage", "chat.use", "tools.use"]


# --- accounts -----------------------------------------------------------------


def test_edit_account_username_and_email(client: TestClient, email: FakeEmailSender) -> None:
    alice = make_member(client, email)
    as_admin(client)

    response = client.patch(f"/api/admin/accounts/{alice}", json={"username": "alicia", "email": "a@example.com"})

    assert response.status_code == 200
    assert (response.json()["username"], response.json()["email"]) == ("alicia", "a@example.com")
    client.post("/api/auth/logout", json={})
    login(client, "alicia")


def test_edit_account_rejects_taken_username_and_bad_values(client: TestClient, email: FakeEmailSender) -> None:
    alice = make_member(client, email)
    make_member(client, email, "bob")
    as_admin(client)

    assert client.patch(f"/api/admin/accounts/{alice}", json={"username": "BOB"}).status_code == 409
    assert client.patch(f"/api/admin/accounts/{alice}", json={"email": "bob@example.com"}).status_code == 409
    assert client.patch(f"/api/admin/accounts/{alice}", json={"username": "a b"}).status_code == 422
    assert client.patch(f"/api/admin/accounts/{alice}", json={"email": "nope"}).status_code == 422
    assert client.patch("/api/admin/accounts/999", json={"username": "ghost"}).status_code == 404


def test_protected_admin_cannot_be_edited_deleted_or_stripped(client: TestClient) -> None:
    as_admin(client)
    root = account_by_name(client, ADMIN_USERNAME)
    admin_role = role_by_name(client, "Administrator")

    assert client.patch(f"/api/admin/accounts/{root['id']}", json={"username": "rooty"}).status_code == 409
    assert client.delete(f"/api/admin/accounts/{root['id']}").status_code == 409
    assert client.delete(f"/api/admin/accounts/{root['id']}/roles/{admin_role['id']}").status_code == 409


def test_disable_ends_sessions_and_blocks_login(client_factory, email: FakeEmailSender) -> None:
    admin_client = as_admin(client_factory())
    alice = make_member(admin_client, email)
    as_admin(admin_client)
    alice_client = client_factory()
    login(alice_client, "alice")

    response = admin_client.patch(f"/api/admin/accounts/{alice}", json={"is_active": False})

    assert response.status_code == 200 and response.json()["is_active"] is False
    assert alice_client.get("/api/auth/me").status_code == 401
    assert alice_client.post(
        "/api/auth/login", json={"username": "alice", "password": MEMBER_PASSWORD}
    ).status_code == 401

    admin_client.patch(f"/api/admin/accounts/{alice}", json={"is_active": True})
    login(alice_client, "alice")


def test_admin_cannot_delete_or_disable_self(client: TestClient, email: FakeEmailSender) -> None:
    second = make_member(client, email, "carol")
    as_admin(client)
    admin_role = role_by_name(client, "Administrator")
    client.put(f"/api/admin/accounts/{second}/roles/{admin_role['id']}")
    client.post("/api/auth/logout", json={})
    login(client, "carol")

    assert client.delete(f"/api/admin/accounts/{second}").status_code == 409
    assert client.patch(f"/api/admin/accounts/{second}", json={"is_active": False}).status_code == 409


def test_delete_account(client: TestClient, email: FakeEmailSender) -> None:
    alice = make_member(client, email)
    as_admin(client)

    assert client.delete(f"/api/admin/accounts/{alice}").status_code == 204
    assert [a["username"] for a in client.get("/api/admin/accounts").json()] == [ADMIN_USERNAME]
    assert client.delete(f"/api/admin/accounts/{alice}").status_code == 404


def test_assign_and_remove_role_changes_permissions(client: TestClient, email: FakeEmailSender) -> None:
    alice = make_member(client, email)
    as_admin(client)
    viewer = client.post("/api/admin/roles", json={"name": "Viewer"}).json()
    member = role_by_name(client, "Member")

    assert client.put(f"/api/admin/accounts/{alice}/roles/{viewer['id']}").status_code == 200
    response = client.delete(f"/api/admin/accounts/{alice}/roles/{member['id']}")
    assert [r["name"] for r in response.json()["roles"]] == ["Viewer"]

    client.post("/api/auth/logout", json={})
    login(client, "alice")
    assert client.get("/api/auth/me").json()["permissions"] == []


def test_admin_cannot_remove_own_admin_role(client: TestClient, email: FakeEmailSender) -> None:
    carol = make_member(client, email, "carol")
    as_admin(client)
    admin_role = role_by_name(client, "Administrator")
    client.put(f"/api/admin/accounts/{carol}/roles/{admin_role['id']}")
    client.post("/api/auth/logout", json={})
    login(client, "carol")

    assert client.delete(f"/api/admin/accounts/{carol}/roles/{admin_role['id']}").status_code == 409


def test_send_verification(client: TestClient, email: FakeEmailSender) -> None:
    alice = make_member(client, email, verify=False)
    as_admin(client)

    assert client.post(f"/api/admin/accounts/{alice}/send-verification", json={}).status_code == 200
    assert email.sent[-1][:2] == ("verify", "alice@example.com")

    email.fail = True
    assert client.post(f"/api/admin/accounts/{alice}/send-verification", json={}).status_code == 503

    root = account_by_name(client, ADMIN_USERNAME)
    assert client.post(f"/api/admin/accounts/{root['id']}/send-verification", json={}).status_code == 409


# --- roles --------------------------------------------------------------------


def test_create_update_delete_role(client: TestClient) -> None:
    as_admin(client)

    created = client.post("/api/admin/roles", json={"name": " Support ", "description": "Helpdesk"})
    assert created.status_code == 201
    role = created.json()
    assert (role["name"], role["description"], role["permissions"]) == ("Support", "Helpdesk", [])

    assert client.post("/api/admin/roles", json={"name": "support"}).status_code == 409
    assert client.post("/api/admin/roles", json={"name": "   "}).status_code == 422

    updated = client.patch(f"/api/admin/roles/{role['id']}", json={"name": "Help", "description": ""})
    assert (updated.json()["name"], updated.json()["description"]) == ("Help", None)

    assert client.delete(f"/api/admin/roles/{role['id']}").status_code == 204
    assert client.delete(f"/api/admin/roles/{role['id']}").status_code == 404


def test_administrator_role_is_locked(client: TestClient) -> None:
    as_admin(client)
    admin_role = role_by_name(client, "Administrator")

    assert client.patch(f"/api/admin/roles/{admin_role['id']}", json={"name": "Boss"}).status_code == 409
    assert client.delete(f"/api/admin/roles/{admin_role['id']}").status_code == 409
    assert client.delete(f"/api/admin/roles/{admin_role['id']}/permissions/chat.use").status_code == 409
    # Description stays editable.
    assert client.patch(f"/api/admin/roles/{admin_role['id']}", json={"description": "All"}).status_code == 200


def test_grant_and_revoke_permission(client: TestClient, email: FakeEmailSender) -> None:
    make_member(client, email)
    as_admin(client)
    member = role_by_name(client, "Member")

    granted = client.put(f"/api/admin/roles/{member['id']}/permissions/admin.manage")
    assert granted.json()["permissions"] == ["admin.manage", "chat.use", "tools.use"]
    assert client.put(f"/api/admin/roles/{member['id']}/permissions/no.such").status_code == 404

    revoked = client.delete(f"/api/admin/roles/{member['id']}/permissions/tools.use")
    assert revoked.json()["permissions"] == ["admin.manage", "chat.use"]

    client.post("/api/auth/logout", json={})
    login(client, "alice")
    assert client.get("/api/auth/me").json()["permissions"] == ["admin.manage", "chat.use"]


def test_admin_cannot_revoke_or_delete_own_only_admin_access(client: TestClient, email: FakeEmailSender) -> None:
    carol = make_member(client, email, "carol")
    as_admin(client)
    ops = client.post("/api/admin/roles", json={"name": "Ops"}).json()
    client.put(f"/api/admin/roles/{ops['id']}/permissions/admin.manage")
    client.put(f"/api/admin/accounts/{carol}/roles/{ops['id']}")
    client.post("/api/auth/logout", json={})
    login(client, "carol")

    assert client.delete(f"/api/admin/roles/{ops['id']}/permissions/admin.manage").status_code == 409
    assert client.delete(f"/api/admin/roles/{ops['id']}").status_code == 409
    # Other permissions on the same role are fine.
    assert client.delete(f"/api/admin/roles/{ops['id']}/permissions/chat.use").status_code == 200


# --- invites ------------------------------------------------------------------


def test_revoke_invite(client: TestClient) -> None:
    code = new_invite(client)
    as_admin(client)
    invite_id = client.get("/api/admin/invites").json()[0]["id"]

    assert client.delete(f"/api/admin/invites/{invite_id}").status_code == 204
    assert client.get("/api/admin/invites").json() == []
    client.post("/api/auth/logout", json={})
    assert register(client, code).status_code == 400


def test_used_invite_cannot_be_revoked(client: TestClient, email: FakeEmailSender) -> None:
    as_admin(client)
    response = client.post("/api/admin/invites", json={})
    invite_id, code = response.json()["invite"]["id"], response.json()["code"]
    client.post("/api/auth/logout", json={})
    register(client, code)
    client.post("/api/auth/logout", json={})
    as_admin(client)

    assert client.delete(f"/api/admin/invites/{invite_id}").status_code == 409
