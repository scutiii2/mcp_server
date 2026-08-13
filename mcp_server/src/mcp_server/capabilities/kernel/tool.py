"""SAP kernel update tool."""

from __future__ import annotations

from mcp_server.capabilities.kernel.contract import KernelUpdateRequest
from mcp_server.capabilities.kernel.domain import apply_kernel_update
from mcp_server.config import settings
from mcp_server.infra.sap_config import load_config
from mcp_server.server import mcp


@mcp.tool(description=(
    "Apply SAP Kernel Update. Use for kernel update, kernel upgrade, kernel patch, "
    "update kernel libraries, update kernel files, upgrade SAP kernel, patch SAP kernel. "
    "Stops SAP, updates kernel binaries, restarts SAP. Always requires confirmation before execution."
))
def apply_kernel_update_tool(sid: str) -> str:
    config = load_config(settings.config_path)
    return apply_kernel_update(KernelUpdateRequest(sid=sid), config=config)
