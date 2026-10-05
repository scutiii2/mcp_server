#!/usr/bin/env python3
"""Mirror the shared agent skills from .agents/skills/ into .claude/skills/.

.agents/skills/ is the one place to edit a skill: Codex reads it directly,
and Claude Code reads the copy this script writes to .claude/skills/. Both
folders are committed, so a fresh clone works for either tool without
running anything.

    python sync_skills.py          copy changed files, remove dropped skills
    python sync_skills.py --check  report drift only; exit 1 if any
"""

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / ".agents" / "skills"
TARGET = ROOT / ".claude" / "skills"


def relative_files(base: Path) -> set[Path]:
    if not base.is_dir():
        return set()
    return {p.relative_to(base) for p in base.rglob("*") if p.is_file()}


def find_drift() -> tuple[list[Path], list[Path]]:
    """Return (files to copy, target files with no source)."""
    source_files = relative_files(SOURCE)
    target_files = relative_files(TARGET)
    to_copy = sorted(
        rel
        for rel in source_files
        if rel not in target_files
        or (SOURCE / rel).read_bytes() != (TARGET / rel).read_bytes()
    )
    stale = sorted(target_files - source_files)
    return to_copy, stale


def apply(to_copy: list[Path], stale: list[Path]) -> None:
    for rel in to_copy:
        dest = TARGET / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(SOURCE / rel, dest)
    for rel in stale:
        (TARGET / rel).unlink()
    # Drop folders left empty by removed skills.
    for folder in sorted(TARGET.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        if folder.is_dir() and not any(folder.iterdir()):
            folder.rmdir()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="report drift without writing")
    args = parser.parse_args()

    if not SOURCE.is_dir():
        print(f"No source folder: {SOURCE}", file=sys.stderr)
        return 1

    to_copy, stale = find_drift()
    for rel in to_copy:
        print(f"{'differs' if args.check else 'copied'}: {rel.as_posix()}")
    for rel in stale:
        print(f"{'no source' if args.check else 'removed'}: {rel.as_posix()}")

    if not to_copy and not stale:
        print("Skills in sync.")
        return 0
    if args.check:
        print("Run: python sync_skills.py", file=sys.stderr)
        return 1
    apply(to_copy, stale)
    return 0


if __name__ == "__main__":
    sys.exit(main())
