# Merged network-gate / login, with temporary gate codes

Status: approved by user, pending implementation plan
Date: 2026-08-17
Scope: `chat_app` only (`mcp_server` has no login concept at all and isn't touched)

## Motivation

`chat_app` is being deployed to a ZimaOS NAS (see `chat_app/zima_host.yaml`),
reachable off-loopback for the first time. Today that requires
`CHAT_AUTH_USER`/`CHAT_AUTH_PASSWORD` — one shared HTTP Basic Auth pair
everyone must know, on top of each person's own account login
(`ADMIN_USERNAME`/`PASSWORD` or a registered account). That's two prompts,
and the outer one isn't tied to any individual — sharing it with friends
means they all know one secret, not their own.

Goals:
- One login prompt for anyone with a real account, not two.
- Each person uses their own credentials end-to-end, not a shared secret.
- Someone without an account yet still needs a way in, without permanently
  weakening the network gate for everyone.
- Preserve the existing "you can't drift into exposing this" property:
  nothing here should make a deployment that has never touched this
  feature suddenly reachable off-loopback.

Non-goals:
- A guaranteed-reliable server-side "log out" (see Known limitation below).
- Changing anything about `mcp_server`, or about `chat_app`'s scope/role
  system itself (`auth/permissions.py`'s `SCOPES`, `ROLE_RANK`, executive
  tier — all untouched).
- Rate-limiting or lockout on login attempts (out of scope; not present
  today either).

## Current behavior (for reference)

`security.py`'s `before_request` chain runs, in order: `check_host`,
`check_auth`, `check_login`, `check_role_permission`, `check_cross_site`.

`check_auth()` today:
```python
def check_auth():
    credentials = configured_credentials()  # CHAT_AUTH_USER/PASSWORD
    if credentials is None:
        if _is_loopback_address(request.remote_addr):
            return None
        return _error("not configured for network access", 403)
    # else: require Basic Auth matching that one pair, unconditionally -
    # even a loopback connection must present it once it's configured.
    ...
```

`check_login()` (separately, later in the chain) redirects anywhere
unauthenticated to `/login`, checking `session` — always mandatory, no
unconfigured fallback.

## Design

### 1. Activation: is the network gate switched on at all?

This is the load-bearing distinction. `ADMIN_USERNAME`/`PASSWORD` (a real
account) is *mandatory* in every deployment — if "a real account exists"
alone were enough to satisfy `check_auth`, every deployment would become
reachable off-loopback automatically, silently breaking the "deliberate
act" property `check_auth`'s own docstring calls out today.

So activation stays a separate question from what satisfies the gate once
active:

**The gate is ON (Basic Auth required for non-loopback traffic) if any of:**
- `CHAT_AUTH_USER`/`CHAT_AUTH_PASSWORD` are configured (today's existing
  signal, unchanged), OR
- at least one currently-valid gate code exists (see §3) — an admin
  minting one is itself a deliberate act, OR
- the new `CHAT_NETWORK_ACCESS_ENABLED` env var is set (any non-empty
  value) — the explicit "I want this reachable via real accounts alone,
  no shared secret" switch, for deployments that never want to configure
  `CHAT_AUTH_USER`/`PASSWORD` at all.

**If the gate is OFF:** behavior is byte-for-byte unchanged from today —
loopback-only, everything else 403s "not configured for network access."

**If the gate is ON, Basic Auth is checked against, in order:**
1. The configured shared pair (`CHAT_AUTH_USER`/`PASSWORD`), if set —
   passes the gate. No session established; this credential isn't tied to
   an identity, same as today.
2. A real account (env admin or any registered user), via the same
   `auth/service.py.check_credentials()` the login form itself already
   uses. On success, **also calls `service.login(username)` immediately**
   — this is the "one prompt" merge. `check_login()` runs right after in
   the same request and sees an already-authenticated session.
3. A currently-valid gate code (§3), checked against the Basic Auth
   *password* field only — whatever username was typed is irrelevant,
   since a gate code isn't tied to any identity. Passes the gate, but
   does **not** establish a session. `check_login()` then redirects to
   `/login` as normal (which links to `/register`) — someone using a gate
   code still needs that one extra step, because they don't have an
   identity yet, not because of an extra Basic Auth prompt.

If none of the three match, `401` with a `WWW-Authenticate` challenge,
same as today.

### 2. Gate codes: storage and lifecycle

A new table in `users.db`, `gate_codes`, mirroring `invite_codes`'
hashing approach (`auth/store.py`'s existing `_hash_invite_code`/
`_invite_code_matches` pattern — HMAC-SHA256, high-entropy generated
codes, not something typed from memory, so no need for `scrypt`'s
memory-hardness):

```sql
CREATE TABLE IF NOT EXISTS gate_codes (
    code_id TEXT PRIMARY KEY,
    salt BLOB NOT NULL,
    code_hash BLOB NOT NULL,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL   -- NOT NULL, unlike invite_codes: a gate
                                -- code without an expiry contradicts
                                -- "temporary rotating" by definition.
)
```

Unlike `invite_codes`, there's no `role` column (a gate code isn't tied to
an account) and no `used_by`/`used_at` (it's multi-use for its whole
window, not consumed on first use — validity is a plain "does any
non-expired row's hash match this code," no claim/race logic needed).

`auth/store.py` additions:
- `create_gate_code(db_path, created_by, ttl_hours: float) -> IssuedGateCode`
  (dataclass mirroring `IssuedInvite`: `code_id`, `code`, `created_by`,
  `created_at`, `expires_at`). `ttl_hours` is required (no `None`/"never"
  option here, unlike `create_invite_code`).
- `list_gate_codes(db_path) -> list[dict]` — only currently-valid
  (non-expired) rows. Opportunistically `DELETE`s expired rows first
  (lazy GC, no cron needed — mirrors no existing precedent exactly, but
  keeps the table from growing unbounded without adding new
  infrastructure).
- `gate_code_is_valid(db_path, code: str) -> bool` — `SELECT 1 FROM
  gate_codes WHERE expires_at > ? AND gate_code_matches(salt, code_hash,
  ?) LIMIT 1`, registering a `gate_code_matches` SQL function via
  `conn.create_function`, exactly like `invite_code_matches` today.
- `delete_gate_code(db_path, code_id)` — manual revocation, mirrors
  `delete_invite_code` (raises `UnknownGateCode` if nothing matched).

`auth/service.py` additions (so `security.py` keeps calling into
`auth.service` only, never `auth.store` directly — matching its existing
import pattern):
- `network_gate_enabled() -> bool` — the three-way OR from §1.
- `gate_code_grants_access(code: str) -> bool` — thin wrapper over
  `store.gate_code_is_valid`.

### 3. Admin UI

A new "Network access" tab in the Account Manager
(`pages/account/template/index.html`), alongside Users/Roles/Invitations
— same table-plus-form pattern as Invitations:
- Create form: TTL only (dropdown: 1 hour / 24 hours / 7 days — no "never
  expires" option, unlike the invite form's dropdown).
- Table of currently-active codes: a copy-once chip for a code just
  generated (same `buildCopyChip`/hash-only-storage pattern as invite
  codes — the plaintext is never recoverable after creation), created-by,
  created-at, expires-at, a Delete/revoke button.

Gated by the same `invites` scope as invite codes (per your answer) — no
new scope. New endpoints: `POST /accounts/api/gate-codes` (admin-facing,
TTL choice), `DELETE /accounts/api/gate-codes/<code_id>`.

A self-service `+ Gate code` sidebar quick-action, mirroring the existing
`+ Invite code` button (`auth.create_invite`'s self-service pattern) —
same `invites`-scope gate, fixed 24-hour TTL, no admin-page visit needed.
New self-service endpoint alongside `auth.create_invite` in
`pages/auth/routes.py`.

### Known limitation: "Log out" is best-effort once merged

Browsers cache Basic Auth credentials and silently resend them on every
subsequent request. Once real-account credentials can satisfy `check_auth`
directly (§1.2), `/logout` clearing the server-side session doesn't
prevent the browser from immediately re-authenticating (and thus
re-establishing a session) on the very next request.

Deliberately not solving this with a realm-cycling trick (challenging
with a different `WWW-Authenticate` realm to force browsers to drop
cached credentials) — it's unreliable across browsers, and a global realm
version would log out every other logged-in user sharing the deployment,
not just the one who clicked Log out. `/logout` keeps clearing the
session (so anything session-scoped is genuinely gone), and a comment/UI
note will say a full logout also needs closing the browser or clearing
saved site credentials.

## Testing

- `check_auth`/`check_login` integration tests via the Flask test client
  (existing style in `tests/test_security.py`/`tests/test_auth_routes.py`):
  gate off by default (byte-for-byte unchanged behavior, regression-tested
  explicitly); gate on via each of the three activation signals
  independently; each of the three credential paths (shared pair, real
  account with auto-login, gate code without auto-login) both succeeding
  and failing; a gate code past its expiry is rejected; a revoked gate
  code is rejected immediately.
- `auth/store.py` unit tests for `create_gate_code`/`list_gate_codes`
  (expired rows excluded and purged)/`gate_code_is_valid`/
  `delete_gate_code`, mirroring `test_auth_store.py`'s existing invite-code
  test shapes.
- Account manager route tests for the new tab's create/list/delete
  endpoints and the sidebar quick-action, mirroring
  `test_account_routes.py`'s existing invite-code tests.

## Open items for the implementation plan (not decided here, deliberately)

- Exact wording of UI copy (button labels, the "Network access" tab name,
  the logout-limitation note's exact text) — implementation detail, not a
  design decision.
- Whether `CHAT_NETWORK_ACCESS_ENABLED` needs documenting in
  `.env.example` and `zima_host.yaml` (yes, it should — flagged here so
  the plan includes updating both, not a new design question).
