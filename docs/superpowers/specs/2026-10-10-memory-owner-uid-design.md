# Memory notes keyed on a stable account uid

Date: 2026-10-10
Status: design approved in chat, not implemented
Amends: `docs/superpowers/specs/2026-10-10-persistent-memory-design.md` (owner identity) and closes follow-up 1 of `_TODO.md` item 6.

## Problem

The `memory` capability keys every note on the username (`identity_context.current_username()`). A username is unique at one moment but not stable over time:

- An admin rename orphans the user's notes.
- A deleted account's notes stay in `mcp_server` for ever.
- A new or renamed account that takes a freed username inherits the previous person's personal facts.

The integer `Account.id` is not a safe key either. It is a plain SQLite `INTEGER PRIMARY KEY` without `AUTOINCREMENT`, so deleting the newest account lets the next account reuse its id (the same bug fixed for note ids in `34eed36`).

## Decision

Key memory on a new immutable `uid` on each account: a random UUID created with the account, never changed, never reused, never shown to a browser. Deleting an account purges its notes. Nothing needs to move when a username changes. Rejected: reusing `Account.id` with `AUTOINCREMENT` (riskier migration of an existing table, and the guarantee would depend on that setting staying in place).

Touches three projects: `ember_api`, `ai_agent`, `mcp_server`. `ember_web` and `chat_cli` do not change.

## Design

### 1. The uid (`apps/Ember/ember_api`)

- `models/account.py`: new column `uid: Mapped[str] = mapped_column(String(32), unique=True, default=lambda: uuid.uuid4().hex)`. Every code path that creates an account gets one through the default: `services/registration_service.py`, `services/auth_service.py` (bootstrap admin) and `services/chat_app_import.py`.
- Migration `migrations/versions/0011_account_uid.py` (revision `0011`, down revision `0010`): add the column as nullable, give every existing row `uuid4().hex`, then make it NOT NULL and add a unique index. SQLite needs the batch form; follow how earlier migrations in that folder alter existing tables. The downgrade drops the index and the column.
- Immutable by construction: no code path assigns `account.uid` after creation. A test renames the account and changes its roles and asserts the uid is unchanged.
- The uid is not added to any response schema (`AccountOut` and similar), the session payload, logs or admin pages. It is internal.

### 2. Carrying the uid to `mcp_server`

- `ember_api`:
  - `services/agent_gateway.py`: `Caller` gets `uid: str = ""` (default keeps old constructions valid). The three construction sites pass it: `routes/chats.py:431`, `routes/server_info.py:195`, `routes/user_extensions.py:106`.
  - `services/mcp_session.py`: `identity_headers(username, email, internal_token, uid="")` adds `X-Requester-Uid` when the uid is non-empty. `AgentGateway._headers` passes `caller.uid`.
  - `services/mcp_proxy.py` (`_upstream_headers`), `services/agent_admin.py` and `services/mcp_server_info.py` add `X-Requester-Uid: account.uid` next to the username and email headers.
  - The browser cannot forge it: `McpProxy` forwards only a fixed allow-list of browser headers and sets identity itself.
- `apps/ai_agent`:
  - `src/core/internal_auth.py`: new `REQUESTER_UID_HEADER = "X-Requester-Uid"`; `Requester` gets `uid: str = ""`; `from_headers` reads it; `__bool__` also counts it; `requester_meta()` adds `"uid"` to `_meta.requester`; the helper that builds headers for delegated calls (the function at about lines 96-106) adds the uid header.
- `apps/mcp_server`:
  - `src/services/identity_context.py`: new `REQUESTER_UID_HEADER = "x-requester-uid"`, a `_uid` ContextVar, `current_uid()` (contextvar, else `_meta.requester.uid`), and `IdentityContextMiddleware` sets and resets it with the other two.
  - `src/services/extensions.py` `_requester_meta()` already builds its own `{username, email}` dict, so the uid is NOT forwarded to third-party extensions. Add a test that pins this.

### 3. Memory keyed on the uid (`apps/mcp_server`)

- `src/capabilities/memory/domain.py`: `_owner()` returns `identity_context.current_uid()`. `memory_store` is unchanged, because the owner is an opaque string to it.
- With no uid, every memory tool refuses. Change the store's refusal text (`_NO_OWNER`) to name the cause without promising a "signed-in user": for example "No account identity is known for this request, so memory is unavailable." Update the tests that match on the old text.
- Memory therefore works only for callers that carry a uid: Ember and `chat_cli` (through `ember_api`). A direct MCP client that sends no uid is refused.
- No notes exist in any release yet, so there is no data migration. A note saved by hand during testing under a username becomes unreachable and can be deleted with the database file.

