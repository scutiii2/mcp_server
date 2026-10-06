"""/api/chats: the logged-in account's chat history, and the chat turns
ember_api runs for it (chat.use)."""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import Settings
from src.deps import (
    get_agent_gateway,
    get_db_session,
    get_log_writer,
    get_settings,
    get_settings_service,
    get_turns,
    require_permission,
)
from src.models import Account, Chat
from src.routes.mcp import get_agent_directory
from src.routes.server_info import EXTENSION_ID_PATTERN
from src.services import summarization
from src.services.agent_directory import NO_AGENT_RUNNING, AgentDirectory
from src.services.agent_gateway import AgentCallError, AgentGateway, Caller
from src.services.log_service import LogWriter
from src.services.chat_search import MAX_QUERY_CHARS, MIN_QUERY_CHARS, ChatSearch, SearchHit
from src.services.chat_service import (
    MAX_CHATS_PER_ACCOUNT,
    TITLE_MAX,
    ChatLimitError,
    ChatMessage,
    ChatNotFound,
    ChatService,
    ImportedChat,
    NotABranchPoint,
    decode_messages,
    message_time,
)
from src.services.folder_service import FolderNotFound
from src.services.permissions import CHAT_USE
from src.services.settings_service import FORCE_TOOL_APPROVAL, SettingsService
from src.services.turns import (
    MAX_AGENT_USAGE_ROWS,
    MAX_STEPS,
    STEP_RESULT_MAX,
    TooManyTurns,
    TurnConflict,
    TurnNotFound,
    TurnOptions,
    TurnRegistry,
)
from src.services.usage_service import LimitBlock, UsageService

router = APIRouter(prefix="/api/chats", tags=["chats"])

require_chat = require_permission(CHAT_USE)

_CHAT_ID_PATTERN = r"^[A-Za-z0-9-]{8,64}$"
# What the agent's tools are called (`tool_<capability>_<command>`, an
# extension's `<id>__<tool>`, `delegate_to_agent`).
_TOOL_NAME = re.compile(r"[A-Za-z0-9_.\-]{1,120}")
MAX_ALLOWED_TOOLS = 200
# Browser-made UUIDs; anything else is refused before touching the database.
ChatId = Path(pattern=_CHAT_ID_PATTERN)
# Room for a question plus a few attached files' text (20k characters each).
QUESTION_MAX = 200_000


def get_chat_service(
    account: Account = Depends(require_chat),
    session: AsyncSession = Depends(get_db_session),
) -> ChatService:
    return ChatService(session, account.id)


def get_chat_search(
    account: Account = Depends(require_chat),
    session: AsyncSession = Depends(get_db_session),
) -> ChatSearch:
    return ChatSearch(session, account.id)


# --- models ------------------------------------------------------------------


class StepIn(BaseModel):
    """One tool step of an answer, as ember_api saved it."""

    tool: str = Field(max_length=200)
    label: str = Field(default="", max_length=300)
    arguments: dict[str, Any] = Field(default_factory=dict)
    ok: bool | None = None
    result: str = Field(default="", max_length=STEP_RESULT_MAX)
    # Which agent ran it, when a delegated agent did.
    agent_id: str | None = Field(default=None, max_length=120)
    agent_label: str | None = Field(default=None, max_length=120)


class AgentUsageIn(BaseModel):
    """One agent's share of an answer that delegated to others."""

    agent: str = Field(max_length=120)
    agent_label: str | None = Field(default=None, max_length=120)
    provider_id: str | None = Field(default=None, max_length=60)
    gateway: str | None = Field(default=None, max_length=60)
    # ISO-8601 UTC ("...Z"), as ai_agent reported them.
    started_at: str | None = Field(default=None, max_length=40)
    finished_at: str | None = Field(default=None, max_length=40)
    model: str | None = Field(default=None, max_length=120)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int = Field(ge=0)


