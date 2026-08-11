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

# Import order = the order tools appear in list_tools(). Add each new
# capability's tool module here as it's built.
from mcp_server.capabilities.control import tool as control_tool  # noqa: F401,E402


def main() -> None:
    import asyncio

    import uvicorn

    tool_names = sorted(t.name for t in asyncio.run(mcp.list_tools()))
    print("SAP AIOps MCP server")
    print(f"  Endpoint : http://{settings.host}:{settings.port}/mcp")
    print(f"  Config   : {settings.config_path}")
    print(f"  Tools    : {len(tool_names)}")
    for name in tool_names:
        print(f"    - {name}")

    uvicorn.run(mcp.streamable_http_app(), host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()
