# mcp_client_template Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `mcp_client_template/` — a standalone, copyable client library that connects to several MCP servers at once (the main `mcp_server` hub, other custom servers directly, and third-party servers like Gmail) and presents them as one merged, namespaced tool catalog.

**Architecture:** `McpClientRegistry` generalizes `mcp_server/src/infra/extensions.py`'s proven connect/namespace/merge/isolate pattern, but with no "our own tools" special case — every configured server, including `mcp_server` itself, is symmetric. Config-driven (`configs/config_servers.json`), async-first, with an optional `sync_wrapper.py` for synchronous host apps.

**Tech Stack:** Python >=3.11, `mcp==1.28.0` (pinned — matches every sibling project in this repo), pytest + anyio for tests (both already installed in the repo's shared `venv_mcp`).

**Spec:** [docs/superpowers/specs/2026-09-03-mcp-client-template-design.md](../specs/2026-09-03-mcp-client-template-design.md)

## Global Constraints

- `mcp==1.28.0` exactly — pinned, matches `mcp_server`, `mcp_server_ext`, and `crafty_mcp_server`'s own `pyproject.toml` files. Do not use a different version.
- Namespace separator is `"__"` (double underscore), exposed as `NAMESPACE_SEPARATOR` — matches `mcp_server/src/infra/extensions.py`'s own constant and reasoning (a single underscore can't be told apart from an ordinary word separator already used in tool names).
- Package import root is `src` (e.g. `from src.config import ...`), matching every sibling project's layout (`mcp_server/src`, `crafty_mcp_server/src`, `mcp_server_ext/src`).
- Run tests with the repo's existing shared venv: `venv_mcp/Scripts/python.exe -m pytest mcp_client_template/tests/<file> -v`, invoked from the repo root (`D:\User\Documents\Programming\Python\MCPServer`). Do not create a new venv for this work — `venv_mcp` already has `mcp==1.28.0`, `pytest`, and `anyio` installed (verified: `mcp` 1.28.0, `anyio` 4.14.2, `pytest` 9.1.1).
- `mcp_client_template` is a **library**, not a server — it has no `mcp.run(...)` entry point and no `[project.scripts]` in its `pyproject.toml`.
- Every commit uses `git add <specific files>` (never `git add -A`/`.`), and ends with:
  ```
  Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
  ```

---

## Task 1: Project scaffolding + `src/config.py`

**Files:**
- Create: `mcp_client_template/pyproject.toml`
- Create: `mcp_client_template/src/__init__.py`
- Create: `mcp_client_template/src/config.py`
- Create: `mcp_client_template/tests/__init__.py`
- Test: `mcp_client_template/tests/test_config.py`

**Interfaces:**
- Produces: `src.config.ConfigError(ValueError)`, `src.config.AuthConfig` (dataclass: `type: str`, `env_var: str | None = None`, `header_name: str | None = None`, `header_value: str | None = None`), `src.config.ServerConfig` (dataclass: `id: str`, `label: str`, `description: str`, `transport: str`, `url: str | None = None`, `command: str | None = None`, `args: list[str] | None = None`, `auth: AuthConfig | None = None`), `src.config.load_servers_config(path: Path) -> dict[str, ServerConfig]`.

- [ ] **Step 1: Create the project layout and `pyproject.toml`**

Create the directory structure:
```
mcp_client_template/
  pyproject.toml
  src/
    __init__.py
  tests/
    __init__.py
```

`mcp_client_template/pyproject.toml`:
```toml
[project]
name = "mcp-client-template"
version = "0.1.0"
description = "Template MCP client - aggregates tools from multiple MCP servers into one merged, namespaced catalog"
requires-python = ">=3.11"
dependencies = [
    "mcp==1.28.0",
]

[project.optional-dependencies]
dev = ["pytest>=8.0", "anyio"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src"]
```

`mcp_client_template/src/__init__.py` — empty file.

`mcp_client_template/tests/__init__.py` — empty file.

- [ ] **Step 2: Write the failing tests for `src/config.py`**

`mcp_client_template/tests/test_config.py`:
```python
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
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `venv_mcp/Scripts/python.exe -m pytest mcp_client_template/tests/test_config.py -v`
Expected: FAIL/ERROR — `src/config.py` doesn't exist yet, so the import fails (`ModuleNotFoundError: No module named 'src.config'`).

- [ ] **Step 4: Implement `src/config.py`**

`mcp_client_template/src/config.py`:
```python
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
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `venv_mcp/Scripts/python.exe -m pytest mcp_client_template/tests/test_config.py -v`
Expected: PASS (13 passed)

- [ ] **Step 6: Commit**

```bash
git add mcp_client_template/pyproject.toml mcp_client_template/src/__init__.py mcp_client_template/src/config.py mcp_client_template/tests/__init__.py mcp_client_template/tests/test_config.py
git commit -m "$(cat <<'EOF'
Scaffold mcp_client_template and add config loading

ServerConfig/AuthConfig plus load_servers_config() validate
config_servers.json eagerly at load time, so a malformed entry fails
loudly at startup instead of surfacing as a confusing connect error.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: `src/transports.py`

**Files:**
- Create: `mcp_client_template/src/transports.py`
- Test: `mcp_client_template/tests/test_transports.py`

**Interfaces:**
- Consumes: `src.config.ServerConfig`, `src.config.AuthConfig` (Task 1).
- Produces: `src.transports.AuthResolutionError(RuntimeError)`, `src.transports.resolve_headers(config: ServerConfig) -> dict[str, str]`, `src.transports.open_session(stack: AsyncExitStack, config: ServerConfig, timeout_seconds: float) -> ClientSession` (async).

- [ ] **Step 1: Write the failing tests for `resolve_headers`**

`mcp_client_template/tests/test_transports.py`:
```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `venv_mcp/Scripts/python.exe -m pytest mcp_client_template/tests/test_transports.py -v`
Expected: FAIL/ERROR — `src/transports.py` doesn't exist yet.

