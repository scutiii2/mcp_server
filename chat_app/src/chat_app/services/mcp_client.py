"""MCP client wrapper - the only place this process talks to the MCP server.

Both the chat loop (for OpenAI tool schemas) and the capabilities browser
(for the tool catalog page) call through here, so there's exactly one
implementation of "how do we reach the MCP server" to maintain.
"""

from __future__ import annotations

import asyncio
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from chat_app.config import settings


async def _list_tools_async() -> list[Any]:
    async with streamablehttp_client(settings.mcp_server_url) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.list_tools()
            return result.tools


async def _call_tool_async(name: str, arguments: dict[str, Any]) -> str:
    async with streamablehttp_client(settings.mcp_server_url) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(name, arguments)
            parts = [getattr(block, "text", str(block)) for block in result.content]
            return "\n".join(parts) if parts else "(no output)"


def list_tools() -> list[Any]:
    """Live tool catalog from the MCP server - never a hardcoded list."""
    return asyncio.run(_list_tools_async())


def call_tool(name: str, arguments: dict[str, Any]) -> str:
    return asyncio.run(_call_tool_async(name, arguments))


def tool_schemas_for_openai() -> list[dict[str, Any]]:
    """Same live catalog, reshaped for the OpenAI Responses API function-tool format."""
    return [
        {
            "type": "function",
            "name": tool.name,
            "description": tool.description or "",
            "parameters": tool.inputSchema or {"type": "object", "properties": {}},
        }
        for tool in list_tools()
    ]
