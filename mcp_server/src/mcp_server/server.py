"""Shared FastMCP server instance.

Keep this file free of tool definitions - it exists only so every module
under ``tools/`` can import the same ``mcp`` object to register onto.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

mcp = FastMCP(
    name="sap-aiops",
    instructions=(
        "SAP AIOps tool server. Tools are grouped by domain: monitoring, "
        "control, kernel update, rename, conversion, and provisioning. "
        "Each tool's own description states when to use it - prefer that "
        "over guessing from the name."
    ),
)
