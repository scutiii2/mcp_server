"""Sessions to private extensions, kept per account and spec.

Everything here runs on the connection loop owned by `SyncMcpClient` (see
mcp_upstream.py); the callers on other loops reach it through
`SyncMcpClient.submit`. A session is reused while it is used at least every
`idle_seconds`; a stale one is closed the next time the pool is used.

Opening a session is split in two for the reason documented in mcp_server's
extensions.py: a failure inside the SDK's own task group (a refused handshake)
corrupts the loop's cancel scopes. So one plain `initialize` POST goes through
the same guarded client first and raises an ordinary error on a bad status.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from contextlib import AsyncExitStack
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import httpx
from mcp import types
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from mcp.shared.exceptions import McpError

from src.private_extensions.guard import guarded_client_factory
from src.private_extensions.spec import PrivateSpec

CONNECT_TIMEOUT_SECONDS = 10.0
CALL_TIMEOUT_SECONDS = 120.0
IDLE_SECONDS = 300.0
MAX_PER_ACCOUNT = 5
MAX_TOTAL = 50

Opener = Callable[[AsyncExitStack, PrivateSpec, Any, float], Awaitable[ClientSession]]


async def _preflight_handshake(spec: PrivateSpec, factory: Any, timeout_seconds: float) -> None:
    payload = {
        "jsonrpc": "2.0",
        "id": 0,
        "method": "initialize",
        "params": {
            "protocolVersion": types.LATEST_PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "ai_agent-preflight", "version": "0"},
        },
    }
    headers = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json", **spec.header_map}
    async with factory(None, httpx.Timeout(timeout_seconds)) as client:
        async with client.stream("POST", spec.url, json=payload, headers=headers) as response:
            if response.status_code >= 400:
                hint = " (check the extension's headers)" if response.status_code in (401, 403) else ""
                raise ConnectionError(f"The server rejected the MCP handshake: HTTP {response.status_code}{hint}")


async def open_private_session(
    stack: AsyncExitStack, spec: PrivateSpec, factory: Any, timeout_seconds: float
) -> ClientSession:
    """Open and initialize a session for `spec`, registering what it opens on `stack`."""
    await _preflight_handshake(spec, factory, timeout_seconds)
    read_stream, write_stream, _session_id = await stack.enter_async_context(
        streamablehttp_client(spec.url, headers=spec.header_map or None, httpx_client_factory=factory)
    )
    session = await stack.enter_async_context(
        ClientSession(read_stream, write_stream, read_timeout_seconds=timedelta(seconds=timeout_seconds))
    )
    await session.initialize()
    return session


@dataclass
class _Entry:
    account: str
    stack: AsyncExitStack
    session: ClientSession
    last_used: float


async def _close_quietly(stack: AsyncExitStack) -> None:
    try:
        await stack.aclose()
    except Exception:  # noqa: BLE001 - a messy close must not break the caller
        pass


class PrivateSessionPool:
    def __init__(
        self,
        *,
        factory: Any = None,
        opener: Opener = open_private_session,
        clock: Callable[[], float] = time.monotonic,
        idle_seconds: float = IDLE_SECONDS,
        per_account: int = MAX_PER_ACCOUNT,
        total: int = MAX_TOTAL,
        connect_timeout: float = CONNECT_TIMEOUT_SECONDS,
        call_timeout: float = CALL_TIMEOUT_SECONDS,
    ) -> None:
        self._factory = factory if factory is not None else guarded_client_factory()
        self._opener = opener
        self._clock = clock
        self._idle = idle_seconds
        self._per_account = per_account
        self._total = total
        self._connect_timeout = connect_timeout
        self._call_timeout = call_timeout
        self._entries: dict[tuple[str, str], _Entry] = {}
        self._locks: dict[tuple[str, str], asyncio.Lock] = {}

    async def session(self, account: str, spec: PrivateSpec) -> ClientSession:
        key = (account, spec.key())
        async with self._locks.setdefault(key, asyncio.Lock()):
            entry = self._entries.get(key)
            if entry is not None and self._clock() - entry.last_used <= self._idle:
                entry.last_used = self._clock()
                return entry.session
            if entry is not None:
                await self._close(key)
            await self._make_room(account)
            stack = AsyncExitStack()
            try:
                session = await self._opener(stack, spec, self._factory, self._connect_timeout)
            except Exception:
                await _close_quietly(stack)
                raise
            self._entries[key] = _Entry(account, stack.pop_all(), session, self._clock())
            return session

    async def _make_room(self, account: str) -> None:
        now = self._clock()
        for key, entry in list(self._entries.items()):
            if now - entry.last_used > self._idle:
                await self._close(key)
        mine = sorted((k for k, e in self._entries.items() if e.account == account), key=lambda k: self._entries[k].last_used)
        while len(mine) >= self._per_account:
            await self._close(mine.pop(0))
        while len(self._entries) >= self._total:
            await self._close(min(self._entries, key=lambda k: self._entries[k].last_used))

    async def _close(self, key: tuple[str, str]) -> None:
        entry = self._entries.pop(key, None)
        if entry is not None:
            await _close_quietly(entry.stack)

    async def drop(self, account: str, spec: PrivateSpec) -> None:
        await self._close((account, spec.key()))

    async def _use(self, account: str, spec: PrivateSpec, action: Callable[[ClientSession], Awaitable[Any]]) -> Any:
        try:
            return await action(await self.session(account, spec))
        except (RuntimeError, McpError) as error:
            # The SDK raises McpError after a server restart (RuntimeError in older versions).
            if "Session terminated" not in str(error):
                raise
        # The server dropped the session: one fresh one, one retry.
        await self.drop(account, spec)
        return await action(await self.session(account, spec))

    async def tools(self, account: str, spec: PrivateSpec) -> list[types.Tool]:
        listed = await self._use(account, spec, lambda session: session.list_tools())
        return list(listed.tools)

    async def call(self, account: str, spec: PrivateSpec, tool: str, arguments: dict[str, Any]) -> types.CallToolResult:
        timeout = timedelta(seconds=self._call_timeout)
        return await self._use(account, spec, lambda session: session.call_tool(tool, arguments, read_timeout_seconds=timeout))

    async def probe(self, spec: PrivateSpec) -> list[types.Tool]:
        """Connect once, list the tools, close. Nothing is kept."""
        stack = AsyncExitStack()
        try:
            session = await self._opener(stack, spec, self._factory, self._connect_timeout)
            return list((await session.list_tools()).tools)
        finally:
            await _close_quietly(stack)

    async def aclose(self) -> None:
        for key in list(self._entries):
            await self._close(key)
