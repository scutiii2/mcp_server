# Capabilities supermarket, phase 1: account-level enabled state

Date: 2026-10-08. Projects: `ember_api`, `ember_web`. Status: design approved in chat, awaiting written-spec review.

This is phase 1 of 3. Phase 2 (a separate permission for managing server-listed extensions) and phase 3 (private, per-account extensions) are out of scope here and get their own specs. See "Later phases" at the end.

## Goal

Split "what exists" from "what I use". Today the Capabilities page lists every built-in capability and every extension, with a switch on each that lives in this browser's `localStorage`. After this change:

- Each account keeps, on the server, the set of built-in capabilities and server-listed extensions it has enabled.
- The Capabilities page shows only what the account has enabled.
- A new Supermarket page lists everything available, so the account can enable more.
- The "Add extension" and "Remove extension" admin actions move into the Supermarket.

## Decisions

| Question | Decision |
|---|---|
| Where is the enabled set stored | Server side, in `ember_api`, per account. It follows the account across devices. |
| New account default | Everything disabled. A new account has no tools until it shops. |
| Migration of existing choices | None. Existing `localStorage` keys are ignored and left in place. The only current account re-enables what it wants. |
| Meaning of the switch on a capability card | Off means disabled for this account. The card leaves the Capabilities page and the item reappears in the Supermarket as disabled. Nothing is deleted. |
| Can a user remove a built-in capability or a server-listed extension | No. They can only disable it. Removing a server-listed extension stays an admin action (`admin.manage`, unchanged in this phase). |
| Supermarket route | `/capabilities/supermarket`. A real route, so it is linkable and the back button works on mobile. |
| Supermarket layout | Two stacked sections, Built-in and Extensions. No "All" tab. |
| Supermarket filter | Two toggle chips, Enabled and Disabled, mutually exclusive. Clicking the active chip clears it. No chip means show both. |
| Status dot | Kept on every Capabilities card with today's meaning (green: on and running, grey: off for everyone, red: extension not connected). It later takes a real per-capability status (see "Status dot"). |

Out of scope: private extensions, the `extensions.manage` permission, a name filter in the Supermarket, tool reload without restart.

## ember_api

### Model

New table `account_capabilities`:

- `account_id`: FK to `accounts.id`, `ON DELETE CASCADE`.
- `kind`: String(16), one of `capability` or `extension`.
- `key`: String(64). A capability name or an extension id, as `mcp_server` reports them.
- `created_at`: naive UTC.
- Primary key `(account_id, kind, key)`.

A row means "enabled". No row means disabled. There is no per-row boolean, so there is no third state to reason about.

One Alembic migration. Its revision id is the next free one when the work starts. `main` ends at `0005`. If branch `feat/nav-sidebar-arrangement` (which adds `0006_nav_preferences`) has merged by then, this one is `0007` with `down_revision = "0006"`. `tests/test_migrations.py` must pass.

`ember_api` does not validate keys against `mcp_server`. Like `nav_preferences`, it stores what the browser sends and the browser ignores keys it does not know. Keys are limited to `^[A-Za-z0-9_.-]{1,64}$`, and an account may hold at most 200 rows.

### Service

`AccountCapabilityService(session, account_id)`, modelled on `NavPreferenceService`. Every query filters by account.

- `get() -> AccountCapabilities` returns `capabilities: list[str]` and `extensions: list[str]`, each sorted.
- `set_enabled(kind, key, enabled) -> AccountCapabilities` inserts or deletes one row and returns the full set. Setting an item to the state it already has is a no-op, not an error.
- `forget_extension(extension_id)` is a module-level function that deletes the rows of that extension for every account. The extension removal route calls it so deleted extensions leave no stale rows.

### Routes (`/api/account-capabilities`, any logged-in account, private to it)

- `GET /api/account-capabilities` returns `{"capabilities": [...], "extensions": [...], "disabled_tools": [...]}`. `disabled_tools` is the sorted list of tool names of every mcp_server capability the account has not added, worked out by ember_api from mcp_server's `/capabilities`. If mcp_server is unreachable the call answers 502 and nothing is guessed.
- `PUT /api/account-capabilities/{kind}/{key}` with body `{"enabled": bool}` returns the same shape. `kind` outside `capability` or `extension` is 422. The capability list is read first, so a 502 leaves the stored set unchanged. This is one call per item, not "replace the whole set", so two devices changing different items never overwrite each other.
- Existing `DELETE /api/extensions/{extension_id}` also calls `forget_extension`.
- `MAX_DISABLED_TOOLS` in `routes/chats.py` rises from 500 to 2000, because with nothing added a question carries every capability's tools.
- Each change is audited with `logs.action` (`account.capability_enable` and `account.capability_disable`, same for extensions).

## ember_web

### Stores

New `stores/accountCapabilities.ts` (Pinia), modelled on `stores/navPrefs.ts`:

- State: `capabilities: string[]`, `extensions: string[]`, `disabled_tools: string[]`, `ready: boolean`, `error: string`.
- `load()` runs when the account signs in. `setCapability(name, on)` and `setExtension(id, on)` apply the change optimistically, call the PUT, replace the state with the server's reply, and roll back and set `error` on failure.
- `reset()` on sign-out, like the other per-account stores.

New `api/AccountCapabilitiesClient.ts` wraps the two routes.

`stores/chat.ts` changes:

