"""Entry point for the MCP server.

Run with:
    python -m src.run
"""

from __future__ import annotations

from pathlib import Path

# Must run before any src.* import: Settings' field defaults read
# os.getenv() at class-definition time (i.e. at import time), so every
# secrets/*.env file needs to be loaded into the environment first or
# those defaults never see it. Loaded from every *.env file in
# src/secrets/ rather than one fixed name, mirroring src/configs/'s
# one-file-per-concern split (secret_app.env, secret_smtp.env,
# secret_ssh.env today; a future capability that owns a real secret adds
# its own file here with zero changes to this loop).
from dotenv import load_dotenv

_SECRETS_DIR = Path("src/secrets")
for _env_file in sorted(_SECRETS_DIR.glob("*.env")):
    load_dotenv(_env_file)

from src.config import settings  # noqa: E402
from src.infra import capability_registry  # noqa: E402
from src.infra.app_config import capability_enabled, load_capabilities_config  # noqa: E402
from src.utils.logging_setup import configure_logging  # noqa: E402
from src.server import mcp  # noqa: E402

# Before anything else runs, so uvicorn's own request/error logging (once
# it starts inside _serve() below) is captured on disk from the start,
# not just log lines written after some later point in startup.
configure_logging(settings.log_dir)

_capabilities_config = load_capabilities_config(settings.capabilities_config_path)

# Import order = the order tools/resources appear in their respective
# list calls. Add each new capability's tool/resource module here as it's
# built, following the pattern in capabilities/<name>/ (contract.py /
# domain.py / tool.py) described in the README's "Adding a new tool"
# section - and add a toggle entry to config_capabilities.json /
# config_capabilities.json.example.
#
# Every capability imports unconditionally now, even a disabled one -
# capability_registry.capturing() needs the import to actually happen so
# it can capture what got registered, which is what makes toggling a
# capability back on later possible without re-importing (Python caches
# modules, so a second import wouldn't re-run the @mcp.tool() decorators
# anyway). Disabled state is applied immediately below, via the same
# registry a live PATCH /capabilities/{name} request uses later - see
# capability_routes.py and infra/capability_registry.py.
#
# host_health appears twice on purpose: the resource serves clients that
# read a URI, the capability serves models that can only see tools. Same
# domain logic underneath, same toggle entry (and the same `capturing`
# block) governs both - see capabilities/host_health/domain.py.
with capability_registry.capturing(mcp, "host_health"):
    from src.capabilities.host_health import tool as host_health_tool  # noqa: E402,F401
    from src.resources.host_health import resource as host_health_resource  # noqa: E402,F401

with capability_registry.capturing(mcp, "otp"):
    from src.capabilities.otp import tool as otp_tool  # noqa: E402,F401

with capability_registry.capturing(mcp, "server_manager"):
    from src.capabilities.server_manager import tool as server_manager_tool  # noqa: E402,F401

with capability_registry.capturing(mcp, "crafty"):
    from src.capabilities.crafty import tool as crafty_tool  # noqa: E402,F401

for _name in capability_registry.names():
    if not capability_enabled(_capabilities_config, _name):
        capability_registry.set_enabled(mcp, _name, False)


async def _serve() -> None:
    """Everything from "connect to extensions" through "serve forever"
    runs inside this one coroutine, under a single asyncio.run() (see
    main()) - not, as a first pass at this had it, several independent
    asyncio.run() calls followed by a separate uvicorn.run(). That
    mattered in practice, not just in theory: infra/extensions.py's
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

    from src.infra import extensions

    try:
        # Before the tool_names line below, on purpose: extensions
        # register their proxied tools onto `mcp` itself (see
        # infra/extensions.py), so connecting first is what makes the
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

        from src.approval_routes import install_approval_routes
        from src.capability_routes import install_capability_routes
        from src.command_routes import install_command_routes
        from src.extension_routes import install_extension_routes
        from src.infra import approvals

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
            f"  Gated    : {', '.join(approvals.registered_names()) or 'none'}",
            f"  Extensions: {', '.join(f'{s.id} ({s.status})' for s in extension_statuses) or 'none'}",
        ]
        if settings.host not in {"127.0.0.1", "localhost", "::1"}:
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

        app = mcp.streamable_http_app()
        # Where a human approves anything gated - deliberately a plain
        # HTTP route rather than a tool, so the model can't approve its
        # own requests. See approval_routes.py.
        install_approval_routes(app)
        # Where a human (or chat_app's sidebar) checks what's connected -
        # also a plain HTTP route, same reasoning: nothing here is
        # something a model needs to call. See extension_routes.py.
        install_extension_routes(app)
        # Where chat_app discovers which built-in tools are invocable as
        # "/" commands - also a plain HTTP route, same reasoning. See
        # command_routes.py.
        install_command_routes(app)
        # Where a human (chat_app's Capabilities page) turns a built-in
        # capability on/off live - also a plain HTTP route, same
        # reasoning as install_approval_routes above: this changes what
        # every caller of this server can do, not something a model
        # should be able to do to itself. See capability_routes.py.
        install_capability_routes(app)

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
