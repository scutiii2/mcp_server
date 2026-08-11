"""SAP control tools - stop/start systems.

Each function here is intentionally a few lines: load config, call the
domain function, return its typed result. If a tool needs more logic than
that, the logic belongs in ``domain/``, not here.
"""

from __future__ import annotations

from mcp_server.capabilities.control.contract import StopSapRequest, StopSapResult
from mcp_server.capabilities.control.domain import stop_sap_system
from mcp_server.config import settings
from mcp_server.infra.sap_config import load_config
from mcp_server.server import mcp


@mcp.tool(description="Stop a SAP system by SID. Confirm with the user before calling - this is destructive.")
def stop_sap_system_tool(sid: str) -> StopSapResult:
    config = load_config(settings.config_path)
    return stop_sap_system(StopSapRequest(sid=sid), config=config)
