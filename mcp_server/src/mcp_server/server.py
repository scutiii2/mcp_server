"""Shared FastMCP server instance.

Keep this file free of tool definitions - it exists only so every module
under ``capabilities/`` and ``resources/`` can import the same ``mcp``
object to register onto.

``name`` and ``instructions`` are what an MCP client sees when it
connects, before it has looked at a single tool. Rename them to match
whatever this server ends up being about; the instructions are worth
rewriting once there are real tools, since a client reads them to decide
when this server is relevant at all.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

mcp = FastMCP(
    name="mcp-server",
    instructions=(
        "General-purpose MCP tool server. Each tool's own description "
        "states when to use it - prefer that over guessing from the name."
    ),
)
