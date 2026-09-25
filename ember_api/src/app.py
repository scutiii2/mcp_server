"""FastAPI application factory."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from src.config import Settings
from src.db import Database
from src.json_only import JsonOnlyMiddleware
from src.routes import admin, auth
from src.services.auth_service import AuthService
from src.services.email_service import EmailSender, SmtpEmailSender
from src.services.otp_service import OtpService
from src.services.session_service import SessionService

logger = logging.getLogger(__name__)


def create_app(settings: Settings, email_sender: EmailSender | None = None) -> FastAPI:
    """email_sender defaults to SMTP from secrets/secret_smtp.env; tests pass a fake."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        settings.database_path.parent.mkdir(parents=True, exist_ok=True)
        database = Database(settings.database_url)
        await database.create_tables()
        async with database.sessions() as session:
            auth_service = AuthService(session)
            generated = await auth_service.ensure_bootstrap_admin(settings.secrets_dir)
            await auth_service.ensure_default_role(settings.default_role)
            await SessionService(session, settings.session_hours).purge_expired()
            await OtpService(session).purge_stale()
        if generated:
            # Printed once, like chat_app; never logged to a file.
            print(f"Bootstrap admin created with password: {generated} (save it now, it won't be shown again)")
        app.state.settings = settings
        app.state.database = database
        app.state.email_sender = email_sender or SmtpEmailSender(settings.secrets_dir)
        try:
            yield
        finally:
            await database.dispose()

    app = FastAPI(title="ember_api", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(JsonOnlyMiddleware)
    app.include_router(auth.router)
    app.include_router(admin.router)

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app
