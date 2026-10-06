# Generator page redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the generator capability's five stacked forms with one tabbed page: a result card with a strength bar on top, live controls below, and a TOTP countdown ring.

**Architecture:** Extend the declarative `gui/page.json` format with generic pieces (`tabs` section, `live` forms, `strength` and `group` on secret results), validated by both mcp_server (pydantic) and ember_web (parser). ember_web draws them with a new `GuiTabsSection`, a live mode on `ToolRunForm`, and an upgraded secret result card. The generator ships a new `page.json` using them.

**Tech Stack:** Python 3 + pydantic + pytest (mcp_server, venv `apps/mcp_server/.venv_mcp`); Vue 3.5 + TypeScript + Vitest + Playwright (ember_web, `apps/ember_web`).

**Spec:** `docs/superpowers/specs/2026-10-06-generator-page-design.md`

## Global Constraints

- Page `version` stays `1`; every addition is optional; unknown keys are ignored (spec: Compatibility).
- `tabs`: 2 to 8 form sections per tabs section. `group`: whole number 2 to 8. `strength` and `group` only on `kind: "secret"`.
- Section ids are unique across the whole page, tab ids included. A page may only name its own capability's tools, tabs included.
- Strength levels: Weak under 45 bits, Fair under 70, Strong under 100, Excellent from 100; the bar is full at 128 bits.
- Live runs: first run when the tab first opens (not at page load); later runs on committed changes only (slider release, chip/select/checkbox change), debounced 300 ms. Never one call per slider tick.
- A tab keeps its control values when you switch away (`KeepAlive`); a hidden tab must not keep running its `refresh_after` countdown.
- The secret is never an `aria-live` region. Bar and ring transitions respect `prefers-reduced-motion`.
- Default behaviour of `ToolRunForm` (Tools page, chat command form) is unchanged except that the three bounded integer fields now draw as sliders (schema hint `input: "range"`).
- Code comments, commit messages and docs in normal English. Commit trailer: `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.
- Never run git at `D:\User\Documents\Programming` root; this repo's root is `D:\User\Documents\Programming\Python\MCPServer`. Do not stage `apps/server_launcher/data/groups.json` (unrelated local change).
- Commands below assume the repo root as the working directory unless stated.

---

## File structure

| File | Responsibility |
|---|---|
| `apps/mcp_server/src/capability_gui.py` | page models: add `GuiTabsSection`, `live`, `strength`, `group`, `form_sections()` |
| `apps/mcp_server/src/capabilities/README.md` | document the new page keys |
| `apps/mcp_server/src/capabilities/generator/contract.py`, `domain.py`, `tool.py` | PIN `entropy_bits`; `input: "range"` hints |
| `apps/mcp_server/src/capabilities/generator/gui/page.json` | the new tabbed page |
| `apps/mcp_server/src/capabilities/generator/README.md` | one line about the page |
| `apps/mcp_server/tests/test_capability_gui.py`, `test_generator_domain.py` | tests for the above |
| `apps/ember_web/src/api/CapabilityPagesClient.ts` | spec types |
| `apps/ember_web/src/utils/guiPage.ts` | parser for the new keys, `formSections()` |
| `apps/ember_web/src/utils/secretDisplay.ts` (new) | pure helpers: `strengthOf`, `groupText`, `segmentsOf` |
| `apps/ember_web/src/style.css` | new `--success` token |
| `apps/ember_web/src/components/GuiResult.vue` | upgraded secret result |
| `apps/ember_web/src/components/ToolRunForm.vue` | `live` mode |
| `apps/ember_web/src/components/CountdownRing.vue` (new) | small SVG ring |
| `apps/ember_web/src/components/GuiFormSection.vue` | live runs, embedded layout, ring, KeepAlive hooks |
| `apps/ember_web/src/components/GuiTabsSection.vue` (new) | tab bar + panel |
| `apps/ember_web/src/views/CapabilityPageView.vue` | draw `tabs` sections |

---

### Task 1: Page models in mcp_server

**Files:**
- Modify: `apps/mcp_server/src/capability_gui.py`
- Modify: `apps/mcp_server/tests/test_capability_gui.py`
- Modify: `apps/mcp_server/src/capabilities/README.md` ("GUI pages" section)

**Interfaces:**
- Produces: `GuiTabsSection(id: str, tabs: list[GuiFormSection])`; `GuiFormSection.live: bool = False`; `GuiResult.strength: str | None`, `GuiResult.group: int | None`; `form_sections(page: GuiPage) -> Iterator[GuiFormSection]` (every form, tab forms included, in page order).

- [ ] **Step 1: Write the failing tests**

In `apps/mcp_server/tests/test_capability_gui.py`, change the import line

```python
from src.capability_gui import GuiFormSection, GuiTextSection, load_page, parse_page
```

to

```python
from src.capability_gui import GuiFormSection, GuiTabsSection, GuiTextSection, form_sections, load_page, parse_page
```

and add after `test_tool_of_another_capability_is_refused`:

```python
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
```

Also change `test_shipped_pages_parse_and_name_only_their_own_tools` so it walks tabs. Replace its loop header, these three lines:

```python
    for section in page.sections:
        if not isinstance(section, GuiFormSection):
            continue
```

with the single line:

```python
    for section in form_sections(page):
```

(the body of the loop, including the `assert hasattr(module, section.tool), f"..."` line, stays as it is), and change the `named = ...` line inside the loop to

```python
        named = {section.result.field, section.result.detail, section.result.refresh_after, section.result.strength} - {None}
```

Add a route test next to `test_gui_route_serves_no_nulls`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd apps/mcp_server && .venv_mcp/Scripts/python.exe -m pytest tests/test_capability_gui.py -q`
Expected: collection error `ImportError: cannot import name 'GuiTabsSection'`.

- [ ] **Step 3: Implement the models**

In `apps/mcp_server/src/capability_gui.py`:

Add `from collections.abc import Iterator` to the imports (next to `import logging`).

Replace `GuiResult` with:

```python
class GuiResult(BaseModel):
    """How a tool's structured result is shown. `field` names the value to show.
    `strength` names a numeric result field (bits of entropy) that draws a
    strength bar; `group` spaces a secret for reading (copying still copies it
    whole). Both only apply to a `secret`."""

    model_config = ConfigDict(extra="ignore")
    kind: Literal["secret", "message", "table", "fields"] = "fields"
    field: str | None = None
    detail: str | None = None
    refresh_after: str | None = None
    strength: str | None = None
    group: int | None = Field(default=None, ge=2, le=8)

    _check_names = field_validator("field", "detail", "refresh_after", "strength")(lambda cls, value: _identifier(value))

    @model_validator(mode="after")
    def _needs_a_field(self) -> "GuiResult":
        if self.kind in ("secret", "table") and self.field is None:
            raise ValueError(f"result kind {self.kind!r} needs a 'field'")
        if self.kind != "secret" and (self.strength is not None or self.group is not None):
            raise ValueError("'strength' and 'group' only apply to a result of kind 'secret'")
        return self
```

In `GuiFormSection` add after `result`:

```python
    # Runs when it opens and whenever a control changes (ember_web debounces).
    live: bool = False
```

After `GuiTextSection` add:

```python
MAX_TABS = 8


class GuiTabsSection(BaseModel):
    """Several forms shown one at a time, each tab keeping its own settings."""

    model_config = ConfigDict(extra="ignore")
    id: str = Field(pattern=_SECTION_ID)
    tabs: list[GuiFormSection] = Field(min_length=2, max_length=MAX_TABS)
```

Replace `_section_kind` and `GuiSection`:

```python
def _section_kind(value: Any) -> str:
    if isinstance(value, dict):
        if "tabs" in value:
            return "tabs"
        return "text" if "text" in value else "form"
    if isinstance(value, GuiTabsSection):
        return "tabs"
    return "text" if isinstance(value, GuiTextSection) else "form"


GuiSection = Annotated[
    Union[
        Annotated[GuiFormSection, Tag("form")],
        Annotated[GuiTextSection, Tag("text")],
        Annotated[GuiTabsSection, Tag("tabs")],
    ],
    Discriminator(_section_kind),
]
```

Replace `GuiPage._unique_section_ids` body:

```python
    @model_validator(mode="after")
    def _unique_section_ids(self) -> "GuiPage":
        ids: list[str] = []
        for section in self.sections:
            ids.append(section.id)
            if isinstance(section, GuiTabsSection):
                ids.extend(tab.id for tab in section.tabs)
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        if duplicates:
            raise ValueError(f"duplicate section ids: {', '.join(duplicates)}")
        return self


def form_sections(page: GuiPage) -> Iterator[GuiFormSection]:
    """Every form of the page, those inside tabs included, in page order."""
    for section in page.sections:
        if isinstance(section, GuiFormSection):
            yield section
        elif isinstance(section, GuiTabsSection):
            yield from section.tabs
```

In `parse_page` replace the `named = ...` line with:

```python
        named = {form.tool for form in form_sections(page)}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd apps/mcp_server && .venv_mcp/Scripts/python.exe -m pytest tests/test_capability_gui.py -q`
Expected: all pass (the shipped generator page still parses: it has no tabs yet).

- [ ] **Step 5: Document the new keys**

In `apps/mcp_server/src/capabilities/README.md`, in "GUI pages", after the bullet starting "- Section types:" replace that bullet with:

```markdown
- Section types: a form bound to one `tool` (with `id`, `title`, optional
  `submit`, `fields`, `result`, `live`), a plain `text` section for notes,
  and a `tabs` section (`id` plus 2 to 8 `tabs`, each one a form section; its
  `title` is the tab label). Section ids are unique across the page, tab ids
  included.
- `live: true` on a form runs it when it first opens and again whenever a
  control changes (ember_web waits 300 ms and does not run on every slider
  tick). The result then offers a Generate again button.
```

and after the bullet starting "- `refresh_after` names" add:

```markdown
- On a `secret` result, `strength` names a numeric result field (bits of
  entropy) that draws a strength bar (Weak under 45, Fair under 70, Strong
  under 100, Excellent above), and `group` (2 to 8) shows the value in groups
  of that many characters while copying the whole value.
```

