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

import urllib.error
from unittest.mock import patch

from chat_app.services.llm.base import ChatResult


def test_chat_page_loads(client):
    response = client.get("/chat")
    assert response.status_code == 200


def test_api_chat_rejects_empty_question(client):
    response = client.post("/api/chat", json={"question": "   "})

    assert response.status_code == 200
    assert response.get_json() == {"response": "Please enter a question."}


def test_api_chat_returns_run_chat_result(client):
    with patch("chat_app.services.llm.router.run_chat") as mock_run_chat:
        mock_run_chat.return_value = ChatResult(
            response="web-1 is running normally.",
            tools_used=["get_host_health"],
            provider_id="claude",
            total_tokens=1234,
        )
        response = client.post(
            "/api/chat",
            json={"question": "how is web-1 doing?", "history": [], "provider": "claude", "model": "claude-opus-4-8"},
        )

    assert response.status_code == 200
    assert response.get_json() == {
        "response": "web-1 is running normally.",
        "tools_used": ["get_host_health"],
        "provider_id": "claude",
        "total_tokens": 1234,
    }
    # enabled_extensions omitted from the request body -> defaults to [],
    # same as history/provider/model already do.
    mock_run_chat.assert_called_once_with("how is web-1 doing?", [], "claude", "claude-opus-4-8", [])


def test_api_chat_includes_total_tokens_as_null_when_provider_did_not_report_it(client):
    """total_tokens defaults to None on ChatResult - the frontend treats a
    null (or missing) total_tokens the same way: hide the token display."""
    with patch("chat_app.services.llm.router.run_chat") as mock_run_chat:
        mock_run_chat.return_value = ChatResult(response="ok", provider_id="openai")
        response = client.post("/api/chat", json={"question": "hello"})

    assert response.status_code == 200
    body = response.get_json()
    assert "total_tokens" in body
    assert body["total_tokens"] is None


def test_api_chat_defaults_provider_and_model_to_none_when_omitted(client):
    with patch("chat_app.services.llm.router.run_chat") as mock_run_chat:
        mock_run_chat.return_value = ChatResult(response="ok", provider_id="openai")
        client.post("/api/chat", json={"question": "hello"})

    # router.run_chat itself applies the "auto" default and resolves it to
    # a real provider - the route just passes through whatever (or
    # nothing) the client sent, unchanged.
    mock_run_chat.assert_called_once_with("hello", [], None, None, [])


def test_api_chat_forwards_enabled_extensions_to_router(client):
    with patch("chat_app.services.llm.router.run_chat") as mock_run_chat:
        mock_run_chat.return_value = ChatResult(response="ok", provider_id="openai")
        client.post(
            "/api/chat",
            json={"question": "hello", "enabled_extensions": ["reference"]},
        )

    mock_run_chat.assert_called_once_with("hello", [], None, None, ["reference"])


def test_api_chat_reports_missing_api_key_without_crashing(client):
    with patch("chat_app.services.llm.router.run_chat", side_effect=ValueError("ANTHROPIC_API_KEY not configured")):
        response = client.post("/api/chat", json={"question": "hello", "provider": "claude"})

    assert response.status_code == 200
    assert "ANTHROPIC_API_KEY not configured" in response.get_json()["response"]


def test_api_chat_catches_unexpected_errors(client):
    with patch("chat_app.services.llm.router.run_chat", side_effect=RuntimeError("MCP server unreachable")):
        response = client.post("/api/chat", json={"question": "hello"})

    assert response.status_code == 200
    assert "Something went wrong" in response.get_json()["response"]


def test_api_chat_does_not_leak_unexpected_exception_text(client, caplog):
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


def test_api_chat_still_shows_curated_provider_errors_verbatim(client):
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