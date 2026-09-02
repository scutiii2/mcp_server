"""Load and validate configs/config_servers.json into typed ServerConfig
objects.

Mirrors the shape of mcp_server/src/infra/app_config.py's ExtensionConfig,
generalized with an optional `auth` block - every configured server here
(including the main mcp_server itself) is symmetric, unlike mcp_server's
extensions.py, which distinguishes "our own tools" from "proxied tools"
because it is itself a server with tools of its own.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ConfigError(ValueError):
    """Raised for a malformed config_servers.json entry."""


@dataclass(frozen=True)
class AuthConfig:
    type: str  # "none" | "header" | "bearer_env"
    env_var: str | None = None
    header_name: str | None = None
    header_value: str | None = None


@dataclass(frozen=True)
class ServerConfig:
    id: str
    label: str
    description: str
    transport: str  # "stdio" | "http"
    url: str | None = None
    command: str | None = None
    args: list[str] | None = None
    auth: AuthConfig | None = None


_VALID_TRANSPORTS = {"stdio", "http"}
_VALID_AUTH_TYPES = {"none", "header", "bearer_env"}


def _build_auth(server_id: str, raw: dict[str, Any] | None) -> AuthConfig | None:
    if raw is None:
        return None
    auth_type = raw.get("type")
    if auth_type not in _VALID_AUTH_TYPES:
        raise ConfigError(f"{server_id!r}: auth.type must be one of {sorted(_VALID_AUTH_TYPES)}, got {auth_type!r}")
    if auth_type == "header" and not (raw.get("header_name") and raw.get("header_value")):
        raise ConfigError(f"{server_id!r}: auth.type 'header' requires header_name and header_value")
    if auth_type == "bearer_env" and not raw.get("env_var"):
        raise ConfigError(f"{server_id!r}: auth.type 'bearer_env' requires env_var")
    return AuthConfig(
        type=auth_type,
        env_var=raw.get("env_var"),
        header_name=raw.get("header_name"),
        header_value=raw.get("header_value"),
    )


def _build_server(server_id: str, raw: dict[str, Any]) -> ServerConfig:
    transport = raw.get("transport")
    if transport not in _VALID_TRANSPORTS:
        raise ConfigError(f"{server_id!r}: transport must be one of {sorted(_VALID_TRANSPORTS)}, got {transport!r}")

    label = raw.get("label")
    if not label:
        raise ConfigError(f"{server_id!r}: 'label' is required")
    description = raw.get("description", "")

    if transport == "http":
        url = raw.get("url")
        if not url:
            raise ConfigError(f"{server_id!r}: transport 'http' requires 'url'")
        if raw.get("command"):
            raise ConfigError(f"{server_id!r}: transport 'http' must not set 'command'")
        command, args = None, None
    else:
        command = raw.get("command")
        if not command:
            raise ConfigError(f"{server_id!r}: transport 'stdio' requires 'command'")
        if raw.get("url"):
            raise ConfigError(f"{server_id!r}: transport 'stdio' must not set 'url'")
        url = None
        args = raw.get("args", [])

    return ServerConfig(
        id=server_id,
        label=label,
        description=description,
        transport=transport,
        url=url,
        command=command,
        args=args,
        auth=_build_auth(server_id, raw.get("auth")),
    )


def load_servers_config(path: Path) -> dict[str, ServerConfig]:
    """Load and validate every entry in `path` (config_servers.json).

    Raises ConfigError for any entry missing a required field, using an
    unknown transport/auth type, or mixing fields from the wrong
    transport (e.g. an http entry with 'command' set). The whole file is
    validated eagerly on load - a bad entry anywhere fails loudly at
    startup rather than surfacing later as a confusing connect failure.
    """
    raw_data = json.loads(path.read_text(encoding="utf-8"))
    return {server_id: _build_server(server_id, raw) for server_id, raw in raw_data.items()}
