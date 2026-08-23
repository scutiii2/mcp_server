"""Tests for the crafty capability's domain logic.

The world registry is real SQLite (``tmp_path``), same convention as
``test_otp_domain.py`` treating its SQLite store as real while patching
the network call - here that's ``infra/crafty.py``'s ``stats``/``action``/
``send_command``, which would otherwise reach a real Crafty instance.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from src.capabilities.crafty import domain
from src.infra import crafty, crafty_registry


def _register(db_path: Path, name: str = "survival", **overrides):
    defaults = dict(
        server_id="srv1",
        api_token="tok3n",
        base_url="https://crafty.example.com",
        verify_ssl=True,
    )
    defaults.update(overrides)
    return crafty_registry.register(db_path, name, **defaults)


# --- register_world --------------------------------------------------------


def test_register_world_uses_the_given_base_url(tmp_path: Path):
    db = tmp_path / "worlds.db"

    result = domain.register_world(
        db, "survival", api_token="tok3n", server_id="srv1",
        base_url="https://crafty.example.com", verify_ssl=True,
        default_base_url="", default_verify_ssl=True,
    )

    assert result.base_url == "https://crafty.example.com"
    stored = crafty_registry.get(db, "survival")
    assert stored.api_token == "tok3n"


def test_register_world_falls_back_to_the_configured_default_base_url(tmp_path: Path):
    db = tmp_path / "worlds.db"

    result = domain.register_world(
        db, "survival", api_token="tok3n", server_id="srv1",
        base_url=None, verify_ssl=None,
        default_base_url="https://default.example.com", default_verify_ssl=True,
    )

    assert result.base_url == "https://default.example.com"


def test_register_world_without_a_base_url_or_a_default_raises(tmp_path: Path):
    db = tmp_path / "worlds.db"

    with pytest.raises(KeyError, match="base_url"):
        domain.register_world(
            db, "survival", api_token="tok3n", server_id="srv1",
            base_url=None, verify_ssl=None,
            default_base_url="", default_verify_ssl=True,
        )


def test_register_world_prefers_an_explicit_base_url_over_a_stored_default(tmp_path: Path):
    db = tmp_path / "worlds.db"
    crafty_registry.set_default(db, base_url="https://stored.example.com", verify_ssl=True)

    result = domain.register_world(
        db, "survival", api_token="tok3n", server_id="srv1",
        base_url="https://explicit.example.com", verify_ssl=None,
        default_base_url="", default_verify_ssl=True,
    )

    assert result.base_url == "https://explicit.example.com"


def test_register_world_uses_a_stored_default_over_the_env_fallback(tmp_path: Path):
    db = tmp_path / "worlds.db"
    crafty_registry.set_default(db, base_url="https://stored.example.com", verify_ssl=False)

    result = domain.register_world(
        db, "survival", api_token="tok3n", server_id="srv1",
        base_url=None, verify_ssl=None,
        default_base_url="https://env.example.com", default_verify_ssl=True,
    )

    assert result.base_url == "https://stored.example.com"
    stored = crafty_registry.get(db, "survival")
    assert stored.verify_ssl is False


# --- set_default_base_url ---------------------------------------------------


def test_set_default_base_url_persists_it_for_a_later_registration(tmp_path: Path):
    db = tmp_path / "worlds.db"

    result = domain.set_default_base_url(db, base_url="https://stored.example.com", verify_ssl=False)

    assert result.base_url == "https://stored.example.com"
    assert result.verify_ssl is False
    stored = crafty_registry.get_default(db)
    assert stored.base_url == "https://stored.example.com"
    assert stored.verify_ssl is False


def test_set_default_base_url_defaults_verify_ssl_to_true(tmp_path: Path):
    db = tmp_path / "worlds.db"

    result = domain.set_default_base_url(db, base_url="https://stored.example.com")

    assert result.verify_ssl is True


# --- ping_base_url -----------------------------------------------------------


@pytest.mark.anyio
async def test_ping_base_url_pings_the_explicitly_given_url(tmp_path: Path):
    db = tmp_path / "worlds.db"
    fake_ping = AsyncMock(return_value=crafty.PingResult(reachable=True, status_code=200, error=None, latency_ms=12.5))

    with patch("src.capabilities.crafty.domain.crafty.ping", new=fake_ping):
        result = await domain.ping_base_url(
            db, base_url="https://explicit.example.com", verify_ssl=None,
            default_base_url="", default_verify_ssl=True,
        )

    fake_ping.assert_called_once_with("https://explicit.example.com", verify_ssl=True)
    assert result.base_url == "https://explicit.example.com"
    assert result.reachable is True
    assert result.status_code == 200
    assert result.latency_ms == 12.5


@pytest.mark.anyio
async def test_ping_base_url_falls_back_to_the_stored_default(tmp_path: Path):
    db = tmp_path / "worlds.db"
    crafty_registry.set_default(db, base_url="https://stored.example.com", verify_ssl=False)
    fake_ping = AsyncMock(return_value=crafty.PingResult(reachable=True, status_code=200, error=None, latency_ms=5.0))

    with patch("src.capabilities.crafty.domain.crafty.ping", new=fake_ping):
        result = await domain.ping_base_url(
            db, base_url=None, verify_ssl=None,
            default_base_url="https://env.example.com", default_verify_ssl=True,
        )

    fake_ping.assert_called_once_with("https://stored.example.com", verify_ssl=False)
    assert result.base_url == "https://stored.example.com"


@pytest.mark.anyio
async def test_ping_base_url_reports_an_unreachable_result_without_raising(tmp_path: Path):
    db = tmp_path / "worlds.db"
    fake_ping = AsyncMock(
        return_value=crafty.PingResult(reachable=False, status_code=None, error="Connection refused", latency_ms=None)
    )

    with patch("src.capabilities.crafty.domain.crafty.ping", new=fake_ping):
        result = await domain.ping_base_url(
            db, base_url="https://down.example.com", verify_ssl=None,
            default_base_url="", default_verify_ssl=True,
        )

    assert result.reachable is False
    assert result.error == "Connection refused"
    assert "not reachable" in result.message.lower()


@pytest.mark.anyio
async def test_ping_base_url_without_a_url_or_a_default_raises(tmp_path: Path):
    db = tmp_path / "worlds.db"

    with pytest.raises(KeyError, match="base_url"):
        await domain.ping_base_url(
            db, base_url=None, verify_ssl=None, default_base_url="", default_verify_ssl=True
        )


# --- list_worlds -------------------------------------------------------------


def test_list_worlds_report_is_readable_text(tmp_path: Path):
    db = tmp_path / "worlds.db"
    _register(db, "survival")

    result = domain.list_worlds(db)

    assert result.worlds[0].name == "survival"
    assert "survival" in result.report


def test_list_worlds_with_none_registered_says_so(tmp_path: Path):
    db = tmp_path / "worlds.db"

    result = domain.list_worlds(db)

    assert result.worlds == []
    assert "No worlds" in result.report


# --- remove_world --------------------------------------------------------


def test_remove_world_deletes_the_registration(tmp_path: Path):
    db = tmp_path / "worlds.db"
    _register(db, "survival")

    result = domain.remove_world(db, "survival")

    assert result.name == "survival"
    assert domain.list_worlds(db).worlds == []


def test_remove_world_with_an_unknown_name_lists_the_names_that_exist(tmp_path: Path):
    db = tmp_path / "worlds.db"
    _register(db, "survival")

    with pytest.raises(KeyError, match="survival"):
        domain.remove_world(db, "creative")


# --- start / stop / restart --------------------------------------------------


@pytest.mark.anyio
async def test_start_world_calls_the_start_action_on_the_right_world(tmp_path: Path):
    db = tmp_path / "worlds.db"
    _register(db, "survival", server_id="srv1", api_token="tok3n")

    with patch("src.capabilities.crafty.domain.crafty.action", new=AsyncMock()) as mock_action:
        result = await domain.start_world(db, "survival")

    mock_action.assert_called_once_with(
        "https://crafty.example.com", "tok3n", "srv1", "start_server", verify_ssl=True
    )
    assert result.action == "start"
    assert "survival" in result.message


@pytest.mark.anyio
async def test_stop_world_calls_the_stop_action(tmp_path: Path):
    db = tmp_path / "worlds.db"
    _register(db, "survival")

    with patch("src.capabilities.crafty.domain.crafty.action", new=AsyncMock()) as mock_action:
        result = await domain.stop_world(db, "survival")

    assert mock_action.call_args.args[3] == "stop_server"
    assert result.action == "stop"


@pytest.mark.anyio
async def test_restart_world_calls_the_restart_action(tmp_path: Path):
    db = tmp_path / "worlds.db"
    _register(db, "survival")

    with patch("src.capabilities.crafty.domain.crafty.action", new=AsyncMock()) as mock_action:
        result = await domain.restart_world(db, "survival")

    assert mock_action.call_args.args[3] == "restart_server"
    assert result.action == "restart"


@pytest.mark.anyio
async def test_unregistered_world_name_lists_the_names_that_exist(tmp_path: Path):
    db = tmp_path / "worlds.db"
    _register(db, "survival")

    with pytest.raises(KeyError, match="survival"):
        await domain.start_world(db, "creative")


# --- send_command ------------------------------------------------------------


@pytest.mark.anyio
async def test_send_command_relays_to_the_right_worlds_console(tmp_path: Path):
    db = tmp_path / "worlds.db"
    _register(db, "survival", server_id="srv1", api_token="tok3n")

    with patch("src.capabilities.crafty.domain.crafty.send_command", new=AsyncMock()) as mock_send:
        result = await domain.send_command(db, "survival", "say hello")

    mock_send.assert_called_once_with(
        "https://crafty.example.com", "tok3n", "srv1", "say hello", verify_ssl=True
    )
    assert result.command == "say hello"


# --- get_status ----------------------------------------------------------


@pytest.mark.anyio
async def test_get_status_parses_the_stats_payload(tmp_path: Path):
    db = tmp_path / "worlds.db"
    _register(db, "survival")
    payload = {
        "status": "ok",
        "data": {
            "running": True,
            "online": 2,
            "max": 20,
            "players": ["alice", "bob"],
            "version": "1.21.1",
            "cpu": 12.5,
            "mem": 1073741824,
            "world_name": "world",
        },
    }

    with patch("src.capabilities.crafty.domain.crafty.stats", new=AsyncMock(return_value=payload)):
        result = await domain.get_status(db, "survival")

    assert result.running is True
    assert result.online == 2
    assert result.max == 20
    assert result.players == ["alice", "bob"]
    assert result.version == "1.21.1"
    assert result.mem == "1.00 GB"
    assert result.world_name == "world"


@pytest.mark.anyio
async def test_get_status_parses_players_given_as_a_json_string(tmp_path: Path):
    """Crafty's stats endpoint sometimes returns the players list JSON-
    encoded inside a string rather than as a real array."""
    db = tmp_path / "worlds.db"
    _register(db, "survival")
    payload = {"status": "ok", "data": {"players": '["alice", "bob"]'}}

    with patch("src.capabilities.crafty.domain.crafty.stats", new=AsyncMock(return_value=payload)):
        result = await domain.get_status(db, "survival")

    assert result.players == ["alice", "bob"]


@pytest.mark.anyio
async def test_get_status_defaults_missing_fields_rather_than_raising(tmp_path: Path):
    db = tmp_path / "worlds.db"
    _register(db, "survival")
    payload = {"status": "ok", "data": {}}

    with patch("src.capabilities.crafty.domain.crafty.stats", new=AsyncMock(return_value=payload)):
        result = await domain.get_status(db, "survival")

    assert result.online == 0
    assert result.max == 0
    assert result.players == []
    assert result.version == "Unknown"
    assert result.mem is None
