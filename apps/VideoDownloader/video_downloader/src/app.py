"""FastAPI application factory: routers, error handlers, CORS and the sweeper."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.api import downloads, files, probe
from src.config import Settings
from src.errors import DownloaderError, ErrorCode
from src.internal_token import InternalTokenMiddleware
from src.mcp_tools.tools import build_mcp
from src.service import DownloadService, build_service
from src.store.sweeper import run_sweeper
from src.system_info import find_ffmpeg, ytdlp_version

logger = logging.getLogger(__name__)


def create_app(settings: Settings, service: DownloadService | None = None) -> FastAPI:
    service = service or build_service(settings)
    mcp = build_mcp(service)
    mcp_app = mcp.streamable_http_app()  # serves /mcp

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await service.store.load_index()
        stop = asyncio.Event()
        sweeper = asyncio.create_task(run_sweeper(service, settings.sweep_interval_seconds, stop))
        try:
            async with mcp.session_manager.run():
                yield
        finally:
            service.cancel_all_jobs()  # running downloads stop instead of holding shutdown open
            stop.set()
            await sweeper

    app = FastAPI(title="video_downloader", lifespan=lifespan)
    app.state.settings = settings
    app.state.service = service

    @app.exception_handler(DownloaderError)
    async def downloader_error(_: Request, error: DownloaderError) -> JSONResponse:
        return JSONResponse(error.to_body(), status_code=error.http_status)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, error: RequestValidationError) -> JSONResponse:
        first = error.errors()[0] if error.errors() else {}
        where = ".".join(str(part) for part in first.get("loc", ()) if part != "body")
        message = f"{where}: {first.get('msg', 'invalid value')}" if where else str(first.get("msg", "Invalid request."))
        return JSONResponse(DownloaderError(ErrorCode.INVALID_REQUEST, message).to_body(), status_code=422)

    @app.exception_handler(Exception)
    async def unexpected_error(_: Request, error: Exception) -> JSONResponse:
        logger.error("Unhandled error", exc_info=error)
        body = DownloaderError(ErrorCode.INTERNAL, "Something went wrong on the server. Try again.").to_body()
        return JSONResponse(body, status_code=500)

    @app.get("/api/health")
    async def health() -> dict:
        return {"status": "ok", "yt_dlp": ytdlp_version(), "ffmpeg": find_ffmpeg() is not None}

    app.include_router(probe.router)
    app.include_router(downloads.router)
    app.include_router(files.router)
    app.mount("/", mcp_app)  # after the routers, so /api/* matches first
    app.add_middleware(InternalTokenMiddleware, token=settings.internal_api_token)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.web_origin],
        allow_credentials=True,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Content-Type"],
    )
    return app
