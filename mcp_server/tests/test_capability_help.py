"""Tests for capability_help.py's build_help() - the target/command
rendering logic behind GET /commands/help/{capability}. Uses a temp
help.json plus an isolated capability_meta registry, same "swap in
isolated state" pattern as test_command_routes.py."""

from __future__ import annotations

import json

import pytest
from mcp.server.fastmcp import FastMCP

from src import capability_help
from src.services import capability_meta, capability_registry


@pytest.fixture(autouse=True)
def _isolated_capability_meta(monkeypatch):
    monkeypatch.setattr(capability_meta, "_BY_FOLDER", {})
    monkeypatch.setattr(capability_registry, "_REGISTRY", {})


@pytest.fixture
def widget_help(tmp_path, monkeypatch):
    capability_meta.register(folder="widgets", id="widget", label="Widgets")
    folder = tmp_path / "widgets"
    folder.mkdir()
    data = {
        "summary": "Makes widgets.",
        "tools": [
            {
                "name": "make_widget_tool",
                "purpose": "Make one.",
                "connection": "SSH",
                "commands": ["make"],
            },
            {
                "name": "hidden_tool",
                "purpose": "Internal only.",
                "connection": "none",
                "commands": [],
            },
        ],
        "commands": [
            {
                "name": "make",
                "tool": "make_widget_tool",
                "params": [
                    {"name": "color", "required": True, "default": None, "description": "Widget color."},
                    {"name": "count", "required": False, "default": 1, "description": "How many to make."},
                ],
            }
        ],
        "workflow": [
            {"sequence": "1", "tool": "make_widget_tool", "ai_only_step": False, "explanation": "Make the widget."}
        ],
    }
    (folder / "help.json").write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(capability_help, "_CAPABILITIES_DIR", tmp_path)
    return data


def test_build_help_target_all_includes_every_table(widget_help):
    result = capability_help.build_help("widget", target="all")

    assert len(result["tools"]) == 2
    assert len(result["commands"]) == 1
    assert len(result["workflow"]) == 1
    assert "Makes widgets." in result["message"]


def test_build_help_target_tools_only_includes_tools_table(widget_help):
    result = capability_help.build_help("widget", target="tools")

    assert "tools" in result
    assert "commands" not in result
    assert "workflow" not in result


def test_build_help_target_commands_only_includes_commands_table(widget_help):
    result = capability_help.build_help("widget", target="commands")

    assert "commands" in result
    assert "tools" not in result
    assert "workflow" not in result


def test_build_help_target_workflow_only_includes_workflow_table(widget_help):
    result = capability_help.build_help("widget", target="workflow")

    assert "workflow" in result
    assert "tools" not in result
    assert "commands" not in result


def test_build_help_tool_row_prefixes_capability_id_onto_slash_command(widget_help):
    result = capability_help.build_help("widget", target="tools")

    row = next(t for t in result["tools"] if t["tool"] == "make_widget_tool")
    assert row["slash_command"] == "/widget make"


def test_build_help_tool_with_no_command_says_mcp_only(widget_help):
    result = capability_help.build_help("widget", target="tools")

    row = next(t for t in result["tools"] if t["tool"] == "hidden_tool")
    assert row["slash_command"] == "none (MCP-only)"


def test_build_help_command_row_lists_every_param(widget_help):
    result = capability_help.build_help("widget", target="commands")

    row = result["commands"][0]
    assert row["slash_command"] == "/widget make"
    assert "color (required) - Widget color." in row["parameters"]
    assert "count (optional, default 1) - How many to make." in row["parameters"]


def test_build_help_for_one_command_includes_its_tool_and_workflow_step(widget_help):
    result = capability_help.build_help("widget", command="make")

    assert result["commands"][0]["slash_command"] == "/widget make"
    assert result["tools"][0]["tool"] == "make_widget_tool"
    assert result["workflow"][0]["tool"] == "make_widget_tool"
    assert "Make one." in result["message"]


def test_build_help_command_takes_priority_over_target(widget_help):
    result = capability_help.build_help("widget", target="workflow", command="make")

    assert "commands" in result
    assert result["commands"][0]["slash_command"] == "/widget make"


def test_build_help_unknown_target_raises_help_error(widget_help):
    with pytest.raises(capability_help.HelpError, match="target"):
        capability_help.build_help("widget", target="bogus")


def test_build_help_unknown_command_raises_help_error(widget_help):
    with pytest.raises(capability_help.HelpError, match="make"):
        capability_help.build_help("widget", command="bogus")


def test_build_help_unknown_capability_raises_help_error():
    with pytest.raises(capability_help.HelpError, match="nope"):
        capability_help.build_help("nope")


# --- build_index ------------------------------------------------------------


def _register_capability(tmp_path, folder, id, label, summary, command_names):  # noqa: A002
    capability_meta.register(folder=folder, id=id, label=label)
    fake_mcp = FastMCP(name=f"test-{id}")
    with capability_registry.capturing(fake_mcp, id, label=label):
        pass  # no real tools needed for these tests - only the registry entry
    folder_path = tmp_path / folder
    folder_path.mkdir()
    data = {
        "summary": summary,
        "tools": [],
        "commands": [{"name": name, "tool": f"{name}_tool", "params": []} for name in command_names],
        "workflow": [],
    }
    (folder_path / "help.json").write_text(json.dumps(data), encoding="utf-8")


@pytest.fixture
def two_capabilities(tmp_path, monkeypatch):
    _register_capability(tmp_path, "widgets", "widget", "Widgets", "Makes widgets.", ["make"])
    _register_capability(tmp_path, "gadgets", "gadget", "Gadgets", "Makes gadgets.", ["build", "inspect"])
    monkeypatch.setattr(capability_help, "_CAPABILITIES_DIR", tmp_path)


def test_build_index_lists_every_enabled_capability(two_capabilities):
    result = capability_help.build_index()

    ids = {row["capability"] for row in result["capabilities"]}
    assert ids == {"/widget", "/gadget"}


def test_build_index_row_has_label_summary_and_commands(two_capabilities):
    result = capability_help.build_index()

    row = next(r for r in result["capabilities"] if r["capability"] == "/gadget")
    assert row["label"] == "Gadgets"
    assert row["summary"] == "Makes gadgets."
    assert row["commands"] == "build, help, inspect"


def test_build_index_always_includes_help_in_the_command_list(two_capabilities):
    result = capability_help.build_index()

    row = next(r for r in result["capabilities"] if r["capability"] == "/widget")
    assert "help" in row["commands"].split(", ")


def test_build_index_omits_a_disabled_capability(two_capabilities):
    fake_mcp = FastMCP(name="test-disable")
    capability_registry.set_enabled(fake_mcp, "widget", False)

    result = capability_help.build_index()

    ids = {row["capability"] for row in result["capabilities"]}
    assert ids == {"/gadget"}


def test_build_index_skips_a_registered_capability_with_no_help_json(tmp_path, monkeypatch):
    capability_meta.register(folder="ghost", id="ghost", label="Ghost")
    fake_mcp = FastMCP(name="test-ghost")
    with capability_registry.capturing(fake_mcp, "ghost", label="Ghost"):
        pass
    monkeypatch.setattr(capability_help, "_CAPABILITIES_DIR", tmp_path)

    result = capability_help.build_index()

    assert result["capabilities"] == []
