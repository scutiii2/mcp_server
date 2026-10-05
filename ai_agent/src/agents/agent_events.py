"""Live "which agent is working" events.

Every event an agent sends up its stream carries agent_id/agent_label
(stamp()). When an orchestrator delegates, delegation.py emits
agent_start/agent_end around the call and re-emits the specialist's own
events - received as MCP progress notifications - into the orchestrator's
stream. The path back up is a ContextVar sink bound by
base_provider.dispatch_with_progress for the duration of one tool step,
the same pattern as tool_progress.py: the delegation runs several layers
down on a worker thread, so threading a callback through every signature
would touch them all.
"""

from __future__ import annotations

from contextvars import ContextVar, Token
from datetime import datetime, timezone
from typing import Any, Callable

Sink = Callable[[dict[str, Any]], None]

_bound: ContextVar[tuple[Sink, str] | None] = ContextVar("agent_events_sink", default=None)

# Specialist events that make sense in the orchestrator's stream as-is.
# `usage` stays out on purpose: callers read usage events as the turn's
# running total, and a specialist's figure would replace the orchestrator's.
_PASS_THROUGH = {"step_start", "step_progress", "step_end", "agent_start", "agent_end", "agent_token"}


def now_iso() -> str:
    """UTC, millisecond precision, "Z" suffix - the one timestamp format
    for events and usage rows."""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def stamp(event: dict[str, Any], agent_id: str, agent_label: str) -> dict[str, Any]:
    """`event` with this agent's identity, unless it already names one (a
    forwarded event keeps the innermost agent that produced it)."""
    if event.get("agent_id"):
        return event
    return {**event, "agent_id": agent_id, "agent_label": agent_label}


def bind(sink: Sink, step_id: str) -> Token:
    return _bound.set((sink, step_id))


def reset(token: Token) -> None:
    _bound.reset(token)


def emitter() -> Sink | None:
    bound = _bound.get()
    return bound[0] if bound else None


def current_step_id() -> str | None:
    bound = _bound.get()
    return bound[1] if bound else None


def emit(event: dict[str, Any]) -> None:
    """Send `event` up the current step's stream; a no-op when nothing is
    listening (non-streaming callers, tests)."""
    sink = emitter()
    if sink is not None:
        sink(event)


def forwarded(event: dict[str, Any], step_id: str | None) -> dict[str, Any] | None:
    """A specialist's event as the orchestrator's stream should carry it,
    or None to drop it. Its answer text becomes agent_token so it never
    mixes into the orchestrator's own answer."""
    kind = event.get("type")
    if kind in ("token", "token_reset"):
        out = {
            "type": "agent_token",
            "agent_id": event.get("agent_id"),
            "agent_label": event.get("agent_label"),
            "step_id": step_id,
            "text": event.get("text", "") if kind == "token" else "",
        }
        if kind == "token_reset":
            out["reset"] = True
        return out
    if kind in _PASS_THROUGH:
        return event
    return None
