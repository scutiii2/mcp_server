"""Config/secret file loading with auto-created real files.

Same behavior as chat_app/src/utils/config_loader.py: a missing real file is
copied from its committed ``.example`` twin on first use instead of failing.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from dotenv import dotenv_values


def _ensure_from_example(path: Path) -> bool:
    """Copies ``<path>.example`` to ``path`` if needed; False if neither exists."""
    if path.exists():
        return True
    example = path.with_name(path.name + ".example")
    if not example.exists():
        return False
    shutil.copyfile(example, path)
    return True


def load_json_config(path: str | Path) -> dict:
    path = Path(path)
    if not _ensure_from_example(path):
        raise FileNotFoundError(f"Config file not found: {path}")
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def load_env_secrets(path: str | Path) -> dict[str, str]:
    """A missing secret file (and example) is an empty dict, not an error."""
    path = Path(path)
    if not _ensure_from_example(path):
        return {}
    return {k: v for k, v in dotenv_values(path).items() if v is not None}
