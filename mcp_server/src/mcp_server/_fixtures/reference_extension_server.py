"""A minimal, self-contained stdio MCP server - a reference fixture for
testing infra/extensions.py's proxy mechanism, not a real integration.

Two trivial tools, ``echo`` and ``add``, exist only so a test can spawn
this as a real subprocess, connect to it as a real MCP client, list its
real tools, call one for real, and check the real result - proving the
proxy mechanism against the actual SDK rather than a mock of it. See
tests/test_extensions.py.

Uses the same ``mcp`` SDK as the rest of this project (no Node/npx, so
proving the mechanism needs nothing beyond this venv), and is invocable
as a module so config.json's "extensions" entries can name it the same
way they'd name any real upstream server:

    venv_mcp\\Scripts\\python.exe -m mcp_server._fixtures.reference_extension_server
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

mcp = FastMCP(
    name="reference-extension",
    instructions="Dev fixture for testing mcp_server's extension proxy. Not a real capability.",
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
