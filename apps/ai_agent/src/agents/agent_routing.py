"""Which specialists an orchestrator offers the model this turn, and which
one `delegate_to_agent(agent_id="auto")` goes to.

The roster is re-read from the registry every turn (specialists start and
stop independently). With routing.laya on, Laya ranks specialists by how
well their `focus` matches the question - the same ranker tool
shortlisting uses (tool_selection.py). Laya is optional: any failure falls
back to the full roster, and "auto" then asks the model to pick an id.
"""

from __future__ import annotations

import logging
from typing import Any

import anyio.to_thread

from src.agents import agent_registry, agent_spec
from src.llm import model_tiers

from src.mcp_client import tool_selection
from src.agents.agent_spec import RosterEntry

_log = logging.getLogger(__name__)


def specialists() -> list[RosterEntry]:
    """Every registered non-orchestrator agent except this one. Blocking
    (re-reads the registry file) - call from a worker thread."""
    agent_registry.reload()
    me = agent_spec.current().id
    return [
        RosterEntry(a["id"], a.get("label") or a["id"], a.get("focus") or "", model_tiers.from_records(a.get("tiers")))
        for a in agent_registry.all_agents()
        if not a.get("orchestrator") and a["id"] != me
    ]


async def roster_for(question: str, ranker: Any = None) -> list[RosterEntry]:
    """This turn's roster: [] unless this agent is an orchestrator; with
    Laya on and more than top_k focused specialists, the top_k best matches
    (plus any specialist without a focus, which cannot be ranked)."""
    spec = agent_spec.current()
    if not spec.orchestrator:
        return []
    everyone = await anyio.to_thread.run_sync(specialists)
    rankable = {r.id: r.focus for r in everyone if r.focus}
    if not spec.routing.laya or len(rankable) <= spec.routing.top_k:
        return everyone
    try:
        chosen = await anyio.to_thread.run_sync(
            (ranker or tool_selection.default_ranker()).rank, question, rankable, spec.routing.top_k
        )
    except Exception:
        _log.warning("Laya agent shortlist failed; offering every specialist", exc_info=True)
        return everyone
    keep = set(chosen)
    return [r for r in everyone if r.id in keep or not r.focus]


def resolve_auto(question: str, ranker: Any = None) -> RosterEntry:
    """The specialist whose focus best fits `question`. Blocking - runs on
    delegation's worker thread. Raises ValueError (shown to the model as
    the tool's error) when it cannot choose."""
    spec = agent_spec.current()
    everyone = specialists()
    rankable = {r.id: r.focus for r in everyone if r.focus}
    if not rankable:
        raise ValueError("no specialist has a focus to route by - pick an agent_id explicitly")
    try:
        labels, scores = (ranker or tool_selection.default_ranker()).rank_with_scores(question, rankable, 1)
    except Exception as error:
        raise ValueError(f"automatic routing is unavailable ({error}) - pick an agent_id explicitly") from error
    if not labels:
        raise ValueError("automatic routing found no specialist - pick an agent_id explicitly")
    best = labels[0]
    if spec.routing.min_score is not None and scores is not None and scores[0] < spec.routing.min_score:
        raise ValueError(
            f"no specialist matches well enough (best: {best}, score {scores[0]:.2f}) - "
            "answer yourself or pick an agent_id explicitly"
        )
    return next(r for r in everyone if r.id == best)
