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
| `POST` | `/api/auth/login` | - | `{username, password}` -> the account; sets the session cookie. `401` with one generic message on any failure; `429` + `Retry-After` after too many failures (`security.rate_limit`). |
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
| `GET` | `/api/chats` | `chat.use` | This account's chats, newest first: `[{id, title, agent_id, message_count, created_at, updated_at}]` (no messages). |
| `GET` | `/api/chats/{id}` | `chat.use` | One chat with `messages`. `404` if missing or another account's. |
| `PUT` | `/api/chats/{id}` | `chat.use` | `{title, agent_id, messages: [{role, content}]}` creates or replaces the chat. `413` over 2 MB or 1000 chats. |
| `PATCH` | `/api/chats/{id}` | `chat.use` | `{title}` renames. |
| `DELETE` | `/api/chats/{id}`, `/api/chats` | `chat.use` | `204`; one chat, or all of this account's. |
| `POST` | `/api/chats/import` | `chat.use` | `{chats: [{id, title, agent_id, messages, created_at, updated_at}]}` (times in ms) -> `{imported, skipped}`. Existing ids are skipped, never replaced. |
| `POST` | `/api/chats/{id}/turns` | `chat.use` | `{question, agent_id, caveman?, title?}` -> `202 {chat, sequence}`. Saves the question (creating the chat) and starts the answer **in ember_api**: it finishes, is saved and counts toward the usage limits even if the browser leaves. `404` unknown agent, `409` already answering, `429` usage limit or 3 answers already running. |
| `GET` | `/api/chats/{id}/events?after=N` | `chat.use` | Server-Sent Events of the chat's running (or just finished) answer: a `snapshot` of the text so far when joining late, then `token` / `step_*` / `summarizing` events, last `final` `{message, cancelled}` or `error`. `404` when there's nothing to watch. |
| `POST` | `/api/chats/{id}/cancel` | `chat.use` | `{cancelled}`; ai_agent stops at its next round, keeping what streamed. |
| `POST` | `/api/chats/{id}/summarize` | `chat.use` | `{agent_id?}` -> the chat, its history replaced by a `summary` message plus a `log_attachment` (raw messages, never sent to the agent again). `502` if the agent couldn't; nothing changes then. |
| `POST` | `/api/chats/{id}/clear` | `chat.use` | -> the chat, restarted: everything kept as one `log_attachment`. |
| `POST` | `/api/chats/{id}/messages` | `chat.use` | `{title, messages}` appends (slash-command calls and results), creating the chat if needed. |
| `GET` | `/api/usage?days=30` | `chat.use` | `{six_hour, weekly: {used, limit, reset_at}, report: {total_tokens, turns, chats, summary_tokens, by_agent, daily, ...}}` |
| `GET` | `/api/admin/usage?days=30` | `admin.manage` | Every account's tokens and answers in the period. |
| `GET` | `/api/commands` | `tools.use` | mcp_server's slash commands: `[{capability, name, description, tool_name}]`. |
| `GET` | `/api/commands/help`, `/api/commands/help/{capability}?target=&command=` | `tools.use` | mcp_server's capability help (what `/help` shows). |
| `GET` | `/api/capabilities` | `tools.use` | mcp_server's built-in capabilities: `[{name, label, enabled, tools, resources}]`. |
| `PATCH` | `/api/capabilities/{name}` | `admin.manage` | `{enabled}` turns a capability on/off for every mcp_server client. |
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
  on agents only `tools/call` of `status` - chat turns run inside ember_api
  (`/api/chats/{id}/turns`), so the browser can't bypass the usage limits or
  skip saving an answer; on mcp_server `tools/list`, any `tools/call` and
  `resources/list` / `resources/templates/list` / `resources/read`.
  Anything else gets a JSON-RPC error (`403`) and never reaches the server.

**Important:** ai_agent and mcp_server don't check any token on `/mcp`
today, so this only protects them while their ports aren't reachable except
from this machine (keep them on `127.0.0.1`). Also, ai_agent doesn't pass the
user's identity on to the mcp_server tools it calls itself.

- **Chat turns** (`services/turns.py`, `services/agent_gateway.py`):
  ember_api calls ai_agent's `ask` itself over MCP (the `mcp` SDK), with the
  account's identity headers, and saves the answer. Watchers only subscribe;
  the event buffer stays small because streamed text is kept as one string
  and late joiners get it as a snapshot. At most 3 running answers per
  account. On shutdown a running answer is saved as interrupted.
- **Usage limits** (`services/usage_service.py`, config `usage`): tokens of
  every answer and summary are recorded per agent; a question over the
  6-hour or weekly cap is refused with `429` before anything is saved.
- **Summaries** (`services/summarization.py`, port of chat_app's): manual
  (Summarize) or automatic before a question once the chat's context is 60%
  full. Written only when a usable summary came back.
- **Chat history:** every query is filtered by the logged-in account, and
  chat ids are unique per account, so another user's chat looks exactly like
  a missing one (`404`). Limits: 2 MB per chat, 1000 chats per account.
- **Body size:** requests over 32 MB are refused with `413` before they are
  read (`src/body_limit.py`).
- **Login rate limiting** (`services/rate_limiter.py`, config
  `security.rate_limit`): after 5 failed logins in 15 minutes from one IP or
  for one account, login answers `429` with `Retry-After` until 15 minutes
  after the last failure - checked before the password, so no hashing work
  and no password answer during a lockout. Refused tries aren't recorded.
- **Client IP** (`src/security.py`): the socket address, or the last
  `X-Forwarded-For` hop when the peer is a `trusted_proxies` entry (Vite's
  loopback proxy, which sets it). Used for the audit, rate limit and IP filter.
- **IP filter:** optional allow/deny lists, `403` on every route.
- **Headers:** nosniff, `X-Frame-Options: DENY`, `Referrer-Policy:
  no-referrer`, `default-src 'none'` CSP on every response; HSTS when
  `hsts_max_age` is set. ember_web's `vite preview` sets its own CSP.

Not yet: device fingerprinting (chat_app's `services/security/fingerprint.py`).

## Layout

```
configs/   config_app.json(.example)          host, port, db path, session/cookie settings
secrets/   secret_bootstrap_admin.env, secret_smtp.env, secret_internal_api.env (+ .example each)
data/      ember_api.db (runtime, gitignored)
src/
  run.py, app.py, config.py, db.py, deps.py, json_only.py, security.py, body_limit.py
  models/     Account, Role, Permission, LoginAttempt, AuthSession, InviteCode, EmailVerificationCode, Chat,
              UsageRecord
  services/   AuthService, SessionService, OtpService, RegistrationService, EmailSender (SMTP),
              AccountService, AdminService, AgentDirectory, AgentGateway, ChatService, TurnRegistry,
              UsageService, summarization, McpServerInfo, LoginRateLimiter, McpPolicy, McpProxy,
              permissions
  routes/     auth, account, admin, chats, usage, mcp, server_info
  utils/      config_loader
tests/
```
