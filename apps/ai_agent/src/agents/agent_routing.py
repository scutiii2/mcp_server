"""Which specialists an orchestrator offers the model this turn.

The roster is re-read from the registry every turn (specialists start and
stop independently).
"""

from __future__ import annotations

import anyio.to_thread

from src.agents import agent_registry, agent_spec
from src.agents.agent_spec import RosterEntry
from src.llm import model_tiers, reasoning_effort


def specialists() -> list[RosterEntry]:
    """Every registered non-orchestrator agent except this one. Blocking
    (re-reads the registry file) - call from a worker thread."""
    agent_registry.reload()
    me = agent_spec.current().id
    return [
        RosterEntry(
            a["id"], a.get("label") or a["id"], a.get("focus") or "",
            model_tiers.from_records(a.get("tiers")), reasoning_effort.from_record(a.get("efforts")),
        )
        for a in agent_registry.all_agents()
        if not a.get("orchestrator") and a["id"] != me
    ]


async def roster_for() -> list[RosterEntry]:
    """This turn's roster: [] unless this agent is an orchestrator."""
    if not agent_spec.current().orchestrator:
        return []
    return await anyio.to_thread.run_sync(specialists)
