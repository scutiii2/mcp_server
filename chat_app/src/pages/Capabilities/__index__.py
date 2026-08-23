"""Live capability browser for the MCP server's tool AND resource catalog.

Nothing here is hardcoded - every request calls list_tools()/
list_resource_templates() on the MCP server, so this page (and the
try-it console on it) always reflects whatever's actually registered
right now. Ported from MCPArchitecture's
chat_app/src/chat_app/pages/capabilities/routes.py - see
docs/superpowers/specs/2026-08-22-chat-capabilities-port-design.md.
"""

from __future__ import annotations

import re

from flask import Blueprint, abort, jsonify, render_template, request
from flask_login import current_user

from src.services.authz import has_permission, register_permission, require_login, require_permission
from src.services.mcp_client import (
    call_tool,
    fetch_extensions,
    list_resource_templates,
    list_tools,
    read_resource,
)
from src.services.tool_capabilities import capability_for_resource, capability_for_tool
from src.services.tool_titles import title_for


blueprint = Blueprint(
    "capabilities", __name__, template_folder=".", static_folder=".", static_url_path="/static"
)

PAGE_PERMISSION = ("capabilities.view", "capabilities.try")
PAGE_DESCRIPTION = "Browse and try MCP server tools and resources live."
PAGE_LAYOUT = "full"
CSRF_EXEMPT = True

register_permission("capabilities.view")
register_permission("capabilities.try")


def _fetch_extensions_or_empty() -> list[dict]:
    try:
        return fetch_extensions()
    except Exception:  # noqa: BLE001 - degrade to built-ins only, don't blank the page
        return []


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


def _group_tools_by_capability(tools: list[dict]) -> list[dict]:
    grouped: dict[str, list[dict]] = {}
    for tool in tools:
        if tool["extension_id"] is not None:
            continue
        label = capability_for_tool(tool["name"])
        grouped.setdefault(label, []).append(tool)

    return [{"label": label, "tools": tools_for_label} for label, tools_for_label in grouped.items()]


def _group_resources_by_capability(resources: list[dict]) -> list[dict]:
    grouped: dict[str, list[dict]] = {}
    for resource in resources:
        label = capability_for_resource(resource["name"])
        grouped.setdefault(label, []).append(resource)

    return [{"label": label, "resources": resources_for_label} for label, resources_for_label in grouped.items()]


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
    if not (has_permission(current_user, "capabilities.view") or has_permission(current_user, "capabilities.try")):
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
    extensions = _group_tools_by_extension(tools, extensions_catalog)
    tool_capability_groups = _group_tools_by_capability(tools)
    resource_capability_groups = _group_resources_by_capability(resources)
    return render_template(
        "capabilities.html",
        tools=tools,
        extensions=extensions,
        tool_capability_groups=tool_capability_groups,
        resources=resources,
        resource_capability_groups=resource_capability_groups,
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
