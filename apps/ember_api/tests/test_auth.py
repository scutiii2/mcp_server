from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient
from sqlalchemy import select

from src.models import LoginAttempt
from src.services.permissions import ALL_PERMISSIONS
from tests.conftest import ADMIN_PASSWORD, ADMIN_USERNAME


def login(client: TestClient, username: str = ADMIN_USERNAME, password: str = ADMIN_PASSWORD):
    return client.post("/api/auth/login", json={"username": username, "password": password})


def login_attempts(client: TestClient) -> list[LoginAttempt]:
    async def fetch() -> list[LoginAttempt]:
        async with client.app.state.database.sessions() as session:
            return list(await session.scalars(select(LoginAttempt)))

    return client.portal.call(fetch)


def test_bootstrap_admin_can_log_in_with_every_permission(client: TestClient) -> None:
    response = login(client)

    assert response.status_code == 200
    body = response.json()
    assert body["username"] == ADMIN_USERNAME
    assert body["email_verified"] is True
    assert body["roles"] == ["Administrator"]
    assert body["permissions"] == sorted(ALL_PERMISSIONS)
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie


def test_me_returns_the_logged_in_account(client: TestClient) -> None:
    login(client)

    response = client.get("/api/auth/me")

    assert response.status_code == 200
    assert response.json()["username"] == ADMIN_USERNAME


def test_me_without_a_session_is_401(client: TestClient) -> None:
    assert client.get("/api/auth/me").status_code == 401


def test_wrong_password_and_unknown_user_fail_identically(client: TestClient) -> None:
    wrong_password = login(client, password="nope")
    unknown_user = login(client, username="ghost", password="nope")

    assert wrong_password.status_code == unknown_user.status_code == 401
    assert wrong_password.json() == unknown_user.json()
    assert "set-cookie" not in wrong_password.headers


def test_every_login_attempt_is_recorded(client: TestClient) -> None:
    login(client, password="nope")
    login(client, username="ghost", password="nope")
    login(client)

    attempts = login_attempts(client)

    assert [a.succeeded for a in attempts] == [False, False, True]
    assert attempts[0].account_id is not None  # known user, wrong password
    assert attempts[1].account_id is None  # unknown user


def test_logout_ends_the_session_server_side(client: TestClient) -> None:
    token = login(client).cookies["ember_session"]

    assert client.post("/api/auth/logout", json={}).status_code == 204

    # Replaying the old cookie must not work: the session row is gone.
    client.cookies.set("ember_session", token)
    assert client.get("/api/auth/me").status_code == 401


def test_expired_session_is_rejected(client_factory) -> None:
    client = client_factory(session_hours=0)  # every session expires immediately
    login(client)

    assert client.get("/api/auth/me").status_code == 401


def test_non_json_post_is_rejected(client: TestClient) -> None:
    response = client.post(
        "/api/auth/login",
        data={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD},  # form-encoded
    )

    assert response.status_code == 415
    assert "set-cookie" not in response.headers


def test_missing_admin_password_is_generated(client_factory, capsys) -> None:
    client_factory(admin_password="")

    assert "Bootstrap admin created with password:" in capsys.readouterr().out


def test_restart_syncs_admin_password_from_secrets(client_factory) -> None:
    client_factory()
    restarted = client_factory(admin_password="a brand new password")

    assert login(restarted).status_code == 401
    assert login(restarted, password="a brand new password").status_code == 200


def test_async_hashing_helpers_round_trip() -> None:
    from src.services.auth_service import hash_password, password_matches

    async def run() -> tuple[bool, bool]:
        hashed = await hash_password("s3cret")
        return await password_matches(hashed, "s3cret"), await password_matches(hashed, "wrong")

    assert asyncio.run(run()) == (True, False)
