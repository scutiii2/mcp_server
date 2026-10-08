"""Entry point for the MCP server.

Run with:
    python -m src.run
"""

from __future__ import annotations

# Must run before any src.* import: Settings' field defaults read
# os.getenv() at class-definition time (i.e. at import time), so .env
# needs to be loaded into the environment first or those defaults never
# see it. A missing .env is built from the legacy .secrets/*.env files,
# else from .env.example.
from src.utils.env_file import load_env_file

load_env_file()

from src.config import settings  # noqa: E402
from src.services import capability_registry  # noqa: E402
from src.services.capability_loader import CapabilityLoader  # noqa: E402
from src.services.identity_context import IdentityContextMiddleware  # noqa: E402
from src.services.internal_token import InternalTokenMiddleware  # noqa: E402
from src.utils.logging_setup import configure_logging  # noqa: E402
from src.server import mcp  # noqa: E402

# Before anything else runs, so uvicorn's own request/error logging (once
# it starts inside _serve() below) is captured on disk from the start,
# not just log lines written after some later point in startup.
configure_logging(settings.log_dir)

# Capabilities are found by scanning src/capabilities/ (services/capability_loader.py),
# not imported by hand here: a folder added later appears on POST /capabilities/refresh
# with no restart. Each folder's __init__.py declares its id and label (META); one
# with a config entry is loaded now, one without stays offline until an admin brings it online.
capability_loader = CapabilityLoader(mcp, "src.capabilities", settings.capabilities_config_path)
capability_loader.startup()


