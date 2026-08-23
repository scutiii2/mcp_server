"""mcp_client.py tests: the extension-tool filter in list_tools(), and
fetch_extensions()'s proxying of mcp_server's plain-HTTP endpoint.

No real MCP server or network call happens here - ``_list_tools_async``
and ``urlopen`` are mocked at the point mcp_client.py uses them, matching
this suite's existing convention (see conftest.py's docstring).
"""

from __future__ import annotations

import json
import urllib.error
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from src.services import mcp_client


def _tool(name: str):
    return SimpleNamespace(name=name, description="", inputSchema={})


def _mixed_tools():
    return [
        _tool("get_host_health_tool"),  # built-in - no "__" prefix
        _tool("request_otp_tool"),  # built-in
        _tool("reference__echo"),  # extension "reference"
        _tool("reference__add"),  # extension "reference"
        _tool("other_ext__do_thing"),  # extension "other_ext"
    ]


def test_list_tools_with_no_filter_drops_all_extension_tools():
    """Omitted enabled_extensions is the deliberate safe default: NOT
    "allow everything" - that inversion is exactly the kind of allowlist
    bug this project has hit before, so it gets its own explicit test."""
    with patch("src.services.mcp_client._list_tools_async", return_value=_mixed_tools()):
        names = [t.name for t in mcp_client.list_tools()]

    assert names == ["get_host_health_tool", "request_otp_tool"]


def test_list_tools_with_empty_list_also_drops_all_extension_tools():
    """Empty list must behave identically to omitted (None) - both mean
    "nothing enabled", not "everything enabled"."""
    with patch("src.services.mcp_client._list_tools_async", return_value=_mixed_tools()):
        names = [t.name for t in mcp_client.list_tools(enabled_extensions=[])]

    assert names == ["get_host_health_tool", "request_otp_tool"]


def test_list_tools_always_keeps_unnamespaced_builtin_tools():
    with patch("src.services.mcp_client._list_tools_async", return_value=_mixed_tools()):
        names = [t.name for t in mcp_client.list_tools(enabled_extensions=["reference"])]

    assert "get_host_health_tool" in names
    assert "request_otp_tool" in names


def test_list_tools_includes_only_the_enabled_extensions_tools():
    with patch("src.services.mcp_client._list_tools_async", return_value=_mixed_tools()):
        names = [t.name for t in mcp_client.list_tools(enabled_extensions=["reference"])]

    assert "reference__echo" in names
    assert "reference__add" in names
    assert "other_ext__do_thing" not in names


def test_list_tools_with_multiple_enabled_extensions():
    with patch("src.services.mcp_client._list_tools_async", return_value=_mixed_tools()):
        names = {t.name for t in mcp_client.list_tools(enabled_extensions=["reference", "other_ext"])}

    assert names == {
        "get_host_health_tool",
        "request_otp_tool",
        "reference__echo",
        "reference__add",
        "other_ext__do_thing",
    }


def test_fetch_extensions_builds_url_from_mcp_server_base_and_returns_parsed_json():
    """settings.mcp_server_url is the MCP protocol path (".../mcp") -
    /extensions is a sibling on the same origin, not a route under it."""
    fake_payload = [
        {
            "id": "reference",
            "label": "Reference Extension (dev fixture)",
            "description": "A dev fixture extension.",
            "status": "connected",
            "error": None,
            "tools": ["reference__echo", "reference__add"],
        }
    ]

    class _FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            import json

            return json.dumps(fake_payload).encode("utf-8")

    captured_url = {}

    def _fake_urlopen(url, timeout=None):
        captured_url["url"] = url
        return _FakeResponse()

    with patch("src.services.mcp_client.urlopen", side_effect=_fake_urlopen):
        result = mcp_client.fetch_extensions()

    assert result == fake_payload
    assert captured_url["url"] == "http://127.0.0.1:8010/extensions"


def test_fetch_commands_builds_url_from_mcp_server_base_and_returns_parsed_json():
    """/commands is a sibling of /extensions on the same origin - same
    reasoning as fetch_extensions() above."""
    fake_payload = [
        {"capability": "otp", "name": "get_otp", "description": "generate otp", "tool_name": "request_otp_tool"}
    ]
    captured_url = {}

    def _fake_urlopen(url, timeout=None):
        captured_url["url"] = url

        class _FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return json.dumps(fake_payload).encode("utf-8")

        return _FakeResponse()

    with patch("src.services.mcp_client.urlopen", side_effect=_fake_urlopen):
        result = mcp_client.fetch_commands()

    assert result == fake_payload
    assert captured_url["url"] == "http://127.0.0.1:8010/commands"


def _fake_response(payload):
    class _FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps(payload).encode("utf-8")

    return _FakeResponse()


