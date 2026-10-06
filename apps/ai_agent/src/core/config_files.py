"""Paths and the shared seed-and-parse step for ai_agent's startup config
files under configs/. Each consumer keeps its own validation; this only
locates the file and reads one top-level section of it."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.core.seed import seed_from_example

CONFIGS_DIR = Path(__file__).resolve().parent.parent.parent / "configs"

# One file per concern, each a JSON object with one top-level section.
LIMITS_PATH = CONFIGS_DIR / "config_limits.json"  # token_limits
SERVERS_PATH = CONFIGS_DIR / "config_servers.json"  # servers
TOOL_SELECTION_PATH = CONFIGS_DIR / "config_tool_selection.json"  # tool_selection

_REQUIRED = object()


def read_section(path: Path, section: str, default: Any = _REQUIRED) -> Any:
    """`section` of the JSON object in `path` (seeded from its .example if
    missing). Raises ValueError if the file is not an object or the section
    is absent and no `default` was given."""
    seed_from_example(path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path.name} must be an object")
    if section not in raw:
        if default is _REQUIRED:
            raise ValueError(f"{path.name} must contain a '{section}' section")
        return default
    return raw[section]