# What message_time() makes: 2026-10-06T14:03:09.123Z (a fraction is optional).
MESSAGE_TIME_PATTERN = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?Z$"


class MessageIn(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    # summary / log_attachment: written by summarize and clear; command: a
    # slash command's call and its result, shown but never asked about.
    kind: Literal["summary", "log_attachment", "command"] | None = None
    # When the message was written (UTC, as message_time makes it). Set by the
    # server for questions and answers; a browser sends back what it was given.
    at: str | None = Field(default=None, pattern=MESSAGE_TIME_PATTERN)
    model: str | None = Field(default=None, max_length=120)
    # The ember agent id that wrote an answer (saved by the turn).
    agent: str | None = Field(default=None, max_length=120)
    total_tokens: int | None = Field(default=None, ge=0)
    # The split of total_tokens, and how long the whole turn took (seconds).
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    duration_s: float | None = Field(default=None, ge=0)
    context_tokens: int | None = Field(default=None, ge=0)
    context_window: int | None = Field(default=None, ge=0)
    # The tool steps of an answer (saved by ember_api's turn; a browser
    # only sends them back when it re-saves or imports a chat).
    steps: list[StepIn] | None = Field(default=None, max_length=MAX_STEPS)
    # Who used the tokens when the answer ran several agents (its own plus
    # delegated ones); absent when only one did.
    agent_usage: list[AgentUsageIn] | None = Field(default=None, max_length=MAX_AGENT_USAGE_ROWS)


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


class UpdateChatRequest(BaseModel):
    """Any of: a new title, a folder (null: out of its folder), a pin."""

    title: str | None = Field(default=None, max_length=TITLE_MAX)
    folder_id: int | None = None
    pinned: bool | None = None

    @field_validator("title")
    @classmethod
    def clean_title(cls, title: str | None) -> str | None:
        return None if title is None else _clean_title(title)

    @model_validator(mode="after")
    def something_to_change(self) -> UpdateChatRequest:
        if self.title is None and self.pinned is None and "folder_id" not in self.model_fields_set:
            raise ValueError("send a title, a folder_id or pinned")
        return self


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
    # Ignored: every question goes to the entry agent. Kept so older browsers still validate.
    agent_id: str | None = Field(default=None, max_length=120)
    caveman: bool = False
    # mcp_server extension ids whose tools the agent may use.
    enabled_extensions: list[str] = Field(default_factory=list, max_length=50)

    @field_validator("enabled_extensions")
    @classmethod
    def extension_ids(cls, ids: list[str]) -> list[str]:
        bad = [i for i in ids if not re.fullmatch(EXTENSION_ID_PATTERN, i)]
        if bad:
            raise ValueError(f"not an extension id: {bad[0][:64]!r}")
        return ids
    # Ask the user before each tool runs (they answer through
    # POST /api/chats/{id}/approvals). allowed_tools: tools they already
    # allowed for this chat, which run without asking.
    ask_before_tools: bool = False
    allowed_tools: list[str] = Field(default_factory=list, max_length=MAX_ALLOWED_TOOLS)

    @field_validator("allowed_tools")
    @classmethod
    def tool_names(cls, names: list[str]) -> list[str]:
        bad = [n for n in names if not _TOOL_NAME.fullmatch(n)]
        if bad:
            raise ValueError(f"not a tool name: {bad[0][:64]!r}")
        return names

    # Used only when this turn creates the chat.
    title: str | None = Field(default=None, max_length=TITLE_MAX)
    # Regenerate / edit: index of the user question this one replaces. It and
    # everything after it are dropped before the new question is added.
    truncate_to: int | None = Field(default=None, ge=0)


class ApprovalRequest(BaseModel):
    # The tool run being answered: the `id` of an approval_request event.
    step_id: str = Field(min_length=1, max_length=200)
    # allow: run it this once. always: run it, and stop asking about this tool
    # for the rest of the turn (the browser remembers it for the chat).
    decision: Literal["allow", "always", "deny"]


class BranchRequest(BaseModel):
    # Index of the answer the new chat ends on.
    upto: int = Field(ge=0)


class AppendRequest(BaseModel):
    # Used only when this creates the chat.
    title: str = Field(max_length=TITLE_MAX)
    messages: list[MessageIn] = Field(min_length=1, max_length=20)

    @field_validator("title")
    @classmethod
    def clean_title(cls, title: str) -> str:
        return _clean_title(title)


class SummarizeRequest(BaseModel):
    # Ignored, see TurnRequest.agent_id.
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
    # The folder this chat is filed in (chat-folders id), and whether it is pinned.
    folder_id: int | None = None
    pinned: bool = False

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
            folder_id=chat.folder_id,
            pinned=chat.pinned,
        )


