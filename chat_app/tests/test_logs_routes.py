"""Tests for the Logs page's routes - access control (executive-only,
enforced outside the scope system - see security.check_role_permission's
EXECUTIVE_ENDPOINTS branch) and the read endpoints themselves."""

from __future__ import annotations

import json

import pytest

from chat_app.app import create_app


ADMIN_USER = "root-admin"
ADMIN_PASSWORD = "s3cret-pw"


@pytest.fixture(autouse=True)
def admin_configured(monkeypatch):
    monkeypatch.setenv("ADMIN_USERNAME", ADMIN_USER)
    monkeypatch.setenv("ADMIN_PASSWORD", ADMIN_PASSWORD)


@pytest.fixture
def admin_client(client):
    """The env admin - root, whose role is EXECUTIVE_ROLE (see
    auth/service.py's current_role())."""
    client.post("/login", data={"username": ADMIN_USER, "password": ADMIN_PASSWORD})
    return client


def _client_with_role(admin_client, role, username, password="hunter2pass"):
    admin_client.post("/accounts/api/users", json={"username": username, "password": password, "role": role})
    fresh = create_app().test_client()
    fresh.post("/login", data={"username": username, "password": password})
    return fresh


def _write_chat_log(log_dir, username, chat_id, lines):
    chat_dir = log_dir / "chats" / username
    chat_dir.mkdir(parents=True, exist_ok=True)
    (chat_dir / f"{chat_id}.jsonl").write_text(
        "\n".join(json.dumps(line) for line in lines) + "\n", encoding="utf-8"
    )


def _write_error_log(log_dir, reference, content):
    errors_dir = log_dir / "errors"
    errors_dir.mkdir(parents=True, exist_ok=True)
    (errors_dir / f"{reference}.log").write_text(content, encoding="utf-8")


# --- access control ---------------------------------------------------


def test_executive_can_reach_the_logs_page(admin_client, users_db, log_dir):
    assert admin_client.get("/logs/").status_code == 200


def test_plain_admin_cannot_reach_the_logs_page(admin_client, users_db, log_dir):
    """The behavior this whole feature exists for: admin - even with
    every scope in SCOPES - does not get the Logs page for free."""
    admin_actor = _client_with_role(admin_client, "admin", "plain-admin")

    assert admin_actor.get("/logs/").status_code == 403


def test_member_cannot_reach_the_logs_page(admin_client, users_db, log_dir):
    member = _client_with_role(admin_client, "member", "plain-member")

    assert member.get("/logs/").status_code == 403


def test_plain_admin_cannot_call_the_logs_apis(admin_client, users_db, log_dir):
    admin_actor = _client_with_role(admin_client, "admin", "plain-admin")

    assert admin_actor.get("/logs/api/chat-users").status_code == 403
    assert admin_actor.get("/logs/api/errors").status_code == 403


def test_a_second_executive_can_also_reach_the_logs_page(admin_client, users_db, log_dir):
    """Not root-only - any user with EXECUTIVE_ROLE."""
    executive_actor = _client_with_role(admin_client, "executive", "exec-two")

    assert executive_actor.get("/logs/").status_code == 200


# --- chat log endpoints --------------------------------------------------


def test_list_chat_log_users_api(admin_client, users_db, log_dir):
    _write_chat_log(log_dir, "alice", "chat1", [{"question": "hi"}])

    response = admin_client.get("/logs/api/chat-users")

    assert response.get_json() == ["alice"]


def test_list_user_chat_logs_api(admin_client, users_db, log_dir):
    _write_chat_log(log_dir, "alice", "chat1", [{"question": "hi"}])

    response = admin_client.get("/logs/api/chats/alice")

    [entry] = response.get_json()
    assert entry["chat_id"] == "chat1"


def test_get_chat_log_api_returns_the_parsed_turns(admin_client, users_db, log_dir):
    _write_chat_log(log_dir, "alice", "chat1", [{"question": "hi", "response": "hello"}])

    response = admin_client.get("/logs/api/chats/alice/chat1")

    assert response.status_code == 200
    [turn] = response.get_json()
    assert turn == {"question": "hi", "response": "hello"}


def test_get_chat_log_api_404s_for_an_unknown_chat(admin_client, users_db, log_dir):
    response = admin_client.get("/logs/api/chats/alice/no-such-chat")

    assert response.status_code == 404


# --- error log endpoints -------------------------------------------------


def test_list_error_logs_api(admin_client, users_db, log_dir):
    _write_error_log(log_dir, "abc123", "traceback text")

    response = admin_client.get("/logs/api/errors")

    [entry] = response.get_json()
    assert entry["reference"] == "abc123"


def test_get_error_log_api_returns_the_content(admin_client, users_db, log_dir):
    _write_error_log(log_dir, "abc123", "reference: abc123\n\nTraceback...")

    response = admin_client.get("/logs/api/errors/abc123")

    assert response.status_code == 200
    assert response.get_json() == {"reference": "abc123", "content": "reference: abc123\n\nTraceback..."}


def test_get_error_log_api_404s_for_an_unknown_reference(admin_client, users_db, log_dir):
    response = admin_client.get("/logs/api/errors/no-such-ref")

    assert response.status_code == 404
