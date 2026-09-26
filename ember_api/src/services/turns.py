"""Server-run chat turns (port of chat_app/src/services/chat_jobs.py, on
asyncio instead of threads).

ember_api asks the agent itself, saves the answer and records the tokens,
so a turn finishes even if the browser closes. Browsers only watch: any
number of them can subscribe to a turn's live events, leave, and come back.

Replay stays small however long the answer is: streamed text is kept as one
growing string, and a subscriber that joins late (or fell behind the event
buffer) first gets a "snapshot" of the text so far, then live events.

Turns survive browser disconnects, not an ember_api restart: on shutdown a
running turn saves what it has, marked as interrupted.
"""

from __future__ import annotations

import asyncio
import json
import logging
import traceback
import uuid
from collections import deque
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from itertools import count
from time import monotonic
from typing import Any

from src.config import UsageSettings
from src.db import Database
from src.services import summarization
from src.services.agent_directory import AgentEntry
from src.services.agent_gateway import AgentCallError, AgentGateway, Caller
from src.services.chat_service import ChatNotFound, ChatService, decode_messages
from src.services.log_service import LogWriter
from src.services.usage_service import UsageService

logger = logging.getLogger(__name__)

TERMINAL = ("final", "error")
# Events a subscriber can't rebuild from the snapshot are kept; tokens are
# folded into Turn.text instead, so this bounds memory, not answer length.
EVENT_BUFFER = 256
HEARTBEAT_SECONDS = 15.0
# How much of an answer the chat-turn log keeps.
TRACE_RESPONSE_MAX = 4000


class TurnConflict(Exception):
    """This chat already has a turn running."""


class TooManyTurns(Exception):
    """This account already runs the maximum number of turns."""


class TurnNotFound(Exception):
    """No turn for this chat (never started, or its replay expired)."""


@dataclass(frozen=True)
class TurnOptions:
    """What the browser chose for this question."""

    caveman: bool = False
    # Extensions whose tools the agent may use (none by default).
    enabled_extensions: tuple[str, ...] = ()


@dataclass(eq=False)
class Turn:
    account_id: int
    chat_id: str
    agent: AgentEntry
    caller: Caller
    options: TurnOptions = field(default_factory=TurnOptions)
    request_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    question: str = ""
    started_at: float = field(default_factory=monotonic)
    status: str = "running"  # running | completed | failed | cancelled
    text: str = ""  # answer streamed so far
    activity: str = ""  # current tool step label, if any
    sequence: int = 0
    events: deque = field(default_factory=lambda: deque(maxlen=EVENT_BUFFER))
    condition: asyncio.Condition = field(default_factory=asyncio.Condition)
    cancel_requested: bool = False
    asking: bool = False
    task: asyncio.Task | None = None
    finished_at: float | None = None

    def snapshot(self) -> dict[str, Any]:
        return {"type": "snapshot", "text": self.text, "activity": self.activity, "sequence": self.sequence}


