import asyncio

from src.llm.base_provider import LiveUsage


def _run(coro):
    return asyncio.run(coro)


def test_estimates_while_streaming_then_exact_at_round_end():
    events = []

    async def on_event(event):
        events.append(event)

    async def scenario():
        meter = LiveUsage(on_event, min_interval=0)
        await meter.chars(40)           # ~10 tokens estimated
        await meter.round_done(500)     # exact
        await meter.chars(80)           # exact 500 + ~20
        await meter.round_done(300)
    _run(scenario())
    assert [(e["total_tokens"], e["estimated"]) for e in events] == [
        (10, True), (500, False), (520, True), (800, False),
    ]
    assert all(e["type"] == "usage" for e in events)


def test_throttles_estimates_and_tolerates_no_listener():
    events = []

    async def on_event(event):
        events.append(event)

    async def scenario():
        meter = LiveUsage(on_event, min_interval=60)
        for _ in range(20):
            await meter.chars(4)
        await LiveUsage(None).round_done(5)  # no listener: must not raise
        return len(events)
    assert _run(scenario()) == 1
