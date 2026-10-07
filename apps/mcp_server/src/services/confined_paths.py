"""Read files only inside one folder, and never a secret.

A caller hands a tool a relative path. `ConfinedRoot` turns it into a real
path or refuses: no absolute paths, no `..`, no symlink that leads outside
the root, and nothing whose name marks a secret or a build folder (the
workspace rule: never read `secrets/`, `.secrets/`, `.env*` or key files).
Used by every capability that reads a folder it does not own.
"""

from __future__ import annotations

import os
from fnmatch import fnmatch
from pathlib import Path, PurePosixPath
from typing import Iterator

from src.utils.catalog import catalog

# Names (fnmatch, case-insensitive) that are never read or listed.
BLOCKED_NAMES: tuple[str, ...] = (
    ".env*",
    "secrets",
    ".secrets",
    "*.key",
    "*.pem",
    "*.pfx",
    "*.p12",
    "id_rsa*",
    "id_ed25519*",
    ".git",
    ".obsidian",
    "node_modules",
    ".venv*",
    "venv",
    "__pycache__",
    "dist",
    "build",
)


class PathRefused(ValueError):
    """The path is outside the root or names something that is never read."""


def is_blocked_name(name: str) -> bool:
    lowered = name.lower()
    return any(fnmatch(lowered, pattern) for pattern in BLOCKED_NAMES)


@catalog
class ConfinedRoot:
    """A folder tools may read, optionally only files with certain suffixes."""

    def __init__(self, root: Path, suffixes: tuple[str, ...] | None = None) -> None:
        self.root = root.resolve()
        self._suffixes = tuple(s.lower() for s in suffixes) if suffixes else None

    def resolve(self, relative: str = "") -> Path:
        """The real path for `relative` inside the root. Raises PathRefused."""
        relative = (relative or "").strip().replace("\\", "/")
        pure = PurePosixPath(relative)
        if pure.is_absolute() or (len(relative) > 1 and relative[1] == ":"):
            raise PathRefused("Use a path relative to the root, not an absolute one.")
        parts = [part for part in pure.parts if part != "."]
        if ".." in parts:
            raise PathRefused("A path may not contain '..'.")
        for part in parts:
            if is_blocked_name(part):
                raise PathRefused(f"{part!r} is never read.")
        target = self.root.joinpath(*parts).resolve()
        if target != self.root and not target.is_relative_to(self.root):
            raise PathRefused("That path leads outside the root.")
        if target.is_file() and not self._suffix_ok(target):
            raise PathRefused(f"Only {', '.join(self._suffixes or ())} files are read here.")
        return target

    def walk_files(self, start: Path | None = None) -> Iterator[Path]:
        """Every readable file under `start` (default: the root), sorted, symlinks not followed."""
        for folder, dirs, files in os.walk(start or self.root, followlinks=False):
            dirs[:] = sorted(d for d in dirs if not is_blocked_name(d))
            for name in sorted(files):
                path = Path(folder, name)
                if not is_blocked_name(name) and self._suffix_ok(path) and not path.is_symlink():
                    yield path

    def relative(self, path: Path) -> str:
        return path.resolve().relative_to(self.root).as_posix()

    def _suffix_ok(self, path: Path) -> bool:
        return self._suffixes is None or path.suffix.lower() in self._suffixes
