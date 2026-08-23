"""HTTP endpoint for the chat-invocable command registry: GET /commands.

Mounted the same way extension_routes.py's /extensions is (see run.py):
a plain HTTP route alongside the MCP surface, not a tool - chat_app's
command execution/autocomplete path polls this, no model ever calls
it.
"""

from __future__ import annotations

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse

from mcp_server import commands


def _spec_json(spec: commands.CommandSpec) -> dict[str, str]:
    return {
        "capability": spec.capability,
        "name": spec.name,
        "description": spec.description,
        "tool_name": spec.tool_name,
    }


async def list_commands(request: Request) -> JSONResponse:
    return JSONResponse([_spec_json(spec) for spec in commands.all_commands()])


def install_command_routes(app: Starlette) -> None:
    app.add_route("/commands", list_commands, methods=["GET"])
