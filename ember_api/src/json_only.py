"""Rejects state-changing requests that aren't JSON.

An HTML form on another site can only send form-encoded or plain-text
bodies, never application/json, so requiring JSON on every unsafe method
closes cross-site request forgery together with the SameSite=Strict cookie.

Pure ASGI (not BaseHTTPMiddleware), so streamed responses - the MCP proxy's
SSE later - pass through untouched.
"""

from __future__ import annotations

import json

from starlette.types import ASGIApp, Receive, Scope, Send

_UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


class JsonOnlyMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["method"] in _UNSAFE_METHODS:
            content_type = dict(scope["headers"]).get(b"content-type", b"").decode("latin-1")
            if content_type.split(";")[0].strip().lower() != "application/json":
                await _reject(send)
                return
        await self.app(scope, receive, send)


async def _reject(send: Send) -> None:
    body = json.dumps({"detail": "Content-Type must be application/json"}).encode()
    await send(
        {
            "type": "http.response.start",
            "status": 415,
            "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())],
        }
    )
    await send({"type": "http.response.body", "body": body})
