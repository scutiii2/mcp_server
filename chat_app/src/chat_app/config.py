"""Flask app settings."""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass


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


settings = Settings()
