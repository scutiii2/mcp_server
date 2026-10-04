"""Watching a turn: the events of an answer ember_api is writing, with the same
reconnect rules as the web page (ember_web's turnStream)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import aclosing
from typing import Any, Protocol

from src.api import EmberError, EmberUnreachable

BACKOFF_SECONDS = (0.5, 1.0, 2.0, 4.0, 8.0)
TERMINAL = ("final", "error")


class ConnectionLost(EmberError):
    """The event stream kept failing; the answer carries on on the server."""


class EventSource(Protocol):
    def stream_events(self, chat_id: str, after: int) -> AsyncIterator[dict[str, Any]]: ...


async def watch_turn(
    source: EventSource,
    chat_id: str,
    after: int,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> AsyncIterator[dict[str, Any]]:
    """Yields every event of the turn in order, ending after its `final` or `error`.

    A dropped connection (the stream ends without a terminal event, a server
    error, bad JSON, a network failure) is retried after 0.5, 1, 2, 4 and 8 s,
    resuming from the last event seen; the wait starts over whenever an event
    arrives. After the fifth failure in a row it raises ConnectionLost. TurnGone
    and SessionExpired are not retried."""
    cursor = after
    attempt = 0
    while True:
        try:
            async with aclosing(source.stream_events(chat_id, cursor)) as events:
                async for event in events:
                    cursor = int(event.get("sequence", cursor))
                    attempt = 0
                    yield event
                    if event.get("type") in TERMINAL:
                        return
        except (EmberUnreachable, ValueError):
            # TurnGone and SessionExpired are other EmberErrors: they pass through.
            pass
        if attempt >= len(BACKOFF_SECONDS):
            raise ConnectionLost("Lost the connection to ember_api")
        await sleep(BACKOFF_SECONDS[attempt])
        attempt += 1