- [ ] **Step 3: Implement `src/transports.py`**

`mcp_client_template/src/transports.py`:
```python
"""Open a live, authenticated MCP session for one configured server.

Two responsibilities live here: resolving `ServerConfig.auth` into
whatever the wire actually needs (an HTTP header today), and opening the
transport itself (stdio subprocess or streamable HTTP) the same way
mcp_server/src/infra/extensions.py does, including the TCP-reachability
pre-check that module's docstring explains at length: a real HTTP connect
failure reaching streamablehttp_client directly corrupts anyio's
cancel-scope tree for the caller's task, so an unreachable host must
never be allowed to reach it in the first place.
"""

from __future__ import annotations

import asyncio
import os
from contextlib import AsyncExitStack
from datetime import timedelta
from urllib.parse import urlsplit

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.streamable_http import streamablehttp_client

from src.config import ServerConfig


class AuthResolutionError(RuntimeError):
    """Raised when a server's auth block names something not actually
    available at connect time - e.g. an unset environment variable."""


def resolve_headers(config: ServerConfig) -> dict[str, str]:
    """The extra HTTP headers `config`'s auth block requires, or {} for
    no auth. Only meaningful for transport 'http' - open_session never
    calls this for 'stdio'."""
    auth = config.auth
    if auth is None or auth.type == "none":
        return {}
    if auth.type == "header":
        return {auth.header_name: auth.header_value}  # type: ignore[dict-item]
    if auth.type == "bearer_env":
        value = os.environ.get(auth.env_var or "")
        if not value:
            raise AuthResolutionError(f"{config.id!r}: environment variable {auth.env_var!r} is not set")
        return {"Authorization": f"Bearer {value}"}
    raise AuthResolutionError(f"{config.id!r}: unknown auth type {auth.type!r}")


async def _check_tcp_reachable(url: str, timeout_seconds: float) -> None:
    """Raise a plain exception if `url`'s host:port won't accept a TCP
    connection - without ever calling streamablehttp_client. Plain
    asyncio, not anyio: this opens no anyio task group, so it can't
    corrupt one - it only answers "is anyone listening"; the real
    connection is opened separately right after this returns."""
    parsed = urlsplit(url)
    if parsed.hostname is None:
        raise ValueError(f"Server URL has no host: {url!r}")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    _reader, writer = await asyncio.wait_for(asyncio.open_connection(parsed.hostname, port), timeout=timeout_seconds)
    writer.close()
    try:
        await writer.wait_closed()
    except Exception:  # noqa: BLE001 - this was only ever a reachability probe
        pass


async def open_session(stack: AsyncExitStack, config: ServerConfig, timeout_seconds: float) -> ClientSession:
    """Open and initialize a session for `config`, registering every
    resource it opens on `stack` so the caller controls their lifetime.
    Does not call list_tools() - that's the caller's job (registry.py)."""
    if config.transport == "http":
        assert config.url is not None  # guaranteed by config.load_servers_config
        await _check_tcp_reachable(config.url, timeout_seconds)
        headers = resolve_headers(config)
        read_stream, write_stream, _get_session_id = await stack.enter_async_context(
            streamablehttp_client(config.url, headers=headers or None)
        )
    else:
        params = StdioServerParameters(command=config.command, args=config.args or [])
        read_stream, write_stream = await stack.enter_async_context(stdio_client(params))

    session = await stack.enter_async_context(
        ClientSession(read_stream, write_stream, read_timeout_seconds=timedelta(seconds=timeout_seconds))
    )
    await session.initialize()
    return session
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `venv_mcp/Scripts/python.exe -m pytest mcp_client_template/tests/test_transports.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add mcp_client_template/src/transports.py mcp_client_template/tests/test_transports.py
git commit -m "$(cat <<'EOF'
Add transports.py: auth header resolution + session opening

resolve_headers() turns a ServerConfig's auth block into the HTTP
headers the wire needs; open_session() opens stdio or streamable-HTTP
the same guarded way mcp_server/src/infra/extensions.py does, including
the TCP-reachability pre-check that avoids corrupting anyio's
cancel-scope tree on a real connect failure.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: `src/registry.py` (+ reference fixture)

**Files:**
- Create: `mcp_client_template/src/_fixtures/__init__.py`
- Create: `mcp_client_template/src/_fixtures/reference_server.py`
- Create: `mcp_client_template/src/registry.py`
- Test: `mcp_client_template/tests/test_registry.py`

