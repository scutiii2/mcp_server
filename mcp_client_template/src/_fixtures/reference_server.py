"""A minimal, self-contained stdio MCP server - a reference fixture for
testing registry.py's connect/list/call path against a real MCP server
speaking the real protocol over real stdio, not a mock of it.

Same two trivial tools as mcp_server/src/_fixtures/reference_extension_server.py,
copied rather than imported so this template has no dependency on
mcp_server's own package.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

mcp = FastMCP(
    name="reference-server",
    instructions="Dev fixture for testing mcp_client_template. Not a real server.",
)


@mcp.tool()
def echo(text: str) -> str:
    """Return `text` unchanged."""
    return text


@mcp.tool()
def add(a: int, b: int) -> int:
    """Return a + b."""
    return a + b


if __name__ == "__main__":
    mcp.run(transport="stdio")
