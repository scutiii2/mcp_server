# Capability Pages Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A capability ships `gui/page.json`; ember_web shows it at `/capabilities/<alias>`, and each card on the Capabilities page links to it.

**Architecture:** `mcp_server` validates and serves the declarative page (`GET /capabilities/{name}/gui`, plus `has_gui` on `GET /capabilities`). `ember_api` passes both through. `ember_web` draws the page with a generic renderer; its buttons call tools through the existing `/api/mcp/server` MCP proxy, so nothing new can execute.

**Tech Stack:** Python 3.11+, Starlette, Pydantic v2, pytest (mcp_server); FastAPI, httpx, pytest (ember_api); Vue 3, TypeScript, Pinia, vue-router, vitest, `@vue/test-utils` (ember_web).

**Spec:** `docs/superpowers/specs/2026-10-06-capability-pages-design.md`

## Global Constraints

- Paths are repo-relative: `apps/mcp_server/...`, `apps/ember_api/...`, `apps/ember_web/...`. Run Python tests from each app's own folder with its own venv (`.venv_mcp`, `.venv_ember_api`); run ember_web commands from `apps/ember_web/`.
- A page is data, not code. The renderer draws only the fixed widget set. Unknown keys are ignored (ember_web logs a console warning).
- Every `tool` a page names must belong to that capability. `mcp_server` checks at load; ember_web checks again.
- Results and entered secrets live only in component memory: never `localStorage`, the URL or ember_api.
- Page `version` is `1`. Result kinds: `secret`, `message`, `table`, `fields` (default). Section types: form (has `tool`) and `text` (has `text`).
- `has_gui` is true only when the capability is enabled and its page is valid. The route returns 404 in every other case.
- `refresh_after` and every result `field`/`detail` are identifier-shaped names (`[A-Za-z_][A-Za-z0-9_]*`).
- Code comments explain intent, never mention this plan or its tasks. Commit messages end with `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.
- ember_web work is proposed step by step: **stop for the user's OK after Task 2, after Task 4 and after Task 7** (end of each app).
- ember_web's browser e2e (Playwright) is not added: its fake API would need a full MCP handshake. The vitest suites cover the renderer; Task 8 checks the page by hand in the browser.

## File Structure

| File | Responsibility |
|---|---|
| `apps/mcp_server/src/capability_gui.py` (new) | Pydantic page models, `parse_page`, `load_page`; no HTTP |
| `apps/mcp_server/src/capability_routes.py` (modify) | `has_gui` in the status JSON; `GET /capabilities/{name}/gui` |
| `apps/mcp_server/src/capabilities/generator/gui/page.json` (new) | The generator's page |
| `apps/mcp_server/tests/test_capability_gui.py` (new) | Model, loader, route and shipped-page tests |
| `apps/mcp_server/src/capabilities/README.md`, `.agents/skills/mcp-capability-scaffold/SKILL.md` | `gui/` folder rule and `page.json` reference |
| `apps/ember_api/src/routes/server_info.py`, `src/services/mcp_server_info.py` (modify) | Pass-through route and client method; `has_gui` on `CapabilityOut` |
| `apps/ember_web/src/api/CapabilityPagesClient.ts` (new) | Page types and `GET /api/capabilities/{name}/gui` |
| `apps/ember_web/src/utils/guiPage.ts` (new) | `parseGuiPage` (checks tool ownership), `applyFieldOverrides`, `resultValue` |
| `apps/ember_web/src/composables/useCountdown.ts` (new) | Countdown that pauses while the tab is hidden |
| `apps/ember_web/src/components/GuiResult.vue`, `GuiFormSection.vue` (new) | Result kinds; one form section with run and refresh |
| `apps/ember_web/src/views/CapabilityPageView.vue` (new) | Loads page, tools and capability; draws sections |
| `apps/ember_web/src/router/index.ts`, `components/CapabilitySection.vue`, `api/CommandsClient.ts` (modify) | Route, "Open page" link, `has_gui` field |

---

## Part A: mcp_server

### Task 1: Page models, loader and shipped generator page

**Files:**
- Create: `apps/mcp_server/src/capability_gui.py`
- Create: `apps/mcp_server/src/capabilities/generator/gui/page.json`
- Test: `apps/mcp_server/tests/test_capability_gui.py`

**Interfaces:**
- Produces: `GuiPage`, `GuiFormSection`, `GuiTextSection`, `GuiField`, `GuiResult` (Pydantic models); `parse_page(raw: str, own_tools: set[str] | None) -> GuiPage`; `load_page(capability_id: str) -> GuiPage | None`; module constant `_CAPABILITIES_DIR: Path`.

- [ ] **Step 1: Write the failing tests**

Create `apps/mcp_server/tests/test_capability_gui.py`:

```python
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
```

Check `capability_registry._CapabilityHandle` is a mutable dataclass before relying on `.enabled = False` in `test_load_page_none_when_capability_is_off`; if it is frozen (the existing tests use `dataclasses.replace` + `monkeypatch.setitem`), use `monkeypatch.setitem(capability_registry._REGISTRY, "widgets", replace(capability_registry._REGISTRY["widgets"], enabled=False))` instead.

- [ ] **Step 2: Run tests to verify they fail**

Run (from `apps/mcp_server/`): `.venv_mcp/Scripts/python.exe -m pytest tests/test_capability_gui.py -q`
Expected: collection error `ImportError: cannot import name 'capability_gui'`.

- [ ] **Step 3: Write `src/capability_gui.py`**

```python
"""Per-capability GUI pages: `capabilities/<folder>/gui/page.json`.

A page is declarative data that ember_web draws with a fixed set of
widgets; the capability's own code never runs in the browser. This module
holds the page models and the loader. `load_page` returns None for every
case that means "no page to show" - no file, capability off, unknown
capability, or an invalid file (logged, so one bad page never breaks the
server or another capability).

Mounted as an HTTP route by `capability_routes.py`, not a tool: a page is
for people, not for a model.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Discriminator, Field, Tag, field_validator, model_validator

from src.services import capability_meta, capability_registry

logger = logging.getLogger(__name__)

_CAPABILITIES_DIR = Path(__file__).resolve().parent / "capabilities"
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
_SECTION_ID = r"^[A-Za-z0-9_-]{1,64}$"


def _identifier(value: str | None) -> str | None:
    if value is not None and not _IDENTIFIER.match(value):
        raise ValueError(f"{value!r} is not a result field name")
    return value


class GuiField(BaseModel):
    """Overrides for one of the tool's own parameters; the form itself is built from the tool's schema."""

    model_config = ConfigDict(extra="ignore")
    param: str
    label: str | None = None
    order: int | None = None
    hidden: bool = False


class GuiResult(BaseModel):
    """How a tool's structured result is shown. `field` names the value to show."""

    model_config = ConfigDict(extra="ignore")
    kind: Literal["secret", "message", "table", "fields"] = "fields"
    field: str | None = None
    detail: str | None = None
    refresh_after: str | None = None

    _check_names = field_validator("field", "detail", "refresh_after")(lambda cls, value: _identifier(value))

    @model_validator(mode="after")
    def _needs_a_field(self) -> "GuiResult":
        if self.kind in ("secret", "table") and self.field is None:
            raise ValueError(f"result kind {self.kind!r} needs a 'field'")
        return self


