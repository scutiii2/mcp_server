# Generator page redesign

Date: 2026-10-06. Status: draft for review.

## Goal

Replace the generator capability's page (five stacked forms, each with a Generate button and a plain result) with one tabbed page: a large result card on top, live controls below, a strength bar, and a TOTP countdown ring. Build it from generic page-format features so other capabilities can reuse them, not as a page specific to `gen`.

Reference mockup: shown in the 2026-10-06 design session (tabs Password / Passphrase / PIN / TOTP, one result card, sliders and chips, strength bar, ring).

## Non-goals

- No new tools and no change to any tool's behaviour. One result gains a field (below).
- No change to how a page is served (`GET /capabilities/{name}/gui`) or how ember_api passes it through.
- No QR code, no password history, nothing stored. A value still shows once.
- No `version` bump of the page format (see Compatibility).

## Page format additions (`gui/page.json`, version 1)

All additions are optional, so existing pages are unchanged.

| Addition | Where | Meaning |
|---|---|---|
| `tabs` section | `sections[]` | `{ "id": str, "tabs": [form section, ...] }`. 2 to 8 tabs. Each tab is an ordinary form section; its `title` is the tab label. A section with a `tabs` key is a tabs section (like `text` marks a text section). |
| `live` | form section, `bool`, default `false` | The form runs once when it opens and again whenever a control changes to a valid value. Adds a Generate again button to the result. Hides the form's own Run button. |
| `strength` | `secret` result, identifier | Names a numeric result field holding bits of entropy. The result shows a strength bar and label. |
| `group` | `secret` result, int 2 to 8 | Display only: insert a space every N characters. Copy still copies the raw value. |

Validation rules:

- `strength` and `group` are only allowed when `kind` is `secret`.
- Section ids are unique across the whole page, including tab ids.
- A page may only name its own capability's tools, including inside tabs.
- Unknown keys are ignored, as today.

The rules are enforced in two places that must agree: `apps/mcp_server/src/capability_gui.py` (pydantic) and `apps/ember_web/src/utils/guiPage.ts` (parser).

## mcp_server changes

- `capability_gui.py`: add `GuiTabsSection`; extend `_section_kind` to pick it by the `tabs` key; add `live` to `GuiFormSection`; add `strength` and `group` to `GuiResult` with the rules above; make the duplicate-id and own-tools checks walk into tabs.
- `capabilities/generator/contract.py` and `domain.py`: `PinResult` gains `entropy_bits` (`length * log2(10)`, rounded like the other results). `generate_pin` fills it. Additive.
- `capabilities/generator/tool.py`: add `json_schema_extra={"input": "range"}` to the length (password, PIN) and words (passphrase) parameters. Their `ge` and `le` bounds stay. This is the same hint convention `secret` already uses (`"input": "password"`). Side effect: the Tools page and the chat command form also draw these three fields as sliders.
- `capabilities/generator/gui/page.json`: one `tabs` section with five tabs:
  1. Password: live, `result: secret / password / strength entropy_bits`.
  2. Passphrase: live, `secret / passphrase / strength entropy_bits`.
  3. PIN: live, `secret / pin / strength entropy_bits`.
  4. TOTP secret: not live, Generate button, `secret / secret`.
  5. TOTP code: not live, `secret / code`, `group: 3`, `refresh_after: seconds_remaining`.
  
  Plus a text section: nothing here is stored.
- Docs: `capabilities/README.md` "GUI pages" section describes `tabs`, `live`, `strength`, `group`; `capabilities/generator/README.md` mentions the page.

## ember_web changes

All under `apps/ember_web/src`.

- `api/CapabilityPagesClient.ts`, `utils/guiPage.ts`: types and parser for the additions, with the same rules and errors as the server.
- `components/GuiTabsSection.vue` (new): tab bar (`role="tablist"`, left and right arrow keys, `aria-selected`) and the active panel. Panels sit inside `<KeepAlive>`, so each tab keeps its control values when you switch away.
- `components/GuiFormSection.vue`:
  - Inside tabs it renders without its own card and title, result first and controls below.
  - With `live`: runs on mount and on valid changes, debounced about 300 ms. The existing `runId` check drops stale responses. A run in flight is never doubled.
  - On deactivate (tab hidden) it stops the `refresh_after` countdown and resumes it on activate.
  - The countdown text becomes `components/CountdownRing.vue` (new, small SVG) beside the code.
- `components/ToolRunForm.vue`: new `live` prop. It emits the built args whenever a field changes and validates. `range` widgets emit on `change` (slider release), not on every `input` tick. In live mode the Run button is hidden, range fields show a value readout, and checkbox fields draw as toggle chips. Default behaviour is unchanged, so the Tools page and chat command form look as they do today apart from the new sliders.
- `components/GuiResult.vue`, `secret` kind: large monospace display with digits tinted accent and symbols green; eye icon to hide; Copy; Generate again (emitted as an event, shown only for live forms); strength bar and label (Weak under 45 bits, Fair under 70, Strong under 100, Excellent above); `group` spacing.
- Accessibility and motion: bar and ring transitions respect `prefers-reduced-motion`. The secret is not an `aria-live` region.

## Behaviour decisions

- Live runs fire on committed changes only: chip, select or checkbox changes, slider release, and typed text after the debounce. Dragging a slider does not call the tool per tick, because each call puts a real secret through the chat-side plumbing (the generator README warns results may reach logs).
- The first live run happens when a tab is first opened, not when the page loads, so hidden tabs make no calls.
- Switching tabs keeps settings but does not regenerate.

## Compatibility

`version` stays 1. All fields are optional and unknown keys are ignored, so older pages work in new apps. A newer `tabs` page opened in an older ember_web fails its parser with "layout is invalid"; both apps ship from this repo, so this is accepted.

## Testing

- `apps/mcp_server/tests/test_capability_gui.py`: valid tabs page; duplicate id across tabs; foreign tool inside a tab; fewer than 2 or more than 8 tabs; `strength` or `group` on a non-secret result; `group` out of range; `live` defaults to false. The existing shipped-page test covers the new generator `page.json`.
- `apps/mcp_server/tests/test_generator_domain.py`: PIN `entropy_bits`.
- `guiPage` parser tests: the same rules as the server.
- Component tests: `GuiTabsSection` (keyboard, keep-alive of settings); live `GuiFormSection` (debounce, stale response dropped, countdown paused while inactive, no run for a hidden tab); `ToolRunForm` live mode (emits on change not on input tick, no emit when invalid); `GuiResult` (strength levels, grouping, hide, copy raw value).
- Full vitest and pytest suites, and the Playwright suite, pass. The e2e fake API may need a capability page route if a page-level test is added.

## Open points

- The tab bar for 8 tabs on a narrow screen: scroll horizontally or wrap. Decide during implementation by viewing it.
- Whether to add a Playwright test for the page: only if the fake API can serve a capability page cheaply.
