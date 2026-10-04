"""Streams one MCP HTTP exchange between the browser and an upstream server.

Only a fixed set of headers crosses in either direction. The browser's own
cookies and any identity/token headers it tries to send are dropped; the
logged-in account's identity (and the internal token, if configured) are
added instead. Responses - including long-lived SSE streams - are relayed
chunk by chunk, and the upstream request is closed as soon as the browser
goes away.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

import httpx
from fastapi import Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from src.models import Account

logger = logging.getLogger(__name__)

# Lowercase; everything else from the browser is dropped.
_REQUEST_HEADERS = ("content-type", "accept", "mcp-session-id", "mcp-protocol-version", "last-event-id")
_RESPONSE_HEADERS = ("content-type", "mcp-session-id", "cache-control")


class McpProxy:
    def __init__(self, client: httpx.AsyncClient, internal_token: str | None) -> None:
        self._client = client
        self._internal_token = internal_token

    def _upstream_headers(self, request: Request, account: Account) -> dict[str, str]:
        headers = {name: request.headers[name] for name in _REQUEST_HEADERS if name in request.headers}
        # Same headers chat_app sets; mcp_server's IdentityContextMiddleware reads them.
        headers["X-Requester-Username"] = account.username
        headers["X-Requester-Email"] = account.email
        if self._internal_token:
            headers["X-Internal-Token"] = self._internal_token
        return headers

    async def forward(self, request: Request, upstream_url: str, account: Account, body: bytes | None) -> Response:
        upstream_request = self._client.build_request(
            request.method, upstream_url, headers=self._upstream_headers(request, account), content=body
        )
        try:
            upstream = await self._client.send(upstream_request, stream=True)
        except httpx.HTTPError as error:
            logger.warning("MCP upstream %s unreachable: %s", upstream_url, error)
            return JSONResponse({"detail": "Upstream server unreachable"}, status_code=502)

        async def relay() -> AsyncIterator[bytes]:
            # try/finally rather than a background task: on a browser
            # disconnect the generator is closed, and this still runs.
            try:
                async for chunk in upstream.aiter_bytes():
                    yield chunk
            finally:
                await upstream.aclose()

        headers = {name: upstream.headers[name] for name in _RESPONSE_HEADERS if name in upstream.headers}
        return StreamingResponse(relay(), status_code=upstream.status_code, headers=headers)
