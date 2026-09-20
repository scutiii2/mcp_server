"""Entry point for the catalog service.

Run with:
    python -m src.run
"""

from __future__ import annotations

import logging

import uvicorn
from starlette.applications import Starlette

from src import registry
from src.config import settings
from src.routes import install_catalog_routes


def build_app() -> Starlette:
    app = Starlette()
    install_catalog_routes(app)
    return app


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    # Cache-first: serve whatever's on disk from the last run immediately,
    # then always kick a fresh background scan so the cache doesn't go
    # stale across restarts - see Global Constraints.
    registry.load_initial(settings.cache_path)
    registry.refresh(settings.sources(), settings.cache_path)
    print(f"Catalog service: http://{settings.host}:{settings.port}", flush=True)
    uvicorn.run(build_app(), host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()
