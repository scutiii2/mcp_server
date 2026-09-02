from __future__ import annotations

import pytest

from src.config import AuthConfig, ServerConfig
from src.transports import AuthResolutionError, resolve_headers


def _server(auth: AuthConfig | None) -> ServerConfig:
    return ServerConfig(
        id="main", label="Main", description="", transport="http", url="http://x/mcp", auth=auth
    )


def test_no_auth_block_returns_empty_headers():
    assert resolve_headers(_server(None)) == {}


def test_auth_type_none_returns_empty_headers():
    assert resolve_headers(_server(AuthConfig(type="none"))) == {}


def test_auth_type_header_returns_the_fixed_header():
    config = _server(AuthConfig(type="header", header_name="X-Api-Key", header_value="secret"))

    assert resolve_headers(config) == {"X-Api-Key": "secret"}


def test_auth_type_bearer_env_reads_the_env_var(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("GMAIL_MCP_TOKEN", "tok-123")
    config = _server(AuthConfig(type="bearer_env", env_var="GMAIL_MCP_TOKEN"))

    assert resolve_headers(config) == {"Authorization": "Bearer tok-123"}


def test_auth_type_bearer_env_raises_when_env_var_unset(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("GMAIL_MCP_TOKEN", raising=False)
    config = _server(AuthConfig(type="bearer_env", env_var="GMAIL_MCP_TOKEN"))

    with pytest.raises(AuthResolutionError, match="GMAIL_MCP_TOKEN"):
        resolve_headers(config)


def test_unknown_auth_type_raises():
    # Bypasses config.py's own validation on purpose, to prove
    # resolve_headers has its own defense too.
    config = _server(AuthConfig(type="oauth2"))

    with pytest.raises(AuthResolutionError, match="unknown auth type"):
        resolve_headers(config)
