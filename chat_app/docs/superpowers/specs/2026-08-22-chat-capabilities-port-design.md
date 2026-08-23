# Chat & Capabilities Pages — Design Spec

Date: 2026-08-22
Status: Draft — pending user review

## 1. Goals

Port MCPArchitecture's **Chat** (`/chat`) and **Capabilities**
(`/capabilities`) pages into this project's `chat_app`, adapted to its
page/permission/security conventions rather than copied wholesale.
This includes the full LLM chat subsystem those two pages depend on,
none of which exists here today:

- Three LLM providers — Claude, OpenAI, Ollama — behind a common
  router, at full feature parity (including the staged-pipeline
  ask-user pause/resume flow and per-provider rate-limit cooldowns).
- A live MCP tool/resource browser talking to `mcp_server` over its
  existing HTTP interface (`MCP_SERVER_URL`) — `mcp_server` itself is
  identical in both repos and is used as-is, unmodified.
- Per-user chat history, persisted across sessions.
- Extension (proxied MCP server) management from the chat sidebar.

## 2. Non-Goals

- No redesign of the chat/capabilities feature set or UI — this is a
  port at feature parity, not a rework.
- MCPArchitecture's own auth/session stack (`chat_app.auth.*`,
  `chat_app.security`) is **not** ported. This project's existing
  `flask_login` + `src.services.authz` + `src.services.security`
  pipeline replaces it entirely — see §4 and §8.
- MCPArchitecture's own per-turn JSONL trace files
  (`services/session_log.py`) and standalone error-reference files
  (`errors.py`) are **not** ported. Both are replaced by this
  project's existing `LogEntry` / `log_service` pipeline — see §6.2
  and §6.3.
- No change to `mcp_server`.
- No change to the three providers' actual model-calling logic beyond
  import-path rewrites (`chat_app.*` → `src.*`) — behavior is
  preserved as-is.

## 3. Pages

### 3.1 `src/pages/Chat/`

`__index__.py` exposes `blueprint` (name `"chat"`), following the
`Account`/`Logs` convention: `template_folder="."`,
`static_folder="."`, `static_url_path="/static"`. `PAGE_LAYOUT =
"full"`, `PAGE_DESCRIPTION = "Chat with the MCP-connected LLM."`,
`PAGE_PERMISSION = "chat.access"`.

Routes ported from `pages/chat/routes.py`, URL-for-URL the same
(`/chat`, `/chat/api/providers`, `/chat/api/extensions`,
`/chat/api/chats`, `/chat/api/chats/<id>`, `/chat/api/chat`), each
decorated `@require_login()` + `@require_permission("chat.access")`.
The page route drops the `username`/`role`/`scopes`/`is_executive`
template context MCPArchitecture passed in — this project's shared
sidebar/account menu already reads that from `flask_login.current_
user` via `pages/__index__.py`'s context processors, so nothing needs
threading through `render_template()` for display purposes.

