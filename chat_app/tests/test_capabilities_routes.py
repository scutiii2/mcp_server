"""Capabilities browser tests.

Fake tools/resources use SimpleNamespace to match the shapes the real MCP
SDK's ``Tool``/``ResourceTemplate`` objects have, without depending on the
SDK being importable or a server being up. The fake names below are
placeholders, not references to anything registered - there are no real
capabilities yet, and these tests are about the browser, not the catalog.

``browse()`` calls both ``_serialize_tools()`` and ``_serialize_resources()``
inside the same try block, so any test exercising it needs BOTH
``list_tools`` and ``list_resource_templates`` patched - leaving one
unpatched means it attempts a real (failing) network call, which the
except clause catches and silently resets *both* tools and resources to
empty, not just the one that actually failed.

``_serialize_tools()`` also calls ``fetch_extensions()`` now (to unlock
``list_tools()``'s extension filter for this page - see its docstring),
which is a THIRD thing that makes a real network call if left unpatched.
Rather than repeat that patch in every test below, ``_no_extensions``
patches it file-wide: almost nothing here cares about extensions, so the
default is "none configured," and the one test that does care overrides
it locally.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _no_extensions():
    """Without this, every test below that exercises _serialize_tools()
    makes a real, slow, failing HTTP call from fetch_extensions() - this
    project's test suite has held to zero real network calls throughout,
    and a 10-second timeout per test is also just a bad time to sit
    through. Confirmed the regression this fixture prevents: before
    adding it, this file's 13 tests took ~12s instead of well under 1s."""
    with patch("chat_app.pages.capabilities.routes.fetch_extensions", return_value=[]):
        yield


def _fake_tool(name="restart_service_tool", description="Restart a service on a host."):
    return SimpleNamespace(
        name=name,
        description=description,
        inputSchema={"type": "object", "properties": {"service": {"type": "string"}}},
    )


def _fake_resource_template(
    name="recent_logs_resource",
    description="Recent log lines from a host.",
    uri_template="logs://recent/{host}",
):
    return SimpleNamespace(name=name, description=description, uriTemplate=uri_template)


def test_browse_renders_live_tool_list(client):
    with patch("chat_app.pages.capabilities.routes.list_tools", return_value=[_fake_tool()]), \
         patch("chat_app.pages.capabilities.routes.list_resource_templates", return_value=[]):
        response = client.get("/capabilities/")

    assert response.status_code == 200
    assert b"restart_service_tool" in response.data


def test_browse_shows_connection_error_instead_of_crashing(client):
    with patch("chat_app.pages.capabilities.routes.list_tools", side_effect=ConnectionError("connection refused")), \
         patch("chat_app.pages.capabilities.routes.list_resource_templates", return_value=[]):
        response = client.get("/capabilities/")

    assert response.status_code == 200
    assert b"connection refused" in response.data


def test_browse_shows_resources_error_without_hiding_successfully_loaded_tools(client):
    """The two sections fail independently - a broken resources fetch must
    not discard tools that loaded fine, and vice versa."""
    with patch("chat_app.pages.capabilities.routes.list_tools", return_value=[_fake_tool()]), \
         patch("chat_app.pages.capabilities.routes.list_resource_templates", side_effect=ConnectionError("resource fetch failed")):
        response = client.get("/capabilities/")

    assert response.status_code == 200
    assert b"resource fetch failed" in response.data
    assert b"restart_service_tool" in response.data  # tools still rendered


def test_browse_asks_list_tools_for_every_connected_extension(client):
    """Regression: this page's whole point (see module docstring) is
    showing whatever mcp_server actually has registered right now.
    list_tools()'s own default is "no extension tools" - correct for
    /api/chat, where an unconfigured extension must never be silently in
    scope for the model, but wrong here: a human browsing the catalog
    isn't the chat sidebar's toggle state, and defaulting to empty would
    make this page quietly under-report what's registered."""
    with patch("chat_app.pages.capabilities.routes.fetch_extensions",
               return_value=[{"id": "reference", "status": "connected"}, {"id": "other", "status": "error"}]), \
         patch("chat_app.pages.capabilities.routes.list_resource_templates", return_value=[]), \
         patch("chat_app.pages.capabilities.routes.list_tools") as mock_list_tools:
        mock_list_tools.return_value = [_fake_tool()]
        client.get("/capabilities/")

    mock_list_tools.assert_called_once_with(enabled_extensions=["reference", "other"])


def test_browse_shows_builtin_tools_even_when_extension_status_is_unreachable(client):
    """A broken fetch_extensions() (mcp_server up, but that one call
    failing) must degrade to "no extensions" rather than blanking the
    whole tools section - built-in tools come from a separate call this
    failure has nothing to do with."""
    with patch("chat_app.pages.capabilities.routes.fetch_extensions", side_effect=ConnectionError("boom")), \
         patch("chat_app.pages.capabilities.routes.list_resource_templates", return_value=[]), \
         patch("chat_app.pages.capabilities.routes.list_tools", return_value=[_fake_tool()]):
        response = client.get("/capabilities/")

    assert response.status_code == 200
    assert b"restart_service_tool" in response.data