**Interfaces:**
- Consumes: `src.config.ServerConfig`, `src.config.load_servers_config` (Task 1); `src.transports.open_session` (Task 2).
- Produces: `src.registry.NAMESPACE_SEPARATOR = "__"`, `src.registry.CONNECT_TIMEOUT_SECONDS = 10.0`, `src.registry.ServerStatus` (dataclass: `id: str`, `label: str`, `description: str`, `status: str`, `error: str | None = None`, `tools: list[str] = field(default_factory=list)`), `src.registry.McpClientRegistry` with `connect_all(config_path: Path) -> list[ServerStatus]` (async), `statuses() -> list[ServerStatus]`, `list_tools() -> list[types.Tool]` (async), `call_tool(name: str, arguments: dict[str, Any]) -> types.CallToolResult` (async), `aclose() -> None` (async).

- [ ] **Step 1: Add the reference stdio fixture**

`mcp_client_template/src/_fixtures/__init__.py` — empty file.

`mcp_client_template/src/_fixtures/reference_server.py`:
```python
"""A minimal, self-contained stdio MCP server - a reference fixture for
testing registry.py's connect/list/call path against a real MCP server
speaking the real protocol over real stdio, not a mock of it.

Same two trivial tools as mcp_server/src/_fixtures/reference_extension_server.py,
copied rather than imported so this template has no dependency on
mcp_server's own package.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

mcp = FastMCP(
    name="reference-server",
    instructions="Dev fixture for testing mcp_client_template. Not a real server.",
)


@mcp.tool()
def echo(text: str) -> str:
    """Return `text` unchanged."""
    return text


@mcp.tool()
def add(a: int, b: int) -> int:
    """Return a + b."""
    return a + b


if __name__ == "__main__":
    mcp.run(transport="stdio")
```

- [ ] **Step 2: Write the failing tests for `registry.py`**

