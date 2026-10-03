"""Refuses request bodies larger than a cap before they are read.

FastAPI reads and parses a whole body before any dependency runs, so a
size check in a route would come after the memory is spent. This pure-ASGI
middleware answers 413 on a too-large Content-Length up front, and stops a
body without one (chunked) as soon as it passes the cap.

The cap depends on the path: only the routes that legitimately take big bodies
(a chat import, attached files) get a large one. Everything else, login and
registration included, which anyone can reach, gets the small default.
"""

from __future__ import annotations

import json
from collections.abc import Mapping

from starlette.types import ASGIApp, Message, Receive, Scope, Send


class BodyTooLarge(Exception):
    pass


class BodyLimitMiddleware:
    def __init__(self, app: ASGIApp, max_bytes: int, path_limits: Mapping[str, int] | None = None) -> None:
        """`max_bytes` for every path, except those starting with a key of
        `path_limits`, which get that value instead (the longest prefix wins)."""
        self.app = app
        self.max_bytes = max_bytes
        self.path_limits = sorted((path_limits or {}).items(), key=lambda item: len(item[0]), reverse=True)

    def _limit_for(self, path: str) -> int:
        return next((limit for prefix, limit in self.path_limits if path.startswith(prefix)), self.max_bytes)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        limit = self._limit_for(scope.get("path", ""))
        declared = dict(scope["headers"]).get(b"content-length", b"")
        if declared.isdigit() and int(declared) > limit:
            await _reject(send)
            return

        received = 0
        started = False

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    raise BodyTooLarge
            return message

        async def tracking_send(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracking_send)
        except BodyTooLarge:
            if not started:
                await _reject(send)


async def _reject(send: Send) -> None:
    body = json.dumps({"detail": "Request body is too large"}).encode()
    await send(
        {
            "type": "http.response.start",
            "status": 413,
            "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())],
        }
    )
    await send({"type": "http.response.body", "body": body})