def test_browse_groups_extension_tools_under_their_own_accordion_section(client):
    """The new per-extension accordion needs each extension's own tools
    bucketed under it, keyed off the live extension catalog (not just
    whatever ids happen to show up in the tool list) - so a connected
    extension that currently offers zero tools still gets an (empty)
    group, and an extension tool renders once, inside its group, not
    also duplicated into the flat built-in list above it."""
    with patch(
        "chat_app.pages.capabilities.routes.fetch_extensions",
        return_value=[
            {"id": "reference", "label": "Reference", "description": "", "status": "connected", "error": None},
            {"id": "empty_ext", "label": "Empty Ext", "description": "", "status": "error", "error": "boom"},
        ],
    ), \
         patch("chat_app.pages.capabilities.routes.list_resource_templates", return_value=[]), \
         patch(
             "chat_app.pages.capabilities.routes.list_tools",
             return_value=[_fake_tool(name="reference__do_thing"), _fake_tool()],
         ):
        response = client.get("/capabilities/")

    html = response.data.decode()
    assert response.status_code == 200
    assert 'data-extension-id="reference"' in html
    assert 'data-extension-id="empty_ext"' in html
    # The extension tool renders exactly once - inside its group, not
    # duplicated into the flat built-in list (which now only loops over
    # tools with no extension_id).
    assert html.count('id="tool-reference__do_thing"') == 1
    # The built-in tool still renders unchanged in the flat list.
    assert "restart_service_tool" in html
    assert "1 tool" in html  # reference's count
    assert "0 tools" in html  # empty_ext's count


def test_api_tools_returns_reshaped_json(client):
    with patch("chat_app.pages.capabilities.routes.list_tools", return_value=[_fake_tool()]):
        response = client.get("/capabilities/api/tools")

    assert response.status_code == 200
    assert response.get_json() == [
        {
            "name": "restart_service_tool",
            "title": "Restart Service",
            "description": "Restart a service on a host.",
            "input_schema": {"type": "object", "properties": {"service": {"type": "string"}}},
            "extension_id": None,
        }
    ]


def test_api_tools_tags_extension_namespaced_tool_with_its_extension_id(client):
    """Extension tools are "{ext_id}__original_name" (double underscore) -
    same convention mcp_client._tool_is_enabled uses. This field is what
    the capabilities page's script.js groups tool cards by."""
    with patch("chat_app.pages.capabilities.routes.list_tools", return_value=[_fake_tool(name="reference__do_thing")]):
        response = client.get("/capabilities/api/tools")

    assert response.status_code == 200
    assert response.get_json()[0]["extension_id"] == "reference"
    assert response.get_json()[0]["name"] == "reference__do_thing"


def test_browse_renders_friendly_title_not_just_raw_name(client):
    with patch("chat_app.pages.capabilities.routes.list_tools", return_value=[_fake_tool()]), \
         patch("chat_app.pages.capabilities.routes.list_resource_templates", return_value=[]):
        response = client.get("/capabilities/")

    assert response.status_code == 200
    assert b"Restart Service" in response.data
    # the raw machine name should still appear somewhere (it's what the
    # try-it console actually POSTs to), just not as the heading anymore
    assert b"restart_service_tool" in response.data


def test_try_tool_calls_through_and_returns_result(client):
    with patch("chat_app.pages.capabilities.routes.call_tool", return_value="nginx restarted") as mock_call:
        response = client.post("/capabilities/api/try/restart_service_tool", json={"service": "nginx"})

    assert response.status_code == 200
    assert response.get_json() == {"status": "ok", "result": "nginx restarted"}
    mock_call.assert_called_once_with("restart_service_tool", {"service": "nginx"})


def test_try_tool_failure_returns_500_with_message(client):
    with patch("chat_app.pages.capabilities.routes.call_tool", side_effect=RuntimeError("MCP server down")):
        response = client.post("/capabilities/api/try/restart_service_tool", json={"service": "nginx"})

    assert response.status_code == 500
    assert response.get_json() == {"status": "error", "message": "MCP server down"}


def test_try_tool_with_no_body_sends_empty_arguments(client):
    with patch("chat_app.pages.capabilities.routes.call_tool", return_value="ok") as mock_call:
        client.post("/capabilities/api/try/list_services", json={})

    mock_call.assert_called_once_with("list_services", {})


def test_api_resources_returns_reshaped_json_with_extracted_params(client):
    with patch("chat_app.pages.capabilities.routes.list_resource_templates", return_value=[_fake_resource_template()]):
        response = client.get("/capabilities/api/resources")

    assert response.status_code == 200
    assert response.get_json() == [
        {
            "name": "recent_logs_resource",
            "title": "Recent Logs Resource",
            "description": "Recent log lines from a host.",
            "uri_template": "logs://recent/{host}",
            "params": ["host"],
        }
    ]


