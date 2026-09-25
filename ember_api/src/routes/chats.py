"""/api/chats: the logged-in account's chat history (chat.use)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Response, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from src.deps import get_db_session, require_permission
from src.models import Account, Chat
from src.services.chat_service import (
    MAX_CHATS_PER_ACCOUNT,
    ChatLimitError,
    ChatMessage,
    ChatNotFound,
    ChatService,
    ImportedChat,
    decode_messages,
)
from src.services.permissions import CHAT_USE

router = APIRouter(prefix="/api/chats", tags=["chats"])

require_chat = require_permission(CHAT_USE)

# Browser-made UUIDs; anything else is refused before touching the database.
ChatId = Path(pattern=r"^[A-Za-z0-9-]{8,64}$")


def get_chat_service(
    account: Account = Depends(require_chat),
    session: AsyncSession = Depends(get_db_session),
) -> ChatService:
    return ChatService(session, account.id)


# --- models ------------------------------------------------------------------


class MessageIn(BaseModel):
    role: Literal["user", "assistant"]
    content: str


def _clean_title(title: str) -> str:
    cleaned = " ".join(title.split())
    if not cleaned:
        raise ValueError("title must not be blank")
    return cleaned


class RenameRequest(BaseModel):
    title: str = Field(max_length=120)

    @field_validator("title")
    @classmethod
    def clean_title(cls, title: str) -> str:
        return _clean_title(title)


class PutChatRequest(RenameRequest):
    agent_id: str | None = Field(default=None, max_length=120)
    messages: list[MessageIn]


class ImportItem(PutChatRequest):
    id: str = Field(pattern=r"^[A-Za-z0-9-]{8,64}$")
    # Milliseconds since the epoch, as the browser stored them.
    created_at: int = Field(ge=0)
    updated_at: int = Field(ge=0)


class ImportRequest(BaseModel):
    chats: list[ImportItem] = Field(max_length=MAX_CHATS_PER_ACCOUNT)


class ChatSummaryOut(BaseModel):
    id: str
    title: str
    agent_id: str | None
    message_count: int
    created_at: datetime
    updated_at: datetime

    @classmethod
    def of(cls, chat: Chat) -> ChatSummaryOut:
        return cls(
            id=chat.chat_id,
            title=chat.title,
            agent_id=chat.agent_id,
            message_count=chat.message_count,
            created_at=chat.created_at,
            updated_at=chat.updated_at,
        )


class MessageOut(BaseModel):
    role: str
    content: str


class ChatOut(ChatSummaryOut):
    messages: list[MessageOut]

    @classmethod
    def of(cls, chat: Chat) -> ChatOut:  # type: ignore[override]
        return cls(
            **ChatSummaryOut.of(chat).model_dump(),
            messages=[MessageOut(**m) for m in decode_messages(chat)],
        )


class ImportOut(BaseModel):
    imported: int
    skipped: int


def _messages(items: list[MessageIn]) -> list[ChatMessage]:
    return [ChatMessage(role=m.role, content=m.content) for m in items]


def _from_ms(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).replace(tzinfo=None)


def _not_found() -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, "Chat not found")


def _too_large(error: ChatLimitError) -> HTTPException:
    return HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, str(error))


# --- routes ------------------------------------------------------------------


@router.get("")
async def list_chats(chats: ChatService = Depends(get_chat_service)) -> list[ChatSummaryOut]:
    return [ChatSummaryOut.of(c) for c in await chats.list()]


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def delete_all_chats(chats: ChatService = Depends(get_chat_service)) -> Response:
    await chats.delete_all()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/import")
async def import_chats(body: ImportRequest, chats: ChatService = Depends(get_chat_service)) -> ImportOut:
    """One-time upload of chats this browser kept locally before chat
    history moved to the server. Existing ids are skipped, never replaced."""
    items = [
        ImportedChat(
            chat_id=c.id,
            title=c.title,
            agent_id=c.agent_id,
            messages=_messages(c.messages),
            created_at=_from_ms(c.created_at),
            updated_at=_from_ms(c.updated_at),
        )
        for c in body.chats
    ]
    try:
        imported, skipped = await chats.import_chats(items)
    except ChatLimitError as error:
        raise _too_large(error) from error
    return ImportOut(imported=imported, skipped=skipped)


@router.get("/{chat_id}")
async def get_chat(chat_id: str = ChatId, chats: ChatService = Depends(get_chat_service)) -> ChatOut:
    try:
        return ChatOut.of(await chats.get(chat_id))
    except ChatNotFound as error:
        raise _not_found() from error


@router.put("/{chat_id}")
async def put_chat(
    body: PutChatRequest,
    chat_id: str = ChatId,
    chats: ChatService = Depends(get_chat_service),
) -> ChatSummaryOut:
    """Creates the chat or replaces it whole (after each finished turn)."""
    try:
        chat = await chats.put(chat_id, body.title, body.agent_id, _messages(body.messages))
    except ChatLimitError as error:
        raise _too_large(error) from error
    return ChatSummaryOut.of(chat)


@router.patch("/{chat_id}")
async def rename_chat(
    body: RenameRequest,
    chat_id: str = ChatId,
    chats: ChatService = Depends(get_chat_service),
) -> ChatSummaryOut:
    try:
        return ChatSummaryOut.of(await chats.rename(chat_id, body.title))
    except ChatNotFound as error:
        raise _not_found() from error


@router.delete("/{chat_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_chat(chat_id: str = ChatId, chats: ChatService = Depends(get_chat_service)) -> Response:
    try:
        await chats.delete(chat_id)
    except ChatNotFound as error:
        raise _not_found() from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)
