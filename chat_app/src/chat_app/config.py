"""Flask app settings."""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from pathlib import Path


def _env(name: str, default: str) -> str:
    """os.getenv, but an empty value counts as unset - a blank line in
    .env (``OPENAI_MODEL=``) means "I didn't set this", not "set it to
    the empty string"."""
    value = os.getenv(name)
    return value if value else default


def _secret_key() -> str:
    """A random key when none is configured, rather than a fixed default.

    The old default was the literal string "dev-change-me", which is
    exactly as good as no secret at all: anyone who has read this file
    can forge whatever the key protects. Nothing signs cookies here yet,
    so this is a landmine rather than a live hole - but it would become
    one silently, the day someone adds a login.

    Generating a random key means an unconfigured deployment is
    *inconvenient* (restarting invalidates sessions) instead of
    *insecure*, which is the right way round for a mistake to fail. Set
    FLASK_SECRET_KEY to make sessions survive a restart.
    """
    configured = os.getenv("FLASK_SECRET_KEY")
    if configured and configured != "dev-change-me":
        return configured
    return secrets.token_urlsafe(32)


@dataclass(frozen=True)
class Settings:
    mcp_server_url: str = _env("MCP_SERVER_URL", "http://127.0.0.1:8010/mcp")
    secret_key: str = _secret_key()
    openai_model: str = _env("OPENAI_MODEL", "gpt-5.6-sol")
    claude_model: str = _env("CLAUDE_MODEL", "claude-sonnet-5")
    # Structured, per-deployment config (currently just the Ollama desired-
    # model list) - see infra/app_config.py. Mirrors mcp_server/config.py's
    # CONFIG_PATH; relative to CWD by default, same as every other path
    # setting in this project.
    chat_config_path: Path = Path(_env("CHAT_CONFIG_PATH", "config.json"))
    # Runtime-created accounts and invite codes - see auth/store.py.
    # Relative to CWD by default, same convention as chat_config_path.
    #
    # ADMIN_USERNAME/ADMIN_PASSWORD (the default account) are deliberately
    # *not* read into this frozen, import-time-evaluated dataclass - see
    # auth/service.py._admin_credentials, which reads them with plain
    # os.getenv() at request time instead, the same way
    # security.configured_credentials() does for CHAT_AUTH_USER/PASSWORD.
    # A frozen dataclass field would freeze the value at process start,
    # which breaks the same thing it breaks for those: tests that
    # monkeypatch the env per-case, and a deployment that expects editing
    # .env and restarting to be enough.
    users_db_path: Path = Path(_env("USERS_DB_PATH", "data/users.db"))
    # Per-user chat history - see chats/store.py. Mirrors users_db_path
    # immediately above it (relative to CWD by default, same convention).
    chats_db_path: Path = Path(_env("CHATS_DB_PATH", "data/chats.db"))
    # Paused staged-pipeline plans (see services/llm/staged_plans_store.py) -
    # bridges one chat turn to the next when a plan pauses on an ask_user
    # step. Mirrors chats_db_path immediately above it: own file, relative
    # to CWD by default, same convention.
    staged_plans_db_path: Path = Path(_env("STAGED_PLANS_DB_PATH", "data/staged_plans.db"))
    # Where logging_setup.configure_logging() writes server.log and
    # errors.report() writes per-reference error files. Relative to CWD by
    # default, same convention as the paths above.
    log_dir: Path = Path(_env("CHAT_LOG_DIR", "logs"))


settings = Settings()