- `enabledExtensions` is no longer its own `localStorage`-backed ref. It reads the account store. `setExtensionEnabled` and `setCapabilityEnabled` call into the account store.
- The tools handed to `disabled_tools` come straight from the account store (`disabled_tools` in the server's reply). The browser no longer reads `/api/capabilities` for this, so accounts with only `chat.use` are covered.
- The `readExtensions` and `disabledCapabilitiesKey` readers and their keys are removed.
- A question is not sent until the account store has loaded. If the load failed, sending shows the error and sends nothing. The store never falls back to "everything on", because an unloaded set would otherwise offer every tool.

### Capabilities page (`views/CapabilitiesView.vue`)

- Lists only built-in capabilities in the account's enabled set and extensions in the account's enabled set. The `groupTools` input is filtered before the call, so search keeps working over the shown items.
- The "All / Built-in / Extensions" segmented control stays. The header gets a **Supermarket** button (router link) and loses **Add extension**.
- The card's switch is now always operable. Turning it off disables the item for this account and the card disappears. The old `locked` rule (a capability that is off for everyone) no longer blocks it.
- A capability that an admin turned off for everyone, but that the account still has enabled, stays on the page dimmed, with the existing "Turned off for everyone" note and the status dot grey.
- The card footer keeps **Turn off / on for everyone** (admin) for built-ins. It drops **Remove** for extensions, which moves to the Supermarket.
- When the account has nothing enabled, the page shows an empty state: "Nothing added yet. Open the Supermarket to add capabilities." with a button to it.
- The "How switches work" text is rewritten: the switch decides what is added to the account, and it follows the account to other devices.
- The tool run modal, resource reader and Open button are unchanged.

### Supermarket page (new `views/SupermarketView.vue`, route `/capabilities/supermarket`)

- The route is declared before `/capabilities/:name` so a capability named `supermarket` can never shadow it. Permission is the same as the Capabilities page (`tools.use` or `chat.use`).
- Header: **Back to capabilities** link, title, and the Enabled / Disabled filter chips.
- Section **Built-in** (needs `tools.use`): one row per capability from `/api/capabilities`.
- Section **Extensions**: one row per extension from `/api/extensions`. Admins (`admin.manage`) see **Add extension** in this section header, which opens the existing `AddExtensionModal`, and **Remove** on each row, which opens the existing `ConfirmModal`. Neither changes meaning in this phase.
- A row (new `components/SupermarketItem.vue`) shows the icon tile, label, id, a one-line summary (tool count, or "Not connected" for a failed extension) and one control:
  - Not enabled: **Add** pill. It enables the item for the account.
  - Enabled: **Added** with a check, and a **Disable** secondary button. This uses the same enable call with `enabled: false`.
  - A capability that is off for everyone: the row is dimmed with the badge "Off for everyone" and **Add** is not offered. An admin sees **Turn on for everyone** here, which reuses the existing confirm flow.
- The filter chips use the account's enabled set. Enabled shows only enabled rows, Disabled only the others, no chip shows both. The chip state lives in the URL query (`?state=enabled`), so a link keeps it.
- The Supermarket has no tool run modal or resource reader. It only manages membership.
- Empty section copy: "No built-in capabilities match this filter." and the same for extensions.

### Status dot

The dot on each Capabilities card keeps today's meaning and still comes from `CapabilityInfo.enabled` and `ExtensionInfo.status`. This phase does not add a status field. The planned live-reload work will add `status: "online" | "offline" | "reloading"` to `CapabilityInfo` and map it onto the same dot, so no card markup changes then. `CapabilitySection` already takes a `status` prop; that is the only seam the later work needs.

## Error handling

- A failed PUT rolls the item back and shows the store's `error` in a banner on the page that triggered it.
- A failed `GET` on the Supermarket or Capabilities page shows the existing load error. The account store being unloaded blocks sending, as above.
- A key the account enabled that no longer exists (an extension an admin removed) is dropped from the page and the Supermarket, since the lists come from `mcp_server`. The row is removed by `forget_extension` when removal goes through `ember_api`, and is harmless otherwise.

## Testing

`ember_api` (pytest):

- Service: enable, disable, repeat is a no-op, set is sorted, an account never sees another account's rows, deleting an account deletes its rows, the row cap, key validation.
- Routes: auth required, 422 on a bad `kind` or key, the returned set matches the stored set, `DELETE /api/extensions/{id}` clears that extension for every account.
- `tests/test_migrations.py` covers the new migration up and down.

`ember_web` (vitest):

- `accountCapabilities` store: load, optimistic update, rollback on failure, reset.
- `chat` store: tools sent as `disabled_tools` are exactly those of capabilities not enabled; extensions sent are exactly the enabled ones; sending is blocked until loaded and when the load failed. `chat.capabilities.test.ts` is rewritten for this.
- `CapabilitiesView`: shows only enabled items, empty state, the Supermarket button, no Add extension button, the switch removes a card.
- `SupermarketView` and `SupermarketItem`: sections, Add and Disable, the filter chips and their URL query, the off-for-everyone row, admin-only add and remove.
- Router: `/capabilities/supermarket` resolves before `/capabilities/:name`.
- `e2e/fakeApi.ts` gains the new routes.

## Docs

- `apps/ember_api/README.md`: the new table and routes.
- `apps/ember_web/README.md`: the Supermarket page and the account-level switches.
- `Brain/Projects/ember_api.md` and the ember_web note are updated at project sync, not in this change.

## Later phases

- Phase 2: a new `extensions.manage` permission replaces `admin.manage` on `POST` and `DELETE /api/extensions`. The Supermarket buttons already live where they will stay.
- Phase 3: user-listed extensions, private to the account that added them. A `user_extensions` table in `ember_api`, a per-turn connection pool in `ai_agent`, a "My extensions" section in the Supermarket with Add and Remove, and URL restrictions (http and https only, no link-local or metadata addresses, a per-account cap). Private extension tools work for the agent, not for slash commands.
