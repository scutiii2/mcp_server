"""HTTP endpoints for configured extensions: status, and runtime
add/remove.

Mounted onto the Starlette app that ``mcp.streamable_http_app()`` returns,
the same technique approval_routes.py uses (see ``run.py``): plain HTTP
routes alongside the MCP surface, not tools - there's nothing here a model
needs to call, only something a human-facing UI (chat_app's sidebar,
being built concurrently against these routes) polls and drives.

GET /extensions returns a JSON array shaped exactly like::

    {
      "id": "reference",
      "label": "Reference Extension (dev fixture)",
      "description": "...",
      "status": "connected",
      "error": null,
      "tools": ["reference__echo", "reference__add"]
    }

That shape is a contract another agent is building chat_app's sidebar
against concurrently - it is not this file's to redesign. POST
/extensions returns one object of that same shape (the just-added
extension's status), for the same reason.

POST /extensions and DELETE /extensions/{id} only support the http
transport, not stdio: adding a stdio extension means naming a command to
spawn on *this* machine, which is a very different (and more dangerous -
arbitrary local process execution) thing to hand a human-facing UI than
"here is a URL where an MCP server is already running". A stdio extension
is still fully supported - just only by hand-editing config.json, the
same as before this feature existed.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from src.config import settings
from src.infra import extensions
from src.infra.app_config import ExtensionConfig

# Anything that isn't a lowercase letter or digit collapses to a single
# "_". That alone guarantees the result never contains "__"
# (extensions.NAMESPACE_SEPARATOR) - a run of separators collapses to one
# underscore, so two would only appear if this code literally joined
# pieces with "__" itself, which it doesn't.
_SLUG_INVALID = re.compile(r"[^a-z0-9]+")


def _slugify(label: str) -> str:
    slug = _SLUG_INVALID.sub("_", label.strip().lower()).strip("_")
    return slug or "extension"


def _unique_extension_id(label: str) -> str:
    """A slug of `label`, disambiguated against every currently-known
    extension id by appending _2, _3, ... on collision - so two
    extensions added with the same display label still get distinct
    ids."""
    base = _slugify(label)
    existing = {status.id for status in extensions.current_statuses()}
    if base not in existing:
        return base
    suffix = 2
    while f"{base}_{suffix}" in existing:
        suffix += 1
    return f"{base}_{suffix}"


def _status_json(status: extensions.ExtensionStatus) -> dict[str, object]:
    return {
        "id": status.id,
        "label": status.label,
        "description": status.description,
        "status": status.status,
        "error": status.error,
        "tools": status.tools,
    }


async def list_extensions(request: Request) -> JSONResponse:
    return JSONResponse([_status_json(status) for status in extensions.current_statuses()])


async def create_extension(request: Request) -> JSONResponse:
    """Add an http-transport extension at runtime, connect to it, and
    persist it to config.json - see extensions.add_extension. A connect
    failure (unreachable URL, wrong path, ...) is still a 201: the
    extension is registered and saved either way, and `status`/`error` in
    the body say whether it's currently reachable - exactly how a broken
    config.json entry already behaves at startup.
    """
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001 - malformed JSON is a 400, not a 500
        return JSONResponse({"error": "Request body must be valid JSON"}, status_code=400)
    if not isinstance(body, dict):
        return JSONResponse({"error": "Request body must be a JSON object"}, status_code=400)

    label = str(body.get("label") or "").strip()
    url = str(body.get("url") or "").strip()
    description = str(body.get("description") or "")

    if not label:
        return JSONResponse({"error": "'label' is required"}, status_code=400)
    if not url:
        return JSONResponse({"error": "'url' is required"}, status_code=400)

    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return JSONResponse(
            {"error": f"'url' must be an http:// or https:// URL, got {url!r}"}, status_code=400
        )

    config = ExtensionConfig(
        id=_unique_extension_id(label),
        label=label,
        description=description,
        transport="http",
        url=url,
    )
    status = await extensions.add_extension(config, settings.extensions_config_path)
    if status is None:
        # Only possible if this route were somehow reachable before
        # install_extensions() ran, which run.py's startup order doesn't
        # allow - guarded anyway rather than assumed.
        return JSONResponse({"error": "Extensions are not available yet"}, status_code=503)

    return JSONResponse(_status_json(status), status_code=201)


async def delete_extension(request: Request) -> Response:
    """Disconnect and forget a runtime extension - see
    extensions.remove_extension. 404 for an unknown id, 204 on success."""
    extension_id = request.path_params["extension_id"]
    removed = await extensions.remove_extension(extension_id, settings.extensions_config_path)
    if not removed:
        return JSONResponse({"error": f"Unknown extension {extension_id!r}"}, status_code=404)
    return Response(status_code=204)


def install_extension_routes(app: Starlette) -> None:
    """Add the extension status/add/remove routes to an existing
    Starlette app."""
    app.add_route("/extensions", list_extensions, methods=["GET"])
    app.add_route("/extensions", create_extension, methods=["POST"])
    app.add_route("/extensions/{extension_id}", delete_extension, methods=["DELETE"])
