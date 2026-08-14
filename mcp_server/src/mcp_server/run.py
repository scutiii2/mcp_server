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
from mcp_server.server import mcp  # noqa: E402

# Import order = the order tools/resources appear in their respective
# list calls. Add each new capability's tool/resource module here as it's
# built, following the pattern in capabilities/<name>/ (contract.py /
# domain.py / tool.py) described in the README's "Adding a new tool"
# section.
#
# These imports look unused - they are not. Importing the module is what
# runs its @mcp.tool()/@mcp.resource() decorator and registers it.
from mcp_server.resources.host_health import resource as host_health_resource  # noqa: E402,F401
from mcp_server.capabilities.otp import tool as otp_tool  # noqa: E402,F401


def main() -> None:
    import asyncio

    import uvicorn

    tool_names = sorted(t.name for t in asyncio.run(mcp.list_tools()))

    # Both calls are needed, not one with the other as a fallback:
    # verified against mcp==1.28.0, a resource whose URI contains a
    # {placeholder} appears ONLY in list_resource_templates(), and one
    # with a fixed URI appears ONLY in list_resources(). Counting just the
    # first would have reported "Resources: 0" while a template was
    # registered and working.
    resource_count: int | str
    try:
        concrete = len(asyncio.run(mcp.list_resources()))
        templated = len(asyncio.run(mcp.list_resource_templates()))
        resource_count = concrete + templated
    except Exception as error:  # noqa: BLE001 - a banner line must never block startup
        resource_count = f"unknown ({error})"

    from mcp_server.approval_routes import install_approval_routes
    from mcp_server.infra import approvals

    banner = [
        "MCP server",
        f"  Endpoint : http://{settings.host}:{settings.port}/mcp",
        f"  Config   : {settings.config_path}",
        f"  Tools    : {len(tool_names)}",
        *(f"    - {name}" for name in tool_names),
        f"  Resources: {resource_count}",
        f"  Gated    : {', '.join(approvals.registered_names()) or 'none'}",
    ]
    if settings.host not in {"127.0.0.1", "localhost", "::1"}:
        # Worth shouting about: there is no authentication on this server,
        # so a non-loopback bind means anything that can route to this
        # port can call every tool above with arguments of its choosing.
        banner.append(f"  WARNING  : bound to {settings.host} with no authentication.")

    # flush=True is not cosmetic. Python block-buffers stdout whenever it
    # isn't a terminal, so under Docker, systemd, or any redirect to a
    # file, this whole banner - including the no-authentication warning -
    # sits in the buffer indefinitely while uvicorn's own logging (which
    # goes to stderr) appears immediately. The result is a log that looks
    # like the server started with nothing registered and nothing to warn
    # about. Flushing costs nothing here and is the difference between the
    # warning being seen and not.
    print("\n".join(banner), flush=True)

    app = mcp.streamable_http_app()
    # Where a human approves anything gated - deliberately a plain HTTP
    # route rather than a tool, so the model can't approve its own
    # requests. See approval_routes.py.
    install_approval_routes(app)

    uvicorn.run(app, host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()