"""Per-request caller identity for audit trails - read out-of-band (HTTP
headers) rather than as a declared tool parameter.

Why not a tool parameter: a value the tool schema declares is something
any MCP caller can set, including an LLM deciding its own tool-call
arguments - which defeats the point of an audit trail meant to say who
actually asked. chat_app is the only caller expected to send these headers
today (see chat_app/src/services/commands.py's _IDENTITY_INJECTED_TOOLS),
attached on the underlying MCP HTTP call, never typed by the end user or
exposed in any tool's inputSchema. A caller that doesn't send them (a
different MCP client, or the LLM Q&A/ai_agent path, which doesn't thread
end-user identity today) just gets "" back from both getters below - never
an error.

IdentityContextMiddleware sets the contextvars for the lifetime of each
HTTP request; a domain function anywhere downstream reads them with
current_username()/current_email() instead of accepting the identity as an
argument.
"""

from __future__ import annotations

from contextvars import ContextVar

REQUESTER_USERNAME_HEADER = "x-requester-username"
REQUESTER_EMAIL_HEADER = "x-requester-email"

_username: ContextVar[str] = ContextVar("requester_username", default="")
_email: ContextVar[str] = ContextVar("requester_email", default="")


def current_username() -> str:
    return _username.get()


def current_email() -> str:
    return _email.get()


class IdentityContextMiddleware:
    """Plain ASGI middleware (not Starlette's BaseHTTPMiddleware, which
    runs the downstream app in a separate task and would need its own
    context-propagation care) - reads the identity headers straight off
    the incoming ASGI scope and sets both contextvars for exactly this
    request's task before calling through, resetting them again on the
    way out.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        raw_headers = dict(scope.get("headers") or [])
        username = raw_headers.get(REQUESTER_USERNAME_HEADER.encode("latin-1"), b"").decode("utf-8")
        email = raw_headers.get(REQUESTER_EMAIL_HEADER.encode("latin-1"), b"").decode("utf-8")

        username_token = _username.set(username)
        email_token = _email.set(email)
        try:
            await self.app(scope, receive, send)
        finally:
            _username.reset(username_token)
            _email.reset(email_token)
