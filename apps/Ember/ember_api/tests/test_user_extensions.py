"""/api/user-extensions: an account's own MCP servers."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.services import user_extension_service as svc
from tests.conftest import FakeAgent, FakeEmailSender
from tests.test_admin import login, make_member
from tests.test_registration import as_admin

URL = "/api/user-extensions"
EXT_URL = "https://notes.example.com/mcp"


def add(client: TestClient, label: str = "Notes", url: str = EXT_URL, **extra):
    return client.post(URL, json={"label": label, "url": url, **extra})


def test_needs_login(client: TestClient) -> None:
    assert client.get(URL).status_code == 401
    assert add(client).status_code == 401
    assert client.patch(f"{URL}/notes", json={"enabled": False}).status_code == 401
    assert client.delete(f"{URL}/notes").status_code == 401


def test_add_returns_the_extension_with_its_live_status(client: TestClient, agent: FakeAgent) -> None:
    as_admin(client)
    agent.probe_results[EXT_URL] = {"status": "connected", "error": None, "tools": ["search", "add"]}

    created = add(client, headers={"X-Key": "s3cret", "Authorization": "Bearer t0ken"})

    assert created.status_code == 201
    assert created.json() == {
        "id": "notes", "label": "Notes", "description": "", "url": EXT_URL,
        "header_names": ["Authorization", "X-Key"], "enabled": True,
        "status": "connected", "error": None, "tools": ["search", "add"],
    }
    assert agent.probes[-1]["extension_url"] == EXT_URL
    assert agent.probes[-1]["headers"] == {"X-Key": "s3cret", "Authorization": "Bearer t0ken"}


def test_no_reply_ever_contains_a_header_value(client: TestClient) -> None:
    as_admin(client)
    created = add(client, headers={"X-Key": "s3cret-value"})
    listed = client.get(URL)
    patched = client.patch(f"{URL}/notes", json={"label": "Renamed"})

    for response in (created, listed, patched):
        assert "s3cret-value" not in response.text


def test_an_unreachable_extension_is_still_saved(client: TestClient, agent: FakeAgent) -> None:
    as_admin(client)
    agent.probe_results[EXT_URL] = {"status": "error", "error": "That address is not allowed", "tools": []}

    created = add(client)

    assert created.status_code == 201
    assert (created.json()["status"], created.json()["error"]) == ("error", "That address is not allowed")
    assert [e["id"] for e in client.get(URL).json()] == ["notes"]


def test_an_agent_that_cannot_be_asked_leaves_the_status_unknown(client: TestClient, agent: FakeAgent) -> None:
    as_admin(client)
    agent.probe_fail = "Could not reach the agent: refused"

    created = add(client)

    assert created.status_code == 201
    assert (created.json()["status"], created.json()["error"]) == ("unknown", "Couldn't check right now")


def test_slugs_are_made_from_the_label_and_stay_unique(client: TestClient) -> None:
    as_admin(client)

    assert add(client, label="My Notes!").json()["id"] == "my_notes"
    assert add(client, label="My Notes!").json()["id"] == "my_notes_2"


def test_bad_input_is_refused_with_a_message(client: TestClient) -> None:
    as_admin(client)

    for body in (
        {"label": "x", "url": "ftp://x.com/m"},
        {"label": "x", "url": "https://u:p@x.com/m"},
        {"label": "  ", "url": EXT_URL},
        {"label": "x", "url": EXT_URL, "headers": {"Host": "evil"}},
        {"label": "x", "url": EXT_URL, "headers": {"X": ""}},
        {"label": "x", "url": EXT_URL, "headers": {"bad name": "v"}},
    ):
        response = client.post(URL, json=body)
        assert response.status_code == 422, body
        assert isinstance(response.json()["detail"], str) and response.json()["detail"]
    assert client.post(URL, json={"url": EXT_URL}).status_code == 422  # a label is required


def test_the_limit_is_a_conflict(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(svc, "MAX_EXTENSIONS", 1)
    as_admin(client)
    add(client)

    assert add(client, label="Two").status_code == 409


def test_an_account_only_sees_and_changes_its_own(client_factory, email: FakeEmailSender) -> None:
    alice = client_factory()
    make_member(alice, email)
    make_member(alice, email, "bob")
    login(alice, "alice")
    add(alice, headers={"X-Key": "s3cret"})

    bob = client_factory()
    login(bob, "bob")

    assert bob.get(URL).json() == []
    assert bob.patch(f"{URL}/notes", json={"enabled": False}).status_code == 404
    assert bob.delete(f"{URL}/notes").status_code == 404
    assert [e["id"] for e in alice.get(URL).json()] == ["notes"]
    assert add(bob).json()["id"] == "notes"  # slugs are per account


def test_patch_changes_fields_and_enabled(client: TestClient) -> None:
    as_admin(client)
    add(client, headers={"X-Key": "s3cret"})

    renamed = client.patch(f"{URL}/notes", json={"label": "My notes", "description": "work"}).json()
    off = client.patch(f"{URL}/notes", json={"enabled": False}).json()

    assert (renamed["label"], renamed["description"], renamed["id"]) == ("My notes", "work", "notes")
    assert off["enabled"] is False
    assert off["header_names"] == ["X-Key"]  # headers untouched


def test_patch_headers_replace_them_and_a_new_host_clears_them(client: TestClient) -> None:
    as_admin(client)
    add(client, headers={"X-Key": "one"})

    replaced = client.patch(f"{URL}/notes", json={"headers": {"Authorization": "Bearer two"}}).json()
    same_host = client.patch(f"{URL}/notes", json={"url": "https://notes.example.com/other"}).json()
    moved = client.patch(f"{URL}/notes", json={"url": "https://elsewhere.example.org/mcp"}).json()

    assert replaced["header_names"] == ["Authorization"]
    assert same_host["header_names"] == ["Authorization"]
    assert moved["header_names"] == []


def test_patch_needs_something_to_change(client: TestClient) -> None:
    as_admin(client)
    add(client)

    assert client.patch(f"{URL}/notes", json={}).status_code == 422
    assert client.patch(f"{URL}/Bad_Slug", json={"enabled": False}).status_code == 422


def test_delete(client: TestClient) -> None:
    as_admin(client)
    add(client)

    assert client.delete(f"{URL}/notes").status_code == 204
    assert client.get(URL).json() == []
    assert client.delete(f"{URL}/notes").status_code == 404


def test_the_status_is_cached_and_an_edit_asks_again(client: TestClient, agent: FakeAgent) -> None:
    as_admin(client)
    add(client)
    asked = len(agent.probes)

    client.get(URL)
    client.get(URL)
    assert len(agent.probes) == asked  # served from the cache

    client.patch(f"{URL}/notes", json={"url": "https://notes.example.com/v2"})
    assert len(agent.probes) == asked + 1


def test_a_disabled_extension_is_not_probed(client: TestClient, agent: FakeAgent) -> None:
    as_admin(client)
    add(client)
    client.patch(f"{URL}/notes", json={"enabled": False})
    asked = len(agent.probes)

    listed = client.get(URL).json()[0]

    assert len(agent.probes) == asked
    assert (listed["enabled"], listed["status"], listed["tools"]) == (False, "unknown", [])


def test_the_headers_are_encrypted_in_the_database(client: TestClient, tmp_path: Path) -> None:
    as_admin(client)
    add(client, headers={"X-Key": "s3cret-value"})

    with sqlite3.connect(tmp_path / "data" / "test.db") as conn:
        (token,) = conn.execute("SELECT headers_encrypted FROM user_extensions").fetchone()

    assert token and "s3cret-value" not in token


def test_unreadable_headers_show_an_error_and_can_be_repaired(client: TestClient, tmp_path: Path) -> None:
    as_admin(client)
    add(client, headers={"X-Key": "one"})
    add(client, label="Wiki", url="https://wiki.example.com/mcp")
    with sqlite3.connect(tmp_path / "data" / "test.db") as conn:
        conn.execute("UPDATE user_extensions SET headers_encrypted = 'garbage' WHERE slug = 'notes'")

    broken = next(e for e in client.get(URL).json() if e["id"] == "notes")
    wiki = next(e for e in client.get(URL).json() if e["id"] == "wiki")
    repaired = client.patch(f"{URL}/notes", json={"headers": {"X-Key": "two"}}).json()

    assert (broken["status"], broken["header_names"]) == ("error", [])
    assert "can't be read" in broken["error"]
    assert wiki["status"] == "connected"
    assert (repaired["status"], repaired["header_names"]) == ("connected", ["X-Key"])


def test_changes_are_logged_without_secrets_or_the_query_string(client: TestClient) -> None:
    as_admin(client)
    add(client, url="https://notes.example.com/mcp?token=abc123", headers={"X-Key": "s3cret-value"})
    client.patch(f"{URL}/notes", json={"enabled": False})
    client.patch(f"{URL}/notes", json={"enabled": True})
    client.patch(f"{URL}/notes", json={"label": "Renamed"})
    client.delete(f"{URL}/notes")
    me = client.get("/api/auth/me").json()["id"]

    logged = [e["message"] for e in client.get("/api/logs/action", params={"actor": me}).json()]

    assert logged[:5] == [
        "Removed private extension 'Renamed'",
        "Edited private extension 'Renamed' (notes.example.com)",
        "Enabled private extension 'Notes'",
        "Disabled private extension 'Notes'",
        "Added private extension 'Notes' (notes.example.com)",
    ]
    assert not any("abc123" in m or "s3cret-value" in m for m in logged)