`mcp_client_template/tests/test_registry.py`:
```python
from __future__ import annotations

import contextlib
import json
import sys
from pathlib import Path
from typing import Any

import pytest

from mcp import types
from mcp.server.fastmcp import FastMCP

from src import registry
from src.config import ServerConfig


# --- fakes for the mocked tests -------------------------------------------
# Same trick mcp_server/tests/test_extensions.py uses: fake stdio_client
# "yields" the fake session itself as the read half, and fake
# ClientSession(read, write) returns `read` unchanged. Patched at the
# src.transports level, since that's the module that actually imports
# these names - registry.py never imports them directly.


class _FakeSession:
    def __init__(self, tools: list[types.Tool], call_results: dict[str, types.CallToolResult] | None = None):
        self._tools = tools
        self._call_results = call_results or {}
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def __aenter__(self) -> "_FakeSession":
        # ClientSession is monkeypatched (below) to return this object
        # directly, and transports.open_session() enters it via
        # stack.enter_async_context(ClientSession(...)) - which requires
        # a real async context manager, hence these two methods.
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        return None

    async def initialize(self) -> None:
        return None

    async def list_tools(self) -> types.ListToolsResult:
        return types.ListToolsResult(tools=self._tools)

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> types.CallToolResult:
        self.calls.append((name, arguments))
        return self._call_results[name]


def _fake_stdio_client(session: _FakeSession):
    @contextlib.asynccontextmanager
    async def _cm(params: object):
        yield (session, None)

    return _cm


def _fake_stdio_client_raising(error: Exception):
    @contextlib.asynccontextmanager
    async def _cm(params: object):
        raise error
        yield  # pragma: no cover - unreachable, satisfies the generator protocol

    return _cm


def _fake_streamablehttp_client(session: _FakeSession):
    @contextlib.asynccontextmanager
    async def _cm(url: str, headers: dict | None = None):
        yield (session, None, None)

    return _cm


def _fake_streamablehttp_client_raising(error: Exception):
    @contextlib.asynccontextmanager
    async def _cm(url: str, headers: dict | None = None):
        raise error
        yield  # pragma: no cover - unreachable, satisfies the generator protocol

    return _cm


def _install_fake_stdio(monkeypatch: pytest.MonkeyPatch, session_or_error) -> None:
    from src import transports

    if isinstance(session_or_error, Exception):
        monkeypatch.setattr(transports, "stdio_client", _fake_stdio_client_raising(session_or_error))
    else:
        monkeypatch.setattr(transports, "stdio_client", _fake_stdio_client(session_or_error))
    monkeypatch.setattr(transports, "ClientSession", lambda read, write, **_kwargs: read)


def _install_fake_http(monkeypatch: pytest.MonkeyPatch, session_or_error) -> None:
    from src import transports

    if isinstance(session_or_error, Exception):
        monkeypatch.setattr(transports, "streamablehttp_client", _fake_streamablehttp_client_raising(session_or_error))
    else:
        monkeypatch.setattr(transports, "streamablehttp_client", _fake_streamablehttp_client(session_or_error))
    monkeypatch.setattr(transports, "ClientSession", lambda read, write, **_kwargs: read)
    monkeypatch.setattr(transports, "_check_tcp_reachable", lambda url, timeout_seconds: _noop())


async def _noop() -> None:
    return None


def _echo_tool() -> types.Tool:
    return types.Tool(name="echo", description="Echo text back", inputSchema={"type": "object", "properties": {}})


def _add_tool() -> types.Tool:
    return types.Tool(name="add", description="Add two numbers", inputSchema={"type": "object", "properties": {}})


def _stdio_config(**overrides: Any) -> ServerConfig:
    base = dict(id="reference", label="Reference", description="Dev fixture", transport="stdio", command="fake-command", args=[])
    base.update(overrides)
    return ServerConfig(**base)


def _http_config(**overrides: Any) -> ServerConfig:
    base = dict(id="remote", label="Remote", description="Dev fixture", transport="http", url="http://127.0.0.1:9000/mcp")
    base.update(overrides)
    return ServerConfig(**base)


# --- namespacing ------------------------------------------------------------


@pytest.mark.anyio
async def test_tools_are_registered_under_server_id_double_underscore_name(monkeypatch: pytest.MonkeyPatch):
    session = _FakeSession(tools=[_echo_tool(), _add_tool()])
    _install_fake_stdio(monkeypatch, session)
    monkeypatch.setattr(registry, "load_servers_config", lambda path: {"reference": _stdio_config()})

    reg = registry.McpClientRegistry()
    await reg.connect_all(Path("unused.json"))

    [status] = reg.statuses()
    assert sorted(status.tools) == ["reference__add", "reference__echo"]


# --- failure isolation -------------------------------------------------


@pytest.mark.anyio
async def test_a_broken_server_does_not_prevent_a_working_sibling(monkeypatch: pytest.MonkeyPatch):
    good_session = _FakeSession(tools=[_echo_tool()])

    def fake_stdio_client(params: Any):
        if params.command == "good-command":
            return _fake_stdio_client(good_session)(params)
        return _fake_stdio_client_raising(FileNotFoundError("no such file or directory"))(params)

    from src import transports

    monkeypatch.setattr(transports, "stdio_client", fake_stdio_client)
    monkeypatch.setattr(transports, "ClientSession", lambda read, write, **_kwargs: read)
    monkeypatch.setattr(
        registry,
        "load_servers_config",
        lambda path: {
            "broken": _stdio_config(id="broken", command="bad-command"),
            "good": _stdio_config(id="good", command="good-command"),
        },
    )

    reg = registry.McpClientRegistry()
    await reg.connect_all(Path("unused.json"))

    statuses = {status.id: status for status in reg.statuses()}
    assert statuses["broken"].status == "error"
    assert statuses["broken"].error
    assert statuses["good"].status == "connected"
    assert statuses["good"].tools == ["good__echo"]


# --- dispatch: list/call -------------------------------------------------


@pytest.mark.anyio
async def test_list_tools_merges_across_multiple_connected_servers(monkeypatch: pytest.MonkeyPatch):
    def fake_stdio_client(params: Any):
        session = _FakeSession(tools=[_echo_tool()]) if params.command == "a" else _FakeSession(tools=[_add_tool()])
        return _fake_stdio_client(session)(params)

    from src import transports

    monkeypatch.setattr(transports, "stdio_client", fake_stdio_client)
    monkeypatch.setattr(transports, "ClientSession", lambda read, write, **_kwargs: read)
    monkeypatch.setattr(
        registry,
        "load_servers_config",
        lambda path: {"one": _stdio_config(id="one", command="a"), "two": _stdio_config(id="two", command="b")},
    )

    reg = registry.McpClientRegistry()
    await reg.connect_all(Path("unused.json"))

    names = {tool.name for tool in await reg.list_tools()}
    assert names == {"one__echo", "two__add"}


@pytest.mark.anyio
async def test_list_tools_falls_back_to_last_known_tools_if_a_live_refetch_fails(monkeypatch: pytest.MonkeyPatch):
    session = _FakeSession(tools=[_echo_tool()])
    _install_fake_stdio(monkeypatch, session)
    monkeypatch.setattr(registry, "load_servers_config", lambda path: {"reference": _stdio_config()})

    reg = registry.McpClientRegistry()
    await reg.connect_all(Path("unused.json"))

    async def _raise() -> None:
        raise ConnectionError("upstream went away")

    monkeypatch.setattr(session, "list_tools", _raise)

    names = {tool.name for tool in await reg.list_tools()}
    assert "reference__echo" in names


@pytest.mark.anyio
async def test_call_tool_routes_a_namespaced_name_upstream(monkeypatch: pytest.MonkeyPatch):
    result = types.CallToolResult(content=[types.TextContent(type="text", text="hi")])
    session = _FakeSession(tools=[_echo_tool()], call_results={"echo": result})
    _install_fake_stdio(monkeypatch, session)
    monkeypatch.setattr(registry, "load_servers_config", lambda path: {"reference": _stdio_config()})

    reg = registry.McpClientRegistry()
    await reg.connect_all(Path("unused.json"))

    returned = await reg.call_tool("reference__echo", {"text": "hi"})

    assert returned is result
    assert session.calls == [("echo", {"text": "hi"})]  # upstream's own name, not the namespaced one


@pytest.mark.anyio
async def test_call_tool_raises_key_error_for_an_unknown_name(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(registry, "load_servers_config", lambda path: {})
    reg = registry.McpClientRegistry()
    await reg.connect_all(Path("unused.json"))

    with pytest.raises(KeyError):
        await reg.call_tool("nope__echo", {})


# --- http transport ---------------------------------------------------


@pytest.mark.anyio
async def test_http_server_connects_and_namespaces_its_tools(monkeypatch: pytest.MonkeyPatch):
    session = _FakeSession(tools=[_echo_tool()])
    _install_fake_http(monkeypatch, session)
    monkeypatch.setattr(registry, "load_servers_config", lambda path: {"remote": _http_config()})

    reg = registry.McpClientRegistry()
    await reg.connect_all(Path("unused.json"))

    [status] = reg.statuses()
    assert status.status == "connected"
    assert status.tools == ["remote__echo"]


@pytest.mark.anyio
async def test_a_broken_http_server_does_not_prevent_a_working_stdio_sibling(monkeypatch: pytest.MonkeyPatch):
    from src import transports

    good_session = _FakeSession(tools=[_echo_tool()])
    monkeypatch.setattr(transports, "stdio_client", _fake_stdio_client(good_session))
    monkeypatch.setattr(
        transports, "streamablehttp_client", _fake_streamablehttp_client_raising(ConnectionRefusedError("refused"))
    )
    monkeypatch.setattr(transports, "ClientSession", lambda read, write, **_kwargs: read)
    monkeypatch.setattr(transports, "_check_tcp_reachable", lambda url, timeout_seconds: _noop())
    monkeypatch.setattr(
        registry,
        "load_servers_config",
        lambda path: {"broken": _http_config(id="broken", url="http://unreachable/mcp"), "good": _stdio_config(id="good", command="good-command")},
    )

    reg = registry.McpClientRegistry()
    await reg.connect_all(Path("unused.json"))

    statuses = {status.id: status for status in reg.statuses()}
    assert statuses["broken"].status == "error"
    assert statuses["good"].status == "connected"
    assert statuses["good"].tools == ["good__echo"]


# --- the genuine, unmocked end-to-end path --------------------------------


@pytest.mark.anyio
async def test_real_fixture_server_end_to_end(tmp_path: Path):
    config_path = tmp_path / "config_servers.json"
    config_path.write_text(
        json.dumps(
            {
                "reference": {
                    "label": "Reference",
                    "description": "Dev fixture",
                    "transport": "stdio",
                    "command": sys.executable,
                    "args": ["-m", "src._fixtures.reference_server"],
                }
            }
        ),
        encoding="utf-8",
    )

    reg = registry.McpClientRegistry()
    try:
        await reg.connect_all(config_path)

        [status] = reg.statuses()
        assert status.status == "connected"
        assert sorted(status.tools) == ["reference__add", "reference__echo"]

        result = await reg.call_tool("reference__add", {"a": 2, "b": 3})
        assert result.structuredContent == {"result": 5}

        echoed = await reg.call_tool("reference__echo", {"text": "hello"})
        [content_block] = echoed.content
        assert content_block.text == "hello"
    finally:
        await reg.aclose()
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `venv_mcp/Scripts/python.exe -m pytest mcp_client_template/tests/test_registry.py -v`
Expected: FAIL/ERROR — `src/registry.py` doesn't exist yet.

- [ ] **Step 4: Implement `src/registry.py`**

`mcp_client_template/src/registry.py`:
```python
"""McpClientRegistry: connect to every server in config_servers.json,
merge their tools into one namespaced catalog, and dispatch calls to
whichever server owns a given name.

Generalizes mcp_server/src/infra/extensions.py's ExtensionRegistry: that
module treats "this server's own FastMCP tools" and "proxied tools" as
two different things, because it is itself an MCP server with tools of
its own. This registry has no tools of its own - every configured
server, including the main mcp_server, is symmetric: connect, namespace,
merge. See docs/superpowers/specs/2026-09-03-mcp-client-template-design.md
for the full design.
"""

