"""Require X-Internal-Token on /mcp (copied from pdf_merger's internal_token.py;
the repo forbids cross-project imports).

An unset token rejects every /mcp call, so a fresh install never exposes tools by accident.
"""

from __future__ import annotations

import hmac
import json

INTERNAL_TOKEN_HEADER = b"x-internal-token"
PROTECTED_PATH = "/mcp"


class InternalTokenMiddleware:
    """Plain ASGI middleware: 401 JSON for /mcp without the right token. Other paths pass through."""

    def __init__(self, app, token: str) -> None:
        self.app = app
        self._token = token.encode("utf-8")

    def _protects(self, scope) -> bool:
        if scope["type"] != "http":
            return False
        path = scope.get("path", "")
        return path == PROTECTED_PATH or path.startswith(PROTECTED_PATH + "/")

    async def __call__(self, scope, receive, send):
        if self._protects(scope):
            provided = dict(scope.get("headers") or []).get(INTERNAL_TOKEN_HEADER, b"")
            if not self._token or not hmac.compare_digest(self._token, provided):
                body = json.dumps({"error": {"code": "unauthorized", "message": "Invalid or missing internal API token."}}).encode()
                await send(
                    {
                        "type": "http.response.start",
                        "status": 401,
                        "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())],
                    }
                )
                await send({"type": "http.response.body", "body": body})
                return
        await self.app(scope, receive, send)
