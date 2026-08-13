"""SAP control tools - list available SIDs, stop/start systems.

Each function here is intentionally a few lines: load config, call the
domain function, return its typed result. If a tool needs more logic than
that, the logic belongs in ``domain/``, not here.
"""

from __future__ import annotations

from mcp_server.capabilities.control.contract import (
    AvailableSidsResult,
    MultiSapControlResult,
    SapControlRequest,
)
from mcp_server.capabilities.control.domain import get_available_sids, start_sap_system, stop_sap_system
from mcp_server.config import settings
from mcp_server.infra.sap_config import load_config
from mcp_server.server import mcp


@mcp.tool(description="List available SAP System IDs from config.json - use this to see which SIDs can be stopped/started/managed.")
def get_available_sids_tool() -> AvailableSidsResult:
    config = load_config(settings.config_path)
    return get_available_sids(config)


@mcp.tool(description=(
    "Stop one or more SAP systems by SID (comma-separated for multiple, e.g. 'S4E,E4G'). "
    "Orchestrates the full landscape: additional app servers, then PAS, then ASCS, then DB. "
    "Confirm with the user before calling - this is destructive."
))
def stop_sap_system_tool(sid: str) -> MultiSapControlResult:
    config = load_config(settings.config_path)
    return stop_sap_system(SapControlRequest(sid=sid), config=config)


@mcp.tool(description=(
    "Start one or more SAP systems by SID (comma-separated for multiple, e.g. 'S4E,E4G'). "
    "Orchestrates the full landscape: DB, then ASCS, then PAS, then additional app servers. "
    "Confirm with the user before calling."
))
def start_sap_system_tool(sid: str) -> MultiSapControlResult:
    config = load_config(settings.config_path)
    return start_sap_system(SapControlRequest(sid=sid), config=config)
