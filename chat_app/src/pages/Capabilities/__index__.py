"""Live capability browser for the MCP server's tool AND resource catalog.

Nothing here is hardcoded - every request calls list_tools()/
list_resource_templates() on the MCP server, so this page (and the
try-it console on it) always reflects whatever's actually registered
right now. Ported from MCPArchitecture's
chat_app/src/chat_app/pages/capabilities/routes.py - see
docs/superpowers/specs/2026-08-22-chat-capabilities-port-design.md.
"""

from __future__ import annotations

import json
import re
import urllib.error

from flask import Blueprint, abort, jsonify, render_template, request
from flask_login import current_user

from src.services.authz import has_permission, register_permission, require_login, require_permission
from src.services.mcp_client import (
    call_tool,
    fetch_capabilities,
    fetch_extensions,
    list_resource_templates,
    list_tools,
    read_resource,
    set_capability_enabled,
)
from src.services.tool_capabilities import (
    capability_for_resource,
    capability_for_tool,
    is_real_capability,
    resource_capability_ids,
)
from src.services.tool_titles import title_for


blueprint = Blueprint(
    "capabilities", __name__, template_folder=".", static_folder=".", static_url_path="/static"
)

PAGE_PERMISSION = ("capabilities.view", "capabilities.try", "capabilities.manage")
PAGE_DESCRIPTION = "Browse and try MCP server tools and resources live."
PAGE_LAYOUT = "full"
CSRF_EXEMPT = True

register_permission("capabilities.view")
register_permission("capabilities.try")
# Separate from "try": toggling a capability changes what mcp_server
# offers to every caller (any chat_app user, any other MCP client), not
# just this session's own tool call - a different, higher risk tier than
# "try" grants, so it's a permission of its own rather than piggybacking
# on capabilities.try.
register_permission("capabilities.manage")


def _fetch_extensions_or_empty() -> list[dict]:
    try:
        return fetch_extensions()
    except Exception:  # noqa: BLE001 - degrade to built-ins only, don't blank the page
        return []


def _fetch_capabilities_meta_or_empty() -> dict[str, dict]:
    """{"host_health": {"enabled": True, "title": "Host Health",
    "command_id": "host", "tools": ["get_host_health_tool"],
    "resources": ["host_health"]}, ...} - live from mcp_server, not the
    config file, so a change made from another tab/user (or a
    TITLE/COMMAND_ID edited in that capability's own __init__.py, or a
    tool/resource a capability newly registers) shows up on the next page
    load. Same degrade-gracefully reasoning as _fetch_extensions_or_empty():
    an unreachable mcp_server shouldn't blank the whole page, it should
    just mean no toggle state (and no switches, see capabilities.html) is
    shown, and every tool/resource falls into the "other" fallback group
    (see tool_capabilities.py) - and _capability_group_meta below falls
    back to the id itself when a capability has no entry here at all."""
    try:
        return {status["name"]: status for status in fetch_capabilities()}
    except Exception:  # noqa: BLE001
        return {}


def _serialize_tools(extensions: list[dict] | None = None) -> list[dict]:
    if extensions is None:
        extensions = _fetch_extensions_or_empty()
    enabled_ids = [extension["id"] for extension in extensions]

    tools = []
    for tool in list_tools(enabled_extensions=enabled_ids):
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


def _capability_group_meta(capability_id: str, capabilities_meta: dict[str, dict]) -> dict:
    """The id/label/enabled/toggleable fields common to a tool group and
    a resource group - factored out so the two group functions below
    can't drift on what a "capability group" carries.

    ``label`` comes from mcp_server's own ``title`` for this id
    (TITLE in that capability's own __init__.py - see
    infra/capability_metadata.py on that side), falling back to the raw
    id when mcp_server didn't report it at all (unreachable mcp_server,
    or a real capability id this deployment's mcp_server predates) -
    same reasoning ``enabled``'s True default and tool_capabilities.py's
    ``capability_for_tool()`` fallback both use: a capability this page
    doesn't fully know about yet must still show up, not vanish.
    """
    meta = capabilities_meta.get(capability_id, {})
    return {
        "id": capability_id,
        "label": meta.get("title") or capability_id,
        "enabled": meta.get("enabled", True),
        "toggleable": is_real_capability(capability_id) and capability_id in capabilities_meta,
    }


def _group_tools_by_capability(tools: list[dict], capabilities_meta: dict[str, dict]) -> list[dict]:
    # Seeded from capabilities_meta, not just from `tools`: a disabled
    # capability has no tools in the live list at all (mcp_server never
    # registered them), so building groups purely from `tools` would
    # make a disabled capability's group vanish - with no switch left
    # anywhere on the page to turn it back on. Seeding first means every
    # capability mcp_server knows about always gets a group, empty or not.
    grouped: dict[str, list[dict]] = {name: [] for name in capabilities_meta}
    for tool in tools:
        if tool["extension_id"] is not None:
            continue
        capability_id = capability_for_tool(tool["name"], capabilities_meta)
        grouped.setdefault(capability_id, []).append(tool)

    return [
        {**_capability_group_meta(capability_id, capabilities_meta), "tools": tools_for_id}
        for capability_id, tools_for_id in grouped.items()
    ]


