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
    assert client.get("/api/providers", headers={"Host": "127.0.0.1:5009"}).status_code == 200


def test_allowlisted_host_is_accepted(client, monkeypatch):
    monkeypatch.setenv("CHAT_ALLOWED_HOSTS", "tools.internal,other.example")

    assert client.get("/api/providers", headers={"Host": "tools.internal"}).status_code == 200


# --- cross-site requests -----------------------------------------------


def test_cross_site_post_is_refused(client):
    response = client.post(
        "/api/chat",
        json={"question": "hi"},
        headers={"Sec-Fetch-Site": "cross-site"},
    )

    assert response.status_code == 403


def test_same_origin_post_is_allowed(client):
    with patch("chat_app.services.llm.router.run_chat", return_value=ChatResult(response="ok")):
        response = client.post(
            "/api/chat",
            json={"question": "hi"},
            headers={"Sec-Fetch-Site": "same-origin"},
        )

    assert response.status_code == 200


def test_direct_navigation_post_is_allowed(client):
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
