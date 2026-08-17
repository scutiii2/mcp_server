"""End-to-end tests for the login gate, login/register pages, and the
invite-code API, using the Flask test client (which persists the session
cookie across requests on the same client, so a login followed by a
protected request behaves like a real browser).

``users_db`` (from conftest.py) points every settings-reading module at a
fresh, per-test SQLite file rather than the real (import-time-frozen)
``settings.users_db_path`` - see config.py's comment on that field.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def no_admin(monkeypatch):
    """Default state: login unconfigured. Individual tests opt in."""
    monkeypatch.delenv("ADMIN_USERNAME", raising=False)
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)


def _set_admin(monkeypatch, user="admin", password="s3cret-pw"):
    monkeypatch.setenv("ADMIN_USERNAME", user)
    monkeypatch.setenv("ADMIN_PASSWORD", password)
    return user, password


# --- the gate itself -----------------------------------------------------


def test_login_is_required_even_without_admin_configured(client, users_db):
    """Unlike CHAT_AUTH_USER/CHAT_AUTH_PASSWORD's loopback fallback, there
    is no "unconfigured means open" escape hatch for per-user login - see
    security.check_login. An unset ADMIN_USERNAME/ADMIN_PASSWORD just
    means nobody currently has valid credentials to log in with; it
    doesn't relax the gate itself."""
    response = client.get("/", follow_redirects=False)

    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_configured_login_redirects_page_requests(client, users_db, monkeypatch):
    _set_admin(monkeypatch)

    response = client.get("/", follow_redirects=False)

    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_configured_login_returns_401_json_for_api_requests(client, users_db, monkeypatch):
    _set_admin(monkeypatch)

    response = client.get("/api/providers")

    assert response.status_code == 401


def test_login_and_register_pages_are_reachable_while_logged_out(client, users_db, monkeypatch):
    _set_admin(monkeypatch)

    assert client.get("/login").status_code == 200
    assert client.get("/register").status_code == 200


# --- logging in -----------------------------------------------------------


def test_admin_login_succeeds_and_unlocks_other_routes(client, users_db, monkeypatch):
    user, password = _set_admin(monkeypatch)

    login = client.post("/login", data={"username": user, "password": password}, follow_redirects=False)
    assert login.status_code == 302

    assert client.get("/").status_code == 200


def test_wrong_password_is_rejected(client, users_db, monkeypatch):
    user, _ = _set_admin(monkeypatch)

    response = client.post("/login", data={"username": user, "password": "nope"})

    assert response.status_code == 401
    assert client.get("/api/providers").status_code == 401


def test_logout_locks_the_app_again(client, users_db, monkeypatch):
    user, password = _set_admin(monkeypatch)
    client.post("/login", data={"username": user, "password": password})
    assert client.get("/").status_code == 200

    client.get("/logout")

    assert client.get("/", follow_redirects=False).status_code == 302


# --- invite-gated registration ---------------------------------------------


def test_registration_without_a_valid_code_is_rejected(client, users_db, monkeypatch):
    _set_admin(monkeypatch)

    response = client.post(
        "/register",
        data={"username": "alice", "password": "hunter2pass", "invite_code": "bogus"},
    )

    assert response.status_code == 400
    assert client.get("/api/providers").status_code == 401


def test_full_invite_and_register_flow(client, users_db, monkeypatch):
    user, password = _set_admin(monkeypatch)
    client.post("/login", data={"username": user, "password": password})

    invite = client.post("/api/invites")
    assert invite.status_code == 200
    code = invite.get_json()["code"]

    # A brand new client, i.e. a different browser/person.
    from chat_app.app import create_app

    other = create_app().test_client()
    register = other.post(
        "/register",
        data={"username": "alice", "password": "hunter2pass", "invite_code": code},
        follow_redirects=False,
    )
    assert register.status_code == 302

    assert other.get("/").status_code == 200

    # The code is single-use.
    third = create_app().test_client()
    reuse = third.post(
        "/register",
        data={"username": "bob", "password": "another-pass1", "invite_code": code},
    )
    assert reuse.status_code == 400


def test_generating_an_invite_requires_login(client, users_db, monkeypatch):
    _set_admin(monkeypatch)

    assert client.post("/api/invites").status_code == 401


# --- self-service gate codes (sidebar quick-action) ------------------------


def test_generating_a_gate_code_requires_login(client, users_db, monkeypatch):
    _set_admin(monkeypatch)

    assert client.post("/api/gate-codes").status_code == 401


def test_logged_in_user_can_generate_a_gate_code(client, users_db, monkeypatch):
    user, password = _set_admin(monkeypatch)
    client.post("/login", data={"username": user, "password": password})

    response = client.post("/api/gate-codes")

    assert response.status_code == 200
    data = response.get_json()
    assert data["code"]
    assert data["expires_at"] is not None


def test_generated_gate_code_carries_a_twenty_four_hour_ttl(client, users_db, monkeypatch):
    user, password = _set_admin(monkeypatch)
    client.post("/login", data={"username": user, "password": password})

    from datetime import datetime

    data = client.post("/api/gate-codes").get_json()
    created = datetime.fromisoformat(data["created_at"])
    expires = datetime.fromisoformat(data["expires_at"])

    assert (expires - created).total_seconds() == pytest.approx(24 * 3600, abs=2)
