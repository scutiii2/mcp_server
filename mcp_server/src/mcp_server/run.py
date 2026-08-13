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
# (No capabilities registered yet.)


def main() -> None:
    import asyncio

    import uvicorn

    tool_names = sorted(t.name for t in asyncio.run(mcp.list_tools()))

    # Resource listing is best-effort for this startup banner: FastMCP
    # may expose templated resources (ones with a {placeholder} in their
    # URI) via a differently-named method than concrete resources. Rather
    # than guess and risk crashing startup over a cosmetic banner line,
    # fall back to "unknown" if neither call works as expected - verify
    # the real count against your installed version.
    resource_count: int | str
    try:
        resource_count = len(asyncio.run(mcp.list_resources()))
    except Exception:
        try:
            resource_count = len(asyncio.run(mcp.list_resource_templates()))
        except Exception:
            resource_count = "unknown - verify against your installed mcp version"

    from mcp_server.approval_routes import install_approval_routes
    from mcp_server.infra import approvals

    print("MCP server")
    print(f"  Endpoint : http://{settings.host}:{settings.port}/mcp")
    print(f"  Config   : {settings.config_path}")
    print(f"  Tools    : {len(tool_names)}")
    for name in tool_names:
        print(f"    - {name}")
    print(f"  Resources: {resource_count}")
    print(f"  Gated    : {', '.join(approvals.registered_names()) or 'none'}")
    if settings.host not in {"127.0.0.1", "localhost", "::1"}:
        # Worth shouting about: there is no authentication on this server,
        # so a non-loopback bind means anything that can route to this
        # port can call every tool above with arguments of its choosing.
        print(f"  WARNING  : bound to {settings.host} with no authentication.")

    app = mcp.streamable_http_app()
    # Where a human approves anything gated - deliberately a plain HTTP
    # route rather than a tool, so the model can't approve its own
    # requests. See approval_routes.py.
    install_approval_routes(app)

    uvicorn.run(app, host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()