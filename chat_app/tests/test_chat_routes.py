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
    }
    mock_run_chat.assert_called_once_with("how is web-1 doing?", [], "claude", "claude-opus-4-8")


def test_api_chat_defaults_provider_and_model_to_none_when_omitted(client):
    with patch("chat_app.services.llm.router.run_chat") as mock_run_chat:
        mock_run_chat.return_value = ChatResult(response="ok", provider_id="openai")
        client.post("/api/chat", json={"question": "hello"})

    # router.run_chat itself applies the "auto" default and resolves it to
    # a real provider - the route just passes through whatever (or
    # nothing) the client sent, unchanged.
    mock_run_chat.assert_called_once_with("hello", [], None, None)


def test_api_chat_reports_missing_api_key_without_crashing(client):
    with patch("chat_app.services.llm.router.run_chat", side_effect=ValueError("ANTHROPIC_API_KEY not configured")):
        response = client.post("/api/chat", json={"question": "hello", "provider": "claude"})

    assert response.status_code == 200
    assert "ANTHROPIC_API_KEY not configured" in response.get_json()["response"]


def test_api_chat_catches_unexpected_errors(client):
    with patch("chat_app.services.llm.router.run_chat", side_effect=RuntimeError("MCP server unreachable")):
        response = client.post("/api/chat", json={"question": "hello"})

    assert response.status_code == 200
    assert "MCP server unreachable" in response.get_json()["response"]


def test_api_providers_reflects_availability(client, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    response = client.get("/api/providers")

    assert response.status_code == 200
    data = {p["id"]: p["available"] for p in response.get_json()}
    # "auto" is available too here, since at least one real provider (openai) is.
    # "ollama" is always True - no API key needed, see ollama_provider.py.
    assert data == {"auto": True, "openai": True, "claude": False, "ollama": True}