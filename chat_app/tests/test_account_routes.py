"""Tests for the account manager (create/remove users, roles, expiring
invites) and for role-based access enforcement in general.

Uses the ``users_db`` fixture from conftest.py (fresh per-test SQLite
file) and the admin env vars, since the account manager is only reachable
once login is configured.
"""

from __future__ import annotations

import pytest

from chat_app.app import create_app
from chat_app.auth import store


ADMIN_USER = "admin"
ADMIN_PASSWORD = "s3cret-pw"


@pytest.fixture(autouse=True)
def admin_configured(monkeypatch):
    monkeypatch.setenv("ADMIN_USERNAME", ADMIN_USER)
    monkeypatch.setenv("ADMIN_PASSWORD", ADMIN_PASSWORD)


@pytest.fixture
def admin_client(client):
    client.post("/login", data={"username": ADMIN_USER, "password": ADMIN_PASSWORD})
    return client


def _member_client(admin_client, username="alice", password="hunter2pass"):
    """Register a fresh member-role account (via an invite the admin
    mints) and return a logged-in client for it - a separate browser."""
    invite = admin_client.post("/api/invites").get_json()
    member = create_app().test_client()
    member.post("/register", data={"username": username, "password": password, "invite_code": invite["code"]})
    return member


def _client_with_role(admin_client, role, username, password="hunter2pass"):
    """A logged-in client for a fresh DB user with the given role -
    created directly by ``admin_client`` (the env admin, whose rank is
    unbounded - see auth/service.py's current_rank()), so this works
    regardless of what a given test is checking about lower ranks."""
    created = admin_client.post("/accounts/api/users", json={"username": username, "password": password, "role": role})
    assert created.status_code == 201, created.get_json()
    fresh = create_app().test_client()
    fresh.post("/login", data={"username": username, "password": password})
    return fresh


# --- who can reach the account manager -----------------------------------


def test_admin_can_reach_the_account_manager(admin_client, users_db):
    assert admin_client.get("/accounts/").status_code == 200


def test_member_cannot_reach_the_account_manager_page(admin_client, users_db):
    member = _member_client(admin_client)

    assert member.get("/accounts/").status_code == 403


def test_member_cannot_call_account_manager_apis(admin_client, users_db):
    member = _member_client(admin_client)

    response = member.post("/accounts/api/users", json={"username": "x", "password": "y" * 8, "role": "member"})

    assert response.status_code == 403


# --- creating / deleting users directly -----------------------------------


def test_admin_creates_a_user_directly(admin_client, users_db):
    response = admin_client.post(
        "/accounts/api/users", json={"username": "bob", "password": "hunter2pass", "role": "member"}
    )
    assert response.status_code == 201

    fresh = create_app().test_client()
    login = fresh.post("/login", data={"username": "bob", "password": "hunter2pass"}, follow_redirects=False)
    assert login.status_code == 302


def test_creating_a_user_with_an_unknown_role_fails(admin_client, users_db):
    response = admin_client.post(
        "/accounts/api/users", json={"username": "bob", "password": "hunter2pass", "role": "not-a-role"}
    )
    assert response.status_code == 400


def test_admin_deletes_a_user(admin_client, users_db):
    admin_client.post("/accounts/api/users", json={"username": "bob", "password": "hunter2pass", "role": "member"})

    response = admin_client.delete("/accounts/api/users/bob")

    assert response.status_code == 200
    fresh = create_app().test_client()
    login = fresh.post("/login", data={"username": "bob", "password": "hunter2pass"})
    assert login.status_code == 401


def test_admin_cannot_delete_their_own_account(admin_client, users_db):
    response = admin_client.delete(f"/accounts/api/users/{ADMIN_USER}")

    assert response.status_code == 400


def test_deleting_a_user_invalidates_their_existing_session(admin_client, users_db):
    member = _member_client(admin_client)
    assert member.get("/").status_code == 200

    admin_client.delete("/accounts/api/users/alice")

    # Same browser, same cookie - but the account it names is gone.
    response = member.get("/", follow_redirects=False)
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


# --- roles ------------------------------------------------------------