- [ ] **Step 6: Commit**

```bash
git add apps/mcp_server/src/capability_gui.py apps/mcp_server/tests/test_capability_gui.py apps/mcp_server/src/capabilities/README.md
git commit -m "feat(mcp_server): tabs, live forms, strength and group in GUI pages

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Generator contract, hints and page

**Files:**
- Modify: `apps/mcp_server/src/capabilities/generator/contract.py` (`PinResult`)
- Modify: `apps/mcp_server/src/capabilities/generator/domain.py` (`generate_pin`)
- Modify: `apps/mcp_server/src/capabilities/generator/tool.py` (three parameters)
- Replace: `apps/mcp_server/src/capabilities/generator/gui/page.json`
- Modify: `apps/mcp_server/src/capabilities/generator/README.md` ("Page" section)
- Test: `apps/mcp_server/tests/test_generator_domain.py`

**Interfaces:**
- Consumes: `GuiTabsSection`, `live`, `strength`, `group` from Task 1.
- Produces: `PinResult.entropy_bits: float`; tool schemas with `"input": "range"` on `tool_gen_generatePassword.length`, `tool_gen_generatePassphrase.words`, `tool_gen_generatePin.length`; the shipped page the ember_web tasks render.

- [ ] **Step 1: Write the failing tests**

Append to `apps/mcp_server/tests/test_generator_domain.py`:

```python
def test_pin_reports_its_entropy():
    assert domain.generate_pin(6).entropy_bits == round(6 * math.log2(10), 1)
    assert domain.generate_pin(12).entropy_bits > domain.generate_pin(4).entropy_bits


@pytest.mark.parametrize(
    ("tool_name", "param"),
    [
        ("tool_gen_generatePassword", "length"),
        ("tool_gen_generatePassphrase", "words"),
        ("tool_gen_generatePin", "length"),
    ],
)
def test_bounded_numbers_ask_for_a_slider(tool_name, param):
    import inspect
    import typing

    from pydantic import TypeAdapter

    from src.capabilities.generator import tool

    function = inspect.unwrap(getattr(tool, tool_name))
    annotation = typing.get_type_hints(function, include_extras=True)[param]
    schema = TypeAdapter(annotation).json_schema()

    assert schema["input"] == "range"
    assert "minimum" in schema and "maximum" in schema
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd apps/mcp_server && .venv_mcp/Scripts/python.exe -m pytest tests/test_generator_domain.py -q`
Expected: FAIL (`AttributeError ... entropy_bits` and `KeyError: 'input'`).

- [ ] **Step 3: Implement**

`contract.py`, `PinResult`: add after `length`:

```python
    entropy_bits: float = Field(description="Strength in bits (length x log2 of 10).")
```

`domain.py`, `generate_pin`: change the return to

```python
    return PinResult(
        pin=pin,
        length=length,
        entropy_bits=_entropy_bits(10, length),
        message=f"Generated a {length}-digit code. It is shown once and not stored.",
    )
```

`tool.py`: change three annotations.

```python
    length: Annotated[int, Field(description="Password length in characters.", ge=8, le=128, json_schema_extra={"input": "range"})] = 20,
```
```python
    words: Annotated[int, Field(description="How many words.", ge=3, le=12, json_schema_extra={"input": "range"})] = 6,
```
```python
    length: Annotated[int, Field(description="How many digits.", ge=4, le=12, json_schema_extra={"input": "range"})] = 6,
```

Replace `gui/page.json` with:

```json
{
  "version": 1,
  "title": "Generator",
  "description": "Random passwords, passphrases, PINs and TOTP codes. Nothing is stored; a value is shown once.",
  "sections": [
    {
      "id": "generate",
      "tabs": [
        {
          "id": "password",
          "title": "Password",
          "tool": "tool_gen_generatePassword",
          "live": true,
          "result": { "kind": "secret", "field": "password", "detail": "message", "strength": "entropy_bits" }
        },
        {
          "id": "passphrase",
          "title": "Passphrase",
          "tool": "tool_gen_generatePassphrase",
          "live": true,
          "result": { "kind": "secret", "field": "passphrase", "detail": "message", "strength": "entropy_bits" }
        },
        {
          "id": "pin",
          "title": "PIN",
          "tool": "tool_gen_generatePin",
          "live": true,
          "result": { "kind": "secret", "field": "pin", "detail": "message", "strength": "entropy_bits" }
        },
        {
          "id": "totp-secret",
          "title": "TOTP secret",
          "tool": "tool_gen_generateTotpSecret",
          "submit": "Generate",
          "result": { "kind": "secret", "field": "secret", "detail": "message" }
        },
        {
          "id": "totp",
          "title": "TOTP code",
          "tool": "tool_gen_getTotpCode",
          "submit": "Show code",
          "result": { "kind": "secret", "field": "code", "detail": "message", "group": 3, "refresh_after": "seconds_remaining" }
        }
      ]
    },
    { "id": "note", "text": "Nothing here is stored. A generated value travels through the chat like any tool result." }
  ]
}
```

`generator/README.md`, "Page" section: replace the sentence with

```markdown
`gui/page.json` gives the capability a page at `/capabilities/gen` in ember_web: one tabbed card (Password, Passphrase and PIN regenerate live as you change a control; TOTP secret and TOTP code run on request) with a strength bar from `entropy_bits`.
```

Also in the README "Tools"/contract text, where `tool_gen_generatePin` is described, add that its result includes `entropy_bits`. (Search the README for "PIN" and edit the one sentence that lists its result fields; if it lists none, skip.)

- [ ] **Step 4: Run the tests**

Run: `cd apps/mcp_server && .venv_mcp/Scripts/python.exe -m pytest tests/test_generator_domain.py tests/test_capability_gui.py -q`
Expected: PASS, including `test_shipped_pages_parse_and_name_only_their_own_tools[generator]` (it now checks every tab's tool and its named result fields, `entropy_bits` on `PinResult` included).

- [ ] **Step 5: Run the whole mcp_server suite**

Run: `cd apps/mcp_server && .venv_mcp/Scripts/python.exe -m pytest -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add apps/mcp_server/src/capabilities/generator apps/mcp_server/tests/test_generator_domain.py
git commit -m "feat(generator): tabbed live page, PIN entropy, slider hints

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 3: ember_web page types and parser

**Files:**
- Modify: `apps/ember_web/src/api/CapabilityPagesClient.ts`
- Modify: `apps/ember_web/src/utils/guiPage.ts`
- Test: `apps/ember_web/src/utils/guiPage.test.ts`

**Interfaces:**
- Produces (types): `GuiResultSpec.strength?: string`, `GuiResultSpec.group?: number`; `GuiFormSectionSpec.live?: boolean`; `GuiTabsSectionSpec { type: "tabs"; id: string; tabs: GuiFormSectionSpec[] }`; `GuiPageSpec.sections: (GuiFormSectionSpec | GuiTextSectionSpec | GuiTabsSectionSpec)[]`.
- Produces (function): `formSections(sections: GuiPageSpec["sections"]): GuiFormSectionSpec[]`.

- [ ] **Step 1: Write the failing tests**

In `apps/ember_web/src/utils/guiPage.test.ts` change the import to

```ts
import { applyFieldOverrides, formSections, GuiPageError, parseGuiPage, resultValue } from "./guiPage";
```

and add inside `describe("parseGuiPage", ...)`:

```ts
  const TABS = {
    id: "gen",
    tabs: [
      { id: "a", title: "A", tool: "tool_a", live: true, result: { kind: "secret", field: "v", strength: "bits", group: 3 } },
      { id: "b", title: "B", tool: "tool_a" },
    ],
  };
  const tabsPage = (section: unknown) => ({ version: 1, title: "T", sections: [section] });

  it("accepts a tabs section and tags it", () => {
    const page = parseGuiPage(tabsPage(TABS), ["tool_a"]);
    const section = page.sections[0]!;
    expect(section).toMatchObject({ type: "tabs", id: "gen" });
    if (section.type !== "tabs") throw new Error("not tabs");
    expect(section.tabs[0]).toMatchObject({ type: "form", live: true, result: { strength: "bits", group: 3 } });
    expect(section.tabs[1]).toMatchObject({ live: false });
  });

  it("accepts null strength and group, as an unstripped page would carry them", () => {
    const page = parseGuiPage(
      tabsPage({ ...TABS, tabs: [{ id: "a", title: "A", tool: "tool_a", live: false, result: { kind: "secret", field: "v", strength: null, group: null } }, TABS.tabs[1]] }),
      ["tool_a"],
    );
    expect(page.sections[0]).toMatchObject({ type: "tabs" });
  });

  it("formSections lists the forms inside tabs too, in order", () => {
    const page = parseGuiPage(
      { version: 1, title: "T", sections: [{ id: "top", title: "Top", tool: "tool_a" }, TABS, { id: "n", text: "x" }] },
      ["tool_a"],
    );
    expect(formSections(page.sections).map((f) => f.id)).toEqual(["top", "a", "b"]);
  });

  it.each([
    ["one tab", tabsPage({ ...TABS, tabs: TABS.tabs.slice(0, 1) })],
    ["nine tabs", tabsPage({ ...TABS, tabs: Array.from({ length: 9 }, (_, i) => ({ id: `t${i}`, title: "T", tool: "tool_a" })) })],
    ["tabs not a list", tabsPage({ ...TABS, tabs: "x" })],
    ["a text section as a tab", tabsPage({ ...TABS, tabs: [TABS.tabs[0], { id: "x", text: "not a form" }] })],
    ["a tab id repeated", tabsPage({ ...TABS, tabs: [TABS.tabs[0], { id: "a", title: "Again", tool: "tool_a" }] })],
    ["a tab id equal to a section id", { version: 1, title: "T", sections: [{ id: "a", title: "Top", tool: "tool_a" }, TABS] }],
    ["a foreign tool in a tab", tabsPage({ ...TABS, tabs: [TABS.tabs[0], { id: "b", title: "B", tool: "elsewhere" }] })],
    ["strength on a message", tabsPage({ ...TABS, tabs: [{ id: "a", title: "A", tool: "tool_a", result: { kind: "message", strength: "bits" } }, TABS.tabs[1]] })],
    ["group on a table", tabsPage({ ...TABS, tabs: [{ id: "a", title: "A", tool: "tool_a", result: { kind: "table", field: "rows", group: 3 } }, TABS.tabs[1]] })],
    ...[1, 9, 2.5, "3"].map((group): [string, unknown] => [
      `group ${JSON.stringify(group)}`,
      tabsPage({ ...TABS, tabs: [{ id: "a", title: "A", tool: "tool_a", result: { kind: "secret", field: "v", group } }, TABS.tabs[1]] }),
    ]),
    ["strength not an identifier", tabsPage({ ...TABS, tabs: [{ id: "a", title: "A", tool: "tool_a", result: { kind: "secret", field: "v", strength: "a-b" } }, TABS.tabs[1]] })],
  ])("rejects %s", (_name, raw) => {
    expect(() => parseGuiPage(raw, ["tool_a"])).toThrow(GuiPageError);
  });
```

