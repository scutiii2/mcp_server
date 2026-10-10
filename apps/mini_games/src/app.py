"""The FastAPI shell every game mounts into: token check, health and error shape."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from src.auth import InternalTokenMiddleware


def create_app(token: str = "") -> FastAPI:
    app = FastAPI(title="mini_games", docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(InternalTokenMiddleware, token=token)

    @app.exception_handler(RequestValidationError)
    async def bad_body(request: Request, error: RequestValidationError) -> JSONResponse:
        detail = "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in error.errors()[:3])
        return JSONResponse({"error": "invalid request", "detail": detail}, status_code=400)

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, error: HTTPException) -> JSONResponse:
        # Starlette's class, so router-raised 404 and 405 get the same {"error"} shape as everything else.
        return JSONResponse({"error": error.detail}, status_code=error.status_code, headers=error.headers)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app
