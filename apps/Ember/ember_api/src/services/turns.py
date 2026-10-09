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
from src.services import question_answers, summarization
from src.services.agent_directory import AgentEntry
from src.services.agent_gateway import AgentCallError, AgentGateway, Caller
from src.services.chat_service import ChatNotFound, ChatService, decode_messages, message_time
from src.services.log_service import LogWriter
from src.services.usage_service import UsageService, usage_rows

logger = logging.getLogger(__name__)

TERMINAL = ("final", "error")
# Events a subscriber can't rebuild from the snapshot are kept; tokens are
# folded into Turn.text instead, so this bounds memory, not answer length.
EVENT_BUFFER = 256
HEARTBEAT_SECONDS = 15.0
# How much of an answer the chat-turn log keeps.
TRACE_RESPONSE_MAX = 4000
# How much of each tool step's result is saved on the answer (chat_app's
# _STEP_RESULT_MAX), and how many steps at most.
STEP_RESULT_MAX = 4000
MAX_STEPS = 50
# StepIn.agent_label's limit.
AGENT_LABEL_MAX = 120
# Most agents one answer's usage is split into (its own plus delegated ones).
MAX_AGENT_USAGE_ROWS = 20
# Caps on what a delegated agent's live events may carry to a browser.
AGENT_QUESTION_MAX = 500
AGENT_TEXT_MAX = 4000


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
    # Ask the user before each tool runs, except the tools they already
    # allowed for this chat.
    ask_before_tools: bool = False
    allowed_tools: tuple[str, ...] = ()
    # Tools the account switched off for its own chats; the agent neither offers nor runs them.
    disabled_tools: tuple[str, ...] = ()
    # The browser can show the agent's clickable questions and send answers back.
    can_ask: bool = False
    # The account's enabled private extensions as ai_agent wants them ({id, label, url, headers});
    # headers are secrets, so this never shows in repr(). Loaded server-side, never from the browser.
    private_extensions: tuple[dict[str, Any], ...] = field(default=(), repr=False)
    # Enabled ones left out because their headers cannot be read: {id, label, error}.
    private_skipped: tuple[dict[str, str], ...] = ()


def _iso(value: Any) -> str | None:
    """A naive-UTC datetime as the ISO string with "Z" ai_agent sent it as."""
    return value.isoformat(timespec="milliseconds") + "Z" if hasattr(value, "isoformat") else None


