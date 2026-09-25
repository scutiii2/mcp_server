"""ember_api settings: configs/config_app.json, overridable by env vars."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from src.utils.config_loader import load_json_config

PROJECT_DIR = Path(__file__).resolve().parent.parent
CONFIGS_DIR = PROJECT_DIR / "configs"
SECRETS_DIR = PROJECT_DIR / "secrets"


@dataclass(frozen=True)
class Settings:
    host: str
    port: int
    database_path: Path
    session_cookie_name: str
    session_hours: int
    cookie_secure: bool
    secrets_dir: Path
    default_role: str = "Member"

    @property
    def database_url(self) -> str:
        return f"sqlite+aiosqlite:///{self.database_path.as_posix()}"


def load_settings() -> Settings:
    """Reads config_app.json (created from its .example if missing).
    EMBER_API_HOST / EMBER_API_PORT win over the file, so server_launcher
    and run.bat can pick the port."""
    raw = load_json_config(CONFIGS_DIR / "config_app.json")
    database_path = Path(raw.get("database_path", "data/ember_api.db"))
    if not database_path.is_absolute():
        database_path = PROJECT_DIR / database_path
    return Settings(
        host=os.getenv("EMBER_API_HOST") or raw.get("host", "127.0.0.1"),
        port=int(os.getenv("EMBER_API_PORT") or raw.get("port", 8030)),
        database_path=database_path,
        session_cookie_name=raw.get("session_cookie_name", "ember_session"),
        session_hours=int(raw.get("session_hours", 12)),
        cookie_secure=bool(raw.get("cookie_secure", False)),
        secrets_dir=SECRETS_DIR,
        default_role=raw.get("default_role") or "Member",
    )
