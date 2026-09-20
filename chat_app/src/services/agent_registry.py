"""Configured ai_agent instances chat_app can send chat questions to -
read once at import time from configs/config_agents.json. The Chat
page's provider dropdown now picks one of these (an agent, hard-pinned
to one LLM) rather than an LLM provider directly - see
services/ai_agent_client.py for how a question actually reaches one.

Each ai_agent instance now writes/removes its own entry here on
startup/shutdown (see ai_agent/src/agent_registry.py's register()/
deregister()), so it no longer needs a manual edit - reload() below
picks up such a change without a chat_app restart, via the Chat page's
provider-dropdown refresh button (GET /api/providers?refresh=1).
"""

from __future__ import annotations

import json
from pathlib import Path

_CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "configs" / "config_agents.json"


def _load() -> list[dict[str, str]]:
    if not _CONFIG_PATH.exists():
        return []
    data = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    return data.get("agents", [])


_AGENTS = _load()
_AGENTS_BY_ID = {agent["id"]: agent for agent in _AGENTS}


def reload() -> None:
    """Re-reads config_agents.json - an ai_agent instance started or
    stopped after this process's own import-time load (see
    ai_agent/src/agent_registry.py's register()/deregister()) needs this
    before the dropdown reflects it; see the Chat page's
    /api/providers?refresh=1."""
    global _AGENTS, _AGENTS_BY_ID
    _AGENTS = _load()
    _AGENTS_BY_ID = {agent["id"]: agent for agent in _AGENTS}


def list_agent_ids() -> list[str]:
    return [agent["id"] for agent in _AGENTS]


def get_agent(agent_id: str | None) -> dict[str, str] | None:
    if not agent_id:
        return None
    return _AGENTS_BY_ID.get(agent_id)


def all_agents() -> list[dict[str, str]]:
    return list(_AGENTS)


def resolve_agent(requested_id: str | None) -> dict[str, str] | None:
    """The agent a request should use: the one asked for, if configured;
    otherwise the first configured agent; ``None`` only when nothing is
    configured at all."""
    agent = get_agent(requested_id)
    if agent is not None:
        return agent
    configured = all_agents()
    return configured[0] if configured else None
