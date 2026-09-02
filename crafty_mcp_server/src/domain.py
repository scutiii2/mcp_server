"""Controlling registered Crafty worlds - the part worth testing.

A "world" here is a name registered against ``registry.py``: which
Crafty Controller it lives on, which server id Crafty knows it as, and
the API token to use. Every function below resolves that record first,
so an unregistered name fails with the names that *are* registered.

``register_world`` takes the default base URL/verify_ssl as parameters
rather than reading a settings object directly, so this module stays
testable without monkeypatching global settings - ``server.py``
resolves those defaults (from the environment) and passes them in.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src import crafty_client, registry
from src.contract import (
    DefaultBaseUrlResult,
    PingBaseUrlResult,
    WorldActionResult,
    WorldCommandResult,
    WorldInfo,
    WorldListResult,
    WorldRegisterResult,
    WorldRemoveResult,
    WorldStatusResult,
)


def _bytes_to_human_readable(num_bytes: Any) -> str | None:
    if num_bytes is None:
        return None
    try:
        value = float(num_bytes)
    except (TypeError, ValueError):
        return None

    kb = 1024
    mb = kb**2
    gb = kb**3
    if value >= gb:
        return f"{value / gb:.2f} GB"
    if value >= mb:
        return f"{value / mb:.2f} MB"
    if value >= kb:
        return f"{value / kb:.2f} KB"
    return f"{value:.0f} Bytes"


def _resolve_base_url(
    db_path: Path,
    base_url: str | None,
    verify_ssl: bool | None,
    default_base_url: str,
    default_verify_ssl: bool,
) -> tuple[str, bool]:
    """The base_url/verify_ssl any crafty tool that accepts an optional
    ``base_url`` actually uses, in precedence order: the explicit
    argument, then the default set live via ``set_default_base_url``
    (``registry``'s ``default_config`` table), then
    ``default_base_url``/``default_verify_ssl`` (this deployment's
    ``CRAFTY_BASE_URL`` env var, resolved by the caller). Returns
    ``("", ...)`` when nothing resolves - the caller decides whether an
    empty result is an error (``register_world``) or something to report
    (there's nothing to ping either, so ``ping_base_url`` also raises).
    """
    stored_default = registry.get_default(db_path)

    resolved_base_url = (base_url or "").strip()
    if not resolved_base_url and stored_default is not None:
        resolved_base_url = stored_default.base_url
    if not resolved_base_url:
        resolved_base_url = (default_base_url or "").strip()

    if verify_ssl is not None:
        resolved_verify_ssl = verify_ssl
    elif stored_default is not None:
        resolved_verify_ssl = stored_default.verify_ssl
    else:
        resolved_verify_ssl = default_verify_ssl

    return resolved_base_url, resolved_verify_ssl


_NO_BASE_URL_MESSAGE = (
    "No base_url was given, no default has been set (see set_default_base_url), "
    "and no default Crafty URL is configured for this deployment (CRAFTY_BASE_URL). "
    "Pass base_url explicitly, call crafty_set_default_base_url, or set that "
    "environment variable."
)


def register_world(
    db_path: Path,
    name: str,
    *,
    api_token: str,
    server_id: str,
    base_url: str | None,
    verify_ssl: bool | None,
    default_base_url: str,
    default_verify_ssl: bool,
) -> WorldRegisterResult:
    """Register (or re-register) a world. See ``_resolve_base_url`` for
    where ``base_url``/``verify_ssl`` come from when omitted. Raises if
    nothing resolves a ``base_url``, since there is nowhere else that
    value could come from.
    """
    resolved_base_url, resolved_verify_ssl = _resolve_base_url(
        db_path, base_url, verify_ssl, default_base_url, default_verify_ssl
    )
    if not resolved_base_url:
        raise KeyError(_NO_BASE_URL_MESSAGE)

    record = registry.register(
        db_path,
        name,
        server_id=server_id,
        api_token=api_token,
        base_url=resolved_base_url,
        verify_ssl=resolved_verify_ssl,
    )
    return WorldRegisterResult(
        name=record.name,
        base_url=record.base_url,
        server_id=record.server_id,
        message=(
            f"World {record.name!r} registered against {record.base_url} "
            f"(server {record.server_id})."
        ),
    )


def set_default_base_url(db_path: Path, *, base_url: str, verify_ssl: bool = True) -> DefaultBaseUrlResult:
    """Set the default Crafty instance ``register_world`` falls back to
    when a call doesn't supply its own ``base_url``. Takes effect
    immediately for the next registration - no restart required, unlike
    changing ``CRAFTY_BASE_URL``."""
    stored = registry.set_default(db_path, base_url=base_url, verify_ssl=verify_ssl)
    return DefaultBaseUrlResult(
        base_url=stored.base_url,
        verify_ssl=stored.verify_ssl,
        message=(
            f"Default Crafty base_url set to {stored.base_url} "
            f"(verify_ssl={stored.verify_ssl}). Future registrations that don't name their "
            f"own base_url will use this."
        ),
    )


async def ping_base_url(
    db_path: Path,
    *,
    base_url: str | None,
    verify_ssl: bool | None,
    default_base_url: str,
    default_verify_ssl: bool,
) -> PingBaseUrlResult:
    """Check whether a Crafty instance answers over the network, without
    needing a registered world - see ``_resolve_base_url`` for where
    ``base_url``/``verify_ssl`` come from when omitted. Never raises for
    an unreachable target: that's the normal, expected answer to "is
    this up", not a failure of the tool call itself. Only raises when
    there's no URL to even attempt, same as ``register_world``.
    """
    resolved_base_url, resolved_verify_ssl = _resolve_base_url(
        db_path, base_url, verify_ssl, default_base_url, default_verify_ssl
    )
    if not resolved_base_url:
        raise KeyError(_NO_BASE_URL_MESSAGE)

    result = await crafty_client.ping(resolved_base_url, verify_ssl=resolved_verify_ssl)

    if result.reachable:
        message = f"{resolved_base_url} is reachable (HTTP {result.status_code}, {result.latency_ms:.0f} ms)."
    else:
        message = f"{resolved_base_url} is not reachable: {result.error}"

    return PingBaseUrlResult(
        base_url=resolved_base_url,
        reachable=result.reachable,
        status_code=result.status_code,
        latency_ms=result.latency_ms,
        error=result.error,
        message=message,
    )


def list_worlds(db_path: Path) -> WorldListResult:
    records = registry.list_all(db_path)
    worlds = [
        WorldInfo(name=r.name, base_url=r.base_url, server_id=r.server_id, verify_ssl=r.verify_ssl)
        for r in records
    ]

    if not worlds:
        report = "No worlds are registered."
    else:
        width = max(len(world.name) for world in worlds)
        report = "\n".join(
            f"{world.name:<{width}}  {world.base_url} (server {world.server_id})" for world in worlds
        )

    return WorldListResult(worlds=worlds, report=report)


def remove_world(db_path: Path, name: str) -> WorldRemoveResult:
    """Delete a world's registration. It stops being controllable by any
    crafty_world_* tool until it's registered again - the world itself,
    on Crafty, is untouched."""
    registry.remove(db_path, name)
    return WorldRemoveResult(
        name=name,
        message=f"World {name!r} removed. Register it again before controlling it.",
    )


async def _act(db_path: Path, name: str, crafty_action: str, label: str, verb: str) -> WorldActionResult:
    world = registry.get(db_path, name)
    await crafty_client.action(
        world.base_url, world.api_token, world.server_id, crafty_action, verify_ssl=world.verify_ssl
    )
    return WorldActionResult(name=name, action=label, message=f"{name} {verb}.")


async def start_world(db_path: Path, name: str) -> WorldActionResult:
    return await _act(db_path, name, "start_server", "start", "started")


async def stop_world(db_path: Path, name: str) -> WorldActionResult:
    return await _act(db_path, name, "stop_server", "stop", "stopped")


async def restart_world(db_path: Path, name: str) -> WorldActionResult:
    return await _act(db_path, name, "restart_server", "restart", "restarted")


async def send_command(db_path: Path, name: str, command: str) -> WorldCommandResult:
    world = registry.get(db_path, name)
    await crafty_client.send_command(
        world.base_url, world.api_token, world.server_id, command, verify_ssl=world.verify_ssl
    )
    return WorldCommandResult(name=name, command=command, message=f"Sent to {name}: {command!r}")


def _parse_players(raw: Any) -> list[str]:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            raw = []
    if not isinstance(raw, list):
        return []
    return [str(player) for player in raw]


async def get_status(db_path: Path, name: str) -> WorldStatusResult:
    world = registry.get(db_path, name)
    payload = await crafty_client.stats(world.base_url, world.api_token, world.server_id, verify_ssl=world.verify_ssl)
    data = payload.get("data") or {}

    online = int(data.get("online") or 0)
    maximum = int(data.get("max") or 0)
    version = data.get("version") or "Unknown"

    report = (
        f"{name}: {'running' if data.get('running') else 'stopped'}, "
        f"{online}/{maximum} players, version {version}"
    )

    return WorldStatusResult(
        name=name,
        running=data.get("running"),
        online=online,
        max=maximum,
        players=_parse_players(data.get("players")),
        version=version,
        cpu=data.get("cpu"),
        mem=_bytes_to_human_readable(data.get("mem")),
        world_name=data.get("world_name"),
        report=report,
    )