class ChatOut(ChatSummaryOut):
    messages: list[dict[str, Any]]

    @classmethod
    def of(cls, chat: Chat, running: bool = False) -> ChatOut:  # type: ignore[override]
        return cls(**ChatSummaryOut.of(chat, running).model_dump(), messages=decode_messages(chat))


class SpanOut(BaseModel):
    start: int
    length: int


class SnippetOut(BaseModel):
    text: str
    start: int
    length: int


class SearchHitOut(BaseModel):
    id: str
    title: str
    updated_at: datetime
    # Where the query sits in the title, if it does.
    title_match: SpanOut | None
    # The text around the first message containing it, and which message.
    snippet: SnippetOut | None
    message_index: int | None
    message_matches: int

    @classmethod
    def of(cls, hit: SearchHit) -> SearchHitOut:
        title = SpanOut(start=hit.title_match.start, length=hit.title_match.length) if hit.title_match else None
        snippet = (
            SnippetOut(text=hit.snippet.text, start=hit.snippet.match.start, length=hit.snippet.match.length)
            if hit.snippet
            else None
        )
        return cls(
            id=hit.chat.chat_id,
            title=hit.chat.title,
            updated_at=hit.chat.updated_at,
            title_match=title,
            snippet=snippet,
            message_index=hit.message_index,
            message_matches=hit.message_matches,
        )


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


