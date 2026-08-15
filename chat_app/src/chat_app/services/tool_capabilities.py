"""Capability-group labels for MCP built-in tools and resources.

This solves the same problem ``tool_titles.py`` solves for display titles,
for a different axis: which "capability" (source-of-truth folder under
``mcp_server/src/mcp_server/capabilities/<name>/``, see that package's
docstring) a given built-in tool or resource belongs to, so the
capabilities page can group them into their own collapsible accordion
sections the same way extension tools are already grouped by extension.

This lives on the Flask side, not the MCP server side, for the exact same
reason ``tool_titles.py`` does: newer versions of the MCP spec/FastMCP
*might* grow some notion of grouping/namespacing tools, but relying on
that is an assumption about an installed package version this scaffold
can't verify. Hand-maintaining a small map here works regardless of what
the installed ``mcp`` version supports, and needs no changes to
``mcp_server`` or the wire protocol at all.

Maintenance: every time a new capability folder is added to
``mcp_server/src/mcp_server/capabilities/`` (see that package's "Add a new
capability" docstring - it already requires a manual edit to ``run.py``),
add its tool name(s) here too. A tool with no entry isn't dropped - see
``capability_for_tool()`` - it just falls into a generic fallback group so
nothing silently disappears if this map goes stale.
"""

from __future__ import annotations

# Explicit tool name -> capability label overrides. Keys are full tool
# names as they come back from list_tools() (e.g. "get_host_health_tool"),
# not extension-namespaced names - extension tools are grouped by
# extension already and never consult this map (see routes.py).
_TOOL_CAPABILITIES: dict[str, str] = {
    "get_host_health_tool": "Host Health",
    "request_otp_tool": "OTP",
    "verify_otp_tool": "OTP",
}

# Label used for any built-in tool with no entry above - keeps a future
# capability visible (grouped generically) instead of disappearing if
# this map isn't updated the same day mcp_server grows one.
_FALLBACK_LABEL = "Other"


def capability_for_tool(tool_name: str) -> str:
    return _TOOL_CAPABILITIES.get(tool_name, _FALLBACK_LABEL)


# Resources are a separate namespace from tools (a resource's ``name`` is
# not a tool name - see resources/host_health/resource.py's
# ``@mcp.resource(...)``-decorated function), so this is a distinct dict
# rather than folded into ``_TOOL_CAPABILITIES`` above, even though today
# it happens to produce the same "Host Health" label for its one entry.
# ``host_health`` here is the SAME underlying capability as
# ``get_host_health_tool`` above (per run.py's comment: the resource
# serves clients that read a URI, the tool serves models deciding to call
# it - same domain logic underneath), so it groups under the same label.
_RESOURCE_CAPABILITIES: dict[str, str] = {
    "host_health": "Host Health",
}

_RESOURCE_FALLBACK_LABEL = "Other"


def capability_for_resource(resource_name: str) -> str:
    return _RESOURCE_CAPABILITIES.get(resource_name, _RESOURCE_FALLBACK_LABEL)
