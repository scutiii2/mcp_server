"""Control Minecraft worlds hosted on one or more Crafty Controller
instances - ten tools, callable directly or proxied through mcp_server
as an extension (see this project's README).

Unlike a fixed inventory, what this server controls isn't fixed at
deploy time - a world only becomes usable once ``crafty_world_register``
is called, naming which Crafty instance it's on, which server id Crafty
knows it as, and an API token scoped to that server.

Not gated behind any approval mechanism: starting, stopping, and
restarting a world are all reversible, and a console command sent to a
world's stdin is no different in kind from an operator typing it
directly into Crafty's own console. Registering a world stores a
credential locally but performs no action against Crafty itself. On a
single-operator homelab deployment the extra ceremony of an approval
step buys little for any of these.

Run with:
    python -m src.server
"""

from __future__ import annotations

import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from src import domain, suggestions
from src.contract import (
    DefaultBaseUrlResult,
    PingBaseUrlResult,
    WorldActionResult,
    WorldCommandResult,
    WorldListResult,
    WorldRegisterResult,
    WorldRemoveResult,
    WorldStatusResult,
)
from src.tool_response import respond

HOST = os.getenv("CRAFTY_MCP_HOST", "127.0.0.1")
PORT = int(os.getenv("CRAFTY_MCP_PORT", "9100"))

# Same env var names mcp_server's own config.py used for these, so an
# existing deployment's secrets/*.env carries over unchanged if it ever
# set them - see this project's README for the migration note.
DEFAULT_BASE_URL = os.getenv("CRAFTY_BASE_URL", "")
DEFAULT_VERIFY_SSL = os.getenv("CRAFTY_VERIFY_SSL", "true").strip().lower() != "false"
WORLDS_DB_PATH = Path(os.getenv("CRAFTY_WORLDS_DB_PATH", "src/data/crafty_worlds.db"))

mcp = FastMCP(
    name="crafty-mcp-server",
    instructions="Control Minecraft worlds hosted on one or more Crafty Controller instances.",
    host=HOST,
    port=PORT,
)


@mcp.tool()
def crafty_set_default_base_url(base_url: str, verify_ssl: bool = True) -> DefaultBaseUrlResult:
    """Set the default Crafty Controller URL that crafty_world_register
    falls back to when a registration call doesn't name its own `base_url`.

    Useful when every world registered on this server lives on the same
    Crafty instance - set it once here instead of passing `base_url` on
    every registration. Takes effect immediately, unlike the
    CRAFTY_BASE_URL environment variable, which needs a restart. Calling
    this again replaces the previous default.
    """
    return respond(domain.set_default_base_url(WORLDS_DB_PATH, base_url=base_url, verify_ssl=verify_ssl))


@mcp.tool()
async def crafty_ping_base_url(base_url: str | None = None, verify_ssl: bool | None = None) -> PingBaseUrlResult:
    """Check whether a Crafty Controller instance is reachable over the network.

    `base_url` defaults to this deployment's configured default (set via
    crafty_set_default_base_url, or CRAFTY_BASE_URL) when omitted.
    Doesn't require any world to be registered first - use this to test a
    URL before registering anything against it.

    `reachable=True` for any HTTP response at all, even a 401/404 - that
    still proves something answered. `reachable=False` means the
    connection itself failed (DNS, refused, timed out, TLS) - that's a
    normal answer to "is this up", not an error from this tool.
    """
    return respond(
        await domain.ping_base_url(
            WORLDS_DB_PATH,
            base_url=base_url,
            verify_ssl=verify_ssl,
            default_base_url=DEFAULT_BASE_URL,
            default_verify_ssl=DEFAULT_VERIFY_SSL,
        )
    )


@mcp.tool()
def crafty_world_register(
    name: str,
    api_token: str,
    server_id: str,
    base_url: str | None = None,
    verify_ssl: bool | None = None,
) -> WorldRegisterResult:
    """Register a Minecraft world hosted on a Crafty Controller instance.

    `name` is the label every other crafty_world_* tool will use to refer
    to this world - pick something short and memorable, e.g. "survival".
    `api_token` and `server_id` come from that world's page in Crafty.
    `base_url` (Crafty's own URL, e.g. "https://crafty.example.com:8443")
    is optional if this deployment has a default Crafty instance
    configured; otherwise it's required. Registering a name that's
    already registered overwrites its previous registration.
    """
    return respond(
        domain.register_world(
            WORLDS_DB_PATH,
            name,
            api_token=api_token,
            server_id=server_id,
            base_url=base_url,
            verify_ssl=verify_ssl,
            default_base_url=DEFAULT_BASE_URL,
            default_verify_ssl=DEFAULT_VERIFY_SSL,
        )
    )


@mcp.tool()
def crafty_world_remove(name: str) -> WorldRemoveResult:
    """Remove a world's registration from this server.

    `name` is the label it was registered under. This only forgets the
    registration (base_url, server id, API token) that this server holds -
    it does not touch the world itself on Crafty. The world can be
    controlled again by calling crafty_world_register for it.
    """
    return respond(domain.remove_world(WORLDS_DB_PATH, name))


@mcp.tool()
def crafty_world_list() -> WorldListResult:
    """List every Minecraft world registered with this server.

    Each entry gives the exact `name` to pass to the other
    crafty_world_* tools.
    """
    return respond(domain.list_worlds(WORLDS_DB_PATH))


@mcp.tool()
async def crafty_world_start(name: str) -> WorldActionResult:
    """Start a stopped, registered Minecraft world.

    `name` is the label it was registered under - `crafty_world_list`
    shows the names that are available.
    """
    return respond(await domain.start_world(WORLDS_DB_PATH, name))


@mcp.tool()
async def crafty_world_stop(name: str) -> WorldActionResult:
    """Stop a running, registered Minecraft world."""
    return respond(await domain.stop_world(WORLDS_DB_PATH, name))


@mcp.tool()
async def crafty_world_restart(name: str) -> WorldActionResult:
    """Restart a registered Minecraft world - stop, then start again.

    Works whether the world is currently running or already stopped.
    """
    return respond(await domain.restart_world(WORLDS_DB_PATH, name))


@mcp.tool()
async def crafty_world_send_command(name: str, command: str) -> WorldCommandResult:
    """Send a raw console command to a registered Minecraft world.

    `command` is typed exactly as it would be into Crafty's own console -
    no leading slash (e.g. "say hello", "whitelist add Steve", "op Steve").
    """
    return respond(await domain.send_command(WORLDS_DB_PATH, name, command))


@mcp.tool()
async def crafty_world_get_status(name: str) -> WorldStatusResult:
    """Check whether a registered Minecraft world is running, who's on
    it, and basic server stats (version, CPU, memory).
    """
    return respond(await domain.get_status(WORLDS_DB_PATH, name))


# Re-registers the low-level ListToolsRequest handler FastMCP's own
# __init__ set up, the same overwrite-by-re-registering mechanism
# mcp_server's infra/extensions.py uses (and documents at length) to
# merge in proxied tools - the justified reach into `_mcp_server` here is
# narrower: only list_tools() is replaced, call_tool() stays exactly what
# FastMCP registered, since suggestions.py only ever touches the
# advertised schema, never how a call is dispatched.
async def _list_tools_with_suggestions() -> list:
    tools = await mcp.list_tools()
    suggestions.apply_suggestions(tools, WORLDS_DB_PATH)
    return tools


mcp._mcp_server.list_tools()(_list_tools_with_suggestions)


def main() -> None:
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
