"""Human-friendly display titles for MCP tools.

MCP tool names are snake_case identifiers meant for machines
(``restart_service_tool``) - not something you'd want as a page heading.

This lives on the Flask side, not the MCP server side, deliberately: newer
versions of the MCP spec/FastMCP may support a ``title`` field directly on
``@mcp.tool()``, but that's an assumption about an installed package
version this scaffold can't verify without the real package available.
This approach works regardless of what your installed ``mcp`` version
supports, and needs no changes to ``mcp_server`` at all.
"""

from __future__ import annotations

# Explicit overrides for tools whose auto-generated title wouldn't read
# well. The fallback below just title-cases the name, which mangles
# acronyms and initialisms ("get_cpu_usage_tool" -> "Get Cpu Usage") - so
# that's the usual reason to add an entry here:
#
#     "get_cpu_usage_tool": "Get CPU Usage",
#
# Empty until there are tools to title; every name falls through to the
# automatic version below, which is correct for most ordinary names.
_OVERRIDES: dict[str, str] = {}


def title_for(tool_name: str) -> str:
    if tool_name in _OVERRIDES:
        return _OVERRIDES[tool_name]
    name = tool_name[:-5] if tool_name.endswith("_tool") else tool_name
    return name.replace("_", " ").strip().title() or tool_name
