from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update

from src.config import SecuritySettings
from src.db import utcnow
from src.models import LoginAttempt
from tests.conftest import ADMIN_PASSWORD, ADMIN_USERNAME


def login(client: TestClient, password: str, username: str = ADMIN_USERNAME, **headers):
    return client.post("/api/auth/login", json={"username": username, "password": password}, headers=headers)


def fail(client: TestClient, times: int, username: str = ADMIN_USERNAME, **headers) -> None:
    for _ in range(times):
        assert login(client, "wrong password", username, **headers).status_code == 401


def age_all_attempts(client: TestClient, seconds: int) -> None:
    async def run() -> None:
        async with client.app.state.database.sessions() as session:
            await session.execute(
                update(LoginAttempt).values(attempted_at=utcnow() - timedelta(seconds=seconds))
            )
            await session.commit()

    client.portal.call(run)


# --- rate limiting -----------------------------------------------------------


def test_lockout_after_max_failures_even_with_right_password(client: TestClient) -> None:
    fail(client, 5)

    response = login(client, ADMIN_PASSWORD)

    assert response.status_code == 429
    assert 0 < int(response.headers["Retry-After"]) <= 900
    assert "Too many failed logins" in response.json()["detail"]


def test_below_the_limit_login_still_works(client: TestClient) -> None:
    fail(client, 4)

    assert login(client, ADMIN_PASSWORD).status_code == 200


def test_lockout_ends_after_lockout_seconds(client: TestClient) -> None:
    fail(client, 5)
    age_all_attempts(client, 600)  # still inside the 900s window and lockout
    assert login(client, ADMIN_PASSWORD).status_code == 429

    age_all_attempts(client, 901)

    assert login(client, ADMIN_PASSWORD).status_code == 200


def test_refused_tries_do_not_extend_the_lockout(client: TestClient) -> None:
    fail(client, 5)
    for _ in range(3):
        assert login(client, ADMIN_PASSWORD).status_code == 429

    age_all_attempts(client, 901)

    assert login(client, ADMIN_PASSWORD).status_code == 200


def test_account_lockout_applies_from_another_ip(client_factory) -> None:
    attacker = client_factory(address="203.0.113.7")
    fail(attacker, 5)

    owner = client_factory(address="198.51.100.2")

    assert login(owner, ADMIN_PASSWORD).status_code == 429


def test_ip_lockout_covers_other_usernames(client_factory) -> None:
    attacker = client_factory(address="203.0.113.7")
    fail(attacker, 5, username="nobody")

    assert login(attacker, ADMIN_PASSWORD).status_code == 429
    assert login(client_factory(address="198.51.100.2"), ADMIN_PASSWORD).status_code == 200


def test_ip_scope_does_not_lock_the_account_elsewhere(client_factory) -> None:
    security = SecuritySettings(rate_limit_scope="ip")
    fail(client_factory(address="203.0.113.7", security=security), 5)

    assert login(client_factory(address="198.51.100.2", security=security), ADMIN_PASSWORD).status_code == 200


def test_rate_limit_can_be_disabled(client_factory) -> None:
    client = client_factory(security=SecuritySettings(rate_limit_enabled=False))
    fail(client, 8)

    assert login(client, ADMIN_PASSWORD).status_code == 200


# --- client IP ------------------------------------------------------------------


def test_forwarded_for_is_trusted_only_from_a_trusted_proxy(client_factory) -> None:
    # Through the (loopback) Vite proxy: the forwarded address is the client.
    proxy = client_factory(address="127.0.0.1")
    fail(proxy, 5, **{"X-Forwarded-For": "203.0.113.7"})
    assert login(proxy, ADMIN_PASSWORD, username="nobody", **{"X-Forwarded-For": "203.0.113.7"}).status_code == 429
    assert login(proxy, "wrong", username="nobody", **{"X-Forwarded-For": "198.51.100.2"}).status_code == 401

    # Straight from an untrusted peer, a forged header is ignored.
    direct = client_factory(address="198.51.100.9")
    assert login(direct, "wrong", username="nobody", **{"X-Forwarded-For": "203.0.113.7"}).status_code == 401


def test_login_attempts_record_the_resolved_ip(client_factory) -> None:
    proxy = client_factory(address="127.0.0.1")
    login(proxy, "wrong", **{"X-Forwarded-For": "spoofed, 203.0.113.7"})

    async def ips() -> list[str]:
        async with proxy.app.state.database.sessions() as session:
            from sqlalchemy import select

            return list(await session.scalars(select(LoginAttempt.ip_address)))

    assert proxy.portal.call(ips) == ["203.0.113.7"]


# --- IP filter ------------------------------------------------------------------


def test_deny_list_blocks_every_route(client_factory) -> None:
    client = client_factory(address="203.0.113.7", security=SecuritySettings(ip_deny_list=("203.0.113.0/24",)))

    response = client.get("/api/health")

    assert response.status_code == 403
    assert response.headers["x-content-type-options"] == "nosniff"


def test_allow_list_admits_only_listed_networks(client_factory) -> None:
    security = SecuritySettings(ip_allow_list=("10.0.0.0/8",))

    assert client_factory(address="10.1.2.3", security=security).get("/api/health").status_code == 200
    assert client_factory(address="203.0.113.7", security=security).get("/api/health").status_code == 403


def test_invalid_network_is_a_startup_error(client_factory) -> None:
    with pytest.raises(ValueError, match="not-an-ip"):
        client_factory(security=SecuritySettings(ip_deny_list=("not-an-ip",)))


# --- headers ----------------------------------------------------------------------


def test_security_headers_on_every_response(client: TestClient) -> None:
    for response in (client.get("/api/health"), client.get("/api/auth/me")):
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["x-frame-options"] == "DENY"
        assert response.headers["referrer-policy"] == "no-referrer"
        assert "default-src 'none'" in response.headers["content-security-policy"]
        assert "strict-transport-security" not in response.headers


def test_hsts_and_disabling_headers(client_factory) -> None:
    hsts = client_factory(security=SecuritySettings(hsts_max_age=31536000)).get("/api/health")
    assert hsts.headers["strict-transport-security"] == "max-age=31536000; includeSubDomains"

    plain = client_factory(security=SecuritySettings(security_headers=False)).get("/api/health")
    assert "x-frame-options" not in plain.headers


def test_config_rejects_unknown_scope() -> None:
    with pytest.raises(ValueError, match="scope"):
        SecuritySettings.from_config({"rate_limit": {"scope": "everyone"}})
