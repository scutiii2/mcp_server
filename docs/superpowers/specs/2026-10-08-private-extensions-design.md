# Capabilities supermarket, phase 3: private (per-account) extensions

Date: 2026-10-08. Projects: `ai_agent`, `ember_api`, `ember_web`. Status: design approved in chat, awaiting written-spec review.

Phase 3 of 3. Phase 1 (account-level enabled state, the Supermarket) and phase 2 (`extensions.manage`) are merged. This phase adds extensions that belong to one account.

## Goal

A user can add an MCP server of their own, by URL and optional headers, that only they can see and only their chats use. It sits beside the server-listed extensions: a **My extensions** section in the Supermarket, and a card on the Capabilities page while it is enabled. Server-listed extensions (global, in `mcp_server`, managed with `extensions.manage`) are unchanged.

## Decisions

| Question | Decision |
|---|---|
| Where the connection is made | `ai_agent`, per turn, for the account that asked. `ember_api` stores the extensions and sends them with each turn; `mcp_server` is not involved. |
| Who may add one | Any account with `chat.use`, on its own rows only. Another account's id is 404. |
| Secrets | Arbitrary request headers. Stored encrypted (Fernet) in `ember_api`; the key is `EMBER_SECRETS_KEY` in `.env`. Header values never go back to the browser, a log or an error message. |
| Allowed addresses | `http` and `https`. Public and private-LAN addresses are allowed. Loopback (`127.0.0.0/8`, `::1`, `localhost`), link-local (`169.254.0.0/16`, `fe80::/10`), unspecified, multicast and cloud-metadata addresses are always blocked. A server on this machine stays a server-listed extension that an admin adds. |
| Approval | A tool of a private extension always asks the user first, even when "Ask before running tools" is off. "Allow for this chat" (the existing `allowed_tools`) lets it run freely in that chat. A delegated agent cannot ask, so it is refused. |
| Reach | The agent only. Slash commands and the Capabilities page tool runner go through `mcp_server`, so they do not cover private tools. |
| Delegation | Private extensions are given to the entry agent for the turn only. They are not passed to agents it delegates to. |
| A private extension is down during a turn | The turn goes on without its tools, and the chat shows a short notice. One bad URL never fails the turn. |
| Defaults | A newly added private extension is enabled. |

Out of scope: running private tools from the Capabilities page or slash commands, sharing a private extension with other accounts, stdio extensions, OAuth flows, editing a header value without retyping it, and per-tool toggles.

## ember_api

### Data

New table `user_extensions`, one Alembic migration (next free revision after the newest in `migrations/versions/`; check at implementation time):

- `id` (pk, integer), `account_id` (FK `accounts.id`, `ON DELETE CASCADE`, indexed).
- `slug` String(40): the id used in tool names, unique per account `(account_id, slug)`. Made from the label like `mcp_server` does (lowercase letters, digits and single `_`), with `_2`, `_3` appended on collision. It never contains `__`.
- `label` String(60), `description` String(300).
- `url` String(1000).
- `headers_encrypted` Text, nullable: a Fernet token of the JSON object `{"Header-Name": "value"}`. Null means no headers.
- `enabled` Boolean, default true.
- `created_at`, `updated_at`: naive UTC.

Limits: 20 extensions per account; at most 20 headers per extension; a header name matches `^[A-Za-z0-9-]{1,64}$`; a value is 1 to 2000 characters with no control characters. These header names are refused because they control the connection: `host`, `content-length`, `transfer-encoding`, `connection`, `upgrade`, `te`, `trailer`, `proxy-authorization`, `cookie`.

URL checks in `ember_api` are syntax only: `http` or `https`, a host, at most 1000 characters, no username or password in the authority. The address policy is enforced where the connection is made (see `ai_agent`), at connect time.

### Secret key

- `EMBER_SECRETS_KEY` is a Fernet key (url-safe base64, 32 bytes) in `.env`. At startup, if it is missing, `ember_api` generates one and appends it to `.env`. New dependency: `cryptography`.
- A small `SecretBox` class in `src/services/secret_box.py` wraps encrypt and decrypt. Decryption of a row that fails (the key changed) does not crash anything: that extension reports `status: "error"` with the message "Its headers can't be read (the secrets key changed). Edit it to set them again."
- When the key had to be generated, one warning line (without the key) is logged saying where it was written and that it must be kept with backups of `.env`.

### Service

