"""delegate_to_agent - lets one ai_agent instance hand a focused
sub-question to another configured specialist instance mid-loop.

Not every "subagent" needs a new ai_agent process: delegating to a
different already-running instance goes through this one generic tool.
An agent never lists itself in its roster; orchestrators delegate to
specialists only (see agent_routing.specialists()).
A genuinely distinct specialized subagent (its own system prompt/tool
scope/model) is still a new ai_agent instance - this module is what lets
any orchestrator reach one once it exists.

Isolated from both provider files so neither anthropic_provider.py nor
openai_provider.py duplicates the tool-schema/dispatch logic - each just
calls tool_description()/tool_parameters()/call() from here.

Cancellation is NOT propagated into a delegated call: chat_app's Stop
button only knows the top-level agent's request_id/URL, with no
visibility into a nested delegate call. A delegated call always passes
request_id=None (cancellation.py already treats a falsy id as
"uncancellable") - a documented limitation, not a bug.
"""

from __future__ import annotations

import asyncio
import json
from contextvars import ContextVar, Token
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from src.agents import agent_events, agent_registry, agent_routing, agent_spec

from src.core import approvals, internal_auth, tool_filter
from src.agents.agent_spec import REASONING_EFFORTS, TIERS, RosterEntry

TOOL_NAME = "delegate_to_agent"
AUTO_AGENT_ID = "auto"

# Token usage of every agent this turn delegated to (including their own
# nested delegations). agent_config.run_chat binds a fresh list per turn;
# call() runs on a worker thread that inherits the context, so it appends
# to that same list. None outside a bound turn (usage is then just dropped).
_usage_sink: ContextVar[list[dict[str, Any]] | None] = ContextVar("delegation_usage_sink", default=None)


def bind_usage() -> tuple[list[dict[str, Any]], Token]:
    usage: list[dict[str, Any]] = []
    return usage, _usage_sink.set(usage)


def reset_usage(token: Token) -> None:
    _usage_sink.reset(token)

# Each hop is itself a full up-to-6-round ask() call, so this bounds a
# worst case that's real but not tiny. 2 hops makes a genuine multi-step
# handoff possible (A -> B -> C, or A -> B -> A) without allowing
# unbounded fan-out or a delegation cycle running forever.
_MAX_DELEGATION_DEPTH = 2

def _offers_choice(roster: list[RosterEntry]) -> bool:
    return any(len(r.tiers) > 1 for r in roster)


def _offers_effort(roster: list[RosterEntry]) -> bool:
    return any(len(r.efforts) > 1 for r in roster)


def tool_parameters(roster: list[RosterEntry], allow_auto: bool) -> dict[str, Any]:
    """The delegate tool's input schema: agent_id limited to this turn's
    roster (plus "auto" when Laya routing may choose), and model_tier when at
    least one specialist offers a choice of model strength."""
    ids = [r.id for r in roster] + ([AUTO_AGENT_ID] if allow_auto else [])
    properties: dict[str, Any] = {
        "agent_id": {"type": "string", "enum": ids, "description": "Which specialist to delegate to."},
        "question": {"type": "string", "description": "The focused sub-question to ask it."},
    }
    if _offers_choice(roster):
        properties["model_tier"] = {
            "type": "string",
            "enum": list(TIERS),
            "description": "Strength of the model the specialist runs on. Omit for its default.",
        }
    if _offers_effort(roster):
        properties["reasoning_effort"] = {
            "type": "string",
            "enum": list(REASONING_EFFORTS),
            "description": (
                "How hard the specialist reasons: off = none, low = a quick check, medium = normal analysis, "
                "high = hard multi-step problems. Omit for its default."
            ),
        }
    return {"type": "object", "properties": properties, "required": ["agent_id", "question"]}


def _roster_line(entry: RosterEntry) -> str:
    line = f"{entry.id} ({entry.label}): {entry.focus or 'no focus given'}"
    if len(entry.tiers) > 1:
        line += " [model_tier: " + ", ".join(f"{t.tier} = {t.use_for}" for t in entry.tiers) + "]"
    if 1 < len(entry.efforts) < len(REASONING_EFFORTS):
        line += f" [reasoning_effort: up to {entry.efforts[-1]}]"
    return line


def tool_description(roster: list[RosterEntry], allow_auto: bool) -> str:
    listing = "; ".join(_roster_line(r) for r in roster)
    auto = ' Use agent_id "auto" to let routing pick the best specialist for the question.' if allow_auto else ""
    choice = (
        " Pick the lightest model_tier whose description fits the task; omit it when unsure."
        if _offers_choice(roster) else ""
    )
    effort = (
        " Pick the lowest reasoning_effort that fits the task; omit it when unsure."
        if _offers_effort(roster) else ""
    )
    return (
        f"Hand a focused sub-question to a specialist agent and get its answer back. Specialists: {listing}.{auto}{choice}{effort} "
        "Sequential: each call adds latency, so delegate only what a specialist does better."
    )


