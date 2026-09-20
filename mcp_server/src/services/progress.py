"""Live progress reporting for long-running tool calls.

``domain.py`` code calls ``report("Connecting to host...")`` at each notable
step. It has no idea who is listening: ``offload.offload_with_progress``
binds a sink for the duration of one tool call, forwarding each message to
the MCP client as a ``notifications/progress``. With no sink bound (unit
tests, watcher threads, a client that sent no progress token) ``report`` is
a silent no-op, so domain code never needs a ``progress`` parameter.

A ``ContextVar`` carries the sink because ``asyncio.to_thread`` copies the
calling context into its worker thread - the same reason
``identity_context`` works there.
"""

from __future__ import annotations

import logging
from contextvars import ContextVar, Token
from typing import Callable

logger = logging.getLogger(__name__)

Sink = Callable[[str], None]

_sink: ContextVar[Sink | None] = ContextVar("progress_sink", default=None)


def bind(sink: Sink) -> Token:
    return _sink.set(sink)


def reset(token: Token) -> None:
    _sink.reset(token)


def report(message: str) -> None:
    sink = _sink.get()
    if sink is None:
        return
    try:
        sink(message)
    except Exception:  # noqa: BLE001 - progress is best-effort, never fail the tool over it
        logger.debug("progress sink failed", exc_info=True)
