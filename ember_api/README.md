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
| 2 | Registration with invite codes, email verification (SMTP) | planned |
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
  of them.

Not yet: login rate limiting, device fingerprinting, IP filter (chat_app has
these in `services/security/`).

## Layout

```
configs/   config_app.json(.example)          host, port, db path, session/cookie settings
secrets/   secret_bootstrap_admin.env(.example)
data/      ember_api.db (runtime, gitignored)
src/
  run.py, app.py, config.py, db.py, deps.py, json_only.py
  models/     Account, Role, Permission, LoginAttempt, AuthSession
  services/   AuthService, SessionService, permissions
  routes/     auth
  utils/      config_loader
tests/
```
