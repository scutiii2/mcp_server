"""Resolves this ai_agent instance's active persona role, once, at import
time - fails loudly if AI_AGENT_ROLE names an id not present in
configs/config_ai_agent_roles.json, rather than discovering that on the
first real request.

SYSTEM_PROMPT (imported by anthropic_provider.py/openai_provider.py in
place of the old base_provider.SYSTEM_PROMPT constant) is built from, in
order: an identity line derived from the config's app_name/app_description
(so every role can answer "what's your name"), the resolved role's persona
text, then the config's shared tool_use_instructions. Editing
tool_use_instructions once updates every role. The generic role's persona
is empty, so its SYSTEM_PROMPT is just identity + tool_use_instructions.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from src.seed import seed_from_example

_CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "configs" / "config_ai_agent_roles.json"

_config: dict[str, Any] | None = None


class AgentRoleError(Exception):
    """Raised at import time for an AI_AGENT_ROLE naming an id that isn't
    in configs/config_ai_agent_roles.json's "roles" map, for the config
    file itself being missing, or for the config being malformed (missing
    a required key)."""


def _load() -> dict[str, Any]:
    global _config
    if _config is None:
        seed_from_example(_CONFIG_PATH)
        try:
            _config = json.loads(_CONFIG_PATH.read_text())
        except FileNotFoundError as exc:
            raise AgentRoleError(
                f"{_CONFIG_PATH} not found - copy {_CONFIG_PATH}.example to it"
            ) from exc
    return _config


def _resolve() -> tuple[str, dict[str, Any]]:
    config = _load()
    try:
        roles = config["roles"]
        role_id = os.getenv("AI_AGENT_ROLE") or config["default_role"]
    except KeyError as exc:
        raise AgentRoleError(f"{_CONFIG_PATH} is missing required key {exc}") from exc
    role = roles.get(role_id)
    if role is None:
        raise AgentRoleError(
            f"Unknown AI_AGENT_ROLE {role_id!r} - must be one of: {', '.join(sorted(roles))}"
        )
    return role_id, role


def _compose_system_prompt(config: dict[str, Any], role: dict[str, Any]) -> str:
    try:
        tool_use_instructions = config["tool_use_instructions"]
    except KeyError as exc:
        raise AgentRoleError(f"{_CONFIG_PATH} is missing required key {exc}") from exc
    app_name = config.get("app_name") or ""
    app_description = config.get("app_description") or ""
    identity = ""
    if app_name:
        identity = f"Your name is {app_name}, an AI Assistant."
        if app_description:
            identity += f" {app_description}"
        identity += " When asked who you are or what your name is, answer with your name and this role."
    persona = role.get("persona") or ""
    parts = [p for p in (identity, persona, tool_use_instructions) if p]
    return "\n\n".join(parts)


ROLE_ID, _ROLE = _resolve()
SYSTEM_PROMPT = _compose_system_prompt(_load(), _ROLE)
