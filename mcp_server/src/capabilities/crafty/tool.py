"""The @mcp.tool() wrappers - thin on purpose.

Resolve the deployment's default Crafty URL/TLS setting from
``src.config.settings`` (only ``register_world_tool`` needs them - every
other tool resolves everything it needs from the registered world
itself), call the domain function, return its result.

Not gated behind ``infra/approvals.py``. Starting, stopping, and
restarting a world are all reversible - same reasoning as
``server_manager/tool.py`` - and a console command sent to a world's
stdin is no different in kind from an operator typing it directly into
Crafty's own console. Registering a world stores a credential locally
but performs no action against Crafty itself. On a single-operator
homelab deployment the extra ceremony of an emailed approval buys little
for any of these; revisit if this server is ever reachable by more than
one person.
"""

from __future__ import annotations

from src.capabilities.crafty import domain
from src.capabilities.crafty.contract import (
    DefaultBaseUrlResult,
    PingBaseUrlResult,
    WorldActionResult,
    WorldCommandResult,
    WorldListResult,
    WorldRegisterResult,
    WorldRemoveResult,
    WorldStatusResult,
)
from src.commands import command
from src.config import settings
from src.server import mcp
from src.tool_response import respond


@command(name="base_url", description="Set the default Crafty base_url")
@mcp.tool(meta={"keywords": ["crafty", "minecraft", "default", "base_url", "url", "configure"]})
def crafty_set_default_base_url(base_url: str, verify_ssl: bool = True) -> DefaultBaseUrlResult:
    """Set the default Crafty Controller URL that crafty_world_register_tool
    falls back to when a registration call doesn't name its own `base_url`.

    Useful when every world registered on this server lives on the same
    Crafty instance - set it once here instead of passing `base_url` on
    every registration. Takes effect immediately, unlike the
    CRAFTY_BASE_URL environment variable, which needs a restart. Calling
    this again replaces the previous default.
    """
    return respond(domain.set_default_base_url(settings.crafty_worlds_db_path, base_url=base_url, verify_ssl=verify_ssl))


@command(name="ping", description="Ping a Crafty base_url")
@mcp.tool(meta={"keywords": ["crafty", "minecraft", "ping", "base_url", "reachable", "health", "connectivity"]})
async def crafty_ping_base_url(base_url: str | None = None, verify_ssl: bool | None = None) -> PingBaseUrlResult:
    """Check whether a Crafty Controller instance is reachable over the network.

    `base_url` defaults to this deployment's configured default (set via
    crafty_set_default_base_url_tool, or CRAFTY_BASE_URL) when omitted.
    Doesn't require any world to be registered first - use this to test a
    URL before registering anything against it.

    `reachable=True` for any HTTP response at all, even a 401/404 - that
    still proves something answered. `reachable=False` means the
    connection itself failed (DNS, refused, timed out, TLS) - that's a
    normal answer to "is this up", not an error from this tool.
    """
    return respond(
        await domain.ping_base_url(
            settings.crafty_worlds_db_path,
            base_url=base_url,
            verify_ssl=verify_ssl,
            default_base_url=settings.crafty_default_base_url,
            default_verify_ssl=settings.crafty_verify_ssl,
        )
    )


@command(name="register", description="Register a Crafty world")
@mcp.tool(meta={"keywords": ["crafty", "minecraft", "world", "register"]})
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
            settings.crafty_worlds_db_path,
            name,
            api_token=api_token,
            server_id=server_id,
            base_url=base_url,
            verify_ssl=verify_ssl,
            default_base_url=settings.crafty_default_base_url,
            default_verify_ssl=settings.crafty_verify_ssl,
        )
    )


@command(name="remove", description="Remove a registered Crafty world")
@mcp.tool(meta={"keywords": ["crafty", "minecraft", "world", "remove", "unregister", "delete"]})
def crafty_world_remove(name: str) -> WorldRemoveResult:
    """Remove a world's registration from this server.

    `name` is the label it was registered under. This only forgets the
    registration (base_url, server id, API token) that this server holds -
    it does not touch the world itself on Crafty. The world can be
    controlled again by calling crafty_world_register_tool for it.
    """
    return respond(domain.remove_world(settings.crafty_worlds_db_path, name))


@command(name="list", description="List registered Crafty worlds")
@mcp.tool(meta={"keywords": ["crafty", "minecraft", "world", "list"]})
def crafty_world_list() -> WorldListResult:
    """List every Minecraft world registered with this server.

    Each entry gives the exact `name` to pass to the other
    crafty_world_* tools.
    """
    return respond(domain.list_worlds(settings.crafty_worlds_db_path))


@command(name="start", description="Start a Crafty world")
@mcp.tool(meta={"keywords": ["crafty", "minecraft", "world", "start"]})
async def crafty_world_start(name: str) -> WorldActionResult:
    """Start a stopped, registered Minecraft world.

    `name` is the label it was registered under - `crafty_world_list_tool`
    shows the names that are available.
    """
    return respond(await domain.start_world(settings.crafty_worlds_db_path, name))


@command(name="stop", description="Stop a Crafty world")
@mcp.tool(meta={"keywords": ["crafty", "minecraft", "world", "stop"]})
async def crafty_world_stop(name: str) -> WorldActionResult:
    """Stop a running, registered Minecraft world."""
    return respond(await domain.stop_world(settings.crafty_worlds_db_path, name))


@command(name="restart", description="Restart a Crafty world")
@mcp.tool(meta={"keywords": ["crafty", "minecraft", "world", "restart"]})
async def crafty_world_restart(name: str) -> WorldActionResult:
    """Restart a registered Minecraft world - stop, then start again.

    Works whether the world is currently running or already stopped.
    """
    return respond(await domain.restart_world(settings.crafty_worlds_db_path, name))


@command(name="command", description="Send a console command to a Crafty world")
@mcp.tool(meta={"keywords": ["crafty", "minecraft", "world", "command", "console"]})
async def crafty_world_send_command(name: str, command: str) -> WorldCommandResult:
    """Send a raw console command to a registered Minecraft world.

    `command` is typed exactly as it would be into Crafty's own console -
    no leading slash (e.g. "say hello", "whitelist add Steve", "op Steve").
    """
    return respond(await domain.send_command(settings.crafty_worlds_db_path, name, command))


@command(name="status", description="Get a Crafty world's status")
@mcp.tool(meta={"keywords": ["crafty", "minecraft", "world", "status", "players"]})
async def crafty_world_get_status(name: str) -> WorldStatusResult:
    """Check whether a registered Minecraft world is running, who's on
    it, and basic server stats (version, CPU, memory).
    """
    return respond(await domain.get_status(settings.crafty_worlds_db_path, name))
