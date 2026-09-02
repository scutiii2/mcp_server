"""Tests for registry.py - real tmp_path SQLite, no mocking.

The one property that matters here: the API token is stored and handed
back to a caller that needs it to reach Crafty, but never appears in a
listing - that's what keeps it out of a tool result a model could relay.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src import registry


def test_register_then_get_round_trips_every_field(tmp_path: Path):
    db = tmp_path / "worlds.db"

    registered = registry.register(
        db,
        "survival",
        server_id="abc123",
        api_token="secret-token",
        base_url="https://crafty.example.com:8443",
        verify_ssl=True,
    )

    fetched = registry.get(db, "survival")

    assert registered == fetched
    assert fetched.name == "survival"
    assert fetched.server_id == "abc123"
    assert fetched.api_token == "secret-token"
    assert fetched.base_url == "https://crafty.example.com:8443"
    assert fetched.verify_ssl is True


def test_registering_the_same_name_again_overwrites_the_old_entry(tmp_path: Path):
    db = tmp_path / "worlds.db"
    registry.register(
        db, "survival", server_id="old", api_token="old-token",
        base_url="https://old.example.com", verify_ssl=True,
    )

    registry.register(
        db, "survival", server_id="new", api_token="new-token",
        base_url="https://new.example.com", verify_ssl=False,
    )

    fetched = registry.get(db, "survival")
    assert fetched.server_id == "new"
    assert fetched.api_token == "new-token"
    assert fetched.verify_ssl is False
    assert len(registry.list_all(db)) == 1


def test_unknown_world_name_lists_the_names_that_exist(tmp_path: Path):
    db = tmp_path / "worlds.db"
    registry.register(db, "survival", server_id="a", api_token="t", base_url="https://x", verify_ssl=True)
    registry.register(db, "creative", server_id="b", api_token="t", base_url="https://x", verify_ssl=True)

    with pytest.raises(KeyError) as error:
        registry.get(db, "skyblock")

    message = str(error.value)
    assert "survival" in message and "creative" in message


def test_remove_deletes_a_registered_world(tmp_path: Path):
    db = tmp_path / "worlds.db"
    registry.register(db, "survival", server_id="a", api_token="t", base_url="https://x", verify_ssl=True)

    registry.remove(db, "survival")

    assert registry.list_all(db) == []


def test_remove_leaves_other_worlds_untouched(tmp_path: Path):
    db = tmp_path / "worlds.db"
    registry.register(db, "survival", server_id="a", api_token="t", base_url="https://x", verify_ssl=True)
    registry.register(db, "creative", server_id="b", api_token="t", base_url="https://x", verify_ssl=True)

    registry.remove(db, "survival")

    names = [world.name for world in registry.list_all(db)]
    assert names == ["creative"]


def test_removing_an_unregistered_name_lists_the_names_that_exist(tmp_path: Path):
    db = tmp_path / "worlds.db"
    registry.register(db, "survival", server_id="a", api_token="t", base_url="https://x", verify_ssl=True)

    with pytest.raises(KeyError) as error:
        registry.remove(db, "skyblock")

    assert "survival" in str(error.value)


def test_removing_from_an_empty_registry_says_so(tmp_path: Path):
    db = tmp_path / "worlds.db"

    with pytest.raises(KeyError, match="No worlds"):
        registry.remove(db, "anything")


def test_no_worlds_registered_at_all_says_so(tmp_path: Path):
    db = tmp_path / "worlds.db"

    with pytest.raises(KeyError, match="No worlds"):
        registry.get(db, "anything")


def test_list_all_is_sorted_by_name(tmp_path: Path):
    db = tmp_path / "worlds.db"
    registry.register(db, "survival", server_id="a", api_token="t", base_url="https://x", verify_ssl=True)
    registry.register(db, "creative", server_id="b", api_token="t", base_url="https://x", verify_ssl=True)

    names = [world.name for world in registry.list_all(db)]
    assert names == ["creative", "survival"]


def test_list_all_is_empty_for_a_fresh_database(tmp_path: Path):
    db = tmp_path / "worlds.db"

    assert registry.list_all(db) == []


# --- default base_url --------------------------------------------------


def test_get_default_is_none_when_nothing_has_been_set(tmp_path: Path):
    db = tmp_path / "worlds.db"

    assert registry.get_default(db) is None


def test_set_default_then_get_default_round_trips(tmp_path: Path):
    db = tmp_path / "worlds.db"

    set_result = registry.set_default(db, base_url="https://crafty.example.com", verify_ssl=False)
    fetched = registry.get_default(db)

    assert set_result == fetched
    assert fetched.base_url == "https://crafty.example.com"
    assert fetched.verify_ssl is False


def test_setting_the_default_again_overwrites_the_old_value(tmp_path: Path):
    db = tmp_path / "worlds.db"
    registry.set_default(db, base_url="https://old.example.com", verify_ssl=True)

    registry.set_default(db, base_url="https://new.example.com", verify_ssl=False)

    fetched = registry.get_default(db)
    assert fetched.base_url == "https://new.example.com"
    assert fetched.verify_ssl is False