async def _serve() -> None:
    """Everything from "connect to extensions" through "serve forever"
    runs inside this one coroutine, under a single asyncio.run() (see
    main()) - not, as a first pass at this had it, several independent
    asyncio.run() calls followed by a separate uvicorn.run(). That
    mattered in practice, not just in theory: services/extensions.py's
    upstream connections (stdio subprocess pipes, anyio task groups,
    cancel scopes) are bound to the event loop they were opened in.
    asyncio.run() tears its loop down when it returns, so connecting
    extensions in one throwaway loop and then serving requests in
    whatever loop uvicorn.run() spins up next leaves every proxied tool
    call reaching into a connection whose reader/writer tasks no longer
    exist - confirmed by hand: it raised
    "RuntimeError: Attempted to exit cancel scope in a different task
    than it was entered in" the moment the process tried to close a
    connection opened in a dead loop. One coroutine, one loop, for the
    server's entire run, is what keeps a proxied connection usable for as
    long as the server that opened it is up.
    """
    import uvicorn

    from src.services import extensions

    try:
        # Before the tool_names line below, on purpose: extensions
        # register their proxied tools onto `mcp` itself (see
        # services/extensions.py), so connecting first is what makes the
        # merged list below - and therefore the "Tools" count and bullet
        # list - include them.
        extension_statuses = await extensions.install_extensions(mcp, settings.extensions_config_path)

        # extensions.merged_list_tools(), not mcp.list_tools(): proxied
        # tools are only visible through the low-level handlers
        # install_extensions() just installed, not through FastMCP's own
        # list_tools() method, which install() deliberately leaves
        # untouched (see extensions.py).
        tool_names = sorted(t.name for t in await extensions.merged_list_tools())

        # Both calls are needed, not one with the other as a fallback:
        # verified against mcp==1.28.0, a resource whose URI contains a
        # {placeholder} appears ONLY in list_resource_templates(), and one
        # with a fixed URI appears ONLY in list_resources(). Counting just
        # the first would have reported "Resources: 0" while a template
        # was registered and working.
        resource_count: int | str
        try:
            concrete = len(await mcp.list_resources())
            templated = len(await mcp.list_resource_templates())
            resource_count = concrete + templated
        except Exception as error:  # noqa: BLE001 - a banner line must never block startup
            resource_count = f"unknown ({error})"

        from src.capability_routes import install_capability_routes
        from src.command_routes import install_command_routes
        from src.download_routes import install_download_routes
        from src.extension_routes import install_extension_routes
        from src.help_routes import install_help_routes
        from src.upload_routes import install_upload_routes

        enabled_capabilities = [
            name for name in capability_registry.names() if capability_registry.is_enabled(name)
        ]
        banner = [
            "MCP server",
            f"  Endpoint : http://{settings.host}:{settings.port}/mcp",
            f"  Config   : {settings.configs_dir}",
            f"  Capabilities: {', '.join(enabled_capabilities) or 'none'}",
            f"  Tools    : {len(tool_names)}",
            *(f"    - {name}" for name in tool_names),
            f"  Resources: {resource_count}",
            f"  Extensions: {', '.join(f'{s.id} ({s.status})' for s in extension_statuses) or 'none'}",
        ]
        banner.append(
            "  /mcp auth : X-Internal-Token required"
            if settings.internal_api_token
            else "  /mcp auth : none (set INTERNAL_API_TOKEN in .env)"
        )
        if settings.host not in {"127.0.0.1", "localhost", "::1"} and not settings.internal_api_token:
            # Worth shouting about: there is no authentication on this
            # server, so a non-loopback bind means anything that can
            # route to this port can call every tool above with arguments
            # of its choosing.
            banner.append(f"  WARNING  : bound to {settings.host} with no authentication.")

        # flush=True is not cosmetic. Python block-buffers stdout
        # whenever it isn't a terminal, so under Docker, systemd, or any
        # redirect to a file, this whole banner - including the
        # no-authentication warning - sits in the buffer indefinitely
        # while uvicorn's own logging (which goes to stderr) appears
        # immediately. The result is a log that looks like the server
        # started with nothing registered and nothing to warn about.
        # Flushing costs nothing here and is the difference between the
        # warning being seen and not.
        print("\n".join(banner), flush=True)

        # Restart the watchers that were running when the server last stopped.
        if "watch" in capability_registry.names() and capability_registry.is_enabled("watch"):
            from src.capabilities.watchers.utils.user_watcher import UserWatcher

            UserWatcher.resume_all(settings.watchers_dir)

        app = mcp.streamable_http_app()
        # Reads chat_app's X-Requester-Username/X-Requester-Email headers
        # (see services/commands.py's _IDENTITY_INJECTED_TOOLS) into
        # per-request contextvars, so an identity-gated capability's
        # domain function can read current_username()/current_email()
        # instead of taking the caller's identity as a tool argument -
        # see services/identity_context.py's module docstring for why.
        app.add_middleware(IdentityContextMiddleware)
        # Added last, so it runs first: a request to /mcp without the
        # shared internal token never reaches the transport (only when a
        # token is configured). See services/internal_token.py.
        app.add_middleware(InternalTokenMiddleware, token=settings.internal_api_token)
        # Where a human (or chat_app's sidebar) checks what's connected -
        # also a plain HTTP route, same reasoning: nothing here is
        # something a model needs to call. See extension_routes.py.
        install_extension_routes(app)
        # Where chat_app discovers which built-in tools are invocable as
        # "/" commands - also a plain HTTP route, same reasoning. See
        # command_routes.py.
        install_command_routes(app)
        # Where chat_app answers "/<capability> help ..." - also a plain
        # HTTP route, same reasoning as install_command_routes above: not
        # a real tool call, just structured data about one capability's
        # tools/commands/workflow for chat_app to render. See
        # help_routes.py.
        install_help_routes(app)
        # Where a human (chat_app's Capabilities page) turns a built-in
        # capability on/off live - also a plain HTTP route, same
        # reasoning as install_command_routes: this changes what
        # every caller of this server can do, not something a model
        # should be able to do to itself. It also rescans src/capabilities/
        # (POST /capabilities/refresh) and reloads a capability's code when it
        # goes online. See capability_routes.py.
        install_capability_routes(app, capability_loader)
        # Where chat_app proxies a file a user dropped into a command-form
        # modal, so a tool param that expects a real server-side path can
        # be filled with one - also a plain HTTP route, checked against
        # the same internal shared secret chat_app itself checks in the
        # other direction. See upload_routes.py.
        install_upload_routes(app)
        # Where a caller fetches a file a tool offered it (a download card's
        # link, through ember_api): a plain HTTP route for the same reason as
        # /upload, checked against the internal token and the requester. See
        # download_routes.py.
        install_download_routes(app)

        # uvicorn.Server(...).serve() rather than the uvicorn.run()
        # convenience function: run() calls asyncio.run() itself, which
        # would open a second event loop nested inside this one's -
        # exactly the split this function's docstring exists to avoid.
        # Server(...).serve() is uvicorn's own supported way to run from
        # inside an event loop you already own.
        server = uvicorn.Server(uvicorn.Config(app, host=settings.host, port=settings.port))
        await server.serve()
    finally:
        # Mirrors install_extensions() at the top: whatever subprocesses
        # got opened get closed on the way out, whether that's an orderly
        # shutdown or a startup failure partway through.
        await extensions.shutdown_extensions()


def main() -> None:
    import asyncio

    asyncio.run(_serve())


if __name__ == "__main__":
    main()
