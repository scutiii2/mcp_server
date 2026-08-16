"""Live capability browser for the MCP server's tool AND resource catalog.

Nothing here is hardcoded - every request calls list_tools()/
list_resource_templates() on the MCP server, so this page (and the
try-it console on it) always reflects whatever's actually registered
right now, even if the MCP server was redeployed five minutes ago with
new capabilities added.

This blueprint owns everything under ``pages/capabilities/`` - both its
routes and its own ``template/`` folder. See ``pages/chat/routes.py`` and
``app.py`` for why the static/template wiring looks the way it does.
"""

from __future__ import annotations

import re

from flask import Blueprint, jsonify, render_template

from chat_app.auth import service
from chat_app.security import json_body
from chat_app.services.mcp_client import (
    call_tool,
    fetch_extensions,
    list_resource_templates,
    list_tools,
    read_resource,
)
from chat_app.services.tool_capabilities import capability_for_resource, capability_for_tool
from chat_app.services.tool_titles import title_for


capabilities_bp = Blueprint(
    "capabilities",
    __name__,
    url_prefix="/capabilities",
    static_folder="template",
    static_url_path="/pages/capabilities/assets",
)


def _fetch_extensions_or_empty() -> list[dict]:
    """Every extension mcp_server currently has connected, regardless of
    status - used both to unlock list_tools()'s filter for this page and
    to build the per-extension accordion groups below.

    list_tools()'s "omit = show no extension tools" default exists for
    /api/chat, where an unconfigured extension must never be silently in
    scope for the model. This page is the opposite case: a human
    browsing the live catalog, whose entire point (see module docstring)
    is showing everything actually registered. Reusing the same default
    here would make this page quietly lie about what mcp_server exposes.
    The full catalog still round-trips from the server on every request -
    what changed is that the browser (script.js) now hides a disabled
    extension's tools by default once they arrive here, so a human can
    still toggle one on to look, and that same toggle state is what's
    offered to the model in chat.

    Failing open to "no extensions" rather than raising: a broken
    /extensions fetch shouldn't blank out the built-in tools too, since
    those come from a separate call this function doesn't touch.
    """
    try:
        return fetch_extensions()
    except Exception:  # noqa: BLE001 - degrade to built-ins only, don't blank the page
        return []


def _serialize_tools(extensions: list[dict] | None = None) -> list[dict]:
    """Reshape raw MCP Tool objects into plain dicts with a friendly
    title attached - shared by both the page and the JSON API so there's
    one place that knows this shape.

    ``extensions`` is the live extension catalog (``fetch_extensions()``'s
    shape) used to unlock list_tools()'s enabled-extension filter - see
    ``_fetch_extensions_or_empty()``. Fetches its own when not given, so
    the JSON API (which has no other use for the catalog) doesn't need to
    know about this wiring; ``browse()`` passes its own copy in so the
    catalog isn't fetched twice per request.
    """
    if extensions is None:
        extensions = _fetch_extensions_or_empty()
    enabled_ids = [extension["id"] for extension in extensions]

    tools = []
    for tool in list_tools(enabled_extensions=enabled_ids):
        # Same double-underscore convention as mcp_client._tool_is_enabled:
        # extension tools are "{ext_id}__original_name"; built-ins have no
        # such prefix and get extension_id=None.
        ext_id, sep, _ = tool.name.partition("__")
        tools.append(
            {
                "name": tool.name,
                "title": title_for(tool.name),
                "description": tool.description or "",
                "input_schema": tool.inputSchema or {},
                "extension_id": ext_id if sep else None,
            }
        )
    return tools


def _group_tools_by_extension(tools: list[dict], extensions: list[dict]) -> list[dict]:
    """Bucket already-serialized tool dicts under their owning extension,
    for the capabilities page's per-extension accordion groups. Keyed off
    ``extensions`` (not just whatever extension ids happen to show up in
    ``tools``) so a connected extension that currently offers zero tools
    still gets a group with an empty ``tools`` list - that's still useful
    "this extension is connected but offers nothing right now" info, not
    something to silently drop."""
    tools_by_extension: dict[str, list[dict]] = {}
    for tool in tools:
        ext_id = tool["extension_id"]
        if ext_id is not None:
            tools_by_extension.setdefault(ext_id, []).append(tool)

    return [
        {
            "id": extension["id"],
            "label": extension.get("label") or extension["id"],
            "description": extension.get("description") or "",
            "status": extension.get("status"),
            "error": extension.get("error"),
            "tools": tools_by_extension.get(extension["id"], []),
        }
        for extension in extensions
    ]


