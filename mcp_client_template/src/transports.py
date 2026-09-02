"""Open a live, authenticated MCP session for one configured server.

Two responsibilities live here: resolving `ServerConfig.auth` into
whatever the wire actually needs (an HTTP header today), and opening the
transport itself (stdio subprocess or streamable HTTP) the same way
mcp_server/src/infra/extensions.py does, including the TCP-reachability
pre-check that module's docstring explains at length: a real HTTP connect
failure reaching streamablehttp_client directly corrupts anyio's
cancel-scope tree for the caller's task, so an unreachable host must
never be allowed to reach it in the first place.
"""

from __future__ import annotations

import asyncio
import os
from contextlib import AsyncExitStack
from datetime import timedelta
from urllib.parse import urlsplit

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.streamable_http import streamablehttp_client

from src.config import ServerConfig


class AuthResolutionError(RuntimeError):
    """Raised when a server's auth block names something not actually
    available at connect time - e.g. an unset environment variable."""


def resolve_headers(config: ServerConfig) -> dict[str, str]:
    """The extra HTTP headers `config`'s auth block requires, or {} for
    no auth. Only meaningful for transport 'http' - open_session never
    calls this for 'stdio'."""
    auth = config.auth
    if auth is None or auth.type == "none":
        return {}
    if auth.type == "header":
        return {auth.header_name: auth.header_value}  # type: ignore[dict-item]
    if auth.type == "bearer_env":
        value = os.environ.get(auth.env_var or "")
        if not value:
            raise AuthResolutionError(f"{config.id!r}: environment variable {auth.env_var!r} is not set")
        return {"Authorization": f"Bearer {value}"}
    raise AuthResolutionError(f"{config.id!r}: unknown auth type {auth.type!r}")


async def _check_tcp_reachable(url: str, timeout_seconds: float) -> None:
    """Raise a plain exception if `url`'s host:port won't accept a TCP
    connection - without ever calling streamablehttp_client. Plain
    asyncio, not anyio: this opens no anyio task group, so it can't
    corrupt one - it only answers "is anyone listening"; the real
    connection is opened separately right after this returns."""
    parsed = urlsplit(url)
    if parsed.hostname is None:
        raise ValueError(f"Server URL has no host: {url!r}")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    _reader, writer = await asyncio.wait_for(asyncio.open_connection(parsed.hostname, port), timeout=timeout_seconds)
    writer.close()
    try:
        await writer.wait_closed()
    except Exception:  # noqa: BLE001 - this was only ever a reachability probe
        pass


async def open_session(stack: AsyncExitStack, config: ServerConfig, timeout_seconds: float) -> ClientSession:
    """Open and initialize a session for `config`, registering every
    resource it opens on `stack` so the caller controls their lifetime.
    Does not call list_tools() - that's the caller's job (registry.py)."""
    if config.transport == "http":
        assert config.url is not None  # guaranteed by config.load_servers_config
        await _check_tcp_reachable(config.url, timeout_seconds)
        headers = resolve_headers(config)
        read_stream, write_stream, _get_session_id = await stack.enter_async_context(
            streamablehttp_client(config.url, headers=headers or None)
        )
    else:
        params = StdioServerParameters(command=config.command, args=config.args or [])
        read_stream, write_stream = await stack.enter_async_context(stdio_client(params))

    session = await stack.enter_async_context(
        ClientSession(read_stream, write_stream, read_timeout_seconds=timedelta(seconds=timeout_seconds))
    )
    await session.initialize()
    return session