from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mcp import types
from mcp.client.session import ClientSession

from src.config import ServerConfig, load_servers_config
from src.transports import open_session

# "__" rather than "_": several servers this connects to (mcp_server's own
# tools among them) already use single underscores as ordinary word
# separators, so a single underscore here couldn't be told apart from
# part of the server id or the upstream tool's own name.
NAMESPACE_SEPARATOR = "__"

# How long connecting to one server (open transport + initialize +
# list_tools) may take before it's recorded as failed - bounded so one
# hung server can't stall connect_all() indefinitely.
CONNECT_TIMEOUT_SECONDS = 10.0


@dataclass
class ServerStatus:
    """What statuses() reports for one configured server."""

    id: str
    label: str
    description: str
    status: str  # "connected" | "error"
    error: str | None = None
    tools: list[str] = field(default_factory=list)


def _namespace(server_id: str, tools: list[types.Tool]) -> list[types.Tool]:
    """Wrap `tools` (as returned by an upstream list_tools()) under their
    namespaced name for this server."""
    return [
        types.Tool(
            name=f"{server_id}{NAMESPACE_SEPARATOR}{tool.name}",
            description=tool.description,
            inputSchema=tool.inputSchema,
            outputSchema=tool.outputSchema,
            _meta=tool.meta,
            annotations=tool.annotations,
            icons=tool.icons,
        )
        for tool in tools
    ]


