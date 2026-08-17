"""Chat route tests.

``router.run_chat`` is patched at its own definition site
(``chat_app.services.llm.router.run_chat``) because ``routes/chat.py``
does ``from chat_app.services.llm import router`` - a module import, not a
name import. It looks up ``.run_chat`` on the ``router`` module object at
call time, so patching that attribute (wherever you spell the path to the
same module object) takes effect; there's no separate "copied reference"
to worry about the way there was with the old ``from ... import run_chat``
style.
"""

from __future__ import annotations

import json
import urllib.error
from unittest.mock import patch

import pytest

from chat_app.chats import store as chats_store
from chat_app.services.llm.base import ChatResult, RecursiveRoundRecord, ToolCallRecord


@pytest.fixture
def client(client, monkeypatch):
    """Login is mandatory app-wide with no unconfigured fallback (see
    security.py), so every test below needs a real session to reach the
    page/API at all. Overrides conftest.py's plain client with one that's
    already logged in as an always-full-access admin - the tests here are
    about the chat page/API's own behavior, not about login/RBAC itself
    (that's test_auth_routes.py/test_account_routes.py's job)."""
    monkeypatch.setenv("ADMIN_USERNAME", "test-admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "test-admin-pw-1")
    client.post("/login", data={"username": "test-admin", "password": "test-admin-pw-1"})
    return client


def test_chat_page_loads(client):
    response = client.get("/chat")
    assert response.status_code == 200


def test_api_chat_rejects_empty_question(client):
    response = client.post("/api/chat", json={"question": "   "})

    assert response.status_code == 200
    assert response.get_json() == {"response": "Please enter a question."}


def test_api_chat_returns_run_chat_result(client, chats_db):
    with patch("chat_app.services.llm.router.run_chat") as mock_run_chat:
        mock_run_chat.return_value = ChatResult(
            response="web-1 is running normally.",
            tools_used=["get_host_health"],
            provider_id="claude",
            model="claude-opus-4-8",
            total_tokens=1234,
        )
        response = client.post(
            "/api/chat",
            json={"question": "how is web-1 doing?", "history": [], "provider": "claude", "model": "claude-opus-4-8"},
        )

    assert response.status_code == 200
    body = response.get_json()
    assert body["response"] == "web-1 is running normally."
    assert body["tools_used"] == ["get_host_health"]
    assert body["provider_id"] == "claude"
    assert body["model"] == "claude-opus-4-8"
    assert body["total_tokens"] == 1234
    assert body["elapsed_seconds"] >= 0
    assert body["chat_id"] is not None  # Now persisted
    # enabled_extensions omitted from the request body -> defaults to [],
    # same as history/provider/model already do.
    mock_run_chat.assert_called_once_with("how is web-1 doing?", [], "claude", "claude-opus-4-8", [])


def test_api_chat_reports_and_persists_recursive_round_count_only(client, chats_db, log_dir):
    """The response JSON and the saved chats.db transcript carry just the
    COUNT (for the chat UI's compact meta line); each round's own answer
    text is a session_log-only detail - see chat_api's assistant_entry
    comment for why."""
    with patch("chat_app.services.llm.router.run_chat") as mock_run_chat:
        mock_run_chat.return_value = ChatResult(
            response="final answer",
            provider_id="ollama",
            model="phi4-mini:latest",
            recursive_rounds=[
                RecursiveRoundRecord(round=1, response="draft", converged=False),
                RecursiveRoundRecord(round=2, response="final answer", converged=True),
            ],
        )
        response = client.post("/api/chat", json={"question": "hello"})

    body = response.get_json()
    assert body["recursive_rounds"] == 2

    chat_id = body["chat_id"]
    saved = chats_store.get_chat(chats_db, "test-admin", chat_id)
    assert saved["messages"][-1]["recursive_rounds"] == 2

    log_file = log_dir / "chats" / "test-admin" / f"{chat_id}.jsonl"
    entry = json.loads(log_file.read_text(encoding="utf-8").strip())
    assert entry["recursive_rounds"] == [
        {"round": 1, "response": "draft", "converged": False},
        {"round": 2, "response": "final answer", "converged": True},
    ]


def test_api_chat_omits_recursive_rounds_when_none_happened(client, chats_db, log_dir):
    with patch("chat_app.services.llm.router.run_chat") as mock_run_chat:
        mock_run_chat.return_value = ChatResult(response="ok", provider_id="openai")
        response = client.post("/api/chat", json={"question": "hello"})

    body = response.get_json()
    assert body["recursive_rounds"] == 0

    saved = chats_store.get_chat(chats_db, "test-admin", body["chat_id"])
    assert "recursive_rounds" not in saved["messages"][-1]


def test_api_chat_writes_a_session_log_entry_with_tool_call_detail(client, chats_db, log_dir):
    with patch("chat_app.services.llm.router.run_chat") as mock_run_chat:
        mock_run_chat.return_value = ChatResult(
            response="web-1 is running normally.",
            tools_used=["get_host_health"],
            tool_calls=[ToolCallRecord(name="get_host_health", arguments={"name": "web-1"}, result="cpu 12%")],
            provider_id="claude",
            model="claude-opus-4-8",
            total_tokens=1234,
        )
        response = client.post(
            "/api/chat",
            json={"question": "how is web-1 doing?", "history": [], "provider": "claude", "model": "claude-opus-4-8"},
        )

    chat_id = response.get_json()["chat_id"]
    log_file = log_dir / "chats" / "test-admin" / f"{chat_id}.jsonl"
    assert log_file.exists()
    entry = json.loads(log_file.read_text(encoding="utf-8").strip())
    assert entry["question"] == "how is web-1 doing?"
    assert entry["response"] == "web-1 is running normally."
    assert entry["provider_id"] == "claude"
    assert entry["model"] == "claude-opus-4-8"
    assert entry["tool_calls"] == [{"name": "get_host_health", "arguments": {"name": "web-1"}, "result": "cpu 12%"}]
    assert entry["elapsed_seconds"] >= 0


def test_api_chat_includes_total_tokens_as_null_when_provider_did_not_report_it(client, chats_db):
    """total_tokens defaults to None on ChatResult - the frontend treats a
    null (or missing) total_tokens the same way: hide the token display."""
    with patch("chat_app.services.llm.router.run_chat") as mock_run_chat:
        mock_run_chat.return_value = ChatResult(response="ok", provider_id="openai")
        response = client.post("/api/chat", json={"question": "hello"})

    assert response.status_code == 200
    body = response.get_json()
    assert "total_tokens" in body
    assert body["total_tokens"] is None


def test_api_chat_defaults_provider_and_model_to_none_when_omitted(client, chats_db):
    with patch("chat_app.services.llm.router.run_chat") as mock_run_chat:
        mock_run_chat.return_value = ChatResult(response="ok", provider_id="openai")
        client.post("/api/chat", json={"question": "hello"})

    # router.run_chat itself applies the "auto" default and resolves it to
    # a real provider - the route just passes through whatever (or
    # nothing) the client sent, unchanged.
    mock_run_chat.assert_called_once_with("hello", [], None, None, [])


def test_api_chat_forwards_enabled_extensions_to_router(client, chats_db):
    with patch("chat_app.services.llm.router.run_chat") as mock_run_chat:
        mock_run_chat.return_value = ChatResult(response="ok", provider_id="openai")
        client.post(
            "/api/chat",
            json={"question": "hello", "enabled_extensions": ["reference"]},
        )

    mock_run_chat.assert_called_once_with("hello", [], None, None, ["reference"])


def test_api_chat_reports_missing_api_key_without_crashing(client, chats_db):
    with patch("chat_app.services.llm.router.run_chat", side_effect=ValueError("ANTHROPIC_API_KEY not configured")):
        response = client.post("/api/chat", json={"question": "hello", "provider": "claude"})

    assert response.status_code == 200
    assert "ANTHROPIC_API_KEY not configured" in response.get_json()["response"]


def test_api_chat_catches_unexpected_errors(client, chats_db):
    with patch("chat_app.services.llm.router.run_chat", side_effect=RuntimeError("MCP server unreachable")):
        response = client.post("/api/chat", json={"question": "hello"})

    assert response.status_code == 200
    assert "Something went wrong" in response.get_json()["response"]


def test_api_chat_does_not_leak_unexpected_exception_text(client, chats_db, caplog):
    """An unplanned exception's text is written for a traceback reader -
    paths, hostnames, sometimes credentials - and this response goes into
    a chat transcript and back to the model. The detail belongs in the
    log, reachable by the reference id shown to the user."""
    boom = RuntimeError("connect failed: postgres://admin:hunter2@10.0.0.5:5432")
    with patch("chat_app.services.llm.router.run_chat", side_effect=boom):
        response = client.post("/api/chat", json={"question": "hello"})

    body = response.get_json()["response"]
    assert "hunter2" not in body
    assert "10.0.0.5" not in body
    # ...but it is recoverable, via the reference the user is given.
    reference = body.rsplit("reference ", 1)[1].rstrip(".")
    assert reference in caplog.text
    assert "hunter2" in caplog.text


def test_api_chat_still_shows_curated_provider_errors_verbatim(client, chats_db):
    """Messages the router wrote for a human ("Claude is not configured")
    contain no internals and are far more useful than a reference id."""
    with patch(
        "chat_app.services.llm.router.run_chat",
        side_effect=ValueError("Claude is not configured (missing API key)"),
    ):
        response = client.post("/api/chat", json={"question": "hello"})

    assert "Claude is not configured (missing API key)" in response.get_json()["response"]


def test_api_providers_reflects_availability(client, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    response = client.get("/api/providers")

    assert response.status_code == 200
    data = {p["id"]: p["available"] for p in response.get_json()}
    # "auto" is available too here, since at least one real provider (openai) is.
    # "ollama" is always True - no API key needed, see ollama_provider.py.
    assert data == {"auto": True, "openai": True, "claude": False, "ollama": True}


def test_api_extensions_proxies_mcp_server_catalog(client):
    """mcp_server's /extensions endpoint isn't built yet (see the
    contract this was built against) - fetch_extensions() is mocked here
    rather than exercised against a live server."""
    fake_extensions = [
        {
            "id": "reference",
            "label": "Reference Extension (dev fixture)",
            "description": "A dev fixture extension.",
            "status": "connected",
            "error": None,
            "tools": ["reference__echo", "reference__add"],
        }
    ]
    with patch("chat_app.pages.chat.routes.fetch_extensions", return_value=fake_extensions):
        response = client.get("/api/extensions")

    assert response.status_code == 200
    assert response.get_json() == {"extensions": fake_extensions, "error": None}


def test_api_extensions_returns_empty_list_with_error_when_mcp_server_unreachable(client):
    """Mirrors capabilities/routes.py's browse(): an unreachable
    mcp_server surfaces as a 200 with an empty list and an error field,
    not a 500 - this endpoint is polled every 15s by the sidebar and a
    transient failure shouldn't crash the page or the poll loop."""
    with patch(
        "chat_app.pages.chat.routes.fetch_extensions",
        side_effect=ConnectionError("connection refused"),
    ):
        response = client.get("/api/extensions")

    assert response.status_code == 200
    body = response.get_json()
    assert body["extensions"] == []
    assert "connection refused" in body["error"]


def _http_error(code, message):
    import json
    from io import BytesIO

    return urllib.error.HTTPError(
        url="http://127.0.0.1:8010/extensions",
        code=code,
        msg="error",
        hdrs=None,
        fp=BytesIO(json.dumps({"error": message}).encode("utf-8")),
    )


def test_add_extension_api_creates_extension_on_success(client):
    created = {
        "id": "reference",
        "label": "Reference",
        "description": "",
        "status": "connected",
        "error": None,
        "tools": [],
    }
    with patch("chat_app.pages.chat.routes.add_extension", return_value=created) as mock_add:
        response = client.post(
            "/api/extensions",
            json={"label": "Reference", "url": "http://example.com/mcp"},
        )

    assert response.status_code == 201
    assert response.get_json() == created
    mock_add.assert_called_once_with("Reference", "http://example.com/mcp", "")


def test_add_extension_api_rejects_missing_label(client):
    with patch("chat_app.pages.chat.routes.add_extension") as mock_add:
        response = client.post("/api/extensions", json={"label": "  ", "url": "http://example.com/mcp"})

    assert response.status_code == 400
    assert "required" in response.get_json()["error"]
    mock_add.assert_not_called()


def test_add_extension_api_rejects_missing_url(client):
    with patch("chat_app.pages.chat.routes.add_extension") as mock_add:
        response = client.post("/api/extensions", json={"label": "Reference", "url": ""})

    assert response.status_code == 400
    assert "required" in response.get_json()["error"]
    mock_add.assert_not_called()


def test_add_extension_api_forwards_mcp_server_validation_error(client):
    with patch("chat_app.pages.chat.routes.add_extension", side_effect=_http_error(400, "url must be http(s)")):
        response = client.post(
            "/api/extensions",
            json={"label": "Reference", "url": "not-a-url"},
        )

    assert response.status_code == 400
    assert response.get_json() == {"error": "url must be http(s)"}


def test_add_extension_api_reports_unreachable_mcp_server_as_502(client):
    with patch("chat_app.pages.chat.routes.add_extension", side_effect=ConnectionError("connection refused")):
        response = client.post(
            "/api/extensions",
            json={"label": "Reference", "url": "http://example.com/mcp"},
        )

    assert response.status_code == 502
    assert "connection refused" in response.get_json()["error"]


def test_remove_extension_api_deletes_on_success(client):
    with patch("chat_app.pages.chat.routes.remove_extension", return_value=None) as mock_remove:
        response = client.delete("/api/extensions/reference")

    assert response.status_code == 204
    assert response.data == b""
    mock_remove.assert_called_once_with("reference")


def test_remove_extension_api_forwards_mcp_server_not_found(client):
    with patch("chat_app.pages.chat.routes.remove_extension", side_effect=_http_error(404, "unknown extension id")):
        response = client.delete("/api/extensions/unknown")

    assert response.status_code == 404
    assert response.get_json() == {"error": "unknown extension id"}


def test_remove_extension_api_reports_unreachable_mcp_server_as_502(client):
    with patch("chat_app.pages.chat.routes.remove_extension", side_effect=ConnectionError("connection refused")):
        response = client.delete("/api/extensions/reference")

    assert response.status_code == 502
    assert "connection refused" in response.get_json()["error"]


def test_api_chat_creates_a_new_chat_and_returns_its_id(client, chats_db):
    with patch("chat_app.services.llm.router.run_chat") as mock_run_chat:
        mock_run_chat.return_value = ChatResult(response="hi there", provider_id="openai")
        response = client.post("/api/chat", json={"question": "hello"})

    body = response.get_json()
    assert body["chat_id"]
    saved = chats_store.get_chat(chats_db, "test-admin", body["chat_id"])
    assert saved["messages"][0] == {"role": "user", "content": "hello"}
    assistant_msg = saved["messages"][1]
    elapsed = assistant_msg.pop("elapsed_seconds")
    assert elapsed >= 0
    assert assistant_msg == {"role": "assistant", "content": "hi there", "provider_id": "openai"}
    assert saved["title"] == "hello"


def test_api_chat_with_chat_id_updates_the_existing_chat(client, chats_db):
    existing_id = chats_store.save_chat(
        chats_db, "test-admin", None, [{"role": "user", "content": "first"}]
    )

    with patch("chat_app.services.llm.router.run_chat") as mock_run_chat:
        mock_run_chat.return_value = ChatResult(response="second reply", provider_id="openai")
        response = client.post(
            "/api/chat",
            json={"question": "second question", "history": [{"role": "user", "content": "first"}], "chat_id": existing_id},
        )

    body = response.get_json()
    assert body["chat_id"] == existing_id
    saved = chats_store.get_chat(chats_db, "test-admin", existing_id)
    assert saved["messages"][:2] == [
        {"role": "user", "content": "first"},
        {"role": "user", "content": "second question"},
    ]
    assistant_msg = saved["messages"][2]
    del assistant_msg["elapsed_seconds"]
    assert assistant_msg == {"role": "assistant", "content": "second reply", "provider_id": "openai"}


def test_api_chat_does_not_duplicate_the_question_when_history_already_includes_it(client, chats_db):
    """script.js's send() sends a `priorHistory` snapshot that never
    includes the current question, but /api/chat is a public JSON API -
    some other caller might send `history` already ending with the
    current question. The saved transcript must still contain that
    question exactly once, not twice."""
    with patch("chat_app.services.llm.router.run_chat") as mock_run_chat:
        mock_run_chat.return_value = ChatResult(response="second reply", provider_id="openai")
        response = client.post(
            "/api/chat",
            json={
                "question": "second question",
                "history": [
                    {"role": "user", "content": "first"},
                    {"role": "user", "content": "second question"},
                ],
            },
        )

    body = response.get_json()
    saved = chats_store.get_chat(chats_db, "test-admin", body["chat_id"])
    assert saved["messages"][:2] == [
        {"role": "user", "content": "first"},
        {"role": "user", "content": "second question"},
    ]
    assistant_msg = saved["messages"][2]
    del assistant_msg["elapsed_seconds"]
    assert assistant_msg == {"role": "assistant", "content": "second reply", "provider_id": "openai"}


def test_api_chat_persists_the_turn_even_when_the_provider_errors(client, chats_db):
    """A curated ValueError still becomes a saved assistant turn - same
    text the user sees in the transcript, so reopening the chat shows
    what happened."""
    with patch(
        "chat_app.services.llm.router.run_chat",
        side_effect=ValueError("Claude is not configured (missing API key)"),
    ):
        response = client.post("/api/chat", json={"question": "hello"})

    body = response.get_json()
    saved = chats_store.get_chat(chats_db, "test-admin", body["chat_id"])
    assert "Claude is not configured" in saved["messages"][-1]["content"]


def test_api_chat_persistence_failure_does_not_break_the_response(client, chats_db):
    with patch("chat_app.services.llm.router.run_chat") as mock_run_chat, \
         patch("chat_app.pages.chat.routes.chats_store.save_chat", side_effect=RuntimeError("disk full")):
        mock_run_chat.return_value = ChatResult(response="hi there", provider_id="openai")
        response = client.post("/api/chat", json={"question": "hello"})

    assert response.status_code == 200
    body = response.get_json()
    assert body["response"] == "hi there"
    assert body["chat_id"] is None


def test_api_chat_with_stale_chat_id_falls_back_to_creating_a_new_chat(client, chats_db):
    """The chat_id the client sent no longer exists (e.g. deleted from
    another tab) - the turn must not be lost, it lands in a fresh chat
    instead."""
    with patch("chat_app.services.llm.router.run_chat") as mock_run_chat:
        mock_run_chat.return_value = ChatResult(response="hi there", provider_id="openai")
        response = client.post("/api/chat", json={"question": "hello", "chat_id": "does-not-exist"})

    body = response.get_json()
    assert body["chat_id"] != "does-not-exist"
    saved = chats_store.get_chat(chats_db, "test-admin", body["chat_id"])
    assert saved["messages"][-1]["content"] == "hi there"


def test_list_chats_api_returns_only_the_current_users_chats(client, chats_db):
    mine = chats_store.save_chat(chats_db, "test-admin", None, [{"role": "user", "content": "mine"}])
    chats_store.save_chat(chats_db, "someone-else", None, [{"role": "user", "content": "not mine"}])

    response = client.get("/api/chats")

    ids = [c["id"] for c in response.get_json()]
    assert ids == [mine]


def test_get_chat_api_returns_the_full_record(client, chats_db):
    chat_id = chats_store.save_chat(chats_db, "test-admin", None, [{"role": "user", "content": "hi"}])

    response = client.get(f"/api/chats/{chat_id}")

    assert response.status_code == 200
    assert response.get_json()["messages"] == [{"role": "user", "content": "hi"}]


def test_get_chat_api_404_for_unknown_id(client, chats_db):
    response = client.get("/api/chats/does-not-exist")

    assert response.status_code == 404


def test_get_chat_api_404_for_a_chat_owned_by_someone_else(client, chats_db):
    chat_id = chats_store.save_chat(chats_db, "someone-else", None, [{"role": "user", "content": "hi"}])

    response = client.get(f"/api/chats/{chat_id}")

    assert response.status_code == 404


def test_rename_chat_api_updates_the_title(client, chats_db):
    chat_id = chats_store.save_chat(chats_db, "test-admin", None, [{"role": "user", "content": "hi"}])

    response = client.patch(f"/api/chats/{chat_id}", json={"title": "New title"})

    assert response.status_code == 204
    assert chats_store.get_chat(chats_db, "test-admin", chat_id)["title"] == "New title"


def test_rename_chat_api_rejects_a_blank_title(client, chats_db):
    chat_id = chats_store.save_chat(chats_db, "test-admin", None, [{"role": "user", "content": "hi"}])

    response = client.patch(f"/api/chats/{chat_id}", json={"title": "   "})

    assert response.status_code == 400


def test_rename_chat_api_404_for_unknown_id(client, chats_db):
    response = client.patch("/api/chats/does-not-exist", json={"title": "New title"})

    assert response.status_code == 404


def test_rename_chat_api_404_for_a_chat_owned_by_someone_else(client, chats_db):
    chat_id = chats_store.save_chat(chats_db, "someone-else", None, [{"role": "user", "content": "hi"}])

    response = client.patch(f"/api/chats/{chat_id}", json={"title": "Hijacked"})

    assert response.status_code == 404
    assert chats_store.get_chat(chats_db, "someone-else", chat_id)["title"] != "Hijacked"


def test_delete_chat_api_removes_the_chat(client, chats_db):
    chat_id = chats_store.save_chat(chats_db, "test-admin", None, [{"role": "user", "content": "hi"}])

    response = client.delete(f"/api/chats/{chat_id}")

    assert response.status_code == 204
    assert chats_store.get_chat(chats_db, "test-admin", chat_id) is None


def test_delete_chat_api_404_for_unknown_id(client, chats_db):
    response = client.delete("/api/chats/does-not-exist")

    assert response.status_code == 404


def test_delete_chat_api_404_for_a_chat_owned_by_someone_else(client, chats_db):
    chat_id = chats_store.save_chat(chats_db, "someone-else", None, [{"role": "user", "content": "hi"}])

    response = client.delete(f"/api/chats/{chat_id}")

    assert response.status_code == 404
    assert chats_store.get_chat(chats_db, "someone-else", chat_id) is not None