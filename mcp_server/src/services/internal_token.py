"""Require the shared internal token (X-Internal-Token) on /mcp.

Every caller of this server's /mcp endpoint is another server in this
repo - chat_app, ai_agent, ember_api - never a browser or an end user, and
each of them already holds INTERNAL_API_TOKEN (the same value everywhere,
see .env). Checking it here means a process
that can merely reach the port can no longer call every tool with
arguments of its choosing.

Only enforced when a token is configured: an unconfigured deployment keeps
today's loopback-only trust model (run.py's banner warns about a
non-loopback bind in that case). The plain-HTTP admin routes (/commands,
/capabilities, /extensions, /help) keep their own trust model; /upload
checks the token itself (upload_routes.py).
"""

from __future__ import annotations

import hmac
import json

INTERNAL_TOKEN_HEADER = b"x-internal-token"
PROTECTED_PATH = "/mcp"


class InternalTokenMiddleware:
    """Plain ASGI middleware: rejects a request to /mcp whose
    X-Internal-Token doesn't match (constant-time), with 401 JSON, before
    the MCP transport ever sees it. Lifespan and other paths pass through."""

    def __init__(self, app, token: str) -> None:
        self.app = app
        self._token = token.encode("utf-8")

    def _protects(self, scope) -> bool:
        if not self._token or scope["type"] != "http":
            return False
        path = scope.get("path", "")
        return path == PROTECTED_PATH or path.startswith(PROTECTED_PATH + "/")

    async def __call__(self, scope, receive, send):
        if self._protects(scope):
            provided = dict(scope.get("headers") or []).get(INTERNAL_TOKEN_HEADER, b"")
            if not hmac.compare_digest(self._token, provided):
                body = json.dumps({"error": "Invalid or missing internal API token"}).encode("utf-8")
                await send({
                    "type": "http.response.start",
                    "status": 401,
                    "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())],
                })
                await send({"type": "http.response.body", "body": body})
                return
        await self.app(scope, receive, send)
