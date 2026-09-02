"""Tests for suggestions.py.

Real tmp_path SQLite via registry.py, same "real store, no mocking"
convention as test_registry.py - what's under test here is only
apply_suggestions()'s own behavior: which (tool, param) pairs it
touches, that values come back deduplicated/ordered correctly, and that
a broken provider never breaks the listing.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from mcp import types

from src import registry, suggestions


def _tool(tool_name: str, **properties: dict) -> types.Tool:
    return types.Tool(
        name=tool_name,
        inputSchema={"type": "object", "properties": {k: dict(v) for k, v in properties.items()}},
    )


def _register(db_path: Path, name: str, base_url: str) -> None:
    registry.register(db_path, name, server_id="srv", api_token="tok", base_url=base_url, verify_ssl=True)


def test_world_names_populate_every_name_taking_tool(tmp_path: Path):
    db = tmp_path / "worlds.db"
    _register(db, "survival", "https://crafty.example.com")

    tools = [
        _tool(name, name={})
        for name in (
            "crafty_world_start", "crafty_world_stop", "crafty_world_restart",
            "crafty_world_remove", "crafty_world_send_command", "crafty_world_get_status",
        )
    ]
    suggestions.apply_suggestions(tools, db)

    for tool in tools:
        assert tool.inputSchema["properties"]["name"]["enum"] == ["survival"]


def test_base_urls_are_deduplicated_in_first_seen_order(tmp_path: Path):
    """registry.list_all() orders by name, so "first seen" here means
    first alphabetically by world name, not registration order - these
    names are chosen so that order is also the order the assertion
    checks: "a_world"/"c_world" share a base_url, "b_world" sorts
    between them by name but not by which base_url appears first."""
    db = tmp_path / "worlds.db"
    _register(db, "a_world", "https://a.example.com")
    _register(db, "b_world", "https://b.example.com")
    _register(db, "c_world", "https://a.example.com")

    tool = _tool("crafty_world_register", base_url={"type": "string"})
    suggestions.apply_suggestions([tool], db)

    assert tool.inputSchema["properties"]["base_url"]["enum"] == ["https://a.example.com", "https://b.example.com"]


def test_leaves_a_param_with_no_registered_provider_untouched(tmp_path: Path):
    db = tmp_path / "worlds.db"
    tool = _tool("crafty_world_register", name={"type": "string"})

    suggestions.apply_suggestions([tool], db)

    assert "enum" not in tool.inputSchema["properties"]["name"]


def test_leaves_a_tool_with_no_properties_untouched(tmp_path: Path):
    db = tmp_path / "worlds.db"
    tool = types.Tool(name="crafty_world_list", inputSchema={"type": "object", "properties": {}})

    suggestions.apply_suggestions([tool], db)  # must not raise

    assert tool.inputSchema["properties"] == {}


def test_a_raising_provider_drops_only_its_own_field_not_the_whole_tool(tmp_path: Path):
    db = tmp_path / "worlds.db"
    tool = _tool("crafty_world_start", name={"type": "string"})

    with patch("src.suggestions.registry.list_all", side_effect=OSError("db locked")):
        suggestions.apply_suggestions([tool], db)  # must not raise

    assert "enum" not in tool.inputSchema["properties"]["name"]


def test_an_empty_result_leaves_no_enum_key_rather_than_an_empty_one(tmp_path: Path):
    db = tmp_path / "worlds.db"
    tool = _tool("crafty_world_start", name={"type": "string"})

    suggestions.apply_suggestions([tool], db)

    assert "enum" not in tool.inputSchema["properties"]["name"]
