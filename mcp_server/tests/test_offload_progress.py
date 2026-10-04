"""offload_with_progress: worker-thread progress.report() calls reach an MCP
client as progress notifications, in order, before the tool result."""

from __future__ import annotations

import asyncio
from typing import Annotated

from mcp.server.fastmcp import FastMCP
from pydantic import Field
from mcp.shared.memory import create_connected_server_and_client_session

from src.offload import offload_with_progress
from src.services import progress


def _build_server() -> FastMCP:
    server = FastMCP("progress-test")

    @server.tool()
    @offload_with_progress
    def slow_tool(name: str) -> str:
        progress.report("step one")
        progress.report("step two")
        return f"done {name}"

    return server


def test_progress_messages_reach_client_before_result():
    received: list[str | None] = []

    async def on_progress(value: float, total: float | None, message: str | None) -> None:
        received.append(message)

    async def run():
        async with create_connected_server_and_client_session(_build_server()._mcp_server) as client:
            return await client.call_tool("slow_tool", {"name": "x"}, progress_callback=on_progress)

    result = asyncio.run(run())
    assert received == ["step one", "step two"]
    assert result.content[0].text == "done x"


def test_tool_schema_hides_ctx():
    async def run():
        async with create_connected_server_and_client_session(_build_server()._mcp_server) as client:
            return (await client.list_tools()).tools[0]

    tool = asyncio.run(run())
    assert list(tool.inputSchema["properties"]) == ["name"]


_Label = Annotated[str, Field(description="A module-level alias, resolved from a string annotation.")]


def test_string_annotations_resolve_in_the_tools_own_module():
    # This file uses `from __future__ import annotations`, like several tool
    # modules: `name: _Label` is a string the wrapper's module cannot resolve.
    server = FastMCP("annotations-test")

    @server.tool()
    @offload_with_progress
    def aliased_tool(name: _Label) -> str:
        return name

    async def run():
        async with create_connected_server_and_client_session(server._mcp_server) as client:
            return (await client.list_tools()).tools[0]

    tool = asyncio.run(run())
    assert tool.inputSchema["properties"]["name"]["description"].startswith("A module-level alias")


def test_report_without_sink_is_noop():
    progress.report("nobody listening")
