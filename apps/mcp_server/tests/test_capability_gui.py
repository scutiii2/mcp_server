"""Tests for per-capability GUI pages: the page models, the loader that
reads gui/page.json from a capability folder, and every page we ship."""

from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest
from mcp.server.fastmcp import FastMCP
from pydantic import ValidationError

from src import capability_gui
from src.capability_gui import GuiFormSection, GuiTextSection, load_page, parse_page
from src.services import capability_meta, capability_registry

PAGE = {
    "version": 1,
    "title": "Widgets",
    "description": "Make widgets.",
    "sections": [
        {"id": "make", "title": "Make", "tool": "make_widget", "submit": "Go",
         "fields": [{"param": "size", "label": "Size", "order": 1}],
         "result": {"kind": "secret", "field": "value", "detail": "message", "refresh_after": "seconds"}},
        {"id": "note", "text": "Widgets are fake."},
    ],
}


def page_with(**changes) -> str:
    return json.dumps({**PAGE, **changes})


def test_parse_valid_page():
    page = parse_page(json.dumps(PAGE), {"make_widget"})

    assert page.title == "Widgets"
    form, note = page.sections
    assert isinstance(form, GuiFormSection) and form.tool == "make_widget"
    assert form.result.kind == "secret" and form.result.refresh_after == "seconds"
    assert form.fields[0].order == 1
    assert isinstance(note, GuiTextSection) and note.text == "Widgets are fake."


def test_form_defaults():
    page = parse_page(json.dumps({"version": 1, "title": "T", "sections": [{"id": "a", "title": "A", "tool": "t"}]}), None)

    form = page.sections[0]
    assert form.submit == "Run" and form.fields == [] and form.result.kind == "fields"


def test_unknown_keys_are_ignored():
    raw = page_with(extra="x", sections=[{"id": "a", "title": "A", "tool": "t", "colour": "red"}])

    assert parse_page(raw, None).sections[0].tool == "t"


def test_tool_of_another_capability_is_refused():
    with pytest.raises(ValueError, match="make_widget"):
        parse_page(json.dumps(PAGE), {"other_tool"})


@pytest.mark.parametrize(
    "changes",
    [
        {"version": 2},
        {"sections": []},
        {"sections": [{"id": "a", "title": "A", "tool": "t"}, {"id": "a", "title": "B", "tool": "t"}]},
        {"sections": [{"id": "a", "title": "A", "tool": "t", "result": {"kind": "secret"}}]},
        {"sections": [{"id": "a", "title": "A", "tool": "t", "result": {"kind": "table"}}]},
        {"sections": [{"id": "a", "title": "A", "tool": "t", "result": {"kind": "bogus"}}]},
        {"sections": [{"id": "a", "title": "A", "tool": "t", "result": {"refresh_after": "not an id"}}]},
        {"sections": [{"id": "bad id", "title": "A", "tool": "t"}]},
    ],
)
def test_invalid_pages_are_rejected(changes):
    with pytest.raises(ValidationError):
        parse_page(page_with(**changes), None)


@pytest.fixture
def widgets(tmp_path, monkeypatch):
    """A registered capability 'widgets' (folder 'widget_folder') whose gui
    folder lives in tmp_path."""
    server = FastMCP(name="test")
    monkeypatch.setattr(capability_registry, "_REGISTRY", {})
    monkeypatch.setattr(capability_meta, "_BY_FOLDER", {})
    capability_meta.register(folder="widget_folder", id="widgets", label="Widgets")
    with capability_registry.capturing(server, "widgets"):
        @server.tool()
        def make_widget() -> str:
            return "w"
    monkeypatch.setattr(capability_gui, "_CAPABILITIES_DIR", tmp_path)
    (tmp_path / "widget_folder" / "gui").mkdir(parents=True)
    return tmp_path / "widget_folder" / "gui" / "page.json"


def test_load_page_reads_the_capability_folder(widgets):
    widgets.write_text(json.dumps(PAGE), encoding="utf-8")

    assert load_page("widgets").title == "Widgets"


def test_load_page_none_without_a_file(widgets):
    assert load_page("widgets") is None


def test_load_page_none_for_unknown_capability(widgets):
    assert load_page("nope") is None


def test_load_page_none_when_capability_is_off(widgets):
    widgets.write_text(json.dumps(PAGE), encoding="utf-8")
    capability_registry._REGISTRY["widgets"].enabled = False

    assert load_page("widgets") is None


def test_load_page_logs_and_hides_an_invalid_file(widgets, caplog):
    widgets.write_text("{ not json", encoding="utf-8")

    assert load_page("widgets") is None
    assert "widgets" in caplog.text


def test_load_page_hides_a_page_naming_foreign_tools(widgets):
    widgets.write_text(page_with(sections=[{"id": "a", "title": "A", "tool": "elsewhere"}]), encoding="utf-8")

    assert load_page("widgets") is None


GUI_FILES = sorted((Path(capability_gui.__file__).parent / "capabilities").glob("*/gui/page.json"))


@pytest.mark.parametrize("path", GUI_FILES, ids=lambda p: p.parent.parent.name)
def test_shipped_pages_parse_and_name_only_their_own_tools(path):
    folder = path.parent.parent.name
    module = importlib.import_module(f"src.capabilities.{folder}.tool")
    page = parse_page(path.read_text(encoding="utf-8"), None)

    for section in page.sections:
        if isinstance(section, GuiFormSection):
            assert hasattr(module, section.tool), f"{folder} page names {section.tool}, not defined in its tool.py"


def test_there_is_at_least_one_shipped_page():
    assert GUI_FILES
