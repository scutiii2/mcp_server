"""mcp_upstream.py with private extensions: the bound turn's tools join the
catalog, calls are routed to the pool, and nothing leaks across turns."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from mcp import types

from src.core import approvals
from src.mcp_client import mcp_upstream
from src.mcp_client.sync_wrapper import SyncMcpClient
from src.private_extensions import turn as private_turn
from src.private_extensions.spec import PrivateSpec
from src.private_extensions.turn import PrivateTurn

RAW = [{"id": "notes", "label": "Notes", "url": "https://notes.example.com/mcp", "headers": {"X-Key": "s3cret"}}]


class FakePool:
    def __init__(self):
        self.calls = []
        self.error: Exception | None = None
        self.probed = []

    async def tools(self, account, spec):
        return [types.Tool(name="search", description="Find.", inputSchema={"type": "object"})]

    async def call(self, account, spec, tool, arguments):
        if self.error:
            raise self.error
        self.calls.append((account, spec.slug, tool, arguments))
        return types.CallToolResult(content=[types.TextContent(type="text", text="found 3")])

    async def probe(self, spec):
        self.probed.append(spec)
        if spec.url.endswith("/down"):
            raise ConnectionError(f"refused for {spec.header_map.get('X-Key', '')}")
        return [types.Tool(name="search", inputSchema={"type": "object"}), types.Tool(name="add", inputSchema={"type": "object"})]

    async def aclose(self):
        pass


@pytest.fixture
def pool(monkeypatch):
    fake = FakePool()
    monkeypatch.setattr(mcp_upstream, "private_pool", fake)
    return fake


@pytest.fixture
def bound(pool):
    turn = PrivateTurn.from_raw(RAW, "a@x")

    async def go():
        await turn.prefetch(pool, lambda coro: coro)

    asyncio.run(go())
    token = private_turn.bind(turn)
    yield turn
    private_turn.reset(token)


def test_the_bound_turns_tools_join_the_catalog(bound):
    names = [t.name for t in mcp_upstream.list_tools([])]

    assert names == ["u_notes__search"]


def test_no_bound_turn_means_no_private_tools(pool):
    assert mcp_upstream.list_tools([]) == []


def test_the_agents_tool_scope_applies_to_private_tools(bound):
    scope = MagicMock()
    scope.tools.allows.side_effect = lambda name: not name.startswith("u_")
    with patch.object(mcp_upstream.agent_spec, "current", return_value=scope):
        assert mcp_upstream.list_tools([]) == []


def test_a_private_call_goes_to_the_pool_with_the_turns_account(bound, pool):
    out = mcp_upstream.call_tool("u_notes__search", {"q": "milk"})

    assert out == "found 3"
    assert pool.calls == [("a@x", "notes", "search", {"q": "milk"})]


def test_an_unknown_or_unbound_private_name_is_refused(bound, pool):
    with pytest.raises(PermissionError):
        mcp_upstream.call_tool("u_notes__delete", {})
    with pytest.raises(PermissionError):
        mcp_upstream.call_tool("u_other__search", {})
    assert pool.calls == []


def test_a_private_name_is_refused_outside_a_turn_that_bound_it(pool):
    with pytest.raises(PermissionError):
        mcp_upstream.call_tool("u_notes__search", {})


def test_a_private_call_is_refused_when_the_agents_scope_forbids_it(bound, pool):
    scope = MagicMock()
    scope.tools.allows.return_value = False
    with patch.object(mcp_upstream.agent_spec, "current", return_value=scope):
        with pytest.raises(PermissionError):
            mcp_upstream.call_tool("u_notes__search", {})


def test_a_failing_private_call_never_shows_a_header_value(bound, pool):
    pool.error = RuntimeError("401 for X-Key s3cret")

    with pytest.raises(RuntimeError) as caught:
        mcp_upstream.call_tool("u_notes__search", {})

    assert "s3cret" not in str(caught.value)
    assert caught.value.__cause__ is None


def test_a_short_private_result_is_returned_whole(bound, pool):
    assert mcp_upstream.call_tool("u_notes__search", {}) == "found 3"


def test_a_huge_private_result_is_cut_with_a_note(bound, pool):
    big = "x" * 60_000

    async def call(account, spec, tool, arguments):
        return types.CallToolResult(content=[types.TextContent(type="text", text=big)])

    pool.call = call

    out = mcp_upstream.call_tool("u_notes__search", {})

    limit = mcp_upstream.MAX_PRIVATE_RESULT_CHARS
    assert limit == 50_000
    assert out.startswith("x" * limit)
    assert out[limit:] == "\n\n[Truncated: the extension returned 60000 characters; only the first 50000 are shown.]"


@pytest.fixture
def policy():
    pol = approvals.ApprovalPolicy("off")
    token = approvals.bind(pol)
    yield pol
    approvals.reset(token)


def test_a_private_call_taints_the_turn_so_later_tools_ask(bound, pool, policy):
    assert policy.tainted is False

    mcp_upstream.call_tool("u_notes__search", {})

    assert policy.tainted is True
    assert policy.needs_approval("main__calc") is True


def test_a_failing_private_call_taints_the_turn_too(bound, pool, policy):
    pool.error = RuntimeError("boom")

    with pytest.raises(RuntimeError):
        mcp_upstream.call_tool("u_notes__search", {})

    assert policy.tainted is True


def test_a_refused_private_call_does_not_taint_the_turn(bound, pool, policy):
    with pytest.raises(PermissionError):
        mcp_upstream.call_tool("u_notes__delete", {})

    assert policy.tainted is False


def test_a_private_call_without_a_bound_policy_never_changes_the_shared_default(bound, pool):
    mcp_upstream.call_tool("u_notes__search", {})

    assert approvals.current().tainted is False


def test_a_built_in_call_is_unchanged(pool):
    with patch.object(mcp_upstream.client, "call_tool", return_value=types.CallToolResult(
        content=[types.TextContent(type="text", text="pong")]
    )) as call:
        assert mcp_upstream.call_tool("main__ping", {}) == "pong"
    call.assert_called_once()


def test_prefetch_private_fills_the_turn_through_the_connection_loop(pool):
    turn = PrivateTurn.from_raw(RAW, "a@x")

    asyncio.run(mcp_upstream.prefetch_private(turn))

    assert [t.name for t in turn.tools()] == ["u_notes__search"]


def test_probe_lists_tool_names_and_never_raises(pool):
    ok = asyncio.run(mcp_upstream.probe_private("https://notes.example.com/mcp", {"X-Key": "s3cret"}))
    down = asyncio.run(mcp_upstream.probe_private("https://notes.example.com/down", {"X-Key": "s3cret"}))
    bad = asyncio.run(mcp_upstream.probe_private("file:///etc/passwd", {}))

    assert ok == {"status": "connected", "error": None, "tools": ["add", "search"]}
    assert down["status"] == "error" and down["tools"] == [] and "s3cret" not in down["error"]
    assert bad["status"] == "error" and bad["tools"] == []


def test_sync_client_can_submit_and_run_a_coroutine():
    client = SyncMcpClient()
    try:
        async def value():
            return 7

        assert client.submit(value()).result(timeout=5) == 7
        assert client.run_coroutine(value()) == 7
    finally:
        client.close()
