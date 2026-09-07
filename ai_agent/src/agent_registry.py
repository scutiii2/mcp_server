"""Sibling ai_agent instances this instance can delegate a sub-question to
(see delegation.py) - read once at import time from
configs/config_agents.json. Identical in shape to chat_app/src/services/
agent_registry.py; copied rather than shared cross-project, same
convention as everything else in this project.

Deliberately includes this instance's own entry (self-delegation is
allowed - see delegation.py's module docstring for why).
"""

from __future__ import annotations

import json
from pathlib import Path

_CONFIG_PATH = Path(__file__).resolve().parent.parent / "configs" / "config_agents.json"


def _load() -> list[dict[str, str]]:
    if not _CONFIG_PATH.exists():
        return []
    data = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    return data.get("agents", [])


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
