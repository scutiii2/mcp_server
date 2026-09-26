"""/api/chats: the logged-in account's chat history, and the chat turns
ember_api runs for it (chat.use)."""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import Settings
from src.deps import get_agent_gateway, get_db_session, get_settings, get_turns, require_permission
from src.models import Account, Chat
from src.routes.mcp import get_agent_directory
from src.services import summarization
from src.services.agent_directory import AgentDirectory
from src.services.agent_gateway import AgentGateway, Caller
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
from src.services.turns import TooManyTurns, TurnConflict, TurnNotFound, TurnRegistry
from src.services.usage_service import LimitBlock, UsageService

router = APIRouter(prefix="/api/chats", tags=["chats"])

require_chat = require_permission(CHAT_USE)

_CHAT_ID_PATTERN = r"^[A-Za-z0-9-]{8,64}$"
# Browser-made UUIDs; anything else is refused before touching the database.
ChatId = Path(pattern=_CHAT_ID_PATTERN)
TITLE_MAX = 120
QUESTION_MAX = 100_000


def get_chat_service(
    account: Account = Depends(require_chat),
    session: AsyncSession = Depends(get_db_session),
) -> ChatService:
    return ChatService(session, account.id)


# --- models ------------------------------------------------------------------


class MessageIn(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    # summary / log_attachment: written by summarize and clear; command: a
    # slash command's call and its result, shown but never asked about.
    kind: Literal["summary", "log_attachment", "command"] | None = None
    model: str | None = Field(default=None, max_length=120)
    total_tokens: int | None = Field(default=None, ge=0)
    context_tokens: int | None = Field(default=None, ge=0)
    context_window: int | None = Field(default=None, ge=0)


def _clean_title(title: str) -> str:
    cleaned = " ".join(title.split())
    if not cleaned:
        raise ValueError("title must not be blank")
    return cleaned


class RenameRequest(BaseModel):
    title: str = Field(max_length=TITLE_MAX)

    @field_validator("title")
    @classmethod
    def clean_title(cls, title: str) -> str:
        return _clean_title(title)


class PutChatRequest(RenameRequest):
    agent_id: str | None = Field(default=None, max_length=120)
    messages: list[MessageIn]


class ImportItem(PutChatRequest):
    id: str = Field(pattern=_CHAT_ID_PATTERN)
    # Milliseconds since the epoch, as the browser stored them.
    created_at: int = Field(ge=0)
    updated_at: int = Field(ge=0)


class ImportRequest(BaseModel):
    chats: list[ImportItem] = Field(max_length=MAX_CHATS_PER_ACCOUNT)


class TurnRequest(BaseModel):
    question: str = Field(min_length=1, max_length=QUESTION_MAX)
    agent_id: str = Field(min_length=1, max_length=120)
    caveman: bool = False
    # Used only when this turn creates the chat.
    title: str | None = Field(default=None, max_length=TITLE_MAX)


class AppendRequest(BaseModel):
    # Used only when this creates the chat.
    title: str = Field(max_length=TITLE_MAX)
    messages: list[MessageIn] = Field(min_length=1, max_length=20)

    @field_validator("title")
    @classmethod
    def clean_title(cls, title: str) -> str:
        return _clean_title(title)


class SummarizeRequest(BaseModel):
    # Which agent writes the summary; defaults to the chat's own agent.
    agent_id: str | None = Field(default=None, max_length=120)


class ChatSummaryOut(BaseModel):
    id: str
    title: str
    agent_id: str | None
    message_count: int
    created_at: datetime
    updated_at: datetime
    # An answer is being written for this chat right now.
    running: bool = False

    @classmethod
    def of(cls, chat: Chat, running: bool = False) -> ChatSummaryOut:
        return cls(
            id=chat.chat_id,
            title=chat.title,
            agent_id=chat.agent_id,
            message_count=chat.message_count,
            created_at=chat.created_at,
            updated_at=chat.updated_at,
            running=running,
        )


class ChatOut(ChatSummaryOut):
    messages: list[dict[str, Any]]

    @classmethod
    def of(cls, chat: Chat, running: bool = False) -> ChatOut:  # type: ignore[override]
        return cls(**ChatSummaryOut.of(chat, running).model_dump(), messages=decode_messages(chat))


class ImportOut(BaseModel):
    imported: int
    skipped: int


class TurnOut(BaseModel):
    chat: ChatSummaryOut
    # Subscribe to /events with after=this to get only newer events.
    sequence: int


def _messages(items: list[MessageIn]) -> list[ChatMessage]:
    return [m.model_dump(exclude_none=True) for m in items]


def _from_ms(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).replace(tzinfo=None)


def _not_found() -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, "Chat not found")


def _too_large(error: ChatLimitError) -> HTTPException:
    return HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, str(error))


def _busy() -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, "An answer is still being written for this chat")


