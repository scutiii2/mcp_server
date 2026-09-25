"""FastAPI application factory."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from src.config import Settings
from src.db import Database
from src.json_only import JsonOnlyMiddleware
from src.routes import auth
from src.services.auth_service import AuthService
from src.services.session_service import SessionService

logger = logging.getLogger(__name__)


def create_app(settings: Settings) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        settings.database_path.parent.mkdir(parents=True, exist_ok=True)
        database = Database(settings.database_url)
        await database.create_tables()
        async with database.sessions() as session:
            generated = await AuthService(session).ensure_bootstrap_admin(settings.secrets_dir)
            await SessionService(session, settings.session_hours).purge_expired()
        if generated:
            # Printed once, like chat_app; never logged to a file.
            print(f"Bootstrap admin created with password: {generated} (save it now, it won't be shown again)")
        app.state.settings = settings
        app.state.database = database
        try:
            yield
        finally:
            await database.dispose()

    app = FastAPI(title="ember_api", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(JsonOnlyMiddleware)
    app.include_router(auth.router)

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app