def _group_resources_by_capability(resources: list[dict], capabilities_meta: dict[str, dict]) -> list[dict]:
    # Same "seed before populating" reasoning as _group_tools_by_capability
    # above, scoped to capabilities that actually own a resource - seeding
    # from every known capability would also produce an empty, pointless
    # resource group for a tool-only capability like "otp".
    grouped: dict[str, list[dict]] = {name: [] for name in resource_capability_ids(capabilities_meta)}
    for resource in resources:
        capability_id = capability_for_resource(resource["name"], capabilities_meta)
        grouped.setdefault(capability_id, []).append(resource)

    return [
        {**_capability_group_meta(capability_id, capabilities_meta), "resources": resources_for_id}
        for capability_id, resources_for_id in grouped.items()
    ]


def _extract_uri_params(uri_template: str) -> list[str]:
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


@blueprint.route("/")
@require_login()
def browse():
    can_view = has_permission(current_user, "capabilities.view")
    can_try = has_permission(current_user, "capabilities.try")
    can_manage = has_permission(current_user, "capabilities.manage")
    # Matches PAGE_PERMISSION's tuple semantics (visible to an account
    # holding any one of these) - a manage-only account must be able to
    # reach the page to use the permission it has, the same way a
    # try-only or view-only account already can.
    if not (can_view or can_try or can_manage):
        abort(403)

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

    error = tools_error or resources_error
    capabilities_meta = _fetch_capabilities_meta_or_empty()
    extensions = _group_tools_by_extension(tools, extensions_catalog)
    tool_capability_groups = _group_tools_by_capability(tools, capabilities_meta)
    resource_capability_groups = _group_resources_by_capability(resources, capabilities_meta)
    return render_template(
        "capabilities.html",
        tools=tools,
        extensions=extensions,
        tool_capability_groups=tool_capability_groups,
        resources=resources,
        resource_capability_groups=resource_capability_groups,
        can_manage_capabilities=can_manage,
        error=error,
    )


@blueprint.route("/api/tools")
@require_permission("capabilities.view")
def api_tools():
    return jsonify(_serialize_tools())


@blueprint.route("/api/resources")
@require_permission("capabilities.view")
def api_resources():
    return jsonify(_serialize_resources())


@blueprint.route("/api/try/<tool_name>", methods=["POST"])
@require_permission("capabilities.try")
def try_tool(tool_name: str):
    arguments = request.get_json(silent=True) or {}
    try:
        result = call_tool(tool_name, arguments)
        return jsonify({"status": "ok", "result": result})
    except Exception as exc:  # noqa: BLE001
        return jsonify({"status": "error", "message": str(exc)}), 500


@blueprint.route("/api/read-resource", methods=["POST"])
@require_permission("capabilities.try")
def read_resource_route():
    data = request.get_json(silent=True) or {}
    uri = (data.get("uri") or "").strip()
    if not uri:
        return jsonify({"status": "error", "message": "Missing uri"}), 400
    try:
        result = read_resource(uri)
        return jsonify({"status": "ok", "result": result})
    except Exception as exc:  # noqa: BLE001
        return jsonify({"status": "error", "message": str(exc)}), 500


def _forward_mcp_server_error(exc: urllib.error.HTTPError):
    """Same shape as Chat/__index__.py's _forward_extension_error - not
    shared code, since each page's blueprint module is self-contained
    (see pages/README.md), but the reasoning is identical: mcp_server's
    own error message (a 404 naming the unknown capability, a 400
    naming the bad body) is more useful to whoever's looking at this
    than a generic "request failed"."""
    try:
        body = json.loads(exc.read().decode("utf-8"))
        message = body.get("error") or f"mcp_server returned {exc.code}."
    except Exception:  # noqa: BLE001 - body wasn't parseable JSON
        message = f"mcp_server returned {exc.code}."
    return jsonify({"error": message}), exc.code


@blueprint.route("/api/capabilities/<name>/toggle", methods=["POST"])
@require_permission("capabilities.manage")
def toggle_capability(name: str):
    data = request.get_json(silent=True) or {}
    enabled = data.get("enabled")
    if not isinstance(enabled, bool):
        return jsonify({"error": "'enabled' (boolean) is required"}), 400
    try:
        status = set_capability_enabled(name, enabled)
        return jsonify(status)
    except urllib.error.HTTPError as exc:
        return _forward_mcp_server_error(exc)
    except Exception as exc:  # noqa: BLE001 - e.g. mcp_server unreachable
        return jsonify({"error": str(exc)}), 502
