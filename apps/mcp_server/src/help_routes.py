"""HTTP endpoints for `/help` and `/<capability> help`: GET /commands/help
and GET /commands/help/{capability}.

Mounted the same way command_routes.py's /commands is (see run.py): a
plain HTTP route alongside the MCP surface, not a tool - chat_app's
commands.py intercepts "/help" and "/<capability> help ..." before
either ever reaches the tool registry and calls one of these instead of
a real MCP tool call (see that module's docstring and
capability_help.py's).
"""

from __future__ import annotations

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse

from src import capability_help
from src.services import capability_registry


async def get_help_index(request: Request) -> JSONResponse:
    return JSONResponse(capability_help.build_index())


async def get_help(request: Request) -> JSONResponse:
    capability_id = request.path_params["capability"]

    # Same "fail closed" reasoning as command_routes.py's
    # _is_capability_enabled: a disabled (or never-registered) built-in
    # capability's help shouldn't be reachable any more than its
    # commands are.
    try:
        enabled = capability_registry.is_enabled(capability_id)
    except KeyError:
        enabled = False
    if not enabled:
        return JSONResponse({"error": f"Unknown capability {capability_id!r}"}, status_code=404)

    target = request.query_params.get("target", "all")
    command = request.query_params.get("command")

    try:
        return JSONResponse(capability_help.build_help(capability_id, target=target, command=command))
    except capability_help.HelpError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


def install_help_routes(app: Starlette) -> None:
    app.add_route("/commands/help", get_help_index, methods=["GET"])
    app.add_route("/commands/help/{capability}", get_help, methods=["GET"])