`UserExtensionService(session, account_id, box)`: `list`, `get`, `create`, `update`, `delete`, `enabled_for_turn`. Every query filters by account. `enabled_for_turn()` returns `[{id: slug, label, url, headers: dict}]` for the enabled rows, with headers decrypted, and skips (and counts) any row whose headers cannot be decrypted. `update` clears the saved headers when the URL's host changes and the request sends no `headers`, so a saved token is never silently sent to another host. `TurnOptions.private_extensions` is excluded from `repr`.

### Routes (`chat.use`, JSON bodies)

- `GET /api/user-extensions` returns `[{id, label, description, url, header_names, enabled, status, error, tools}]`. `id` is the slug. `status` is `connected`, `error` or `unknown`. `tools` are the tool names the server listed. Status comes from a probe (below), cached in memory for 60 seconds per row; missing or expired entries of enabled extensions are probed concurrently (at most 5 at once); a disabled extension is not probed and reports `unknown`. `url` is returned; header values never are.
- `POST /api/user-extensions` with `{label, url, description?, headers?}` returns 201 with the same shape. It probes once, saves the row either way (an unreachable server is saved with `status: "error"`, like server-listed extensions), and returns the probe result. 409 at the 20-extension limit, 422 for a bad URL or header.
- `PATCH /api/user-extensions/{id}` with any of `{label, description, url, headers, enabled}`. `headers`, when present, replaces the whole set (so the browser sends it only when the user retyped them). Changing `url` or `headers` drops the cached probe and probes again.
- `DELETE /api/user-extensions/{id}` returns 204.
- Each add, edit, enable, disable and remove is written to the activity log (`account.user_extension_add` and so on). The message names the label and the URL's host, never the full URL (it may carry a token in the query string) and never a header value.

### Probe

`ember_api` calls a new `ai_agent` tool `probe_extension` through the gateway (new `AgentGateway.probe_extension(url, caller, *, extension_url, headers)`), because the guarded connector lives in `ai_agent`. The result is `{status, error, tools}`.

### Turn path

- `AgentGateway.ask` gains `private_extensions: list[dict] | None`. When non-empty it first checks `status.private_extensions` (fail closed, like `tool_approval` and `tool_filter`): an `ai_agent` that predates this would ignore the argument and the user's private tools would silently be missing, so the turn is refused with a message saying the agent needs updating and restarting.
- `TurnOptions` gets nothing from the browser. `routes/chats.py` loads `UserExtensionService.enabled_for_turn()` itself and passes the list in. The browser cannot name an extension URL for a turn.
- Approvals already work for any turn: `TurnRegistry.decide` and the `approvals` route only need a pending `approval_request` event, not `ask_before_tools`. Nothing changes there.
- `ai_agent`'s result may carry `private_extension_errors: [{id, label, error}]`. `TurnRegistry` publishes them as a live `notice` turn event `{type: "notice", notices: [...]}` just before the turn finishes; they are not saved in the chat. A private extension whose headers cannot be decrypted is left out of the turn and reported the same way, in a `notice` event at the start.
- `MAX_DISABLED_TOOLS` and the existing tool-name pattern are unaffected. Private tool names follow `u_<slug>__<tool>`, which fits `_TOOL_NAME`.

### Docs

`README.md`: the new routes, the table, the `EMBER_SECRETS_KEY` setting and what happens if it changes.

## ai_agent

### Connector and guard

New package `src/private_extensions/`:

- `guard.py`: `GuardedTransport`, an `httpx` async transport (or a network backend under it) that resolves the host itself and checks **every** resolved address before connecting, then connects to a checked address. Because every connection and every redirect hop goes through it, DNS rebinding and a redirect to `127.0.0.1` or `169.254.169.254` are both blocked. The blocklist: loopback, link-local, unspecified, multicast, reserved, the cloud metadata addresses (`169.254.169.254`, `fd00:ec2::254`, `100.100.100.200`), and IPv4-mapped IPv6 forms of those. Private LAN ranges (`10/8`, `172.16/12`, `192.168/16`, `fc00::/7`) are allowed. A blocked address raises `BlockedAddress` with a message safe to show ("That address is not allowed").
- The MCP SDK's `streamablehttp_client` must be given this transport. Check that the installed `mcp` version accepts an `httpx_client_factory`; if it does not, wrap the client creation so the factory is applied. A redirect is followed only to the same scheme, host and port, at most 3 hops; any other target raises `RedirectRefused`, so a configured header (a token) is never sent to another host. Each hop also passes the guard. A connection is made to the checked IP address, with the original host kept in the `Host` header and as the TLS server name, so a second DNS answer cannot change where it connects.
- Before `streamablehttp_client` is used, `open_private_session` makes one plain `initialize` POST through the same guarded client and raises on an HTTP error status (a wrong token is a 401). `mcp_server`'s `extensions.py` documents why: such a failure inside the SDK's own task group corrupts the event loop's cancel scopes.
- `pool.py`: `PrivateSessionPool`. Sessions are keyed by `(account email, url, sha256 of the sorted headers)`, so a header change opens a new session. A session idle for more than 300 seconds is closed the next time the pool is used (and all are closed at shutdown); at most 5 sessions per account and 50 in total (the oldest idle one is closed first); connect timeout 10 seconds (the existing `CONNECT_TIMEOUT_SECONDS`); call timeout 120 seconds. It uses the existing `open_session` pattern from `mcp_client/transports.py` and runs on the same background event loop as `SyncMcpClient`.
- `catalog.py`: for one turn, `bind(specs)` stores the specs in a `ContextVar`. `list_tools()` returns each connected extension's tools, namespaced `u_<slug>__<tool>`, capped at 100 tools per extension, and drops a tool whose full name exceeds 64 characters or does not match `^[a-zA-Z0-9_-]+$`, with the reason kept for the notice. A private tool never shadows a built-in or server-listed name (the `u_` prefix cannot clash with `main__`).

### Wiring

- `server.py` `ask(...)` gains `private_extensions: list[dict[str, Any]] | None = None`. It binds them for the turn with `catalog.bind` and resets afterward, like `tool_filter` and `internal_auth`.
- `mcp_upstream.list_tools` and `call_tool` merge in and route private tools. A call to a `u_...` name goes to the pooled session of that extension; an unknown or unbound `u_...` name is refused, so a model cannot name another account's tool.
- The tools are fetched before the provider starts, by an async `prefetch` run from `agent_config.run_chat` that connects to every extension concurrently on the connection loop. The providers' blocking `list_tools()` then only reads that cache, so it never waits on a network connection.
- `status()` adds `private_extensions`: true, except when the agent's provider is `laya` (it has its own tool shortlist and does not list tools through `mcp_upstream`).
- A new MCP tool `probe_extension(url, headers)` connects once through the guard, lists the tools, closes, and returns `{status, error, tools}`. It never raises for a bad server; the error is a short message without the headers.
- A connect failure during a turn is recorded in the result as `private_extension_errors` and the turn continues without those tools.
- Delegation: `delegation.py` does not forward `private_extensions`. A delegated agent never has private tools.

### Approval

In `core/approvals.py`:

- `ApprovalPolicy` gets `ask_prefixes: tuple[str, ...]`, set to `("u_",)` for a turn that has private extensions. Every private tool name starts with `u_`; no built-in or server-listed name does (those start with `main__`).
- `needs_approval(tool)` becomes: `tool not in allowed_tools` and (`mode != "off"` or the name starts with one of `ask_prefixes`).
- In `review()`, such a tool under mode `off` is handled as `ask`; under mode `deny` it is refused as today.
- A user's "Allow for this chat" and "always" decisions already add the tool to `allowed_tools`; nothing else changes.

### Logging

Nothing logs a header value. Exceptions are reduced to their root-cause message (`root_cause`) and the URL's host before they leave the module.

## ember_web

