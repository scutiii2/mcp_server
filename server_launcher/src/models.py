"""Plain data types: server templates, presets and groups."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class AgentInfo:
    """One ai_agent agent file (`agents/<id>.json`), as the launcher shows it.
    Read-only: the launcher never writes these files. `error` is set, and the
    other fields are empty, when the file could not be read."""

    id: str
    label: str
    port: int | None
    provider: str
    model: str
    enabled: bool
    entry: bool
    error: str | None = None


@dataclass
class ServerTemplate:
    key: str
    display_name: str
    description: str
    working_dir: Path
    venv_python: Path | None  # None for a node project
    module: str  # python: module run with -m; node: npm script name
    port_env_var: str
    default_port: int
    extra_env_vars: dict[str, str]  # editable flags besides port, e.g. AI_AGENT_PROVIDER
    supports_args: bool  # bat forwards %* to the process it runs
    runtime: str = "python"  # "python" (venv + py -m) or "node" (npm run)
    # Agent files of a project run by a supervisor (ai_agent); empty otherwise.
    agents: list[AgentInfo] = field(default_factory=list)

    @property
    def command_summary(self) -> str:
        """One-line human description of what gets launched."""
        if self.runtime == "node":
            return f"npm run {self.module}"
        return f"{self.venv_python.name}  -m {self.module}"


@dataclass
class Preset:
    """A named, saved set of flag values for one template - clicking it
    in the Presets section overwrites the current Port/env-var/Extra-args
    fields with these, the same way it would if typed by hand."""

    name: str
    port: int
    env_vars: dict[str, str] = field(default_factory=dict)
    args: str = ""


@dataclass
class GroupMember:
    template_key: str
    port: int
    extra_env: dict[str, str] = field(default_factory=dict)
    extra_args: str = ""
    preset_name: str | None = None


@dataclass
class ServerGroup:
    name: str
    members: list[GroupMember] = field(default_factory=list)
