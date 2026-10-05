"""Read-only view of ai_agent's agent files for the launcher.

ai_agent's run.bat starts `src.supervisor`, which runs one process per
enabled `agents/<id>.json`, each on that file's port, and reads no
command-line arguments. So for such a project the launcher's own port,
env and args fields mean nothing: it shows the agents instead and uses the
entry agent's port to tell whether the project is running. The supervisor
validates the files itself; this module only reads what it needs to show.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from .models import AgentInfo

SUPERVISOR_MODULE = "src.supervisor"
AGENTS_DIR_NAME = "agents"


def is_agent_project(working_dir: Path, module: str) -> bool:
    """A project whose bat runs the supervisor and that has an agents folder."""
    return module == SUPERVISOR_MODULE and (working_dir / AGENTS_DIR_NAME).is_dir()


def read_agent_files(agents_dir: Path) -> list[AgentInfo]:
    """Every `*.json` in `agents_dir`, sorted by id (the template file ends in
    `.template`, so it is not matched). A file that cannot be read becomes an
    error row rather than stopping the launcher."""
    return [_read_one(path) for path in sorted(agents_dir.glob("*.json"))]


def _read_one(path: Path) -> AgentInfo:
    agent_id = path.stem
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        return _error_row(agent_id, f"cannot read: {error}")
    if not isinstance(data, dict):
        return _error_row(agent_id, "not a JSON object")
    llm = data.get("llm") if isinstance(data.get("llm"), dict) else {}
    port = data.get("port")
    return AgentInfo(
        id=agent_id,
        label=_text(data.get("label")) or agent_id,
        port=port if isinstance(port, int) and not isinstance(port, bool) else None,
        provider=_text(llm.get("provider")),
        model=_text(llm.get("model")),
        enabled=data.get("enabled", True) is True,
        entry=data.get("entry", False) is True,
    )


def _error_row(agent_id: str, message: str) -> AgentInfo:
    return AgentInfo(agent_id, agent_id, None, "", "", enabled=False, entry=False, error=message)


def _text(value: Any) -> str:
    return value if isinstance(value, str) else ""


def entry_port(agents: Iterable[AgentInfo]) -> int | None:
    """The enabled entry agent's port, else the first enabled agent's, else None."""
    enabled = [a for a in agents if a.enabled and a.port is not None]
    entry = next((a for a in enabled if a.entry), None)
    chosen = entry or (enabled[0] if enabled else None)
    return chosen.port if chosen else None


def _agents_of(template: Any) -> list[AgentInfo]:
    # Templates built by hand (tests, older callers) may not carry `agents`.
    return list(getattr(template, "agents", None) or [])


def launch_port(template: Any, requested: int) -> int:
    """The port to start and track a template on: the entry agent's port for
    an agent project, else the requested one."""
    port = entry_port(_agents_of(template))
    return port if port is not None else requested


def start_refusal(template: Any, port_in_use: Callable[[int], bool]) -> str | None:
    """Why an agent project must not start now, or None. Never bump its port:
    a second supervisor would fight the first for every agent's port."""
    agents = _agents_of(template)
    if not agents:
        return None
    port = entry_port(agents)
    if port is None:
        return f"{template.display_name} has no enabled agent with a port in its agents folder."
    if port_in_use(port):
        return f"{template.display_name} already seems to run on port {port} (its entry agent)."
    return None