class McpClientRegistry:
    """Owns every live upstream connection for the life of the process.
    Connect once via connect_all(), then call list_tools()/call_tool()
    as needed, and aclose() on shutdown."""

    def __init__(self) -> None:
        # One AsyncExitStack per server - see ExtensionRegistry's __init__
        # in mcp_server/src/infra/extensions.py for why this can't be one
        # shared stack (no way to close a single entry from a shared LIFO
        # stack).
        self._stacks: dict[str, AsyncExitStack] = {}
        self._sessions: dict[str, ClientSession] = {}
        self._last_known_tools: dict[str, list[types.Tool]] = {}
        self._statuses: list[ServerStatus] = []

    def statuses(self) -> list[ServerStatus]:
        return list(self._statuses)

    async def connect_all(self, config_path: Path) -> list[ServerStatus]:
        """Connect to every server in `config_path`, isolated - one bad
        entry is recorded as an error status and never stops a sibling
        from connecting."""
        for server_id, config in load_servers_config(config_path).items():
            await self._connect_one(server_id, config)
        return self.statuses()

    async def _connect_one(self, server_id: str, config: ServerConfig) -> ServerStatus:
        local_stack = AsyncExitStack()
        try:
            session = await open_session(local_stack, config, CONNECT_TIMEOUT_SECONDS)
            listed = await session.list_tools()
        except Exception as error:  # noqa: BLE001 - one bad server must not block the others
            try:
                await local_stack.aclose()
            except Exception:  # noqa: BLE001 - a messy close must not escape a failed connect
                pass
            status = ServerStatus(
                id=server_id,
                label=config.label,
                description=config.description,
                status="error",
                error=str(error) or type(error).__name__,
            )
            self._statuses.append(status)
            return status

        opened = local_stack.pop_all()
        self._stacks[server_id] = opened
        namespaced_tools = _namespace(server_id, listed.tools)
        self._last_known_tools[server_id] = namespaced_tools
        self._sessions[server_id] = session
        status = ServerStatus(
            id=server_id,
            label=config.label,
            description=config.description,
            status="connected",
            tools=[tool.name for tool in namespaced_tools],
        )
        self._statuses.append(status)
        return status

    async def _live_tools_for(self, server_id: str, session: ClientSession) -> list[types.Tool]:
        try:
            listed = await session.list_tools()
        except Exception:  # noqa: BLE001 - one flaky server must not break the others
            return self._last_known_tools.get(server_id, [])
        namespaced_tools = _namespace(server_id, listed.tools)
        self._last_known_tools[server_id] = namespaced_tools
        return namespaced_tools

    async def list_tools(self) -> list[types.Tool]:
        """The merged catalog, fetched live from every connected server on
        each call - so a server's tools changing at runtime is reflected
        without a restart, the same reasoning as extensions.py's
        merged_list_tools()."""
        results = await asyncio.gather(
            *(self._live_tools_for(server_id, session) for server_id, session in self._sessions.items())
        )
        return [tool for tools in results for tool in tools]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> types.CallToolResult:
        """Route `name` (as returned by list_tools(), e.g. "main__ping")
        to whichever server owns it. Raises KeyError for a name that
        isn't currently connected - callers are expected to only call
        names they just got from list_tools()."""
        server_id, separator, upstream_name = name.partition(NAMESPACE_SEPARATOR)
        session = self._sessions.get(server_id) if separator else None
        if session is None:
            raise KeyError(f"No tool named {name!r} on any connected server")
        return await session.call_tool(upstream_name, arguments)

    async def aclose(self) -> None:
        """Close every open connection. One server failing to close
        cleanly must not stop the others."""
        for stack in self._stacks.values():
            try:
                await stack.aclose()
            except Exception:  # noqa: BLE001 - a messy shutdown must not block the rest
                pass
        self._stacks.clear()
        self._sessions.clear()
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `venv_mcp/Scripts/python.exe -m pytest mcp_client_template/tests/test_registry.py -v`
Expected: PASS (9 passed)

- [ ] **Step 6: Commit**

```bash
git add mcp_client_template/src/_fixtures/__init__.py mcp_client_template/src/_fixtures/reference_server.py mcp_client_template/src/registry.py mcp_client_template/tests/test_registry.py
git commit -m "$(cat <<'EOF'
Add McpClientRegistry: connect, merge, dispatch across N servers

Generalizes mcp_server/src/infra/extensions.py's connect/namespace/
merge/isolate pattern with no "our own tools" special case - every
configured server, including the main mcp_server, is symmetric. Tools
are fetched live on every list_tools() call so a server's schema
changing at runtime is reflected without a restart.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: `src/sync_wrapper.py`

**Files:**
- Create: `mcp_client_template/src/sync_wrapper.py`
- Test: `mcp_client_template/tests/test_sync_wrapper.py`

**Interfaces:**
- Consumes: `src.registry.McpClientRegistry`, `src.registry.ServerStatus` (Task 3).
- Produces: `src.sync_wrapper.SyncMcpClient` with `connect_all(config_path: Path) -> list[ServerStatus]`, `list_tools() -> list[types.Tool]`, `call_tool(name: str, arguments: dict[str, Any]) -> types.CallToolResult`, `close() -> None` — all synchronous/blocking, no `async`.

- [ ] **Step 1: Write the failing test**

`mcp_client_template/tests/test_sync_wrapper.py`:
```python
from __future__ import annotations

import json
import sys
from pathlib import Path

from src.sync_wrapper import SyncMcpClient


def _write_config(tmp_path: Path) -> Path:
    config_path = tmp_path / "config_servers.json"
    config_path.write_text(
        json.dumps(
            {
                "reference": {
                    "label": "Reference",
                    "description": "Dev fixture",
                    "transport": "stdio",
                    "command": sys.executable,
                    "args": ["-m", "src._fixtures.reference_server"],
                }
            }
        ),
        encoding="utf-8",
    )
    return config_path


