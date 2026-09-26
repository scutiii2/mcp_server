"""FastAPI application factory."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from src.config import Settings
from src.db import Database
from src.body_limit import BodyLimitMiddleware
from src.json_only import JsonOnlyMiddleware
from src.security import SecurityMiddleware
from src.routes import account, admin, auth, chats, mcp, server_info, usage
from src.services.agent_gateway import AgentGateway, McpAgentGateway
from src.services.auth_service import AuthService
from src.services.chat_service import MAX_CHAT_BYTES
from src.services.email_service import EmailSender, SmtpEmailSender
from src.services.mcp_proxy import McpProxy
from src.services.otp_service import OtpService
from src.services.session_service import SessionService
from src.services.turns import TurnRegistry
from src.utils.config_loader import load_env_secrets

logger = logging.getLogger(__name__)

MAX_REQUEST_BYTES = 16 * MAX_CHAT_BYTES

# No read timeout: an MCP event stream stays open for as long as a chat turn
# (or the session) lasts. Connect/write/pool still fail fast.
_UPSTREAM_TIMEOUT = httpx.Timeout(connect=10.0, read=None, write=30.0, pool=10.0)


def create_app(
    settings: Settings,
    email_sender: EmailSender | None = None,
    upstream_transport: httpx.AsyncBaseTransport | None = None,
    agent_gateway: AgentGateway | None = None,
) -> FastAPI:
    """email_sender defaults to SMTP from secrets/secret_smtp.env,
    upstream_transport to real HTTP and agent_gateway to a real MCP client
    for ai_agent; tests pass fakes for all three."""

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
        app.state.upstream = upstream
        app.state.internal_token = internal_token or None
        app.state.mcp_proxy = McpProxy(upstream, internal_token or None)
        app.state.agent_gateway = agent_gateway or McpAgentGateway(internal_token or None)
        app.state.turns = TurnRegistry(database, app.state.agent_gateway, settings.usage)
        try:
            yield
        finally:
            # Before the database closes: running turns save what they have.
            await app.state.turns.shutdown()
            await upstream.aclose()
            await database.dispose()

    app = FastAPI(title="ember_api", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(JsonOnlyMiddleware)
    # Largest legitimate body: a chat-history import of several 2 MB chats.
    app.add_middleware(BodyLimitMiddleware, max_bytes=MAX_REQUEST_BYTES)
    # Added last, so it runs first: blocked IPs never reach JSON checks or
    # routes, and even those rejections carry the security headers.
    app.add_middleware(SecurityMiddleware, settings=settings.security)
    app.include_router(auth.router)
    app.include_router(account.router)
    app.include_router(admin.router)
    app.include_router(chats.router)
    app.include_router(usage.router)
    app.include_router(mcp.router)
    app.include_router(server_info.router)

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app
