"""HTTP endpoints for built-in capabilities: status, and live enable/disable.

Mounted onto the Starlette app that ``mcp.streamable_http_app()`` returns,
the same technique ``extension_routes.py`` uses (see ``run.py``): plain
HTTP routes alongside the MCP surface, not tools - toggling what this
server can do is a human/admin action, not something a model should be
able to do to itself.

GET /capabilities returns a JSON array shaped exactly like::

    { "name": "host_health", "enabled": true }

PATCH /capabilities/{name} takes ``{"enabled": bool}`` and returns that
same shape for the capability just changed - 404 for an unknown name,
400 for a missing/non-boolean ``enabled``.

Persist-then-apply, same ordering as ``extensions.add_extension``:
``save_capabilities_config`` writes to disk first, and only then does
``capability_registry.set_enabled`` touch the live server. A disk-write
failure (a deleted config directory, a full disk) then raises before
anything live changes, so config_capabilities.json and the running
server's actual tool/resource list can never disagree about what a
failed request did.
"""

from __future__ import annotations

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse

from src.config import settings
from src.infra import capability_registry
from src.infra.app_config import save_capabilities_config
from src.server import mcp


def _status_json(name: str) -> dict[str, object]:
    return {"name": name, "enabled": capability_registry.is_enabled(name)}


async def list_capabilities(request: Request) -> JSONResponse:
    return JSONResponse([_status_json(name) for name in capability_registry.names()])


async def update_capability(request: Request) -> JSONResponse:
    name = request.path_params["name"]
    if name not in capability_registry.names():
        return JSONResponse({"error": f"Unknown capability {name!r}"}, status_code=404)

    try:
        body = await request.json()
    except Exception:  # noqa: BLE001 - malformed JSON is a 400, not a 500
        return JSONResponse({"error": "Request body must be valid JSON"}, status_code=400)
    if not isinstance(body, dict) or not isinstance(body.get("enabled"), bool):
        return JSONResponse({"error": "'enabled' (a boolean) is required"}, status_code=400)

    enabled = body["enabled"]
    save_capabilities_config(settings.capabilities_config_path, name, enabled)
    capability_registry.set_enabled(mcp, name, enabled)

    return JSONResponse(_status_json(name))


def install_capability_routes(app: Starlette) -> None:
    """Add the capability status/toggle routes to an existing Starlette app."""
    app.add_route("/capabilities", list_capabilities, methods=["GET"])
    app.add_route("/capabilities/{name}", update_capability, methods=["PATCH"])
