"""Problems in ember_api's config and secret files, for the Config issues
page (port of chat_app/src/services/config_validation.py).

ember_api refuses to start on a config it can't use at all, so this looks
for what still lets it run but is wrong: mistyped values, a broken agent
registry, secrets still set to a placeholder, half-configured SMTP.
Messages name the file and key only, never a secret's value.

Checks read the files fresh each call, so fixing one and reloading the page
shows the result; changes to config_app.json itself still need a restart
to take effect, which the page says.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from dotenv import dotenv_values

from src.config import Settings

_PLACEHOLDER = re.compile(
    r"^(change[-_ ]?me|replace[-_ ]?me|your[-_ ].*|<.*>|x{3,}|todo)$|@example\.(com|org|net)$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ConfigIssue:
    file: str
    key: str
    message: str


Problem = tuple[str, str]  # (key, message)


def _is_int(value: Any, minimum: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= minimum


def _is_http_url(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    parts = urlsplit(value)
    return parts.scheme in ("http", "https") and bool(parts.netloc)


def _is_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _check_app(data: dict[str, Any]) -> list[Problem]:
    rules: list[tuple[str, Callable[[Any], bool], str]] = [
        ("host", _is_text, "a non-empty string"),
        ("port", lambda v: _is_int(v, 1) and v <= 65535, "a port number (1-65535)"),
        ("database_path", _is_text, "a non-empty string"),
        ("session_cookie_name", lambda v: isinstance(v, str) and re.fullmatch(r"[A-Za-z0-9_-]+", v), "letters, digits, _ or -"),
        ("session_hours", lambda v: _is_int(v, 1), "a positive integer"),
        ("cookie_secure", lambda v: isinstance(v, bool), "true or false"),
        ("default_role", _is_text, "a non-empty string"),
        ("agents_registry_path", _is_text, "a non-empty string"),
        ("mcp_server_url", _is_http_url, "an http(s) URL"),
        ("security", lambda v: isinstance(v, dict), "an object"),
        ("usage", lambda v: isinstance(v, dict), "an object"),
    ]
    problems = [(key, f"must be {expected}") for key, check, expected in rules if key in data and not check(data[key])]
    usage = data.get("usage")
    if isinstance(usage, dict):
        for key in ("six_hour_token_limit", "weekly_token_limit", "max_context_tokens_per_chat"):
            if key in usage and not _is_int(usage[key], 0):
                problems.append((f"usage.{key}", "must be a whole number, 0 or more (0 = unlimited)"))
    security = data.get("security")
    if isinstance(security, dict):
        rate = security.get("rate_limit", {})
        for key in ("max_attempts", "window_seconds", "lockout_seconds"):
            if isinstance(rate, dict) and key in rate and not _is_int(rate[key], 1):
                problems.append((f"security.rate_limit.{key}", "must be a positive integer"))
    return problems


def _check_agents(data: Any) -> list[Problem]:
    agents = data.get("agents") if isinstance(data, dict) else None
    if not isinstance(agents, list):
        return [("agents", "must be a list")]
    if not agents:
        return [("agents", "is empty - there is no agent to chat with")]
    problems: list[Problem] = []
    seen: set[Any] = set()
    for index, agent in enumerate(agents):
        label = f"agents[{index}]"
        if not isinstance(agent, dict):
            problems.append((label, "must be an object"))
            continue
        for key in ("id", "label"):
            if not _is_text(agent.get(key)):
                problems.append((f"{label}.{key}", "must be a non-empty string"))
        if not _is_http_url(agent.get("url")):
            problems.append((f"{label}.url", "must be an http(s) URL"))
        if agent.get("id") in seen:
            problems.append((f"{label}.id", "duplicate agent id"))
        seen.add(agent.get("id"))
    return problems


def _check_bootstrap_admin(env: dict[str, str]) -> list[Problem]:
    email = env.get("BOOTSTRAP_ADMIN_EMAIL", "")
    if email and "@" not in email:
        return [("BOOTSTRAP_ADMIN_EMAIL", "must be an email address")]
    return []


def _check_smtp(env: dict[str, str]) -> list[Problem]:
    keys = ("SMTP_HOST", "SMTP_USERNAME", "SMTP_PASSWORD", "MAIL_FROM_ADDRESS")
    if not any(env.get(k) for k in keys):
        return [("-", "email is not configured - invites and verification codes can't be sent")]
    problems: list[Problem] = []
    if not env.get("SMTP_HOST"):
        problems.append(("SMTP_HOST", "is empty but other SMTP settings are set"))
    if not (env.get("MAIL_FROM_ADDRESS") or env.get("SMTP_USERNAME")):
        problems.append(("MAIL_FROM_ADDRESS", "is empty and there is no SMTP_USERNAME to send from"))
    port = env.get("SMTP_PORT", "587")
    if not (port.isdigit() and 0 < int(port) < 65536):
        problems.append(("SMTP_PORT", "must be a port number (1-65535)"))
    if env.get("MAIL_FROM_ADDRESS") and "@" not in env["MAIL_FROM_ADDRESS"]:
        problems.append(("MAIL_FROM_ADDRESS", "must be an email address"))
    if env.get("SMTP_USE_TLS", "true").lower() not in ("true", "false"):
        problems.append(("SMTP_USE_TLS", "must be true or false"))
    return problems


_ENV_CHECKS: dict[str, Callable[[dict[str, str]], list[Problem]]] = {
    "secret_bootstrap_admin.env": _check_bootstrap_admin,
    "secret_internal_api.env": lambda env: [],
    "secret_smtp.env": _check_smtp,
}


def _read_json(path: Path, name: str, issues: list[ConfigIssue]) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        issues.append(ConfigIssue(name, "-", f"file not found ({path})"))
    except (OSError, ValueError) as error:
        issues.append(ConfigIssue(name, "-", f"cannot be read as JSON: {error}"))
    return None


def collect_issues(settings: Settings) -> list[ConfigIssue]:
    """Blocking file reads; use collect_issues_async from request handlers."""
    issues: list[ConfigIssue] = []

    name = settings.config_path.name
    data = _read_json(settings.config_path, name, issues)
    if data is not None:
        if isinstance(data, dict):
            issues.extend(ConfigIssue(name, k, m) for k, m in _check_app(data))
        else:
            issues.append(ConfigIssue(name, "-", "top level must be a JSON object"))

    registry = settings.agents_registry_path
    agents = _read_json(registry, "agents registry", issues)
    if agents is not None:
        issues.extend(ConfigIssue(f"agents registry ({registry.name})", k, m) for k, m in _check_agents(agents))

    for file_name, check in _ENV_CHECKS.items():
        path = settings.secrets_dir / file_name
        if not path.exists():
            issues.append(ConfigIssue(file_name, "-", "file is missing (copy it from its .example)"))
            continue
        env = {k: (v or "").strip() for k, v in dotenv_values(path).items()}
        issues.extend(ConfigIssue(file_name, k, m) for k, m in check(env))
        issues.extend(
            ConfigIssue(file_name, key, "is still a placeholder value")
            for key, value in env.items()
            if value and _PLACEHOLDER.search(value)
        )
    return issues


async def collect_issues_async(settings: Settings) -> list[ConfigIssue]:
    return await asyncio.to_thread(collect_issues, settings)
