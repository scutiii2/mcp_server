"""/api/watchers: status of mcp_server's background watchers, every
capability's at once (port of chat_app's Watchers page; watchers.view).
Live data - nothing is stored here. Recipients are read-only; they're set
on the mcp_server side."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from src.deps import require_permission
from src.models import Account
from src.services.agent_gateway import Caller
from src.services.permissions import WATCHERS_VIEW
from src.services.server_tools import ServerTools, ServerUnavailable

router = APIRouter(prefix="/api/watchers", tags=["watchers"])

require_watchers = require_permission(WATCHERS_VIEW)


def get_server_tools(request: Request) -> ServerTools:
    return request.app.state.server_tools


class WatchersOut(BaseModel):
    # Each row as the capability reports it (key, phase, started_at,
    # last_polled_at, detail, recipients) plus "capability".
    watchers: list[dict[str, Any]]
    errors: list[str]


@router.get("")
async def list_watchers(
    account: Account = Depends(require_watchers), tools: ServerTools = Depends(get_server_tools)
) -> WatchersOut:
    """502 when mcp_server is unreachable, or when every capability failed."""
    try:
        report = await tools.watchers(Caller(username=account.username, email=account.email))
    except ServerUnavailable as error:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"mcp_server is unreachable: {error}") from error
    if report.errors and not report.watchers:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "; ".join(report.errors))
    return WatchersOut(watchers=report.watchers, errors=report.errors)
