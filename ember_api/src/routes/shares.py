"""Share links. `router` is for the logged-in account (chat.use): make, list
and revoke links. `public_router` is the one place a chat can be read without
logging in: GET /api/shared/{token}, read-only. See services/share_service.py
for what a link exposes and why."""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.deps import get_db_session, get_log_writer, get_share_limiter, require_permission
from src.models import Account, SharedChat
from src.routes.chats import ChatId, get_chat_service
from src.security import client_ip
from src.services.chat_service import ChatNotFound, ChatService
from src.services.log_service import LogWriter
from src.services.permissions import CHAT_USE
from src.services.public_rate_limiter import PublicReadLimiter
from src.services.share_service import (
    NothingToShare,
    ShareLimitError,
    ShareNotFound,
    ShareService,
    read_shared,
)

router = APIRouter(prefix="/api", tags=["shares"])
public_router = APIRouter(prefix="/api/shared", tags=["shares"])

require_chat = require_permission(CHAT_USE)

ShareId = Path(ge=1, le=2**31 - 1)
# secrets.token_urlsafe(32) is 43 characters; anything else cannot be a link.
_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{40,64}$")


def get_share_service(
    account: Account = Depends(require_chat),
    session: AsyncSession = Depends(get_db_session),
) -> ShareService:
    return ShareService(session, account.id)


class CreateShareRequest(BaseModel):
    # Days until the link stops working; null: it never does.
    expires_in_days: Literal[1, 7, 30] | None = 7


class ShareOut(BaseModel):
    id: int
    chat_id: str
    title: str
    message_count: int
    created_at: datetime
    expires_at: datetime | None

    @classmethod
    def of(cls, share: SharedChat) -> ShareOut:
        return cls(
            id=share.id,
            chat_id=share.chat_id,
            title=share.title,
            message_count=share.message_count,
            created_at=share.created_at,
            expires_at=share.expires_at,
        )


class ShareCreatedOut(ShareOut):
    # The link's secret, shown only in this response: ember_api keeps no copy.
    token: str


class SharedChatOut(BaseModel):
    title: str
    messages: list[dict[str, str]]
    created_at: datetime
    expires_at: datetime | None


def _not_found() -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, "Shared chat not found")


# --- the account's own links --------------------------------------------------------


@router.post("/chats/{chat_id}/shares", status_code=status.HTTP_201_CREATED)
async def create_share(
    body: CreateShareRequest,
    chat_id: str = ChatId,
    account: Account = Depends(require_chat),
    chats: ChatService = Depends(get_chat_service),
    shares: ShareService = Depends(get_share_service),
    logs: LogWriter = Depends(get_log_writer),
) -> ShareCreatedOut:
    """Freezes what may be shared of the chat (typed questions and plain
    answers) behind a new link. The response is the only time the link's token
    is shown."""
    try:
        chat = await chats.get(chat_id)
    except ChatNotFound as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Chat not found") from error
    try:
        created = await shares.create(chat, body.expires_in_days)
    except NothingToShare as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "This chat has nothing to share yet") from error
    except ShareLimitError as error:
        raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error
    expiry = f"{body.expires_in_days} days" if body.expires_in_days else "no expiry"
    await logs.action(account, "share.create", f'Shared chat "{chat.title}" (link {created.share.id}, {expiry})')
    return ShareCreatedOut(**ShareOut.of(created.share).model_dump(), token=created.token)


@router.get("/shares")
async def list_shares(
    chat_id: str | None = Query(default=None, pattern=r"^[A-Za-z0-9-]{8,64}$"),
    shares: ShareService = Depends(get_share_service),
) -> list[ShareOut]:
    """This account's active links (never their tokens), newest first;
    `chat_id` narrows them to one chat."""
    return [ShareOut.of(s) for s in await shares.list(chat_id)]


@router.delete("/shares/{share_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_share(
    share_id: int = ShareId,
    account: Account = Depends(require_chat),
    shares: ShareService = Depends(get_share_service),
    logs: LogWriter = Depends(get_log_writer),
) -> Response:
    try:
        share = await shares.revoke(share_id)
    except ShareNotFound as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Shared link not found") from error
    await logs.action(account, "share.revoke", f'Revoked the link {share.id} to chat "{share.title}"')
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- the public read ----------------------------------------------------------------


@public_router.get("/{token}")
async def read_shared_chat(
    token: str,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_db_session),
    limiter: PublicReadLimiter = Depends(get_share_limiter),
) -> SharedChatOut:
    """No login. A link that is unknown, revoked or expired gives the same
    404 as one that never existed. Never cached, never indexed."""
    wait = limiter.retry_after(client_ip(request))
    if wait is not None:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, "Too many requests - wait a moment", headers={"Retry-After": str(wait)}
        )
    share = await read_shared(session, token) if _TOKEN_PATTERN.fullmatch(token) else None
    if share is None:
        raise _not_found()
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    return SharedChatOut(
        title=share.title,
        messages=json.loads(share.messages),
        created_at=share.created_at,
        expires_at=share.expires_at,
    )

