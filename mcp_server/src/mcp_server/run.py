"""Entry point for the MCP server.

Run with:
    python -m mcp_server.run
"""

from __future__ import annotations

# Must run before any mcp_server.* import: Settings' field defaults read
# os.getenv() at class-definition time (i.e. at import time), so .env needs
# to be loaded into the environment first or those defaults never see it.
from dotenv import load_dotenv

load_dotenv()

from mcp_server.config import settings  # noqa: E402
from mcp_server.logging_setup import configure_logging  # noqa: E402
from mcp_server.server import mcp  # noqa: E402

# Before anything else runs, so uvicorn's own request/error logging (once
# it starts inside _serve() below) is captured on disk from the start,
# not just log lines written after some later point in startup.
configure_logging(settings.log_dir)

# Import order = the order tools/resources appear in their respective
# list calls. Add each new capability's tool/resource module here as it's
# built, following the pattern in capabilities/<name>/ (contract.py /
# domain.py / tool.py) described in the README's "Adding a new tool"
# section.
#
# These imports look unused - they are not. Importing the module is what
# runs its @mcp.tool()/@mcp.resource() decorator and registers it.
#
# host_health appears twice on purpose: the resource serves clients that
# read a URI, the capability serves models that can only see tools. Same
# domain logic underneath - see capabilities/host_health/domain.py.
from mcp_server.capabilities.host_health import tool as host_health_tool  # noqa: E402,F401
from mcp_server.capabilities.otp import tool as otp_tool  # noqa: E402,F401
from mcp_server.resources.host_health import resource as host_health_resource  # noqa: E402,F401


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

    from mcp_server.infra import extensions

    try:
        # Before the tool_names line below, on purpose: extensions
        # register their proxied tools onto `mcp` itself (see
        # infra/extensions.py), so connecting first is what makes the
        # merged list below - and therefore the "Tools" count and bullet
        # list - include them.
        extension_statuses = await extensions.install_extensions(mcp, settings.config_path)

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

        from mcp_server.approval_routes import install_approval_routes
        from mcp_server.extension_routes import install_extension_routes
        from mcp_server.infra import approvals

        banner = [
            "MCP server",
            f"  Endpoint : http://{settings.host}:{settings.port}/mcp",
            f"  Config   : {settings.config_path}",
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
