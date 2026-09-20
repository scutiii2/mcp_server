"""Blocking wrapper around McpClientRegistry, for a synchronous host app
that wants persistent connections rather than opening a fresh connection
per request.

One background thread owns one long-lived event loop; the registry and
every connection it holds live entirely on that thread. Each public
method here blocks the calling thread until the corresponding coroutine
finishes on the background loop - asyncio.run_coroutine_threadsafe() is
built exactly for handing a coroutine to a loop running on another
thread and waiting for its result.
"""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from typing import Any, Callable

from mcp import types

from src.registry import McpClientRegistry, ServerStatus


class SyncMcpClient:
    def __init__(self) -> None:
        self._loop = asyncio.new_event_loop()
        self._registry = McpClientRegistry()
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True)
        self._thread.start()

    def _run(self, coro: Any) -> Any:
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result()

    def connect_all(self, config_path: Path, url_overrides: dict[str, str] | None = None) -> list[ServerStatus]:
        return self._run(self._registry.connect_all(config_path, url_overrides))

    def list_tools(self) -> list[types.Tool]:
        return self._run(self._registry.list_tools())

    def call_tool(
        self, name: str, arguments: dict[str, Any], on_progress: Callable[[str], None] | None = None
    ) -> types.CallToolResult:
        if on_progress is None:
            return self._run(self._registry.call_tool(name, arguments))
        return self._run(self._registry.call_tool(name, arguments, on_progress=on_progress))

    def close(self) -> None:
        """Close every connection and stop the background loop/thread.
        Safe to call once - not idempotent, matching aclose()'s own
        single-shutdown contract in registry.py."""
        self._run(self._registry.aclose())
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=5)