- `src/api/UserExtensionsClient.ts` for the four routes, and `src/stores/userExtensions.ts` (Pinia, per account, reset on account change) holding the list, an `error`, and `add`, `update`, `remove`, `refresh`.
- **Supermarket** (`SupermarketView.vue`): a new **My extensions** section below Extensions, shown to every account with `chat.use`. Each row (reuse `SupermarketItem`) shows label, slug, status and tool count, with **Enable** or **Disable**, **Edit** and **Remove**. **Add your own extension** opens `UserExtensionModal.vue`. The state filter chips apply to this section too (Enabled = enabled rows).
- `UserExtensionModal.vue`: label, URL, description and a header editor (name and value rows, value input masked, a row can be removed). On edit, the existing header **names** are shown with an empty value and the note "Leave blank to keep the saved value"; headers are sent only if the user changed any, as the whole set. The server's error message (blocked address, limit) is shown inline.
- Remove uses the in-app confirm modal, not a type-to-confirm one (the user's own thing, easy to re-add).
- **Capabilities page** (`CapabilitiesView.vue`): enabled private extensions are cards in the Extensions group, with the status dot, the tool names (no run button), a switch that disables the extension, and a "Private" label. They have no Open button and no resources.
- The chat shows a `notice` turn event as a small line under the answer.
- The approval card for a private tool is the existing one; no UI change beyond making sure it is shown when `ask_before_tools` is off.
- Tokens only for styling (`ember-design-system` skill): no hex colours, radius tokens, `:focus-visible`, icon-only buttons get a name.

## Error handling

- Bad URL, blocked address, header limit: 422 with a plain message. The 20-extension limit: 409.
- `ai_agent` unreachable when probing: the row is saved with `status: "unknown"` and `error: "Couldn't check right now"`; nothing is lost.
- `ai_agent` too old (no `private_extensions` flag): a turn that has private extensions is refused with the message above; a turn with none is unaffected.
- Key changed: affected extensions show an error and are left out of turns; the others work.
- Account deleted: its rows go with it (`ON DELETE CASCADE`).

## Testing

`ai_agent` (pytest):

- Guard: each blocked class (IPv4 and IPv6 loopback, link-local, metadata, unspecified, IPv4-mapped IPv6); a hostname that resolves to a blocked address; a hostname with several addresses where one is blocked; a redirect to a blocked address; LAN and public addresses allowed.
- Pool: reuse for the same key; a different header set opens a new session; idle expiry; per-account and global caps; a failed connect does not poison the pool.
- Catalog: namespacing, the 100-tool cap, over-long and invalid names dropped, no shadowing, a `u_` name that was not bound for this turn is refused.
- `ask()`: private tools listed for the turn that bound them and not for the next; a down extension yields `private_extension_errors` and the turn still finishes; not forwarded to a delegated agent.
- Approval: a private tool asks under mode `off`, runs after "allow", is skipped when in `allowed_tools`, is refused under `deny`, and a built-in tool still does not ask under `off`.
- `status()` reports `private_extensions`; `probe_extension` returns tools, error and never raises or echoes headers.

`ember_api` (pytest, with `FakeAgent`/`FakeUpstream`):

- Service and routes: create, list, update, delete, enable and disable; per-account isolation (another account's id is 404); limits; header validation including the refused names; the URL authority check.
- Encryption: headers are not readable in the database file; the API never returns a value; a wrong key makes the row report an error without breaking the list; a log entry never contains a value or a query string.
- Probe: cached for 60 seconds; a change to `url` or `headers` re-probes; an unreachable agent gives `status: "unknown"`.
- Turn: only the caller's enabled rows are sent; the browser cannot supply a URL; the fail-closed refusal against an old `ai_agent`; an `approval_request` for a private tool is accepted when `ask_before_tools` is off; `private_extension_errors` become a `notice` event.
- Migration test updated (`HEAD`/`NEXT` and the legacy-database helpers), as in earlier migrations.

`ember_web` (vitest and Playwright):

- Store: add, update, remove, optimistic enable and disable with rollback, reset on account change.
- Modal: masked values, edit keeps names with blank values, sends headers only when changed, shows the server's message.
- Supermarket: the new section, the filter chips, remove confirmation, errors. Capabilities page: private cards and their switch. Notice rendering.
- Playwright: add a private extension through the fake API, see its card on the Capabilities page, disable it.

## Work breakdown

Three parts, built in this order. `ai_agent` and `ember_api` ship together because of the fail-closed check.

1. `ai_agent`: `guard.py`, `pool.py`, `catalog.py`, the `ask()` argument, tool routing, `status()` flag, `probe_extension`, the approval change, and their tests.
2. `ember_api`: dependency and `SecretBox`, model and migration, service, routes, probe cache, gateway changes, turn integration, notices, README, and tests.
3. `ember_web`: client, store, modal, Supermarket section, Capabilities cards, notice line, tests, README.

Each part gets its own implementation plan and is committed task by task.

## Risks to check early

- Settled: `streamablehttp_client` accepts `httpx_client_factory` (mcp SDK in use). A factory returns an `httpx.AsyncClient`; the guard is installed as its `transport`.
- Whether `services/turns.py` and the `decide` route accept approvals when `ask_before_tools` is off.
- Provider limits on tool names (64 characters, a restricted character set) for both providers.
- The `anyio` cancel-scope problems documented in `mcp_server`'s `extensions.py` and `mcp_client/transports.py`: a connect to an unreachable host must go through the same plain-asyncio reachability probe before `streamablehttp_client`, then the guard.