def _limit_reached(block: LimitBlock) -> HTTPException:
    minutes = max(1, int((block.reset_at - datetime.now(timezone.utc).replace(tzinfo=None)).total_seconds() // 60) + 1)
    wait = f"{minutes} min" if minutes < 60 else f"{minutes // 60} h {minutes % 60} min"
    return HTTPException(
        status.HTTP_429_TOO_MANY_REQUESTS,
        f"You've reached your {block.reason}. It frees up in about {wait}.",
        headers={"Retry-After": str(minutes * 60)},
    )


def _caller(account: Account) -> Caller:
    return Caller(username=account.username, email=account.email)


# --- history -----------------------------------------------------------------


@router.get("")
async def list_chats(
    account: Account = Depends(require_chat),
    chats: ChatService = Depends(get_chat_service),
    turns: TurnRegistry = Depends(get_turns),
) -> list[ChatSummaryOut]:
    running = turns.running_chat_ids(account.id)
    return [ChatSummaryOut.of(c, c.chat_id in running) for c in await chats.list()]


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def delete_all_chats(
    account: Account = Depends(require_chat),
    chats: ChatService = Depends(get_chat_service),
    turns: TurnRegistry = Depends(get_turns),
) -> Response:
    await turns.discard_account(account.id)
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
async def get_chat(
    chat_id: str = ChatId,
    account: Account = Depends(require_chat),
    chats: ChatService = Depends(get_chat_service),
    turns: TurnRegistry = Depends(get_turns),
) -> ChatOut:
    try:
        return ChatOut.of(await chats.get(chat_id), turns.is_running(account.id, chat_id))
    except ChatNotFound as error:
        raise _not_found() from error


@router.put("/{chat_id}")
async def put_chat(
    body: PutChatRequest,
    chat_id: str = ChatId,
    account: Account = Depends(require_chat),
    chats: ChatService = Depends(get_chat_service),
    turns: TurnRegistry = Depends(get_turns),
) -> ChatSummaryOut:
    """Creates the chat or replaces it whole. Refused while an answer is
    being written, which would otherwise be lost or land in the wrong place."""
    if turns.is_running(account.id, chat_id):
        raise _busy()
    try:
        chat = await chats.put(chat_id, body.title, body.agent_id, _messages(body.messages))
    except ChatLimitError as error:
        raise _too_large(error) from error
    return ChatSummaryOut.of(chat)


@router.patch("/{chat_id}")
async def rename_chat(
    body: RenameRequest,
    chat_id: str = ChatId,
    account: Account = Depends(require_chat),
    chats: ChatService = Depends(get_chat_service),
    turns: TurnRegistry = Depends(get_turns),
) -> ChatSummaryOut:
    try:
        return ChatSummaryOut.of(await chats.rename(chat_id, body.title), turns.is_running(account.id, chat_id))
    except ChatNotFound as error:
        raise _not_found() from error


@router.delete("/{chat_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_chat(
    chat_id: str = ChatId,
    account: Account = Depends(require_chat),
    chats: ChatService = Depends(get_chat_service),
    turns: TurnRegistry = Depends(get_turns),
) -> Response:
    """Also stops an answer still being written for it."""
    try:
        await chats.get(chat_id)
    except ChatNotFound as error:
        raise _not_found() from error
    await turns.discard(account.id, chat_id)
    await chats.delete(chat_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{chat_id}/messages")
async def append_messages(
    body: AppendRequest,
    chat_id: str = ChatId,
    account: Account = Depends(require_chat),
    chats: ChatService = Depends(get_chat_service),
    turns: TurnRegistry = Depends(get_turns),
) -> ChatSummaryOut:
    """Adds messages the browser produced itself - a slash command and its
    result - creating the chat if needed."""
    if turns.is_running(account.id, chat_id):
        raise _busy()
    extra = _messages(body.messages)
    try:
        try:
            existing = decode_messages(await chats.get(chat_id))
            chat = await chats.replace_messages(chat_id, [*existing, *extra])
        except ChatNotFound:
            chat = await chats.put(chat_id, body.title, None, extra)
    except ChatLimitError as error:
        raise _too_large(error) from error
    return ChatSummaryOut.of(chat)


# --- turns ---------------------------------------------------------------------


@router.post("/{chat_id}/turns", status_code=status.HTTP_202_ACCEPTED)
async def start_turn(
    body: TurnRequest,
    chat_id: str = ChatId,
    account: Account = Depends(require_chat),
    chats: ChatService = Depends(get_chat_service),
    session: AsyncSession = Depends(get_db_session),
    turns: TurnRegistry = Depends(get_turns),
    directory: AgentDirectory = Depends(get_agent_directory),
    settings: Settings = Depends(get_settings),
) -> TurnOut:
    """Saves the question and starts answering it in ember_api. The answer
    keeps going (and is saved) even if the browser leaves; watch it via
    /events."""
    agent = await directory.get(body.agent_id)
    if agent is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown agent")
    if turns.is_running(account.id, chat_id):
        raise _busy()
    block = await UsageService(session, settings.usage).check(account.id)
    if block is not None:
        raise _limit_reached(block)

    question = {"role": "user", "content": body.question}
    try:
        try:
            existing = decode_messages(await chats.get(chat_id))
            chat = await chats.replace_messages(chat_id, [*existing, question], agent_id=agent.id)
        except ChatNotFound:
            title = _clean_title(body.title or body.question[:60])
            chat = await chats.put(chat_id, title, agent.id, [question])
    except ChatLimitError as error:
        raise _too_large(error) from error

    try:
        turn = turns.start(account.id, chat_id, agent, _caller(account), body.caveman)
    except TurnConflict as error:
        raise _busy() from error
    except TooManyTurns as error:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, "Too many answers running at once - wait for one to finish"
        ) from error
    return TurnOut(chat=ChatSummaryOut.of(chat, running=True), sequence=turn.sequence)


@router.get("/{chat_id}/events")
async def turn_events(
    request: Request,
    chat_id: str = ChatId,
    after: int = Query(default=0, ge=0),
    account: Account = Depends(require_chat),
    turns: TurnRegistry = Depends(get_turns),
) -> StreamingResponse:
    """Server-Sent Events for the chat's current (or just finished) turn:
    a snapshot of the text so far when joining late, then live events, and
    last a "final" or "error" event. 404 when there is no turn to watch."""
    last_event_id = request.headers.get("last-event-id", "")
    if last_event_id.isdigit():
        after = max(after, int(last_event_id))
    try:
        events = await turns.subscribe(account.id, chat_id, after)
    except TurnNotFound as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No answer is being written for this chat") from error

    async def stream() -> AsyncIterator[bytes]:
        async for event in events:
            if event.get("type") == "ping":
                yield b": ping\n\n"
                continue
            yield f"id: {event['sequence']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n".encode()

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/{chat_id}/cancel")
async def cancel_turn(
    chat_id: str = ChatId,
    account: Account = Depends(require_chat),
    turns: TurnRegistry = Depends(get_turns),
) -> dict[str, bool]:
    return {"cancelled": await turns.cancel(account.id, chat_id)}


# --- summarize / clear ---------------------------------------------------------


@router.post("/{chat_id}/summarize")
async def summarize_chat(
    body: SummarizeRequest,
    chat_id: str = ChatId,
    account: Account = Depends(require_chat),
    chats: ChatService = Depends(get_chat_service),
    session: AsyncSession = Depends(get_db_session),
    turns: TurnRegistry = Depends(get_turns),
    directory: AgentDirectory = Depends(get_agent_directory),
    gateway: AgentGateway = Depends(get_agent_gateway),
    settings: Settings = Depends(get_settings),
) -> ChatOut:
    """Replaces the history with one summary (what the agent sees from now
    on) plus the raw log it replaced. Nothing changes if it fails. Counts
    toward the usage limits like a chat turn."""
    if turns.is_running(account.id, chat_id):
        raise _busy()
    try:
        chat = await chats.get(chat_id)
    except ChatNotFound as error:
        raise _not_found() from error
    agent = await directory.get(body.agent_id or chat.agent_id or "")
    if agent is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown agent")
    usage = UsageService(session, settings.usage)
    block = await usage.check(account.id)
    if block is not None:
        raise _limit_reached(block)

    try:
        outcome = await summarization.summarize(gateway, agent.url, _caller(account), decode_messages(chat))
    except summarization.SummarizeError as error:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Couldn't summarize: {error}") from error
    if outcome is None:
        return ChatOut.of(chat)  # nothing new since the last summary
    turn_id = uuid.uuid4().hex
    for result in outcome.results:
        await usage.record(account.id, turn_id, "summary", chat_id, result)
    try:
        chat = await chats.replace_messages(chat_id, outcome.messages)
    except ChatNotFound as error:
        raise _not_found() from error
    return ChatOut.of(chat)


@router.post("/{chat_id}/clear")
async def clear_chat(
    chat_id: str = ChatId,
    account: Account = Depends(require_chat),
    chats: ChatService = Depends(get_chat_service),
    turns: TurnRegistry = Depends(get_turns),
) -> ChatOut:
    """Starts the conversation afresh without asking an agent: the old
    messages are kept as one raw log the agent never sees again."""
    if turns.is_running(account.id, chat_id):
        raise _busy()
    try:
        chat = await chats.get(chat_id)
        messages = summarization.cleared(decode_messages(chat))
        if messages is not None:
            chat = await chats.replace_messages(chat_id, messages)
    except ChatNotFound as error:
        raise _not_found() from error
    except ChatLimitError as error:
        raise _too_large(error) from error
    return ChatOut.of(chat)
