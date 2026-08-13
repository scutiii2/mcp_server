"""Entry point for the SAP AIOps MCP server.

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
# list calls. Add each new capability's tool/resource module here as
# it's built.
from mcp_server.capabilities.control import tool as control_tool  # noqa: F401,E402
from mcp_server.capabilities.conversion import tool as conversion_tool  # noqa: F401,E402
from mcp_server.capabilities.dumps import tool as dumps_tool  # noqa: F401,E402
from mcp_server.capabilities.health import tool as health_tool  # noqa: F401,E402
from mcp_server.capabilities.jobs import tool as jobs_tool  # noqa: F401,E402
from mcp_server.capabilities.kernel import tool as kernel_tool  # noqa: F401,E402
from mcp_server.capabilities.monitoring import tool as monitoring_tool  # noqa: F401,E402
from mcp_server.capabilities.user_provisioning import tool as user_provisioning_tool  # noqa: F401,E402
from mcp_server.capabilities.user_provisioning.approval_routes import (  # noqa: E402
    approve_and_execute,
    show_approval_page,
)
from mcp_server.resources.job_history import resource as job_history_resource  # noqa: F401,E402


def main() -> None:
    import asyncio

    import uvicorn

    tool_names = sorted(t.name for t in asyncio.run(mcp.list_tools()))

    # Resource listing is best-effort for this startup banner: FastMCP
    # may expose templated resources (ones with a {placeholder} in their
    # URI, like job_history_resource) via a differently-named method than
    # concrete resources. Rather than guess and risk crashing startup over
    # a cosmetic banner line, fall back to "unknown" if neither call works
    # as expected - verify the real count against your installed version.
    resource_count: int | str
    try:
        resource_count = len(asyncio.run(mcp.list_resources()))
    except Exception:
        try:
            resource_count = len(asyncio.run(mcp.list_resource_templates()))
        except Exception:
            resource_count = "unknown - verify against your installed mcp version"

    print("SAP AIOps MCP server")
    print(f"  Endpoint : http://{settings.host}:{settings.port}/mcp")
    print(f"  Config   : {settings.config_path}")
    print(f"  Tools    : {len(tool_names)}")
    for name in tool_names:
        print(f"    - {name}")
    print(f"  Resources: {resource_count}")

    app = mcp.streamable_http_app()
    # Plain HTTP routes, deliberately NOT MCP tools - see
    # capabilities/user_provisioning/approval_routes.py's module
    # docstring for why the execute step must only be reachable this way.
    app.add_route("/approvals/user-provisioning/{token}", show_approval_page, methods=["GET"])
    app.add_route("/approvals/user-provisioning/{token}", approve_and_execute, methods=["POST"])
    print(f"  Approvals: http://{settings.host}:{settings.port}/approvals/user-provisioning/<token>")

    uvicorn.run(app, host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()