- [ ] **Step 2: Run to verify failure**

Run: `cd apps/ember_web && npx vitest run src/utils/guiPage.test.ts`
Expected: FAIL (`formSections is not a function`, tabs rejected as invalid forms).

- [ ] **Step 3: Implement types**

In `CapabilityPagesClient.ts`: in `GuiResultSpec` add

```ts
  /** A numeric result field: bits of entropy, drawn as a strength bar (secret only). */
  strength?: string;
  /** Show a secret in groups of this many characters, 2 to 8 (secret only). */
  group?: number;
```

in `GuiFormSectionSpec` add `/** Runs when it opens and when a control changes. */ live?: boolean;`, add

```ts
export interface GuiTabsSectionSpec {
  type: "tabs";
  id: string;
  /** Two to eight forms, one shown at a time; a form's title is its tab label. */
  tabs: GuiFormSectionSpec[];
}
```

and change `GuiPageSpec.sections` to `(GuiFormSectionSpec | GuiTextSectionSpec | GuiTabsSectionSpec)[]`.

- [ ] **Step 4: Implement the parser**

In `guiPage.ts`:

1. Import `GuiTabsSectionSpec` in the type import list.
2. After `const SECTION_ID = ...` add `const MIN_TABS = 2;` and `const MAX_TABS = 8;`.
3. In `parseResult`: change the `warnUnknown` list to `["kind", "field", "detail", "refresh_after", "strength", "group"]`; after computing `kind` validation replace the `const result` block and the secret/table check with:

```ts
  const group = raw.group;
  if (group != null && (typeof group !== "number" || !Number.isInteger(group) || group < 2 || group > 8)) {
    throw new GuiPageError(`${where}: 'group' must be a whole number from 2 to 8`);
  }
  const result: GuiResultSpec = {
    kind,
    field: name(raw, "field", where),
    detail: name(raw, "detail", where),
    refresh_after: name(raw, "refresh_after", where),
    strength: name(raw, "strength", where),
    group: typeof group === "number" ? group : undefined,
  };
  if ((kind === "secret" || kind === "table") && !result.field) {
    throw new GuiPageError(`${where}: result kind '${kind}' needs a 'field'`);
  }
  if (kind !== "secret" && (result.strength !== undefined || result.group !== undefined)) {
    throw new GuiPageError(`${where}: 'strength' and 'group' only apply to a result of kind 'secret'`);
  }
  return result;
```

4. Replace `parseSection` with these three functions:

```ts
function parseSectionId(raw: Obj, where: string): string {
  const id = text(raw, "id", where)!;
  if (!SECTION_ID.test(id)) throw new GuiPageError(`${where}: bad id '${id}'`);
  return id;
}

function parseForm(raw: unknown, where: string): GuiFormSectionSpec {
  if (!isObj(raw)) throw new GuiPageError(`${where} must be an object`);
  const id = parseSectionId(raw, where);
  warnUnknown(where, raw, ["id", "title", "tool", "submit", "fields", "result", "live"]);
  return {
    type: "form",
    id,
    title: text(raw, "title", where)!,
    tool: text(raw, "tool", where)!,
    submit: text(raw, "submit", where, false) ?? "Run",
    fields: parseFields(raw.fields, where),
    result: parseResult(raw.result, where),
    live: raw.live === true,
  };
}

function parseTabs(raw: Obj, where: string): GuiTabsSectionSpec {
  const id = parseSectionId(raw, where);
  warnUnknown(where, raw, ["id", "tabs"]);
  const tabs = raw.tabs;
  if (!Array.isArray(tabs) || tabs.length < MIN_TABS || tabs.length > MAX_TABS) {
    throw new GuiPageError(`${where}: 'tabs' must be a list of ${MIN_TABS} to ${MAX_TABS} forms`);
  }
  return { type: "tabs", id, tabs: tabs.map((tab, i) => parseForm(tab, `${where} tab ${i + 1}`)) };
}

function parseSection(raw: unknown, index: number): GuiFormSectionSpec | GuiTextSectionSpec | GuiTabsSectionSpec {
  const where = `section ${index + 1}`;
  if (!isObj(raw)) throw new GuiPageError(`${where} must be an object`);
  if ("tabs" in raw) return parseTabs(raw, where);
  // Any section with a `text` key is prose (as mcp_server reads it), even if it also names a tool.
  if ("text" in raw) {
    const id = parseSectionId(raw, where);
    warnUnknown(where, raw, ["id", "title", "text"]);
    return { type: "text", id, title: text(raw, "title", where, false), text: text(raw, "text", where)! };
  }
  return parseForm(raw, where);
}

/** Every form of the page, those inside tabs included, in page order. */
export function formSections(sections: GuiPageSpec["sections"]): GuiFormSectionSpec[] {
  return sections.flatMap((s) => (s.type === "form" ? [s] : s.type === "tabs" ? s.tabs : []));
}
```

5. In `parseGuiPage` replace the `ids`/`dup`/`foreign` lines with:

```ts
  const ids = sections.flatMap((s) => (s.type === "tabs" ? [s.id, ...s.tabs.map((t) => t.id)] : [s.id]));
  const dup = ids.find((id, i) => ids.indexOf(id) !== i);
  if (dup) throw new GuiPageError(`Duplicate section id '${dup}'`);
  const foreign = formSections(sections).flatMap((f) => (ownTools.includes(f.tool) ? [] : [f.tool]));
  if (foreign.length) throw new GuiPageError(`The page names tools its capability does not own: ${foreign.join(", ")}`);
```

(keep the closing `return { version: 1, ... }` as it is).

- [ ] **Step 5: Run the tests and the type check**

Run: `cd apps/ember_web && npx vitest run src/utils/guiPage.test.ts && npx vue-tsc --noEmit`
Expected: tests PASS. `vue-tsc` will report an error in `apps/ember_web/src/views/CapabilityPageView.vue`: after the `text` branch, `s` can now also be a tabs section, but `GuiFormSection :section="s"` expects a form. Make the minimal edit now (Task 8 replaces these two lines): change `v-else-if="tools[s.tool]"` on the `GuiFormSection` line to `v-else-if="s.type === 'form' && tools[s.tool]"`, and change the following `<p v-else class="error">` to `<p v-else-if="s.type === 'form'" class="error">`. Re-run `npx vue-tsc --noEmit`; expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add apps/ember_web/src/api/CapabilityPagesClient.ts apps/ember_web/src/utils/guiPage.ts apps/ember_web/src/utils/guiPage.test.ts apps/ember_web/src/views/CapabilityPageView.vue
git commit -m "feat(ember_web): parse tabs, live, strength and group in GUI pages

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Secret display helpers and the success colour

**Files:**
- Create: `apps/ember_web/src/utils/secretDisplay.ts`
- Create: `apps/ember_web/src/utils/secretDisplay.test.ts`
- Modify: `apps/ember_web/src/style.css` (add `--success`)

**Interfaces:**
- Produces:
  - `type StrengthLevel = "weak" | "fair" | "strong" | "excellent"`
  - `strengthOf(bits: number): { level: StrengthLevel; label: string; fraction: number }` (fraction 0 to 1, full at 128 bits)
  - `groupText(text: string, size: number): string` (a space every `size` characters)
  - `type Segment = { text: string; kind: "plain" | "digit" | "symbol" }`
  - `segmentsOf(text: string): Segment[]` (colour classes only for mixed values: text with at least one letter; a value with no letters, like a PIN, is one plain segment)

- [ ] **Step 1: Write the failing tests**

`apps/ember_web/src/utils/secretDisplay.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { groupText, segmentsOf, strengthOf } from "./secretDisplay";

describe("strengthOf", () => {
  it.each([
    [0, "weak", "Weak"],
    [44.9, "weak", "Weak"],
    [45, "fair", "Fair"],
    [69.9, "fair", "Fair"],
    [70, "strong", "Strong"],
    [99.9, "strong", "Strong"],
    [100, "excellent", "Excellent"],
    [300, "excellent", "Excellent"],
  ])("%s bits is %s", (bits, level, label) => {
    expect(strengthOf(bits)).toMatchObject({ level, label });
  });

  it("fills the bar up to 128 bits and never beyond", () => {
    expect(strengthOf(64).fraction).toBe(0.5);
    expect(strengthOf(128).fraction).toBe(1);
    expect(strengthOf(500).fraction).toBe(1);
    expect(strengthOf(-5).fraction).toBe(0);
  });
});

describe("groupText", () => {
  it("puts a space every N characters", () => {
    expect(groupText("123456", 3)).toBe("123 456");
    expect(groupText("12345678", 4)).toBe("1234 5678");
    expect(groupText("1234567", 3)).toBe("123 456 7");
  });

  it("leaves short text and nonsense sizes alone", () => {
    expect(groupText("12", 3)).toBe("12");
    expect(groupText("", 3)).toBe("");
    expect(groupText("123456", 0)).toBe("123456");
  });
});

describe("segmentsOf", () => {
  it("is one plain segment for a value with no letters (a PIN or a code)", () => {
    expect(segmentsOf("123 456")).toEqual([{ text: "123 456", kind: "plain" }]);
  });

  it("tags digits and symbols in a mixed value and merges runs", () => {
    expect(segmentsOf("ab12!!cd")).toEqual([
      { text: "ab", kind: "plain" },
      { text: "12", kind: "digit" },
      { text: "!!", kind: "symbol" },
      { text: "cd", kind: "plain" },
    ]);
  });

  it("is empty for empty text", () => {
    expect(segmentsOf("")).toEqual([]);
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `cd apps/ember_web && npx vitest run src/utils/secretDisplay.test.ts`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement**

`apps/ember_web/src/utils/secretDisplay.ts`:

```ts
// Pure helpers for drawing a generated secret: how strong it is, how it is
// spaced for reading, and which characters get a colour.

