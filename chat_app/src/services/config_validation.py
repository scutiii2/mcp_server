"""Validates chat_app's configs/*.json and secrets/*.env without raising.

collect_issues() returns every problem it finds (unreadable file, bad JSON,
missing/mistyped key, value still a placeholder) as ConfigIssue rows for the
ConfigIssues page. Secret values are never put in a message - only the file
and key name - since the page is reachable before login.

install_config_guard() redirects every request to that page while any issue
exists; the mtime-keyed cache means editing a file clears the redirect on the
next request without a restart.
"""

import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from flask import Flask, redirect, request, url_for

from src.utils.config_loader import load_env_secrets, load_json_config

_EXEMPT_BLUEPRINTS = {"configissues", "internal"}

_PLACEHOLDER = re.compile(
    r"^(change[-_ ]?me|replace[-_ ]?me|your[-_ ].*|<.*>|x{3,}|todo|dev-insecure-key-change-me)$"
    r"|@example\.(com|org|net)$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ConfigIssue:
    file: str
    key: str
    message: str


def _is_pos_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _is_nonblank_str(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_http_url(value) -> bool:
    if not isinstance(value, str):
        return False
    parsed = urlparse(value)
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def _require(data: dict, key: str, check, expected: str) -> tuple[str, str] | None:
    if key not in data:
        return key, "missing"
    if not check(data[key]):
        return key, f"must be {expected}"
    return None


def _check_app(data):
    return [_require(data, "app_name", _is_nonblank_str, "a non-empty string")]


def _check_usage_limits(data):
    return [
        _require(data, key, _is_pos_int, "a positive integer")
        for key in ("six_hour_token_limit", "weekly_token_limit", "max_context_tokens_per_chat")
    ]


def _check_agents(data):
    agents = data.get("agents")
    if not isinstance(agents, list):
        return [("agents", "must be a list")]
    problems = []
    seen = set()
    for index, agent in enumerate(agents):
        label = f"agents[{index}]"
        if not isinstance(agent, dict):
            problems.append((label, "must be an object"))
            continue
        for field in ("id", "label"):
            if not _is_nonblank_str(agent.get(field)):
                problems.append((f"{label}.{field}", "must be a non-empty string"))
        if not _is_http_url(agent.get("url")):
            problems.append((f"{label}.url", "must be an http(s) URL"))
        if agent.get("id") in seen:
            problems.append((f"{label}.id", "duplicate agent id"))
        seen.add(agent.get("id"))
    return problems


def _is_bool(value) -> bool:
    return isinstance(value, bool)


def _is_list(value) -> bool:
    return isinstance(value, list)


def _is_dict(value) -> bool:
    return isinstance(value, dict)


def _is_nonneg_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _check_fingerprint(data):
    return [
        _require(data, "enabled", _is_bool, "true or false"),
        _require(data, "signals", _is_list, "a list"),
        _require(data, "new_device_behavior", _is_nonblank_str, "a non-empty string"),
        _require(data, "trust_duration_days", _is_pos_int, "a positive integer"),
    ]


def _check_headers(data):
    return [
        _require(data, "enabled", _is_bool, "true or false"),
        _require(data, "csrf_enabled", _is_bool, "true or false"),
        _require(data, "force_https", _is_bool, "true or false"),
        _require(data, "hsts_max_age", _is_nonneg_int, "a non-negative integer"),
        _require(data, "content_security_policy", _is_nonblank_str, "a non-empty string"),
    ]


def _check_ip_filter(data):
    problems = [
        _require(data, "enabled", _is_bool, "true or false"),
        _require(data, "allow_list", _is_list, "a list"),
        _require(data, "deny_list", _is_list, "a list"),
        _require(data, "geofencing", _is_dict, "an object"),
    ]
    geofencing = data.get("geofencing")
    if isinstance(geofencing, dict) and not _is_bool(geofencing.get("enabled")):
        problems.append(("geofencing.enabled", "must be true or false"))
    return problems


def _check_rate_limit(data):
    return [
        _require(data, "enabled", _is_bool, "true or false"),
        _require(data, "max_attempts", _is_pos_int, "a positive integer"),
        _require(data, "window_seconds", _is_pos_int, "a positive integer"),
        _require(data, "lockout_seconds", _is_pos_int, "a positive integer"),
        _require(data, "scope", _is_nonblank_str, "a non-empty string"),
    ]


_JSON_CHECKS = {
    "config_app.json": _check_app,
    "config_usage_limits.json": _check_usage_limits,
    "config_agents.json": _check_agents,
    "config_security_fingerprint.json": _check_fingerprint,
    "config_security_headers.json": _check_headers,
    "config_security_ip_filter.json": _check_ip_filter,
    "config_security_rate_limit.json": _check_rate_limit,
}


def _check_secret_app(env):
    key = env.get("SECRET_KEY", "")
    if not key:
        return [("SECRET_KEY", "is empty - the insecure dev fallback key is in use")]
    if len(key) < 16:
        return [("SECRET_KEY", "is too short (minimum 16 characters)")]
    return []


def _check_secret_internal_api(env):
    if not env.get("INTERNAL_API_TOKEN"):
        return [("INTERNAL_API_TOKEN", "is empty")]
    return []


def _check_secret_mcp(env):
    url = env.get("MCP_SERVER_URL", "")
    if url and not _is_http_url(url):
        return [("MCP_SERVER_URL", "must be an http(s) URL")]
    return []


def _check_secret_db(env):
    url = env.get("DATABASE_URL", "")
    if url and "://" not in url:
        return [("DATABASE_URL", "is not a valid database URL")]
    return []


def _check_secret_smtp(env):
    fields = ("SMTP_HOST", "SMTP_PORT", "SMTP_USERNAME", "SMTP_PASSWORD", "MAIL_FROM_ADDRESS")
    if not any(env.get(field) for field in fields):
        return []  # email deliberately unconfigured
    problems = []
    for field in ("SMTP_HOST", "MAIL_FROM_ADDRESS"):
        if not env.get(field):
            problems.append((field, "is empty but other SMTP settings are set"))
    port = env.get("SMTP_PORT", "")
    if not (port.isdigit() and 0 < int(port) < 65536):
        problems.append(("SMTP_PORT", "must be a port number (1-65535)"))
    if env.get("MAIL_FROM_ADDRESS") and "@" not in env["MAIL_FROM_ADDRESS"]:
        problems.append(("MAIL_FROM_ADDRESS", "must be an email address"))
    if env.get("SMTP_USE_TLS", "true").lower() not in ("true", "false"):
        problems.append(("SMTP_USE_TLS", "must be true or false"))
    return problems


def _check_secret_bootstrap_admin(env):
    email = env.get("BOOTSTRAP_ADMIN_EMAIL", "")
    if email and "@" not in email:
        return [("BOOTSTRAP_ADMIN_EMAIL", "must be an email address")]
    return []


_ENV_CHECKS = {
    "secret_app.env": _check_secret_app,
    "secret_internal_api.env": _check_secret_internal_api,
    "secret_mcp.env": _check_secret_mcp,
    "secret_db.env": _check_secret_db,
    "secret_smtp.env": _check_secret_smtp,
    "secret_bootstrap_admin.env": _check_secret_bootstrap_admin,
}


def _watched_paths(app_dir: Path) -> list[Path]:
    return [app_dir / "configs" / name for name in _JSON_CHECKS] + [
        app_dir / "secrets" / name for name in _ENV_CHECKS
    ]


def collect_issues(app_dir: Path) -> list[ConfigIssue]:
    issues: list[ConfigIssue] = []

    for name, check in _JSON_CHECKS.items():
        path = app_dir / "configs" / name
        try:
            data = load_json_config(path)
        except FileNotFoundError:
            issues.append(ConfigIssue(name, "-", "file is missing and has no .example to copy from"))
            continue
        except (OSError, ValueError) as error:
            issues.append(ConfigIssue(name, "-", f"cannot be read as JSON: {error}"))
            continue
        if not isinstance(data, dict):
            issues.append(ConfigIssue(name, "-", "top level must be a JSON object"))
            continue
        issues.extend(ConfigIssue(name, key, message) for key, message in filter(None, check(data)))

    for name, check in _ENV_CHECKS.items():
        path = app_dir / "secrets" / name
        env = {key: (value or "") for key, value in load_env_secrets(path).items()}
        if not path.exists():
            issues.append(ConfigIssue(name, "-", "file is missing and has no .example to copy from"))
            continue
        issues.extend(ConfigIssue(name, key, message) for key, message in check(env))
        for key, value in env.items():
            if value and _PLACEHOLDER.search(value.strip()):
                issues.append(ConfigIssue(name, key, "is still a placeholder value"))

    return issues


def install_config_guard(app: Flask, app_dir: Path) -> None:
    cache: dict = {"signature": None, "issues": []}

    def current_issues() -> list[ConfigIssue]:
        signature = tuple(
            path.stat().st_mtime_ns if path.exists() else None for path in _watched_paths(app_dir)
        )
        if signature != cache["signature"]:
            cache["issues"] = collect_issues(app_dir)
            # Re-stat: collect_issues may have just created files from .example.
            cache["signature"] = tuple(
                path.stat().st_mtime_ns if path.exists() else None for path in _watched_paths(app_dir)
            )
        return cache["issues"]

    app.config["CONFIG_ISSUES_PROVIDER"] = current_issues

    @app.before_request
    def _redirect_to_config_issues():
        if app.config.get("TESTING"):
            return None
        if request.endpoint == "static" or request.blueprint in _EXEMPT_BLUEPRINTS:
            return None
        if current_issues():
            return redirect(url_for("configissues.index"))
        return None
