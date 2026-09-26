"""FastAPI application factory."""

from __future__ import annotations

import logging
import traceback
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from src.config import Settings
from src.db import Database
from src.body_limit import BodyLimitMiddleware
from src.json_only import JsonOnlyMiddleware
from src.security import SecurityMiddleware
from src.routes import (
    account,
    admin,
    attachments,
    auth,
    chats,
    config_issues,
    logs,
    mcp,
    server_info,
    usage,
    watchers,
)
from src.services.agent_gateway import AgentGateway, McpAgentGateway
from src.services.auth_service import AuthService
from src.services.chat_service import MAX_CHAT_BYTES
from src.services.email_service import EmailSender, SmtpEmailSender
from src.services.log_service import LogWriter
from src.services.mcp_proxy import McpProxy
from src.services.otp_service import OtpService
from src.services.server_tools import McpServerTools, ServerTools
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
    server_tools: ServerTools | None = None,
) -> FastAPI:
    """email_sender defaults to SMTP from secrets/secret_smtp.env,
    upstream_transport to real HTTP, agent_gateway to a real MCP client for
    ai_agent and server_tools to one for mcp_server; tests pass fakes."""

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
        log_writer = LogWriter(database)
        await log_writer.purge_old()
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
        app.state.server_tools = server_tools or McpServerTools(settings.mcp_server_url, internal_token or None)
        app.state.logs = log_writer
        app.state.turns = TurnRegistry(database, app.state.agent_gateway, settings.usage, log_writer)
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
    app.include_router(watchers.router)
    app.include_router(logs.router)
    app.include_router(attachments.router)
    app.include_router(config_issues.router)

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, error: Exception) -> JSONResponse:
        """Any unhandled exception: logged for the Logs page's Errors tab
        (under the account, when the request had one) and answered with a
        generic 500 - the details stay server-side."""
        logs_writer: LogWriter | None = getattr(request.app.state, "logs", None)
        if logs_writer is not None:
            await logs_writer.error(
                getattr(request.state, "account_id", None),
                f"http {request.method} {request.url.path}",
                f"{type(error).__name__}: {error}",
                "".join(traceback.format_exception(error)),
            )
        return JSONResponse({"detail": "Internal server error"}, status_code=500)

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app
