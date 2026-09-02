"""Thin async client for the Crafty Controller v2 REST API.

Every function here is stateless per call - no session held across
calls, no client cached at import time. These calls are infrequent and
human-paced (start a world, check its status), so there's no real
round-trip cost being saved by keeping a connection open between them;
and a session held across calls would mean one world's unreachable
Crafty instance could leave a dangling connection that outlives the
call that opened it.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import aiohttp


class CraftyError(Exception):
    """Raised when Crafty is unreachable, misconfigured, or returns an error."""


@dataclass(frozen=True)
class PingResult:
    reachable: bool
    status_code: int | None
    error: str | None
    latency_ms: float | None


# Deliberately a strict subset of Crafty's own action set (which also
# has "kill_server"): nothing in this project calls kill, and an action
# nothing can reach is not worth a guard elsewhere staying honest about.
VALID_ACTIONS = {"start_server", "stop_server", "restart_server"}


async def _request(
    method: str,
    base_url: str,
    path: str,
    *,
    api_token: str,
    verify_ssl: bool,
    **kwargs: Any,
) -> dict[str, Any]:
    url = f"{base_url.rstrip('/')}{path}"
    connector = aiohttp.TCPConnector(ssl=verify_ssl)

    try:
        async with aiohttp.ClientSession(
            headers={"Authorization": f"Bearer {api_token}"},
            connector=connector,
            timeout=aiohttp.ClientTimeout(total=10),
        ) as session:
            async with session.request(method, url, **kwargs) as response:
                payload = await response.json(content_type=None)
    except (aiohttp.ClientError, ValueError) as error:
        raise CraftyError(f"Could not reach Crafty at {base_url}: {error}") from error

    if payload.get("status") != "ok":
        raise CraftyError(payload.get("error") or "Unknown Crafty API error.")

    return payload


async def stats(base_url: str, api_token: str, server_id: str, *, verify_ssl: bool = True) -> dict[str, Any]:
    """GET /servers/{id}/stats - running state, online/max players, version, etc."""
    return await _request(
        "GET", base_url, f"/api/v2/servers/{server_id}/stats", api_token=api_token, verify_ssl=verify_ssl
    )


async def action(
    base_url: str, api_token: str, server_id: str, action_name: str, *, verify_ssl: bool = True
) -> None:
    """POST /servers/{id}/action/{action} - start/stop/restart."""
    if action_name not in VALID_ACTIONS:
        raise ValueError(f"Unsupported Crafty action: {action_name}")
    await _request(
        "POST",
        base_url,
        f"/api/v2/servers/{server_id}/action/{action_name}",
        api_token=api_token,
        verify_ssl=verify_ssl,
    )


async def ping(base_url: str, *, verify_ssl: bool = True, timeout: float = 5.0) -> PingResult:
    """GET the bare base_url and report whether anything answered.

    Deliberately doesn't go through ``_request``: there's no server id or
    API token yet - the whole point is checking reachability *before*
    those are known to be right - and Crafty's root serves its login
    page (HTML), not the ``{"status": "ok"}`` JSON envelope every other
    call here expects.

    Any HTTP response at all counts as reachable, including a 401 or
    404 - that still proves something on the other end answered, which
    is the entire question this asks. Whether the URL, token, or server
    id are actually *right* is what ``stats``/``action``/``send_command``
    answer instead. Only a connection-level failure (DNS, refused,
    timed out, TLS) counts as unreachable.
    """
    url = base_url.rstrip("/")
    connector = aiohttp.TCPConnector(ssl=verify_ssl)
    started = time.monotonic()

    try:
        async with aiohttp.ClientSession(
            connector=connector, timeout=aiohttp.ClientTimeout(total=timeout)
        ) as session:
            async with session.get(url) as response:
                elapsed_ms = (time.monotonic() - started) * 1000
                return PingResult(reachable=True, status_code=response.status, error=None, latency_ms=elapsed_ms)
    except (aiohttp.ClientError, TimeoutError) as error:
        # TimeoutError's own str() is usually empty, unlike aiohttp's
        # ClientError subclasses which describe themselves - so it's the
        # one case that needs a message manufactured rather than relayed.
        if isinstance(error, TimeoutError):
            message = str(error) or f"Timed out after {timeout}s"
        else:
            message = str(error) or type(error).__name__
        return PingResult(reachable=False, status_code=None, error=message, latency_ms=None)


async def send_command(
    base_url: str, api_token: str, server_id: str, command: str, *, verify_ssl: bool = True
) -> None:
    """POST /servers/{id}/stdin - raw console command, no leading slash."""
    await _request(
        "POST",
        base_url,
        f"/api/v2/servers/{server_id}/stdin",
        api_token=api_token,
        verify_ssl=verify_ssl,
        data=command,
        headers={"Content-Type": "text/plain"},
    )
