"""Human-friendly display titles for MCP tools.

MCP tool names are snake_case identifiers meant for machines
(``stop_sap_system_tool``) - not something you'd want as a page heading.
This lives on the Flask side, not the MCP server side, deliberately: newer
versions of the MCP spec/FastMCP may support a ``title`` field directly on
``@mcp.tool()``, but that's an assumption about an installed package
version this scaffold can't verify without the real package available.
This approach works regardless of what your installed ``mcp`` version
supports, and needs no changes to ``mcp_server`` at all.
"""

from __future__ import annotations

# Explicit overrides for tools whose auto-generated title wouldn't read
# well (acronyms, awkward capitalization, etc). Add an entry here as new
# tools are built if the auto-generated fallback below looks wrong -
# common culprits are SAP-specific acronyms (SAP, SID, ABAP, HANA, SSH).
_OVERRIDES: dict[str, str] = {
    "stop_sap_system_tool": "Stop SAP System",
}


def title_for(tool_name: str) -> str:
    if tool_name in _OVERRIDES:
        return _OVERRIDES[tool_name]
    name = tool_name[:-5] if tool_name.endswith("_tool") else tool_name
    return name.replace("_", " ").strip().title() or tool_name
