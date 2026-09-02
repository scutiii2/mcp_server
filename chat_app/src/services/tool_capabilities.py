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

The tool/resource -> capability mapping is never hand-maintained here:
mcp_server's own capability_registry auto-discovers exactly which tools
and resource templates each capability registered (see that module's
``capturing()`` docstring), and ``GET /capabilities`` now reports those
names directly (see capability_routes.py's docstring on that side) -
alongside ``title``/``command_id``, which already worked this way. The
functions below just build a reverse lookup from that live data, keyed by
tool/resource name, so a tool with no known capability (an unmapped
extension tool, or a deployment whose mcp_server predates this field)
falls into a generic fallback group rather than disappearing - see
``capability_for_tool()``. A fallback-grouped tool has no real capability
id, so its group renders with no toggle switch at all - see
capabilities.html.
"""

from __future__ import annotations

# Id used for any tool/resource whose owning capability isn't known from
# the live data - keeps it visible (grouped generically) instead of
# disappearing when mcp_server is unreachable or predates this field.
# Not a real mcp_server capability id, so it never gets a toggle switch -
# see is_real_capability() below.
_FALLBACK_ID = "other"


def _reverse_lookup(capabilities_meta: dict[str, dict], field: str) -> dict[str, str]:
    return {
        name: capability_id
        for capability_id, meta in capabilities_meta.items()
        for name in meta.get(field, [])
    }


def capability_for_tool(tool_name: str, capabilities_meta: dict[str, dict]) -> str:
    """`capabilities_meta` is the live ``{capability_id: status}`` dict
    from mcp_server's ``GET /capabilities`` (see pages/Capabilities/
    __index__.py's ``_fetch_capabilities_meta_or_empty()``), each status
    carrying a ``"tools"`` list of the tool names that capability owns."""
    return _reverse_lookup(capabilities_meta, "tools").get(tool_name, _FALLBACK_ID)


def capability_for_resource(resource_name: str, capabilities_meta: dict[str, dict]) -> str:
    """Same as capability_for_tool() above, for a status's ``"resources"``
    list - a separate namespace from tools, so a resource name colliding
    with an unrelated tool name never picks up that tool's capability."""
    return _reverse_lookup(capabilities_meta, "resources").get(resource_name, _FALLBACK_ID)


def resource_capability_ids(capabilities_meta: dict[str, dict]) -> set[str]:
    """Every capability id that owns at least one resource - used to seed
    a resource group for a capability that's currently disabled (so its
    resource template is briefly absent from mcp_server's live list, see
    __index__.py's _group_resources_by_capability) without also seeding
    an empty, pointless resource group for a tool-only capability like
    "otp"."""
    return {capability_id for capability_id, meta in capabilities_meta.items() if meta.get("resources")}


def is_real_capability(capability_id: str) -> bool:
    """False for the fallback group ("Other") - which is not a real
    mcp_server capability id and must never be sent to
    ``PATCH /capabilities/{name}``."""
    return capability_id != _FALLBACK_ID
