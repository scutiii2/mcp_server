# ember_admin: admin web app and live capability management

Date: 2026-10-08
Status: design approved in chat, awaiting written-spec review

## Goal

A separate web app, `apps/ember_admin`, for the administrators of ember. It
gives admins:

1. The Admin and Analytics pages, ported from `ember_web`.
2. A page to list, add and remove mcp_server extensions.
3. A page to set each capability online or offline, so its code can be edited.
4. A Refresh button that finds capabilities added to mcp_server's folder while
   it runs, with no restart of `mcp_server` or `ember_api`.

## Decisions

| Question | Decision |
|---|---|
| Admin and Analytics in `ember_web` | Copy. They stay in `ember_web` until the owner asks to remove them. |
| Backend | `ember_api`. No second backend, no second login system. |
| Going online | Every offline to online switch re-imports the capability from disk. |
| State of a newly discovered capability | Offline. |
| Discovery | A folder scanner in `mcp_server`, not a manifest file. |

## Architecture

```
browser --> ember_admin (:5175) --/api proxy--> ember_api (:8030) --> mcp_server (:8010)
```

### ember_admin (new project)

- Vue 3 + TypeScript, same stack and design tokens as `ember_web`, so the
  Admin and Analytics components copy over directly.
- Pages: Admin (accounts, roles, invites, settings), Analytics (logs, traffic),
  Capabilities, Extensions.
- Auth: its Vite dev and preview servers proxy `/api` to `ember_api`, as
  `ember_web` does, so the browser sees one origin and no CORS is involved.
  Cookies are not scoped by port, so a login made in `ember_web` also works
  here. A user without `admin.manage` or the log and traffic permissions sees
  the no-access page.
- Has a `run.bat` and an entry in `server_launcher` (port 5175, env var
  `EMBER_ADMIN_PORT`).
- Follows the `ember-design-system` and `ember-feature-scaffold` skills.

### ember_api changes

- New admin-only proxy routes (permission `admin.manage`):
  - `POST /api/capabilities/refresh` runs the mcp_server scan.
  - The capability status list gains `load_error`, `missing` and `discovered`
    fields.
- Each action (toggle, refresh, extension add or remove) writes an entry to the
  activity log, which the Analytics page already reads.
- No new database tables.

### mcp_server changes

New module `src/services/capability_loader.py` replaces the eight hard-wired
import blocks in `src/run.py:55-93`.

**Discovery.** Lists the folders of `src/capabilities/` that contain an
`__init__.py`. Importing the package runs `capability_meta.register(...)`,
which gives the folder's `id` and `label`.

- Startup: each folder whose `config_capabilities.json` entry is online is
  loaded and registered live. A folder with no entry is registered offline.
- `POST /capabilities/refresh` runs the same scan on the running server and
  returns the new status list. New folders are added. A folder that vanished is
  marked `missing`, not deleted.

**Going online (load and reload).**

1. Remove the capability's old state: its tools and resource templates from
   `mcp`, its entries in `commands._COMMANDS`, and its `capability_meta` entry
   (a new `capability_meta.unregister(folder)` is needed, because `register`
   raises on a duplicate folder).
2. Purge `src.capabilities.<folder>` and every submodule from `sys.modules`,
   then import again inside `capability_registry.capturing(...)`. A fresh
   import is used, not `importlib.reload`, because reload misses submodules
   such as `domain.py` and `contract.py`.
3. If the import raises, roll back to offline and store the error text as
   `load_error`.

**Going offline.** Same as the existing `capability_registry.set_enabled`
behavior (tools and templates removed from the live server). The module stays
in `sys.modules` until the next online.

**Persist-then-apply** stays as in `capability_routes.py`: the config file is
written first, then the live server is changed.

**First-run migration.** `config_capabilities.json` today lists eight
capabilities and omits `watchers`, which the current rule (absent means
enabled) keeps on. Under "absent means offline" it would go dark. On first run
the loader writes an explicit `enabled: true` entry for every capability that
is already registered and has no entry, so nothing changes for existing
installs.

**Agent tool lists.** `ai_agent` may cache the tool list, so a toggle or reload
might not reach a running agent until it refreshes. This is unverified.
Before the implementation plan, read how `ai_agent` refreshes its tool list
(`apps/ai_agent/src/mcp_client/`). If it needs a nudge, Refresh and toggles
also notify the agents.

## Error handling

- Import error on online or reload: roll back to offline, keep the last 20
  lines of the traceback (no secrets) as `load_error`, show it on the row in
  ember_admin. Other capabilities are unaffected.
- Import error at startup or Refresh: the server still boots. The capability is
  listed offline with `load_error`.
- Duplicate tool name with another capability: the online step is refused with
  HTTP 409 naming the clash, and the old state is restored.
- Config write fails: nothing live changes (persist-then-apply).
- Concurrency: one `asyncio.Lock` serializes load, unload and scan. The blocking
  import runs in `asyncio.to_thread` so the event loop is not stalled.
- ember_admin shows a failed call as an inline error on that row. A toggle
  stays pending until the server answers and never shows an unconfirmed state.
  Offline and Refresh need no type-to-confirm because they are reversible.
  Extension removal uses the in-app confirm modal from the ember_web UI
  conventions.

## Testing

- mcp_server (pytest), using a temp capabilities folder with fixture packages:
  - the scan finds a new folder and registers it offline
  - online loads it, and an edited file is picked up on the next online
    (proves a fresh import, not a cache)
  - a broken import rolls back and sets `load_error`
  - a removed folder becomes `missing`
  - `@command` and `capability_meta` entries are cleaned up, with no
    duplicate-key error on reload
  - concurrent toggles are serialized
  - first-run migration keeps `watchers` online
- ember_api (pytest): permission checks, proxy shape for refresh and status,
  one activity-log entry per action.
- ember_admin (vitest): Capabilities and Extensions pages, plus the copied
  Admin and Analytics tests. Playwright e2e against a fake API, as ember_web
  does. No live browser verification by the agent; the owner tests manually.
- Docs: update `Brain/Projects/MCPServer.md` and add `ember_admin.md` when a
  project sync is requested.

## Out of scope

- Removing Admin and Analytics from `ember_web` (a later, separate step).
- Editing capability source code from the browser. Code is edited in the repo.
- A separate backend or login system for ember_admin.
- Reload of an extension (HTTP MCP server). Extensions are only listed, added
  and removed.