def _group_tools_by_capability(tools: list[dict]) -> list[dict]:
    """Bucket built-in (non-extension) tool dicts under their capability
    label, for the capabilities page's per-capability accordion groups -
    the built-in equivalent of ``_group_tools_by_extension`` above, same
    ``{label, tools}`` shape minus the extension-only fields (``id``,
    ``status``, ``error``) that don't apply to a built-in grouping - no
    connection status, nothing to toggle.

    Unlike ``_group_tools_by_extension``, there's no upfront catalog of
    known labels to iterate (capability labels come from
    ``tool_capabilities``'s hand-maintained map, not something fetched
    from mcp_server), so groups are built in first-seen order across
    ``tools`` instead. A tool with no entry in that map still lands in a
    group (the "Other" fallback baked into ``capability_for_tool``) rather
    than being dropped - same fail-open reasoning used throughout this
    module: nothing should silently disappear just because the map lagged
    behind a new capability landing in mcp_server. Extension tools are
    skipped entirely here - they're already grouped by extension."""
    grouped: dict[str, list[dict]] = {}
    for tool in tools:
        if tool["extension_id"] is not None:
            continue
        label = capability_for_tool(tool["name"])
        grouped.setdefault(label, []).append(tool)

    return [{"label": label, "tools": tools_for_label} for label, tools_for_label in grouped.items()]


def _group_resources_by_capability(resources: list[dict]) -> list[dict]:
    """Same idea as ``_group_tools_by_capability`` above, for resources.
    Resources have no extension concept at all today (they're all
    built-in), so unlike the tools version there's nothing to skip - every
    resource gets grouped."""
    grouped: dict[str, list[dict]] = {}
    for resource in resources:
        label = capability_for_resource(resource["name"])
        grouped.setdefault(label, []).append(resource)

    return [{"label": label, "resources": resources_for_label} for label, resources_for_label in grouped.items()]


def _extract_uri_params(uri_template: str) -> list[str]:
    """Pull {placeholder} names out of a resource URI template, in order -
    used to render one input field per parameter, the resource-template
    equivalent of a tool's inputSchema properties."""
    return re.findall(r"\{(\w+)\}", uri_template)


def _serialize_resources() -> list[dict]:
    resources = []
    for template in list_resource_templates():
        uri_template = getattr(template, "uriTemplate", None) or getattr(template, "uri_template", "")
        name = getattr(template, "name", "") or ""
        resources.append(
            {
                "name": name,
                "title": title_for(name) if name else uri_template,
                "description": getattr(template, "description", "") or "",
                "uri_template": uri_template,
                "params": _extract_uri_params(uri_template),
            }
        )
    return resources


@capabilities_bp.get("/")
def browse():
    # Fetched once up front and threaded through _serialize_tools() so the
    # accordion grouping below can reuse the exact same catalog rather than
    # hitting mcp_server's /extensions endpoint a second time this request.
    extensions_catalog = _fetch_extensions_or_empty()

    try:
        tools = _serialize_tools(extensions_catalog)
        tools_error = None
    except Exception as exc:  # noqa: BLE001 - surface any error to the page
        tools = []
        tools_error = str(exc)

    try:
        resources = _serialize_resources()
        resources_error = None
    except Exception as exc:  # noqa: BLE001
        resources = []
        resources_error = str(exc)

    # Combined for the single error banner at the top of the page - kept
    # separate above so one section failing doesn't discard the other
    # section's successfully-fetched data.
    error = tools_error or resources_error
    extensions = _group_tools_by_extension(tools, extensions_catalog)
    tool_capability_groups = _group_tools_by_capability(tools)
    resource_capability_groups = _group_resources_by_capability(resources)
    # Login is mandatory app-wide (security.check_login has no
    # unconfigured fallback), so reaching this view at all guarantees a
    # session - current_scopes() can't return None here.
    return render_template(
        "capabilities/index.html",
        tools=tools,
        extensions=extensions,
        tool_capability_groups=tool_capability_groups,
        resources=resources,
        resource_capability_groups=resource_capability_groups,
        error=error,
        username=service.current_username(),
        role=service.current_role(),
        scopes=service.current_scopes() or set(),
        current_page="capabilities",
    )


@capabilities_bp.get("/api/tools")
def api_tools():
    return jsonify(_serialize_tools())


@capabilities_bp.get("/api/resources")
def api_resources():
    return jsonify(_serialize_resources())


@capabilities_bp.post("/api/try/<tool_name>")
def try_tool(tool_name: str):
    """Call a tool directly, bypassing chat/OpenAI entirely - for debugging."""
    arguments = json_body()
    try:
        result = call_tool(tool_name, arguments)
        return jsonify({"status": "ok", "result": result})
    except Exception as exc:  # noqa: BLE001
        return jsonify({"status": "error", "message": str(exc)}), 500


@capabilities_bp.post("/api/read-resource")
def read_resource_route():
    """Read a resource directly by its concrete URI (placeholders already
    filled in client-side), bypassing chat entirely - same idea as
    try_tool but for resources. The URI goes in the JSON body rather than
    the URL path since it contains characters (:// and further /) that
    don't play nicely as a single path segment."""
    data = json_body()
    uri = (data.get("uri") or "").strip()
    if not uri:
        return jsonify({"status": "error", "message": "Missing uri"}), 400
    try:
        result = read_resource(uri)
        return jsonify({"status": "ok", "result": result})
    except Exception as exc:  # noqa: BLE001
        return jsonify({"status": "error", "message": str(exc)}), 500
