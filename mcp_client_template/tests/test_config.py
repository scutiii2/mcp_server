from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.config import AuthConfig, ConfigError, ServerConfig, load_servers_config


def _write(tmp_path: Path, data: dict) -> Path:
    path = tmp_path / "config_servers.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_loads_a_valid_http_entry(tmp_path: Path):
    path = _write(
        tmp_path,
        {
            "main": {
                "label": "Main MCP Server",
                "description": "The hub.",
                "transport": "http",
                "url": "http://127.0.0.1:8000/mcp",
            }
        },
    )

    servers = load_servers_config(path)

    assert servers == {
        "main": ServerConfig(
            id="main",
            label="Main MCP Server",
            description="The hub.",
            transport="http",
            url="http://127.0.0.1:8000/mcp",
            command=None,
            args=None,
            auth=None,
        )
    }


def test_loads_a_valid_stdio_entry_and_defaults_args_to_empty_list(tmp_path: Path):
    path = _write(
        tmp_path,
        {
            "reference": {
                "label": "Reference",
                "description": "Dev fixture.",
                "transport": "stdio",
                "command": "python",
            }
        },
    )

    servers = load_servers_config(path)

    assert servers["reference"].command == "python"
    assert servers["reference"].args == []
    assert servers["reference"].url is None


def test_missing_label_raises(tmp_path: Path):
    path = _write(tmp_path, {"main": {"transport": "http", "url": "http://x/mcp"}})

    with pytest.raises(ConfigError, match="'label' is required"):
        load_servers_config(path)


def test_unknown_transport_raises(tmp_path: Path):
    path = _write(tmp_path, {"main": {"label": "Main", "transport": "carrier-pigeon"}})

    with pytest.raises(ConfigError, match="transport must be one of"):
        load_servers_config(path)


def test_http_without_url_raises(tmp_path: Path):
    path = _write(tmp_path, {"main": {"label": "Main", "transport": "http"}})

    with pytest.raises(ConfigError, match="requires 'url'"):
        load_servers_config(path)


def test_http_with_command_raises(tmp_path: Path):
    path = _write(
        tmp_path,
        {"main": {"label": "Main", "transport": "http", "url": "http://x/mcp", "command": "python"}},
    )

    with pytest.raises(ConfigError, match="must not set 'command'"):
        load_servers_config(path)


def test_stdio_without_command_raises(tmp_path: Path):
    path = _write(tmp_path, {"reference": {"label": "Reference", "transport": "stdio"}})

    with pytest.raises(ConfigError, match="requires 'command'"):
        load_servers_config(path)


def test_auth_defaults_to_none_when_omitted(tmp_path: Path):
    path = _write(
        tmp_path, {"main": {"label": "Main", "transport": "http", "url": "http://x/mcp"}}
    )

    assert load_servers_config(path)["main"].auth is None


def test_auth_header_type_loads(tmp_path: Path):
    path = _write(
        tmp_path,
        {
            "main": {
                "label": "Main",
                "transport": "http",
                "url": "http://x/mcp",
                "auth": {"type": "header", "header_name": "X-Api-Key", "header_value": "secret"},
            }
        },
    )

    assert load_servers_config(path)["main"].auth == AuthConfig(
        type="header", header_name="X-Api-Key", header_value="secret"
    )


def test_auth_header_missing_header_value_raises(tmp_path: Path):
    path = _write(
        tmp_path,
        {
            "main": {
                "label": "Main",
                "transport": "http",
                "url": "http://x/mcp",
                "auth": {"type": "header", "header_name": "X-Api-Key"},
            }
        },
    )

    with pytest.raises(ConfigError, match="requires header_name and header_value"):
        load_servers_config(path)


def test_auth_bearer_env_loads(tmp_path: Path):
    path = _write(
        tmp_path,
        {
            "gmail": {
                "label": "Gmail",
                "transport": "http",
                "url": "https://example.invalid/mcp",
                "auth": {"type": "bearer_env", "env_var": "GMAIL_MCP_TOKEN"},
            }
        },
    )

    assert load_servers_config(path)["gmail"].auth == AuthConfig(type="bearer_env", env_var="GMAIL_MCP_TOKEN")


def test_auth_bearer_env_missing_env_var_raises(tmp_path: Path):
    path = _write(
        tmp_path,
        {"gmail": {"label": "Gmail", "transport": "http", "url": "https://x/mcp", "auth": {"type": "bearer_env"}}},
    )

    with pytest.raises(ConfigError, match="requires env_var"):
        load_servers_config(path)


def test_unknown_auth_type_raises(tmp_path: Path):
    path = _write(
        tmp_path,
        {"main": {"label": "Main", "transport": "http", "url": "http://x/mcp", "auth": {"type": "oauth2"}}},
    )

    with pytest.raises(ConfigError, match="auth.type must be one of"):
        load_servers_config(path)


def test_the_example_config_file_loads_without_error():
    """Guards against the example drifting out of sync with what
    load_servers_config() actually accepts - see README.md's usage
    section, which walks through this exact file."""
    example_path = Path(__file__).resolve().parent.parent / "configs" / "config_servers.json.example"

    servers = load_servers_config(example_path)

    assert set(servers) == {"main", "crafty", "gmail"}
    assert servers["main"].transport == "http"
    assert servers["crafty"].transport == "http"
    assert servers["gmail"].auth is not None
    assert servers["gmail"].auth.type == "bearer_env"
