"""Configured ai_agent instances chat_app can send chat questions to -
read once at import time from src/configs/config_agents.json, the same
way services/llm/app_config.py read config_chat.json before this
project's Chat page migrated onto ai_agent.
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


def get_agent(agent_id: str) -> dict[str, str] | None:
    return _AGENTS_BY_ID.get(agent_id)


def all_agents() -> list[dict[str, str]]:
    return list(_AGENTS)
