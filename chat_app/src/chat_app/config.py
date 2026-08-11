"""Flask app settings."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    mcp_server_url: str = os.getenv("MCP_SERVER_URL", "http://127.0.0.1:8010/mcp")
    secret_key: str = os.getenv("FLASK_SECRET_KEY", "dev-change-me")
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-4o")


settings = Settings()
