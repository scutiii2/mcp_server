"""Plain HTTP JSON routes for the catalog - no auth (see Global
Constraints in docs/superpowers/plans/2026-09-13-catalog-service.md: this
serves read-only, non-sensitive metadata).
"""

from __future__ import annotations

from pathlib import Path

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse

from src import registry, scanner
from src.config import settings

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
INDEX_HTML = STATIC_DIR / "index.html"


async def get_catalog(request: Request) -> JSONResponse:
    status, entries = registry.current()
    return JSONResponse({"status": status, "entries": entries})


async def get_catalog_entry(request: Request) -> JSONResponse:
    entry_id = request.path_params["entry_id"]
    entry = registry.get_by_id(entry_id)
    if entry is None:
        return JSONResponse({"error": f"Unknown catalog id {entry_id!r}"}, status_code=404)
    return JSONResponse(entry)


async def get_catalog_entry_snippet(request: Request) -> JSONResponse:
    entry_id = request.path_params["entry_id"]
    entry = registry.get_by_id(entry_id)
    if entry is None:
        return JSONResponse({"error": f"Unknown catalog id {entry_id!r}"}, status_code=404)
    snippet = scanner.extract_snippet(settings.sources(), entry)
    if snippet is None:
        return JSONResponse({"error": "Snippet unavailable"}, status_code=404)
    return JSONResponse({"snippet": snippet})


async def refresh_catalog(request: Request) -> JSONResponse:
    registry.refresh(settings.sources(), settings.cache_path)
    return JSONResponse({"status": "scanning"})


async def health(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


async def index(request: Request) -> FileResponse:
    return FileResponse(INDEX_HTML)


def install_catalog_routes(app: Starlette) -> None:
    app.add_route("/", index, methods=["GET"])
    app.add_route("/catalog", get_catalog, methods=["GET"])
    app.add_route("/catalog/{entry_id}", get_catalog_entry, methods=["GET"])
    app.add_route("/catalog/{entry_id}/snippet", get_catalog_entry_snippet, methods=["GET"])
    app.add_route("/catalog/refresh", refresh_catalog, methods=["POST"])
    app.add_route("/health", health, methods=["GET"])