def _agent_usage(row: dict[str, Any]) -> dict[str, Any]:
    """One saved `agent_usage` entry from a usage row: who, which model, where
    it ran and when, and the token counts that are known."""
    entry = {
        "agent": row["agent"] or "unknown",
        "agent_label": row.get("agent_label"),
        "provider_id": row.get("provider_id"),
        "gateway": row.get("gateway"),
        "model": row["model"],
        "input_tokens": row["input_tokens"],
        "output_tokens": row["output_tokens"],
        "total_tokens": row["total_tokens"],
        "started_at": _iso(row.get("started_at")),
        "finished_at": _iso(row.get("finished_at")),
    }
    return {key: value for key, value in entry.items() if value is not None}


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
    # Tool steps so far: {id, tool, label, arguments, ok, result}; saved on the
    # answer so a reload can still show "Ran N tools".
    steps: list[dict[str, Any]] = field(default_factory=list)
    # (agent id, step id) -> index in `steps`: a specialist's step ids can
    # equal the orchestrator's own.
    step_index: dict[tuple[str, str], int] = field(default_factory=dict)
    # Agents working right now, outermost first: {agent_id, label, since, step_id}.
    active_agents: list[dict[str, str]] = field(default_factory=list)
    # Tool runs waiting for the user's answer, by step id: {id, tool, label, arguments}.
    pending_approvals: dict[str, dict[str, Any]] = field(default_factory=dict)
    # Questions waiting for the user's answer, by step id: {id, questions}.
    pending_questions: dict[str, dict[str, Any]] = field(default_factory=dict)
    plans: dict[str, dict[str, Any]] = field(default_factory=dict)
    sequence: int = 0
    events: deque = field(default_factory=lambda: deque(maxlen=EVENT_BUFFER))
    condition: asyncio.Condition = field(default_factory=asyncio.Condition)
    cancel_requested: bool = False
    asking: bool = False
    task: asyncio.Task | None = None
    finished_at: float | None = None

    def snapshot(self) -> dict[str, Any]:
        return {
            "type": "snapshot",
            "text": self.text,
            "activity": self.activity,
            "steps": [dict(s) for s in self.steps],
            "approvals": [dict(a) for a in self.pending_approvals.values()],
            "questions": [dict(q) for q in self.pending_questions.values()],
            "plans": [dict(p) for p in self.plans.values()],
            "active_agents": [dict(a) for a in self.active_agents],
            "sequence": self.sequence,
        }

    def record_approval(self, event: dict[str, Any]) -> None:
        """Remembers a tool run that waits for the user, so a browser that
        joins late (or reloads) still gets its question."""
        step_id = str(event.get("id") or "")
        if not step_id:
            return
        self.pending_approvals[step_id] = {
            "id": step_id,
            "tool": str(event.get("tool") or ""),
            "label": str(event.get("label") or ""),
            "arguments": event.get("arguments") if isinstance(event.get("arguments"), dict) else {},
        }

    def record_question(self, event: dict[str, Any]) -> None:
        """Remembers questions that wait for the user, so a browser that joins
        late (or reloads) still gets them."""
        step_id = str(event.get("id") or "")
        if not step_id:
            return
        self.pending_questions[step_id] = {"id": step_id, "questions": event.get("questions") or []}

    def record_plan(self, event: dict[str, Any]) -> None:
        """Keep each agent's latest checklist for a reconnect, only this turn."""
        agent_id = str(event.get("agent_id") or "")
        if not event.get("items"):
            self.plans.pop(agent_id, None)
        elif agent_id in self.plans or len(self.plans) < MAX_AGENT_USAGE_ROWS:
            self.plans[agent_id] = {
                "agent_id": agent_id, "agent_label": str(event.get("agent_label") or "")[:AGENT_LABEL_MAX],
                "items": event["items"],
            }

    def record_agent(self, event: dict[str, Any]) -> None:
        """Folds agent_start / agent_end into the stack of working agents."""
        agent_id = str(event.get("agent_id") or "")
        step_id = str(event.get("step_id") or "")
        if event.get("type") == "agent_start":
            self.active_agents.append(
                {
                    "agent_id": agent_id,
                    "label": str(event.get("agent_label") or ""),
                    "since": str(event.get("at") or ""),
                    "step_id": step_id,
                }
            )
        else:
            self.active_agents = [
                a for a in self.active_agents if not (a["step_id"] == step_id and a["agent_id"] == agent_id)
            ]

    def record_step(self, event: dict[str, Any]) -> None:
        """Folds a step_start / step_end event into `steps`."""
        step_id = str(event.get("id") or "")
        key = (str(event.get("agent_id") or ""), step_id)
        if event.get("type") == "step_start":
            if len(self.steps) >= MAX_STEPS:
                return
            self.step_index[key] = len(self.steps)
            step = {
                "id": step_id,
                "tool": str(event.get("tool") or ""),
                "label": str(event.get("label") or ""),
                "arguments": event.get("arguments") if isinstance(event.get("arguments"), dict) else {},
                "ok": None,
                "result": "",
            }
            if event.get("agent_id"):
                step["agent_id"] = str(event["agent_id"])
                step["agent_label"] = str(event.get("agent_label") or "")[:AGENT_LABEL_MAX]
            self.steps.append(step)
        elif key in self.step_index:
            step = self.steps[self.step_index[key]]
            step["ok"] = bool(event.get("ok"))
            step["result"] = str(event.get("result") or "")[:STEP_RESULT_MAX]


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

    def pending_approval(self, account_id: int, chat_id: str, step_id: str) -> dict[str, Any] | None:
        """The tool run of this step that is waiting for an answer, if any."""
        turn = self.get(account_id, chat_id)
        if turn is None or turn.status != "running":
            return None
        return turn.pending_approvals.get(step_id)

    async def decide(self, account_id: int, chat_id: str, step_id: str, decision: str) -> bool:
        """Answers a waiting tool approval of this account's running turn.
        False when that step is not waiting (unknown, already answered, or the
        turn moved on). The agent then reports the outcome as an
        `approval_resolved` event, which clears it for every watcher."""
        turn = self.get(account_id, chat_id)
        if turn is None or turn.status != "running" or step_id not in turn.pending_approvals:
            return False
        return await self._gateway.decide(turn.agent.url, turn.caller, turn.request_id, step_id, decision)

    def pending_question(self, account_id: int, chat_id: str, step_id: str) -> dict[str, Any] | None:
        """The question set of this step that is waiting for an answer, if any."""
        turn = self.get(account_id, chat_id)
        if turn is None or turn.status != "running":
            return None
        return turn.pending_questions.get(step_id)

    async def answer(
        self, account_id: int, chat_id: str, step_id: str, answers: list[dict[str, Any]], skipped: bool
    ) -> bool:
        """Sends the user's answers (or a skip) for a waiting question of this
        account's running turn. False when it is not waiting (unknown, already
        answered, or the turn moved on). The agent then reports the outcome as a
        `question_resolved` event, which clears it for every watcher."""
        turn = self.get(account_id, chat_id)
        if turn is None or turn.status != "running" or step_id not in turn.pending_questions:
            return False
        return await self._gateway.answer_question(turn.agent.url, turn.caller, turn.request_id, step_id, answers, skipped)

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
                turn.record_step(event)
            elif kind == "step_end":
                turn.activity = ""
                turn.record_step(event)
                turn.pending_approvals.pop(str(event.get("id") or ""), None)
                turn.pending_questions.pop(str(event.get("id") or ""), None)
            elif kind in ("agent_start", "agent_end"):
                turn.record_agent(event)
            elif kind == "plan_update":
                turn.record_plan(event)
            elif kind == "approval_request":
                turn.activity = "waiting for your approval"
                turn.record_approval(event)
            elif kind == "approval_resolved":
                turn.activity = ""
                turn.pending_approvals.pop(str(event.get("id") or ""), None)
            elif kind == "question_request":
                turn.activity = "waiting for your answer"
                turn.record_question(event)
            elif kind == "question_resolved":
                turn.activity = ""
                turn.pending_questions.pop(str(event.get("id") or ""), None)
            elif kind == "summarized":
                turn.activity = ""
            elif kind == "summarizing":
                turn.activity = "summarizing earlier messages"
            turn.events.append({**event, "sequence": turn.sequence})
            if kind in TERMINAL:
                turn.status = status or "failed"
                turn.finished_at = monotonic()
                turn.pending_approvals.clear()
                turn.pending_questions.clear()
                turn.active_agents.clear()
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
            if event.get("type") in (
                "token", "token_reset", "step_start", "step_progress", "step_end", "usage",
                "approval_request", "approval_resolved", "question_request", "question_resolved",
                "agent_start", "agent_end", "agent_token", "plan_update",
            ):
                await self._publish(turn, _clamped(event))

        if turn.options.private_skipped:
            await self._publish(turn, {"type": "notice", "notices": [dict(n) for n in turn.options.private_skipped]})
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
                approval_mode="ask" if turn.options.ask_before_tools else "off",
                allowed_tools=list(turn.options.allowed_tools),
                disabled_tools=list(turn.options.disabled_tools),
                ask_user=turn.options.can_ask,
                private_extensions=list(turn.options.private_extensions) or None,
            )
        except AgentCallError as error:
            await self._logs.error(turn.account_id, "chat.answer", f"{turn.agent.id}: {error}")
            await self._finish(turn, f"error: {error}", status="failed", error=str(error))
            return
        finally:
            turn.asking = False

        errors = result.get("private_extension_errors")
        if isinstance(errors, list) and errors:
            await self._publish(
                turn,
                {
                    "type": "notice",
                    "notices": [
                        {k: str(n.get(k) or "")[:300] for k in ("id", "label", "error")}
                        for n in errors[:20]
                        if isinstance(n, dict)
                    ],
                },
            )
        cancelled = bool(result.get("cancelled"))
        response = str(result.get("response") or "")
        content = f"{turn.text}\n\n{response}" if cancelled and turn.text else response
        message = {
            "role": "assistant",
            "content": content,
            # Which of ember's agents answered (the chat's own agent can change later).
            "agent": turn.agent.id,
            **{
                k: result[k]
                for k in ("model", "total_tokens", "input_tokens", "output_tokens", "context_tokens", "context_window")
                if result.get(k) is not None
            },
            # The whole turn (auto-summary and tool calls included), as in the chat-turn log line.
            "duration_s": round(monotonic() - turn.started_at, 1),
        }
        rows = usage_rows(result)
        # Several agents ran (the answer's agent plus delegated ones): keep who used
        # what. One agent only repeats the answer's own totals.
        if len(rows) > 1:
            message["agent_usage"] = [_agent_usage(row) for row in rows[:MAX_AGENT_USAGE_ROWS]]
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
        message = {**message, "at": message_time()}
        if turn.steps:
            # The step id only matters to a live viewer (snapshot); it is not saved.
            message = {**message, "steps": [{k: v for k, v in s.items() if k != "id"} for s in turn.steps]}
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


def _clamped(event: dict[str, Any]) -> dict[str, Any]:
    """A delegated agent's question and streamed text are shown to browsers: cap them."""
    kind = event.get("type")
    if kind == "agent_start" and isinstance(event.get("question"), str):
        return {**event, "question": event["question"][:AGENT_QUESTION_MAX]}
    if kind == "agent_token" and isinstance(event.get("text"), str):
        return {**event, "text": event["text"][:AGENT_TEXT_MAX]}
    if kind == "question_request":
        return {**event, "questions": question_answers.clamp_questions(event.get("questions"))}
    if kind == "plan_update":
        raw = event.get("items")
        items = [
            {"text": item["text"][:300], "status": item["status"]}
            for item in (raw[:50] if isinstance(raw, list) else [])
            if isinstance(item, dict) and isinstance(item.get("text"), str)
            and item.get("status") in ("pending", "in_progress", "done")
        ]
        return {**event, "items": items}
    return event


def _interrupted(text: str) -> str:
    note = "⚠️ Interrupted: ember_api stopped before the answer finished."
    return f"{text}\n\n{note}" if text else note
