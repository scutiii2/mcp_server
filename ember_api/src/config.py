"""ember_api settings: configs/config_app.json, overridable by env vars."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from src.utils.config_loader import load_json_config

PROJECT_DIR = Path(__file__).resolve().parent.parent
CONFIGS_DIR = PROJECT_DIR / "configs"
SECRETS_DIR = PROJECT_DIR / "secrets"


@dataclass(frozen=True)
class SecuritySettings:
    """config_app.json's "security" block (port of chat_app's
    config_security_*.json). Every field has a safe default, so a config
    file without the block still gets login rate limiting and headers."""

    # Login rate limiting: after `max_attempts` failed logins within
    # `window_seconds`, login is refused (429) until `lockout_seconds` after
    # the last failure. scope: "ip", "account" or "both" (either can trip it).
    rate_limit_enabled: bool = True
    max_attempts: int = 5
    window_seconds: int = 900
    lockout_seconds: int = 900
    rate_limit_scope: str = "both"
    # Requests from these addresses may name the real client in
    # X-Forwarded-For (Vite's dev/preview proxy runs on loopback). Anything
    # else is taken at its socket address, so the header can't be spoofed.
    trusted_proxies: tuple[str, ...] = ("127.0.0.1", "::1")
    # Networks (CIDR or single address). Deny wins; a non-empty allow list
    # refuses everything not on it. Checked on every request (403).
    ip_allow_list: tuple[str, ...] = ()
    ip_deny_list: tuple[str, ...] = ()
    # nosniff / frame / referrer / CSP headers on every response.
    security_headers: bool = True
    # >0 adds Strict-Transport-Security; only once served over HTTPS.
    hsts_max_age: int = 0

    @classmethod
    def from_config(cls, raw: dict) -> SecuritySettings:
        rate = raw.get("rate_limit", {})
        ip_filter = raw.get("ip_filter", {})
        headers = raw.get("headers", {})
        scope = rate.get("scope", "both")
        if scope not in ("ip", "account", "both"):
            raise ValueError(f'security.rate_limit.scope must be "ip", "account" or "both", not {scope!r}')
        return cls(
            rate_limit_enabled=bool(rate.get("enabled", True)),
            max_attempts=int(rate.get("max_attempts", 5)),
            window_seconds=int(rate.get("window_seconds", 900)),
            lockout_seconds=int(rate.get("lockout_seconds", 900)),
            rate_limit_scope=scope,
            trusted_proxies=tuple(raw.get("trusted_proxies", ("127.0.0.1", "::1"))),
            ip_allow_list=tuple(ip_filter.get("allow_list", ())),
            ip_deny_list=tuple(ip_filter.get("deny_list", ())),
            security_headers=bool(headers.get("enabled", True)),
            hsts_max_age=int(headers.get("hsts_max_age", 0)),
        )


@dataclass(frozen=True)
class UsageSettings:
    """config_app.json's "usage" block (port of chat_app's
    config_usage_limits.json). A limit of 0 means unlimited."""

    six_hour_token_limit: int = 1_000_000
    weekly_token_limit: int = 5_000_000
    # Soft cap on one chat's context, whatever the model allows: at
    # auto_summarize_ratio of it (or of the model's window, if smaller) the
    # chat is summarized before the next question is sent.
    max_context_tokens_per_chat: int = 150_000
    auto_summarize_ratio: float = 0.6

    @classmethod
    def from_config(cls, raw: dict) -> UsageSettings:
        ratio = float(raw.get("auto_summarize_ratio", 0.6))
        if not 0 < ratio <= 1:
            raise ValueError("usage.auto_summarize_ratio must be above 0 and at most 1")
        return cls(
            six_hour_token_limit=max(0, int(raw.get("six_hour_token_limit", 1_000_000))),
            weekly_token_limit=max(0, int(raw.get("weekly_token_limit", 5_000_000))),
            max_context_tokens_per_chat=max(0, int(raw.get("max_context_tokens_per_chat", 150_000))),
            auto_summarize_ratio=ratio,
        )


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
    agents_registry_path: Path = PROJECT_DIR.parent / "ai_agent" / "configs" / "config_agents.json"
    mcp_server_url: str = "http://127.0.0.1:8010/mcp"
    security: SecuritySettings = field(default_factory=SecuritySettings)
    usage: UsageSettings = field(default_factory=UsageSettings)

    @property
    def database_url(self) -> str:
        return f"sqlite+aiosqlite:///{self.database_path.as_posix()}"


def load_settings() -> Settings:
    """Reads config_app.json (created from its .example if missing).
    EMBER_API_HOST / EMBER_API_PORT win over the file, so server_launcher
    and run.bat can pick the port."""
    raw = load_json_config(CONFIGS_DIR / "config_app.json")
    database_path = _project_path(raw.get("database_path", "data/ember_api.db"))
    return Settings(
        host=os.getenv("EMBER_API_HOST") or raw.get("host", "127.0.0.1"),
        port=int(os.getenv("EMBER_API_PORT") or raw.get("port", 8030)),
        database_path=database_path,
        session_cookie_name=raw.get("session_cookie_name", "ember_session"),
        session_hours=int(raw.get("session_hours", 12)),
        cookie_secure=bool(raw.get("cookie_secure", False)),
        secrets_dir=SECRETS_DIR,
        default_role=raw.get("default_role") or "Member",
        agents_registry_path=_project_path(
            raw.get("agents_registry_path", "../ai_agent/configs/config_agents.json")
        ),
        mcp_server_url=raw.get("mcp_server_url") or "http://127.0.0.1:8010/mcp",
        security=SecuritySettings.from_config(raw.get("security", {})),
        usage=UsageSettings.from_config(raw.get("usage", {})),
    )


def _project_path(value: str) -> Path:
    """Relative config paths are relative to the ember_api folder."""
    path = Path(value)
    return path if path.is_absolute() else (PROJECT_DIR / path).resolve()
