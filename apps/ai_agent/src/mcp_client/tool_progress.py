"""Carries a running tool's live progress messages up to the chat stream.

A provider's tool loop dispatches each tool on a worker thread
(``anyio.to_thread.run_sync``), several layers above the MCP call that
actually receives mcp_server's progress notifications. Threading a callback
through ``_dispatch`` -> ``mcp_upstream.call_tool`` -> ``SyncMcpClient`` ->
the registry would touch every signature on the way, so a ``ContextVar``
carries it instead: the provider binds a sink before dispatching, and
``mcp_upstream.call_tool`` reads it back. Worker-thread hops copy the
context, so the sink survives them. Unbound (delegation, tests, non-streaming
callers) it is simply ``None``.
"""

from __future__ import annotations

from contextvars import ContextVar, Token
from typing import Callable

Sink = Callable[[str], None]

_sink: ContextVar[Sink | None] = ContextVar("tool_progress_sink", default=None)


def bind(sink: Sink) -> Token:
    return _sink.set(sink)


def reset(token: Token) -> None:
    _sink.reset(token)


def current() -> Sink | None:
    return _sink.get()
