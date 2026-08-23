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

from mcp_server.config import settings

# host=settings.host (not the library's own "127.0.0.1" default) matters
# beyond where uvicorn binds (run.py handles that separately): FastMCP
# only auto-enables its Host-header DNS-rebinding protection, restricted
# to 127.0.0.1/localhost/::1, when it believes it's loopback-only. Leaving
# this at the default made every request whose Host header wasn't one of
# those three values fail with 421, even from another container calling
# in by its Docker Compose service name - independent of MCP_HOST and
# invisible from the outside, since the bind address was still correct.
mcp = FastMCP(
    name="mcp-server",
    instructions=(
        "General-purpose MCP tool server. Each tool's own description "
        "states when to use it - prefer that over guessing from the name."
    ),
    host=settings.host,
)
