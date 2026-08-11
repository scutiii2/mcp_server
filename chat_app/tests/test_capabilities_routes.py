"""Capabilities browser tests.

Fake tools use SimpleNamespace to match the shape the real MCP SDK's
``Tool`` objects have (``.name``, ``.description``, ``.inputSchema``)
without depending on the SDK being importable or a server being up.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch


def _fake_tool(name="stop_sap_system_tool", description="Stop a SAP system by SID."):
    return SimpleNamespace(
        name=name,
        description=description,
        inputSchema={"type": "object", "properties": {"sid": {"type": "string"}}},
    )


def test_browse_renders_live_tool_list(client):
    with patch("chat_app.routes.capabilities.list_tools", return_value=[_fake_tool()]):
        response = client.get("/capabilities/")

    assert response.status_code == 200
    assert b"stop_sap_system_tool" in response.data


def test_browse_shows_connection_error_instead_of_crashing(client):
    with patch("chat_app.routes.capabilities.list_tools", side_effect=ConnectionError("connection refused")):
        response = client.get("/capabilities/")

    assert response.status_code == 200
    assert b"connection refused" in response.data


def test_api_tools_returns_reshaped_json(client):
    with patch("chat_app.routes.capabilities.list_tools", return_value=[_fake_tool()]):
        response = client.get("/capabilities/api/tools")

    assert response.status_code == 200
    assert response.get_json() == [
        {
            "name": "stop_sap_system_tool",
            "description": "Stop a SAP system by SID.",
            "input_schema": {"type": "object", "properties": {"sid": {"type": "string"}}},
        }
    ]


def test_try_tool_calls_through_and_returns_result(client):
    with patch("chat_app.routes.capabilities.call_tool", return_value="E4G stopped successfully") as mock_call:
        response = client.post("/capabilities/api/try/stop_sap_system_tool", json={"sid": "E4G"})

    assert response.status_code == 200
    assert response.get_json() == {"status": "ok", "result": "E4G stopped successfully"}
    mock_call.assert_called_once_with("stop_sap_system_tool", {"sid": "E4G"})


def test_try_tool_failure_returns_500_with_message(client):
    with patch("chat_app.routes.capabilities.call_tool", side_effect=RuntimeError("MCP server down")):
        response = client.post("/capabilities/api/try/stop_sap_system_tool", json={"sid": "E4G"})

    assert response.status_code == 500
    assert response.get_json() == {"status": "error", "message": "MCP server down"}


def test_try_tool_with_no_body_sends_empty_arguments(client):
    with patch("chat_app.routes.capabilities.call_tool", return_value="ok") as mock_call:
        client.post("/capabilities/api/try/get_available_sids", json={})

    mock_call.assert_called_once_with("get_available_sids", {})
