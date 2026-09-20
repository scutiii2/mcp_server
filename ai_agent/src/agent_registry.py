"""Sibling ai_agent instances this instance can delegate a sub-question to
(see delegation.py) - read once at import time from
configs/config_agents.json, then kept live by register()/deregister()
below. Identical in shape to chat_app/src/services/agent_registry.py;
copied rather than shared cross-project, same convention as everything
else in this project.

Deliberately includes this instance's own entry (self-delegation is
allowed - see delegation.py's module docstring for why).
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

_CONFIG_PATH = Path(__file__).resolve().parent.parent / "configs" / "config_agents.json"

# chat_app's own copy of this same file (its provider dropdown - see
# chat_app/src/services/agent_registry.py). register()/deregister() below
# write both rather than one shared file, keeping the "copied, not shared
# cross-project" convention while no longer needing a human to keep the
# two in sync by hand.
_CHAT_APP_CONFIG_PATH = (
    Path(__file__).resolve().parent.parent.parent / "chat_app" / "src" / "configs" / "config_agents.json"
)

# "claude"/"openai" rather than this instance's own AI_AGENT_PROVIDER
# ("anthropic"/"openai" - see agent_config.py) for the id prefix: the
# provider id was renamed from "claude" to "anthropic" without renaming
# the agent id, and delegate_to_agent calls, chat_app's stored
# `provider` field on old chat turns, and cancel's `provider` param all
# already reference "claude-agent" - deriving straight from PROVIDER_ID
# would silently rename that out from under them.
_AGENT_ID_PREFIX = {"anthropic": "claude", "openai": "openai"}

_LOCK_TIMEOUT_SECONDS = 5.0
_LOCK_POLL_SECONDS = 0.05


def agent_id_for(provider_id: str) -> str:
    return f"{_AGENT_ID_PREFIX.get(provider_id, provider_id)}-agent"


def _read(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("agents", [])


def _write(path: Path, agents: list[dict[str, str]]) -> None:
    path.write_text(json.dumps({"agents": agents}, indent=2) + "\n", encoding="utf-8")


def _acquire_lock(lock_path: Path) -> bool:
    """Best-effort mutual exclusion between ai_agent instances starting/
    stopping at the same moment - an exclusive file create is atomic on
    both Windows and POSIX. Gives up (returns False) after
    _LOCK_TIMEOUT_SECONDS rather than blocking startup forever on a stale
    lock left behind by a process that crashed mid-write."""
    deadline = time.monotonic() + _LOCK_TIMEOUT_SECONDS
    while True:
        try:
            os.close(os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
            return True
        except FileExistsError:
            if time.monotonic() >= deadline:
                return False
            time.sleep(_LOCK_POLL_SECONDS)


def _release_lock(lock_path: Path) -> None:
    lock_path.unlink(missing_ok=True)


def _update(path: Path, mutate) -> None:
    """Locked read-modify-write of one config_agents.json: `mutate` takes
    the current agent list and returns the new one. Silently gives up on
    any OSError (e.g. chat_app's copy missing because only ai_agent was
    checked out) - self-registration is a convenience, not something
    that should ever stop this instance from starting or stopping."""
    lock_path = path.with_name(path.name + ".lock")
    try:
        _acquire_lock(lock_path)
        try:
            _write(path, mutate(_read(path)))
        finally:
            _release_lock(lock_path)
    except OSError:
        pass


def _load() -> list[dict[str, str]]:
    return _read(_CONFIG_PATH)


_AGENTS = _load()
_AGENTS_BY_ID = {agent["id"]: agent for agent in _AGENTS}


def reload() -> None:
    """Re-reads _CONFIG_PATH into this process's in-memory registry -
    called by register()/deregister() below so this instance's own
    delegate_to_agent sees the change immediately, without needing a
    restart."""
    global _AGENTS, _AGENTS_BY_ID
    _AGENTS = _load()
    _AGENTS_BY_ID = {agent["id"]: agent for agent in _AGENTS}


def register(agent_id: str, label: str, url: str) -> None:
    """Upserts this instance's own {id, label, url} into both
    config_agents.json copies (this project's and chat_app's), so
    neither needs a manual edit to learn about a newly-started instance.
    Call once at startup, before serving; see deregister() for the
    matching shutdown call."""
    entry = {"id": agent_id, "label": label, "url": url}

    def _upsert(agents: list[dict[str, str]]) -> list[dict[str, str]]:
        return [a for a in agents if a["id"] != agent_id] + [entry]

    for path in (_CONFIG_PATH, _CHAT_APP_CONFIG_PATH):
        _update(path, _upsert)
    reload()


def deregister(agent_id: str) -> None:
    """Removes this instance's own entry from both config_agents.json
    copies - called on clean shutdown (Ctrl+C, or the process exiting
    normally) so a stopped instance doesn't linger in either list. A
    crash that skips Python's own shutdown path leaves the entry behind,
    same as any other clean-shutdown-only cleanup in this project."""

    def _remove(agents: list[dict[str, str]]) -> list[dict[str, str]]:
        return [a for a in agents if a["id"] != agent_id]

    for path in (_CONFIG_PATH, _CHAT_APP_CONFIG_PATH):
        _update(path, _remove)
    reload()


def list_agent_ids() -> list[str]:
    return [agent["id"] for agent in _AGENTS]


def get_agent(agent_id: str | None) -> dict[str, str] | None:
    if not agent_id:
        return None
    return _AGENTS_BY_ID.get(agent_id)


def all_agents() -> list[dict[str, str]]:
    return list(_AGENTS)