async def _call_tool(url: str, name: str, arguments: dict[str, Any], on_progress: Any = None) -> dict[str, Any]:
    # Same shape as chat_app/src/services/ai_agent_client.py's _call_tool,
    # including its fix: raise only AFTER both async with blocks exit,
    # never inside them - an exception raised while either is still open
    # gets wrapped in a BaseExceptionGroup by anyio on unwind, which the
    # caller's plain `except Exception` would then fail to stringify
    # usefully.
    # The shared token (peers require it) and the asking user, so the
    # delegate's own mcp_server calls carry them on too.
    async with streamablehttp_client(url, headers=internal_auth.outbound_headers() or None) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(name, arguments, progress_callback=on_progress)

    if result.isError:
        parts = [getattr(block, "text", str(block)) for block in result.content]
        raise RuntimeError("\n".join(parts) if parts else f"{name} failed")
    return result.structuredContent or {}


def _progress_forwarder(sink: agent_events.Sink | None, step_id: str | None) -> Any:
    """An MCP progress callback that re-emits the specialist's live events
    (JSON in each progress message - see server.ask) into this agent's
    stream. The sink is captured here, not looked up per message: the
    callback runs on the MCP client's own task inside asyncio.run below."""
    if sink is None:
        return None

    async def on_progress(progress: float, total: float | None, message: str | None) -> None:
        if not message:
            return
        try:
            event = json.loads(message)
        except ValueError:
            return
        if isinstance(event, dict):
            out = agent_events.forwarded(event, step_id)
            if out is not None:
                sink(out)

    return on_progress


def call(
    agent_id: str, question: str, depth: int, model_tier: str | None = None, reasoning_effort: str | None = None,
) -> str:
    """Blocking. Must run in a worker thread (the providers dispatch it via
    anyio.to_thread.run_sync): asyncio.run() below fails inside a running
    event loop, and delegating to this same instance needs its event loop
    free to serve the nested ask() rather than blocked waiting on it."""
    if depth >= _MAX_DELEGATION_DEPTH:
        raise ValueError(f"max delegation depth ({_MAX_DELEGATION_DEPTH}) reached")

    prefix = ""
    if agent_id == AUTO_AGENT_ID:
        chosen = agent_routing.resolve_auto(question)
        agent_id = chosen.id
        prefix = f"Delegated to {chosen.id} ({chosen.label}).\n\n"

    # Specialists start and stop on their own - read the current registry.
    agent_registry.reload()
    agent = agent_registry.get_agent(agent_id)
    if agent is None:
        configured = ", ".join(agent_registry.list_agent_ids()) or "(none configured)"
        raise ValueError(f"unknown agent_id {agent_id!r} - configured agents: {configured}")

    # A delegate has no way to ask the user, so when this turn asks before
    # tools run, the delegate's tools that would need asking are refused.
    approval_mode = "off" if approvals.current().mode == "off" else "deny"
    me = agent_spec.current().id
    label = agent.get("label") or agent_id
    step_id = agent_events.current_step_id()
    sink = agent_events.emitter()
    agent_events.emit({
        "type": "agent_start", "agent_id": agent_id, "agent_label": label, "delegated_by": me,
        "question": question, "step_id": step_id, "at": agent_events.now_iso(),
    })
    ok = False
    try:
        arguments: dict[str, Any] = {
            "question": question,
            "history": [],
            "enabled_extensions": [],
            "request_id": None,
            "depth": depth + 1,
            "approval_mode": approval_mode,
            "delegated_by": me,
            # What the user switched off holds for the specialist too.
            "disabled_tools": sorted(tool_filter.blocked()),
        }
        if model_tier:
            arguments["model_tier"] = model_tier
        if reasoning_effort:
            arguments["reasoning_effort"] = reasoning_effort
        if "*" in tool_filter.blocked():
            status = asyncio.run(_call_tool(agent["url"], "status", {}))
            if not status.get("tool_filter_all"):
                raise PermissionError("The delegated agent cannot block all tools; update and restart it")
        result = asyncio.run(
            _call_tool(
                agent["url"],
                "ask",
                arguments,
                on_progress=_progress_forwarder(sink, step_id),
            )
        )
        ok = True
    finally:
        agent_events.emit({
            "type": "agent_end", "agent_id": agent_id, "agent_label": label,
            "ok": ok, "step_id": step_id, "at": agent_events.now_iso(),
        })
    usage_sink = _usage_sink.get()
    if usage_sink is not None:
        # The delegate's own entries already include anything it delegated on.
        usage_sink.extend(result.get("agent_usage") or [])
    notes = [n for n in (result.get("model_note"), result.get("effort_note")) if n]
    note_prefix = f"[{'; '.join(notes)}]\n\n" if notes else ""
    return prefix + note_prefix + result.get("response", "")


def dispatch(arguments: dict[str, Any], depth: int) -> str:
    """Run a delegate_to_agent tool call from its model-supplied arguments.
    Shared by both providers so neither re-reads the argument names."""
    extra = {
        key: value
        for key in ("model_tier", "reasoning_effort")
        if isinstance(value := arguments.get(key), str) and value
    }
    return call(arguments["agent_id"], arguments["question"], depth, **extra)