export type StrengthLevel = "weak" | "fair" | "strong" | "excellent";

/** The strength bar is full at this many bits of entropy. */
export const STRENGTH_FULL_BITS = 128;

const LABELS: Record<StrengthLevel, string> = { weak: "Weak", fair: "Fair", strong: "Strong", excellent: "Excellent" };

export function strengthOf(bits: number): { level: StrengthLevel; label: string; fraction: number } {
  const level: StrengthLevel = bits < 45 ? "weak" : bits < 70 ? "fair" : bits < 100 ? "strong" : "excellent";
  return { level, label: LABELS[level], fraction: Math.max(0, Math.min(bits / STRENGTH_FULL_BITS, 1)) };
}

/** `text` with a space every `size` characters ("123456" -> "123 456"). */
export function groupText(text: string, size: number): string {
  if (size < 1 || text.length <= size) return text;
  const groups: string[] = [];
  for (let i = 0; i < text.length; i += size) groups.push(text.slice(i, i + size));
  return groups.join(" ");
}

export interface Segment {
  text: string;
  kind: "plain" | "digit" | "symbol";
}

/** Runs of the same kind of character. Only a value with letters in it (a
 * password, a passphrase) is coloured; digits-only values (a PIN, a TOTP
 * code) stay plain, since colouring every character says nothing. */