def test_sync_client_connects_lists_and_calls_tools_from_a_plain_sync_test(tmp_path: Path):
    """No @pytest.mark.anyio here on purpose - the whole point of this
    module is that a synchronous caller never touches asyncio directly."""
    client = SyncMcpClient()
    try:
        statuses = client.connect_all(_write_config(tmp_path))
        assert [status.status for status in statuses] == ["connected"]

        names = {tool.name for tool in client.list_tools()}
        assert names == {"reference__echo", "reference__add"}

        result = client.call_tool("reference__add", {"a": 2, "b": 3})
        assert result.structuredContent == {"result": 5}
    finally:
        client.close()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `venv_mcp/Scripts/python.exe -m pytest mcp_client_template/tests/test_sync_wrapper.py -v`
Expected: FAIL/ERROR — `src/sync_wrapper.py` doesn't exist yet.

- [ ] **Step 3: Implement `src/sync_wrapper.py`**

`mcp_client_template/src/sync_wrapper.py`:
```python
"""Blocking wrapper around McpClientRegistry, for a synchronous host app
(e.g. a Flask process) that wants persistent connections rather than
opening a fresh connection per request. Optional - an async host can use
McpClientRegistry directly and skip this module entirely.

One background thread owns one long-lived event loop; the registry and
every connection it holds live entirely on that thread. Each public
method here blocks the calling thread until the corresponding coroutine
finishes on the background loop - asyncio.run_coroutine_threadsafe() is
built exactly for handing a coroutine to a loop running on another
thread and waiting for its result.
"""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from typing import Any

from mcp import types

from src.registry import McpClientRegistry, ServerStatus


class SyncMcpClient:
    def __init__(self) -> None:
        self._loop = asyncio.new_event_loop()
        self._registry = McpClientRegistry()
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True)
        self._thread.start()

    def _run(self, coro: Any) -> Any:
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result()

    def connect_all(self, config_path: Path) -> list[ServerStatus]:
        return self._run(self._registry.connect_all(config_path))

    def list_tools(self) -> list[types.Tool]:
        return self._run(self._registry.list_tools())

    def call_tool(self, name: str, arguments: dict[str, Any]) -> types.CallToolResult:
        return self._run(self._registry.call_tool(name, arguments))

    def close(self) -> None:
        """Close every connection and stop the background loop/thread.
        Safe to call once - not idempotent, matching aclose()'s own
        single-shutdown contract in registry.py."""
        self._run(self._registry.aclose())
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=5)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `venv_mcp/Scripts/python.exe -m pytest mcp_client_template/tests/test_sync_wrapper.py -v`
Expected: PASS (1 passed)

- [ ] **Step 5: Commit**

```bash
git add mcp_client_template/src/sync_wrapper.py mcp_client_template/tests/test_sync_wrapper.py
git commit -m "$(cat <<'EOF'
Add SyncMcpClient: optional blocking wrapper for sync host apps

A background thread owns one event loop and the registry's persistent
connections; connect_all()/list_tools()/call_tool() block the caller
via run_coroutine_threadsafe(). Lets a synchronous app (Flask, etc.)
keep connections alive across requests instead of reconnecting per
call, without going fully async itself.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Example config + README

**Files:**
- Create: `mcp_client_template/configs/config_servers.json.example`
- Create: `mcp_client_template/README.md`
- Modify: `mcp_client_template/tests/test_config.py`

**Interfaces:**
- Consumes: `src.config.load_servers_config` (Task 1).

- [ ] **Step 1: Write the failing test that the example config loads cleanly**

