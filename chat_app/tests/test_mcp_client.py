"""Tests for the OpenAI-shape reformatting in mcp_client.

``list_tools`` is patched at ``chat_app.services.mcp_client.list_tools``
(its own definition site) because ``tool_schemas_for_openai`` calls it as a
same-module reference, unlike the route-level patches which target the
importing module.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from chat_app.services.mcp_client import tool_schemas_for_openai


def test_reshapes_tool_into_openai_function_format():
    fake_tool = SimpleNamespace(
        name="stop_sap_system_tool",
        description="Stop a SAP system by SID.",
        inputSchema={"type": "object", "properties": {"sid": {"type": "string"}}},
    )

    with patch("chat_app.services.mcp_client.list_tools", return_value=[fake_tool]):
        schemas = tool_schemas_for_openai()

    assert schemas == [
        {
            "type": "function",
            "name": "stop_sap_system_tool",
            "description": "Stop a SAP system by SID.",
            "parameters": {"type": "object", "properties": {"sid": {"type": "string"}}},
        }
    ]


def test_handles_missing_description_and_schema_gracefully():
    fake_tool = SimpleNamespace(name="noop_tool", description=None, inputSchema=None)

    with patch("chat_app.services.mcp_client.list_tools", return_value=[fake_tool]):
        schemas = tool_schemas_for_openai()

    assert schemas[0]["description"] == ""
    assert schemas[0]["parameters"] == {"type": "object", "properties": {}}


def test_empty_tool_list_returns_empty_schemas():
    with patch("chat_app.services.mcp_client.list_tools", return_value=[]):
        assert tool_schemas_for_openai() == []