`chats_store` calls (`list_chats`, `get_chat`, `rename_chat`,
`delete_chat`, `save_chat`, `UnknownChat`) are keyed by
`current_user.username` instead of the original's `service.
current_username()`.

### 3.2 `src/pages/Capabilities/`

Same shape: `blueprint` name `"capabilities"`, `url_prefix=
"/capabilities"` (matches the existing folder-name-derived prefix, no
override needed), `template_folder="."`, `static_folder="."`,
`PAGE_LAYOUT = "full"`, `PAGE_DESCRIPTION = "Browse and try MCP server
tools and resources live."`, `PAGE_PERMISSION = ("capabilities.view",
"capabilities.try")` (visible if the account holds *either* — reuses
the tuple/list support `_visible()` already gained for the Logs page).

Routes ported from `pages/capabilities/routes.py`:
`/capabilities/` (browse), `/capabilities/api/tools`,
`/capabilities/api/resources` → gated by
`@require_permission("capabilities.view")`;
`/capabilities/api/try/<tool_name>`,
`/capabilities/api/read-resource` → gated by
`@require_permission("capabilities.try")` (see §4 for why these are
split).

### 3.3 Templates

Both pages' `index.html` are restructured from MCPArchitecture's
standalone HTML documents into this project's `{% extends "base.html"
%}` + block convention (see `Logs/logs.html` for the pattern):

```html
{% extends "base.html" %}
{% block title %}Chat{% endblock %}
{% block sidebar %}{% include "sidebar.html" %}{% endblock %}
{% block content %}
<link rel="stylesheet" href="{{ url_for('chat.static', filename='styles.css') }}">
... (ported body markup, unchanged) ...
<script src="{{ url_for('chat.static', filename='script.js') }}"></script>
{% endblock %}
```

MCPArchitecture's own `_shared/template` assets
(`sidebar.html`/`sidebar.css`/`sidebar.js`) are **not** ported — this
project's `__shared__/sidebar.html` + `account_menu.html` already
render `nav_pages` and the account menu from `current_user`, and are
used instead. `modal.css`/`modal.js` are ported only if Chat's
`script.js` actually calls into them (e.g. a rename/delete-chat
confirm dialog) — to be confirmed by reading `script.js` during
implementation; if unused, they're dropped. `styles.css`/`script.js`
for both pages are otherwise ported near-verbatim, since neither
depends on the old auth/sidebar internals for anything beyond what's
already covered above. The two `marked`/`dompurify` CDN `<script>`
tags in Chat's template are kept as-is (no local vendoring in scope).

## 4. Permissions

Four new permissions, registered the same way existing pages register
theirs (`register_permission(...)` at module scope):

- `chat.access` — the Chat page and all `/chat/api/*` routes.
- `capabilities.view` — the Capabilities page and its read-only
  `/api/tools`, `/api/resources`.
- `capabilities.try` — `/api/try/<tool_name>` and
  `/api/read-resource`, split out from `capabilities.view` because
  this console executes real MCP tool calls with caller-supplied
  arguments (deleting, restarting, sending mail — whatever a
  connected tool does) — the same reasoning that gives Logs its own
  `logs.errors.view` split from `logs.view`.
- `logs.chat.view` — see §6.2.

Both pages appear in `nav_pages` per the existing visibility rule
(any-of the page's `PAGE_PERMISSION` tuple); nobody sees them until an
admin grants the relevant permission to a role, same as every other
non-Overview/Sample page today.

## 5. Backend services

Ported into `src/services/llm/` and `src/services/`, with every
`chat_app.*` import rewritten to `src.*` and behavior otherwise
unchanged:

- `services/llm/base.py`, `router.py`, `cooldown.py`,
  `claude_provider.py`, `openai_provider.py`, `ollama_provider.py`,
  `staged_pipeline.py`, `staged_plans_store.py`.
- `services/llm/app_config.py` — Ollama desired-model-list loader
  (was `infra/app_config.py`); reads `src/configs/config_chat.json`
  instead of the original's `CHAT_CONFIG_PATH` env-pointed file, to
  match how `config_security_*.json` already lives under
  `src/configs/` (see §7).
- `services/mcp_client.py` — unchanged behavior; still an HTTP client
  to `mcp_server` via `streamablehttp_client`, reading
  `MCP_SERVER_URL` from the new `secret_llm.env` (§7) instead of
  `chat_app.config.settings`.
- `services/tool_capabilities.py`, `services/tool_titles.py` —
  unchanged, pure lookup tables.
- `chats/store.py` → `src/services/chats_store.py` — see §6.1.

## 6. Persistence

### 6.1 Chat history & staged plans — dedicated SQLite files

Per your decision, this project's convention is each page/feature that
needs its own storage gets its own dedicated database file rather than
folding everything into `app.db`. `chats/store.py` (plain `sqlite3`,
no ORM, JSON-blob-per-conversation) and
`services/llm/staged_plans_store.py` are ported essentially unchanged:
`data/chats.db` and `data/staged_plans.db`, alongside the existing
`data/app.db`. `UnknownChat` and every function's `(db_path,
username, ...)` signature carry over as-is.

### 6.2 Turn-trace logging → `LogEntry`

MCPArchitecture's `session_log.record_turn()` (one JSONL file per
chat, written to `logs/chats/<user>/<chat_id>.jsonl`) is **not**
ported. Instead, each chat turn becomes a `LogEntry` row via a new
`log_service` call:

- `kind = "chat_trace"` (new value alongside existing `"action"` /
  `"error"` — fits the existing `String(20)` column).
- `account_id` = the chatting account's id (never `NULL` — a chat
  turn always belongs to a specific account, unlike server-scoped
  action/error entries).
- `source = "chat.turn"`.
- `message` = a short one-line summary — question (truncated),
  provider/model, elapsed time, token count — built the same way
  `run.py`'s `_MESSAGE_MAX`-truncation already keeps other `message`
  values under the column's 500-char cap.
- `details` = JSON text: tool calls (name, arguments, result),
  recursive-round records, full response text — the same shape
  `record_turn()` used to write per line, now the `LogEntry.details`
  blob instead of a JSONL line.

This needs a **new `logs.chat.view` permission** (trace payloads can
carry tool arguments/results, so it's gated separately from
`logs.view`/`logs.errors.view`) and a **third tab** on the existing
Logs page: `Logs/__index__.py`'s `PAGE_PERMISSION` becomes
`("logs.view", "logs.errors.view", "logs.chat.view")`, and its route
gains a `can_view_chat_traces` flag + third `list_entries(db.session,
"chat_trace", ...)` call, rendered as a third `data-tabs` panel
alongside Logs/Errors.

Written from `chat_api` the same defensive way the original did —
wrapped so a logging failure never breaks the chat answer itself
(mirrors the existing `try/except ... report(error, context=...)`
pattern at that call site, just calling `log_service.log_error`
instead of the dropped `errors.report`).

### 6.3 Unexpected-exception handling

`chat_api`'s unexpected-exception branch (`except Exception as error:
...`) stops calling MCPArchitecture's own `errors.report()` (which
wrote a standalone reference file under `log_dir/errors/`) and instead
calls `log_service.log_error(db.session, current_user, source=...,
message=..., details=traceback.format_exc())` — the same pipeline
`run.py`'s global `handle_unexpected_error` already uses, visible on
the Logs page's existing Errors tab. The response text shown to the
chat user keeps the same "something went wrong, reference is in the
log" shape, generated at the call site instead of by a dedicated
`errors.py` module.

**Correction (post-implementation):** `try_tool`/`read_resource_route`
in Capabilities do **not** call `log_service.log_error` — matching
MCPArchitecture's own original `capabilities/routes.py`, which never
called `errors.report()` from those two handlers either (they return
`str(exc)` straight to the browser, uncaptured server-side, by
original design — the try-it console is an explicit debugging tool,
not a production code path). An earlier draft of this section
incorrectly implied both `chat_api` and `try_tool` gained the new
logging call; only `chat_api` did, which is the correct, faithful
behavior.

## 7. Config & secrets

New `src/secrets/secret_llm.env` (+ `secret_llm.env.example`), loaded
via the existing `utils/config_loader.load_env_secrets` (no new
dependency needed — this project doesn't use `python-dotenv`). Its
values, plus `BASE_DIR`-resolved defaults for `CHATS_DB_PATH`/
`STAGED_PLANS_DB_PATH`/`CHAT_CONFIG_PATH`, are merged into
`os.environ` by `run.py`'s `create_app()` before any page is
registered — see the implementation plan's Task 1 for exact
mechanism (`chat_app.config`'s original CWD-relative path defaults
would otherwise regress the same bug this project's own
`_resolve_sqlite_uri` already exists to prevent for `app.db`):

```
MCP_SERVER_URL=http://127.0.0.1:8010/mcp
OPENAI_API_KEY=
OPENAI_MODEL=gpt-5.6-sol
ANTHROPIC_API_KEY=
CLAUDE_MODEL=claude-sonnet-5
```

New `src/configs/config_chat.json` (alongside the existing
`config_security_*.json` files, loaded the same way via
`utils/config_loader.load_all_json_configs`), holding the Ollama
desired-model list (`providers.ollama.models[].{id,label,
recursive_chain,staged_pipeline}`) — same shape and validation rules
as the original `config.json`, read by the new
`services/llm/app_config.py` (§5). **Ships as `{}` by default** (no
`providers.ollama` section) — a deliberate, valid quiet state per
`app_config.load_ollama_models`'s own docstring (an unconfigured
deployment shouldn't need this file just to start), not something the
operator must populate before running the app. `Chat/script.js`'s
provider dropdown correctly disables Ollama with a "no models
configured" label whenever this file leaves `MODELS` empty, rather
than offering a selectable-but-guaranteed-to-fail option.

## 8. Cross-site request protection

This project's `CSRFProtect` is conditionally enabled
(`config_security_headers.json`'s `csrf_enabled`). Chat/Capabilities'
`script.js` makes JSON `fetch()` POST/PATCH/DELETE calls without CSRF
tokens (MCPArchitecture relied on a `Sec-Fetch-Site`/Origin check
instead — see its `security.py`'s `check_cross_site`). This project's
security pipeline (`fingerprint.py`/`headers.py`/`ip_filter.py`/
`rate_limit.py`) currently has **no** equivalent check.

Per your decision: a small project-wide check is added rather than a
one-off fix scoped to these two pages —

- New `src/services/security/cross_site.py`, `check_cross_site()`
  ported from MCPArchitecture's version: state-changing methods
  (`POST`/`PUT`/`PATCH`/`DELETE`) require `Sec-Fetch-Site` to be
  `same-origin`/`none` when present, falling back to an Origin-vs-Host
  comparison when the browser doesn't send that header.
- Wired into `services/security/pipeline.py`'s existing
  `before_request` chain (unconditional, not gated by a config flag —
  same as MCPArchitecture's original, and it protects every current
  and future JSON endpoint, not just these two pages).
- `chat_bp` and `capabilities_bp` are exempted from `CSRFProtect` (only
  meaningful when `csrf_enabled` is on) via `csrf.exempt(...)` —
  `pipeline.py`'s `register_security_pipeline()` needs to expose the
  `CSRFProtect` instance it creates (currently a local, unreturned
  variable) so `run.py`/`pages/__index__.py` can call `.exempt()` on
  the two new blueprints after registration.

This does **not** change authentication — `require_login()` /
`require_permission()` (backed by the `flask_login` session cookie)
still gate every Chat/Capabilities route exactly as everywhere else in
the app; the cross-site check is an independent, additional layer that
stands in for the CSRF token these two pages don't carry.

## 9. Dependencies

`chat_app/pyproject.toml` gains: `mcp`, `pydantic`, `pydantic_core`,
`openai`, `anthropic` (version pins to match MCPArchitecture's
`pyproject.toml` unless a newer compatible version is preferred at
implementation time).

## 10. Testing Strategy

- `tests/test_llm_router.py` / provider-level tests — port
  MCPArchitecture's existing provider/router tests, updating imports
  only.
- New `tests/test_chats_store.py` — round-trip
  save/list/get/rename/delete against a temp `chats.db`, mirroring
  `chats/store.py`'s own docstring invariants (a chat id belonging to
  another user is indistinguishable from nonexistent).
- New `tests/test_chat_page.py` — route tests: 401/403 without
  `chat.access`; `/api/chat` persists a `LogEntry(kind="chat_trace")`
  on success; an unexpected exception produces a
  `LogEntry(kind="error")` and a safe reference-style message, not a
  raw traceback, in the response.
- New `tests/test_capabilities_page.py` — 403 on `/api/try/<tool>` and
  `/api/read-resource` for an account holding only
  `capabilities.view`; both permitted for one holding
  `capabilities.try`.
- `tests/test_logs_page.py` — extend for the third `chat_trace` tab
  and `logs.chat.view` permission, mirroring existing
  logs/errors-tab coverage.
- New `tests/test_cross_site.py` — `check_cross_site()` rejects a
  cross-site `Sec-Fetch-Site` header and a mismatched Origin on a
  state-changing method; allows `same-origin`/`none`/absent-with-
  matching-Origin; ignores `GET`.

## 11. Defaults Flagged for Review

- `capabilities.try`'s split from `capabilities.view` and
  `logs.chat.view`'s split from `logs.view`/`logs.errors.view` are new
  permission names not present in either source project — flag if you
  want different naming or a coarser grouping.
- The Logs page's existing "Server + every account" dropdown doesn't
  quite fit the `chat_trace` tab (a chat turn is never server-scoped)
  — the "Server" option would always show zero rows there. Proposed:
  keep the same dropdown shape for consistency, "Server" just always
  empty for that tab; flag if you'd rather the dropdown default straight
  to a specific account for that tab, or drop "Server" from it
  entirely.
- `modal.css`/`modal.js` porting is contingent on what Chat's
  `script.js` actually uses them for — confirmed during
  implementation, not decided here.
- Dependency version pins (§9) default to matching MCPArchitecture's
  current `pyproject.toml` exactly; flag if you want latest-compatible
  instead.
