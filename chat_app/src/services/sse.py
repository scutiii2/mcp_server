"""Bridges an async generator (an MCP client's live event stream) onto a
plain synchronous iterator, so a normal Flask view - this whole app stays
WSGI/sync, not ASGI - can `yield` Server-Sent Events without every route
that needs one learning asyncio. Runs the async generator to completion
on a dedicated background thread with its own event loop; the calling
thread just drains a thread-safe queue.Queue.
"""

from __future__ import annotations

import asyncio
import json
import queue
import threading
from typing import Any, AsyncIterator, Callable, Iterator

from src.utils.catalog import catalog

_SENTINEL = object()


@catalog
def encode_sse(event: dict[str, Any]) -> bytes:
    return f"data: {json.dumps(event)}\n\n".encode("utf-8")


@catalog
def stream_async_generator(factory: Callable[[], AsyncIterator[dict[str, Any]]]) -> Iterator[dict[str, Any]]:
    q: queue.Queue = queue.Queue()

    def worker() -> None:
        async def drain() -> None:
            try:
                async for item in factory():
                    q.put(item)
            except Exception as exc:  # noqa: BLE001 - surfaced to the caller as a stream event, never raised across threads
                q.put({"type": "error", "message": str(exc)})
            finally:
                q.put(_SENTINEL)

        asyncio.run(drain())

    threading.Thread(target=worker, daemon=True).start()
    while True:
        item = q.get()
        if item is _SENTINEL:
            return
        yield item
