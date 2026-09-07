"""LLM subsystem settings, read from environment variables.

secret_llm.env's values are merged into os.environ by run.py's
create_app() (via os.environ.setdefault, before any page is registered)
so every os.getenv() call here - and every provider's own direct
os.getenv() call for its API key - sees them without each module needing
to know how they got there. Mirrors chat_app.config.Settings' relevant
fields exactly (see docs/superpowers/specs/2026-08-22-chat-capabilities-
port-design.md).
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
    attachments_config_path: Path = field(
        default_factory=lambda: Path(_env("ATTACHMENTS_CONFIG_PATH", "src/configs/config_attachments.json"))
    )
    attachments_dir: Path = field(default_factory=lambda: Path(_env("ATTACHMENTS_DIR", "data/attachments")))


settings = Settings()
