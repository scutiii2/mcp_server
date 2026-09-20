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
# Written on close only when the user chooses to leave running instances in
# the background instead of stopping them - the (template, port) pairs to
# re-adopt on the next launch. Consumed (deleted) as soon as it's read, so
# it never goes stale - see LauncherWindow._adopt_running_instances().
_KEPT_RUNNING_PATH = DATA_DIR / "kept_running.json"

# Hint text shown under the "Extra args" field for templates that support
# it, keyed by ServerTemplate.key - not auto-derived from the target
# project's own --help (a hardcoded entry per project isn't worth a
# --help-parsing mechanism for just two of them); add an entry here if
# another project's run.bat starts forwarding %* too.
_EXTRA_ARGS_HINTS = {
    "ai_agent": (
        "--gateway <name>   override the LLM gateway, e.g. openrouter, bedrock, vertex, "
        "litellm, helicone, portkey (anthropic) or azure, together, groq, fireworks, "
        "deepinfra, perplexity, ollama, vllm (openai)\n"
        "--role <name>      override the persona role, e.g. ops_specialist "
        "(configs/config_ai_agent_roles.json)\n"
        "--mcp-url <url>    override the mcp_server URL this agent connects to, "
        "e.g. http://127.0.0.1:8010/mcp"
    ),
    "chat_app": (
        "--mcp-url <url>    override the mcp_server URL this app connects to, "
        "e.g. http://127.0.0.1:8010/mcp"
    ),
}

_VENV_RE = re.compile(r'call\s+\.venv_(\w+)\\Scripts\\activate')
# Excludes "py -m venv ..." (the bootstrap line) so this finds the actual
# run command (py -m src.run / py -m src.server) regardless of where in
# the bat the bootstrap block sits relative to it.
_MODULE_RE = re.compile(r'py\s+-m\s+(?!venv\b)(\S+)')
# Not anchored to line-start: ai_agent's run.bat sets its defaults via
# `if not defined X set X=value`, so `set` doesn't always open the line.
_SET_VAR_RE = re.compile(r"(?:^|\s)set\s+([A-Za-z_][A-Za-z0-9_]*)=([^\r\n]*)", re.IGNORECASE | re.MULTILINE)
# `REM LABEL: ...` / `REM DESCRIPTION: ...` - a run.bat's own self-declared
# display name/blurb for server_launcher.py, so relabeling a server is a
# one-line edit in the bat instead of touching launcher code.
_LABEL_RE = re.compile(r"^\s*REM\s+LABEL:\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE)
_DESCRIPTION_RE = re.compile(r"^\s*REM\s+DESCRIPTION:\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE)

# Port env var + default for a project whose bat doesn't `set` its own
# port (mcp_server/chat_app/catalog_service each read one straight from
# their own config/run.py - see MCP_PORT/CHAT_APP_PORT/CATALOG_PORT).
# ai_agent needs no entry here: its bat already `set`s AI_AGENT_PORT
# itself, picked up generically below.
_PROJECT_PORT_ENV = {
    "mcp_server": ("MCP_PORT", 8010),
    "chat_app": ("CHAT_APP_PORT", 5000),
    "catalog_service": ("CATALOG_PORT", 8020),
}

_POLL_MS = 500
_RESTART_WAIT_SECONDS = 6