export function segmentsOf(text: string): Segment[] {
  if (text === "") return [];
  if (!/[A-Za-z]/.test(text)) return [{ text, kind: "plain" }];
  const segments: Segment[] = [];
  for (const ch of text) {
    const kind: Segment["kind"] = /[0-9]/.test(ch) ? "digit" : /[A-Za-z\s]/.test(ch) ? "plain" : "symbol";
    const last = segments[segments.length - 1];
    if (last && last.kind === kind) last.text += ch;
    else segments.push({ text: ch, kind });
  }
  return segments;
}
```

In `apps/ember_web/src/style.css`, after the `--danger` line add:

```css
  --success: light-dark(#1baf7a, #199e70);
```

- [ ] **Step 4: Run the tests**

Run: `cd apps/ember_web && npx vitest run src/utils/secretDisplay.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/ember_web/src/utils/secretDisplay.ts apps/ember_web/src/utils/secretDisplay.test.ts apps/ember_web/src/style.css
git commit -m "feat(ember_web): helpers for strength, grouping and colouring a secret

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Upgraded secret result card

**Files:**
- Modify: `apps/ember_web/src/components/GuiResult.vue`
- Test: `apps/ember_web/src/components/GuiResult.test.ts`

**Interfaces:**
- Consumes: `strengthOf`, `groupText`, `segmentsOf` (Task 4); `GuiResultSpec.strength/group` (Task 3).
- Produces: `GuiResult` props gain `canRegenerate?: boolean`; it emits `again` (no payload) when its Generate again button is clicked. Test hooks: `[data-test=secret]` (the value), `[data-test=toggle]`, `[data-test=copy]`, `[data-test=again]`, `[data-test=strength]` (label text) and `[data-test=bits]`.

- [ ] **Step 1: Write the failing tests**

Add to `GuiResult.test.ts` inside the `describe("GuiResult", ...)` block:

```ts
  it("secret: shows a strength bar and label from the named bits field", () => {
    const w = mount(GuiResult, { props: { spec: { kind: "secret", field: "password", strength: "entropy_bits" }, result: result({ password: "x", entropy_bits: 131.2 }) } });
    expect(w.get("[data-test=strength]").text()).toBe("Excellent");
    expect(w.get("[data-test=bits]").text()).toContain("131");
    expect(w.get(".fill").classes()).toContain("excellent");
    expect((w.get(".fill").element as HTMLElement).style.width).toBe("100%");
  });

  it("secret: no strength bar without the option, or when the field is missing", () => {
    const plain = mount(GuiResult, { props: { spec: { kind: "secret", field: "password" }, result: result({ password: "x", entropy_bits: 50 }) } });
    expect(plain.find("[data-test=strength]").exists()).toBe(false);
    const missing = mount(GuiResult, { props: { spec: { kind: "secret", field: "password", strength: "entropy_bits" }, result: result({ password: "x" }) } });
    expect(missing.find("[data-test=strength]").exists()).toBe(false);
  });

  it("secret: groups the display but copies the whole value", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    const w = mount(GuiResult, { props: { spec: { kind: "secret", field: "code", group: 3 }, result: result({ code: "123456" }) } });
    expect(w.get("[data-test=secret]").text()).toBe("123 456");
    await w.get("[data-test=copy]").trigger("click");
    expect(writeText).toHaveBeenCalledWith("123456");
  });

  it("secret: colours digits and symbols of a mixed value only", () => {
    const mixed = mount(GuiResult, { props: { spec: { kind: "secret", field: "p" }, result: result({ p: "ab12!" }) } });
    expect(mixed.findAll(".digit").map((e) => e.text())).toEqual(["12"]);
    expect(mixed.findAll(".symbol").map((e) => e.text())).toEqual(["!"]);
    const pin = mount(GuiResult, { props: { spec: { kind: "secret", field: "p" }, result: result({ p: "123456" }) } });
    expect(pin.find(".digit").exists()).toBe(false);
  });

  it("secret: hides as dots, not as the value", async () => {
    const w = mount(GuiResult, { props: { spec: { kind: "secret", field: "p", group: 3 }, result: result({ p: "123456" }) } });
    await w.get("[data-test=toggle]").trigger("click");
    expect(w.get("[data-test=secret]").text()).toBe("••••••");
  });

  it("secret: Generate again appears only when asked for, and says so", async () => {
    const without = mount(GuiResult, { props: { spec: { kind: "secret", field: "p" }, result: result({ p: "x" }) } });
    expect(without.find("[data-test=again]").exists()).toBe(false);
    const w = mount(GuiResult, { props: { spec: { kind: "secret", field: "p" }, result: result({ p: "x" }), canRegenerate: true } });
    await w.get("[data-test=again]").trigger("click");
    expect(w.emitted("again")).toHaveLength(1);
  });
```

- [ ] **Step 2: Run to verify failure**

Run: `cd apps/ember_web && npx vitest run src/components/GuiResult.test.ts`
Expected: the six new tests FAIL; the existing ones still pass.

- [ ] **Step 3: Implement**

In `GuiResult.vue` script:

```ts
import { groupText, segmentsOf, strengthOf } from "../utils/secretDisplay";

const props = defineProps<{ spec: GuiResultSpec; result: ToolRunResult; canRegenerate?: boolean }>();
const emit = defineEmits<{ again: [] }>();
```

(replace the existing `defineProps` line; keep the other imports) and after the `secretText` computed add:

```ts
// What the person reads: spaced when the page asks for groups. Copy uses secretText.
const shown = computed(() => (props.spec.group ? groupText(secretText.value, props.spec.group) : secretText.value));
const segments = computed(() => segmentsOf(shown.value));
const hiddenText = computed(() => "•".repeat(Math.min(secretText.value.length, 32)));
const strength = computed(() => {
  const bits = props.spec.strength ? resultValue(props.result, props.spec.strength) : undefined;
  return typeof bits === "number" ? { bits, ...strengthOf(bits) } : null;
});
```

Replace the `<template v-else-if="spec.kind === 'secret'">` block with:

```vue
    <template v-else-if="spec.kind === 'secret'">
      <p v-if="secretText === ''" class="muted">The tool returned no value for '{{ spec.field }}'.</p>
      <div v-else class="secret-card">
        <div class="secret-row">
          <code data-test="secret" class="secret"><template v-if="revealed"><span v-for="(s, i) in segments" :key="i" :class="s.kind">{{ s.text }}</span></template><template v-else>{{ hiddenText }}</template></code>
          <button type="button" class="icon" data-test="toggle" :aria-label="revealed ? 'Hide' : 'Show'" :title="revealed ? 'Hide' : 'Show'" @click="revealed = !revealed">
            <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
              <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round" />
              <circle cx="12" cy="12" r="3" fill="none" stroke="currentColor" stroke-width="1.8" />
              <path v-if="!revealed" d="M4 4l16 16" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" />
            </svg>
          </button>
          <button v-if="canRegenerate" type="button" class="icon" data-test="again" aria-label="Generate again" title="Generate again" @click="emit('again')">
            <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
              <path d="M20 12a8 8 0 1 1-2.6-5.9M20 4v5h-5" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" />
            </svg>
          </button>
          <button type="button" class="copy" data-test="copy" @click="copy">{{ copied ? "Copied" : "Copy" }}</button>
        </div>
        <div v-if="strength" class="strength">
          <div class="bar" aria-hidden="true"><div :class="['fill', strength.level]" :style="{ width: `${strength.fraction * 100}%` }" /></div>
          <div class="strength-meta">
            <span data-test="strength">{{ strength.label }}</span>
            <span data-test="bits">{{ Math.round(strength.bits) }} bits of entropy</span>
          </div>
        </div>
      </div>
      <p v-if="detail" class="muted">{{ detail }}</p>
    </template>
```

Replace the `.secret-row` and `.secret` style lines with:

```css
.secret-card { display: flex; flex-direction: column; gap: 12px; padding: 14px 16px; border: 1px solid var(--border); border-radius: 12px; background: var(--bg); }
.secret-row { display: flex; gap: 8px; align-items: center; }
.secret { flex: 1; min-width: 0; font-family: var(--mono); font-size: 1.25em; line-height: 1.5; word-break: break-all; }
.digit { color: var(--accent); }
.symbol { color: var(--success); }
.icon, .copy { display: inline-flex; align-items: center; justify-content: center; height: 34px; border: 1px solid var(--border); border-radius: 8px; background: var(--surface); color: var(--text); cursor: pointer; }
.icon { width: 34px; padding: 0; }
.copy { padding: 0 14px; font-weight: 600; }
.bar { height: 6px; border-radius: 3px; background: var(--surface); overflow: hidden; }
.fill { height: 100%; border-radius: 3px; transition: width 0.25s, background-color 0.25s; }
.fill.weak { background: var(--danger); }
.fill.fair { background: var(--warning); }
.fill.strong, .fill.excellent { background: var(--success); }
.strength-meta { display: flex; justify-content: space-between; margin-top: 6px; font-size: 0.8em; color: var(--muted); }
@media (prefers-reduced-motion: reduce) { .fill { transition: none; } }
```

(keep the other style rules; delete the old `.secret` line.)

- [ ] **Step 4: Run the tests**

Run: `cd apps/ember_web && npx vitest run src/components/GuiResult.test.ts && npx vue-tsc --noEmit`
Expected: all pass (old tests included: they read `[data-test=secret]` text and click `toggle` and `copy`).

- [ ] **Step 5: Commit**

```bash
git add apps/ember_web/src/components/GuiResult.vue apps/ember_web/src/components/GuiResult.test.ts
git commit -m "feat(ember_web): strength bar, grouping and Generate again on a secret result

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Live mode for ToolRunForm

**Files:**
- Modify: `apps/ember_web/src/components/ToolRunForm.vue`
- Create: `apps/ember_web/src/components/ToolRunForm.test.ts`

**Interfaces:**
- Produces: `ToolRunForm` prop `live?: boolean`. When true: emits `run` once on mount with the built args (if valid), and again on every native `change` event inside the form (slider release, checkbox/select change, text on blur or Enter) when the values are valid. It hides the Run button. Range fields show their value; checkbox fields draw as chips. When false (default) nothing changes.

- [ ] **Step 1: Write the failing tests**

`apps/ember_web/src/components/ToolRunForm.test.ts`:

```ts
import { mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";
import type { JsonSchema } from "../api/types";
import ToolRunForm from "./ToolRunForm.vue";

vi.mock("../api/CommandsClient", () => ({ commandsClient: { options: vi.fn(), upload: vi.fn() } }));

const SCHEMA: JsonSchema = {
  type: "object",
  properties: {
    length: { type: "integer", minimum: 8, maximum: 128, default: 20, input: "range" },
    use_upper: { type: "boolean", default: true },
  },
};

const mountForm = (props: Record<string, unknown> = {}) =>
  mount(ToolRunForm, { props: { schema: SCHEMA, running: false, ...props } });

describe("ToolRunForm live mode", () => {
  it("runs once on mount with the defaults", () => {
    const w = mountForm({ live: true });
    expect(w.emitted("run")).toEqual([[{ length: 20, use_upper: true }]]);
  });

  it("does not run on mount when not live", () => {
    expect(mountForm().emitted("run")).toBeUndefined();
  });

  it("runs when a control is committed, not while a slider is still moving", async () => {
    const w = mountForm({ live: true });
    const slider = w.get("input[type=range]");
    await slider.setValue("64"); // setValue fires `input`
    expect(w.emitted("run")).toHaveLength(1);
    await slider.trigger("change"); // the release
    expect(w.emitted("run")).toHaveLength(2);
    expect(w.emitted("run")![1]).toEqual([{ length: 64, use_upper: true }]);
  });

  it("runs when a toggle chip changes", async () => {
    const w = mountForm({ live: true });
    await w.get("input[type=checkbox]").setValue(false);
    await w.get("input[type=checkbox]").trigger("change");
    expect(w.emitted("run")!.at(-1)).toEqual([{ length: 20, use_upper: false }]);
  });

  it("does not run for values that do not validate", async () => {
    const schema: JsonSchema = { type: "object", properties: { secret: { type: "string" } }, required: ["secret"] };
    const w = mountForm({ live: true, schema });
    expect(w.emitted("run")).toBeUndefined();
    await w.get("input").setValue("abc");
    await w.get("input").trigger("change");
    expect(w.emitted("run")).toEqual([[{ secret: "abc" }]]);
  });

  it("hides the Run button and shows the slider's value", () => {
    const live = mountForm({ live: true });
    expect(live.find("button.run").exists()).toBe(false);
    expect(live.get("output").text()).toBe("20");
    expect(mountForm().find("button.run").exists()).toBe(true);
    expect(mountForm().find("output").exists()).toBe(false);
  });

  it("a normal form ignores change events", async () => {
    const w = mountForm();
    await w.get("input[type=range]").trigger("change");
    expect(w.emitted("run")).toBeUndefined();
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `cd apps/ember_web && npx vitest run src/components/ToolRunForm.test.ts`
Expected: FAIL (no run on mount, `output` missing, Run button still there).

- [ ] **Step 3: Implement**

In `ToolRunForm.vue` script:

- change the props line to
  `const props = withDefaults(defineProps<{ schema: JsonSchema; running: boolean; submitLabel?: string; live?: boolean }>(), { submitLabel: "Run", live: false });`
- after `function submit() {...}` add:

```ts
/** Live mode: a committed change (the native `change` event: slider release,
 * toggle, select, text on blur) runs the tool again. */
function onFormChange(): void {
  if (props.live) submit();
}
// Live mode also runs once as it opens, with the defaults.
onMounted(() => {
  if (props.live) submit();
});
```

Template: change the `<form>` opening tag to

```vue
  <form :class="['tool-form', { live }]" @submit.prevent="submit" @change="onFormChange">
```

Change the final `<input v-else ...>` (the generic input) so the range gets a readout: wrap it:

```vue
        <div v-else-if="f.widget === 'range'" class="range-row">
          <input
            :id="`field-${f.name}`"
            v-model="values[f.name] as string"
            type="range"
            :step="f.step ?? 1"
            :min="f.min"
            :max="f.max"
          />
          <output class="readout" :for="`field-${f.name}`">{{ values[f.name] }}</output>
        </div>
```

placed immediately **before** the existing `<input v-else ...>` (so the chain is `textarea v-else-if ... → range v-else-if → input v-else`; the `<textarea v-else-if="f.widget === 'json' || ...">` comes first in the chain, insert the new `div` right after it).

Wrap the Run button: `<button v-if="!live" type="submit" class="run" ...>` (add `v-if="!live"` to the existing tag).

Style additions:

```css
.range-row {
  display: flex;
  align-items: center;
  gap: 10px;
}
.range-row input[type="range"] {
  flex: 1;
  accent-color: var(--accent);
}
.readout {
  min-width: 2.5em;
  text-align: right;
  font-weight: 600;
}
/* Live forms: toggles are chips in a row, other controls take the full width. */
.live {
  flex-direction: row;
  flex-wrap: wrap;
  align-items: center;
}
.live .field {
  flex: 1 1 100%;
}
.live .field:has(> .check) {
  flex: 0 0 auto;
}
.live .check {
  position: relative;
  padding: 5px 12px;
  border: 1px solid var(--border);
  border-radius: 999px;
  cursor: pointer;
  font-size: 0.9em;
}
.live .check input {
  position: absolute;
  opacity: 0;
  pointer-events: none;
}
.live .check:has(input:checked) {
  border-color: var(--accent);
  background: var(--accent);
  color: var(--accent-contrast);
}
.live .check:has(input:focus-visible) {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}
```

- [ ] **Step 4: Run the tests**

Run: `cd apps/ember_web && npx vitest run src/components/ToolRunForm.test.ts && npx vue-tsc --noEmit`
Expected: PASS. Also run `npx vitest run src/components` to confirm nothing that mounts `ToolRunForm` (command form, tool run modal) broke.

- [ ] **Step 5: Commit**

```bash
git add apps/ember_web/src/components/ToolRunForm.vue apps/ember_web/src/components/ToolRunForm.test.ts
git commit -m "feat(ember_web): live mode for ToolRunForm with sliders and toggle chips

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Live runs, embedded layout and ring in GuiFormSection

**Files:**
- Create: `apps/ember_web/src/components/CountdownRing.vue`
- Modify: `apps/ember_web/src/components/GuiFormSection.vue`
- Test: `apps/ember_web/src/components/GuiFormSection.test.ts`

**Interfaces:**
- Consumes: `ToolRunForm` live mode (Task 6), `GuiResult` `canRegenerate` and `again` (Task 5), `GuiFormSectionSpec.live` (Task 3).
- Produces: `GuiFormSection` prop `embedded?: boolean` (no own title/description; result and refresh ring above the controls). `CountdownRing` props `{ remaining: number; total: number }`.

- [ ] **Step 1: Write the failing tests**

Add to `GuiFormSection.test.ts` (extend the imports with `defineComponent, h, KeepAlive, nextTick` from `"vue"`):

```ts
const LIVE_TOOL: ToolInfo = {
  name: "tool_a",
  title: "A",
  description: "",
  inputSchema: { type: "object", properties: { length: { type: "integer", minimum: 8, maximum: 128, default: 20, input: "range" } } },
};
const LIVE: GuiFormSectionSpec = { ...SECTION, live: true };

describe("GuiFormSection live", () => {
  beforeEach(() => vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval"] }));
  afterEach(() => vi.useRealTimers());

  it("runs as soon as it opens, with no Run button", async () => {
    const runTool = vi.fn().mockResolvedValue(ok({ code: "abc" }));
    const w = mount(GuiFormSection, { props: { section: LIVE, tool: LIVE_TOOL, runTool } });
    await flushPromises();
    expect(runTool).toHaveBeenCalledTimes(1);
    expect(runTool).toHaveBeenCalledWith("tool_a", { length: 20 });
    expect(w.find("button.run").exists()).toBe(false);
    expect(w.get("[data-test=secret]").text()).toBe("abc");
  });

  it("waits 300 ms after a change and runs once for a burst of changes", async () => {
    const runTool = vi.fn().mockResolvedValue(ok({ code: "abc" }));
    const w = mount(GuiFormSection, { props: { section: LIVE, tool: LIVE_TOOL, runTool } });
    await flushPromises();
    const slider = w.get("input[type=range]");
    for (const value of ["30", "40", "50"]) {
      await slider.setValue(value);
      await slider.trigger("change");
    }
    vi.advanceTimersByTime(299);
    expect(runTool).toHaveBeenCalledTimes(1);
    vi.advanceTimersByTime(1);
    await flushPromises();
    expect(runTool).toHaveBeenCalledTimes(2);
    expect(runTool).toHaveBeenLastCalledWith("tool_a", { length: 50 });
  });

  it("Generate again runs with the same arguments", async () => {
    const runTool = vi.fn().mockResolvedValue(ok({ code: "abc" }));
    const w = mount(GuiFormSection, { props: { section: LIVE, tool: LIVE_TOOL, runTool } });
    await flushPromises();
    await w.get("[data-test=again]").trigger("click");
    await flushPromises();
    expect(runTool).toHaveBeenCalledTimes(2);
    expect(runTool).toHaveBeenLastCalledWith("tool_a", { length: 20 });
  });

  it("a form that is not live has no Generate again button", async () => {
    const runTool = vi.fn().mockResolvedValue(ok({ code: "abc" }));
    const w = mount(GuiFormSection, { props: { section: SECTION, tool: TOOL, runTool } });
    await w.get("form").trigger("submit");
    await flushPromises();
    expect(w.find("[data-test=again]").exists()).toBe(false);
  });

  it("drops the title and description when embedded, and shows the result before the form", async () => {
    const runTool = vi.fn().mockResolvedValue(ok({ code: "abc" }));
    const w = mount(GuiFormSection, { props: { section: LIVE, tool: { ...LIVE_TOOL, description: "Makes a thing." }, runTool, embedded: true } });
    await flushPromises();
    expect(w.find("h3").exists()).toBe(false);
    expect(w.text()).not.toContain("Makes a thing.");
    expect(w.classes()).toContain("embedded");
  });
});

describe("GuiFormSection inside KeepAlive", () => {
  beforeEach(() => vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval"] }));
  afterEach(() => vi.useRealTimers());

  const REFRESHING = { ...SECTION, result: { kind: "secret", field: "code", refresh_after: "seconds_remaining" } } as GuiFormSectionSpec;

  function host(runTool: ReturnType<typeof vi.fn>) {
    return mount(
      defineComponent({
        props: { on: { type: Boolean, default: true } },
        setup: (props) => () =>
          h(KeepAlive, null, { default: () => (props.on ? h(GuiFormSection, { section: REFRESHING, tool: TOOL, runTool }) : null) }),
      }),
    );
  }

  it("stops refreshing while hidden and refreshes again when shown", async () => {
    const runTool = vi.fn().mockResolvedValue(ok({ code: "1", seconds_remaining: 5 }));
    const w = host(runTool);
    await w.get("form").trigger("submit");
    await flushPromises();
    expect(runTool).toHaveBeenCalledTimes(1);

    await w.setProps({ on: false });
    vi.advanceTimersByTime(20_000);
    await flushPromises();
    expect(runTool).toHaveBeenCalledTimes(1);

    await w.setProps({ on: true });
    await flushPromises();
    expect(runTool).toHaveBeenCalledTimes(2);
  });
});
```

Add `CountdownRing` coverage inside `GuiFormSection.test.ts` is not needed; it is tested through the ring's existence in the refresh test below. Also add this test to the first `describe`:

```ts
  it("shows a ring beside the countdown text", async () => {
    const section = { ...SECTION, result: { kind: "secret", field: "code", refresh_after: "seconds_remaining" } } as GuiFormSectionSpec;
    const runTool = vi.fn().mockResolvedValue(ok({ code: "1", seconds_remaining: 30 }));
    const w = mount(GuiFormSection, { props: { section, tool: TOOL, runTool } });
    await w.get("form").trigger("submit");
    await flushPromises();
    expect(w.find("svg.ring").exists()).toBe(true);
    expect(w.text()).toContain("New code in 30 s");
  });
```

- [ ] **Step 2: Run to verify failure**

Run: `cd apps/ember_web && npx vitest run src/components/GuiFormSection.test.ts`
Expected: the new tests FAIL (no live behaviour, no ring, no `embedded`).

- [ ] **Step 3: Implement `CountdownRing.vue`**

`apps/ember_web/src/components/CountdownRing.vue`:

```vue
<script setup lang="ts">
import { computed } from "vue";

/** A small ring that empties as `remaining` seconds run down from `total`. */
const props = defineProps<{ remaining: number; total: number }>();

const RADIUS = 15;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;
const offset = computed(() => CIRCUMFERENCE * (1 - (props.total > 0 ? Math.max(0, Math.min(props.remaining / props.total, 1)) : 0)));
</script>

<template>
  <svg class="ring" viewBox="0 0 36 36" width="28" height="28" aria-hidden="true">
    <circle cx="18" cy="18" :r="RADIUS" fill="none" stroke="var(--surface)" stroke-width="4" />
    <circle
      class="arc"
      cx="18"
      cy="18"
      :r="RADIUS"
      fill="none"
      stroke="var(--accent)"
      stroke-width="4"
      stroke-linecap="round"
      :stroke-dasharray="CIRCUMFERENCE"
      :stroke-dashoffset="offset"
      transform="rotate(-90 18 18)"
    />
  </svg>
</template>

<style scoped>
.arc {
  transition: stroke-dashoffset 1s linear;
}
@media (prefers-reduced-motion: reduce) {
  .arc {
    transition: none;
  }
}
</style>
```

- [ ] **Step 4: Implement `GuiFormSection.vue`**

Replace the whole file with:

```vue
<script setup lang="ts">
import { computed, onActivated, onDeactivated, onScopeDispose, ref } from "vue";
import type { GuiFormSectionSpec } from "../api/CapabilityPagesClient";
import type { ToolInfo, ToolRunResult } from "../api/types";
import { useCountdown } from "../composables/useCountdown";
import { errorMessage } from "../utils/errors";
import { applyFieldOverrides, resultValue } from "../utils/guiPage";
import CountdownRing from "./CountdownRing.vue";
import GuiResult from "./GuiResult.vue";
import ToolRunForm from "./ToolRunForm.vue";

/** One form section of a capability page: the tool's form (built from its own
 * schema), the run, and its result. With `refresh_after` the tool is run again
 * with the same arguments when the countdown ends. With `live` it runs as it
 * opens and again (after a short wait) whenever a control changes. `embedded`
 * (inside tabs) drops the card, title and description and shows the result
 * above the controls. State is memory only. */
const props = defineProps<{
  section: GuiFormSectionSpec;
  tool: ToolInfo;
  runTool: (name: string, args: Record<string, unknown>) => Promise<ToolRunResult>;
  embedded?: boolean;
}>();

/** A burst of changes (several toggles, a typed value) becomes one run. */
const LIVE_DEBOUNCE_MS = 300;

const schema = computed(() => applyFieldOverrides(props.tool.inputSchema, props.section.fields));
const live = computed(() => props.section.live === true);
const running = ref(false);
const result = ref<ToolRunResult | null>(null);
const error = ref("");
// Seconds the current countdown started from, for the ring.
const countdownTotal = ref(0);
let lastArgs: Record<string, unknown> = {};
let ran = false;
let runId = 0;
let disposed = false;
let debounce: ReturnType<typeof setTimeout> | null = null;

function clearDebounce(): void {
  if (debounce !== null) clearTimeout(debounce);
  debounce = null;
}
onScopeDispose(() => {
  disposed = true;
  clearDebounce();
});

const countdown = useCountdown(() => void run(lastArgs));

async function run(args: Record<string, unknown>): Promise<void> {
  lastArgs = args;
  ran = true;
  clearDebounce();
  const id = ++runId;
  running.value = true;
  error.value = "";
  countdown.stop();
  try {
    const res = await props.runTool(props.tool.name, args);
    // A disposed section or an older run must not touch state or restart the countdown.
    if (disposed || id !== runId) return;
    result.value = res;
    const after = props.section.result.refresh_after;
    const seconds = after && !res.isError ? resultValue(res, after) : undefined;
    if (typeof seconds === "number" && seconds > 0) {
      countdownTotal.value = seconds;
      countdown.start(seconds);
    }
  } catch (err) {
    if (disposed || id !== runId) return;
    result.value = null;
    error.value = errorMessage(err);
  } finally {
    if (!disposed && id === runId) running.value = false;
  }
}

/** The form's args: run now (a button press), or, when live, the first time
 * at once and later changes after a short wait. */
function onFormRun(args: Record<string, unknown>): void {
  if (!live.value || !ran) {
    void run(args);
    return;
  }
  lastArgs = args;
  clearDebounce();
  debounce = setTimeout(() => void run(args), LIVE_DEBOUNCE_MS);
}

function again(): void {
  void run(lastArgs);
}

// Inside <KeepAlive> (tabs): a hidden form must not keep calling the tool.
onDeactivated(() => {
  countdown.stop();
  clearDebounce();
});
onActivated(() => {
  if (ran && props.section.result.refresh_after) void run(lastArgs);
});
</script>

<template>
  <section :class="['card', { embedded }]">
    <h3 v-if="!embedded">{{ section.title }}</h3>
    <p v-if="tool.description && !embedded" class="muted">{{ tool.description }}</p>
    <ToolRunForm :schema="schema" :running="running" :submit-label="section.submit" :live="live" @run="onFormRun" />
    <p v-if="error" class="error">{{ error }}</p>
    <GuiResult v-if="result" class="result" :spec="section.result" :result="result" :can-regenerate="live" @again="again" />
    <div v-if="countdown.running.value" class="refresh">
      <CountdownRing :remaining="countdown.remaining.value" :total="countdownTotal" />
      <span class="muted">New code in {{ countdown.remaining.value }} s</span>
    </div>
  </section>
</template>

<style scoped>
.card {
  display: flex;
  flex-direction: column;
  margin-bottom: 12px;
  padding: 12px 14px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--surface);
}
.card.embedded {
  margin: 0;
  padding: 0;
  border: none;
  background: none;
  gap: 14px;
}
/* Embedded: the result (and its refresh ring) lead, the controls follow. */
.embedded .result,
.embedded .refresh {
  order: -1;
}
.refresh {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 8px;
}
.muted {
  color: var(--muted);
}
.error {
  color: var(--danger);
}
</style>
```

Note on ordering: with `order: -1` on both `.result` and `.refresh`, the DOM order (result, then refresh) is kept between them, so the ring sits right under the result card.

- [ ] **Step 5: Run the tests**

Run: `cd apps/ember_web && npx vitest run src/components/GuiFormSection.test.ts && npx vue-tsc --noEmit`
Expected: all pass, old and new. If the "stops refreshing while hidden" test shows the second call missing, check that `onActivated` runs on re-show (KeepAlive caches the instance when `on` goes false).

- [ ] **Step 6: Commit**

```bash
git add apps/ember_web/src/components/CountdownRing.vue apps/ember_web/src/components/GuiFormSection.vue apps/ember_web/src/components/GuiFormSection.test.ts
git commit -m "feat(ember_web): live runs, embedded layout and countdown ring for form sections

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Tabs section and the page view

**Files:**
- Create: `apps/ember_web/src/components/GuiTabsSection.vue`
- Create: `apps/ember_web/src/components/GuiTabsSection.test.ts`
- Modify: `apps/ember_web/src/views/CapabilityPageView.vue`
- Test: `apps/ember_web/src/views/CapabilityPageView.test.ts`

**Interfaces:**
- Consumes: `GuiTabsSectionSpec` (Task 3), `GuiFormSection` with `embedded` (Task 7).
- Produces: `GuiTabsSection` props `{ section: GuiTabsSectionSpec; tools: Record<string, ToolInfo>; runTool: (name: string, args: Record<string, unknown>) => Promise<ToolRunResult> }`. Tab buttons: `role="tab"`, `[data-test=tab]`; roving tabindex; left and right arrows, Home and End move and focus; only the active tab's form is drawn, the others stay alive in `KeepAlive`.

- [ ] **Step 1: Write the failing tests**

`apps/ember_web/src/components/GuiTabsSection.test.ts`:

```ts
import { flushPromises, mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";
import type { GuiFormSectionSpec, GuiTabsSectionSpec } from "../api/CapabilityPagesClient";
import type { ToolInfo, ToolRunResult } from "../api/types";
import GuiTabsSection from "./GuiTabsSection.vue";

vi.mock("../api/CommandsClient", () => ({ commandsClient: { options: vi.fn(), upload: vi.fn() } }));

const tool = (name: string): ToolInfo => ({
  name,
  title: name,
  description: "",
  inputSchema: { type: "object", properties: { n: { type: "integer", default: 1 } } },
});
const TOOLS = { tool_a: tool("tool_a"), tool_b: tool("tool_b") };
const form = (id: string, title: string, toolName: string, live = false): GuiFormSectionSpec => ({
  type: "form",
  id,
  title,
  tool: toolName,
  submit: "Go",
  fields: [],
  live,
  result: { kind: "secret", field: "v" },
});
const SECTION: GuiTabsSectionSpec = {
  type: "tabs",
  id: "gen",
  tabs: [form("a", "Alpha", "tool_a", true), form("b", "Beta", "tool_b")],
};
const ok = (v: string): ToolRunResult => ({ text: "", isError: false, structured: { v } });

function mountTabs(runTool = vi.fn().mockImplementation(async (name: string) => ok(name))) {
  return { runTool, w: mount(GuiTabsSection, { props: { section: SECTION, tools: TOOLS, runTool } }) };
}

describe("GuiTabsSection", () => {
  it("shows every tab title and only the first tab's panel", async () => {
    const { w, runTool } = mountTabs();
    await flushPromises();
    expect(w.findAll("[data-test=tab]").map((t) => t.text())).toEqual(["Alpha", "Beta"]);
    expect(w.findAll("[data-test=tab]").map((t) => t.attributes("aria-selected"))).toEqual(["true", "false"]);
    expect(runTool).toHaveBeenCalledTimes(1); // Alpha is live: it ran, Beta did not
    expect(runTool).toHaveBeenCalledWith("tool_a", { n: 1 });
    expect(w.get("[data-test=secret]").text()).toBe("tool_a");
  });

  it("switches tabs by click and does not run a tab that is not live", async () => {
    const { w, runTool } = mountTabs();
    await flushPromises();
    await w.findAll("[data-test=tab]")[1]!.trigger("click");
    await flushPromises();
    expect(w.findAll("[data-test=tab]")[1]!.attributes("aria-selected")).toBe("true");
    expect(runTool).toHaveBeenCalledTimes(1);
    expect(w.find("button.run").exists()).toBe(true);
  });

  it("keeps a tab's settings and result when you come back", async () => {
    const { w, runTool } = mountTabs();
    await flushPromises();
    await w.findAll("[data-test=tab]")[1]!.trigger("click");
    await w.findAll("[data-test=tab]")[0]!.trigger("click");
    await flushPromises();
    expect(runTool).toHaveBeenCalledTimes(1); // coming back does not regenerate
    expect(w.get("[data-test=secret]").text()).toBe("tool_a");
  });

  it("moves with the arrow keys, Home and End, wrapping around", async () => {
    const { w } = mountTabs();
    await flushPromises();
    const list = w.get("[role=tablist]");
    await list.trigger("keydown", { key: "ArrowRight" });
    expect(w.findAll("[data-test=tab]")[1]!.attributes("aria-selected")).toBe("true");
    await list.trigger("keydown", { key: "ArrowRight" });
    expect(w.findAll("[data-test=tab]")[0]!.attributes("aria-selected")).toBe("true");
    await list.trigger("keydown", { key: "ArrowLeft" });
    expect(w.findAll("[data-test=tab]")[1]!.attributes("aria-selected")).toBe("true");
    await list.trigger("keydown", { key: "Home" });
    expect(w.findAll("[data-test=tab]")[0]!.attributes("aria-selected")).toBe("true");
    await list.trigger("keydown", { key: "End" });
    expect(w.findAll("[data-test=tab]")[1]!.attributes("aria-selected")).toBe("true");
  });

  it("uses a roving tabindex and ties each tab to its panel", async () => {
    const { w } = mountTabs();
    await flushPromises();
    const tabs = w.findAll("[data-test=tab]");
    expect(tabs.map((t) => t.attributes("tabindex"))).toEqual(["0", "-1"]);
    const panel = w.get("[role=tabpanel]");
    expect(panel.attributes("aria-labelledby")).toBe(tabs[0]!.attributes("id"));
    expect(tabs[0]!.attributes("aria-controls")).toBe(panel.attributes("id"));
  });

  it("says so when a tab's tool is not available", async () => {
    const w = mount(GuiTabsSection, { props: { section: SECTION, tools: { tool_b: TOOLS.tool_b }, runTool: vi.fn() } });
    await flushPromises();
    expect(w.text()).toContain("The tool tool_a is not available right now.");
  });
});
```

In `apps/ember_web/src/views/CapabilityPageView.test.ts` add:

```ts
  it("draws a tabs section as tabs", async () => {
    mocks.capabilities.mockResolvedValue([{ ...CAP, tools: ["tool_a", "tool_b"] }]);
    mocks.listTools.mockResolvedValue([TOOL, { ...TOOL, name: "tool_b", title: "B" }]);
    mocks.page.mockResolvedValue({
      version: 1,
      title: "Generator page",
      description: "",
      sections: [{ id: "g", tabs: [
        { id: "a", title: "Alpha", tool: "tool_a", result: { kind: "message" } },
        { id: "b", title: "Beta", tool: "tool_b", result: { kind: "message" } },
      ] }],
    });
    const w = await open();
    expect(w.findAll("[role=tab]").map((t) => t.text())).toEqual(["Alpha", "Beta"]);
  });
```

- [ ] **Step 2: Run to verify failure**

Run: `cd apps/ember_web && npx vitest run src/components/GuiTabsSection.test.ts src/views/CapabilityPageView.test.ts`
Expected: FAIL (component missing; view ignores tabs).

- [ ] **Step 3: Implement `GuiTabsSection.vue`**

```vue
<script setup lang="ts">
import { computed, nextTick, ref } from "vue";
import type { GuiTabsSectionSpec } from "../api/CapabilityPagesClient";
import type { ToolInfo, ToolRunResult } from "../api/types";
import GuiFormSection from "./GuiFormSection.vue";

/** Several form sections shown one at a time. The tab bar follows the ARIA
 * tabs pattern (roving tabindex; arrows, Home and End). Every tab you have
 * opened stays alive in <KeepAlive>, so it keeps its controls and result. */
const props = defineProps<{
  section: GuiTabsSectionSpec;
  tools: Record<string, ToolInfo>;
  runTool: (name: string, args: Record<string, unknown>) => Promise<ToolRunResult>;
}>();

const active = ref(0);
const buttons = ref<HTMLButtonElement[]>([]);
const current = computed(() => props.section.tabs[active.value]!);
const currentTool = computed(() => props.tools[current.value.tool]);

const tabId = (index: number) => `${props.section.id}-tab-${index}`;
const panelId = `${props.section.id}-panel`;

function select(index: number, focus = false): void {
  active.value = index;
  if (focus) void nextTick(() => buttons.value[index]?.focus());
}

function onKeydown(event: KeyboardEvent): void {
  const last = props.section.tabs.length - 1;
  const next: Record<string, number> = {
    ArrowRight: active.value === last ? 0 : active.value + 1,
    ArrowLeft: active.value === 0 ? last : active.value - 1,
    Home: 0,
    End: last,
  };
  const target = next[event.key];
  if (target === undefined) return;
  event.preventDefault();
  select(target, true);
}
</script>

<template>
  <section class="tabs">
    <div class="tablist" role="tablist" aria-label="Page sections" @keydown="onKeydown">
      <button
        v-for="(tab, i) in section.tabs"
        :id="tabId(i)"
        :key="tab.id"
        ref="buttons"
        type="button"
        role="tab"
        data-test="tab"
        :class="['tab', { active: i === active }]"
        :aria-selected="i === active"
        :aria-controls="panelId"
        :tabindex="i === active ? 0 : -1"
        @click="select(i)"
      >
        {{ tab.title }}
      </button>
    </div>
    <div :id="panelId" class="panel" role="tabpanel" :aria-labelledby="tabId(active)">
      <p v-if="!currentTool" class="error">The tool {{ current.tool }} is not available right now.</p>
      <KeepAlive>
        <GuiFormSection v-if="currentTool" :key="current.id" :section="current" :tool="currentTool" :run-tool="runTool" embedded />
      </KeepAlive>
    </div>
  </section>
</template>

<style scoped>
.tabs {
  margin-bottom: 12px;
}
/* Many tabs on a narrow screen scroll sideways instead of wrapping. */
.tablist {
  display: flex;
  gap: 4px;
  padding: 4px;
  margin-bottom: 14px;
  overflow-x: auto;
  border-radius: 12px;
  background: var(--surface);
}
.tab {
  flex: 1 0 auto;
  padding: 7px 14px;
  border: none;
  border-radius: 9px;
  cursor: pointer;
  font: inherit;
  white-space: nowrap;
  color: var(--muted);
  background: transparent;
}
.tab.active {
  font-weight: 600;
  color: var(--text);
  background: var(--bg);
  box-shadow: 0 0 0 1px var(--border);
}
.tab:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 1px;
}
.error {
  color: var(--danger);
}
</style>
```

- [ ] **Step 4: Wire it into the page view**

In `CapabilityPageView.vue`: add `import GuiTabsSection from "../components/GuiTabsSection.vue";` and replace the form/else lines in the section loop (the ones Task 3 adjusted) with:

```vue
          <GuiTabsSection v-else-if="s.type === 'tabs'" :section="s" :tools="tools" :run-tool="runTool" />
          <GuiFormSection v-else-if="tools[s.tool]" :section="s" :tool="tools[s.tool]" :run-tool="runTool" />
          <p v-else class="error">The tool {{ s.tool }} is not available right now.</p>
```

(After the `text` branch and the `tabs` branch, TypeScript narrows `s` to a form section, so the original lines work again.)

- [ ] **Step 5: Run the tests**

Run: `cd apps/ember_web && npx vitest run src/components/GuiTabsSection.test.ts src/views/CapabilityPageView.test.ts && npx vue-tsc --noEmit`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/ember_web/src/components/GuiTabsSection.vue apps/ember_web/src/components/GuiTabsSection.test.ts apps/ember_web/src/views/CapabilityPageView.vue apps/ember_web/src/views/CapabilityPageView.test.ts
git commit -m "feat(ember_web): tabs section for capability pages

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 9: Verify everything, look at it in a browser, update the spec

**Files:**
- Create (temporary, deleted at the end): `apps/ember_web/e2e/tmp_generator.spec.ts`
- Modify: `docs/superpowers/specs/2026-10-06-generator-page-design.md` (open points)

- [ ] **Step 1: Full test suites**

Run:

```bash
cd apps/mcp_server && .venv_mcp/Scripts/python.exe -m pytest -q
cd ../ember_web && npx vue-tsc --noEmit && npx vitest run && npm run test:e2e
```

Expected: everything passes. Fix any failure before going on; a failure in a test you did not touch is a regression from this work.

- [ ] **Step 2: Write a temporary browser check**

The page talks to `/api/capabilities`, `/api/capabilities/gen/gui` and the MCP proxy `POST /api/mcp/server` (JSON-RPC: `initialize`, `tools/list`, `tools/call`). Create `apps/ember_web/e2e/tmp_generator.spec.ts`:

```ts
import { test } from "@playwright/test";
import { ACCOUNT, installFakeApi, PASSWORD } from "./fakeApi.ts";

const range = (min: number, max: number, dflt: number) => ({ type: "integer", minimum: min, maximum: max, default: dflt, input: "range" });
const TOOLS = [
  { name: "tool_gen_generatePassword", description: "Password", inputSchema: { type: "object", properties: {
    length: range(8, 128, 20),
    use_upper: { type: "boolean", default: true }, use_lower: { type: "boolean", default: true },
    use_digits: { type: "boolean", default: true }, use_symbols: { type: "boolean", default: true },
    exclude_ambiguous: { type: "boolean", default: false } } } },
  { name: "tool_gen_getTotpCode", description: "TOTP", inputSchema: { type: "object", properties: { secret: { type: "string" } }, required: ["secret"] } },
];
const PAGE = { version: 1, title: "Generator", description: "Random things.", sections: [{ id: "generate", tabs: [
  { id: "password", title: "Password", tool: TOOLS[0]!.name, submit: "Run", fields: [], live: true,
    result: { kind: "secret", field: "password", detail: "message", strength: "entropy_bits" } },
  { id: "totp", title: "TOTP code", tool: TOOLS[1]!.name, submit: "Show code", fields: [], live: false,
    result: { kind: "secret", field: "code", group: 3, refresh_after: "seconds_remaining" } },
] }] };

function randomPassword(length: number): string {
  const pool = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789!@#$%";
  return Array.from({ length }, () => pool[Math.floor(Math.random() * pool.length)]).join("");
}

test("generator page", async ({ page }) => {
  await installFakeApi(page);
  const calls: string[] = [];
  // Registered after installFakeApi, so these win over its catch-all.
  await page.route("**/api/capabilities", (r) => r.fulfill({ json: [{ name: "gen", enabled: true, label: "Generator", tools: TOOLS.map((t) => t.name), resources: [], has_gui: true }] }));
  await page.route("**/api/capabilities/gen/gui", (r) => r.fulfill({ json: PAGE }));
  await page.route("**/api/mcp/server", async (route) => {
    const message = route.request().postDataJSON() as { id?: number; method: string; params?: { name: string; arguments: Record<string, unknown> } };
    if (message.id === undefined) return route.fulfill({ status: 202, body: "" });
    let result: unknown = {};
    if (message.method === "initialize") result = { protocolVersion: "2025-06-18", capabilities: { tools: {} }, serverInfo: { name: "fake", version: "1" } };
    else if (message.method === "tools/list") result = { tools: TOOLS };
    else if (message.method === "tools/call") {
      calls.push(JSON.stringify(message.params));
      const args = message.params!.arguments;
      const structured = message.params!.name === TOOLS[0]!.name
        ? { password: randomPassword(Number(args.length ?? 20)), entropy_bits: Number(args.length ?? 20) * 5.9, message: "Generated." }
        : { code: "492039", seconds_remaining: 20, message: "ok" };
      result = { content: [{ type: "text", text: JSON.stringify(structured) }], structuredContent: structured, isError: false };
    }
    return route.fulfill({ contentType: "application/json", headers: { "Mcp-Session-Id": "s" }, body: JSON.stringify({ jsonrpc: "2.0", id: message.id, result }) });
  });

  await page.goto("/");
  await page.getByLabel("Username").fill(ACCOUNT.username);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Log in" }).click();
  await page.getByPlaceholder(/Ask something/).waitFor();
  await page.goto("/capabilities/gen");
  await page.getByRole("tab", { name: "Password" }).waitFor();
  await page.waitForTimeout(600);
  await page.screenshot({ path: "tmp_gen_password.png" });

  await page.locator("input[type=range]").fill("64"); // fires input and change
  await page.waitForTimeout(800);
  await page.getByRole("tab", { name: "TOTP code" }).click();
  await page.getByLabel(/secret/i).fill("JBSWY3DPEHPK3PXP");
  await page.getByLabel(/secret/i).press("Enter");
  await page.waitForTimeout(600);
  await page.screenshot({ path: "tmp_gen_totp.png" });
  console.log("tool calls:", calls.length, calls.map((c) => c.slice(0, 80)).join(" | "));
});
```

- [ ] **Step 3: Run it and look at the screenshots**

Run: `cd apps/ember_web && npx playwright test e2e/tmp_generator.spec.ts`
Expected: passes, prints `tool calls: 3` (the password on open, one after the slider release, then the TOTP code once; a slider `fill` fires a single `change`, so there must be no per-tick calls). Open `tmp_gen_password.png` and `tmp_gen_totp.png` and check against the mockup: result card first with the big value and strength bar, chips and slider below, tab bar on top, TOTP code shown as `492 039` with the ring and "New code in N s". Fix layout problems in the components (spacing, chip row, bar colours) and re-run; also check dark mode by adding `await page.emulateMedia({ colorScheme: "dark" })` before the first `goto` and re-running once.

- [ ] **Step 4: Remove the temporary files**

```bash
rm apps/ember_web/e2e/tmp_generator.spec.ts apps/ember_web/tmp_gen_password.png apps/ember_web/tmp_gen_totp.png
rm -rf apps/ember_web/test-results
```

- [ ] **Step 5: Update the spec's open points**

In `docs/superpowers/specs/2026-10-06-generator-page-design.md`, replace the "Open points" section with:

```markdown
## Decisions made during implementation

- Many tabs on a narrow screen scroll horizontally (they do not wrap).
- A newer live run supersedes an older one in flight (only the last result is shown), rather than queueing.
- The hide/show control is an eye icon button with an accessible label; Copy stays a text button.
- No Playwright test was added for the page; the browser check used a throwaway spec with a mocked MCP proxy.
```

- [ ] **Step 6: Final commit and status**

```bash
git add docs/superpowers/specs/2026-10-06-generator-page-design.md
git commit -m "docs: record decisions from building the generator page

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
git status --short
```

Expected: only `apps/server_launcher/data/groups.json` remains modified (not ours). Report the three suite results and the screenshots to the person; do not push until they ask.
