"""extension_probe.py: live status of a private extension, cached and bounded."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from src.services.agent_gateway import AgentCallError, Caller
from src.services.extension_probe import NO_AGENT, UNKNOWN_MESSAGE, ExtensionProbe, ProbeResult
from src.services.user_extension_service import UNREADABLE_MESSAGE, StoredExtension

CALLER = Caller(username="alice", email="alice@example.com")


def stored(slug="notes", url="https://notes.example.com/mcp", headers=None) -> StoredExtension:
    row = SimpleNamespace(slug=slug, url=url)
    return StoredExtension(row, {} if headers is None else headers)  # type: ignore[arg-type]


class Gateway:
    def __init__(self):
        self.calls: list[tuple[str, dict | None]] = []
        self.answer = {"status": "connected", "error": None, "tools": ["add", "search"]}
        self.fail: str | None = None
        self.running = 0
        self.peak = 0

    async def probe_extension(self, url, caller, *, extension_url, headers):
        self.calls.append((extension_url, headers))
        self.running += 1
        self.peak = max(self.peak, self.running)
        try:
            await asyncio.sleep(0.01)
            if self.fail:
                raise AgentCallError(self.fail)
            return self.answer
        finally:
            self.running -= 1


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


def make(**kwargs):
    gateway, clock = Gateway(), Clock()
    return ExtensionProbe(gateway, clock=clock, **kwargs), gateway, clock


def run(coro):
    return asyncio.run(coro)


def test_a_connected_extension_reports_its_tools():
    probe, gateway, _ = make()

    result = run(probe.check("http://agent", CALLER, 1, stored(headers={"X-Key": "s3cret"})))

    assert result == ProbeResult("connected", None, ("add", "search"))
    assert gateway.calls == [("https://notes.example.com/mcp", {"X-Key": "s3cret"})]


def test_no_headers_are_sent_as_none():
    probe, gateway, _ = make()

    run(probe.check("http://agent", CALLER, 1, stored()))

    assert gateway.calls[0][1] is None


def test_a_result_is_cached_for_the_ttl_then_asked_again():
    probe, gateway, clock = make(ttl=60)

    async def go():
        await probe.check("http://agent", CALLER, 1, stored())
        await probe.check("http://agent", CALLER, 1, stored())
        clock.now += 59
        await probe.check("http://agent", CALLER, 1, stored())
        clock.now += 2
        await probe.check("http://agent", CALLER, 1, stored())

    run(go())
    assert len(gateway.calls) == 2


def test_an_error_result_is_cached_too():
    probe, gateway, _ = make()
    gateway.answer = {"status": "error", "error": "That address is not allowed", "tools": []}

    async def go():
        first = await probe.check("http://agent", CALLER, 1, stored())
        await probe.check("http://agent", CALLER, 1, stored())
        return first

    assert run(go()) == ProbeResult("error", "That address is not allowed", ())
    assert len(gateway.calls) == 1


def test_a_change_of_url_or_headers_is_asked_again_at_once():
    probe, gateway, _ = make()

    async def go():
        await probe.check("http://agent", CALLER, 1, stored(headers={"X-Key": "one"}))
        await probe.check("http://agent", CALLER, 1, stored(headers={"X-Key": "two"}))
        await probe.check("http://agent", CALLER, 1, stored(url="https://other.example.com/mcp", headers={"X-Key": "two"}))

    run(go())
    assert len(gateway.calls) == 3


def test_forget_drops_the_cached_result():
    probe, gateway, _ = make()

    async def go():
        await probe.check("http://agent", CALLER, 1, stored())
        probe.forget(1, "notes")
        await probe.check("http://agent", CALLER, 1, stored())

    run(go())
    assert len(gateway.calls) == 2


def test_accounts_do_not_share_results():
    probe, gateway, _ = make()

    async def go():
        await probe.check("http://agent", CALLER, 1, stored())
        await probe.check("http://agent", CALLER, 2, stored())

    run(go())
    assert len(gateway.calls) == 2


def test_an_agent_that_cannot_be_reached_is_unknown_and_not_cached():
    probe, gateway, _ = make()
    gateway.fail = "Could not reach the agent: refused"

    async def go():
        first = await probe.check("http://agent", CALLER, 1, stored())
        gateway.fail = None
        second = await probe.check("http://agent", CALLER, 1, stored())
        return first, second

    first, second = run(go())
    assert first == ProbeResult("unknown", UNKNOWN_MESSAGE, ())
    assert second.status == "connected"


def test_no_agent_running_is_unknown():
    probe, gateway, _ = make()

    assert run(probe.check(None, CALLER, 1, stored())) == NO_AGENT
    assert gateway.calls == []


def test_unreadable_headers_are_an_error_without_asking_the_agent():
    probe, gateway, _ = make()

    result = run(probe.check("http://agent", CALLER, 1, StoredExtension(SimpleNamespace(slug="n", url="u"), None)))  # type: ignore[arg-type]

    assert result == ProbeResult("error", UNREADABLE_MESSAGE, ())
    assert gateway.calls == []


def test_an_odd_status_from_the_agent_becomes_unknown():
    probe, gateway, _ = make()
    gateway.answer = {"status": "weird", "error": None, "tools": []}

    assert run(probe.check("http://agent", CALLER, 1, stored())).status == "unknown"


def test_at_most_concurrency_probes_run_at_once():
    probe, gateway, _ = make(concurrency=2)

    async def go():
        await asyncio.gather(*(probe.check("http://agent", CALLER, 1, stored(slug=f"e{i}")) for i in range(6)))

    run(go())
    assert gateway.peak == 2