def test_add_extension_posts_json_and_returns_parsed_status():
    created = {
        "id": "reference",
        "label": "Reference",
        "description": "desc",
        "status": "connected",
        "error": None,
        "tools": [],
    }
    captured = {}

    def _fake_urlopen(request, timeout=None):
        captured["url"] = request.full_url
        captured["method"] = request.get_method()
        captured["headers"] = dict(request.header_items())
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return _fake_response(created)

    with patch("src.services.mcp_client.urlopen", side_effect=_fake_urlopen):
        result = mcp_client.add_extension("Reference", "http://example.com/mcp", "desc")

    assert result == created
    assert captured["url"] == "http://127.0.0.1:8010/extensions"
    assert captured["method"] == "POST"
    assert captured["headers"]["Content-type"] == "application/json"
    assert captured["body"] == {"label": "Reference", "url": "http://example.com/mcp", "description": "desc"}


def test_add_extension_defaults_description_to_empty_string():
    def _fake_urlopen(request, timeout=None):
        body = json.loads(request.data.decode("utf-8"))
        assert body["description"] == ""
        return _fake_response({"id": "x", "label": "x", "description": "", "status": "error", "error": "boom", "tools": []})

    with patch("src.services.mcp_client.urlopen", side_effect=_fake_urlopen):
        mcp_client.add_extension("x", "http://example.com/mcp")


def test_add_extension_propagates_http_error_with_status_code_intact():
    """A 400 from mcp_server's own validation must reach the caller with
    .code intact, not get swallowed into a generic exception - the route
    layer needs it to forward the right HTTP status."""
    error = urllib.error.HTTPError(
        url="http://127.0.0.1:8010/extensions",
        code=400,
        msg="Bad Request",
        hdrs=None,
        fp=None,
    )

    with patch("src.services.mcp_client.urlopen", side_effect=error):
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            mcp_client.add_extension("", "not-a-url")

    assert exc_info.value.code == 400


def test_remove_extension_sends_delete_to_the_id_specific_url():
    captured = {}

    def _fake_urlopen(request, timeout=None):
        captured["url"] = request.full_url
        captured["method"] = request.get_method()
        return _fake_response(None)

    with patch("src.services.mcp_client.urlopen", side_effect=_fake_urlopen):
        result = mcp_client.remove_extension("reference")

    assert result is None
    assert captured["url"] == "http://127.0.0.1:8010/extensions/reference"
    assert captured["method"] == "DELETE"


def test_remove_extension_propagates_http_error_with_status_code_intact():
    """A 404 for an unknown id must reach the caller with .code intact."""
    error = urllib.error.HTTPError(
        url="http://127.0.0.1:8010/extensions/unknown",
        code=404,
        msg="Not Found",
        hdrs=None,
        fp=None,
    )

    with patch("src.services.mcp_client.urlopen", side_effect=error):
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            mcp_client.remove_extension("unknown")

    assert exc_info.value.code == 404


def test_fetch_capabilities_builds_url_from_mcp_server_base_and_returns_parsed_json():
    fake_payload = [{"name": "host_health", "enabled": True}, {"name": "otp", "enabled": False}]
    captured_url = {}

    def _fake_urlopen(url, timeout=None):
        captured_url["url"] = url
        return _fake_response(fake_payload)

    with patch("src.services.mcp_client.urlopen", side_effect=_fake_urlopen):
        result = mcp_client.fetch_capabilities()

    assert result == fake_payload
    assert captured_url["url"] == "http://127.0.0.1:8010/capabilities"


def test_set_capability_enabled_patches_json_and_returns_parsed_status():
    updated = {"name": "otp", "enabled": False}
    captured = {}

    def _fake_urlopen(request, timeout=None):
        captured["url"] = request.full_url
        captured["method"] = request.get_method()
        captured["headers"] = dict(request.header_items())
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return _fake_response(updated)

    with patch("src.services.mcp_client.urlopen", side_effect=_fake_urlopen):
        result = mcp_client.set_capability_enabled("otp", False)

    assert result == updated
    assert captured["url"] == "http://127.0.0.1:8010/capabilities/otp"
    assert captured["method"] == "PATCH"
    assert captured["headers"]["Content-type"] == "application/json"
    assert captured["body"] == {"enabled": False}


def test_set_capability_enabled_propagates_http_error_with_status_code_intact():
    """A 404 for an unknown capability name must reach the caller with
    .code intact, same reasoning as add_extension's equivalent test."""
    error = urllib.error.HTTPError(
        url="http://127.0.0.1:8010/capabilities/nonexistent",
        code=404,
        msg="Not Found",
        hdrs=None,
        fp=None,
    )

    with patch("src.services.mcp_client.urlopen", side_effect=error):
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            mcp_client.set_capability_enabled("nonexistent", True)

    assert exc_info.value.code == 404
