"""ember_api's single ``.env`` file.

Replaces the old ``secrets/secret_*.env`` one-file-per-concern split. If
``.env`` is missing it is built once: from the legacy ``secrets/*.env`` files
when any exist (so real values, such as the bootstrap admin password,
survive the move), otherwise from ``.env.example``. The legacy folder is left
in place for the operator to delete.

Values are read from the file on demand (see ``load_env_secrets``), not
loaded into the process environment.
"""

from __future__ import annotations

import shutil
from pathlib import Path


def migrate_legacy_secrets(env_path: Path, legacy_dir: Path) -> bool:
    """Build ``env_path`` from ``legacy_dir/*.env``; True if it was written.

    Does nothing when ``env_path`` already exists or no legacy file does.
    Each legacy file is copied verbatim under a header naming its source.
    """
    if env_path.exists() or not legacy_dir.is_dir():
        return False
    legacy_files = sorted(legacy_dir.glob("*.env"))
    if not legacy_files:
        return False
    parts = []
    for legacy in legacy_files:
        body = legacy.read_text(encoding="utf-8")
        parts.append(f"# ---- from {legacy_dir.name}/{legacy.name} ----\n{body.rstrip()}\n")
    env_path.write_text("\n".join(parts), encoding="utf-8")
    return True


def ensure_env_file(env_path: Path, example_path: Path, legacy_dir: Path) -> None:
    """Make sure ``env_path`` exists: migrate legacy files, else copy the example."""
    if env_path.exists():
        return
    if migrate_legacy_secrets(env_path, legacy_dir):
        return
    if example_path.exists():
        shutil.copyfile(example_path, env_path)