def test_admin_creates_and_assigns_a_custom_role(admin_client, users_db):
    create = admin_client.post("/accounts/api/roles", json={"name": "reviewer", "scopes": ["capabilities"]})
    assert create.status_code == 201

    admin_client.post("/accounts/api/users", json={"username": "bob", "password": "hunter2pass", "role": "reviewer"})
    reroll = admin_client.post("/accounts/api/users/bob/role", json={"role": "member"})
    assert reroll.status_code == 200


def test_role_restricts_access_to_only_its_granted_scopes(admin_client, users_db):
    admin_client.post("/accounts/api/roles", json={"name": "reviewer", "scopes": ["capabilities"]})
    invite = admin_client.post("/accounts/api/invites", json={"role": "reviewer"}).get_json()

    reviewer = create_app().test_client()
    reviewer.post("/register", data={"username": "carol", "password": "hunter2pass", "invite_code": invite["code"]})

    assert reviewer.get("/capabilities/").status_code == 200
    assert reviewer.get("/chat").status_code == 403


def test_creating_a_role_with_an_unknown_scope_fails(admin_client, users_db):
    response = admin_client.post("/accounts/api/roles", json={"name": "bogus", "scopes": ["not-a-scope"]})
    assert response.status_code == 400


def test_deleting_a_role_still_assigned_to_a_user_fails(admin_client, users_db):
    admin_client.post("/accounts/api/roles", json={"name": "reviewer", "scopes": ["capabilities"]})
    admin_client.post("/accounts/api/users", json={"username": "bob", "password": "hunter2pass", "role": "reviewer"})

    response = admin_client.delete("/accounts/api/roles/reviewer")

    assert response.status_code == 400


def test_admin_role_cannot_be_deleted_via_the_api(admin_client, users_db):
    response = admin_client.delete("/accounts/api/roles/admin")
    assert response.status_code == 400


# --- expiring invite codes ------------------------------------------------


def test_admin_generated_invite_can_carry_an_expiry_and_role(admin_client, users_db):
    response = admin_client.post("/accounts/api/invites", json={"role": "member", "ttl_hours": 1})

    assert response.status_code == 201
    data = response.get_json()
    assert data["role"] == "member"
    assert data["expires_at"] is not None


def test_admin_generated_invite_defaults_to_never_expiring(admin_client, users_db):
    response = admin_client.post("/accounts/api/invites", json={"role": "member"})

    assert response.status_code == 201
    assert response.get_json()["expires_at"] is None


def test_admin_can_delete_an_outstanding_invite(admin_client, users_db):
    admin_client.post("/accounts/api/invites", json={"role": "member"})
    [invite] = store.list_invite_codes(users_db)

    response = admin_client.delete(f"/accounts/api/invites/{invite['code_id']}")

    assert response.status_code == 200
    assert store.list_invite_codes(users_db) == []


def test_deleting_an_unknown_invite_returns_404(admin_client, users_db):
    response = admin_client.delete("/accounts/api/invites/not-a-real-code-id")

    assert response.status_code == 404


def test_member_cannot_delete_an_invite(admin_client, users_db):
    admin_client.post("/accounts/api/invites", json={"role": "member"})
    [invite] = store.list_invite_codes(users_db)
    member = _member_client(admin_client)

    response = member.delete(f"/accounts/api/invites/{invite['code_id']}")

    assert response.status_code == 403


# --- role hierarchy: executive tier, ranked promotion/demotion -----------
#
# admin_client is logged in as the env-configured admin - which is root,
# and root's role is EXECUTIVE_ROLE now, not ADMIN_ROLE (see
# auth/service.py's current_role()). Every test below that needs a
# genuinely rank-1 actor (not root) creates one via _client_with_role().


def test_env_admin_is_executive_not_admin(admin_client, users_db):
    """The one behavioral guarantee "the .env user is the only Executive
    by default" rests on."""
    page = admin_client.get("/accounts/").get_data(as_text=True)
    assert "executive" in page


def test_plain_admin_cannot_promote_a_member_to_admin(admin_client, users_db):
    admin_actor = _client_with_role(admin_client, "admin", "plain-admin")
    admin_client.post("/accounts/api/users", json={"username": "bob", "password": "hunter2pass", "role": "member"})

    response = admin_actor.post("/accounts/api/users/bob/role", json={"role": "admin"})

    assert response.status_code == 403


