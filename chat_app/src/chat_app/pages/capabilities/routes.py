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

from flask import Blueprint, jsonify, render_template, request

from chat_app.services.mcp_client import (
    call_tool,
    list_resource_templates,
    list_tools,
    read_resource,
)
from chat_app.services.tool_titles import title_for


capabilities_bp = Blueprint(
    "capabilities",
    __name__,
    url_prefix="/capabilities",
    static_folder="template",
    static_url_path="/pages/capabilities/assets",
)


def _serialize_tools() -> list[dict]:
    """Reshape raw MCP Tool objects into plain dicts with a friendly
    title attached - shared by both the page and the JSON API so there's
    one place that knows this shape."""
    return [
        {
            "name": tool.name,
            "title": title_for(tool.name),
            "description": tool.description or "",
            "input_schema": tool.inputSchema or {},
        }
        for tool in list_tools()
    ]


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
    try:
        tools = _serialize_tools()
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
    return render_template("capabilities/index.html", tools=tools, resources=resources, error=error)


@capabilities_bp.get("/api/tools")
def api_tools():
    return jsonify(_serialize_tools())


@capabilities_bp.get("/api/resources")
def api_resources():
    return jsonify(_serialize_resources())


@capabilities_bp.post("/api/try/<tool_name>")
def try_tool(tool_name: str):
    """Call a tool directly, bypassing chat/OpenAI entirely - for debugging."""
    arguments = request.get_json(force=True) or {}
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
    data = request.get_json(force=True) or {}
    uri = (data.get("uri") or "").strip()
    if not uri:
        return jsonify({"status": "error", "message": "Missing uri"}), 400
    try:
        result = read_resource(uri)
        return jsonify({"status": "ok", "result": result})
    except Exception as exc:  # noqa: BLE001
        return jsonify({"status": "error", "message": str(exc)}), 500
