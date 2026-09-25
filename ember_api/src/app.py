"""FastAPI application factory."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from src.config import Settings
from src.db import Database
from src.json_only import JsonOnlyMiddleware
from src.routes import account, admin, auth, mcp
from src.services.auth_service import AuthService
from src.services.email_service import EmailSender, SmtpEmailSender
from src.services.mcp_proxy import McpProxy
from src.services.otp_service import OtpService
from src.services.session_service import SessionService
from src.utils.config_loader import load_env_secrets

logger = logging.getLogger(__name__)

# No read timeout: an MCP event stream stays open for as long as a chat turn
# (or the session) lasts. Connect/write/pool still fail fast.
_UPSTREAM_TIMEOUT = httpx.Timeout(connect=10.0, read=None, write=30.0, pool=10.0)


def create_app(
    settings: Settings,
    email_sender: EmailSender | None = None,
    upstream_transport: httpx.AsyncBaseTransport | None = None,
) -> FastAPI:
    """email_sender defaults to SMTP from secrets/secret_smtp.env and
    upstream_transport to real HTTP; tests pass fakes for both."""

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

        internal_token = load_env_secrets(settings.secrets_dir / "secret_internal_api.env").get("INTERNAL_API_TOKEN")
        upstream = httpx.AsyncClient(transport=upstream_transport, timeout=_UPSTREAM_TIMEOUT)

        app.state.settings = settings
        app.state.database = database
        app.state.email_sender = email_sender or SmtpEmailSender(settings.secrets_dir)
        app.state.mcp_proxy = McpProxy(upstream, internal_token or None)
        try:
            yield
        finally:
            await upstream.aclose()
            await database.dispose()

    app = FastAPI(title="ember_api", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(JsonOnlyMiddleware)
    app.include_router(auth.router)
    app.include_router(account.router)
    app.include_router(admin.router)
    app.include_router(mcp.router)

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app
