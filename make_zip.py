#!/usr/bin/env python3
"""Zip up this repo's projects, excluding everything covered by .gitignore.

Uses `git ls-files` to determine which files are eligible (so all
.gitignore rules - including nested ones and negation patterns, and
including chat_app's own nested .gitignore - are honored automatically),
then keeps only the files that live under one of the included top-level
project directories or are a top-level `.bat` launcher. Output goes to
zip_versions/, which is itself gitignored.

Two zips:
- Default: mcp_server/, chat_app/, ai_agent/, docs/, and the root-level
  .bat launchers - the projects actually needed to run this setup.
- `--with-templates`: the same, plus mcp_client_template/ and
  mcp_server_ext/ - the copy-to-start-a-new-project templates, not
  needed to just run the existing setup.
"""

import argparse
import subprocess
import sys
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "zip_versions"

DEFAULT_DIRS = ("mcp_server", "chat_app", "ai_agent", "docs")
TEMPLATE_DIRS = ("mcp_client_template", "mcp_server_ext")

# Root-level .bat launchers to leave out even though they're top-level
# .bat files - run_crafty.bat launches crafty_mcp_server/, which isn't
# bundled in either zip variant, so including it would be a launcher
# with no matching project.
EXCLUDED_BAT_FILES = ("run_crafty.bat",)


def get_included_files() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)
        sys.exit(1)
    return [line for line in result.stdout.splitlines() if line]


def _is_included(rel_path: str, top_level_dirs: tuple[str, ...]) -> bool:
    posix = rel_path.replace("\\", "/")
    if "/" not in posix:
        # A root-level file - only the run_*.bat launchers belong in
        # either zip (every other repo-root file, like make_zip.py
        # itself, is left out), except EXCLUDED_BAT_FILES.
        return posix.endswith(".bat") and posix not in EXCLUDED_BAT_FILES
    top = posix.split("/", 1)[0]
    return top in top_level_dirs


def filter_files(files: list[str], with_templates: bool) -> list[str]:
    dirs = DEFAULT_DIRS + TEMPLATE_DIRS if with_templates else DEFAULT_DIRS
    return [f for f in files if _is_included(f, dirs)]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--with-templates",
        action="store_true",
        help="Also include mcp_client_template/ and mcp_server_ext/.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    files = filter_files(get_included_files(), with_templates=args.with_templates)
    if not files:
        print("No files found to zip.", file=sys.stderr)
        sys.exit(1)

    OUTPUT_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    suffix = "_with_templates" if args.with_templates else ""
    zip_path = OUTPUT_DIR / f"{ROOT.name}{suffix}_{timestamp}.zip"

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel_path in files:
            full_path = ROOT / rel_path
            if full_path.is_file():
                zf.write(full_path, rel_path)

    print(f"Created {zip_path} ({len(files)} files)")


if __name__ == "__main__":
    main()
