# ember_api

Backend for [ember_web](../ember_web). It owns ember_web's user accounts and
login sessions (its own database, separate from chat_app's) and will proxy
all of ember_web's MCP traffic to `ai_agent` and `mcp_server`, so the
browser never talks to those servers or holds their credentials.

Built with FastAPI + async SQLAlchemy (SQLite via aiosqlite). The auth logic
mirrors chat_app's `services/auth_service.py`: same werkzeug password
hashes, same bootstrap-admin rules, same role/permission tables.

## Status

| Phase | What | State |
|---|---|---|
| 1 | Accounts, bootstrap admin, login/logout/me, sessions | done |
| 2 | Registration with invite codes, email verification (SMTP) | done |
| 3 | MCP proxy to ai_agent / mcp_server with permission checks | done |
| 4 | ember_web switches to ember_api (login pages, `/api` via Vite proxy) | done |
| 5 | Cleanup: drop the old direct CORS on ai_agent / mcp_server | done |

## Requirements

- Python 3.11+ (developed on 3.14)

## Setup and running

`run.bat` creates `.venv_ember_api`, installs the project (editable, with dev
extras) on first run, then starts the server on `EMBER_API_PORT` (default
`8030`). server_launcher lists it as **Ember API**.

Manually:

```bash
py -m venv .venv_ember_api
.venv_ember_api\Scripts\pip install -e ".[dev]"
.venv_ember_api\Scripts\python -m src.run
```

On first start, missing `configs/config_app.json` and
`secrets/secret_bootstrap_admin.env` are copied from their `.example` twins,
`data/ember_api.db` is created, and the bootstrap admin account is made. If
`BOOTSTRAP_ADMIN_PASSWORD` is empty, a random password is printed to the
console once - save it.

Tests:

```bash
.venv_ember_api\Scripts\python -m pytest
```

## API

Every `POST` must send `Content-Type: application/json` (anything else gets
`415`) - with the `SameSite=Strict` cookie this blocks cross-site request
forgery. (Other methods need a CORS preflight cross-site, which ember_api
never grants; the MCP client's session `DELETE` has no body at all.)

| Method | Path | Auth | Returns |
|---|---|---|---|
| `POST` | `/api/auth/login` | - | `{username, password}` -> the account; sets the session cookie. `401` with one generic message on any failure. |
| `POST` | `/api/auth/logout` | cookie | `204`; deletes the session server-side and clears the cookie. |
| `GET` | `/api/auth/me` | cookie | `{id, username, email, email_verified, roles, permissions}` or `401`. |
| `POST` | `/api/auth/register` | - | `{username, email, password, invite_code}` -> `201 {account, verification_email_sent, email_error}`; logs in. `400` bad/expired/used invite, `409` taken username/email, `422` invalid fields. |
| `POST` | `/api/auth/verify-email` | cookie | `{code}` -> the account, now verified. `400` wrong/expired code. |
| `POST` | `/api/auth/verify-email/resend` | cookie | `{sent: true}`; `503` if SMTP failed, `409` if already verified. |
| `POST` | `/api/account/email` | cookie | `{current_password, email}` -> `{account, verification_email_sent, email_error}`. The new email is unverified (permissions off) until its emailed code is entered. `400` wrong password, `409` email taken or bootstrap admin. |
| `POST` | `/api/account/password` | cookie | `{current_password, new_password}` (8+ chars) -> the account. Logs out every other session. `400` wrong password, `409` bootstrap admin (change it in `secret_bootstrap_admin.env`). |
| `POST` | `/api/admin/invites` | `admin.manage` | `{invitee_email?, delivery_method: "manual"\|"email"}` -> `201 {invite, code, email_sent, email_error}`. The code is shown only here. |
| `GET` | `/api/admin/invites` | `admin.manage` | Open (unused, unexpired) invites, without codes. |
| `DELETE` | `/api/admin/invites/{id}` | `admin.manage` | `204`; the code stops working. `409` if already used. |
| `GET` | `/api/admin/accounts` | `admin.manage` | `[{id, username, email, email_verified, is_active, is_protected, created_at, roles: [{id, name}]}]` |
| `PATCH` | `/api/admin/accounts/{id}` | `admin.manage` | Any of `{username, email, is_active}` -> the account. Disabling ends its sessions. `409` taken name/email, protected account, or disabling yourself. |
| `DELETE` | `/api/admin/accounts/{id}` | `admin.manage` | `204`. `409` for the protected account or yourself. |
| `PUT` `DELETE` | `/api/admin/accounts/{id}/roles/{role_id}` | `admin.manage` | Assign / remove a role -> the account. `409` removing from the protected account, or removing your own last `admin.manage`. |
| `POST` | `/api/admin/accounts/{id}/send-verification` | `admin.manage` | `{sent: true}`; `409` already verified, `503` SMTP failed. |
| `GET` | `/api/admin/roles` | `admin.manage` | `[{id, name, description, is_protected, permissions, account_count}]` |
| `POST` | `/api/admin/roles` | `admin.manage` | `{name, description?}` -> `201` role. `409` name taken (case-insensitive). |
| `PATCH` | `/api/admin/roles/{id}` | `admin.manage` | Any of `{name, description}` (`""` clears it) -> the role. Administrator can't be renamed. |
| `DELETE` | `/api/admin/roles/{id}` | `admin.manage` | `204`. `409` for Administrator, or if it's your only source of `admin.manage`. |
| `PUT` `DELETE` | `/api/admin/roles/{id}/permissions/{name}` | `admin.manage` | Grant / revoke -> the role. `404` unknown permission; `409` changing Administrator or revoking your own last `admin.manage`. |
| `GET` | `/api/admin/permissions` | `admin.manage` | `[{name, description}]` - defined in code (`services/permissions.py`), not editable. |
| `GET` | `/api/agents` | `chat.use` | Registered ai_agent instances as `[{id, label}]` - no URLs. |
| `GET` `POST` `DELETE` | `/api/mcp/agents/{agent_id}` | `chat.use` | MCP Streamable HTTP proxy to that agent. `404` if the id isn't in ai_agent's registry. |
| `GET` `POST` `DELETE` | `/api/mcp/server` | `tools.use` | MCP Streamable HTTP proxy to mcp_server. |
| `GET` | `/api/health` | - | `{status: "ok"}` |

## Security model

- **Sessions:** a random 256-bit token in an `HttpOnly`, `SameSite=Strict`
  cookie (`Secure` when `cookie_secure` is on). The database stores only its
  SHA-256, with an expiry (`session_hours`); logout deletes the row.
- **Passwords:** werkzeug hashes, checked on a worker thread so hashing
  never blocks the event loop. Unknown usernames are checked against a dummy
  hash so they take as long as a wrong password.
- **Audit:** every login attempt is stored in `login_attempts` (IP, matched
  account if any, success).
- **Permissions:** `chat.use`, `tools.use`, `admin.manage`
  (`src/services/permissions.py`). The Administrator role always holds all
  of them. New registrations get `default_role` (config, default `Member`:
  `chat.use` + `tools.use`) - unlike chat_app, where new accounts get no
  role. An account with an unverified email holds no permissions at all.
- **Invites and verification codes:** 10 random characters, stored as
  SHA-256, single use, 15-minute expiry (same as chat_app). Registration
  checks the invite before revealing whether a username is taken, and a
  failed registration leaves the invite unused.
- **Email:** `secrets/secret_smtp.env` (same keys as chat_app), sent on a
  worker thread. If sending fails, registration still succeeds and
  `/verify-email/resend` retries; an invite's code is still returned to the
  admin.

- **MCP proxy:** the browser only ever talks to ember_api. Upstream URLs come
  from server-side config (`mcp_server_url`) and ai_agent's own registry file
  (`agents_registry_path`), never from the request. Only
  `content-type`, `accept`, `mcp-session-id`, `mcp-protocol-version` and
  `last-event-id` are forwarded; the browser's cookie and any
  `X-Requester-*` / `X-Internal-Token` it sends are dropped, and ember_api
  adds `X-Requester-Username` / `X-Requester-Email` from the session (plus
  `X-Internal-Token` from `secrets/secret_internal_api.env`, if set).
  Responses, including SSE, are relayed chunk by chunk; the upstream request
  closes when the browser disconnects.
- **What may pass** (`src/services/mcp_policy.py`, bodies up to 1 MB): the
  MCP handshake (`initialize`, `ping`, a few notifications) for everyone;
  on agents only `tools/call` of `ask` / `cancel` / `status`, with `ask`
  limited to `question`, `history`, `request_id`, `enabled_extensions`,
  `caveman` (no `depth`); on mcp_server `tools/list` and any `tools/call`.
  Anything else gets a JSON-RPC error (`403`) and never reaches the server.

**Important:** ai_agent and mcp_server don't check any token on `/mcp`
today, so this only protects them while their ports aren't reachable except
from this machine (keep them on `127.0.0.1`). Also, ai_agent doesn't pass the
user's identity on to the mcp_server tools it calls itself.

Not yet: login rate limiting, device fingerprinting, IP filter (chat_app has
these in `services/security/`).

## Layout

```
configs/   config_app.json(.example)          host, port, db path, session/cookie settings
secrets/   secret_bootstrap_admin.env, secret_smtp.env, secret_internal_api.env (+ .example each)
data/      ember_api.db (runtime, gitignored)
src/
  run.py, app.py, config.py, db.py, deps.py, json_only.py
  models/     Account, Role, Permission, LoginAttempt, AuthSession, InviteCode, EmailVerificationCode
  services/   AuthService, SessionService, OtpService, RegistrationService, EmailSender (SMTP),
              AccountService, AdminService, AgentDirectory, McpPolicy, McpProxy, permissions
  routes/     auth, account, admin, mcp
  utils/      config_loader
tests/
```