def test_browse_groups_builtin_tools_under_their_capability_accordion(client):
    """Built-in tools with a known capability (host_health/otp - see
    tool_capabilities.py) get grouped into their own accordion sections,
    the same way extension tools are grouped by extension. This is
    separate from the flat ``tools`` list, which is kept around for the
    top summary count."""
    with patch("chat_app.pages.capabilities.routes.list_resource_templates", return_value=[]), \
         patch(
             "chat_app.pages.capabilities.routes.list_tools",
             return_value=[
                 _fake_tool(name="get_host_health_tool"),
                 _fake_tool(name="request_otp_tool"),
                 _fake_tool(name="verify_otp_tool"),
             ],
         ):
        response = client.get("/capabilities/")

    html = response.data.decode()
    assert response.status_code == 200
    assert 'data-capability-label="Host Health"' in html
    assert 'data-capability-label="OTP"' in html
    assert "2 tools" in html  # OTP's count (request_otp_tool + verify_otp_tool)
    assert "1 tool" in html  # Host Health's count


def test_browse_falls_back_unmapped_builtin_tools_to_other_group(client):
    """A built-in tool with no entry in tool_capabilities.py's map isn't
    dropped - it lands in the "Other" fallback group, so nothing silently
    disappears if a future mcp_server capability lands before this map is
    updated."""
    with patch("chat_app.pages.capabilities.routes.list_resource_templates", return_value=[]), \
         patch("chat_app.pages.capabilities.routes.list_tools", return_value=[_fake_tool()]):
        response = client.get("/capabilities/")

    html = response.data.decode()
    assert response.status_code == 200
    assert 'data-capability-label="Other"' in html
    assert "restart_service_tool" in html


def test_browse_excludes_extension_tools_from_capability_groups(client):
    """An extension tool is grouped under its extension only - it must
    not also show up in a capability group, since it doesn't come from
    tool_capabilities.py's built-in map at all."""
    with patch(
        "chat_app.pages.capabilities.routes.fetch_extensions",
        return_value=[{"id": "reference", "label": "Reference", "description": "", "status": "connected", "error": None}],
    ), \
         patch("chat_app.pages.capabilities.routes.list_resource_templates", return_value=[]), \
         patch(
             "chat_app.pages.capabilities.routes.list_tools",
             return_value=[_fake_tool(name="reference__do_thing"), _fake_tool(name="get_host_health_tool")],
         ):
        response = client.get("/capabilities/")

    html = response.data.decode()
    assert response.status_code == 200
    # The extension tool renders once, inside its extension group -
    # capability groups only ever hold built-ins (extension_id is None).
    assert html.count('id="tool-reference__do_thing"') == 1
    assert 'data-capability-label="Host Health"' in html


def test_browse_groups_resources_under_their_capability_accordion(client):
    """host_health the resource groups under the same "Host Health" label
    as get_host_health_tool - same underlying capability, per run.py's
    comment (the resource serves URI-reading clients, the tool serves
    models)."""
    with patch("chat_app.pages.capabilities.routes.list_tools", return_value=[]), \
         patch(
             "chat_app.pages.capabilities.routes.list_resource_templates",
             return_value=[_fake_resource_template(name="host_health", uri_template="host://health/{name}")],
         ):
        response = client.get("/capabilities/")

    html = response.data.decode()
    assert response.status_code == 200
    assert 'data-capability-label="Host Health"' in html
    assert "1 resource" in html


def test_browse_falls_back_unmapped_resources_to_other_group(client):
    with patch("chat_app.pages.capabilities.routes.list_tools", return_value=[]), \
         patch("chat_app.pages.capabilities.routes.list_resource_templates", return_value=[_fake_resource_template()]):
        response = client.get("/capabilities/")

    html = response.data.decode()
    assert response.status_code == 200
    assert 'data-capability-label="Other"' in html
    assert "Recent Logs Resource" in html


def test_browse_renders_resource_section(client):
    with patch("chat_app.pages.capabilities.routes.list_tools", return_value=[]), \
         patch("chat_app.pages.capabilities.routes.list_resource_templates", return_value=[_fake_resource_template()]):
        response = client.get("/capabilities/")

    assert response.status_code == 200
    assert b"Recent Logs Resource" in response.data
    assert b"logs://recent/{host}" in response.data


def test_read_resource_calls_through_and_returns_result(client):
    with patch("chat_app.pages.capabilities.routes.read_resource", return_value='{"host": "web-1", "lines": []}') as mock_read:
        response = client.post("/capabilities/api/read-resource", json={"uri": "logs://recent/web-1"})

    assert response.status_code == 200
    assert response.get_json() == {"status": "ok", "result": '{"host": "web-1", "lines": []}'}
    mock_read.assert_called_once_with("logs://recent/web-1")


def test_read_resource_failure_returns_500(client):
    with patch("chat_app.pages.capabilities.routes.read_resource", side_effect=RuntimeError("MCP server down")):
        response = client.post("/capabilities/api/read-resource", json={"uri": "logs://recent/web-1"})

    assert response.status_code == 500
    assert response.get_json() == {"status": "error", "message": "MCP server down"}


def test_read_resource_missing_uri_returns_400(client):
    response = client.post("/capabilities/api/read-resource", json={})

    assert response.status_code == 400
