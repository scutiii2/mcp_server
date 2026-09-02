"""Template MCP extension server - streamable HTTP.

Copy this whole `mcp_server_ext/` folder as the starting point for a
real MCP extension: give it its own tools (and secrets/config, if it
needs any), keep its own venv, and run it as its own process. Wire it
into `mcp_server` by adding an entry to that project's
`src/configs/config_extensions.json`, "url" pointing here - see this
folder's README.md for the exact entry and how mcp_server picks tools
up from it.

Two example tools below (`echo`, `summarize_numbers`) show the two
shapes a tool usually takes: a trivial passthrough, and one with
several typed/validated arguments and a structured return value -
FastMCP derives a tool's JSON schema straight from the function's type
hints and docstring, so both matter for what a caller sees.
`greeting` shows the same for a resource template (a URI a client
reads instead of calls).

Run directly:
    python -m src.server
"""

from __future__ import annotations

import os

from mcp.server.fastmcp import FastMCP

# Matches the "example-http" entry in mcp_server's own
# config_extensions.json.example (http://127.0.0.1:9000/mcp) - change
# both if you run this on a different port.
HOST = os.getenv("MCP_EXT_HOST", "127.0.0.1")
PORT = int(os.getenv("MCP_EXT_PORT", "9000"))

mcp = FastMCP(
    name="mcp-server-ext-template",
    instructions="Template extension server - replace with your own tools.",
    host=HOST,
    port=PORT,
)


@mcp.tool()
def echo(text: str) -> str:
    """Return `text` unchanged - the simplest possible tool shape."""
    return text


@mcp.tool()
def summarize_numbers(numbers: list[int]) -> dict[str, float]:
    """Return the sum, average, min, and max of `numbers`.

    Demonstrates a tool with a typed list argument and a structured
    dict return - FastMCP validates `numbers` against this signature
    before the function ever runs, rejecting a call whose "numbers"
    isn't a list of integers.
    """
    if not numbers:
        raise ValueError("numbers must not be empty")
    return {
        "sum": float(sum(numbers)),
        "average": sum(numbers) / len(numbers),
        "min": float(min(numbers)),
        "max": float(max(numbers)),
    }


@mcp.resource("greeting://{name}")
def greeting(name: str) -> str:
    """A URI-addressed, read-only piece of data - the resource
    equivalent of a tool. A client reads `greeting://Ada` instead of
    calling a tool with `name="Ada"`."""
    return f"Hello, {name}!"


def main() -> None:
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
