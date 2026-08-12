"""Capabilities browser tests.

Fake tools/resources use SimpleNamespace to match the shapes the real MCP
SDK's ``Tool``/``ResourceTemplate`` objects have, without depending on the
SDK being importable or a server being up.

``browse()`` calls both ``_serialize_tools()`` and ``_serialize_resources()``
inside the same try block, so any test exercising it needs BOTH
``list_tools`` and ``list_resource_templates`` patched - leaving one
unpatched means it attempts a real (failing) network call, which the
except clause catches and silently resets *both* tools and resources to
empty, not just the one that actually failed.
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


def _fake_resource_template(
    name="job_history_resource",
    description="Recent background job execution history.",
    uri_template="sap://job-history/{sid}",
):
    return SimpleNamespace(name=name, description=description, uriTemplate=uri_template)


def test_browse_renders_live_tool_list(client):
    with patch("chat_app.pages.capabilities.routes.list_tools", return_value=[_fake_tool()]), \
         patch("chat_app.pages.capabilities.routes.list_resource_templates", return_value=[]):
        response = client.get("/capabilities/")

    assert response.status_code == 200
    assert b"stop_sap_system_tool" in response.data


def test_browse_shows_connection_error_instead_of_crashing(client):
    with patch("chat_app.pages.capabilities.routes.list_tools", side_effect=ConnectionError("connection refused")), \
         patch("chat_app.pages.capabilities.routes.list_resource_templates", return_value=[]):
        response = client.get("/capabilities/")

    assert response.status_code == 200
    assert b"connection refused" in response.data


def test_browse_shows_resources_error_without_hiding_successfully_loaded_tools(client):
    """The two sections now fail independently - a broken resources fetch
    must not discard tools that loaded fine, and vice versa."""
    with patch("chat_app.pages.capabilities.routes.list_tools", return_value=[_fake_tool()]), \
         patch("chat_app.pages.capabilities.routes.list_resource_templates", side_effect=ConnectionError("resource fetch failed")):
        response = client.get("/capabilities/")

    assert response.status_code == 200
    assert b"resource fetch failed" in response.data
    assert b"stop_sap_system_tool" in response.data  # tools still rendered


def test_api_tools_returns_reshaped_json(client):
    with patch("chat_app.pages.capabilities.routes.list_tools", return_value=[_fake_tool()]):
        response = client.get("/capabilities/api/tools")

    assert response.status_code == 200
    assert response.get_json() == [
        {
            "name": "stop_sap_system_tool",
            "title": "Stop SAP System",
            "description": "Stop a SAP system by SID.",
            "input_schema": {"type": "object", "properties": {"sid": {"type": "string"}}},
        }
    ]


def test_browse_renders_friendly_title_not_just_raw_name(client):
    with patch("chat_app.pages.capabilities.routes.list_tools", return_value=[_fake_tool()]), \
         patch("chat_app.pages.capabilities.routes.list_resource_templates", return_value=[]):
        response = client.get("/capabilities/")

    assert response.status_code == 200
    assert b"Stop SAP System" in response.data
    # the raw machine name should still appear somewhere (it's what the
    # try-it console actually POSTs to), just not as the heading anymore
    assert b"stop_sap_system_tool" in response.data


def test_try_tool_calls_through_and_returns_result(client):
    with patch("chat_app.pages.capabilities.routes.call_tool", return_value="E4G stopped successfully") as mock_call:
        response = client.post("/capabilities/api/try/stop_sap_system_tool", json={"sid": "E4G"})

    assert response.status_code == 200
    assert response.get_json() == {"status": "ok", "result": "E4G stopped successfully"}
    mock_call.assert_called_once_with("stop_sap_system_tool", {"sid": "E4G"})


def test_try_tool_failure_returns_500_with_message(client):
    with patch("chat_app.pages.capabilities.routes.call_tool", side_effect=RuntimeError("MCP server down")):
        response = client.post("/capabilities/api/try/stop_sap_system_tool", json={"sid": "E4G"})

    assert response.status_code == 500
    assert response.get_json() == {"status": "error", "message": "MCP server down"}


def test_try_tool_with_no_body_sends_empty_arguments(client):
    with patch("chat_app.pages.capabilities.routes.call_tool", return_value="ok") as mock_call:
        client.post("/capabilities/api/try/get_available_sids", json={})

    mock_call.assert_called_once_with("get_available_sids", {})


def test_api_resources_returns_reshaped_json_with_extracted_params(client):
    with patch("chat_app.pages.capabilities.routes.list_resource_templates", return_value=[_fake_resource_template()]):
        response = client.get("/capabilities/api/resources")

    assert response.status_code == 200
    assert response.get_json() == [
        {
            "name": "job_history_resource",
            "title": "Job History",
            "description": "Recent background job execution history.",
            "uri_template": "sap://job-history/{sid}",
            "params": ["sid"],
        }
    ]


def test_browse_renders_resource_section(client):
    with patch("chat_app.pages.capabilities.routes.list_tools", return_value=[]), \
         patch("chat_app.pages.capabilities.routes.list_resource_templates", return_value=[_fake_resource_template()]):
        response = client.get("/capabilities/")

    assert response.status_code == 200
    assert b"Job History" in response.data
    assert b"sap://job-history/{sid}" in response.data


def test_read_resource_calls_through_and_returns_result(client):
    with patch("chat_app.pages.capabilities.routes.read_resource", return_value='{"sid": "E4G", "jobs": []}') as mock_read:
        response = client.post("/capabilities/api/read-resource", json={"uri": "sap://job-history/E4G"})

    assert response.status_code == 200
    assert response.get_json() == {"status": "ok", "result": '{"sid": "E4G", "jobs": []}'}
    mock_read.assert_called_once_with("sap://job-history/E4G")


def test_read_resource_failure_returns_500(client):
    with patch("chat_app.pages.capabilities.routes.read_resource", side_effect=RuntimeError("MCP server down")):
        response = client.post("/capabilities/api/read-resource", json={"uri": "sap://job-history/E4G"})

    assert response.status_code == 500
    assert response.get_json() == {"status": "error", "message": "MCP server down"}


def test_read_resource_missing_uri_returns_400(client):
    response = client.post("/capabilities/api/read-resource", json={})

    assert response.status_code == 400
    assert response.get_json() == {"status": "error", "message": "Missing uri"}
