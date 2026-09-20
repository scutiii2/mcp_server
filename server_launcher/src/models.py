"""Plain data types: server templates, presets and groups."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ServerTemplate:
    key: str
    display_name: str
    description: str
    working_dir: Path
    venv_python: Path
    module: str
    port_env_var: str
    default_port: int
    extra_env_vars: dict[str, str]  # editable flags besides port, e.g. AI_AGENT_PROVIDER
    supports_args: bool  # bat forwards %* to the process it runs


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
