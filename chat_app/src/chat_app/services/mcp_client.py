"""MCP client wrapper - the only place this process talks to the MCP server.

Provider-agnostic on purpose: every LLM provider (openai_provider.py,
claude_provider.py, ...) reshapes this same live catalog into its own
wire format. This file only knows the generic MCP shape.
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


async def _list_resource_templates_async() -> list[Any]:
    async with streamablehttp_client(settings.mcp_server_url) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.list_resource_templates()
            # NOT runtime-verified against the installed mcp==1.28.0 SDK in
            # the sandbox this was built in (no network access to install
            # it there) - the MCP spec defines this field as
            # "resourceTemplates" on the wire, and the Python SDK typically
            # exposes it as the snake_case ``resource_templates``. Confirm
            # the attribute name once you can actually run this.
            return getattr(result, "resource_templates", getattr(result, "resourceTemplates", []))


async def _read_resource_async(uri: str) -> str:
    async with streamablehttp_client(settings.mcp_server_url) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.read_resource(uri)
            parts = [getattr(block, "text", str(block)) for block in result.contents]
            return "\n".join(parts) if parts else "(empty)"


def list_resource_templates() -> list[Any]:
    """Live resource-template catalog - the MCP equivalent of list_tools()
    for browsable, URI-addressed read-only data instead of actions."""
    return asyncio.run(_list_resource_templates_async())


def read_resource(uri: str) -> str:
    return asyncio.run(_read_resource_async(uri))
