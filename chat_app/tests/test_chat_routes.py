"""Chat route tests.

``run_chat`` is patched at ``chat_app.routes.chat.run_chat`` - that's where
the name lives after ``from chat_app.services.openai_service import
run_chat``, not at its original definition site. Patching the definition
site wouldn't affect the reference the route module already holds.
"""

from __future__ import annotations

from unittest.mock import patch


def test_chat_page_loads(client):
    response = client.get("/chat")
    assert response.status_code == 200


def test_api_chat_rejects_empty_question(client):
    response = client.post("/api/chat", json={"question": "   "})

    assert response.status_code == 200
    assert response.get_json() == {"response": "Please enter a question."}


def test_api_chat_returns_run_chat_result(client):
    with patch("chat_app.routes.chat.run_chat") as mock_run_chat:
        mock_run_chat.return_value = {
            "response": "E4G is running normally.",
            "tools_used": ["get_sap_system_health"],
        }
        response = client.post("/api/chat", json={"question": "how is E4G doing?", "history": []})

    assert response.status_code == 200
    assert response.get_json() == {
        "response": "E4G is running normally.",
        "tools_used": ["get_sap_system_health"],
    }
    mock_run_chat.assert_called_once_with("how is E4G doing?", [])


def test_api_chat_reports_missing_api_key_without_crashing(client):
    with patch("chat_app.routes.chat.run_chat", side_effect=ValueError("OPENAI_API_KEY not configured")):
        response = client.post("/api/chat", json={"question": "hello"})

    assert response.status_code == 200
    assert "OPENAI_API_KEY not configured" in response.get_json()["response"]


def test_api_chat_catches_unexpected_errors(client):
    with patch("chat_app.routes.chat.run_chat", side_effect=RuntimeError("MCP server unreachable")):
        response = client.post("/api/chat", json={"question": "hello"})

    assert response.status_code == 200
    assert "MCP server unreachable" in response.get_json()["response"]
