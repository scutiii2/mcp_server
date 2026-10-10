# Emberlings in Ember: the playable page

Date: 2026-10-10. Builds on `2026-10-10-emberlings-backend-design.md` (the `apps/mini_games` backend, built and merged).

## Goal

Let an Ember user play Emberlings in the browser: collect Sparks, fight wild ones, answer the EMBLEM prompt, spend Insignia in the shop. Today the backend answers HTTP calls only; nothing in Ember can reach it.

This spec covers the page and the ember_api pass-through that serves it. It does not cover chat or MCP tools (see "What comes second").

## Why the page comes first

1. The game is real-time and visual. A battle has two health bars, a round log, a legal-action list and a five-second EMBLEM prompt with a countdown. A chat reply cannot show a countdown or update in place.
2. The backend is ready for it as it stands. The chat route needs a new `/mcp` endpoint on `mini_games`, a tool design and a decision about how an agent plays a timed prompt. The page needs none of that.
3. The page defines the one HTTP client that chat tools can reuse later. Building tools first would mean designing that client twice.

## Out of scope

- MCP tools, `/mcp` on `mini_games`, registering `mini_games` as an mcp_server extension, and playing from chat.
- Revealing the mood draw after a finished battle, and a game-discovery route (both named as deferred in the backend README).
- Admin tools for the catalog, a leaderboard, trading between accounts, animations and art. Sparks are drawn with text, tier badges and health bars only.

## Architecture

```
ember_web  /emberlings            (Vue page, Pinia store, EmberlingsClient)
   |  same-origin /api/emberlings/...   session cookie
ember_api  routes/emberlings.py   (permission, audit, Idempotency-Key forwarding)
   |  EmberlingsGateway           (httpx, internal token, requester header)
mini_games /sparks/...            (all game state; unchanged)
```

ember_api keeps no game data: no new table, no migration. All state lives in `mini_games`' SQLite. The browser never learns the `mini_games` address or token, and any identity header the browser sends is dropped, the same rule the MCP proxy follows.

### ember_api

**Config.** New key `emberlings_url` in `configs/config_app.json` and its `.example` (default `http://127.0.0.1:8060`). The internal token is the existing `INTERNAL_API_TOKEN` from `.env`. A missing key falls back to the default so existing real configs keep working.

**`services/emberlings_gateway.py`: `EmberlingsGateway`.** Modelled on `McpServerInfo`. One `httpx.AsyncClient`, the base URL, the internal token and a `TrafficRecorder`. One method, `request(method, path, account, json=None, params=None, idempotency_key=None)`, sends `X-Requester-Username: <account.id as text>` (see "Owner identity"), `X-Internal-Token` (when set) and `Idempotency-Key` (when given), with a 10 second timeout. Only the fixed paths in the table below are reachable. Results:
- `mini_games` 2xx: the JSON body (204 gives `None`).
- `mini_games` 400, 404 or 409: raises `EmberlingsRefused(status, message)` carrying its own `error` text, which is safe to show. The route turns it into the same status and body shape.
- `mini_games` 401, 5xx or no connection: raises `EmberlingsUnavailable`, which maps to 502 with "Emberlings is not available right now". A 401 here means the two `.env` tokens differ, so it is logged as a warning and never shown in detail.
- A `Protocol` (`EmberlingsApi`) sits in front of the gateway; tests inject `FakeEmberlings`, as `FakeAgent` and `FakeServerTools` do. It is created in the lifespan, stored on `app.state`, read through a `deps.py` getter and injectable through `create_app(...)`.

**Permission.** New `emberlings.play` in `ALL_PERMISSIONS` (description "Play Emberlings"). The Administrator role gets it on the next start; the `Member` role does not, because existing roles are never re-seeded. Say so when handing over, and grant it from the roles page.

**Routes** (`routes/emberlings.py`, prefix `/api/emberlings`, all `Depends(require_permission("emberlings.play"))`, JSON bodies only). Request models mirror `mini_games`' bodies with unknown fields rejected, so ember_api validates before forwarding.

