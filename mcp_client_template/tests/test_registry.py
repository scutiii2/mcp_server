from __future__ import annotations

import contextlib
import json
import sys
from pathlib import Path
from typing import Any

import pytest

from mcp import types

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
    # Invoked by absolute file path, not "-m src._fixtures.reference_server":
    # a spawned subprocess resolves "-m" against its own cwd, which is
    # wherever pytest itself was launched from (the repo/worktree root per
    # this template's own convention) - not mcp_client_template/, so the
    # module wouldn't be found. An absolute path has no such dependency.
    fixture_path = Path(__file__).resolve().parent.parent / "src" / "_fixtures" / "reference_server.py"
    config_path = tmp_path / "config_servers.json"
    config_path.write_text(
        json.dumps(
            {
                "reference": {
                    "label": "Reference",
                    "description": "Dev fixture",
                    "transport": "stdio",
                    "command": sys.executable,
                    "args": [str(fixture_path)],
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
