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
| 3 | MCP proxy to ai_agent / mcp_server with permission checks | planned |

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

All state-changing requests must send `Content-Type: application/json`
(anything else gets `415`) - with the `SameSite=Strict` cookie this blocks
cross-site request forgery.

| Method | Path | Auth | Returns |
|---|---|---|---|
| `POST` | `/api/auth/login` | - | `{username, password}` -> the account; sets the session cookie. `401` with one generic message on any failure. |
| `POST` | `/api/auth/logout` | cookie | `204`; deletes the session server-side and clears the cookie. |
| `GET` | `/api/auth/me` | cookie | `{id, username, email, email_verified, roles, permissions}` or `401`. |
| `POST` | `/api/auth/register` | - | `{username, email, password, invite_code}` -> `201 {account, verification_email_sent, email_error}`; logs in. `400` bad/expired/used invite, `409` taken username/email, `422` invalid fields. |
| `POST` | `/api/auth/verify-email` | cookie | `{code}` -> the account, now verified. `400` wrong/expired code. |
| `POST` | `/api/auth/verify-email/resend` | cookie | `{sent: true}`; `503` if SMTP failed, `409` if already verified. |
| `POST` | `/api/admin/invites` | `admin.manage` | `{invitee_email?, delivery_method: "manual"\|"email"}` -> `201 {invite, code, email_sent, email_error}`. The code is shown only here. |
| `GET` | `/api/admin/invites` | `admin.manage` | Open (unused, unexpired) invites, without codes. |
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

Not yet: login rate limiting, device fingerprinting, IP filter (chat_app has
these in `services/security/`).

## Layout

```
configs/   config_app.json(.example)          host, port, db path, session/cookie settings
secrets/   secret_bootstrap_admin.env(.example), secret_smtp.env(.example)
data/      ember_api.db (runtime, gitignored)
src/
  run.py, app.py, config.py, db.py, deps.py, json_only.py
  models/     Account, Role, Permission, LoginAttempt, AuthSession, InviteCode, EmailVerificationCode
  services/   AuthService, SessionService, OtpService, RegistrationService, EmailSender (SMTP), permissions
  routes/     auth, admin
  utils/      config_loader
tests/
```
