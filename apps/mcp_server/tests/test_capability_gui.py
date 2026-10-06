"""Tests for per-capability GUI pages: the page models, the loader that
reads gui/page.json from a capability folder, and every page we ship."""

from __future__ import annotations

import importlib
import inspect
import json
import typing
from pathlib import Path

import pytest
from mcp.server.fastmcp import FastMCP
from pydantic import ValidationError

from src import capability_gui
from src.capability_gui import GuiFormSection, GuiTabsSection, GuiTextSection, form_sections, load_page, parse_page
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


TABS = {
    "id": "gen",
    "tabs": [
        {"id": "a", "title": "A", "tool": "t1", "live": True,
         "result": {"kind": "secret", "field": "v", "strength": "bits", "group": 3}},
        {"id": "b", "title": "B", "tool": "t2"},
    ],
}


def tabs_page(**section_changes) -> str:
    return json.dumps({"version": 1, "title": "T", "sections": [{**TABS, **section_changes}]})


def test_parse_tabs_page():
    page = parse_page(tabs_page(), {"t1", "t2"})

    (section,) = page.sections
    assert isinstance(section, GuiTabsSection)
    first, second = section.tabs
    assert first.live is True and first.result.strength == "bits" and first.result.group == 3
    assert second.live is False and second.result.strength is None and second.result.group is None


def test_form_sections_walks_into_tabs():
    raw = json.dumps({"version": 1, "title": "T", "sections": [
        {"id": "top", "title": "Top", "tool": "t0"},
        TABS,
        {"id": "note", "text": "hi"},
    ]})

    assert [f.id for f in form_sections(parse_page(raw, None))] == ["top", "a", "b"]


def test_a_tab_may_only_name_its_own_tools():
    with pytest.raises(ValueError, match="t2"):
        parse_page(tabs_page(), {"t1"})


@pytest.mark.parametrize(
    "raw",
    [
        tabs_page(tabs=TABS["tabs"][:1]),
        tabs_page(tabs=[{"id": f"t{i}", "title": "T", "tool": "t"} for i in range(9)]),
        tabs_page(tabs=[TABS["tabs"][0], {"id": "a", "title": "Again", "tool": "t"}]),
        tabs_page(tabs=[TABS["tabs"][0], {"id": "x", "text": "not a form"}]),
        tabs_page(id="bad id"),
        json.dumps({"version": 1, "title": "T", "sections": [
            {"id": "a", "title": "Top", "tool": "t0"}, TABS]}),
        *[
            tabs_page(tabs=[{"id": "a", "title": "A", "tool": "t", "result": result}, TABS["tabs"][1]])
            for result in (
                {"kind": "message", "strength": "bits"},
                {"kind": "table", "field": "rows", "group": 3},
                {"kind": "secret", "field": "v", "group": 1},
                {"kind": "secret", "field": "v", "group": 9},
                {"kind": "secret", "field": "v", "strength": "not an id"},
            )
        ],
    ],
)
def test_invalid_tabs_pages_are_rejected(raw):
    with pytest.raises(ValidationError):
        parse_page(raw, None)


def test_a_form_is_not_live_by_default():
    page = parse_page(json.dumps({"version": 1, "title": "T", "sections": [{"id": "a", "title": "A", "tool": "t"}]}), None)

    assert page.sections[0].live is False


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
        {"title": ""},
        {"sections": [{"id": "a", "title": "", "tool": "t"}]},
        {"sections": [{"id": "a", "title": "A", "tool": ""}]},
        {"sections": [{"id": "a", "title": "A", "tool": "t", "submit": ""}]},
        {"sections": [{"id": "a", "text": ""}]},
        {"sections": [{"id": "a", "title": "", "text": "x"}]},
        {"sections": [{"id": "a", "title": "A", "tool": "t", "fields": [{"param": ""}]}]},
        *[
            {"sections": [{"id": "a", "title": "A", "tool": "t", "result": {"kind": "secret", "field": "x", key: bad}}]}
            for key in ("field", "detail", "refresh_after")
            for bad in ("code\n", "a-b")
        ],
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

    for section in form_sections(page):
        assert hasattr(module, section.tool), f"{folder} page names {section.tool}, not defined in its tool.py"
        function = inspect.unwrap(getattr(module, section.tool))
        result_model = typing.get_type_hints(function)["return"]
        named = {section.result.field, section.result.detail, section.result.refresh_after, section.result.strength} - {None}
        missing = named - set(result_model.model_fields)
        assert not missing, f"{folder}/{section.id}: {sorted(missing)} not in {result_model.__name__}"


def test_there_is_at_least_one_shipped_page():
    assert GUI_FILES


from starlette.applications import Starlette  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

from src import capability_routes  # noqa: E402


@pytest.fixture
def client(widgets, monkeypatch, tmp_path):
    monkeypatch.setattr(capability_routes, "mcp", FastMCP(name="routes"))
    app = Starlette()
    capability_routes.install_capability_routes(app)
    with TestClient(app) as test_client:
        yield test_client


def test_gui_route_serves_the_page(client, widgets):
    widgets.write_text(json.dumps(PAGE), encoding="utf-8")

    response = client.get("/capabilities/widgets/gui")

    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "Widgets" and body["sections"][0]["tool"] == "make_widget"


def test_gui_route_404_without_a_page(client):
    response = client.get("/capabilities/widgets/gui")

    assert response.status_code == 404
    assert "no page" in response.json()["error"].lower()


def test_gui_route_404_for_unknown_capability(client):
    assert client.get("/capabilities/nope/gui").status_code == 404


def test_list_reports_has_gui(client, widgets):
    assert client.get("/capabilities").json()[0]["has_gui"] is False

    widgets.write_text(json.dumps(PAGE), encoding="utf-8")

    assert client.get("/capabilities").json()[0]["has_gui"] is True


def _nulls(value, path="$"):
    if value is None:
        yield path
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from _nulls(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _nulls(item, f"{path}[{index}]")


def test_gui_route_serves_no_nulls(client, widgets):
    page = {"version": 1, "title": "T", "sections": [
        {"id": "a", "title": "A", "tool": "make_widget", "fields": [{"param": "p"}]},
        {"id": "n", "text": "hi"},
    ]}
    widgets.write_text(json.dumps(page), encoding="utf-8")

    body = client.get("/capabilities/widgets/gui").json()

    assert list(_nulls(body)) == []
    assert body["sections"][0]["fields"][0]["param"] == "p"


def test_gui_route_serves_a_tabs_page(client, widgets):
    page = {"version": 1, "title": "T", "sections": [{"id": "g", "tabs": [
        {"id": "a", "title": "A", "tool": "make_widget", "live": True},
        {"id": "b", "title": "B", "tool": "make_widget"},
    ]}]}
    widgets.write_text(json.dumps(page), encoding="utf-8")

    body = client.get("/capabilities/widgets/gui").json()

    assert [t["id"] for t in body["sections"][0]["tabs"]] == ["a", "b"]
    assert body["sections"][0]["tabs"][0]["live"] is True
    assert list(_nulls(body)) == []
