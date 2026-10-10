---
name: ember-feature-scaffold
description: Add a feature to ember_web (the Vue 3 + TypeScript browser app) and/or ember_api (its FastAPI backend) following this repo's established layout, auth and proxy conventions. Use whenever the user asks for a new ember_web page, screen, tab, panel, store or API call, a new ember_api route, permission, admin action or model, or wants ember_web to reach a new ai_agent / mcp_server capability - even if they only describe the behavior ("let admins see login attempts", "add a settings page to ember", "show token usage per answer") without naming files. Also use when reviewing whether ember_web/ember_api code follows these conventions. Not for new mcp_server tools (use mcp-capability-scaffold).
---

# ember_web + ember_api feature scaffolding

Two root projects that ship together:

- **ember_web/** - Vue 3 + TS (Vite, Pinia, vue-router). Talks **only** to
  ember_api, same-origin: Vite forwards `/api` to ember_api (`vite.config.ts`),
  so the `HttpOnly` session cookie just works and no server URL, token or
  key is ever in the bundle.
- **ember_api/** - FastAPI + async SQLAlchemy (SQLite/aiosqlite). Owns
  accounts, sessions, roles/permissions, invites, email verification (can be
  switched off with `require_email_verification: false`), and
  proxies MCP to ai_agent (`/api/mcp/agents/{id}`) and mcp_server
  (`/api/mcp/server`). Auth logic lives in its own database.

A third client uses the same REST API: **chat_cli/** (terminal chat, logs in
with the account, same cookie session, same SSE events). A change to an
existing route's shape or to the turn/events contract must keep it working -
check `apps/chat_cli/src/api.py` and `events.py` - and a new route the web app
needs is not automatically wanted there.

Read both READMEs (`apps/Ember/ember_web/README.md`, `apps/Ember/ember_api/README.md`) before
designing - they hold the current API table and security model this skill
compresses.

## Working agreement with this user

Propose each step first (files to create/change, packages, deletions),
wait for approval, then implement, verify, and report. Commit only after
verification passes and the user agrees; push only when asked. One step at
a time - never scaffold several unapproved pieces in one go. This is how
every ember change so far was made, and the user explicitly asked for it.

## 1. Decide where the feature lives

| The feature needs... | Touch |
|---|---|
| Only presentation of data ember_web already has | ember_web only |
| New data, a new action, or anything that must be enforced | ember_api route (+ service/model) **and** ember_web client/view |
| Something ai_agent or mcp_server can do | the MCP proxy path (section 4) - never a direct browser call |

Anything security-relevant (who may see or do what) must be enforced in
ember_api. ember_web's router guard and hidden tabs are cosmetic: they
keep the UI from offering calls the server would refuse, nothing more.

## 2. ember_api side

Layout: `src/routes/` (one `APIRouter` per area, prefix `/api/...`),
`src/services/` (classes taking an `AsyncSession` - logic lives here, not
in routes), `src/models/` (SQLAlchemy 2 typed models), `src/deps.py`
(dependencies), `src/services/permissions.py`.

1. **Permission.** Reuse `chat.use` / `tools.use` / `admin.manage` when one
   fits. A new one goes in `ALL_PERMISSIONS` (name -> description); the
   Administrator role picks it up automatically on next start. It is *not*
   added to existing roles such as `Member` (`ensure_default_role` only
   seeds a role when creating it) - say so to the user if members need it.
2. **Model** (if new data): new file in `src/models/`, export it from
   `src/models/__init__.py` (that import is what registers the table).
   Relationships use `lazy="selectin"` - async sessions can't lazy-load.
   Store times as naive UTC via `src.db.utcnow`. Any model change (new
   table or column) needs an Alembic migration: stop ember_api, run
   `python -m scripts.migrate_db revision "what changed"`, read the file it
   writes (a new `NOT NULL` column needs a `server_default`). Startup applies
   it after a backup; `tests/test_migrations.py` fails if it is missing.
3. **Service**: a class with `__init__(self, session: AsyncSession)`.
   Anything blocking (hashing, SMTP, file I/O) goes through
   `asyncio.to_thread`. Secrets/codes/tokens are stored hashed, never raw.
4. **Route**: gate with `Depends(require_permission(NAME))` (it also
   rejects unverified emails, unless `require_email_verification` is false) or `Depends(current_account)` for any
   logged-in user. Request/response bodies are pydantic models; response
   models get a `@classmethod of(cls, row)`. Register a new router in
   `src/app.py` (`app.include_router(...)`). New app-wide dependencies
   (clients, senders) are created in the lifespan, stored on `app.state`,
   read via a `deps.py` getter, and injectable through `create_app(...)`
   parameters so tests can pass fakes.
5. **POST bodies are always JSON** - `JsonOnlyMiddleware` rejects anything
   else with 415 (CSRF guard with the `SameSite=Strict` cookie). Don't
   add form endpoints.
6. **Tests** in `apps/Ember/ember_api/tests/`: fixtures in `conftest.py` give
   `client`, `client_factory(**settings)`, `email` (FakeEmailSender) and
   `upstream` (FakeUpstream for the MCP proxy); `tests/test_registration.py`
   has `as_admin`, `new_invite`, `register` helpers. Cover: happy path,
   401 when logged out, 403 without the permission / unverified, and
   validation errors. Run:
   `Ember\ember_api\.venv_ember_api\Scripts\python -m pytest -q` (from `apps/Ember/ember_api/`).
7. Update the API table in `apps/Ember/ember_api/README.md`.

## 3. ember_web side

Layout: `src/api/` (clients), `src/stores/` (Pinia setup stores),
`src/views/` (**pages - always here, never in components/**, a user
preference), `src/components/` (reusable pieces only), `src/router/`,
`src/utils/`, `src/services/`.

1. **Client** in `src/api/`: REST calls go through `apiRequest` from
   `api/http.ts` (JSON, same-origin cookie, 401 -> `UnauthorizedError` and
   the auth store drops the account). Export a plain object of functions
   like `authClient` / `adminClient`, with TypeScript interfaces for the
   response shapes.
2. **Store** (when state outlives one view): `defineStore("name", () => {...})`.
   Per-user state must reset when the user changes - watch
   `useAuthStore().account?.id` (see `stores/entryAgent.ts`, `stores/chat.ts`).
   Anything saved in `localStorage` is keyed per account and wrapped in
   try/catch (storage may be blocked) - see `services/ConversationStorage.ts`.
3. **View** in `src/views/XxxView.vue`, lazy-loaded route in
   `src/router/index.ts` with `meta: { permission: "..." }` (or
   `guestOnly: true` for logged-out pages). If it can be a landing page,
   add it to `HOME_PAGES`. Add it to `NAV_PAGES` in `src/router/pages.ts`
   (label, **`icon`** = stroked 24x24 SVG path data, one-line description,
   permission): that list drives both the icon-only left rail
   (`components/NavRail.vue`) and the Overview tiles (`IconTile.vue`). Don't
   add a page that duplicates one: Tools was merged into Capabilities
   (`/tools` redirects), so put tool UI there (`CapabilitySection`, `ToolCard`
   rows that open `ToolRunModal`). To keep its state across tab switches, add it
   to the `KeepAlive include` list (cache is keyed per account already).
4. **Shared controls - reuse, don't hand-roll**: `ToggleSwitch` (pill, instead
   of a checkbox), `LockSwitch` (a setting an admin can force on),
   `SegmentedControl` (period/tab pickers; Admin, Logs and Usage use it),
   `BaseModal` (every dialog: `AddExtensionModal`, `ToolRunModal`, ...),
   `IconTile` (Overview tiles and extension tiles), `SaveButton`, `CopyButton`.
   Look in `src/components/` before writing a new one.
5. **Styling**: theme tokens from `src/style.css` (`--bg`, `--surface`,
   `--text`, `--muted`, `--border`, `--accent`, `--accent-contrast`,
   `--danger`, `--code-bg`, `--mono`) - never hardcoded colors, so light and
   dark both work. Page views scroll themselves (`flex: 1; min-height: 0;
   overflow-y: auto`), content column `max-width: 820px`.
6. **TypeScript gotcha**: `tsconfig.app.json` has `erasableSyntaxOnly`, so
   no constructor parameter properties (`constructor(private x: T)`) and no
   enums - declare fields explicitly.
7. **Markdown/HTML from the server or a model** only via
   `components/MarkdownContent.vue` (DOMPurify-sanitized) - never raw `v-html`.
8. Verify from `apps/Ember/ember_web/`: `npx vue-tsc -b --noEmit` (must print
   nothing) and `npx vite build`, then delete `dist/`. Tests sit beside the source
   (`*.test.ts`, Vitest + jsdom, ember_api mocked): `npm test`. If a page now
   calls a new `/api` route, add it to `e2e/fakeApi.ts` - the Playwright test
   (`npm run test:e2e`) fails on any call the fake does not know.

## 4. Reaching ai_agent / mcp_server

The browser never gets their URLs; everything goes through ember_api's
proxy, which drops browser-supplied identity/token headers and adds
`X-Requester-Username` / `X-Requester-Email` (+ `X-Internal-Token` if
configured) itself. ai_agent and mcp_server reject `/mcp` without that
token once it's configured, so any new ember_api client of theirs must
send it too (`identity_headers()` in `services/mcp_session.py` does).

- **mcp_server tools and resources**: already allowed for `tools.use`
  (`SERVER_POLICY`: `tools/list`, any `tools/call`, `resources/*`). Call them
  from ember_web with `McpServerClient` (`api/McpServerClient.ts`).
  mcp_server's plain HTTP routes (`/commands`, `/capabilities`, ...) go
  through `services/mcp_server_info.py` + `routes/server_info.py`.
- **A page for one mcp_server capability** is declared in that capability's
  `gui/page.json` (see mcp_server's capabilities README), not added as a new
  Vue view: `CapabilityPageView` at `/capabilities/<name>` draws it.
- **Chat with ai_agent** runs inside ember_api, never through the proxy:
  `services/turns.py` (TurnRegistry) calls the agent through
  `services/agent_gateway.py` (the `mcp` SDK), saves the answer and records
  usage; the browser starts a turn (`POST /api/chats/{id}/turns`) and
  watches `/events` (SSE, `services/turnStream.ts`). The proxy allows only
  `status` on agents - adding `ask` there would let the browser bypass the
  usage limits. A new agent tool the server needs goes on `AgentGateway`
  (and `FakeAgent` in `tests/conftest.py`); one the browser may call
  directly goes in `AGENT_POLICY.tools` with its exact argument names.
- **Server-side mcp_server calls** (such as command-option metadata)
  go through `services/server_tools.py` (`ServerTools`
  Protocol, `McpServerTools` on one MCP session; `FakeServerTools` in
  tests) behind its own permission, not through the browser proxy.
- **Audit:** a route that changes something calls
  `logs.action(account, "<area>.<verb>", "<what changed>")`
  (`LogWriter` via `Depends(get_log_writer)`) after it succeeded. New
  permissions go in `services/permissions.py`; the Administrator role gets
  them on the next start.
- Agent discovery is ember_api's `GET /api/agent` (the entry agent; reads ai_agent's
  `.data/agent_registry.json` through `AgentDirectory`: `entry`, `orchestrator`,
  `focus`); don't add a tool for it. **There is no agent picker**: every turn goes
  to the entry agent, a browser-sent `agent_id` is ignored, and the entry agent
  delegates to specialists itself. The chat store tracks who is working from
  `agent_start` / `agent_end` / `agent_token` events and the snapshot's
  `active_agents`; steps and tokens are keyed by `(agent_id, id)` because a
  specialist's step ids can collide with the entry agent's. New per-agent
  display belongs on those events, not on a new route.
- **Usage** carries agent, provider, gateway, model and call times
  (`agent_usage` on answers, usage rows in the DB): reports take `group_by`
  (`agent|provider|gateway|model`) and `agent`/`provider` filters, and
  `GET /api/usage/records` lists calls. Adding a column to usage rows is a
  model change - see the Alembic step in section 2 (`0003` did this).
- Tests: route tests use `FakeAgent` (the `agent` fixture; `hold=True` keeps
  a turn running until `agent.release()`); `tests/test_agent_gateway.py`
  runs the real gateway against a real FastMCP server. Starlette's
  TestClient only returns a streamed body once it's complete.

## 5. Before reporting done

- ember_api tests pass; ember_web type-check and build pass.
- READMEs updated (API table, features, layout) when the surface changed.
- Summarize for the user what changed, what was verified and how, what
  they should test by hand (they test manually - don't launch browser
  verification agents), and propose the commit message.
