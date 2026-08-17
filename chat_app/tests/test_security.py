"""Tests for the before_request security layer.

These use ``/api/providers`` (a cheap GET that touches no external
service) and ``/api/chat`` (a POST) as representative routes - the checks
are installed app-wide, so which route they run against doesn't matter
beyond needing one of each method.

``environ_base={"REMOTE_ADDR": ...}`` is how the Flask test client
pretends a request came from somewhere other than loopback.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from chat_app.services.llm.base import ChatResult


REMOTE = {"REMOTE_ADDR": "203.0.113.5"}


@pytest.fixture(autouse=True)
def no_credentials(monkeypatch):
    """Default state for these tests: auth unconfigured. Individual tests
    opt in by setting both vars."""
    monkeypatch.delenv("CHAT_AUTH_USER", raising=False)
    monkeypatch.delenv("CHAT_AUTH_PASSWORD", raising=False)
    monkeypatch.delenv("CHAT_ALLOWED_HOSTS", raising=False)


@pytest.fixture
def client(client, monkeypatch, users_db):
    """Login is mandatory app-wide with no unconfigured fallback (see
    security.py), so a "200 means the request reached the route" test
    below needs a real session, not just a passing check_host/check_auth.
    Overrides conftest.py's plain client with one that's already logged in
    as an always-full-access admin - these tests are about check_host/
    check_auth/check_cross_site specifically, not about login/RBAC (that's
    test_auth_routes.py/test_account_routes.py's job), so admin's blanket
    access keeps every existing assertion here meaningful unchanged. Runs
    after the autouse no_credentials fixture above (autouse fixtures run
    before explicitly-requested ones), so this login always happens while
    CHAT_AUTH_USER is still unset - individual tests that set it afterward,
    inside the test body, do so only for the request(s) they make next."""
    monkeypatch.setenv("ADMIN_USERNAME", "test-admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "test-admin-pw-1")
    client.post("/login", data={"username": "test-admin", "password": "test-admin-pw-1"})
    return client


def _login_with_host(client, host: str) -> None:
    """The shared ``client`` fixture already logged in once, but Werkzeug's
    test client cookie jar keys the session cookie by the Host header used
    at login time (matching real browsers: Flask's session cookie has no
    explicit Domain attribute, so it's host-only) - see the two tests below
    that vary Host on purpose. A request under a different Host simply
    won't carry that cookie, so those two log in again under the specific
    Host they're about to use."""
    client.post(
        "/login",
        data={"username": "test-admin", "password": "test-admin-pw-1"},
        headers={"Host": host},
    )


def _basic(user: str, password: str) -> dict[str, str]:
    from base64 import b64encode

    token = b64encode(f"{user}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


# --- the loopback fallback ---------------------------------------------


def test_loopback_is_allowed_when_no_credentials_are_configured(client):
    assert client.get("/api/providers").status_code == 200


def test_remote_address_is_refused_when_no_credentials_are_configured(client):
    """The whole point of the fallback: unconfigured means local-only, not
    open to the network."""
    response = client.get("/api/providers", environ_base=REMOTE)

    assert response.status_code == 403
    assert "CHAT_AUTH_USER" in response.get_json()["message"]


def test_half_configured_credentials_count_as_unconfigured(client, monkeypatch):
    """A username with no password is a half-finished setup. Treating it as
    'auth enabled' would lock you out; treating it as 'auth disabled'
    would expose things. Neither guess is safe, so the local-only
    fallback stays in force."""
    monkeypatch.setenv("CHAT_AUTH_USER", "me")

    assert client.get("/api/providers", environ_base=REMOTE).status_code == 403


# --- basic auth --------------------------------------------------------


def test_configured_credentials_require_an_auth_header(client, monkeypatch):
    monkeypatch.setenv("CHAT_AUTH_USER", "me")
    monkeypatch.setenv("CHAT_AUTH_PASSWORD", "s3cret")

    response = client.get("/api/providers")

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"].startswith("Basic ")


def test_wrong_password_is_rejected(client, monkeypatch):
    monkeypatch.setenv("CHAT_AUTH_USER", "me")
    monkeypatch.setenv("CHAT_AUTH_PASSWORD", "s3cret")

    response = client.get("/api/providers", headers=_basic("me", "wrong"))

    assert response.status_code == 401


def test_wrong_username_is_rejected(client, monkeypatch):
    monkeypatch.setenv("CHAT_AUTH_USER", "me")
    monkeypatch.setenv("CHAT_AUTH_PASSWORD", "s3cret")

    response = client.get("/api/providers", headers=_basic("someone-else", "s3cret"))

    assert response.status_code == 401


def test_correct_credentials_pass(client, monkeypatch):
    monkeypatch.setenv("CHAT_AUTH_USER", "me")
    monkeypatch.setenv("CHAT_AUTH_PASSWORD", "s3cret")

    assert client.get("/api/providers", headers=_basic("me", "s3cret")).status_code == 200


def test_non_ascii_basic_auth_credentials_are_rejected_not_crashed(client, monkeypatch):
    """secrets.compare_digest raises TypeError on non-ASCII str arguments
    (bytes are fine) - a Basic Auth header is attacker-controlled, so this
    must produce a clean 401, not an unhandled 500, against the shared-pair
    path."""
    monkeypatch.setenv("CHAT_AUTH_USER", "me")
    monkeypatch.setenv("CHAT_AUTH_PASSWORD", "s3cret")

    response = client.get("/api/providers", headers=_basic("café", "x"))

    assert response.status_code == 401


def test_credentials_unlock_remote_access(client, monkeypatch):
    """Configuring auth is exactly what lifts the loopback restriction."""
    monkeypatch.setenv("CHAT_AUTH_USER", "me")
    monkeypatch.setenv("CHAT_AUTH_PASSWORD", "s3cret")

    response = client.get("/api/providers", headers=_basic("me", "s3cret"), environ_base=REMOTE)

    assert response.status_code == 200


# --- Host header / DNS rebinding ---------------------------------------


def test_foreign_host_header_is_refused_even_from_loopback(client):
    """DNS rebinding makes remote_addr look local while the Host header
    still carries the attacker's domain - so the Host is what's checked."""
    response = client.get("/api/providers", headers={"Host": "evil.example.com"})

    assert response.status_code == 403
    assert "CHAT_ALLOWED_HOSTS" in response.get_json()["message"]


def test_host_with_a_port_is_matched_on_the_hostname(client):
    _login_with_host(client, "127.0.0.1:5009")
    assert client.get("/api/providers", headers={"Host": "127.0.0.1:5009"}).status_code == 200


def test_allowlisted_host_is_accepted(client, monkeypatch):
    monkeypatch.setenv("CHAT_ALLOWED_HOSTS", "tools.internal,other.example")

    _login_with_host(client, "tools.internal")
    assert client.get("/api/providers", headers={"Host": "tools.internal"}).status_code == 200


# --- cross-site requests -----------------------------------------------


def test_cross_site_post_is_refused(client):
    response = client.post(
        "/api/chat",
        json={"question": "hi"},
        headers={"Sec-Fetch-Site": "cross-site"},
    )

    assert response.status_code == 403


def test_same_origin_post_is_allowed(client, chats_db):
    with patch("chat_app.services.llm.router.run_chat", return_value=ChatResult(response="ok")):
        response = client.post(
            "/api/chat",
            json={"question": "hi"},
            headers={"Sec-Fetch-Site": "same-origin"},
        )

    assert response.status_code == 200


def test_direct_navigation_post_is_allowed(client, chats_db):
    """Sec-Fetch-Site: none means a typed URL or bookmark, not another
    site's request."""
    with patch("chat_app.services.llm.router.run_chat", return_value=ChatResult(response="ok")):
        response = client.post("/api/chat", json={"question": "hi"}, headers={"Sec-Fetch-Site": "none"})

    assert response.status_code == 200


def test_mismatched_origin_is_refused_when_sec_fetch_site_is_absent(client):
    """Fallback path for clients that don't send Sec-Fetch-Site."""
    response = client.post("/api/chat", json={"question": "hi"}, headers={"Origin": "http://evil.example.com"})

    assert response.status_code == 403


def test_get_requests_are_not_subject_to_the_cross_site_check(client):
    """No GET route here mutates anything, so blocking cross-site reads
    would cost usability for no gain."""
    assert client.get("/api/providers", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 200


# --- content type ------------------------------------------------------


def test_non_json_content_type_is_refused(client):
    """The CSRF vector that get_json(force=True) left open: a cross-origin
    <form> can POST text/plain with no preflight. Requiring the JSON
    content type is what makes a stray page unable to reach this at all."""
    response = client.post("/api/chat", data='{"question": "hi"}', content_type="text/plain")

    assert response.status_code == 415


def test_form_encoded_post_is_refused(client):
    response = client.post("/api/chat", data={"question": "hi"})

    assert response.status_code == 415


def test_empty_json_body_is_still_accepted_as_no_arguments(client):
    with patch("chat_app.pages.capabilities.routes.call_tool", return_value="ok") as mock_call:
        response = client.post("/capabilities/api/try/some_tool", json={})

    assert response.status_code == 200
    mock_call.assert_called_once_with("some_tool", {})


# --- merged login (real accounts, gate codes) ---------------------------
#
# Unlike the sections above, these tests mostly use a FRESH, sessionless
# client (client.application.test_client()) rather than the file's shared
# `client` fixture - that fixture is already logged in via a session
# cookie, and once any of these tests switches the gate on, every
# subsequent request needs its own valid Basic Auth regardless of that
# cookie (check_auth runs before check_login, unconditionally - see
# check_auth's own docstring). A fresh client sidesteps having to reason
# about that ordering for each assertion.


def test_gate_stays_off_with_no_activation_signal(client):
    """Regression check for the byte-for-byte-unchanged-when-off
    guarantee - the two tests in the loopback-fallback section above
    already cover this implicitly, this one names it explicitly."""
    assert client.get("/api/providers", environ_base=REMOTE).status_code == 403


def test_network_access_enabled_env_var_switches_the_gate_on(client, monkeypatch):
    monkeypatch.setenv("CHAT_NETWORK_ACCESS_ENABLED", "1")

    response = client.get("/api/providers", environ_base=REMOTE)

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"].startswith("Basic ")


def test_a_live_gate_code_switches_the_gate_on(client, users_db):
    from chat_app.auth import store

    store.create_gate_code(users_db, created_by="test-admin", ttl_hours=1)

    response = client.get("/api/providers", environ_base=REMOTE)

    assert response.status_code == 401


def test_real_account_credentials_pass_the_gate_and_auto_login(client, monkeypatch):
    """The 'one prompt, not two' merge: Basic Auth with a real account's
    own credentials both satisfies check_auth AND establishes a session,
    so check_login (which runs right after in the same request) doesn't
    also redirect to /login."""
    monkeypatch.setenv("CHAT_NETWORK_ACCESS_ENABLED", "1")
    fresh = client.application.test_client()

    response = fresh.get(
        "/api/providers", headers=_basic("test-admin", "test-admin-pw-1"), environ_base=REMOTE
    )

    assert response.status_code == 200


def test_non_ascii_credentials_against_the_real_account_path_are_rejected_not_crashed(client, monkeypatch):
    """Same non-ASCII crash as the shared-pair test above, but exercised
    against check_credentials's admin-account comparison (auth/service.py)
    instead of security.py's shared-pair comparison."""
    monkeypatch.setenv("CHAT_NETWORK_ACCESS_ENABLED", "1")
    fresh = client.application.test_client()

    response = fresh.get("/api/providers", headers=_basic("café", "x"), environ_base=REMOTE)

    assert response.status_code == 401


def test_wrong_real_account_password_falls_through_to_401(client, monkeypatch):
    monkeypatch.setenv("CHAT_NETWORK_ACCESS_ENABLED", "1")
    fresh = client.application.test_client()

    response = fresh.get("/api/providers", headers=_basic("test-admin", "wrong-pw"), environ_base=REMOTE)

    assert response.status_code == 401


def test_a_gate_code_passes_the_gate_but_does_not_establish_a_session(client, users_db):
    from chat_app.auth import store

    issued = store.create_gate_code(users_db, created_by="test-admin", ttl_hours=1)
    fresh = client.application.test_client()

    response = fresh.get("/", headers=_basic("whoever", issued.code), environ_base=REMOTE, follow_redirects=False)

    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_gate_code_username_field_is_ignored(client, users_db):
    from chat_app.auth import store

    issued = store.create_gate_code(users_db, created_by="test-admin", ttl_hours=1)
    fresh = client.application.test_client()

    response = fresh.get("/api/providers", headers=_basic("literally-anything", issued.code), environ_base=REMOTE)

    assert response.status_code == 401
    assert response.get_json()["message"] == "Not logged in."  # gate passed (check_auth's own 401 says "Invalid credentials.")


def test_expired_gate_code_is_rejected(client, users_db, monkeypatch):
    """CHAT_NETWORK_ACCESS_ENABLED keeps the gate itself on independent of
    this one code's fate - the code under test is the only gate code that
    has ever existed here, so without another activation signal, expiring
    it would also flip network_gate_enabled() back to False and this
    request would 403 as "not configured" rather than 401 as "invalid
    credentials," which is the thing actually under test."""
    monkeypatch.setenv("CHAT_NETWORK_ACCESS_ENABLED", "1")
    from chat_app.auth import store
    import sqlite3
    from datetime import datetime, timedelta, timezone

    issued = store.create_gate_code(users_db, created_by="test-admin", ttl_hours=1)
    conn = sqlite3.connect(str(users_db))
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    conn.execute("UPDATE gate_codes SET expires_at = ? WHERE code_id = ?", (past, issued.code_id))
    conn.commit()
    conn.close()
    fresh = client.application.test_client()

    response = fresh.get("/api/providers", headers=_basic("whoever", issued.code), environ_base=REMOTE)

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"].startswith("Basic ")


def test_revoked_gate_code_is_rejected_immediately(client, users_db, monkeypatch):
    """Same reasoning as test_expired_gate_code_is_rejected above:
    CHAT_NETWORK_ACCESS_ENABLED keeps the gate on independent of this one
    code, which is the only one ever created here and is about to be
    deleted."""
    monkeypatch.setenv("CHAT_NETWORK_ACCESS_ENABLED", "1")
    from chat_app.auth import store

    issued = store.create_gate_code(users_db, created_by="test-admin", ttl_hours=1)
    store.delete_gate_code(users_db, issued.code_id)
    fresh = client.application.test_client()

    response = fresh.get("/api/providers", headers=_basic("whoever", issued.code), environ_base=REMOTE)

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"].startswith("Basic ")


def test_shared_pair_still_takes_priority_when_configured(client, monkeypatch):
    """When Basic Auth credentials match BOTH the shared pair and a real
    account, the shared pair (checked first) wins - which means no
    session gets established (see check_auth's docstring: the shared
    pair path deliberately doesn't call login()). If path 2 fired
    instead, this would establish a session and a fresh client would get
    200/302-to-overview instead of a redirect to /login."""
    monkeypatch.setenv("CHAT_AUTH_USER", "test-admin")
    monkeypatch.setenv("CHAT_AUTH_PASSWORD", "test-admin-pw-1")
    fresh = client.application.test_client()

    response = fresh.get(
        "/", headers=_basic("test-admin", "test-admin-pw-1"), environ_base=REMOTE, follow_redirects=False
    )

    assert response.status_code == 302
    assert "/login" in response.headers["Location"]
