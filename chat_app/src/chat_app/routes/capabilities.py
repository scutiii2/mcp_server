"""Live capability browser for the MCP server's tool catalog.

Nothing here is hardcoded - every request calls list_tools() on the MCP
server, so this page (and the try-it console on it) always reflects
whatever tools are actually registered right now, even if the MCP server
was redeployed five minutes ago with new tools added.
"""

from __future__ import annotations

from flask import Blueprint, jsonify, render_template, request

from chat_app.services.mcp_client import call_tool, list_tools


capabilities_bp = Blueprint("capabilities", __name__, url_prefix="/capabilities")


@capabilities_bp.get("/")
def browse():
    try:
        tools = list_tools()
        error = None
    except Exception as exc:  # noqa: BLE001 - surface any error to the page
        tools = []
        error = str(exc)
    return render_template("capabilities.html", tools=tools, error=error)


@capabilities_bp.get("/api/tools")
def api_tools():
    tools = list_tools()
    return jsonify(
        [
            {
                "name": tool.name,
                "description": tool.description or "",
                "input_schema": tool.inputSchema or {},
            }
            for tool in tools
        ]
    )


@capabilities_bp.post("/api/try/<tool_name>")
def try_tool(tool_name: str):
    """Call a tool directly, bypassing chat/OpenAI entirely - for debugging."""
    arguments = request.get_json(force=True) or {}
    try:
        result = call_tool(tool_name, arguments)
        return jsonify({"status": "ok", "result": result})
    except Exception as exc:  # noqa: BLE001
        return jsonify({"status": "error", "message": str(exc)}), 500