### 4. Deleting an account's notes

- `src/services/memory_store.py`: new `purge_owner(path: Path, owner: str) -> int` deleting the owner's rows from `notes` and `notes_fts` in one transaction and returning the number removed. It refuses an empty owner and does not create the database file when it does not exist.
- `mcp_server` new plain HTTP route `DELETE /memory/owners/{uid}` in a new `src/memory_routes.py`, installed from `run.py` next to `install_upload_routes`. It checks `X-Internal-Token` exactly like `upload_routes._token_valid` (an unset token never validates). It is a route and not a tool, so no model can name a user. Returns `{"purged": <n>}`. Honours the capability toggle: when `memory` is offline it returns 404 and does nothing.
- `ember_api`: a small `services/memory_purger.py` (httpx, derives the `mcp_server` origin from `settings.mcp_server_url`, sends the internal token, short timeout). `routes/admin.py` `delete_account` reads `target.uid` before the deletion, and after `admin_service.delete_account` succeeds it calls the purger. The call is best effort: any failure is logged (without the uid's owner details beyond the username already logged) and never blocks or rolls back the deletion.
- A failed purge leaves orphaned notes. This is harmless for other users because a uid is never reused, but the personal data lingers. State it in the README and the `_TODO.md` follow-ups (retry or a periodic sweep is out of scope).
- With no `INTERNAL_API_TOKEN` configured the route always refuses, as `/upload` does, so purging only works on a token-protected install. State this too.

### 5. Docs

- `memory/README.md` and `STATIC-GUIDELINES.md`: replace the "Ownership is keyed on the username only" rule (rename orphaning, deleted accounts, username reuse) with the uid rule and the purge behaviour and its limits (best effort, needs the token). Keep the rule that privacy depends on `INTERNAL_API_TOKEN` and say that the uid, like the username, is only as trustworthy as the caller. Keep the sentence that forgetting a note does not remove it from past chat transcripts.
- `_TODO.md` item 6 follow-ups: mark follow-up 1 closed (by this change); keep follow-ups 2 to 4; add "retry or sweep of failed purges".
- `apps/mcp_server/src/capabilities/README.md` needs no change. Mention the new route in the `mcp_server` README or wherever `/upload` is documented, if such a list exists.

## Safety

- The uid is an opaque random value, not guessable, and never leaves the internal services. It is a caller-asserted identity like the username; privacy still depends on the internal token on non-loopback hosts.
- The purge route is destructive, so it is token-protected, refuses when no token is configured, cannot be reached through MCP, and takes the owner only from its path.
- The uid is not logged by `mcp_server` or forwarded to extensions.

## Testing

`ember_api` (pytest in `apps/Ember/ember_api`):
- A new account has a 32-character hex uid; two accounts differ; the migration gives existing rows a unique uid (use the migration test pattern in `tests/test_migrations.py`).
- The uid is unchanged after a rename or role change, and does not appear in any account response.
- The identity headers include `X-Requester-Uid` for proxy calls and agent calls; an empty uid sends no header.
- Deleting an account calls the purger once with that account's uid; a purger failure still deletes the account and logs; deleting a protected or own account does not call it.
- The purger sends `DELETE /memory/owners/<uid>` with the token and handles connection errors.

`ai_agent` (pytest in `apps/ai_agent`): `Requester.from_headers` reads the uid; `requester_meta()` contains it; the delegation headers include it; `__bool__` is true with a uid alone.

`mcp_server` (pytest in `apps/mcp_server`):
- `current_uid()` from header and from `_meta.requester`; middleware sets and resets it.
- `extensions._requester_meta()` output has no uid.
- Memory tools refuse without a uid; two uids are isolated; a username-only caller is refused.
- `purge_owner` removes only that owner's rows from both tables and creates no file; the route needs the token, returns the count, leaves other owners alone, and returns 404 when the capability is offline.

Run each project's whole suite before finishing; take fresh baselines first (as of 2026-10-10: `ember_api` 1074 passed, `mcp_server` 746 passed).

## Out of scope

Changing the username, email or any other identity field; sending the uid to ember_web, third-party extensions or logs; retry or sweep of failed purges; moving Emberlings (`str(account.id)`) to the uid; automatic recall; refusing memory when the token is empty on a non-loopback host (still follow-up 3).
