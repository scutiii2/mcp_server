"""HTTP endpoints for built-in capabilities: status, live enable/disable, refresh.

Mounted onto the Starlette app that ``mcp.streamable_http_app()`` returns,
the same technique ``extension_routes.py`` uses (see ``run.py``): plain
HTTP routes alongside the MCP surface, not tools - toggling what this
server can do is a human/admin action, not something a model should be
able to do to itself.

GET /capabilities returns a JSON array shaped exactly like::

    {
        "name": "server",
        "enabled": true,
        "label": "Server Manager",
        "tools": ["tool_srv_listApps", ...],
        "resources": [],
        "has_gui": false,
        "load_error": null,
        "missing": false,
        "loaded": true
    }

``label``/``tools``/``resources`` let chat_app derive its Capabilities
page grouping (which tool belongs to which capability, and what to call
it) entirely from this one live response, instead of hand-maintaining
its own copy - see chat_app's ``services/tool_capabilities.py``.
``loaded`` is false for a folder that was discovered but never brought
online (its tools are not imported yet), ``load_error`` holds the text of
the last failed import, and ``missing`` means the folder is gone from disk.

POST /capabilities/refresh rescans ``src/capabilities/`` so a folder added
while the server runs shows up (offline), and returns the same array.

GET /capabilities/{name}/gui returns that capability's GUI page (the
validated ``gui/page.json``) or 404 when it has none; ``has_gui`` says
which capabilities do.

PATCH /capabilities/{name} takes ``{"enabled": bool}`` and returns that
same shape for the capability just changed - 404 for an unknown name,
400 for a missing/non-boolean ``enabled``, 409 when going online fails
(the import raised, the id or a tool name clashes, or the folder is gone;
the body is ``{"error": "<message>"}``). Going online re-imports the
capability from disk, so an edited file takes effect.

Persist-then-apply, same ordering as ``extensions.add_extension``, for
going offline: ``save_capabilities_config`` writes to disk first, and only
then does ``capability_registry.set_enabled`` touch the live server. A
disk-write failure (a deleted config directory, a full disk) then raises
before anything live changes, so config_capabilities.json and the running
server's actual tool/resource list can never disagree about what a
failed request did. Going online is the reverse: the import can fail, so
it is applied first and persisted after (a failed import writes nothing).
"""

from __future__ import annotations

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse

from src import capability_gui
from src.services import capability_registry
from src.services.capability_loader import CapabilityError, CapabilityLoader


def _status_json(loader: CapabilityLoader, name: str) -> dict[str, object]:
    record = loader.record_for(name)
    known = name in capability_registry.names()
    return {
        "name": name,
        "enabled": known and capability_registry.is_enabled(name),
        "label": capability_registry.label(name) if known else (record.label if record else name),
        "tools": capability_registry.tool_names(name) if known else [],
        "resources": capability_registry.resource_names(name) if known else [],
        # True only when a valid page exists and the capability is on, so a link never leads to a 404.
        "has_gui": known and capability_gui.load_page(name) is not None,
        "load_error": record.load_error if record else None,
        "missing": record.missing if record else False,
        "loaded": record.loaded if record else known,
    }


def _all_names(loader: CapabilityLoader) -> list[str]:
    return sorted(set(capability_registry.names()) | {record.id for record in loader.records()})


def _list(loader: CapabilityLoader) -> JSONResponse:
    return JSONResponse([_status_json(loader, name) for name in _all_names(loader)])


def install_capability_routes(app: Starlette, loader: CapabilityLoader) -> None:
    """Add the capability status/toggle/refresh routes to an existing Starlette app."""

    async def list_capabilities(request: Request) -> JSONResponse:
        return _list(loader)

    async def refresh_capabilities(request: Request) -> JSONResponse:
        await loader.refresh()
        return _list(loader)

    async def capability_gui_page(request: Request) -> JSONResponse:
        name = request.path_params["name"]
        if name not in capability_registry.names():
            return JSONResponse({"error": f"Unknown capability {name!r}"}, status_code=404)
        page = capability_gui.load_page(name)
        if page is None:
            return JSONResponse({"error": f"Capability {name!r} has no page"}, status_code=404)
        return JSONResponse(page.model_dump(mode="json", exclude_none=True))

    async def update_capability(request: Request) -> JSONResponse:
        name = request.path_params["name"]
        if name not in _all_names(loader):
            return JSONResponse({"error": f"Unknown capability {name!r}"}, status_code=404)
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001 - malformed JSON is a 400, not a 500
            return JSONResponse({"error": "Request body must be valid JSON"}, status_code=400)
        if not isinstance(body, dict) or not isinstance(body.get("enabled"), bool):
            return JSONResponse({"error": "'enabled' (a boolean) is required"}, status_code=400)
        try:
            final_id = await loader.set_online(name, body["enabled"])
        except CapabilityError as error:
            return JSONResponse({"error": str(error)}, status_code=error.status)
        return JSONResponse(_status_json(loader, final_id))

    app.add_route("/capabilities", list_capabilities, methods=["GET"])
    app.add_route("/capabilities/refresh", refresh_capabilities, methods=["POST"])
    app.add_route("/capabilities/{name}/gui", capability_gui_page, methods=["GET"])
    app.add_route("/capabilities/{name}", update_capability, methods=["PATCH"])