| ember_api route | mini_games route | Notes |
|---|---|---|
| `GET /catalog` | `GET /sparks/catalog` | Cacheable for the session by the client |
| `POST /profile` | `POST /sparks/profile` | Needs `Idempotency-Key` |
| `GET /profile` | `GET /sparks/profile` | |
| `GET /sparks/{spark_id}/personalities` | same under `/sparks/sparks/...` | `limit`, `cursor` query |
| `GET`/`PUT /sparks/{spark_id}/presets/{slot}` | same | PUT needs a key |
| `POST /encounters`, `GET /encounters/{id}`, `POST /encounters/{id}/decline` | same | Roll and decline need a key |
| `POST /battles`, `GET /battles/{id}` | same | Start needs a key |
| `POST /battles/{id}/actions`, `/emblem`, `/advance`, `/mode`, `/forfeit` | same | All need a key |
| `POST /shop/purchases`, `POST /sparks/{spark_id}/sales` | same | Need a key |

Path parameters use the existing id patterns (letters, digits, `_`, `-`). A mutation without an `Idempotency-Key` header (1 to 200 characters) is a 400 here, before it reaches `mini_games`.

**Audit.** After success, `logs.action(account, "emberlings.<verb>", ...)` for the actions that change value: `profile_create`, `battle_start`, `battle_forfeit`, `shop_buy`, `spark_sell`. Round actions and `advance` are not logged (one per round would flood the log); a finished battle is already recorded in `mini_games`.

**Owner identity.** The owner is the account's id as text, not its username. An administrator can change a username (`PATCH` on the admin accounts route), and a username owner would lose its Sparks on rename. `mini_games` treats the header value as an opaque owner string, so no change is needed there. The other extensions key on the username; this one deliberately does not.

### ember_web

**Files.**
- `src/api/EmberlingsClient.ts`: plain object of functions over `apiRequest`, with TypeScript interfaces for the profile, catalog, encounter preview and battle view (fields as `mini_games` returns them: `spark_id`, `tier_id`, `hp`, `max_hp`, `actions`, `prompt.seconds_left`, `history`, `result`). Mutating calls create a fresh `crypto.randomUUID()` key per user action and reuse it only for an automatic retry of that same action.
- `src/stores/emberlings.ts`: Pinia setup store holding catalog, profile, current encounter, current battle and the loop state. Resets when `useAuthStore().account?.id` changes.
- `src/views/EmberlingsView.vue`: the page (always under `views/`).
- `src/components/emberlings/`: `SparkCard.vue`, `TierBadge.vue`, `HealthBar.vue`, `BattleArena.vue`, `ActionBar.vue`, `EmblemPrompt.vue`, `RoundLog.vue`, `PresetEditor.vue`, `ShopPanel.vue`. Reuse `SegmentedControl`, `BaseModal`, `ToggleSwitch`, `SaveButton`; look in `src/components/` before writing a new control.
- Router: lazy route `/emberlings`, `meta: { permission: "emberlings.play" }`; entry in `NAV_PAGES` (label "Emberlings", a stroked 24x24 spark/flame icon, one-line description). It joins `KeepAlive include` so an open battle survives tab switches, with the loop paused while hidden.
- Styling: theme tokens only. Tier badges use `--accent` for the top tiers and neutral tokens for the lower ones, with the tier name as text, so light and dark both work and color is never the only signal. Follow the radius scale and the `ember-design-system` skill.

**The page.** A `SegmentedControl` with three tabs: **Collection**, **Battle**, **Shop**. Insignia and EMBLEM counts show in a small header on every tab.

*First visit.* No profile yet: the Battle and Shop tabs are disabled and Collection shows the starter Sparks from the catalog; picking one calls `POST /profile`.

*Collection.* One `SparkCard` per owned Spark: name, tier badge, level, XP bar (`xp` / `xp_needed`, hidden at the cap), copies, and a fainted countdown from `faint_until`. Opening a card shows its abilities with unlock levels, its collected personalities (paged) and its five preset slots (up to three personality instances each) in `PresetEditor`. The catalog lists the Sparks the player does not own yet, greyed.

*Battle.* Three states:
1. **No encounter.** A "Look for a wild Spark" button, disabled with a countdown until `next_roll_at`. A profile with a `pending_encounter` or `active_battle` goes straight to that state on load (the page restores, it does not reroll).
2. **Encounter preview.** The wild Spark's name, tier, level, with Decline (free) and Fight. Fight opens a small form: which owned, non-fainted Spark, preset slot (or none), mode (Manual or Autonomous), EMBLEM limit (the highest tier an autonomous Spark may throw; "none" by default).
3. **Battle.** `BattleArena` shows both Sparks (name, level, tier, `HealthBar`, essence and speed, buffs, the defense effect), `RoundLog` renders `history`, and `ActionBar` shows the mode switch, Forfeit, and in manual mode one button per entry in `actions` (name, category, percentage; a not-ready ability is disabled with its cooldown). A catch action asks which EMBLEM tier to throw, from the owned counts. When `result` is set the page shows the outcome: won, knocked out, captured (listing the personalities revealed), escaped or forfeited, with XP, Insignia and copies gained, and a "Back" button.

