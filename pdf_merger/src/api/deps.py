"""Request-scoped dependencies: the service and who is calling."""

from __future__ import annotations

import hmac
import re
import secrets

from fastapi import Request, Response

from src.service import Caller, MergeService

COOKIE_NAME = "pm_session"
TOKEN_HEADER = "X-Internal-Token"
REQUESTER_HEADER = "X-Requester-Username"
_SESSION_RE = re.compile(r"[A-Za-z0-9_-]{32}")


def get_service(request: Request) -> MergeService:
    return request.app.state.service


def _token_valid(request: Request) -> bool:
    """Constant-time compare. An unset expected token never validates."""
    expected = request.app.state.settings.internal_api_token
    provided = request.headers.get(TOKEN_HEADER, "")
    return bool(expected) and hmac.compare_digest(expected.encode("utf-8"), provided.encode("utf-8", "replace"))


def get_caller(request: Request, response: Response) -> Caller:
    if _token_valid(request):
        username = request.headers.get(REQUESTER_HEADER, "").strip() or "anonymous"
        return Caller(session=f"mcp:{username}", privileged=True)

    session_id = request.cookies.get(COOKIE_NAME, "")
    if not _SESSION_RE.fullmatch(session_id):
        session_id = secrets.token_urlsafe(24)  # 32 URL-safe characters
        response.set_cookie(
            COOKIE_NAME,
            session_id,
            max_age=request.app.state.settings.file_ttl_seconds,
            httponly=True,
            samesite="strict",
        )
    return Caller(session=f"web:{session_id}")
