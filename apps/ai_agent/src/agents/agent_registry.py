"""Sibling ai_agent instances this instance can delegate a sub-question to
(see delegation.py) - read once at import time from the runtime registry
.data/agent_registry.json, then kept live by register()/deregister()
below. The file is written by the running instances, never edited by hand,
so it lives under .data/ (gitignored runtime state) rather than configs/.
Includes this instance's own entry, but an agent never lists itself in
its roster (see agent_routing.specialists()): orchestrators delegate to
specialists only.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any, Iterable

from src.agents import agent_spec
from src.llm import model_tiers

_CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / ".data" / "agent_registry.json"

# "claude"/"openai" rather than this instance's own AI_AGENT_PROVIDER
# ("anthropic"/"openai" - see agent_config.py) for the id prefix: the
# provider id was renamed from "claude" to "anthropic" without renaming
# the agent id, and delegate_to_agent calls, stored chat
# `provider` fields on old chat turns, and cancel's `provider` param all
# already reference "claude-agent" - deriving straight from PROVIDER_ID
# would silently rename that out from under them.
_AGENT_ID_PREFIX = {"anthropic": "claude", "openai": "openai"}

_log = logging.getLogger(__name__)

_LOCK_TIMEOUT_SECONDS = 5.0
_LOCK_POLL_SECONDS = 0.05
_REPLACE_ATTEMPTS = 10
_REPLACE_POLL_SECONDS = 0.05


def agent_id_for(provider_id: str) -> str:
    return f"{_AGENT_ID_PREFIX.get(provider_id, provider_id)}-agent"


def _read(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("agents", [])


def _replace_with_retry(source: str, target: Path) -> None:
    """os.replace, retried briefly on PermissionError: on Windows a reader
    holding the target open (another instance's _read) makes the swap fail
    for a few milliseconds."""
    for attempt in range(_REPLACE_ATTEMPTS):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if attempt == _REPLACE_ATTEMPTS - 1:
                raise
            time.sleep(_REPLACE_POLL_SECONDS)


def _write(path: Path, agents: list[dict[str, Any]], key: str = "agents") -> None:
    """Writes a temp file in the same directory, then swaps it over `path`
    in one step, so a concurrent reader (another instance, or this one's
    per-turn reload) sees the old file or the new one - never a truncated
    half. The temp file is removed if anything fails."""
    payload = json.dumps({key: agents}, indent=2) + "\n"
    fd, temp_name = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            file.write(payload)
        # mkstemp creates the file 0600; keep the target's mode, or use a
        # normal 0644 for a new file. Best effort - modes mean little on Windows.
        try:
            if path.exists():
                shutil.copymode(path, temp_name)
            else:
                os.chmod(temp_name, 0o644)
        except OSError:
            pass
        _replace_with_retry(temp_name, path)
    except BaseException:
        Path(temp_name).unlink(missing_ok=True)
        raise


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
    """Locked read-modify-write of one registry file: `mutate` takes
    the current agent list and returns the new one. Silently gives up on
    any OSError - self-registration is a convenience, not something
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


def _load() -> list[dict[str, Any]]:
    return _read(_CONFIG_PATH)


_AGENTS = _load()
_AGENTS_BY_ID = {agent["id"]: agent for agent in _AGENTS}


def reload() -> None:
    """Re-reads _CONFIG_PATH into this process's in-memory registry -
    called by register()/deregister() below so this instance's own
    delegate_to_agent sees the change immediately, without needing a
    restart.

    If the file cannot be read or parsed (e.g. caught mid-write by another
    process), keeps the last good in-memory registry and logs a warning."""
    global _AGENTS, _AGENTS_BY_ID
    try:
        _AGENTS = _load()
    except (ValueError, OSError):
        _log.warning("could not read %s; keeping the last good agent registry", _CONFIG_PATH, exc_info=True)
        return
    _AGENTS_BY_ID = {agent["id"]: agent for agent in _AGENTS}


def register(
    agent_id: str, label: str, url: str, *, entry: bool = False, orchestrator: bool = False, focus: str = "",
    tiers: list[dict[str, str]] | None = None, efforts: list[str] | None = None,
) -> None:
    """Upserts this instance's own entry into the registry file, so no
    manual edit is needed to learn about a newly-started instance. Call once at startup, before
    serving; see deregister() for the matching shutdown call.

    entry/orchestrator/focus are optional for readers (a missing key reads
    as False/False/""): ember_api picks the entry agent, and an
    orchestrator builds its roster and Laya options from focus.
    tiers is this agent's allowed model tiers (model_tiers.as_records); an orchestrator offers them when delegating. It is stored only when non-empty.
    efforts is the reasoning efforts it accepts from a delegator (reasoning_effort.own_efforts); likewise stored only when non-empty."""
    record: dict[str, Any] = {
        "id": agent_id, "label": label, "url": url,
        "entry": entry, "orchestrator": orchestrator, "focus": focus,
    }
    if tiers:
        record["tiers"] = tiers
    if efforts:
        record["efforts"] = list(efforts)

    def _upsert(agents: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [a for a in agents if a["id"] != agent_id] + [record]

    # .data/ is gitignored runtime state, so a fresh checkout has no such
    # folder yet.
    try:
        _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    _update(_CONFIG_PATH, _upsert)
    reload()


def deregister(agent_id: str) -> None:
    """Removes this instance's own entry from the registry file
    - called on clean shutdown (Ctrl+C, or the process exiting
    normally) so a stopped instance doesn't linger in the list. A
    crash that skips Python's own shutdown path leaves the entry behind,
    same as any other clean-shutdown-only cleanup in this project."""

    def _remove(agents: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [a for a in agents if a["id"] != agent_id]

    _update(_CONFIG_PATH, _remove)
    reload()


def list_agent_ids() -> list[str]:
    return [agent["id"] for agent in _AGENTS]


def get_agent(agent_id: str | None) -> dict[str, Any] | None:
    if not agent_id:
        return None
    return _AGENTS_BY_ID.get(agent_id)


def all_agents() -> list[dict[str, Any]]:
    return list(_AGENTS)


def _definitions_path() -> Path:
    return _CONFIG_PATH.with_name("agent_definitions.json")


def _tiers_of(spec: Any) -> list[dict[str, str]]:
    """The model tiers an agent offers, weakest first, for its definition
    record. Empty for laya (no tiers), a provider without a default gateway,
    or a gateways file that cannot be read - publishing must not fail on it."""
    provider = spec.llm.provider
    gateway = spec.llm.gateway or agent_spec.default_gateway(provider)
    if provider == "laya" or not gateway:
        return []
    try:
        return model_tiers.as_records(
            model_tiers.effective_tiers(provider, gateway, spec.llm.min_tier, spec.llm.max_tier)
        )
    except (ValueError, OSError):
        _log.warning("could not read model tiers for agent %s", spec.id, exc_info=True)
        return []


def write_definitions(specs: Iterable[Any]) -> None:
    """Publishes every agent the supervisor knows (from agents/*.json) next
    to the registry, enabled or not. The registry lists only agents that are
    running, so this is how readers (ember_api's Agents page) tell an agent
    that is stopped or switched off from one that does not exist. Written
    once at supervisor start - an agent's file is read only then. Silently
    gives up on any OSError, like register(). `llm` (provider, gateway,
    model; the last two may be null) is what the Agents page shows, with
    `tiers` (the models its min_tier/max_tier range allows; see _tiers_of)."""
    records = [
        {
            "id": spec.id, "label": spec.label, "focus": spec.focus,
            "entry": spec.entry, "orchestrator": spec.orchestrator, "enabled": spec.enabled,
            "llm": {
                "provider": spec.llm.provider, "gateway": spec.llm.gateway, "model": spec.llm.model,
                "tiers": _tiers_of(spec),
            },
        }
        for spec in specs
    ]
    path = _definitions_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        _write(path, records, key="defined")
    except OSError:
        pass


def read_definitions() -> list[dict[str, Any]]:
    """What write_definitions() published; empty when nothing was (an
    instance started without the supervisor) or the file is unreadable."""
    try:
        data = json.loads(_definitions_path().read_text(encoding="utf-8"))
        defined = data.get("defined", [])
    except (OSError, ValueError, AttributeError):
        return []
    return defined if isinstance(defined, list) else []
