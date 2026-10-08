"""Private extensions on a turn: only the caller's enabled ones go to the agent,
the browser cannot name one, notices reach the watcher, and a private tool asks."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from src.services.turns import TurnOptions
from tests.conftest import FakeAgent, FakeEmailSender
from tests.test_admin import login, make_member
from tests.test_registration import as_admin
from tests.test_turns import chat, events, new_id, start, wait_until

URL = "/api/user-extensions"


def add(client: TestClient, label: str, url: str, **extra):
    response = client.post(URL, json={"label": label, "url": url, **extra})
    assert response.status_code == 201, response.text
    return response


def finished(client: TestClient, chat_id: str) -> list[dict]:
    wait_until(lambda: chat(client, chat_id)["running"] is False)
    return events(client, chat_id)


def test_only_the_callers_enabled_extensions_are_sent(client_factory, email: FakeEmailSender, agent: FakeAgent) -> None:
    alice = client_factory()
    make_member(alice, email)
    make_member(alice, email, "bob")
    login(alice, "alice")
    add(alice, "Notes", "https://notes.example.com/mcp", headers={"X-Key": "s3cret"})
    add(alice, "Off", "https://off.example.com/mcp")
    alice.patch(f"{URL}/off", json={"enabled": False})
    bob = client_factory()
    login(bob, "bob")
    add(bob, "Bobs", "https://bob.example.com/mcp")

    chat_id = new_id()
    assert start(alice, chat_id).status_code == 202
    finished(alice, chat_id)

    assert agent.asks[-1]["private_extensions"] == [
        {"id": "notes", "label": "Notes", "url": "https://notes.example.com/mcp", "headers": {"X-Key": "s3cret"}}
    ]


def test_a_turn_without_private_extensions_sends_none(client: TestClient, agent: FakeAgent) -> None:
    as_admin(client)
    chat_id = new_id()

    start(client, chat_id)
    finished(client, chat_id)

    assert not agent.asks[-1]["private_extensions"]


def test_the_browser_cannot_name_an_extension_for_a_turn(client: TestClient, agent: FakeAgent) -> None:
    as_admin(client)
    chat_id = new_id()

    start(client, chat_id, private_extensions=[{"id": "evil", "label": "x", "url": "http://10.0.0.5/mcp", "headers": {}}])
    finished(client, chat_id)

    assert not agent.asks[-1]["private_extensions"]


def test_what_the_agent_could_not_connect_to_reaches_the_watcher_as_a_notice(client: TestClient, agent: FakeAgent) -> None:
    as_admin(client)
    add(client, "Notes", "https://notes.example.com/mcp")
    notices = [{"id": "notes", "label": "Notes", "error": "Timed out"}]
    agent.result_extra = {"private_extension_errors": notices}
    chat_id = new_id()

    start(client, chat_id)
    stream = finished(client, chat_id)

    assert [e["notices"] for e in stream if e["type"] == "notice"] == [notices]


def test_no_notice_when_everything_connected(client: TestClient, agent: FakeAgent) -> None:
    as_admin(client)
    add(client, "Notes", "https://notes.example.com/mcp")
    chat_id = new_id()

    start(client, chat_id)

    assert not [e for e in finished(client, chat_id) if e["type"] == "notice"]


def test_an_extension_whose_headers_cannot_be_read_is_left_out_with_a_notice(
    client: TestClient, agent: FakeAgent, tmp_path: Path
) -> None:
    as_admin(client)
    add(client, "Notes", "https://notes.example.com/mcp", headers={"X-Key": "one"})
    add(client, "Wiki", "https://wiki.example.com/mcp")
    with sqlite3.connect(tmp_path / "data" / "test.db") as conn:
        conn.execute("UPDATE user_extensions SET headers_encrypted = 'garbage' WHERE slug = 'notes'")
    chat_id = new_id()

    start(client, chat_id)
    stream = finished(client, chat_id)

    assert [e["id"] for e in agent.asks[-1]["private_extensions"]] == ["wiki"]
    notice = next(e for e in stream if e["type"] == "notice")
    assert notice["notices"][0]["id"] == "notes"
    assert "can't be read" in notice["notices"][0]["error"]


def test_a_private_tool_asks_even_when_ask_before_tools_is_off(client: TestClient, agent: FakeAgent) -> None:
    as_admin(client)
    add(client, "Notes", "https://notes.example.com/mcp")
    agent.tool_calls = ["u_notes__search"]
    chat_id = new_id()

    start(client, chat_id)  # no ask_before_tools
    wait_until(lambda: agent._waiting)
    assert agent.ran == []

    decided = client.post(f"/api/chats/{chat_id}/approvals", json={"step_id": "step0", "decision": "allow"})
    assert decided.status_code == 200
    finished(client, chat_id)

    assert agent.ran == ["u_notes__search"]


def test_turn_options_never_show_header_values_in_repr() -> None:
    options = TurnOptions(private_extensions=({"id": "notes", "label": "N", "url": "u", "headers": {"X-Key": "s3cret"}},))

    assert "s3cret" not in repr(options)
