"""Paths and the shared seed-and-parse step for ai_agent's startup config
files under configs/. Each consumer keeps its own validation; this only
locates the file and reads one top-level section of it."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from src.core.catalog import catalog
from src.core.seed import seed_from_example

CONFIGS_DIR = Path(__file__).resolve().parent.parent.parent / "configs"

# Runtime tuning shares one file; the MCP server list stays separate.
TUNING_PATH = CONFIGS_DIR / "config_tuning.json"  # token_limits, tool_selection
SERVERS_PATH = CONFIGS_DIR / "config_servers.json"  # servers

_REQUIRED = object()


def read_section(path: Path, section: str, default: Any = _REQUIRED) -> Any:
    """`section` of the JSON object in `path` (seeded from its .example if
    missing). Raises ValueError if the file is not an object or the section
    is absent and no `default` was given."""
    if path.name == TUNING_PATH.name:
        seed_tuning(path)
    else:
        seed_from_example(path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path.name} must be an object")
    if section not in raw:
        if default is _REQUIRED:
            raise ValueError(f"{path.name} must contain a '{section}' section")
        return default
    return raw[section]


@catalog
def seed_tuning(path: Path = TUNING_PATH) -> None:
    """Seed shared tuning, preserving legacy sections and keeping old files
    as rollback backups. An existing tuning file is always authoritative.
    Publish the complete JSON atomically so parallel agent starts never
    read a partially written migration.
    """
    if path.exists():
        return
    legacy_paths = {
        "token_limits": path.parent / "config_limits.json",
        "tool_selection": path.parent / "config_tool_selection.json",
    }
    if not any(legacy.exists() for legacy in legacy_paths.values()):
        seed_from_example(path)
        return
    example = path.with_name(path.name + ".example")
    raw = json.loads(example.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{example.name} must be an object")
    for section, legacy in legacy_paths.items():
        if legacy.exists():
            default = {} if section == "tool_selection" else _REQUIRED
            raw[section] = read_section(legacy, section, default)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, suffix=".tmp", delete=False,
        ) as output:
            temporary = Path(output.name)
            json.dump(raw, output, indent=2)
            output.write("\n")
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
