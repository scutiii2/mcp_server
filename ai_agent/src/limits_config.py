"""Reads one top-level section of configs/config_limits.json - the single
file holding token_limits, tool_selection and servers. Each consumer keeps
its own `_CONFIG_PATH` and validation; this only does the shared
seed-and-parse step."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.seed import seed_from_example

CONFIG_PATH = Path(__file__).resolve().parent.parent / "configs" / "config_limits.json"

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
