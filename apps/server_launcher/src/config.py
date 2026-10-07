"""Paths, run.bat parsing patterns and timing constants."""

from __future__ import annotations

import re
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = PROJECT_DIR.parent
SELF_DIR_NAME = PROJECT_DIR.name  # discovery must not list the launcher itself
ASSETS_DIR = PROJECT_DIR / "src" / "assets"
DATA_DIR = PROJECT_DIR / "data"
_PRESETS_PATH = DATA_DIR / "presets.json"
_GROUPS_PATH = DATA_DIR / "groups.json"
# Other folders (relative to REPO_ROOT) whose */run.bat projects are
# launchable too - for projects that live in their own repo next to this
# one, e.g. "../PDFMerger". A JSON list of strings; tracked, not personal.
_EXTRA_ROOTS_PATH = DATA_DIR / "extra_roots.json"
# What the Servers tab's Add / Remove buttons change: project folders added by
# hand and the keys of detected servers hidden from the list. Per machine
# (absolute paths), so gitignored.
_SERVERS_PATH = DATA_DIR / "servers.json"
# Written on close only when the user chooses to leave running instances in
# the background instead of stopping them - the (template, port) pairs to
# re-adopt on the next launch. Consumed (deleted) as soon as it's read, so
# it never goes stale - see LauncherWindow._adopt_running_instances().
_KEPT_RUNNING_PATH = DATA_DIR / "kept_running.json"

# Hint text shown under the "Extra args" field for templates that support
# it, keyed by ServerTemplate.key - not auto-derived from the target
# project's own --help (a hardcoded entry per project isn't worth a
# --help-parsing mechanism for just two of them); add an entry here if
# another project's run.bat starts forwarding %* too. Empty since ai_agent's
# bat runs the supervisor, which reads no arguments (see agent_files.py).
_EXTRA_ARGS_HINTS: dict[str, str] = {}

_VENV_RE = re.compile(r'call\s+\.venv_(\w+)\\Scripts\\activate')
# Excludes "py -m venv ..." (the bootstrap line) so this finds the actual
# run command (py -m src.run / py -m src.server) regardless of where in
# the bat the bootstrap block sits relative to it.
_MODULE_RE = re.compile(r'py\s+-m\s+(?!venv\b)(\S+)')
# A node project's run.bat (e.g. ember_web): `npm run <script>` is its run
# command, checked only when the python venv/module patterns above miss.
_NPM_SCRIPT_RE = re.compile(r'npm\s+run\s+(\S+)')
# Not anchored to line-start: ai_agent's run.bat sets its defaults via
# `if not defined X set X=value`, so `set` doesn't always open the line.
_SET_VAR_RE = re.compile(r"(?:^|\s)set\s+([A-Za-z_][A-Za-z0-9_]*)=([^\r\n]*)", re.IGNORECASE | re.MULTILINE)
# `REM LABEL: ...` / `REM DESCRIPTION: ...` - a run.bat's own self-declared
# display name/blurb for server_launcher.py, so relabeling a server is a
# one-line edit in the bat instead of touching launcher code.
_LABEL_RE = re.compile(r"^\s*REM\s+LABEL:\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE)
_DESCRIPTION_RE = re.compile(r"^\s*REM\s+DESCRIPTION:\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE)
# `REM LAUNCHER: skip` - a project that is not a server (e.g. chat_cli, an
# interactive terminal program) opts out of discovery in its own bat.
_SKIP_RE = re.compile(r"^\s*REM\s+LAUNCHER:\s*skip\b", re.IGNORECASE | re.MULTILINE)

# Port env var + default for a project whose bat doesn't `set` its own
# port (mcp_server/catalog_service each read one straight from
# their own config/run.py - see MCP_PORT/CATALOG_PORT; the PDFMerger
# projects read theirs from the repo-root .env).
# ai_agent needs no entry here: its bat already `set`s AI_AGENT_PORT
# itself, picked up generically below.
_PROJECT_PORT_ENV = {
    "mcp_server": ("MCP_PORT", 8010),
    "catalog_service": ("CATALOG_PORT", 8020),
    "pdf_merger": ("PDF_MERGER_PORT", 8040),
    "pdf_merger_web": ("PDF_MERGER_WEB_PORT", 5174),
    "video_downloader": ("VIDEO_DOWNLOADER_PORT", 8050),
    "video_downloader_web": ("VIDEO_DOWNLOADER_WEB_PORT", 5175),
}

_POLL_MS = 500
_RESTART_WAIT_SECONDS = 6
