"""Capability-group ids and labels for MCP built-in tools and resources.

This solves the same problem ``tool_titles.py`` solves for display titles,
for a different axis: which "capability" (source-of-truth folder under
``mcp_server/src/capabilities/<name>/``, see that package's docstring) a
given built-in tool or resource belongs to, so the capabilities page can
group them into their own collapsible accordion sections the same way
extension tools are already grouped by extension - and, since mcp_server
grew a live enable/disable toggle for capabilities, so the page can wire
each group's switch to the exact name mcp_server's ``PATCH
/capabilities/{name}`` route expects.

Unlike the version of this file that used to exist, none of this is
hand-maintained here anymore. mcp_server's ``GET /capabilities`` now
returns each capability's id, display ``label``, and the tool/resource
names it owns (see ``capability_routes.py`` and ``infra/capability_meta.py``
on that side) - a new capability, or a new tool inside an existing one,
needs zero changes in this file. ``refresh_from()`` is how that live
response gets in: called by ``pages/Capabilities/__index__.py`` every
time ``mcp_client.fetch_capabilities()`` succeeds.

The catch is that this data now depends on having reached mcp_server at
least once. Rather than falling back to the generic "other" group every
time mcp_server happens to be briefly unreachable - which, before this
module fetched anything live, would have been *every* request - the
last successful response is cached to disk (``settings.capability_cache_path``)
and reloaded at import time, so a request that lands between restarts,
or during a transient mcp_server outage, still groups every
previously-seen tool correctly. Only a tool neither the live response
nor the cache has ever heard of falls into "other" - see
``capability_for_tool()``.
"""

from __future__ import annotations

import json
from pathlib import Path

from src.services.llm.settings import settings

# Id used for any built-in tool with no known capability - keeps a tool
# visible (grouped generically) instead of disappearing if it's genuinely
# new (mcp_server has never reported it, live or cached). Not a real
# mcp_server capability id, so it never gets a toggle switch - see
# label_for_capability()/is_real_capability() below.
_FALLBACK_ID = "other"

_tool_to_capability: dict[str, str] = {}
_resource_to_capability: dict[str, str] = {}
_labels: dict[str, str] = {_FALLBACK_ID: "Other"}


def _cache_path() -> Path:
    return settings.capability_cache_path


def _load_cached() -> list[dict]:
    try:
        data = json.loads(_cache_path().read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError, OSError):
        return []
    return data if isinstance(data, list) else []


def _save_cache(capabilities: list[dict]) -> None:
    path = _cache_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(capabilities, indent=2), encoding="utf-8")
    except OSError:
        pass  # best-effort cache - a write failure must not break the live caller


def _apply(capabilities: list[dict]) -> None:
    global _tool_to_capability, _resource_to_capability, _labels
    tool_map: dict[str, str] = {}
    resource_map: dict[str, str] = {}
    labels: dict[str, str] = {_FALLBACK_ID: "Other"}

    for entry in capabilities:
        name = entry.get("name")
        if not name:
            continue
        labels[name] = entry.get("label") or name
        for tool_name in entry.get("tools") or []:
            tool_map[tool_name] = name
        for resource_name in entry.get("resources") or []:
            resource_map[resource_name] = name

    _tool_to_capability, _resource_to_capability, _labels = tool_map, resource_map, labels


# Seed from whatever the last successful refresh_from() call left on disk -
# empty (everything falls back to "other" until the first live fetch) on a
# brand-new install that has never reached mcp_server even once.
_apply(_load_cached())


def refresh_from(capabilities: list[dict]) -> None:
    """Rebuild every map below from a fresh ``GET /capabilities`` response
    (``mcp_client.fetch_capabilities()``'s return value) and persist it to
    disk. Call this every time that fetch succeeds - see
    ``pages/Capabilities/__index__.py``'s ``_fetch_capability_states_or_empty()``.
    Never call this with a failed/empty fetch result "just to be safe":
    doing so would overwrite a good cache with nothing the moment
    mcp_server is briefly unreachable, exactly the problem this module
    exists to avoid.
    """
    _apply(capabilities)
    _save_cache(capabilities)


def capability_for_tool(tool_name: str) -> str:
    return _tool_to_capability.get(tool_name, _FALLBACK_ID)


# Resources are a separate namespace from tools (a resource's ``name`` is
# not a tool name - see resources/README.md's ``@mcp.resource(...)``
# pattern), so this is a distinct dict rather than folded into
# ``_tool_to_capability`` above.


def capability_for_resource(resource_name: str) -> str:
    return _resource_to_capability.get(resource_name, _FALLBACK_ID)


def resource_capability_ids() -> set[str]:
    """Every capability id that owns at least one resource - used to seed
    a resource group for a capability that's currently disabled (so its
    resource template is briefly absent from mcp_server's live list, see
    __index__.py's _group_resources_by_capability) without also seeding
    an empty, pointless resource group for a tool-only capability like
    a tool-only one."""
    return set(_resource_to_capability.values())


def label_for_capability(capability_id: str) -> str:
    # Falls back to the id itself (not _FALLBACK_ID's label) for a real
    # capability id this process hasn't seen a label for yet - same
    # "don't silently disappear" reasoning as capability_for_tool()'s
    # fallback.
    return _labels.get(capability_id, capability_id)


def known_labels() -> dict[str, str]:
    """``{capability_id: label}`` for every real capability seen so far
    (live or cached) - what the Chat page's suggestion bar shows."""
    return {i: label for i, label in _labels.items() if i != _FALLBACK_ID}


def is_real_capability(capability_id: str) -> bool:
    """False for the fallback group ("Other") - which is not a real
    mcp_server capability id and must never be sent to
    ``PATCH /capabilities/{name}``."""
    return capability_id != _FALLBACK_ID


def _known_ids() -> set[str]:
    return {capability_id for capability_id in _labels if capability_id != _FALLBACK_ID}


def _bootstrap_from_mcp_server() -> None:
    """Last resort for known_capability_ids() below: a live fetch this
    module makes for itself, rather than waiting for some other page to
    have made one first. Imports mcp_client locally - most callers of
    this module never hit the cold path that needs it, so there's no
    reason to pay for that dependency at import time for all of them."""
    from src.services import mcp_client

    try:
        refresh_from(mcp_client.fetch_capabilities())
    except Exception:  # noqa: BLE001 - mcp_server still unreachable; caller's own
        # validation reports "unknown capability" same as it would have
        # without this attempt, so there's nothing more useful to do here.
        pass


def known_capability_ids() -> set[str]:
    """Every real mcp_server capability id this process has seen (live or
    cached) - excludes the fallback "other" group, same reasoning as
    is_real_capability(). Used to validate a capability id.

    Empty only means "nothing has EVER been fetched or cached" - a
    brand-new install where no page has called refresh_from() yet, and
    the on-disk cache (settings.capability_cache_path) doesn't exist
    either. Rather than reject a perfectly real capability id just
    because of that ordering accident, this makes one just-in-time live
    attempt of its own before answering - see _bootstrap_from_mcp_server()
    above. A genuinely unreachable mcp_server still means an empty
    result, exactly as before this existed.
    """
    ids = _known_ids()
    if ids:
        return ids
    _bootstrap_from_mcp_server()
    return _known_ids()
