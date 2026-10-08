"""pool.py: sessions are reused per account and spec, capped, expired when idle,
and a dead one is replaced once."""

from __future__ import annotations

import asyncio

import pytest
from mcp import types

from src.private_extensions.pool import PrivateSessionPool
from src.private_extensions.spec import PrivateSpec


def spec(slug="notes", **headers) -> PrivateSpec:
    return PrivateSpec.parse({"id": slug, "url": f"https://{slug}.example.com/mcp", "headers": headers})


class FakeSession:
    def __init__(self, slug: str):
        self.slug = slug
        self.calls: list[tuple] = []
        self.fail_once: Exception | None = None

    async def list_tools(self):
        return types.ListToolsResult(tools=[types.Tool(name="echo", inputSchema={"type": "object", "properties": {}})])

    async def call_tool(self, name, arguments, read_timeout_seconds=None):
        if self.fail_once is not None:
            error, self.fail_once = self.fail_once, None
            raise error
        self.calls.append((name, arguments))
        return types.CallToolResult(content=[types.TextContent(type="text", text="ok")])


class Harness:
    def __init__(self, **options):
        self.now = 1000.0
        self.opened: list[PrivateSpec] = []
        self.closed: list[str] = []
        self.sessions: list[FakeSession] = []
        self.fail_open = 0
        self.pool = PrivateSessionPool(factory=object(), opener=self.opener, clock=lambda: self.now, **options)

    async def opener(self, stack, spec, factory, timeout):
        if self.fail_open:
            self.fail_open -= 1
            raise ConnectionError("down")
        session = FakeSession(spec.slug)
        self.sessions.append(session)
        self.opened.append(spec)

        async def closed(slug):
            self.closed.append(slug)

        stack.push_async_callback(closed, spec.slug)
        return session


def run(coro):
    return asyncio.run(coro)


def test_the_same_account_and_spec_share_one_session():
    h = Harness()

    async def go():
        await h.pool.call("a@x", spec(), "echo", {})
        await h.pool.call("a@x", spec(), "echo", {})

    run(go())
    assert len(h.opened) == 1
    assert h.sessions[0].calls == [("echo", {}), ("echo", {})]


def test_another_account_or_other_headers_get_their_own_session():
    h = Harness()

    async def go():
        await h.pool.session("a@x", spec())
        await h.pool.session("b@x", spec())
        await h.pool.session("a@x", spec(**{"X-Key": "1"}))
        await h.pool.session("a@x", spec(**{"X-Key": "2"}))

    run(go())
    assert len(h.opened) == 4


def test_an_idle_session_is_closed_and_replaced_on_next_use():
    h = Harness(idle_seconds=300)

    async def go():
        await h.pool.session("a@x", spec())
        h.now += 301
        await h.pool.session("a@x", spec())

    run(go())
    assert len(h.opened) == 2
    assert h.closed == ["notes"]


def test_a_session_used_within_the_idle_time_is_kept():
    h = Harness(idle_seconds=300)

    async def go():
        await h.pool.session("a@x", spec())
        h.now += 200
        await h.pool.session("a@x", spec())
        h.now += 200
        await h.pool.session("a@x", spec())

    run(go())
    assert len(h.opened) == 1


def test_the_per_account_cap_closes_that_accounts_oldest():
    h = Harness(per_account=2)

    async def go():
        await h.pool.session("a@x", spec("one"))
        h.now += 1
        await h.pool.session("a@x", spec("two"))
        h.now += 1
        await h.pool.session("a@x", spec("three"))

    run(go())
    assert h.closed == ["one"]


def test_the_total_cap_closes_the_oldest_overall():
    h = Harness(total=2, per_account=5)

    async def go():
        await h.pool.session("a@x", spec("one"))
        h.now += 1
        await h.pool.session("b@x", spec("two"))
        h.now += 1
        await h.pool.session("c@x", spec("three"))

    run(go())
    assert h.closed == ["one"]


def test_a_failed_open_leaves_nothing_behind_and_the_next_try_works():
    h = Harness()
    h.fail_open = 1

    async def go():
        with pytest.raises(ConnectionError):
            await h.pool.session("a@x", spec())
        return await h.pool.session("a@x", spec())

    assert isinstance(run(go()), FakeSession)
    assert len(h.opened) == 1


def test_a_terminated_session_is_replaced_and_the_call_retried_once():
    h = Harness()

    async def go():
        await h.pool.call("a@x", spec(), "echo", {})
        h.sessions[0].fail_once = RuntimeError("Session terminated")
        return await h.pool.call("a@x", spec(), "echo", {"n": 1})

    result = run(go())
    assert result.content[0].text == "ok"
    assert len(h.opened) == 2
    assert h.closed == ["notes"]
    assert h.sessions[1].calls == [("echo", {"n": 1})]


def test_any_other_error_is_not_retried():
    h = Harness()

    async def go():
        await h.pool.call("a@x", spec(), "echo", {})
        h.sessions[0].fail_once = RuntimeError("boom")
        await h.pool.call("a@x", spec(), "echo", {})

    with pytest.raises(RuntimeError, match="boom"):
        run(go())
    assert len(h.opened) == 1


def test_tools_lists_what_the_server_offers():
    h = Harness()

    tools = run(h.pool.tools("a@x", spec()))

    assert [t.name for t in tools] == ["echo"]


def test_probe_opens_lists_and_closes_without_keeping_anything():
    h = Harness()

    async def go():
        tools = await h.pool.probe(spec())
        await h.pool.session("a@x", spec())  # not served from a probe
        return tools

    assert [t.name for t in run(go())] == ["echo"]
    assert h.closed == ["notes"]
    assert len(h.opened) == 2


def test_aclose_closes_everything():
    h = Harness()

    async def go():
        await h.pool.session("a@x", spec("one"))
        await h.pool.session("b@x", spec("two"))
        await h.pool.aclose()

    run(go())
    assert sorted(h.closed) == ["one", "two"]


def test_drop_closes_one_session():
    h = Harness()

    async def go():
        await h.pool.session("a@x", spec("one"))
        await h.pool.drop("a@x", spec("one"))
        await h.pool.drop("a@x", spec("one"))  # nothing left: fine

    run(go())
    assert h.closed == ["one"]
