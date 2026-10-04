"""watch_turn: reading a turn's events, and carrying on after a dropped connection."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest

from src.api import EmberUnreachable, SessionExpired, TurnGone
from src.events import BACKOFF_SECONDS, ConnectionLost, watch_turn
from tests.conftest import final, token


class Source:
    """Scripted connections: each item is a list of events (the stream then ends),
    or an exception to raise (after any events listed before it in a tuple)."""

    def __init__(self, *attempts: Any) -> None:
        self.attempts = list(attempts)
        self.calls: list[tuple[str, int]] = []
        self.closed = 0

    async def stream_events(self, chat_id: str, after: int) -> AsyncIterator[dict[str, Any]]:
        self.calls.append((chat_id, after))
        try:
            plan = self.attempts.pop(0)
            events, error = plan if isinstance(plan, tuple) else (plan, None) if isinstance(plan, list) else ([], plan)
            for event in events:
                yield event
            if error is not None:
                raise error
        finally:
            self.closed += 1


class Sleeps:
    def __init__(self) -> None:
        self.waited: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.waited.append(seconds)


async def collect(source: Source, sleeps: Sleeps | None = None, after: int = 0) -> list[dict[str, Any]]:
    return [e async for e in watch_turn(source, "chat-1", after, sleep=sleeps or Sleeps())]


async def test_events_come_out_in_order_and_end_at_the_final_one() -> None:
    events = await collect(Source([token("a", 1), token("b", 2), final("ab", 3)]))

    assert [e["sequence"] for e in events] == [1, 2, 3]


async def test_an_error_event_ends_it_too() -> None:
    events = await collect(Source([token("a", 1), {"sequence": 2, "type": "error", "message": "boom"}]))

    assert events[-1]["type"] == "error"


async def test_nothing_after_the_final_event_is_read() -> None:
    events = await collect(Source([final("x", 1), token("late", 2)]))

    assert [e["sequence"] for e in events] == [1]


async def test_the_stream_is_closed_when_it_ends_early() -> None:
    source = Source([final("x", 1), token("late", 2)])

    await collect(source)

    assert source.closed == 1


async def test_it_asks_for_events_after_the_given_sequence() -> None:
    source = Source([final("x", 8)])

    await collect(source, after=7)

    assert source.calls == [("chat-1", 7)]


async def test_a_stream_that_ends_without_a_final_event_is_resumed_from_the_last_sequence() -> None:
    source = Source([token("a", 1), token("b", 2)], [token("c", 3), final("abc", 4)])
    sleeps = Sleeps()

    events = await collect(source, sleeps)

    assert [e["sequence"] for e in events] == [1, 2, 3, 4]
    assert source.calls == [("chat-1", 0), ("chat-1", 2)]
    assert sleeps.waited == [0.5]


async def test_a_failed_connection_is_retried() -> None:
    source = Source(EmberUnreachable("down"), EmberUnreachable("still down"), [final("x", 1)])
    sleeps = Sleeps()

    events = await collect(source, sleeps)

    assert [e["sequence"] for e in events] == [1]
    assert sleeps.waited == [0.5, 1.0]


async def test_a_broken_event_is_a_dropped_connection() -> None:
    source = Source(([token("a", 1)], ValueError("bad json")), [final("a", 2)])

    events = await collect(source)

    assert [e["sequence"] for e in events] == [1, 2]
    assert source.calls[1] == ("chat-1", 1)


async def test_the_waits_are_half_a_second_then_doubling_to_eight_and_then_it_gives_up() -> None:
    assert BACKOFF_SECONDS == (0.5, 1.0, 2.0, 4.0, 8.0)
    source = Source(*[EmberUnreachable("down")] * 6)
    sleeps = Sleeps()

    with pytest.raises(ConnectionLost, match="Lost the connection"):
        await collect(source, sleeps)

    assert sleeps.waited == [0.5, 1.0, 2.0, 4.0, 8.0]
    assert len(source.calls) == 6


async def test_the_wait_starts_over_once_an_event_arrives() -> None:
    source = Source(
        EmberUnreachable("down"),
        EmberUnreachable("down"),
        [token("a", 1)],  # an event, then the stream ends
        [final("a", 2)],
    )
    sleeps = Sleeps()

    await collect(source, sleeps)

    assert sleeps.waited == [0.5, 1.0, 0.5]


async def test_a_missing_turn_is_not_retried() -> None:
    source = Source(TurnGone("gone"))
    sleeps = Sleeps()

    with pytest.raises(TurnGone):
        await collect(source, sleeps)

    assert sleeps.waited == [] and len(source.calls) == 1


async def test_an_ended_session_is_not_retried() -> None:
    source = Source(([token("a", 1)], SessionExpired(401, "ended")))

    with pytest.raises(SessionExpired):
        await collect(source)

    assert len(source.calls) == 1


async def test_a_turn_that_vanishes_during_a_reconnect_is_reported() -> None:
    source = Source([token("a", 1)], TurnGone("gone"))

    with pytest.raises(TurnGone):
        await collect(source)
