"""The shared internal token and the asking user's identity, both ways.

Inbound: every caller of this agent's /mcp is another server in this repo
(chat_app, ember_api, a delegating peer agent), so once INTERNAL_API_TOKEN
is configured (.env, the same value as
mcp_server's, chat_app's and ember_api's) InternalTokenMiddleware rejects a
request without it.

Outbound: the same token goes on this agent's own calls - to mcp_server
(mcp_upstream.py) and to peers (delegation.py) - and so does the asking
user. ask() reads X-Requester-Username / X-Requester-Email off the HTTP
request (set by ember_api / chat_app, never by the model) and binds them
for the turn with bind_requester(). The persistent mcp_server session is
shared by every user, so the identity travels in each tool call's `_meta`
(requester_meta()) instead of in headers; mcp_server's identity_context.py
reads it from there.
"""

from __future__ import annotations

import hmac
import json
import os
from contextvars import ContextVar, Token
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from dotenv import dotenv_values

from src.core.seed import seed_from_example

_SECRETS_PATH = Path(__file__).resolve().parent.parent.parent / ".env"

INTERNAL_TOKEN_HEADER = "X-Internal-Token"
REQUESTER_USERNAME_HEADER = "X-Requester-Username"
REQUESTER_EMAIL_HEADER = "X-Requester-Email"
REQUESTER_META_KEY = "requester"
# /registry lists every agent's URL, so it sits behind the token like /mcp.
PROTECTED_PATHS = ("/mcp", "/registry")


def load_token() -> str:
    """INTERNAL_API_TOKEN from the environment, else from the secret file
    (seeded from its .example on first run). "" = not configured."""
    seed_from_example(_SECRETS_PATH)
    return os.getenv("INTERNAL_API_TOKEN") or dotenv_values(_SECRETS_PATH).get("INTERNAL_API_TOKEN") or ""


TOKEN = load_token()


@dataclass(frozen=True)
class Requester:
    username: str = ""
    email: str = ""

    @classmethod
    def from_headers(cls, headers: Mapping[str, str] | None) -> "Requester":
        if headers is None:
            return cls()
        username = headers.get(REQUESTER_USERNAME_HEADER, "")
        email = headers.get(REQUESTER_EMAIL_HEADER, "")
        return cls(username if isinstance(username, str) else "", email if isinstance(email, str) else "")

    def __bool__(self) -> bool:
        return bool(self.username or self.email)


_requester: ContextVar[Requester] = ContextVar("requester", default=Requester())


def bind_requester(requester: Requester) -> Token:
    return _requester.set(requester)


def reset_requester(token: Token) -> None:
    _requester.reset(token)


def current_requester() -> Requester:
    return _requester.get()


def requester_meta() -> dict[str, Any] | None:
    """The `_meta` for an outbound tool call carrying the current user, or
    None when this turn has no known user (the call keeps its old shape)."""
    requester = current_requester()
    if not requester:
        return None
    return {REQUESTER_META_KEY: {"username": requester.username, "email": requester.email}}


def outbound_headers() -> dict[str, str]:
    """Headers for a fresh HTTP MCP session to a peer agent: the token, if
    configured, and the current user, if known."""
    headers: dict[str, str] = {}
    if TOKEN:
        headers[INTERNAL_TOKEN_HEADER] = TOKEN
    requester = current_requester()
    if requester.username:
        headers[REQUESTER_USERNAME_HEADER] = requester.username
    if requester.email:
        headers[REQUESTER_EMAIL_HEADER] = requester.email
    return headers


class InternalTokenMiddleware:
    """Plain ASGI middleware: a request to /mcp or /registry whose X-Internal-Token
    doesn't match (constant-time) gets 401 JSON before the MCP transport
    sees it. Does nothing when no token is configured."""

    def __init__(self, app, token: str) -> None:
        self.app = app
        self._token = token.encode("utf-8")

    def _protects(self, scope) -> bool:
        if not self._token or scope["type"] != "http":
            return False
        path = scope.get("path", "")
        return any(path == p or path.startswith(p + "/") for p in PROTECTED_PATHS)

    async def __call__(self, scope, receive, send):
        if self._protects(scope):
            provided = dict(scope.get("headers") or []).get(INTERNAL_TOKEN_HEADER.lower().encode("latin-1"), b"")
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
