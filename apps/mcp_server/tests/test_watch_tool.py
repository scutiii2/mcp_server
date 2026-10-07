"""The watch tools are registered with the shapes ember_api and the agent rely on."""

from __future__ import annotations

import pytest

from src.capabilities.watchers import tool as watch_tool  # noqa: F401
from src.server import mcp


@pytest.mark.anyio
async def test_the_three_tools_exist_with_their_parameters():
    tools = {tool.name: tool for tool in await mcp.list_tools()}

    assert {"tool_watch_create", "tool_watch_listWatchers", "tool_watch_cancel"} <= set(tools)
    create = tools["tool_watch_create"].inputSchema
    assert set(create["properties"]) == {"kind", "target", "expect", "contains", "label"}
    assert create["required"] == ["kind", "target"]
    assert set(tools["tool_watch_cancel"].inputSchema["properties"]) == {"key"}
    assert tools["tool_watch_listWatchers"].inputSchema.get("properties", {}) == {}


@pytest.mark.anyio
async def test_the_list_tool_returns_a_top_level_watchers_list():
    tools = {tool.name: tool for tool in await mcp.list_tools()}

    output = tools["tool_watch_listWatchers"].outputSchema

    assert "watchers" in output["properties"]
