"""Tests for infra/extensions.py, the proxy/aggregation engine.

Mostly mocked: stdio_client and ClientSession are replaced with fakes so
namespacing and failure isolation can be checked fast, without spawning a
process per test. The one thing a mock can't prove is that this module
actually speaks the real MCP client protocol correctly against a real
process - which is the highest-risk part of this mechanism - so
test_real_fixture_server_end_to_end below spawns the real reference
fixture (src/_fixtures/reference_extension_server.py) and
drives the genuine connect/list/call path against it.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import sys
from pathlib import Path
from typing import Any

import pytest

from mcp import types
from mcp.server.fastmcp import FastMCP

from src.infra import extensions
from src.infra.app_config import ExtensionConfig


# --- fakes for the mocked tests ------------------------------------------
# ExtensionRegistry._open_and_list only ever does two things with the SDK:
# `stdio_client(params)` to get a (read, write) pair, then
# `ClientSession(read, write)` to wrap it. Faking both lets a test drive
# connect_all() through its real code path - real timeout handling, real
# per-extension isolation, real namespacing - without a subprocess.
#
# The trick: fake stdio_client "yields" the fake session itself as the
# `read` half, and fake ClientSession(read, write) just returns `read`
# unchanged. ExtensionRegistry never inspects what stdio_client/
# ClientSession hand back beyond passing them straight through, so this
# is indistinguishable from the real thing as far as the code under test
# can tell.


class _FakeSession:
    def __init__(self, tools: list[types.Tool], call_results: dict[str, types.CallToolResult] | None = None):
        self._tools = tools
        self._call_results = call_results or {}
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def __aenter__(self) -> "_FakeSession":
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


def _install_fake_connection(monkeypatch: pytest.MonkeyPatch, session_or_error) -> None:
    """Point extensions.stdio_client/ClientSession at one fake connection
    outcome. Used when a test only configures a single extension."""
    if isinstance(session_or_error, Exception):
        monkeypatch.setattr(extensions, "stdio_client", _fake_stdio_client_raising(session_or_error))
    else:
        monkeypatch.setattr(extensions, "stdio_client", _fake_stdio_client(session_or_error))
    # ClientSession(read, write) -> read (the fake session smuggled through
    # stdio_client's yield) - see the module comment above.
    monkeypatch.setattr(extensions, "ClientSession", lambda read, write: read)


# Same trick as _fake_stdio_client above, for the http transport:
# streamablehttp_client's __aenter__ yields a 3-tuple (read, write,
# get_session_id) rather than stdio_client's 2-tuple, so the fake session
# is smuggled through as the first element and the other two are ignored,
# same as _open_and_list itself discards the third.


def _fake_streamablehttp_client(session: _FakeSession):
    @contextlib.asynccontextmanager
    async def _cm(url: str):
        yield (session, None, None)

    return _cm


def _fake_streamablehttp_client_raising(error: Exception):
    @contextlib.asynccontextmanager
    async def _cm(url: str):
        raise error
        yield  # pragma: no cover - unreachable, satisfies the generator protocol

    return _cm


def _install_fake_http_connection(monkeypatch: pytest.MonkeyPatch, session_or_error) -> None:
    if isinstance(session_or_error, Exception):
        monkeypatch.setattr(extensions, "streamablehttp_client", _fake_streamablehttp_client_raising(session_or_error))
    else:
        monkeypatch.setattr(extensions, "streamablehttp_client", _fake_streamablehttp_client(session_or_error))
    monkeypatch.setattr(extensions, "ClientSession", lambda read, write: read)


def _echo_tool() -> types.Tool:
    return types.Tool(name="echo", description="Echo text back", inputSchema={"type": "object", "properties": {}})


def _add_tool() -> types.Tool:
    return types.Tool(name="add", description="Add two numbers", inputSchema={"type": "object", "properties": {}})


def _config(**overrides: Any) -> ExtensionConfig:
    base = dict(id="reference", label="Reference", description="Dev fixture", command="fake-command", args=[])
    base.update(overrides)
    return ExtensionConfig(**base)


# --- namespacing -----------------------------------------------------------


@pytest.mark.anyio
async def test_tools_are_registered_under_extension_id_double_underscore_name(monkeypatch: pytest.MonkeyPatch):
    """The property the whole feature depends on: a tool named `echo` from
    the extension `reference` must show up as `reference__echo`, not
    `echo` - otherwise two extensions offering the same tool name (or an
    extension colliding with one of this server's own tools) would
    silently shadow each other."""
    session = _FakeSession(tools=[_echo_tool(), _add_tool()])
    _install_fake_connection(monkeypatch, session)

    registry = extensions.ExtensionRegistry()
    monkeypatch.setattr(extensions, "load_extensions_config", lambda path: {"reference": _config()})
    await registry.connect_all(Path("unused.json"))

    names = {tool.name for tool in registry.proxied_tool_definitions()}
    assert names == {"reference__echo", "reference__add"}
    assert registry.is_proxied("reference__echo")
    assert not registry.is_proxied("echo")


@pytest.mark.anyio
async def test_connected_status_lists_the_namespaced_tool_names(monkeypatch: pytest.MonkeyPatch):
    session = _FakeSession(tools=[_echo_tool()])
    _install_fake_connection(monkeypatch, session)
    monkeypatch.setattr(extensions, "load_extensions_config", lambda path: {"reference": _config()})

    registry = extensions.ExtensionRegistry()
    await registry.connect_all(Path("unused.json"))

    [status] = registry.statuses()
    assert status == extensions.ExtensionStatus(
        id="reference",
        label="Reference",
        description="Dev fixture",
        status="connected",
        error=None,
        tools=["reference__echo"],
    )


@pytest.mark.anyio
async def test_proxied_tool_definition_preserves_meta_annotations_and_icons(monkeypatch: pytest.MonkeyPatch):
    """Regression test: meta/annotations/icons were silently dropped when
    building _ProxiedTool.definition, which would break any feature (like
    keyword-based tool filtering) that relies on an extension's own
    declared metadata surviving the proxy."""
    tool = types.Tool(
        name="echo",
        description="Echo text back",
        inputSchema={"type": "object", "properties": {}},
        _meta={"keywords": ["echo", "repeat"]},
        annotations=types.ToolAnnotations(title="Echo"),
        icons=[types.Icon(src="https://example.com/icon.png")],
    )
    session = _FakeSession(tools=[tool])
    _install_fake_connection(monkeypatch, session)
    monkeypatch.setattr(extensions, "load_extensions_config", lambda path: {"reference": _config()})

    registry = extensions.ExtensionRegistry()
    await registry.connect_all(Path("unused.json"))

    [proxied] = registry.proxied_tool_definitions()
    assert proxied.meta == {"keywords": ["echo", "repeat"]}
    assert proxied.annotations == types.ToolAnnotations(title="Echo")
    assert proxied.icons == [types.Icon(src="https://example.com/icon.png")]


# --- failure isolation -------------------------------------------------


@pytest.mark.anyio
async def test_a_broken_extension_does_not_prevent_a_working_sibling(monkeypatch: pytest.MonkeyPatch):
    """The required property: one bad `command` must not stop a different,
    correctly configured extension from connecting."""
    good_session = _FakeSession(tools=[_echo_tool()])

    def fake_stdio_client(params: Any):
        if params.command == "good-command":
            return _fake_stdio_client(good_session)(params)
        return _fake_stdio_client_raising(FileNotFoundError("no such file or directory"))(params)

    monkeypatch.setattr(extensions, "stdio_client", fake_stdio_client)
    monkeypatch.setattr(extensions, "ClientSession", lambda read, write: read)
    monkeypatch.setattr(
        extensions,
        "load_extensions_config",
        lambda path: {
            "broken": _config(id="broken", command="bad-command"),
            "good": _config(id="good", command="good-command"),
        },
    )

    registry = extensions.ExtensionRegistry()
    await registry.connect_all(Path("unused.json"))

    statuses = {status.id: status for status in registry.statuses()}
    assert statuses["broken"].status == "error"
    assert statuses["broken"].error  # a message is present
    assert statuses["broken"].tools == []
    assert statuses["good"].status == "connected"
    assert statuses["good"].tools == ["good__echo"]


@pytest.mark.anyio
async def test_a_broken_extension_does_not_prevent_our_own_tools_from_working(monkeypatch: pytest.MonkeyPatch):
    """install() must still merge in this server's own tools even when
    every configured extension failed to connect - a typo in one
    extension's command must never be able to take the whole server
    down."""
    monkeypatch.setattr(extensions, "stdio_client", _fake_stdio_client_raising(ConnectionRefusedError("refused")))
    monkeypatch.setattr(extensions, "ClientSession", lambda read, write: read)
    monkeypatch.setattr(extensions, "load_extensions_config", lambda path: {"broken": _config()})

    mcp = FastMCP(name="test-server")

    @mcp.tool()
    def builtin_tool() -> str:
        return "ok"

    registry = extensions.ExtensionRegistry()
    await registry.connect_all(Path("unused.json"))
    registry.install(mcp)

    names = {tool.name for tool in await registry.merged_list_tools()}
    assert names == {"builtin_tool"}
    assert registry.statuses()[0].status == "error"


@pytest.mark.anyio
async def test_connect_timeout_is_recorded_as_an_error_not_raised(monkeypatch: pytest.MonkeyPatch):
    async def hang_forever(*args: object, **kwargs: object) -> None:
        await asyncio.sleep(10_000)

    monkeypatch.setattr(extensions, "CONNECT_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(extensions.ExtensionRegistry, "_open_and_list", staticmethod(hang_forever))
    monkeypatch.setattr(extensions, "load_extensions_config", lambda path: {"slow": _config(id="slow")})

    registry = extensions.ExtensionRegistry()
    await registry.connect_all(Path("unused.json"))  # must not raise

    [status] = registry.statuses()
    assert status.status == "error"


# --- dispatch: merged list/call ------------------------------------------


@pytest.mark.anyio
async def test_merged_list_tools_includes_builtin_and_proxied(monkeypatch: pytest.MonkeyPatch):
    session = _FakeSession(tools=[_echo_tool()])
    _install_fake_connection(monkeypatch, session)
    monkeypatch.setattr(extensions, "load_extensions_config", lambda path: {"reference": _config()})

    mcp = FastMCP(name="test-server")

    @mcp.tool()
    def builtin_tool() -> str:
        return "ok"

    registry = extensions.ExtensionRegistry()
    await registry.connect_all(Path("unused.json"))
    registry.install(mcp)

    names = {tool.name for tool in await registry.merged_list_tools()}
    assert names == {"builtin_tool", "reference__echo"}


@pytest.mark.anyio
async def test_merged_call_tool_routes_a_namespaced_name_upstream(monkeypatch: pytest.MonkeyPatch):
    result = types.CallToolResult(content=[types.TextContent(type="text", text="hi")])
    session = _FakeSession(tools=[_echo_tool()], call_results={"echo": result})
    _install_fake_connection(monkeypatch, session)
    monkeypatch.setattr(extensions, "load_extensions_config", lambda path: {"reference": _config()})

    mcp = FastMCP(name="test-server")
    registry = extensions.ExtensionRegistry()
    await registry.connect_all(Path("unused.json"))
    registry.install(mcp)

    returned = await registry.merged_call_tool("reference__echo", {"text": "hi"})

    assert returned is result
    assert session.calls == [("echo", {"text": "hi"})]  # upstream's own name, not the namespaced one


@pytest.mark.anyio
async def test_merged_call_tool_routes_a_plain_name_to_our_own_dispatch(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(extensions, "load_extensions_config", lambda path: {})

    mcp = FastMCP(name="test-server")

    @mcp.tool()
    def builtin_tool() -> str:
        return "from builtin"

    registry = extensions.ExtensionRegistry()
    await registry.connect_all(Path("unused.json"))
    registry.install(mcp)

    content, structured = await registry.merged_call_tool("builtin_tool", {})

    # FastMCP's own call_tool() wraps a plain string return this way
    # (content blocks plus a structured {"result": ...} form) - the point
    # of this test isn't that shape, it's that a non-namespaced name goes
    # through FastMCP's dispatch at all rather than being treated as an
    # unknown proxied tool.
    assert structured == {"result": "from builtin"}
    [block] = content
    assert block.text == "from builtin"


# --- http transport ---------------------------------------------------
# Mirrors the stdio mocked tests above: same namespacing, same failure
# isolation, just connecting via streamablehttp_client instead of
# stdio_client - see _open_and_list's branch on config.transport.


@pytest.mark.anyio
async def test_http_extension_connects_and_namespaces_its_tools(monkeypatch: pytest.MonkeyPatch):
    session = _FakeSession(tools=[_echo_tool()])
    _install_fake_http_connection(monkeypatch, session)
    monkeypatch.setattr(
        extensions,
        "load_extensions_config",
        lambda path: {"remote": _config(id="remote", command="", transport="http", url="http://127.0.0.1:9000/mcp")},
    )

    registry = extensions.ExtensionRegistry()
    await registry.connect_all(Path("unused.json"))

    [status] = registry.statuses()
    assert status.status == "connected"
    assert status.tools == ["remote__echo"]
    assert registry.is_proxied("remote__echo")
    assert not registry.is_proxied("echo")


@pytest.mark.anyio
async def test_a_broken_http_extension_does_not_prevent_a_working_stdio_sibling(monkeypatch: pytest.MonkeyPatch):
    good_session = _FakeSession(tools=[_echo_tool()])
    monkeypatch.setattr(extensions, "stdio_client", _fake_stdio_client(good_session))
    monkeypatch.setattr(
        extensions, "streamablehttp_client", _fake_streamablehttp_client_raising(ConnectionRefusedError("refused"))
    )
    monkeypatch.setattr(extensions, "ClientSession", lambda read, write: read)
    monkeypatch.setattr(
        extensions,
        "load_extensions_config",
        lambda path: {
            "broken": _config(id="broken", command="", transport="http", url="http://unreachable/mcp"),
            "good": _config(id="good", command="good-command"),
        },
    )

    registry = extensions.ExtensionRegistry()
    await registry.connect_all(Path("unused.json"))

    statuses = {status.id: status for status in registry.statuses()}
    assert statuses["broken"].status == "error"
    assert statuses["good"].status == "connected"
    assert statuses["good"].tools == ["good__echo"]


# --- runtime add()/remove() ------------------------------------------------
# The other half of "toggleable extensions": connecting/disconnecting one
# extension without disturbing any other, after the registry is already
# up and running (not just at startup, like connect_all above).


@pytest.mark.anyio
async def test_add_connects_a_new_extension_after_connect_all_already_ran(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(extensions, "load_extensions_config", lambda path: {})
    mcp = FastMCP(name="test-server")
    registry = extensions.ExtensionRegistry()
    await registry.connect_all(Path("unused.json"))
    registry.install(mcp)

    result = types.CallToolResult(content=[types.TextContent(type="text", text="hi")])
    session = _FakeSession(tools=[_echo_tool()], call_results={"echo": result})
    _install_fake_connection(monkeypatch, session)

    status = await registry.add("reference", _config())

    assert status.status == "connected"
    assert status.tools == ["reference__echo"]
    names = {tool.name for tool in await registry.merged_list_tools()}
    assert "reference__echo" in names
    returned = await registry.merged_call_tool("reference__echo", {"text": "hi"})
    assert returned is result


@pytest.mark.anyio
async def test_add_records_a_connect_failure_as_an_error_status_without_raising(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(extensions, "load_extensions_config", lambda path: {})
    registry = extensions.ExtensionRegistry()
    await registry.connect_all(Path("unused.json"))
    _install_fake_connection(monkeypatch, FileNotFoundError("no such file or directory"))

    status = await registry.add("broken", _config(id="broken"))

    assert status.status == "error"
    assert status.error
    assert not registry.is_proxied("broken__echo")


@pytest.mark.anyio
async def test_remove_disconnects_and_forgets_an_extension(monkeypatch: pytest.MonkeyPatch):
    session = _FakeSession(tools=[_echo_tool()])
    _install_fake_connection(monkeypatch, session)
    monkeypatch.setattr(extensions, "load_extensions_config", lambda path: {"reference": _config()})

    mcp = FastMCP(name="test-server")
    registry = extensions.ExtensionRegistry()
    await registry.connect_all(Path("unused.json"))
    registry.install(mcp)

    removed = await registry.remove("reference")

    assert removed is True
    names = {tool.name for tool in await registry.merged_list_tools()}
    assert "reference__echo" not in names
    assert not registry.statuses()
    with pytest.raises(KeyError):
        await registry.call("reference__echo", {})


@pytest.mark.anyio
async def test_remove_returns_false_for_an_unknown_id() -> None:
    registry = extensions.ExtensionRegistry()
    assert await registry.remove("does-not-exist") is False


@pytest.mark.anyio
async def test_remove_of_an_errored_extension_needs_no_live_connection(monkeypatch: pytest.MonkeyPatch):
    """An extension recorded as "error" never got a session or exit
    stack - remove() must still clean up its status entry rather than
    assuming a stack is always present."""
    monkeypatch.setattr(extensions, "load_extensions_config", lambda path: {})
    registry = extensions.ExtensionRegistry()
    await registry.connect_all(Path("unused.json"))
    _install_fake_connection(monkeypatch, ConnectionRefusedError("refused"))
    status = await registry.add("broken", _config(id="broken"))
    assert status.status == "error"

    removed = await registry.remove("broken")

    assert removed is True
    assert registry.statuses() == []


# --- the genuine, unmocked end-to-end path --------------------------------
# This is the one test in the suite that spawns a real subprocess. It
# exists because the mocked tests above only prove ExtensionRegistry's own
# logic is right; they say nothing about whether this module is actually
# calling the SDK's stdio_client/ClientSession correctly against a real
# MCP server speaking the real protocol over real stdio - which is the
# highest-risk part of this whole mechanism.


def _real_extension_config() -> ExtensionConfig:
    return ExtensionConfig(
        id="reference",
        label="Reference Extension (dev fixture)",
        description="Dev fixture",
        command=sys.executable,
        args=["-m", "src._fixtures.reference_extension_server"],
    )


@pytest.mark.anyio
async def test_real_fixture_server_end_to_end(tmp_path: Path):
    config_path = tmp_path / "config_extensions.json"
    config_path.write_text(
        json.dumps(
            {
                "reference": {
                    "label": "Reference Extension (dev fixture)",
                    "description": "Dev fixture",
                    "command": sys.executable,
                    "args": ["-m", "src._fixtures.reference_extension_server"],
                }
            }
        ),
        encoding="utf-8",
    )

    registry = extensions.ExtensionRegistry()
    try:
        await registry.connect_all(config_path)

        [status] = registry.statuses()
        assert status.status == "connected"
        assert status.error is None
        assert sorted(status.tools) == ["reference__add", "reference__echo"]

        result = await registry.call("reference__add", {"a": 2, "b": 3})
        assert result.isError is False
        assert result.structuredContent == {"result": 5}

        echoed = await registry.call("reference__echo", {"text": "hello"})
        assert echoed.isError is False
        [content_block] = echoed.content
        assert content_block.text == "hello"
    finally:
        await registry.aclose()


@pytest.mark.anyio
async def test_concurrent_calls_to_the_real_fixture_server_both_succeed(tmp_path: Path):
    """Covers the concurrency question this module's docstring answers by
    reading the SDK source: two calls fired at once on the same session
    must not cross-deliver results. Real subprocess, real concurrent
    asyncio tasks - a mock of ClientSession couldn't prove anything about
    this, since the risk is in the SDK's request/response routing, not in
    our own code."""
    registry = extensions.ExtensionRegistry()
    try:
        await registry._connect_one("reference", _real_extension_config())

        first, second = await asyncio.gather(
            registry.call("reference__add", {"a": 1, "b": 1}),
            registry.call("reference__add", {"a": 10, "b": 10}),
        )

        assert first.structuredContent == {"result": 2}
        assert second.structuredContent == {"result": 20}
    finally:
        await registry.aclose()


@pytest.mark.anyio
async def test_add_then_remove_a_real_extension_tears_down_the_subprocess():
    """The one test that actually proves the per-extension-exit-stack
    refactor in _connect_one/remove works. A mocked ClientSession's
    aclose() always "succeeds" trivially and proves nothing about whether
    the underlying resources really closed - only a real subprocess can
    show that removing one extension's connection genuinely tears it
    down, rather than merely forgetting about it while it (and its
    process) keeps running in the background.
    """
    registry = extensions.ExtensionRegistry()
    try:
        status = await registry.add("reference", _real_extension_config())
        assert status.status == "connected"
        assert sorted(status.tools) == ["reference__add", "reference__echo"]

        result = await registry.call("reference__add", {"a": 2, "b": 3})
        assert result.structuredContent == {"result": 5}

        # Grab the live session before removing it, so the assertion below
        # can prove *this exact connection* stopped working - not just
        # that the registry forgot its name.
        session = registry._sessions["reference"]

        removed = await registry.remove("reference")
        assert removed is True

        assert registry.statuses() == []
        assert "reference__add" not in {tool.name for tool in registry.proxied_tool_definitions()}
        with pytest.raises(KeyError):
            await registry.call("reference__add", {"a": 1, "b": 1})

        # The subprocess and its stdio pipes are actually gone: a call on
        # the session directly (bypassing the registry, which no longer
        # knows about this extension at all) fails rather than succeeding
        # against a process that's still quietly running.
        with pytest.raises(Exception):  # noqa: B017 - any failure proves the transport is closed
            await session.list_tools()
    finally:
        await registry.aclose()
