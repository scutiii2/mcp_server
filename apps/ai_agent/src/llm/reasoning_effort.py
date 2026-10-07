"""Reasoning effort a delegating orchestrator may request of one agent.

Pure logic over the agent spec - no provider or SDK imports. The scale is
agent_spec.REASONING_EFFORTS (off < low < medium < high). An agent's
llm.max_effort caps what it accepts; a request above the cap is clamped to the
cap, never refused, because the agent enforces its own limit (a stale or
careless caller cannot push it past it).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.agents import agent_spec
from src.agents.agent_spec import REASONING_EFFORTS


@dataclass(frozen=True)
class EffortResolution:
    """The effort a turn runs at. `effort` is None when the agent's own
    default applies; `note` says why a request was changed ("" when it was not)."""

    effort: str | None
    note: str = ""


def allowed(max_effort: str | None) -> tuple[str, ...]:
    """The efforts up to and including `max_effort`, weakest first (all of
    them when there is no cap)."""
    if max_effort is None:
        return REASONING_EFFORTS
    return REASONING_EFFORTS[: REASONING_EFFORTS.index(max_effort) + 1]


def resolve(requested: str | None, max_effort: str | None, agent_id: str) -> EffortResolution:
    """Turn a requested effort into the one to run at. No request: the
    agent's default, silently. An unknown name: the default with a note. A
    request above the cap: the cap, with a note."""
    if not requested:
        return EffortResolution(None)
    if requested not in REASONING_EFFORTS:
        return EffortResolution(None, f"unknown reasoning_effort {requested!r}; ran on {agent_id}'s default effort")
    if requested in allowed(max_effort):
        return EffortResolution(requested)
    return EffortResolution(max_effort, f"{requested} is above {agent_id}'s reasoning_effort limit; ran on {max_effort}")


def own_efforts() -> tuple[str, ...]:
    """The efforts this process's agent accepts from a delegator. A Laya
    triage agent has no reasoning control."""
    spec = agent_spec.current()
    if spec.llm.provider == "laya":
        return ()
    return allowed(spec.llm.max_effort)


def from_record(record: Any) -> tuple[str, ...]:
    """Read a registry record's `efforts` back; anything malformed is
    skipped, since the registry file is written by other processes."""
    if not isinstance(record, list):
        return ()
    return tuple(level for level in REASONING_EFFORTS if level in record)