*Shop.* `ShopPanel`: buy EMBLEMs per tier (price from the catalog, quantity), buy copies of a regular Spark at a tier, sell one absorbed copy. Buttons are disabled when Insignia would not cover the cost; a 409 from the server is still shown if the numbers changed in between.

**The battle loop (in the store).**
- *Autonomous mode.* After each response, if `status` is `active` and `phase` is `choosing`, wait 1.5 seconds (so the round log is readable) and call `POST /battles/{id}/advance`. The loop stops when `status` is not `active`, on unmount, and when the page is hidden (`document.visibilityState`); it resumes on return. The backend keeps the battle between rounds, so stopping is safe.
- *Manual mode.* No loop. An action sends `{round, revision, action}` from the last view. A 409 stale response triggers one `GET /battles/{id}` refresh and the buttons update; the action is not retried silently.
- *EMBLEM prompt.* When `phase` is `awaiting_emblem` and `prompt` is set, `EmblemPrompt` opens as a modal over the arena: the permitted tiers as buttons with owned counts and a countdown. The countdown runs from `prompt.seconds_left` at the moment the response arrived, using the local monotonic clock, not the server timestamp, so a wrong device clock cannot matter. Choosing calls `POST /battles/{id}/emblem`. At zero the buttons are disabled and the loop calls `advance`, which settles the prompt on the server (the Spark's Laya choice, or basic ATTACK). A late answer the server refuses (409 deadline passed) is treated the same way: refresh and continue.
- *Mode switch.* `POST /battles/{id}/mode` between rounds; the loop starts or stops to match.
- *Errors.* Network errors pause the loop with a "Reconnecting..." note and retry `GET /battles/{id}` every 3 seconds; the loop resumes when it answers. 502 shows "Emberlings is not available right now" instead of the page body, with a Retry button.

## Data flow for one autonomous round

1. Store calls `advance` with a fresh idempotency key.
2. ember_api checks the session and permission, forwards with the username and token.
3. `mini_games` locks the round, decides both actions, resolves it, saves the checkpoint and returns the new view.
4. The store replaces `battle`, `RoundLog` appends the new history entries, the loop schedules the next call.

A reload at any point rebuilds the page from `GET /profile` and `GET /battles/{id}`.

## Testing

- **ember_api** (`tests/test_emberlings.py`, `FakeEmberlings` in `conftest.py`): happy path per route, 401 logged out, 403 without `emberlings.play`, 400 for a missing `Idempotency-Key`, an unknown body field and a bad id, the same status and message passed through for a `mini_games` 404 and 409, 502 when unavailable, requester and token headers sent, browser-supplied `X-Requester-Username` and `X-Internal-Token` ignored, audit rows for the five logged actions only, the Administrator role has the new permission. A `tests/test_emberlings_gateway.py` runs the real gateway against `httpx.MockTransport`.
- **ember_web** (Vitest, ember_api mocked): the store loop (advances until finished, stops on unmount and when hidden, pauses on a network error, does not retry a stale action), the prompt countdown with fake timers, the encounter and shop buttons' disabled states, and the router guard. `e2e/fakeApi.ts` gets the new routes so Playwright keeps passing.
- Type-check (`vue-tsc -b --noEmit`) and `vite build` as the skill requires. Playing it for real is left to the user; no browser-verification agents.

## Docs

Update the API table in `ember_api/README.md`, the feature list in `ember_web/README.md`, add a Brain project note section for the Emberlings page, and note the new `emberlings_url` key in the `.example` config.

## What comes second

Chat and MCP: add an `/mcp` endpoint to `mini_games` (tools for profile, roll, fight, advance, shop) and register it as an extension with the complete entry (URL, token header, `forward_requester`). Text-only play suits autonomous battles and shop questions; the timed EMBLEM prompt needs its own design (for example, a chat-played battle always lets the Spark decide). The gateway and request models from this spec are reused, which is the reason to build the page first.

## Decisions taken without asking

- Owner is the account id, because usernames can be changed by an administrator (checked in `routes/admin.py`).
- New permission `emberlings.play`, not added to `Member` automatically.
- No ember_api database table; ember_api is a validating pass-through.
- Round actions are not written to the activity log.
- Autonomous round pace is 1.5 seconds, a constant in the store.