def _replaced_from(existing: list[ChatMessage], index: int) -> list[ChatMessage]:
    """`existing` up to (not including) `index`, which must be a question the
    user typed - never a summary, a raw log or a slash command."""
    target = existing[index] if index < len(existing) else None
    if target is None or target.get("role") != "user" or target.get("kind"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Only a question you typed can be regenerated or edited")
    return existing[:index]


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


@router.get("/search")
async def search_chats(
    q: str = Query(min_length=MIN_QUERY_CHARS, max_length=MAX_QUERY_CHARS),
    search: ChatSearch = Depends(get_chat_search),
) -> list[SearchHitOut]:
    """Chats whose title or messages contain `q` (case-insensitive, literal),
    newest first, at most 50, each with a snippet around the first message
    match. Declared before /{chat_id}, which would otherwise take "search"."""
    return [SearchHitOut.of(hit) for hit in await search.search(q)]


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
async def update_chat(
    body: UpdateChatRequest,
    chat_id: str = ChatId,
    account: Account = Depends(require_chat),
    chats: ChatService = Depends(get_chat_service),
    turns: TurnRegistry = Depends(get_turns),
) -> ChatSummaryOut:
    """Renames, files (folder_id; null takes it out of its folder) or pins a
    chat. Allowed while an answer is being written: it changes no messages."""
    changes: dict[str, Any] = {"title": body.title, "pinned": body.pinned}
    if "folder_id" in body.model_fields_set:
        changes["folder_id"] = body.folder_id
    try:
        chat = await chats.update(chat_id, **changes)
    except ChatNotFound as error:
        raise _not_found() from error
    except FolderNotFound as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Folder not found") from error
    return ChatSummaryOut.of(chat, turns.is_running(account.id, chat_id))


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


@router.post("/{chat_id}/branch", status_code=status.HTTP_201_CREATED)
async def branch_chat(
    body: BranchRequest,
    chat_id: str = ChatId,
    chats: ChatService = Depends(get_chat_service),
) -> ChatOut:
    """Copies the chat up to and including the answer at `upto` into a new
    chat (new id, "Branch of <title>", same agent) and returns it. The
    original is unchanged, and may even be answering meanwhile: only saved
    messages are copied."""
    try:
        return ChatOut.of(await chats.branch(chat_id, body.upto))
    except ChatNotFound as error:
        raise _not_found() from error
    except NotABranchPoint as error:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "A branch can only end on one of the assistant's answers"
        ) from error
    except ChatLimitError as error:
        raise _too_large(error) from error


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
    app_settings: SettingsService = Depends(get_settings_service),
) -> TurnOut:
    """Saves the question and starts answering it in ember_api. The answer
    keeps going (and is saved) even if the browser leaves; watch it via
    /events."""
    agent = await directory.entry()
    if agent is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, NO_AGENT_RUNNING)
    if turns.is_running(account.id, chat_id):
        raise _busy()
    block = await UsageService(session, settings.usage).check(account.id)
    if block is not None:
        raise _limit_reached(block)

    question = {"role": "user", "content": body.question, "at": message_time()}
    try:
        try:
            existing = decode_messages(await chats.get(chat_id))
            if body.truncate_to is not None:
                existing = _replaced_from(existing, body.truncate_to)
            chat = await chats.replace_messages(chat_id, [*existing, question], agent_id=agent.id)
        except ChatNotFound:
            if body.truncate_to is not None:
                raise _not_found() from None
            title = _clean_title(body.title or body.question[:60])
            chat = await chats.put(chat_id, title, agent.id, [question])
    except ChatLimitError as error:
        raise _too_large(error) from error

    # When the administrator requires it, the browser's choice does not matter:
    # every tool asks, and no tool is pre-allowed.
    forced = await app_settings.get_bool(FORCE_TOOL_APPROVAL)
    try:
        options = TurnOptions(
            caveman=body.caveman,
            enabled_extensions=tuple(dict.fromkeys(body.enabled_extensions)),
            ask_before_tools=body.ask_before_tools or forced,
            allowed_tools=() if forced else tuple(dict.fromkeys(body.allowed_tools)),
        )
        turn = turns.start(account.id, chat_id, agent, _caller(account), options)
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


@router.post("/{chat_id}/approvals")
async def decide_approval(
    body: ApprovalRequest,
    chat_id: str = ChatId,
    account: Account = Depends(require_chat),
    turns: TurnRegistry = Depends(get_turns),
    logs: LogWriter = Depends(get_log_writer),
    app_settings: SettingsService = Depends(get_settings_service),
) -> dict[str, bool]:
    """Answers a tool the running answer is waiting to run (the `id` of an
    `approval_request` event). Only the chat's own account can; once a step is
    answered nothing else can answer it. Recorded in the activity log."""
    if not turns.is_running(account.id, chat_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No answer is being written for this chat")
    pending = turns.pending_approval(account.id, chat_id, body.step_id)
    if pending is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Nothing is waiting for that answer")
    # "Always" would let the tool skip asking for the rest of the turn; while
    # approval is required it means "this once".
    decision = body.decision
    if decision == "always" and await app_settings.get_bool(FORCE_TOOL_APPROVAL):
        decision = "allow"
    try:
        decided = await turns.decide(account.id, chat_id, body.step_id, decision)
    except AgentCallError as error:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(error)) from error
    if not decided:
        raise HTTPException(status.HTTP_409_CONFLICT, "Nothing is waiting for that answer")
    await logs.action(account, "tool.approval", f'{decision}: "{pending["tool"]}"')
    return {"decided": True}


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
    agent = await directory.entry()
    if agent is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, NO_AGENT_RUNNING)
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
