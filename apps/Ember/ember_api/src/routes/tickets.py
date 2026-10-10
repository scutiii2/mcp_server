"""/api/tickets: a signed-in account's own tickets (tickets.create), and
/api/admin/tickets + /api/admin/ticket-groups: every ticket for staff
(tickets.manage). ember_api only proxies to mcp_server's ticket core. The
reporter is always the logged-in account; the browser cannot name one, set
tags, or pick a source. Staff changes go to the activity log (ids and field
names only, never ticket text).
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from src.config import Settings
from src.deps import get_log_writer, get_settings, require_permission
from src.models import Account
from src.services.log_service import LogWriter
from src.services.mcp_server_info import McpServerInfo, McpServerRefused, McpServerUnavailable
from src.services.permissions import TICKETS_CREATE, TICKETS_MANAGE
from src.services.ticket_gateway import TicketGateway

router = APIRouter(prefix="/api/tickets", tags=["tickets"])
admin_router = APIRouter(prefix="/api/admin", tags=["tickets-admin"])

require_create = require_permission(TICKETS_CREATE)
require_manage = require_permission(TICKETS_MANAGE)

TicketType = Literal["bug", "feature", "other"]
TicketStatus = Literal["open", "in_progress", "resolved", "closed"]
TicketPriority = Literal["low", "normal", "high", "urgent"]
TicketId = Annotated[int, Path(ge=1)]


def get_ticket_gateway(request: Request, settings: Settings = Depends(get_settings)) -> TicketGateway:
    return TicketGateway(
        McpServerInfo(request.app.state.upstream, settings.mcp_server_url, request.app.state.internal_token, request.app.state.traffic)
    )


async def _call(awaitable: Any) -> Any:
    try:
        return await awaitable
    except McpServerUnavailable as error:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "mcp_server is unreachable") from error
    except McpServerRefused as error:
        code = status.HTTP_404_NOT_FOUND if error.status == 404 else status.HTTP_400_BAD_REQUEST
        raise HTTPException(code, str(error)) from error


class TicketIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: TicketType
    title: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=4000)


class CommentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    body: str = Field(min_length=1, max_length=2000)


# ---- reporter routes -------------------------------------------------------

@router.post("")
async def create_ticket(
    body: TicketIn, account: Account = Depends(require_create), gateway: TicketGateway = Depends(get_ticket_gateway),
) -> JSONResponse:
    payload = {
        **body.model_dump(),
        "source": "user",
        "verified_context": {"via": "ember_api", "account_id": str(account.id)},
    }
    result = await _call(gateway.create(account, payload))
    return JSONResponse(result, status_code=200 if result.get("duplicate") else 201)


@router.get("")
async def list_own_tickets(
    status_filter: Annotated[TicketStatus | None, Query(alias="status")] = None,
    account: Account = Depends(require_create), gateway: TicketGateway = Depends(get_ticket_gateway),
) -> Any:
    return await _call(gateway.list_own(account, status_filter))


@router.get("/{ticket_id}")
async def get_own_ticket(
    ticket_id: TicketId, account: Account = Depends(require_create), gateway: TicketGateway = Depends(get_ticket_gateway),
) -> Any:
    return await _call(gateway.get_own(account, ticket_id))


@router.post("/{ticket_id}/comments")
async def comment_own_ticket(
    ticket_id: TicketId, body: CommentIn,
    account: Account = Depends(require_create), gateway: TicketGateway = Depends(get_ticket_gateway),
) -> Any:
    return await _call(gateway.comment_own(account, ticket_id, body.body))


@router.post("/{ticket_id}/close")
async def close_own_ticket(
    ticket_id: TicketId, account: Account = Depends(require_create), gateway: TicketGateway = Depends(get_ticket_gateway),
) -> Any:
    return await _call(gateway.close_own(account, ticket_id))
