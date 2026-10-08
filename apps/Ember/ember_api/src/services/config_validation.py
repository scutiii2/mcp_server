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
import ipaddress
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
from dotenv import dotenv_values

from src.config import Settings
from src.utils.config_loader import load_env_secrets

_PLACEHOLDER = re.compile(
    r"^(change[-_ ]?me|replace[-_ ]?me|your[-_ ].*|<.*>|x{3,}|todo)$|@example\.(com|org|net)$",
    re.IGNORECASE,
)


ERROR = "error"  # broken or won't work
WARNING = "warning"  # runs, but risky or incomplete


@dataclass(frozen=True)
class ConfigIssue:
    file: str
    key: str
    message: str
    severity: str = ERROR


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
        ("require_email_verification", lambda v: isinstance(v, bool), "true or false"),
        ("agents_registry_path", _is_text, "a non-empty string"),
        ("agents_registry_url", _is_http_url, "an http(s) URL"),
        ("mcp_server_url", _is_http_url, "an http(s) URL"),
        ("security", lambda v: isinstance(v, dict), "an object"),
        ("usage", lambda v: isinstance(v, dict), "an object"),
        ("backup", lambda v: isinstance(v, dict), "an object"),
    ]
    problems = [(key, f"must be {expected}") for key, check, expected in rules if key in data and not check(data[key])]
    usage = data.get("usage")
    if isinstance(usage, dict):
        for key in ("six_hour_token_limit", "weekly_token_limit", "max_context_tokens_per_chat"):
            if key in usage and not _is_int(usage[key], 0):
                problems.append((f"usage.{key}", "must be a whole number, 0 or more (0 = unlimited)"))
    backup = data.get("backup")
    if isinstance(backup, dict):
        if "enabled" in backup and not isinstance(backup["enabled"], bool):
            problems.append(("backup.enabled", "must be true or false"))
        for key in ("keep", "every_hours"):
            if key in backup and not _is_int(backup[key], 1):
                problems.append((f"backup.{key}", "must be a positive integer"))
    security = data.get("security")
    if isinstance(security, dict):
        rate = security.get("rate_limit", {})
        for key in ("max_attempts", "window_seconds", "lockout_seconds"):
            if isinstance(rate, dict) and key in rate and not _is_int(rate[key], 1):
                problems.append((f"security.rate_limit.{key}", "must be a positive integer"))
    return problems


def _is_local_host(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host.strip("[]")).is_loopback
    except ValueError:
        return False


def _check_deployment(settings: Settings) -> list[Problem]:
    """What is fine on a developer's machine but not on a server: these only
    warn, because ember_api cannot tell which one this is."""
    problems: list[Problem] = []
    if not settings.cookie_secure and not _is_local_host(settings.host):
        problems.append(
            (
                "cookie_secure",
                f"is false while host is {settings.host!r}, which other machines can reach: "
                "the session cookie can travel unencrypted. Serve ember over HTTPS and set it to true",
            )
        )
    if settings.cookie_secure and settings.security.hsts_max_age == 0:
        problems.append(
            (
                "security.headers.hsts_max_age",
                "is 0 while cookie_secure is on: browsers are not told to insist on HTTPS. Set it, for example, to 31536000",
            )
        )
    if not settings.backup.enabled:
        problems.append(("backup.enabled", "is false: the database is not backed up automatically"))
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


def _check_internal_api(env: dict[str, str]) -> list[Problem]:
    if not env.get("INTERNAL_API_TOKEN"):
        return [
            (
                "INTERNAL_API_TOKEN",
                "is empty: mcp_server and ai_agent accept requests from anything that can reach them. "
                "Set the same token in each project's .env",
            )
        ]
    return []


def _check_bootstrap_admin(env: dict[str, str]) -> list[Problem]:
    email = env.get("BOOTSTRAP_ADMIN_EMAIL", "")
    if email and "@" not in email:
        return [("BOOTSTRAP_ADMIN_EMAIL", "must be an email address")]
    return []


def _smtp_in_use(env: dict[str, str]) -> bool:
    return any(env.get(k) for k in ("SMTP_HOST", "SMTP_USERNAME", "SMTP_PASSWORD", "MAIL_FROM_ADDRESS"))


def _warn_smtp_unset(env: dict[str, str]) -> list[Problem]:
    if _smtp_in_use(env):
        return []
    return [("-", "email is not configured - invites and verification codes can't be sent")]


def _check_smtp(env: dict[str, str]) -> list[Problem]:
    if not _smtp_in_use(env):
        return []
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


_ENV_CHECKS: tuple[Callable[[dict[str, str]], list[Problem]], ...] = (_check_bootstrap_admin, _check_smtp)

# What in .env only warrants a warning.
_ENV_WARNINGS: tuple[Callable[[dict[str, str]], list[Problem]], ...] = (_check_internal_api, _warn_smtp_unset)


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
    issues.extend(ConfigIssue(name, k, m, WARNING) for k, m in _check_deployment(settings))

    # With a registry URL the file is not used; the async variant checks the URL.
    if not settings.agents_registry_url:
        registry = settings.agents_registry_path
        agents = _read_json(registry, "agents registry", issues)
        if agents is not None:
            issues.extend(ConfigIssue(f"agents registry ({registry.name})", k, m) for k, m in _check_agents(agents))

    env_name = settings.env_path.name
    if not settings.env_path.exists():
        issues.append(ConfigIssue(env_name, "-", "file is missing (copy it from .env.example)"))
        return issues
    env = {k: (v or "").strip() for k, v in dotenv_values(settings.env_path).items()}
    for check in _ENV_CHECKS:
        issues.extend(ConfigIssue(env_name, k, m) for k, m in check(env))
    for check in _ENV_WARNINGS:
        issues.extend(ConfigIssue(env_name, k, m, WARNING) for k, m in check(env))
    issues.extend(
        ConfigIssue(env_name, key, "is still a placeholder value", WARNING)
        for key, value in env.items()
        if value and _PLACEHOLDER.search(value)
    )
    return issues


async def _registry_url_issues(settings: Settings) -> list[ConfigIssue]:
    """Fetches agents_registry_url once and checks what comes back."""
    url = settings.agents_registry_url
    name = "agents registry (URL)"
    token = (await asyncio.to_thread(load_env_secrets, settings.env_path)).get("INTERNAL_API_TOKEN")
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(3.0)) as client:
            response = await client.get(url, headers={"X-Internal-Token": token} if token else {})
        response.raise_for_status()
        data = response.json()
    except (httpx.HTTPError, ValueError) as error:
        # The error text can name the URL but never carries the token.
        return [ConfigIssue(name, "agents_registry_url", f"could not be read: {error}")]
    return [ConfigIssue(name, k, m) for k, m in _check_agents(data)]


async def collect_issues_async(settings: Settings) -> list[ConfigIssue]:
    issues = await asyncio.to_thread(collect_issues, settings)
    if settings.agents_registry_url:
        issues.extend(await _registry_url_issues(settings))
    return issues
