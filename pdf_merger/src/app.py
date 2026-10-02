"""FastAPI application factory."""

from __future__ import annotations

from fastapi import FastAPI

from src.config import Settings


def create_app(settings: Settings) -> FastAPI:
    app = FastAPI(title="pdf_merger")
    app.state.settings = settings

    @app.get("/api/health")
    async def health() -> dict:
        return {"status": "ok"}

    return app