def test_plain_admin_cannot_create_a_user_with_admin_role(admin_client, users_db):
    admin_actor = _client_with_role(admin_client, "admin", "plain-admin")

    response = admin_actor.post(
        "/accounts/api/users", json={"username": "bob", "password": "hunter2pass", "role": "admin"}
    )

    assert response.status_code == 403


def test_plain_admin_cannot_mint_an_executive_invite(admin_client, users_db):
    admin_actor = _client_with_role(admin_client, "admin", "plain-admin")

    response = admin_actor.post("/accounts/api/invites", json={"role": "executive"})

    assert response.status_code == 403


def test_executive_can_promote_a_member_to_admin(admin_client, users_db):
    executive_actor = _client_with_role(admin_client, "executive", "exec-two")
    admin_client.post("/accounts/api/users", json={"username": "bob", "password": "hunter2pass", "role": "member"})

    response = executive_actor.post("/accounts/api/users/bob/role", json={"role": "admin"})

    assert response.status_code == 200
    assert store.get_user_role(users_db, "bob") == "admin"


def test_executive_can_grant_the_executive_role_to_someone_else(admin_client, users_db):
    """The requirement this whole hierarchy exists to satisfy: any
    executive - not just root - can create another one."""
    executive_actor = _client_with_role(admin_client, "executive", "exec-two")
    admin_client.post("/accounts/api/users", json={"username": "bob", "password": "hunter2pass", "role": "member"})

    response = executive_actor.post("/accounts/api/users/bob/role", json={"role": "executive"})

    assert response.status_code == 200
    assert store.get_user_role(users_db, "bob") == "executive"


def test_two_peer_executives_cannot_change_each_others_role(admin_client, users_db):
    exec_one = _client_with_role(admin_client, "executive", "exec-one")
    _client_with_role(admin_client, "executive", "exec-two")

    response = exec_one.post("/accounts/api/users/exec-two/role", json={"role": "member"})

    assert response.status_code == 403
    assert store.get_user_role(users_db, "exec-two") == "executive"


def test_root_can_demote_any_executive(admin_client, users_db):
    _client_with_role(admin_client, "executive", "exec-one")

    response = admin_client.post("/accounts/api/users/exec-one/role", json={"role": "member"})

    assert response.status_code == 200
    assert store.get_user_role(users_db, "exec-one") == "member"


def test_user_can_demote_themselves(admin_client, users_db):
    admin_actor = _client_with_role(admin_client, "admin", "plain-admin")

    response = admin_actor.post("/accounts/api/users/plain-admin/role", json={"role": "member"})

    assert response.status_code == 200
    assert store.get_user_role(users_db, "plain-admin") == "member"


def test_user_cannot_promote_themselves(admin_client, users_db):
    admin_actor = _client_with_role(admin_client, "admin", "plain-admin")

    response = admin_actor.post("/accounts/api/users/plain-admin/role", json={"role": "executive"})

    assert response.status_code == 403
    assert store.get_user_role(users_db, "plain-admin") == "admin"


def test_plain_admin_cannot_delete_a_peer_admin(admin_client, users_db):
    admin_actor = _client_with_role(admin_client, "admin", "plain-admin")
    _client_with_role(admin_client, "admin", "other-admin")

    response = admin_actor.delete("/accounts/api/users/other-admin")

    assert response.status_code == 403
    assert store.get_user_role(users_db, "other-admin") == "admin"


def test_executive_can_delete_an_admin(admin_client, users_db):
    executive_actor = _client_with_role(admin_client, "executive", "exec-two")
    _client_with_role(admin_client, "admin", "plain-admin")

    response = executive_actor.delete("/accounts/api/users/plain-admin")

    assert response.status_code == 200


def test_assigning_a_custom_role_still_only_needs_accounts_scope(admin_client, users_db):
    """The unranked path (member and any custom role) is deliberately
    untouched by this feature - a plain admin could always do this, and
    still can."""
    admin_actor = _client_with_role(admin_client, "admin", "plain-admin")
    admin_client.post("/accounts/api/roles", json={"name": "reviewer", "scopes": ["capabilities"]})
    admin_client.post("/accounts/api/users", json={"username": "bob", "password": "hunter2pass", "role": "member"})

    response = admin_actor.post("/accounts/api/users/bob/role", json={"role": "reviewer"})

    assert response.status_code == 200
