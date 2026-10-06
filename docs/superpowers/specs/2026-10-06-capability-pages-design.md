# Capability pages: design

Date: 2026-10-06. Status: approved in chat, awaiting written-spec review.

## Goal

Each `mcp_server` capability can ship its own page in ember_web, at `/capabilities/<alias>`. The page layout lives in the capability's folder (`gui/page.json`), is served by `mcp_server`, passed through `ember_api`, and drawn by a generic renderer in `ember_web`. The page sits beside the existing tool-runner list; each capability card links to it.

## Decisions

- Declarative UI: a page is data, not code. The capability's own code never runs in the browser.
- The page sits beside the current `/capabilities` list. The card gets an "Open page" link when the capability has a page.
- The first page is the `generator` capability (`/gen`).
- Out of scope for v1: charts, multi-tool sections, custom styling, per-capability scripts, server-pushed updates.

## Data flow

1. `mcp_server`: `GET /capabilities/{name}/gui` returns the capability's validated `gui/page.json`. 404 if the capability has no page, the page is invalid, or the capability is turned off. `GET /capabilities` gains `has_gui: bool` per capability.
2. `ember_api`: `GET /api/capabilities/{name}/gui` passes the JSON through. Needs `tools.use`.
3. `ember_web`: route `/capabilities/:name` opens `CapabilityPageView`, a generic renderer. Buttons call tools through the existing `/api/mcp/server` proxy, so identity handling and permissions are unchanged.

## Security

- `page.json` is data. The renderer draws only its fixed widget set and ignores anything else.
- Every `tool` a page names must belong to that capability. `mcp_server` checks this at load; `ember_web` checks again.
- Results and entered secrets live only in component memory. Never in `localStorage`, the URL or `ember_api`.

## Folder shape

`gui/` joins the capability top-level whitelist (next to `static/` and `utils/`). It holds `page.json` only. The capabilities README and the `mcp-capability-scaffold` skill are updated to say so.

## page.json format (version 1)

```json
{
  "version": 1,
  "title": "Generator",
  "description": "Random passwords, passphrases, PINs and TOTP codes. Nothing is stored.",
  "sections": [
    {
      "id": "password",
      "title": "Password",
      "tool": "tool_gen_generatePassword",
      "submit": "Generate",
      "result": { "kind": "secret", "field": "password", "detail": "message" }
    },
    {
      "id": "totp",
      "title": "TOTP code",
      "tool": "tool_gen_getTotpCode",
      "fields": [{ "param": "secret", "label": "Secret" }],
      "result": { "kind": "secret", "field": "code", "refresh_after": "seconds_remaining" }
    }
  ]
}
```

- Page: `version`, `title`, optional `description`, ordered `sections`.
- Section types: a form bound to one `tool`, and a plain `text` section for notes.
- Form fields come from the tool's own input schema (the same schema `ToolRunForm` uses), so types, ranges, defaults and the masked secret input need no extra JSON. `fields` is optional and only overrides `label`, `order` or `hidden`.
- Result kinds: `secret` (monospace, copy button, hide/show), `message` (plain text), `table` (uniform list), `fields` (default label/value list).
- `refresh_after` names a numeric result field. The page shows a countdown and calls the tool again when it reaches zero. It stops on unmount and while the tab is hidden.
- Unknown keys are ignored with a console warning.

## Errors

- No page, or capability off: 404. ember_web shows "This capability has no page" and a link back.
- Invalid `page.json`: `mcp_server` validates it with Pydantic when it loads the capability, logs the problem and reports `has_gui: false`. One bad file never breaks the server or other capabilities.
- Tool call fails: inline error in the section, same handling as the tool-runner modal.
- Missing `tools.use`: same redirect as the existing Capabilities page.

## Tests

- `mcp_server`: page-model validation (valid page, unknown tool, wrong capability, bad `refresh_after`), the route (200, 404 with no page, 404 when disabled), the `has_gui` flag, and a test that every shipped `gui/page.json` parses and names only its own capability's tools.
- `ember_api`: pass-through route, permission check, 404 relay.
- `ember_web`: vitest for the renderer (form from schema, each result kind, countdown and refresh with fake timers, stop on unmount, invalid-page card) and the "Open page" link; one Playwright test for the generator page against the fake API.

## Docs

Capabilities README (folder whitelist and a `page.json` reference), `mcp-capability-scaffold` and `ember-feature-scaffold` skills, `ember_web` and `ember_api` READMEs, and the Brain notes.

## Rollout

One commit per step, each after the user's OK (ember_web work is proposed step by step).

1. `mcp_server`: page model, loader, route, `has_gui`, generator `page.json`, tests, docs.
2. `ember_api`: pass-through route, tests, README.
3. `ember_web`: types, API client, `CapabilityPageView` and renderer, route, card link, tests.
4. Final check: all suites, and the page tried in the browser.