class TurnRegistry:
    """One per app; every lookup is scoped to an account."""

    def __init__(
        self,
        database: Database,
        gateway: AgentGateway,
        usage: UsageSettings,
        logs: LogWriter,
        *,
        max_running_per_account: int = 3,
        retention_seconds: float = 120.0,
    ) -> None:
        self._database = database
        self._gateway = gateway
        self._usage = usage
        self._logs = logs
        self._max_running = max_running_per_account
        self._retention = retention_seconds
        self._turns: dict[tuple[int, str], Turn] = {}
        self._sequences = count(1)

    # --- queries -------------------------------------------------------------

    def get(self, account_id: int, chat_id: str) -> Turn | None:
        self._expire_finished()
        return self._turns.get((account_id, chat_id))

    def is_running(self, account_id: int, chat_id: str) -> bool:
        turn = self.get(account_id, chat_id)
        return turn is not None and turn.status == "running"

    def running_chat_ids(self, account_id: int) -> set[str]:
        return {c for (a, c), t in self._turns.items() if a == account_id and t.status == "running"}

    # --- control -------------------------------------------------------------

    def start(
        self, account_id: int, chat_id: str, agent: AgentEntry, caller: Caller, options: TurnOptions | None = None
    ) -> Turn:
        """Starts answering the chat's last message (the caller saved the
        question first). Returns at once; the work runs as a task."""
        if self.is_running(account_id, chat_id):
            raise TurnConflict(chat_id)
        if len(self.running_chat_ids(account_id)) >= self._max_running:
            raise TooManyTurns(account_id)
        turn = Turn(account_id=account_id, chat_id=chat_id, agent=agent, caller=caller, options=options or TurnOptions())
        self._turns[(account_id, chat_id)] = turn
        turn.task = asyncio.create_task(self._run(turn), name=f"turn {chat_id}")
        return turn

    async def cancel(self, account_id: int, chat_id: str) -> bool:
        """Cooperative, like chat_app: ai_agent stops at its next round and
        the turn ends with whatever had streamed."""
        turn = self.get(account_id, chat_id)
        if turn is None or turn.status != "running" or turn.cancel_requested:
            return False
        turn.cancel_requested = True
        await self._publish(turn, {"type": "cancelling"})
        if turn.asking:
            try:
                await self._gateway.cancel(turn.agent.url, turn.caller, turn.request_id)
            except AgentCallError as error:
                logger.warning("cancel of turn %s failed: %s", turn.request_id, error)
        return True

    async def discard(self, account_id: int, chat_id: str) -> None:
        """The chat is being deleted: stop its turn and forget the replay.
        The task finds no chat to save into and ends quietly."""
        await self.cancel(account_id, chat_id)
        turn = self._turns.pop((account_id, chat_id), None)
        if turn is not None:
            async with turn.condition:
                turn.condition.notify_all()

    async def discard_account(self, account_id: int) -> None:
        for (a, c) in list(self._turns):
            if a == account_id:
                await self.discard(a, c)

    async def shutdown(self) -> None:
        tasks = [t.task for t in self._turns.values() if t.task and not t.task.done()]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    # --- watching ------------------------------------------------------------

    async def subscribe(self, account_id: int, chat_id: str, after: int = 0) -> AsyncIterator[dict[str, Any]]:
        """Live events after sequence `after`, ending with the terminal one.
        Starts with a snapshot when older events were already folded away.
        Yields {"type": "ping"} while idle so proxies keep the stream open."""
        turn = self.get(account_id, chat_id)
        if turn is None:
            raise TurnNotFound(chat_id)

        async def events() -> AsyncIterator[dict[str, Any]]:
            cursor = after
            oldest = turn.events[0]["sequence"] if turn.events else turn.sequence + 1
            if turn.status == "running" and (cursor == 0 or cursor < oldest - 1):
                snapshot = turn.snapshot()
                cursor = snapshot["sequence"]
                yield snapshot
            while True:
                async with turn.condition:
                    batch = [e for e in turn.events if e["sequence"] > cursor]
                    finished = turn.status != "running"
                    if not batch and not finished:
                        if self._turns.get((account_id, chat_id)) is not turn:
                            return  # discarded
                        try:
                            await asyncio.wait_for(turn.condition.wait(), HEARTBEAT_SECONDS)
                        except TimeoutError:
                            yield {"type": "ping"}
                        continue
                for event in batch:
                    cursor = event["sequence"]
                    yield event
                if finished:
                    return

        return events()

    async def _publish(self, turn: Turn, event: dict[str, Any], status: str | None = None) -> None:
        """Adds one event; a terminal one also sets the final status, under
        the same lock, so no watcher sees "finished" without the event."""
        async with turn.condition:
            turn.sequence = next(self._sequences)
            kind = event.get("type")
            if kind == "token":
                turn.text += str(event.get("text") or "")
            elif kind == "token_reset":
                turn.text = ""
            elif kind == "step_start":
                turn.activity = str(event.get("label") or event.get("tool") or "")
            elif kind == "step_end" or kind == "summarized":
                turn.activity = ""
            elif kind == "summarizing":
                turn.activity = "summarizing earlier messages"
            turn.events.append({**event, "sequence": turn.sequence})
            if kind in TERMINAL:
                turn.status = status or "failed"
                turn.finished_at = monotonic()
            turn.condition.notify_all()

    def _expire_finished(self) -> None:
        now = monotonic()
        for key, turn in list(self._turns.items()):
            if turn.finished_at is not None and now - turn.finished_at > self._retention:
                del self._turns[key]

    # --- the work --------------------------------------------------------------

    async def _run(self, turn: Turn) -> None:
        try:
            await self._answer(turn)
        except asyncio.CancelledError:
            # ember_api is stopping: keep what streamed, marked as such.
            await asyncio.shield(self._finish(turn, _interrupted(turn.text), status="failed", error=None))
            raise
        except Exception as error:  # noqa: BLE001 - a bug here must still end the turn for its watchers
            logger.exception("turn %s crashed", turn.request_id)
            await self._logs.error(
                turn.account_id, "chat.answer", f"{type(error).__name__}: {error}", traceback.format_exc()
            )
            await self._finish(
                turn, "error: the answer could not be completed", status="failed", error="The answer could not be completed."
            )

    async def _answer(self, turn: Turn) -> None:
        async with self._database.sessions() as session:
            try:
                messages = decode_messages(await ChatService(session, turn.account_id).get(turn.chat_id))
            except ChatNotFound:
                return
        if not messages or messages[-1].get("role") != "user":
            await self._finish(turn, "error: nothing to answer", status="failed", error="Nothing to answer.")
            return
        question = str(messages[-1]["content"])
        turn.question = question
        earlier = messages[:-1]

        if summarization.needs_summary(
            earlier, self._usage.max_context_tokens_per_chat, self._usage.auto_summarize_ratio
        ):
            earlier = await self._auto_summarize(turn, earlier, messages[-1])

        if turn.cancel_requested:
            await self._finish(turn, "⏹️ Cancelled.", status="cancelled", error=None, cancelled=True)
            return

        async def on_event(event: dict[str, Any]) -> None:
            if event.get("type") in ("token", "token_reset", "step_start", "step_progress", "step_end", "usage"):
                await self._publish(turn, event)

        turn.asking = True
        try:
            result = await self._gateway.ask(
                turn.agent.url,
                turn.caller,
                question=question,
                history=summarization.history_for_agent(earlier),
                request_id=turn.request_id,
                caveman=turn.options.caveman,
                enabled_extensions=list(turn.options.enabled_extensions),
                on_event=on_event,
            )
        except AgentCallError as error:
            await self._logs.error(turn.account_id, "chat.answer", f"{turn.agent.id}: {error}")
            await self._finish(turn, f"error: {error}", status="failed", error=str(error))
            return
        finally:
            turn.asking = False

        cancelled = bool(result.get("cancelled"))
        response = str(result.get("response") or "")
        content = f"{turn.text}\n\n{response}" if cancelled and turn.text else response
        message = {
            "role": "assistant",
            "content": content,
            **{k: result[k] for k in ("model", "total_tokens", "context_tokens", "context_window") if result.get(k) is not None},
        }
        await self._record_usage(turn, "chat", result)
        await self._finish(turn, message, status="cancelled" if cancelled else "completed", error=None, cancelled=cancelled)

    async def _auto_summarize(
        self, turn: Turn, earlier: list[dict[str, Any]], question: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Summarizes before sending, when the chat's context is nearly full.
        A failure never blocks the turn: the history is then sent as is."""
        await self._publish(turn, {"type": "summarizing"})
        try:
            outcome = await summarization.summarize(self._gateway, turn.agent.url, turn.caller, earlier)
        except summarization.SummarizeError as error:
            logger.info("auto-summarize of chat %s skipped: %s", turn.chat_id, error)
            return earlier
        if outcome is None:
            return earlier
        for result in outcome.results:
            await self._record_usage(turn, "summary", result)
        async with self._database.sessions() as session:
            try:
                await ChatService(session, turn.account_id).replace_messages(
                    turn.chat_id, [*outcome.messages, question]
                )
            except ChatNotFound:
                return earlier
        await self._publish(turn, {"type": "summarized"})
        return outcome.messages

    async def _record_usage(self, turn: Turn, kind: str, result: dict[str, Any]) -> None:
        try:
            async with self._database.sessions() as session:
                await UsageService(session, self._usage).record(turn.account_id, turn.request_id, kind, turn.chat_id, result)
        except Exception:  # noqa: BLE001 - accounting must not lose the user's answer
            logger.exception("recording usage of turn %s failed", turn.request_id)

    async def _finish(
        self,
        turn: Turn,
        answer: str | dict[str, Any],
        *,
        status: str,
        error: str | None,
        cancelled: bool = False,
    ) -> None:
        """Appends the answer to the chat as it is now (it may have been
        renamed, or deleted, meanwhile), then ends the turn for watchers."""
        message = answer if isinstance(answer, dict) else {"role": "assistant", "content": answer}
        try:
            async with self._database.sessions() as session:
                chats = ChatService(session, turn.account_id)
                current = decode_messages(await chats.get(turn.chat_id))
                await chats.replace_messages(turn.chat_id, [*current, message], agent_id=turn.agent.id)
        except ChatNotFound:
            pass  # deleted while the answer was running
        except Exception:  # noqa: BLE001
            logger.exception("saving the answer of turn %s failed", turn.request_id)
        terminal: dict[str, Any] = (
            {"type": "error", "message": error}
            if error is not None
            else {"type": "final", "message": message, "cancelled": cancelled}
        )
        await self._publish(turn, terminal, status)
        if turn.question:
            await self._trace(turn, message, status)

    async def _trace(self, turn: Turn, message: dict[str, Any], status: str) -> None:
        """One chat-turn log line per answered question (port of chat_app's
        chat traces): the question, who answered and how long it took."""
        elapsed = round(monotonic() - turn.started_at, 1)
        question = " ".join(turn.question.split())
        question = question if len(question) <= 80 else question[:79] + "…"
        details = {
            "chat_id": turn.chat_id,
            "agent": turn.agent.id,
            "status": status,
            "model": message.get("model"),
            "total_tokens": message.get("total_tokens"),
            "enabled_extensions": list(turn.options.enabled_extensions),
            "response": str(message.get("content", ""))[:TRACE_RESPONSE_MAX],
        }
        await self._logs.chat_trace(
            turn.account_id,
            f"{question} → {turn.agent.id}/{message.get('model') or status}, {elapsed}s",
            json.dumps(details, ensure_ascii=False, indent=2),
        )


def _interrupted(text: str) -> str:
    note = "⚠️ Interrupted: ember_api stopped before the answer finished."
    return f"{text}\n\n{note}" if text else note
