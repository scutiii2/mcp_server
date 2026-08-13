"""SAP health tools - infrastructure assessment + maintenance mode."""

from __future__ import annotations

from mcp_server.capabilities.health.contract import MaintenanceModeRequest, SidRequest
from mcp_server.capabilities.health.domain import get_maintenance_status, get_system_health, set_maintenance_mode
from mcp_server.config import settings
from mcp_server.infra.sap_config import load_config
from mcp_server.server import mcp


@mcp.tool(description=(
    "PRIMARY TOOL FOR OVERALL SYSTEM HEALTH. Use for: overall health, detailed component status, "
    "infrastructure health, OS health, server health, health summary, health score. Returns: "
    "CPU, Memory, Swap, Disk, SAP Services, Database, Kernel, Network Connectivity, Health Score and Recommendations."
))
def get_system_health_tool(sid: str) -> str:
    config = load_config(settings.config_path)
    return get_system_health(SidRequest(sid=sid), config=config)


@mcp.tool(description="Check which SAP systems are currently in maintenance mode.")
def get_maintenance_status_tool() -> str:
    return get_maintenance_status(maintenance_path=settings.maintenance_path)


@mcp.tool(description="Enable or disable maintenance mode for a SAP system. While in maintenance, alerts are suppressed.")
def set_maintenance_mode_tool(sid: str, enable: bool) -> str:
    return set_maintenance_mode(MaintenanceModeRequest(sid=sid, enable=enable), maintenance_path=settings.maintenance_path)
