"""LLM subsystem settings, read from environment variables.

secret_llm.env's values are merged into os.environ by run.py's
create_app() (via os.environ.setdefault, before any page is registered)
so every os.getenv() call here sees them without each module needing to
know how they got there.

Only mcp_server_url and chats_db_path remain here - provider/model
choice now lives in ai_agent (see ai_agent/src/agent_config.py), hard-
pinned per instance rather than a chat_app-side setting.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _env(name: str, default: str) -> str:
    """os.getenv, but an empty value counts as unset."""
    value = os.getenv(name)
    return value if value else default


@dataclass(frozen=True)
class Settings:
    mcp_server_url: str = field(default_factory=lambda: _env("MCP_SERVER_URL", "http://127.0.0.1:8010/mcp"))
    chats_db_path: Path = field(default_factory=lambda: Path(_env("CHATS_DB_PATH", "data/chats.db")))
    # Last-known-good tool/resource -> capability mapping from mcp_server's
    # GET /capabilities, written by services/tool_capabilities.py every
    # time that call succeeds. Read back at import time so a capability
    # this process hasn't fetched live yet (a fresh restart, or a request
    # that hits before the first successful fetch) still groups
    # correctly instead of falling into the generic "Other" bucket - see
    # that module's docstring.
    capability_cache_path: Path = field(
        default_factory=lambda: Path(_env("CAPABILITY_CACHE_PATH", "data/capability_tool_cache.json"))
    )
    # Per-user token usage log backing usage_limits.py's 6-hour/weekly caps
    # - kept separate from chats_db_path since it's a distinct concern
    # (usage accounting, not chat transcripts) with its own retention.
    usage_db_path: Path = field(default_factory=lambda: Path(_env("USAGE_DB_PATH", "data/usage.db")))


settings = Settings()