Append to `mcp_client_template/tests/test_config.py`:
```python


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
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `venv_mcp/Scripts/python.exe -m pytest mcp_client_template/tests/test_config.py -v`
Expected: FAIL — `configs/config_servers.json.example` doesn't exist yet (`FileNotFoundError`).

- [ ] **Step 3: Create the example config**

`mcp_client_template/configs/config_servers.json.example`:
```json
{
  "main": {
    "label": "Main MCP Server",
    "description": "This repo's own mcp_server hub - its built-in tools plus anything it proxies from its own extensions.",
    "transport": "http",
    "url": "http://127.0.0.1:8000/mcp"
  },
  "crafty": {
    "label": "Crafty (direct)",
    "description": "crafty_mcp_server reached directly over HTTP, bypassing mcp_server's own extension proxy.",
    "transport": "http",
    "url": "http://127.0.0.1:9100/mcp"
  },
  "gmail": {
    "label": "Gmail",
    "description": "Placeholder for a real Gmail MCP server - replace url with the real endpoint and set GMAIL_MCP_TOKEN before connecting.",
    "transport": "http",
    "url": "https://example.invalid/mcp",
    "auth": {
      "type": "bearer_env",
      "env_var": "GMAIL_MCP_TOKEN"
    }
  }
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `venv_mcp/Scripts/python.exe -m pytest mcp_client_template/tests/test_config.py -v`
Expected: PASS (14 passed)

- [ ] **Step 5: Run the full test suite**

Run: `venv_mcp/Scripts/python.exe -m pytest mcp_client_template/tests -v`
Expected: PASS (all tests across test_config.py, test_transports.py, test_registry.py, test_sync_wrapper.py)

- [ ] **Step 6: Write the README**

`mcp_client_template/README.md`:
```markdown
# mcp_client_template

A minimal, standalone MCP *client* - a template to copy when building an
app that needs to pull tools from several MCP servers at once: this
repo's own `mcp_server` hub, other custom servers reached directly
(`crafty_mcp_server`, a copy of `mcp_server_ext`), and ordinary
third-party MCP servers (Gmail, or anything else). Not wired into
anything itself: no other project in this repo imports or depends on
this folder.

It's the client-side counterpart to `mcp_server_ext/` (a template for
building a new MCP *server*) and generalizes the aggregation pattern
already proven in
[`mcp_server/src/infra/extensions.py`](../mcp_server/src/infra/extensions.py) -
connect out to N servers, merge their tool lists under a namespaced
name, dispatch calls by namespace, isolate each server's failures from
the others. The difference: this has no tools of its own, so every
configured server - including `mcp_server` itself - is symmetric.

## What's here

- `src/config.py` - loads and validates `configs/config_servers.json`.
- `src/transports.py` - opens a session for one server (stdio or HTTP),
  resolving its `auth` block into HTTP headers.
- `src/registry.py` - `McpClientRegistry`: connects to every configured
  server, merges their tools into one namespaced catalog, dispatches
  calls. Async.
- `src/sync_wrapper.py` - `SyncMcpClient`: optional blocking wrapper
  around `McpClientRegistry` for a synchronous host app.
- `src/_fixtures/reference_server.py` - a trivial stdio server (`echo`,
  `add`) used only by this template's own tests.

## Configuring servers

Copy `configs/config_servers.json.example` to `configs/config_servers.json`
and edit it. Three examples are included, one per category:

- **`main`** - this repo's own `mcp_server`, reached over HTTP the same
  way `chat_app` does today.
- **`crafty`** - a custom server (`crafty_mcp_server`) reached *directly*
  over HTTP, bypassing `mcp_server`'s own extension proxy. Point this at
  a copy of `mcp_server_ext` the same way.
- **`gmail`** - a placeholder for a "normal" third-party MCP server.
  Replace `url` with the real endpoint; `auth.type: "bearer_env"` reads
  the bearer token from the named environment variable at connect time
  (never store the token in the config file itself).

Each entry is either `"transport": "http"` (needs `url`) or
`"transport": "stdio"` (needs `command`, optionally `args`) - never both.
The optional `auth` block supports three types:

| `type`        | Extra fields                    | Effect                                            |
|---------------|----------------------------------|----------------------------------------------------|
| `none`        | (default if `auth` is omitted)   | No extra headers.                                  |
| `header`      | `header_name`, `header_value`    | A fixed extra header (e.g. a static API key).      |
| `bearer_env`  | `env_var`                        | `Authorization: Bearer <value of that env var>`.   |

A malformed entry raises `ConfigError` as soon as `load_servers_config()`
runs - a bad config fails loudly at startup rather than as a confusing
connect failure later.

## Using it (async)

```python
import asyncio
from pathlib import Path

from src.registry import McpClientRegistry

async def main() -> None:
    registry = McpClientRegistry()
    await registry.connect_all(Path("configs/config_servers.json"))

    for tool in await registry.list_tools():
        print(tool.name)  # e.g. "main__ping_host", "crafty__crafty_world_start"

    result = await registry.call_tool("crafty__crafty_world_list", {})
    print(result.structuredContent)

    await registry.aclose()

asyncio.run(main())
```

## Using it (sync host apps)

```python
from pathlib import Path
from src.sync_wrapper import SyncMcpClient

client = SyncMcpClient()
client.connect_all(Path("configs/config_servers.json"))
tools = client.list_tools()
result = client.call_tool("main__ping_host", {"host": "example.com"})
client.close()
```

Prefer this over reconnecting per call (the way `chat_app`'s current
single-server client does) whenever the host app is synchronous but
still wants persistent connections - especially important for stdio
subprocess servers, where reconnecting per call means respawning a
process every time.

## Tests

```
venv_mcp/Scripts/python.exe -m pytest mcp_client_template/tests -v
```

(from the repo root, using the repo's shared `venv_mcp` - see this
template's `pyproject.toml` for the exact dependency versions if you're
setting up a standalone venv for a copy of this folder elsewhere.)

## Not in this template (yet)

- Runtime add/remove-server routes - `mcp_server`'s own `/extensions`
  endpoints already cover that for its own extensions; this template is
  a library, not an admin surface.
- Real OAuth token-refresh flows - the `auth` block is shaped so this
  can be added later (a fourth `auth.type`) without a redesign.

See
[`docs/superpowers/specs/2026-09-03-mcp-client-template-design.md`](../docs/superpowers/specs/2026-09-03-mcp-client-template-design.md)
for the full design rationale.
```

- [ ] **Step 7: Commit**

```bash
git add mcp_client_template/configs/config_servers.json.example mcp_client_template/README.md mcp_client_template/tests/test_config.py
git commit -m "$(cat <<'EOF'
Add example config and README for mcp_client_template

Three worked config_servers.json entries covering the three server
categories the template targets: the main mcp_server hub, a custom
server reached directly, and a third-party server (Gmail) needing a
bearer token from an environment variable.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```
