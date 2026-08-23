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

from src import commands
from src.infra import capability_registry


def _spec_json(spec: commands.CommandSpec) -> dict[str, str]:
    return {
        "capability": spec.capability,
        "name": spec.name,
        "description": spec.description,
        "tool_name": spec.tool_name,
    }


def _is_capability_enabled(name: str) -> bool:
    # A command whose capability the registry has never heard of (should
    # only happen in a test that registers a command directly, never for
    # a real capability - run.py's capturing() covers every one of
    # those) fails open, same "absent means enabled" rule
    # app_config.capability_enabled() already applies to the config file.
    try:
        return capability_registry.is_enabled(name)
    except KeyError:
        return True


async def list_commands(request: Request) -> JSONResponse:
    return JSONResponse(
        [_spec_json(spec) for spec in commands.all_commands() if _is_capability_enabled(spec.capability)]
    )


def install_command_routes(app: Starlette) -> None:
    app.add_route("/commands", list_commands, methods=["GET"])
