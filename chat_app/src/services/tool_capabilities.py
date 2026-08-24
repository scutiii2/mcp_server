"""Capability-group ids for MCP built-in tools and resources.

This solves the same problem ``tool_titles.py`` solves for display titles,
for a different axis: which "capability" (source-of-truth folder under
``mcp_server/src/capabilities/<name>/``, see that package's docstring) a
given built-in tool or resource belongs to, so the capabilities page can
group them into their own collapsible accordion sections the same way
extension tools are already grouped by extension - and, since mcp_server
grew a live enable/disable toggle for capabilities, so the page can wire
each group's switch to the exact name mcp_server's ``PATCH
/capabilities/{name}`` route expects.

This lives on the Flask side, not the MCP server side, for the exact same
reason ``tool_titles.py`` does: newer versions of the MCP spec/FastMCP
*might* grow some notion of grouping/namespacing tools, but relying on
that is an assumption about an installed package version this scaffold
can't verify. Hand-maintaining a small map here works regardless of what
the installed ``mcp`` version supports, and needs no changes to
``mcp_server`` or the wire protocol at all.

The map below holds real capability **ids** (``"host_health"``, ``"otp"``
- the same strings mcp_server's ``GET /capabilities``,
``config_capabilities.json``, and ``PATCH /capabilities/{name}`` all use)
- never a display label or a shortened alias. Those are a *different*
concern that mcp_server now owns per-capability (``TITLE``/``COMMAND_ID``
in each ``capabilities/<name>/__init__.py`` - see
``infra/capability_metadata.py``'s docstring on that side) and fetches
live from ``GET /capabilities`` (see ``pages/Capabilities/__index__.py``'s
``_fetch_capabilities_meta_or_empty()``), precisely so this file never has
to hand-maintain a second map that can drift from the first. Putting
anything other than a real capability id in this map breaks the toggle
switch for that capability - it would PATCH a name mcp_server has never
heard of.

Maintenance: every time a new capability folder is added to
``mcp_server/src/capabilities/`` (see that package's "Add a new
capability" docstring - it already requires a manual edit to ``run.py``),
add its tool name(s) here too. A tool with no entry isn't dropped - see
``capability_for_tool()`` - it just falls into a generic fallback group so
nothing silently disappears if this map goes stale. A fallback-grouped
tool has no real capability id, so its group renders with no toggle
switch at all - see capabilities.html.
"""

from __future__ import annotations

# Explicit tool name -> capability id overrides. Keys are full tool
# names as they come back from list_tools() (e.g. "get_host_health_tool"),
# not extension-namespaced names - extension tools are grouped by
# extension already and never consult this map (see __index__.py).
_TOOL_CAPABILITIES: dict[str, str] = {
    "get_host_health_tool": "host_health",

    "request_otp_tool": "otp",
    "verify_otp_tool": "otp",

    "crafty_world_register": "crafty",
    "crafty_world_list": "crafty",
    "crafty_world_start": "crafty",
    "crafty_world_stop": "crafty",
    "crafty_world_restart": "crafty",
    "crafty_world_send_command": "crafty",
    "crafty_world_get_status": "crafty",
    "crafty_set_default_base_url": "crafty",
    "crafty_world_remove": "crafty",
    "crafty_ping_base_url": "crafty",

    "start_app_tool": "server_manager",
    "stop_app_tool": "server_manager",
    "restart_app_tool": "server_manager",
    "list_apps_tool": "server_manager",
}

# Id used for any built-in tool with no entry above - keeps a future
# capability visible (grouped generically) instead of disappearing if
# this map isn't updated the same day mcp_server grows one. Not a real
# mcp_server capability id, so it never gets a toggle switch - see
# is_real_capability() below.
_FALLBACK_ID = "other"


def capability_for_tool(tool_name: str) -> str:
    return _TOOL_CAPABILITIES.get(tool_name, _FALLBACK_ID)


# Resources are a separate namespace from tools (a resource's ``name`` is
# not a tool name - see resources/host_health/resource.py's
# ``@mcp.resource(...)``-decorated function), so this is a distinct dict
# rather than folded into ``_TOOL_CAPABILITIES`` above, even though today
# it happens to map to the same "host_health" id as
# ``get_host_health_tool`` above (per run.py's comment: the resource
# serves clients that read a URI, the tool serves models deciding to call
# it - same domain logic underneath, same toggle), so it groups under the
# same id.
_RESOURCE_CAPABILITIES: dict[str, str] = {
    "host_health": "host_health",
}


def capability_for_resource(resource_name: str) -> str:
    return _RESOURCE_CAPABILITIES.get(resource_name, _FALLBACK_ID)


def resource_capability_ids() -> set[str]:
    """Every capability id that owns at least one resource - used to seed
    a resource group for a capability that's currently disabled (so its
    resource template is briefly absent from mcp_server's live list, see
    __index__.py's _group_resources_by_capability) without also seeding
    an empty, pointless resource group for a tool-only capability like
    "otp"."""
    return set(_RESOURCE_CAPABILITIES.values())


def is_real_capability(capability_id: str) -> bool:
    """False for the fallback group ("Other") - which is not a real
    mcp_server capability id and must never be sent to
    ``PATCH /capabilities/{name}``."""
    return capability_id != _FALLBACK_ID