class GuiFormSection(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(pattern=_SECTION_ID)
    title: str
    tool: str
    submit: str = "Run"
    fields: list[GuiField] = Field(default_factory=list)
    result: GuiResult = Field(default_factory=GuiResult)


class GuiTextSection(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(pattern=_SECTION_ID)
    title: str | None = None
    text: str


def _section_kind(value: Any) -> str:
    if isinstance(value, dict):
        return "text" if "text" in value else "form"
    return "text" if isinstance(value, GuiTextSection) else "form"


GuiSection = Annotated[
    Union[Annotated[GuiFormSection, Tag("form")], Annotated[GuiTextSection, Tag("text")]],
    Discriminator(_section_kind),
]


class GuiPage(BaseModel):
    model_config = ConfigDict(extra="ignore")
    version: Literal[1]
    title: str
    description: str = ""
    sections: list[GuiSection] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_section_ids(self) -> "GuiPage":
        ids = [section.id for section in self.sections]
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        if duplicates:
            raise ValueError(f"duplicate section ids: {', '.join(duplicates)}")
        return self


def parse_page(raw: str, own_tools: set[str] | None) -> GuiPage:
    """Validate `raw`. With `own_tools`, every form's tool must be one of them."""
    page = GuiPage.model_validate_json(raw)
    if own_tools is not None:
        named = {section.tool for section in page.sections if isinstance(section, GuiFormSection)}
        foreign = sorted(named - own_tools)
        if foreign:
            raise ValueError(f"page names tools this capability does not own: {', '.join(foreign)}")
    return page


def _page_path(capability_id: str) -> Path | None:
    folder = capability_meta.folder_for_id(capability_id)
    return None if folder is None else _CAPABILITIES_DIR / folder / "gui" / "page.json"


def load_page(capability_id: str) -> GuiPage | None:
    """The capability's page, or None when there is nothing to show (see module docstring)."""
    path = _page_path(capability_id)
    if path is None or not path.is_file():
        return None
    try:
        if not capability_registry.is_enabled(capability_id):
            return None
        return parse_page(path.read_text(encoding="utf-8"), set(capability_registry.tool_names(capability_id)))
    except (KeyError, OSError, ValueError) as error:  # pydantic's ValidationError is a ValueError
        logger.warning("Ignoring the GUI page of capability %r (%s): %s", capability_id, path, error)
        return None
```

- [ ] **Step 4: Write the generator page**

Create `apps/mcp_server/src/capabilities/generator/gui/page.json`:

```json
{
  "version": 1,
  "title": "Generator",
  "description": "Random passwords, passphrases, PINs and TOTP codes. Nothing is stored; a value is shown once.",
  "sections": [
    {
      "id": "password",
      "title": "Password",
      "tool": "tool_gen_generatePassword",
      "submit": "Generate",
      "result": { "kind": "secret", "field": "password", "detail": "message" }
    },
    {
      "id": "passphrase",
      "title": "Passphrase",
      "tool": "tool_gen_generatePassphrase",
      "submit": "Generate",
      "result": { "kind": "secret", "field": "passphrase", "detail": "message" }
    },
    {
      "id": "pin",
      "title": "PIN or one-time code",
      "tool": "tool_gen_generatePin",
      "submit": "Generate",
      "result": { "kind": "secret", "field": "pin", "detail": "message" }
    },
    {
      "id": "totp-secret",
      "title": "New TOTP secret",
      "tool": "tool_gen_generateTotpSecret",
      "submit": "Generate",
      "result": { "kind": "secret", "field": "secret", "detail": "message" }
    },
    {
      "id": "totp",
      "title": "Current TOTP code",
      "tool": "tool_gen_getTotpCode",
      "submit": "Show code",
      "result": { "kind": "secret", "field": "code", "detail": "message", "refresh_after": "seconds_remaining" }
    }
  ]
}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv_mcp/Scripts/python.exe -m pytest tests/test_capability_gui.py -q`
Expected: all pass. If `_check_names = field_validator(...)(lambda ...)` is rejected by Pydantic, replace it with a normal `@field_validator("field", "detail", "refresh_after") @classmethod def _check_names(cls, value): return _identifier(value)` method.

- [ ] **Step 6: Commit**

```bash
git add apps/mcp_server/src/capability_gui.py apps/mcp_server/src/capabilities/generator/gui apps/mcp_server/tests/test_capability_gui.py
git commit -m "feat(mcp_server): validate and load per-capability GUI pages"
```

### Task 2: Route, `has_gui` and docs

**Files:**
- Modify: `apps/mcp_server/src/capability_routes.py`
- Modify: `apps/mcp_server/tests/test_capability_routes.py` (existing exact-JSON expectations gain `"has_gui": False`)
- Modify: `apps/mcp_server/tests/test_capability_gui.py` (route tests)
- Modify: `apps/mcp_server/src/capabilities/README.md`, `.agents/skills/mcp-capability-scaffold/SKILL.md`, `apps/mcp_server/src/capabilities/generator/README.md`

**Interfaces:**
- Consumes: `capability_gui.load_page(capability_id) -> GuiPage | None`
- Produces: `GET /capabilities/{name}/gui` -> 200 `GuiPage.model_dump()` or 404 `{"error": ...}`; every `GET /capabilities` entry and the `PATCH` response gain `"has_gui": bool`.

- [ ] **Step 1: Write the failing route tests**

Append to `tests/test_capability_gui.py`:

```python
from starlette.applications import Starlette
from starlette.testclient import TestClient

from src import capability_routes


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
```

In `tests/test_capability_routes.py` add `"has_gui": False` to every expected capability dict (`test_get_lists_every_registered_capability`, `test_patch_disables_a_capability`, and any other exact comparison; run the file and fix each failing assertion the same way).

- [ ] **Step 2: Run to verify failure**

Run: `.venv_mcp/Scripts/python.exe -m pytest tests/test_capability_gui.py tests/test_capability_routes.py -q`
Expected: new tests FAIL (404 route missing, no `has_gui` key); the edited route tests FAIL on the missing key.

- [ ] **Step 3: Implement**

In `src/capability_routes.py` add `from src import capability_gui` to the imports, then:

```python
def _status_json(name: str) -> dict[str, object]:
    return {
        "name": name,
        "enabled": capability_registry.is_enabled(name),
        "label": capability_registry.label(name),
        "tools": capability_registry.tool_names(name),
        "resources": capability_registry.resource_names(name),
        # True only when a valid page exists and the capability is on, so a link never leads to a 404.
        "has_gui": capability_gui.load_page(name) is not None,
    }


async def capability_gui_page(request: Request) -> JSONResponse:
    name = request.path_params["name"]
    if name not in capability_registry.names():
        return JSONResponse({"error": f"Unknown capability {name!r}"}, status_code=404)
    page = capability_gui.load_page(name)
    if page is None:
        return JSONResponse({"error": f"Capability {name!r} has no page"}, status_code=404)
    return JSONResponse(page.model_dump())
```

and in `install_capability_routes` add:

```python
    app.add_route("/capabilities/{name}/gui", capability_gui_page, methods=["GET"])
```

Update the module docstring's JSON example to include `"has_gui": false` and one line describing the new route.

- [ ] **Step 4: Run the whole suite**

Run: `.venv_mcp/Scripts/python.exe -m pytest -q`
Expected: all pass (previous 362 plus the new tests).

- [ ] **Step 5: Docs**

- `src/capabilities/README.md`: in "Shape of a capability" add `gui/` to the top-level whitelist ("`gui/` - `page.json` only: the page ember_web shows at `/capabilities/<id>`"), and add a "GUI pages" section with the `page.json` format (copy the spec's format section: page keys, section types, result kinds, `refresh_after`, the rule that a page may only name its own capability's tools, and that an invalid file is logged and hidden).
- `.agents/skills/mcp-capability-scaffold/SKILL.md`: add `gui/` to the closed whitelist bullet list and one bullet on `page.json`, pointing to the README. Then run `python sync_skills.py` from the repo root.
- `generator/README.md`: add a short "Page" paragraph: "`gui/page.json` gives the capability a page at `/capabilities/gen` in ember_web."

- [ ] **Step 6: Commit and stop**

```bash
git add apps/mcp_server .agents .claude
git commit -m "feat(mcp_server): serve capability GUI pages and report has_gui"
```

Stop here and report to the user before Part B.

---

## Part B: ember_api

### Task 3: Pass-through route and `has_gui`

**Files:**
- Modify: `apps/ember_api/src/services/mcp_server_info.py`
- Modify: `apps/ember_api/src/routes/server_info.py`
- Modify: `apps/ember_api/tests/test_server_info.py`
- Modify: `apps/ember_api/README.md`

**Interfaces:**
- Consumes: mcp_server `GET /capabilities/{name}/gui`.
- Produces: `McpServerInfo.capability_page(account, name) -> dict[str, Any]`; `GET /api/capabilities/{name}/gui` (needs `tools.use`; 404 relayed, 502 when mcp_server is down); `CapabilityOut.has_gui: bool = False`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_server_info.py`: set `"has_gui": True` on the `CAPABILITIES[0]` dict, and add to the `mcp_server` fake handler (before the final `return`):

```python
    if path == "/capabilities/server_manager/gui":
        return httpx.Response(200, json=GUI_PAGE)
    if path.startswith("/capabilities/") and path.endswith("/gui"):
        return httpx.Response(404, json={"error": "Capability 'nope' has no page"})
```

with, near `CAPABILITIES`:

```python
GUI_PAGE = {"version": 1, "title": "Server", "description": "", "sections": [{"id": "list", "title": "Apps", "tool": "tool_srv_listApps"}]}
```

and the test:

```python
def test_capability_page_is_passed_through(client: TestClient, upstream: FakeUpstream) -> None:
    upstream.handler = mcp_server
    as_admin(client)

    assert client.get("/api/capabilities/server_manager/gui").json() == GUI_PAGE
    missing = client.get("/api/capabilities/nope/gui")
    assert (missing.status_code, missing.json()["detail"]) == (404, "Capability 'nope' has no page")
    assert upstream.requests[0].headers["x-requester-username"] == "root"


def test_capability_page_needs_tools_use(client_factory, email: FakeEmailSender, upstream: FakeUpstream) -> None:
    upstream.handler = mcp_server
    member = make_member(client_factory, email, permissions=[])  # no tools.use

    assert member.get("/api/capabilities/server_manager/gui").status_code == 403
```

Look at `test_capabilities_list_and_admin_switch` (lines ~71-90 of that file) and copy exactly how it builds a member without `tools.use`; use the same helper and arguments in `test_capability_page_needs_tools_use` rather than the `permissions=[]` shown above.

- [ ] **Step 2: Run to verify failure**

Run (from `apps/ember_api/`): `.venv_ember_api/Scripts/python.exe -m pytest tests/test_server_info.py -q`
Expected: new tests FAIL (404 route), list test FAILs on `has_gui`.

- [ ] **Step 3: Implement**

`services/mcp_server_info.py`, next to `capabilities`:

```python
    async def capability_page(self, account: Account, name: str) -> dict[str, Any]:
        """A capability's GUI page (the declarative layout ember_web draws)."""
        body = await self._request("GET", f"/capabilities/{quote(name, safe='')}/gui", account)
        return body if isinstance(body, dict) else {}
```

`routes/server_info.py`: add `has_gui: bool = False` to `CapabilityOut` and, after `list_capabilities`:

```python
@router.get("/capabilities/{name}/gui")
async def capability_page(
    name: str = Path(pattern=NAME_PATTERN),
    account: Account = Depends(require_tools),
    info: McpServerInfo = Depends(get_server_info),
) -> dict[str, Any]:
    """A capability's page layout, as mcp_server validated it; ember_web draws it."""
    return await _call(info.capability_page(account, name))
```

Update the module docstring's first lines to mention `/api/capabilities/{name}/gui`. In `README.md`, add the route to the API table.

- [ ] **Step 4: Run the suite**

Run: `.venv_ember_api/Scripts/python.exe -m pytest tests/test_server_info.py -q` then the full suite (about 5 minutes): `.venv_ember_api/Scripts/python.exe -m pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit and stop**

```bash
git add apps/ember_api
git commit -m "feat(ember_api): pass capability GUI pages through to ember_web"
```

Stop and report to the user before Part C.

---

## Part C: ember_web

### Task 4: Types, client and parsing utilities

**Files:**
- Create: `apps/ember_web/src/api/CapabilityPagesClient.ts`
- Create: `apps/ember_web/src/utils/guiPage.ts`
- Modify: `apps/ember_web/src/api/CommandsClient.ts` (add `has_gui?: boolean` to `CapabilityInfo`)
- Test: `apps/ember_web/src/utils/guiPage.test.ts`

**Interfaces:**
- Produces:
  - `type GuiResultKind = "secret" | "message" | "table" | "fields"`
  - `interface GuiResultSpec { kind: GuiResultKind; field?: string; detail?: string; refresh_after?: string }`
  - `interface GuiFieldSpec { param: string; label?: string; order?: number; hidden?: boolean }`
  - `interface GuiFormSectionSpec { type: "form"; id: string; title: string; tool: string; submit: string; fields: GuiFieldSpec[]; result: GuiResultSpec }`
  - `interface GuiTextSectionSpec { type: "text"; id: string; title?: string; text: string }`
  - `interface GuiPageSpec { version: 1; title: string; description: string; sections: (GuiFormSectionSpec | GuiTextSectionSpec)[] }`
  - `capabilityPagesClient.get(name: string): Promise<unknown>`
  - `parseGuiPage(raw: unknown, ownTools: string[]): GuiPageSpec` (throws `GuiPageError`)
  - `applyFieldOverrides(schema: JsonSchema, fields: GuiFieldSpec[]): JsonSchema`
  - `resultValue(result: ToolRunResult, field: string): unknown`

- [ ] **Step 1: Write the failing tests**

Create `src/utils/guiPage.test.ts`:

```ts
import { describe, expect, it, vi } from "vitest";
import type { JsonSchema, ToolRunResult } from "../api/types";
import { applyFieldOverrides, GuiPageError, parseGuiPage, resultValue } from "./guiPage";

const RAW = {
  version: 1,
  title: "Generator",
  description: "d",
  sections: [
    { id: "pw", title: "Password", tool: "tool_a", submit: "Go", fields: [{ param: "length", label: "How long" }],
      result: { kind: "secret", field: "password", detail: "message", refresh_after: "seconds" } },
    { id: "note", text: "Hello" },
  ],
};

describe("parseGuiPage", () => {
  it("accepts a valid page and tags section types", () => {
    const page = parseGuiPage(RAW, ["tool_a"]);
    expect(page.title).toBe("Generator");
    expect(page.sections[0]).toMatchObject({ type: "form", tool: "tool_a", submit: "Go" });
    expect(page.sections[1]).toMatchObject({ type: "text", text: "Hello" });
  });

  it("fills defaults", () => {
    const page = parseGuiPage({ version: 1, title: "T", sections: [{ id: "a", title: "A", tool: "t" }] }, ["t"]);
    expect(page.sections[0]).toMatchObject({ submit: "Run", fields: [], result: { kind: "fields" } });
    expect(page.description).toBe("");
  });

  it("ignores unknown keys with a console warning", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const page = parseGuiPage({ ...RAW, colour: "red" }, ["tool_a"]);
    expect(page.title).toBe("Generator");
    expect(warn).toHaveBeenCalled();
    warn.mockRestore();
  });

  it.each([
    ["wrong version", { ...RAW, version: 2 }],
    ["no sections", { ...RAW, sections: [] }],
    ["not an object", "x"],
    ["bad result kind", { ...RAW, sections: [{ id: "a", title: "A", tool: "tool_a", result: { kind: "bogus" } }] }],
    ["secret without field", { ...RAW, sections: [{ id: "a", title: "A", tool: "tool_a", result: { kind: "secret" } }] }],
    ["duplicate ids", { ...RAW, sections: [{ id: "a", title: "A", tool: "tool_a" }, { id: "a", text: "x" }] }],
  ])("rejects %s", (_name, raw) => {
    expect(() => parseGuiPage(raw, ["tool_a"])).toThrow(GuiPageError);
  });

  it("rejects a tool the capability does not own", () => {
    expect(() => parseGuiPage(RAW, ["tool_b"])).toThrow(/tool_a/);
  });
});

describe("applyFieldOverrides", () => {
  const schema: JsonSchema = {
    type: "object",
    properties: { a: { type: "string" }, b: { type: "string", default: "x" }, c: { type: "string" } },
    required: ["c"],
  };

  it("relabels, reorders and hides optional params", () => {
    const out = applyFieldOverrides(schema, [
      { param: "a", label: "Alpha", order: 2 },
      { param: "b", hidden: true },
      { param: "c", order: 1 },
    ]);
    expect(Object.keys(out.properties!)).toEqual(["c", "a"]);
    expect(out.properties!.a.title).toBe("Alpha");
  });

  it("never hides a required param", () => {
    const out = applyFieldOverrides(schema, [{ param: "c", hidden: true }]);
    expect(Object.keys(out.properties!)).toContain("c");
  });

  it("ignores overrides for params the tool does not have", () => {
    expect(applyFieldOverrides(schema, [{ param: "zzz", label: "x" }])).toEqual(schema);
  });

  it("does not change its input", () => {
    const copy = JSON.parse(JSON.stringify(schema));
    applyFieldOverrides(schema, [{ param: "a", label: "Alpha" }]);
    expect(schema).toEqual(copy);
  });
});

describe("resultValue", () => {
  const ok = (structured?: Record<string, unknown>, text = ""): ToolRunResult => ({ text, isError: false, structured });

  it("reads a structured field", () => {
    expect(resultValue(ok({ code: "123456" }), "code")).toBe("123456");
  });

  it("falls back to the JSON text when there is no structured content", () => {
    expect(resultValue(ok(undefined, '{"code":"654321"}'), "code")).toBe("654321");
  });

  it("is undefined when the field is missing", () => {
    expect(resultValue(ok({ other: 1 }), "code")).toBeUndefined();
    expect(resultValue(ok(undefined, "plain text"), "code")).toBeUndefined();
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run (from `apps/ember_web/`): `npx vitest run src/utils/guiPage.test.ts`
Expected: FAIL, cannot resolve `./guiPage`.

- [ ] **Step 3: Implement**

`src/api/CapabilityPagesClient.ts`:

```ts
import { apiRequest } from "./http";

export type GuiResultKind = "secret" | "message" | "table" | "fields";

export interface GuiResultSpec {
  kind: GuiResultKind;
  /** The result value to show (required for secret and table). */
  field?: string;
  /** A second result value shown below as plain text. */
  detail?: string;
  /** A numeric result field: seconds until the tool is run again. */
  refresh_after?: string;
}

export interface GuiFieldSpec {
  param: string;
  label?: string;
  order?: number;
  hidden?: boolean;
}

export interface GuiFormSectionSpec {
  type: "form";
  id: string;
  title: string;
  tool: string;
  submit: string;
  fields: GuiFieldSpec[];
  result: GuiResultSpec;
}

export interface GuiTextSectionSpec {
  type: "text";
  id: string;
  title?: string;
  text: string;
}

export interface GuiPageSpec {
  version: 1;
  title: string;
  description: string;
  sections: (GuiFormSectionSpec | GuiTextSectionSpec)[];
}

/** A capability's page layout, as mcp_server validated it (ember_api passes it through).
 * Typed as unknown: `parseGuiPage` checks it again before anything is drawn. */
export const capabilityPagesClient = {
  get: (name: string) => apiRequest<unknown>("GET", `/api/capabilities/${encodeURIComponent(name)}/gui`),
};
```

`src/utils/guiPage.ts`:

```ts
import type {
  GuiFieldSpec,
  GuiFormSectionSpec,
  GuiPageSpec,
  GuiResultKind,
  GuiResultSpec,
  GuiTextSectionSpec,
} from "../api/CapabilityPagesClient";
import type { JsonSchema, ToolRunResult } from "../api/types";

/** The page's layout is unusable; the message is safe to show. */
export class GuiPageError extends Error {}

const KINDS: GuiResultKind[] = ["secret", "message", "table", "fields"];
const IDENTIFIER = /^[A-Za-z_][A-Za-z0-9_]{0,63}$/;
const SECTION_ID = /^[A-Za-z0-9_-]{1,64}$/;

type Obj = Record<string, unknown>;

function isObj(value: unknown): value is Obj {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function warnUnknown(where: string, obj: Obj, known: string[]): void {
  const extra = Object.keys(obj).filter((k) => !known.includes(k));
  if (extra.length) console.warn(`Capability page: ignoring unknown ${where} keys: ${extra.join(", ")}`);
}

function text(obj: Obj, key: string, where: string, required = true): string | undefined {
  const value = obj[key];
  if (value === undefined && !required) return undefined;
  if (typeof value !== "string" || value === "") throw new GuiPageError(`${where}: '${key}' must be a non-empty string`);
  return value;
}

function name(obj: Obj, key: string, where: string): string | undefined {
  const value = text(obj, key, where, false);
  if (value !== undefined && !IDENTIFIER.test(value)) throw new GuiPageError(`${where}: '${key}' is not a field name`);
  return value;
}

function parseResult(raw: unknown, where: string): GuiResultSpec {
  if (raw === undefined) return { kind: "fields" };
  if (!isObj(raw)) throw new GuiPageError(`${where}: 'result' must be an object`);
  warnUnknown(`${where} result`, raw, ["kind", "field", "detail", "refresh_after"]);
  const kind = (raw.kind ?? "fields") as GuiResultKind;
  if (!KINDS.includes(kind)) throw new GuiPageError(`${where}: unknown result kind '${String(raw.kind)}'`);
  const result: GuiResultSpec = {
    kind,
    field: name(raw, "field", where),
    detail: name(raw, "detail", where),
    refresh_after: name(raw, "refresh_after", where),
  };
  if ((kind === "secret" || kind === "table") && !result.field) {
    throw new GuiPageError(`${where}: result kind '${kind}' needs a 'field'`);
  }
  return result;
}

function parseFields(raw: unknown, where: string): GuiFieldSpec[] {
  if (raw === undefined) return [];
  if (!Array.isArray(raw)) throw new GuiPageError(`${where}: 'fields' must be a list`);
  return raw.map((item) => {
    if (!isObj(item) || typeof item.param !== "string") throw new GuiPageError(`${where}: each field needs a 'param'`);
    warnUnknown(`${where} field`, item, ["param", "label", "order", "hidden"]);
    return {
      param: item.param,
      label: typeof item.label === "string" ? item.label : undefined,
      order: typeof item.order === "number" ? item.order : undefined,
      hidden: item.hidden === true,
    };
  });
}

function parseSection(raw: unknown, index: number): GuiFormSectionSpec | GuiTextSectionSpec {
  const where = `section ${index + 1}`;
  if (!isObj(raw)) throw new GuiPageError(`${where} must be an object`);
  const id = text(raw, "id", where)!;
  if (!SECTION_ID.test(id)) throw new GuiPageError(`${where}: bad id '${id}'`);
  if ("text" in raw && !("tool" in raw)) {
    warnUnknown(where, raw, ["id", "title", "text"]);
    return { type: "text", id, title: text(raw, "title", where, false), text: text(raw, "text", where)! };
  }
  warnUnknown(where, raw, ["id", "title", "tool", "submit", "fields", "result"]);
  return {
    type: "form",
    id,
    title: text(raw, "title", where)!,
    tool: text(raw, "tool", where)!,
    submit: text(raw, "submit", where, false) ?? "Run",
    fields: parseFields(raw.fields, where),
    result: parseResult(raw.result, where),
  };
}

/** Checks a page from mcp_server before anything is drawn. Every tool a page
 * names must be one of `ownTools` (its own capability's); unknown keys are
 * ignored with a console warning so a newer page still opens. */
export function parseGuiPage(raw: unknown, ownTools: string[]): GuiPageSpec {
  if (!isObj(raw)) throw new GuiPageError("The page is not an object");
  warnUnknown("page", raw, ["version", "title", "description", "sections"]);
  if (raw.version !== 1) throw new GuiPageError(`Unsupported page version ${String(raw.version)}`);
  if (!Array.isArray(raw.sections) || raw.sections.length === 0) throw new GuiPageError("The page has no sections");
  const sections = raw.sections.map(parseSection);
  const ids = sections.map((s) => s.id);
  const dup = ids.find((id, i) => ids.indexOf(id) !== i);
  if (dup) throw new GuiPageError(`Duplicate section id '${dup}'`);
  const foreign = sections.flatMap((s) => (s.type === "form" && !ownTools.includes(s.tool) ? [s.tool] : []));
  if (foreign.length) throw new GuiPageError(`The page names tools its capability does not own: ${foreign.join(", ")}`);
  return {
    version: 1,
    title: text(raw, "title", "page")!,
    description: typeof raw.description === "string" ? raw.description : "",
    sections,
  };
}

/** The tool's schema with the page's label/order/hidden overrides applied.
 * A required param is never hidden. Does not change its input. */
export function applyFieldOverrides(schema: JsonSchema, fields: GuiFieldSpec[]): JsonSchema {
  const properties = schema.properties ?? {};
  const required = new Set(schema.required ?? []);
  const byParam = new Map(fields.map((f) => [f.param, f]));
  const entries = Object.entries(properties)
    .filter(([param]) => !(byParam.get(param)?.hidden && !required.has(param)))
    .map(([param, prop]): [string, JsonSchema] => {
      const label = byParam.get(param)?.label;
      return [param, label ? { ...prop, title: label } : prop];
    });
  const rank = (param: string): number => byParam.get(param)?.order ?? Number.MAX_SAFE_INTEGER;
  // Array.sort is stable, so params without an order keep the tool's own order.
  entries.sort((x, y) => rank(x[0]) - rank(y[0]));
  return { ...schema, properties: Object.fromEntries(entries) };
}

/** One value from a tool's result: its structured content, or the JSON in its text. */
export function resultValue(result: ToolRunResult, field: string): unknown {
  if (result.structured && field in result.structured) return result.structured[field];
  try {
    const parsed: unknown = JSON.parse(result.text);
    return isObj(parsed) ? parsed[field] : undefined;
  } catch {
    return undefined;
  }
}
```

In `src/api/CommandsClient.ts` add to `CapabilityInfo`: `/** A page to open at /capabilities/<name> (mcp_server's gui/page.json). */ has_gui?: boolean;`

- [ ] **Step 4: Run tests and type check**

Run: `npx vitest run src/utils/guiPage.test.ts && npx vue-tsc -b --noEmit`
Expected: tests pass; vue-tsc prints nothing.

- [ ] **Step 5: Commit**

```bash
git add apps/ember_web/src
git commit -m "feat(ember_web): parse and check capability page layouts"
```

(Task 4 ends Part C's first stop: report to the user before Task 5.)

### Task 5: Countdown composable and result renderer

**Files:**
- Create: `apps/ember_web/src/composables/useCountdown.ts`
- Create: `apps/ember_web/src/components/GuiResult.vue`
- Test: `apps/ember_web/src/composables/useCountdown.test.ts`, `apps/ember_web/src/components/GuiResult.test.ts`

**Interfaces:**
- Consumes: `resultValue`, `GuiResultSpec`, `ToolRunResult`, `formatToolResult`-free (this component draws its own).
- Produces: `useCountdown(onZero: () => void): { remaining: Ref<number>; running: Ref<boolean>; start(seconds: number): void; stop(): void }`; `<GuiResult :spec="GuiResultSpec" :result="ToolRunResult" />`.

- [ ] **Step 1: Write the failing tests**

`src/composables/useCountdown.test.ts`:

```ts
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { effectScope } from "vue";
import { useCountdown } from "./useCountdown";

describe("useCountdown", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  function make(onZero = vi.fn()) {
    const scope = effectScope();
    const countdown = scope.run(() => useCountdown(onZero))!;
    return { countdown, onZero, scope };
  }

  it("counts down each second and calls onZero once at zero", () => {
    const { countdown, onZero } = make();
    countdown.start(3);
    expect(countdown.remaining.value).toBe(3);
    vi.advanceTimersByTime(2000);
    expect(countdown.remaining.value).toBe(1);
    expect(onZero).not.toHaveBeenCalled();
    vi.advanceTimersByTime(1000);
    expect(onZero).toHaveBeenCalledTimes(1);
    expect(countdown.running.value).toBe(false);
  });

  it("restarting replaces the running countdown", () => {
    const { countdown, onZero } = make();
    countdown.start(5);
    vi.advanceTimersByTime(2000);
    countdown.start(2);
    vi.advanceTimersByTime(2000);
    expect(onZero).toHaveBeenCalledTimes(1);
  });

  it("stop cancels it", () => {
    const { countdown, onZero } = make();
    countdown.start(2);
    countdown.stop();
    vi.advanceTimersByTime(5000);
    expect(onZero).not.toHaveBeenCalled();
  });

  it("stops when its scope is disposed", () => {
    const { countdown, onZero, scope } = make();
    countdown.start(2);
    scope.stop();
    vi.advanceTimersByTime(5000);
    expect(onZero).not.toHaveBeenCalled();
  });

  it("does not tick while the tab is hidden and re-syncs when it returns", () => {
    const { countdown, onZero } = make();
    countdown.start(10);
    Object.defineProperty(document, "hidden", { configurable: true, get: () => true });
    vi.advanceTimersByTime(4000);
    expect(countdown.remaining.value).toBe(10);
    Object.defineProperty(document, "hidden", { configurable: true, get: () => false });
    document.dispatchEvent(new Event("visibilitychange"));
    vi.advanceTimersByTime(1000);
    expect(countdown.remaining.value).toBe(9);
    expect(onZero).not.toHaveBeenCalled();
  });
});
```

`src/components/GuiResult.test.ts`:

```ts
import { mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";
import type { ToolRunResult } from "../api/types";
import GuiResult from "./GuiResult.vue";

const result = (structured: Record<string, unknown>, isError = false, text = ""): ToolRunResult => ({ text, isError, structured });

describe("GuiResult", () => {
  it("secret: shows the value, hidden-toggle and copy", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });
    const w = mount(GuiResult, { props: { spec: { kind: "secret", field: "password", detail: "message" }, result: result({ password: "s3cret!", message: "Generated." }) } });
    expect(w.get("[data-test=secret]").text()).toBe("s3cret!");
    expect(w.text()).toContain("Generated.");
    await w.get("[data-test=copy]").trigger("click");
    expect(writeText).toHaveBeenCalledWith("s3cret!");
    await w.get("[data-test=toggle]").trigger("click");
    expect(w.get("[data-test=secret]").text()).not.toContain("s3cret!");
    await w.get("[data-test=toggle]").trigger("click");
    expect(w.get("[data-test=secret]").text()).toBe("s3cret!");
  });

  it("message: plain text of the field, default 'message'", () => {
    const w = mount(GuiResult, { props: { spec: { kind: "message" }, result: result({ message: "All done." }) } });
    expect(w.text()).toContain("All done.");
  });

  it("table: a list of uniform objects becomes rows", () => {
    const rows = [{ name: "a", status: "up" }, { name: "b", status: "down" }];
    const w = mount(GuiResult, { props: { spec: { kind: "table", field: "apps" }, result: result({ apps: rows }) } });
    expect(w.findAll("th").map((h) => h.text())).toEqual(["name", "status"]);
    expect(w.findAll("tbody tr")).toHaveLength(2);
    expect(w.text()).toContain("down");
  });

  it("fields: label/value list of scalar fields", () => {
    const w = mount(GuiResult, { props: { spec: { kind: "fields" }, result: result({ length: 12, message: "ok" }) } });
    expect(w.text()).toContain("length");
    expect(w.text()).toContain("12");
  });

  it("a tool error shows its text, not the field", () => {
    const w = mount(GuiResult, { props: { spec: { kind: "secret", field: "password" }, result: result({}, true, "length must be between 8 and 128.") } });
    expect(w.text()).toContain("length must be between 8 and 128.");
    expect(w.find("[data-test=secret]").exists()).toBe(false);
  });

  it("a missing field says so instead of showing an empty box", () => {
    const w = mount(GuiResult, { props: { spec: { kind: "secret", field: "password" }, result: result({ other: 1 }) } });
    expect(w.text()).toMatch(/no value/i);
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `npx vitest run src/composables/useCountdown.test.ts src/components/GuiResult.test.ts`
Expected: FAIL (modules missing).

- [ ] **Step 3: Implement**

`src/composables/useCountdown.ts`:

```ts
import { onScopeDispose, ref } from "vue";

/** A whole-second countdown that calls `onZero` once at zero. It does not tick
 * while the tab is hidden (nobody sees it) and carries on when the tab returns;
 * it stops when its owner is disposed. */
export function useCountdown(onZero: () => void) {
  const remaining = ref(0);
  const running = ref(false);
  let timer: ReturnType<typeof setInterval> | null = null;

  function clear(): void {
    if (timer !== null) clearInterval(timer);
    timer = null;
    running.value = false;
  }

  function tick(): void {
    if (document.hidden) return;
    remaining.value -= 1;
    if (remaining.value <= 0) {
      remaining.value = 0;
      clear();
      onZero();
    }
  }

  function start(seconds: number): void {
    clear();
    remaining.value = Math.max(1, Math.ceil(seconds));
    running.value = true;
    timer = setInterval(tick, 1000);
  }

  onScopeDispose(clear);
  return { remaining, running, start, stop: clear };
}
```

`src/components/GuiResult.vue`:

```vue
<script setup lang="ts">
import { computed, ref } from "vue";
import type { GuiResultSpec } from "../api/CapabilityPagesClient";
import type { ToolRunResult } from "../api/types";
import { resultValue } from "../utils/guiPage";

/** One tool result drawn the way its page asked: a copyable secret, a message,
 * a table or a label/value list. Values stay in this component's memory. */
const props = defineProps<{ spec: GuiResultSpec; result: ToolRunResult }>();

const value = computed(() => (props.spec.field ? resultValue(props.result, props.spec.field) : undefined));
const detail = computed(() => {
  const v = props.spec.detail ? resultValue(props.result, props.spec.detail) : undefined;
  return typeof v === "string" ? v : "";
});
const message = computed(() => {
  const v = resultValue(props.result, props.spec.field ?? "message");
  return typeof v === "string" ? v : props.result.text;
});

const revealed = ref(true);
const copied = ref(false);
const secretText = computed(() => (value.value === undefined || value.value === null ? "" : String(value.value)));

async function copy(): Promise<void> {
  try {
    await navigator.clipboard.writeText(secretText.value);
    copied.value = true;
    setTimeout(() => (copied.value = false), 1500);
  } catch {
    // Clipboard blocked (permissions / insecure context): nothing to do.
  }
}

const rows = computed<Record<string, unknown>[]>(() =>
  Array.isArray(value.value) ? (value.value as unknown[]).filter((r): r is Record<string, unknown> => typeof r === "object" && r !== null) : [],
);
const columns = computed(() => [...new Set(rows.value.flatMap((r) => Object.keys(r)))]);

const scalars = computed(() =>
  Object.entries(props.result.structured ?? {}).filter(([, v]) => ["string", "number", "boolean"].includes(typeof v)),
);
</script>

<template>
  <div :class="['gui-result', { failed: result.isError }]">
    <p v-if="result.isError" class="error">{{ result.text || "The tool reported an error." }}</p>
    <template v-else-if="spec.kind === 'secret'">
      <p v-if="secretText === ''" class="muted">The tool returned no value for '{{ spec.field }}'.</p>
      <div v-else class="secret-row">
        <code data-test="secret" class="secret">{{ revealed ? secretText : "•".repeat(Math.min(secretText.length, 32)) }}</code>
        <button type="button" data-test="toggle" @click="revealed = !revealed">{{ revealed ? "Hide" : "Show" }}</button>
        <button type="button" data-test="copy" @click="copy">{{ copied ? "Copied" : "Copy" }}</button>
      </div>
      <p v-if="detail" class="muted">{{ detail }}</p>
    </template>
    <p v-else-if="spec.kind === 'message'">{{ message }}</p>
    <template v-else-if="spec.kind === 'table'">
      <p v-if="rows.length === 0" class="muted">No rows.</p>
      <table v-else>
        <thead><tr><th v-for="c in columns" :key="c">{{ c }}</th></tr></thead>
        <tbody><tr v-for="(r, i) in rows" :key="i"><td v-for="c in columns" :key="c">{{ r[c] ?? "" }}</td></tr></tbody>
      </table>
    </template>
    <dl v-else class="fields">
      <template v-for="[k, v] in scalars" :key="k"><dt>{{ k }}</dt><dd>{{ v }}</dd></template>
    </dl>
  </div>
</template>

<style scoped>
.gui-result { margin-top: 12px; }
.secret-row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.secret { padding: 6px 10px; border: 1px solid var(--border); border-radius: 8px; background: var(--surface); word-break: break-all; }
.error { color: var(--danger, #c0392b); }
.fields { display: grid; grid-template-columns: max-content 1fr; gap: 4px 12px; }
table { border-collapse: collapse; }
th, td { padding: 4px 10px; border-bottom: 1px solid var(--border); text-align: left; }
</style>
```

- [ ] **Step 4: Run tests and type check**

Run: `npx vitest run src/composables/useCountdown.test.ts src/components/GuiResult.test.ts && npx vue-tsc -b --noEmit`
Expected: pass. If the existing CSS variables used in `<style>` (`--border`, `--surface`) differ, use the names `CapabilitySection.vue` uses.

- [ ] **Step 5: Commit**

```bash
git add apps/ember_web/src
git commit -m "feat(ember_web): countdown and result renderer for capability pages"
```

### Task 6: Form section and page view

**Files:**
- Create: `apps/ember_web/src/components/GuiFormSection.vue`
- Create: `apps/ember_web/src/views/CapabilityPageView.vue`
- Test: `apps/ember_web/src/components/GuiFormSection.test.ts`, `apps/ember_web/src/views/CapabilityPageView.test.ts`

**Interfaces:**
- Consumes: `ToolRunForm` (`props: schema, running, submitLabel?`; `emits run(args)`), `GuiResult`, `useCountdown`, `applyFieldOverrides`, `resultValue`, `parseGuiPage`, `capabilityPagesClient.get`, `commandsClient.capabilities`, `McpServerClient.listTools/runTool`.
- Produces: `<GuiFormSection :section="GuiFormSectionSpec" :tool="ToolInfo" :run-tool="(name, args) => Promise<ToolRunResult>" />`; view for route `/capabilities/:name`.

- [ ] **Step 1: Write the failing tests**

`src/components/GuiFormSection.test.ts`:

```ts
import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { GuiFormSectionSpec } from "../api/CapabilityPagesClient";
import type { ToolInfo, ToolRunResult } from "../api/types";
import GuiFormSection from "./GuiFormSection.vue";

vi.mock("../api/CommandsClient", () => ({ commandsClient: { options: vi.fn(), upload: vi.fn() } }));

const TOOL: ToolInfo = {
  name: "tool_a",
  title: "A",
  description: "Makes a thing.",
  inputSchema: { type: "object", properties: { length: { type: "integer", default: 12 } } },
};
const SECTION: GuiFormSectionSpec = {
  type: "form", id: "a", title: "Thing", tool: "tool_a", submit: "Make it", fields: [],
  result: { kind: "secret", field: "code" },
};
const ok = (structured: Record<string, unknown>): ToolRunResult => ({ text: "", isError: false, structured });

describe("GuiFormSection", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("runs the tool with the form's values and shows the result", async () => {
    const runTool = vi.fn().mockResolvedValue(ok({ code: "abc" }));
    const w = mount(GuiFormSection, { props: { section: SECTION, tool: TOOL, runTool } });
    expect(w.text()).toContain("Thing");
    await w.get("form").trigger("submit");
    await flushPromises();
    expect(runTool).toHaveBeenCalledWith("tool_a", { length: 12 });
    expect(w.get("[data-test=secret]").text()).toBe("abc");
  });

  it("shows a transport failure inline", async () => {
    const runTool = vi.fn().mockRejectedValue(new Error("mcp_server is unreachable"));
    const w = mount(GuiFormSection, { props: { section: SECTION, tool: TOOL, runTool } });
    await w.get("form").trigger("submit");
    await flushPromises();
    expect(w.text()).toContain("mcp_server is unreachable");
  });

  it("re-runs with the same arguments when the refresh countdown ends", async () => {
    const section = { ...SECTION, result: { kind: "secret", field: "code", refresh_after: "seconds_remaining" } } as GuiFormSectionSpec;
    const runTool = vi.fn()
      .mockResolvedValueOnce(ok({ code: "111111", seconds_remaining: 2 }))
      .mockResolvedValueOnce(ok({ code: "222222", seconds_remaining: 30 }));
    const w = mount(GuiFormSection, { props: { section, tool: TOOL, runTool } });
    await w.get("form").trigger("submit");
    await flushPromises();
    expect(w.text()).toMatch(/2\s*s/);
    vi.advanceTimersByTime(2000);
    await flushPromises();
    expect(runTool).toHaveBeenCalledTimes(2);
    expect(runTool).toHaveBeenLastCalledWith("tool_a", { length: 12 });
    expect(w.get("[data-test=secret]").text()).toBe("222222");
  });

  it("stops refreshing when unmounted", async () => {
    const section = { ...SECTION, result: { kind: "secret", field: "code", refresh_after: "seconds_remaining" } } as GuiFormSectionSpec;
    const runTool = vi.fn().mockResolvedValue(ok({ code: "1", seconds_remaining: 2 }));
    const w = mount(GuiFormSection, { props: { section, tool: TOOL, runTool } });
    await w.get("form").trigger("submit");
    await flushPromises();
    w.unmount();
    vi.advanceTimersByTime(10_000);
    expect(runTool).toHaveBeenCalledTimes(1);
  });

  it("applies label overrides to the form", () => {
    const section = { ...SECTION, fields: [{ param: "length", label: "How long" }] };
    const w = mount(GuiFormSection, { props: { section, tool: TOOL, runTool: vi.fn() } });
    expect(w.text()).toContain("How long");
  });
});
```

`src/views/CapabilityPageView.test.ts` (same mocking style as `CapabilitiesView.test.ts`):

```ts
import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createMemoryHistory, createRouter } from "vue-router";
import type { CapabilityInfo } from "../api/CommandsClient";
import type { ToolInfo } from "../api/types";
import CapabilityPageView from "./CapabilityPageView.vue";

const mocks = vi.hoisted(() => ({ capabilities: vi.fn(), page: vi.fn(), listTools: vi.fn(), runTool: vi.fn() }));

vi.mock("../api/CommandsClient", () => ({ commandsClient: { capabilities: mocks.capabilities, options: vi.fn(), upload: vi.fn() } }));
vi.mock("../api/CapabilityPagesClient", () => ({ capabilityPagesClient: { get: mocks.page } }));
vi.mock("../api/McpServerClient", () => ({
  McpServerClient: class {
    listTools = mocks.listTools;
    runTool = mocks.runTool;
  },
}));

const CAP: CapabilityInfo = { name: "gen", enabled: true, label: "Generator", tools: ["tool_a"], resources: [], has_gui: true };
const TOOL: ToolInfo = { name: "tool_a", title: "A", description: "", inputSchema: { type: "object", properties: {} } };
const PAGE = { version: 1, title: "Generator page", description: "Intro", sections: [{ id: "a", title: "Make", tool: "tool_a", submit: "Go", result: { kind: "message" } }, { id: "n", text: "A note." }] };

async function open(path = "/capabilities/gen") {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/capabilities", component: { template: "<div />" } },
      { path: "/capabilities/:name", component: CapabilityPageView },
    ],
  });
  await router.push(path);
  const w = mount(CapabilityPageView, { global: { plugins: [createPinia(), router] } });
  await flushPromises();
  return w;
}

describe("CapabilityPageView", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    Object.values(mocks).forEach((m) => m.mockReset());
    mocks.capabilities.mockResolvedValue([CAP]);
    mocks.page.mockResolvedValue(PAGE);
    mocks.listTools.mockResolvedValue([TOOL]);
  });

  it("draws the title, description, form and text sections", async () => {
    const w = await open();
    expect(w.text()).toContain("Generator page");
    expect(w.text()).toContain("Intro");
    expect(w.text()).toContain("Make");
    expect(w.text()).toContain("A note.");
    expect(w.find('a[href="/capabilities"]').exists()).toBe(true);
    expect(mocks.page).toHaveBeenCalledWith("gen");
  });

  it("says so when the capability has no page", async () => {
    mocks.page.mockRejectedValue(Object.assign(new Error("Capability 'gen' has no page"), { status: 404 }));
    const w = await open();
    expect(w.text()).toMatch(/no page/i);
  });

  it("shows a layout problem instead of a half-drawn page", async () => {
    mocks.page.mockResolvedValue({ ...PAGE, sections: [{ id: "a", title: "x", tool: "tool_zzz" }] });
    const w = await open();
    expect(w.text()).toMatch(/layout/i);
    expect(w.text()).toContain("tool_zzz");
  });

  it("says when the capability is off", async () => {
    mocks.capabilities.mockResolvedValue([{ ...CAP, enabled: false }]);
    const w = await open();
    expect(w.text()).toMatch(/turned off/i);
    expect(mocks.page).not.toHaveBeenCalled();
  });

  it("says when the capability is unknown", async () => {
    const w = await open("/capabilities/zzz");
    expect(w.text()).toMatch(/unknown/i);
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `npx vitest run src/components/GuiFormSection.test.ts src/views/CapabilityPageView.test.ts`
Expected: FAIL (components missing).

- [ ] **Step 3: Implement**

`src/components/GuiFormSection.vue`:

```vue
<script setup lang="ts">
import { computed, ref } from "vue";
import type { GuiFormSectionSpec } from "../api/CapabilityPagesClient";
import type { ToolInfo, ToolRunResult } from "../api/types";
import { useCountdown } from "../composables/useCountdown";
import { errorMessage } from "../utils/errors";
import { applyFieldOverrides, resultValue } from "../utils/guiPage";
import GuiResult from "./GuiResult.vue";
import ToolRunForm from "./ToolRunForm.vue";

/** One form section of a capability page: the tool's form (built from its own
 * schema), the run, and its result. With `refresh_after` the tool is run again
 * with the same arguments when the countdown ends. State is memory only. */
const props = defineProps<{
  section: GuiFormSectionSpec;
  tool: ToolInfo;
  runTool: (name: string, args: Record<string, unknown>) => Promise<ToolRunResult>;
}>();

const schema = computed(() => applyFieldOverrides(props.tool.inputSchema, props.section.fields));
const running = ref(false);
const result = ref<ToolRunResult | null>(null);
const error = ref("");
let lastArgs: Record<string, unknown> = {};

const countdown = useCountdown(() => void run(lastArgs));

async function run(args: Record<string, unknown>): Promise<void> {
  lastArgs = args;
  running.value = true;
  error.value = "";
  countdown.stop();
  try {
    result.value = await props.runTool(props.tool.name, args);
    const after = props.section.result.refresh_after;
    const seconds = after && !result.value.isError ? resultValue(result.value, after) : undefined;
    if (typeof seconds === "number" && seconds > 0) countdown.start(seconds);
  } catch (err) {
    result.value = null;
    error.value = errorMessage(err);
  } finally {
    running.value = false;
  }
}
</script>

<template>
  <section class="card">
    <h3>{{ section.title }}</h3>
    <p v-if="tool.description" class="muted">{{ tool.description }}</p>
    <ToolRunForm :schema="schema" :running="running" :submit-label="section.submit" @run="run" />
    <p v-if="error" class="error">{{ error }}</p>
    <GuiResult v-if="result" :spec="section.result" :result="result" />
    <p v-if="countdown.running.value" class="muted">New code in {{ countdown.remaining.value }} s</p>
  </section>
</template>

<style scoped>
.card { margin-bottom: 12px; padding: 12px 14px; border: 1px solid var(--border); border-radius: 10px; background: var(--surface); }
.error { color: var(--danger, #c0392b); }
</style>
```

`src/views/CapabilityPageView.vue`:

```vue
<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { RouterLink, useRoute } from "vue-router";
import { capabilityPagesClient, type GuiPageSpec } from "../api/CapabilityPagesClient";
import { commandsClient } from "../api/CommandsClient";
import { McpServerClient } from "../api/McpServerClient";
import type { ToolInfo } from "../api/types";
import GuiFormSection from "../components/GuiFormSection.vue";
import { errorMessage } from "../utils/errors";
import { GuiPageError, parseGuiPage } from "../utils/guiPage";

/** A capability's own page (mcp_server's gui/page.json): a title, notes and
 * one form per tool section. Nothing here is specific to one capability. */
const route = useRoute();
const server = new McpServerClient();

const name = computed(() => String(route.params.name ?? ""));
const loading = ref(true);
const problem = ref("");
const page = ref<GuiPageSpec | null>(null);
const label = ref("");
const tools = ref<Record<string, ToolInfo>>({});

async function load(): Promise<void> {
  loading.value = true;
  problem.value = "";
  page.value = null;
  try {
    const capability = (await commandsClient.capabilities()).find((c) => c.name === name.value);
    if (!capability) {
      problem.value = `Unknown capability '${name.value}'.`;
      return;
    }
    label.value = capability.label ?? capability.name;
    if (!capability.enabled) {
      problem.value = `${label.value} is turned off.`;
      return;
    }
    const [raw, allTools] = await Promise.all([capabilityPagesClient.get(name.value), server.listTools()]);
    page.value = parseGuiPage(raw, capability.tools);
    tools.value = Object.fromEntries(allTools.map((t) => [t.name, t]));
  } catch (err) {
    if (err instanceof GuiPageError) problem.value = `This page's layout is invalid: ${err.message}`;
    else if ((err as { status?: number }).status === 404) problem.value = `${label.value || name.value} has no page.`;
    else problem.value = errorMessage(err);
  } finally {
    loading.value = false;
  }
}

const runTool = (tool: string, args: Record<string, unknown>) => server.runTool(tool, args);

onMounted(load);
watch(name, load);
</script>

<template>
  <div class="page">
    <p><RouterLink to="/capabilities">← Capabilities</RouterLink></p>
    <p v-if="loading" class="muted">Loading…</p>
    <p v-else-if="problem" class="error" role="alert">{{ problem }}</p>
    <template v-else-if="page">
      <h2>{{ page.title }}</h2>
      <p v-if="page.description" class="muted">{{ page.description }}</p>
      <template v-for="s in page.sections" :key="s.id">
        <section v-if="s.type === 'text'" class="note">
          <h3 v-if="s.title">{{ s.title }}</h3>
          <p>{{ s.text }}</p>
        </section>
        <GuiFormSection v-else-if="tools[s.tool]" :section="s" :tool="tools[s.tool]" :run-tool="runTool" />
        <p v-else class="error">The tool {{ s.tool }} is not available right now.</p>
      </template>
    </template>
  </div>
</template>

<style scoped>
.page { max-width: 760px; margin: 0 auto; padding: 16px; }
.error { color: var(--danger, #c0392b); }
</style>
```

Verify `apiRequest` errors carry a numeric `status` (look at `src/api/http.ts`'s `ApiError`); if the property has a different name, use it in the 404 check and in the test's rejected error.

- [ ] **Step 4: Run tests and type check**

Run: `npx vitest run src/components/GuiFormSection.test.ts src/views/CapabilityPageView.test.ts && npx vue-tsc -b --noEmit`
Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add apps/ember_web/src
git commit -m "feat(ember_web): capability page view with form sections"
```

### Task 7: Route, "Open page" link and docs

**Files:**
- Modify: `apps/ember_web/src/router/index.ts`
- Modify: `apps/ember_web/src/components/CapabilitySection.vue`
- Modify: `apps/ember_web/src/views/CapabilitiesView.test.ts` (link test), `apps/ember_web/src/components/NavRail.vue` only if its active-link logic misses `/capabilities/<name>`
- Modify: `apps/ember_web/README.md`, `.agents/skills/ember-feature-scaffold/SKILL.md`

**Interfaces:**
- Consumes: `CapabilityInfo.has_gui?: boolean`, view from Task 6.
- Produces: route `{ path: "/capabilities/:name", name: "capability-page" }` (permission `tools.use`); an "Open page" `RouterLink` in each card header whose capability is on and has a page.

- [ ] **Step 1: Write the failing test**

Add to `src/views/CapabilitiesView.test.ts` (use that file's own mount helper and mocks; the route list in its router needs `{ path: "/capabilities/:name", component: { template: "<div />" } }` added so `RouterLink` resolves). Give one fixture capability `has_gui: true` (for example `pdf`) and add:

```ts
it("links a capability that has a page to it, and only that one", async () => {
  const wrapper = await mountView(); // the file's existing helper
  const links = wrapper.findAll("a").filter((a) => a.text() === "Open page");
  expect(links).toHaveLength(1);
  expect(links[0].attributes("href")).toBe("/capabilities/pdf");
});
```

Use the name of the helper that file already uses in its other tests.

- [ ] **Step 2: Run to verify failure**

Run: `npx vitest run src/views/CapabilitiesView.test.ts`
Expected: new test FAILs (no link).

- [ ] **Step 3: Implement**

`router/index.ts`, after the `/capabilities` entry:

```ts
    {
      path: "/capabilities/:name",
      name: "capability-page",
      component: () => import("../views/CapabilityPageView.vue"),
      meta: { permission: "tools.use" },
    },
```

`CapabilitySection.vue`: import `RouterLink` from `vue-router`, and inside `<header class="card-head">` just before the toggle/badge block add:

```vue
      <RouterLink
        v-if="capability.has_gui && capability.enabled"
        class="page-link"
        :to="`/capabilities/${encodeURIComponent(capability.name)}`"
        @click.stop
      >Open page</RouterLink>
```

with style `.page-link { margin-right: 10px; font-size: 0.85rem; white-space: nowrap; }`. Run the full ember_web suite; fix any component test that mounts `CapabilitySection` without a router by adding a `RouterLink` stub (`global: { stubs: { RouterLink: true } }`).

- [ ] **Step 4: Check the nav rail highlight**

Run: `grep -n "startsWith\|route.path\|isActive\|exact" src/components/NavRail.vue`. If the Capabilities item is active only for an exact `/capabilities`, change the check so `/capabilities/<name>` also highlights it (with a NavRail test); if it already matches by prefix, change nothing.

- [ ] **Step 5: Docs**

`apps/ember_web/README.md`: a "Capability pages" section (route, what draws it, where the layout comes from, the memory-only rule). `.agents/skills/ember-feature-scaffold/SKILL.md`: one bullet saying a capability page is declared in the capability's `gui/page.json` (see mcp_server's capabilities README), not as a new Vue view; then `python sync_skills.py` from the repo root.

- [ ] **Step 6: Full ember_web check and commit**

Run: `npx vitest run && npx vue-tsc -b --noEmit`
Expected: all pass, no type errors.

```bash
git add apps/ember_web .agents .claude
git commit -m "feat(ember_web): route and card link for capability pages"
```

Stop and report to the user before Task 8.

---

### Task 8: Final check

- [ ] **Step 1:** Run every suite once more: mcp_server (`.venv_mcp`), ember_api (`.venv_ember_api`, about 5 minutes), ember_web (`npx vitest run`, `npx vue-tsc -b --noEmit`). Expected: all pass.
- [ ] **Step 2:** Start `mcp_server`, `ember_api` and `ember_web` (launch.json / `run.bat` files). Log in, open Capabilities: the Generator card shows "Open page". Open it and check: each of the five forms runs, a password is copyable and can be hidden, the TOTP section counts down and refreshes the code by itself (compare with an authenticator app using a secret from the "New TOTP secret" form), and `/capabilities/server` shows the "has no page" message.
- [ ] **Step 3:** Update `Brain/Projects/MCPServer.md`, `mcp_server.md`, `ember_web.md`, `ember_api.md` (one line each) and report the result to the user. Push only if the user asks.

## Self-Review Notes

- Spec coverage: data flow (Tasks 1-3, 6), security rules (Tasks 1, 4: ownership checked in both places; Task 5-6: memory only), folder shape and docs (Tasks 2, 7), page format (Tasks 1, 4), errors (Task 2: 404; Task 6: view messages; Task 6: inline tool errors), tests (every task), rollout (task order and stops). The spec's Playwright test is replaced by the manual browser check in Task 8 (see Global Constraints).
- Type names used across tasks: `GuiPageSpec`, `GuiFormSectionSpec`, `GuiTextSectionSpec`, `GuiFieldSpec`, `GuiResultSpec`, `parseGuiPage`, `applyFieldOverrides`, `resultValue`, `useCountdown`, `capabilityPagesClient.get`, `McpServerInfo.capability_page`, `load_page`, `parse_page`.
