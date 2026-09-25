"""Rejects POST requests that aren't JSON.

An HTML form on another site can only send GET or POST, with form-encoded or
plain-text bodies - never application/json. So requiring JSON on POST closes
cross-site request forgery together with the SameSite=Strict cookie.
PUT/PATCH/DELETE aren't checked: a cross-site page can only send them after a
CORS preflight, which ember_api never grants - and the MCP client's session
DELETE carries no body or Content-Type at all.

Pure ASGI (not BaseHTTPMiddleware), so streamed responses - the MCP proxy's
SSE later - pass through untouched.
"""

from __future__ import annotations

import json

from starlette.types import ASGIApp, Receive, Scope, Send

_CHECKED_METHODS = {"POST"}


class JsonOnlyMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["method"] in _CHECKED_METHODS:
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
