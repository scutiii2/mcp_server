# AuthTemplate

A Flask app template that merges network-level security (rate limiting,
IP filtering, security headers, device fingerprinting) with a single
invite-only account, role/permission-based authorization, and an LLM
chat interface backed by one or more standalone `ai_agent` instances
(see the repo-root `ai_agent/README.md`), with MCP tool-calling.

## Requirements

- Python >= 3.11
- (optional) an MCP server reachable at `MCP_SERVER_URL` — enables slash
  commands and the Capabilities page's "try it" console
- (optional) one or more `ai_agent` instances (repo root) — enables the
  Chat page's LLM Q&A; each configured in `configs/config_agents.json`

## Setup

1. Copy the `.example` files under `secrets/` and `configs/` and
   fill in real values — see [Configuration](#configuration).

2. Run the app:

   ```
   run.bat
   ```

   (from `chat_app/` - creates `.venv_chat` and installs this project
   into it in editable mode on first run, then runs `py -m src.run` -
   see `src/README.md` for `run.py`'s `create_app()`.)

## Configuration

Both loaded once at boot by `src/run.py` (see
[`src/utils/README.md`](src/utils/README.md) for the loader itself):

- **`secrets/*.env`** — credentials, gitignored. Copy each
  `*.env.example` to the matching `*.env`:
  - `secret_app.env` — Flask `SECRET_KEY`.
  - `secret_db.env` — `DATABASE_URL` (SQLite under `data/app.db` if left blank).
  - `secret_bootstrap_admin.env` — the one admin account created on first boot.
  - `secret_smtp.env` — outbound mail for invite emails (optional; invites
    still work without it, just no auto-email delivery).
  - `secret_mcp.env` — `MCP_SERVER_URL`; LLM API keys and model
    choice live in each `ai_agent` instance's own secrets instead (see
    `ai_agent/README.md`).
  - `secret_internal_api.env` — `INTERNAL_API_TOKEN`, shared with
    mcp_server's own `secret_internal_api.env` (same value both sides);
    authenticates internal calls between the two services (see
    `src/README.md`'s `internal_routes.py` entry).
- **`configs/*.json`** — non-secret feature toggles, tracked in git.
  Copy each `.json.example` for the documented shape/defaults:
  - `config_agents.json` — the configured `ai_agent` instances the Chat
    page's provider dropdown can send questions to (`{id, label, url}`
    each; no `.example` twin, see `configs/README.md`).
  - `config_security_fingerprint.json`, `config_security_ip_filter.json`,
    `config_security_rate_limit.json`, `config_security_headers.json` —
    tuning for each stage of the security pipeline (see
    [`src/services/README.md`](src/services/README.md)).

## Project layout

- [`src/pages/`](src/pages/README.md) — one Flask blueprint per page
  (routes/templates/JS/CSS), auto-discovered at boot; links each page's
  own README.
- [`src/services/`](src/services/README.md) — business logic: auth,
  authorization, the security pipeline, admin actions, logging, and the
  LLM chat subsystem (`services/llm/`).
- [`src/models/`](src/models/README.md) — SQLAlchemy models.
- [`src/utils/`](src/utils/README.md) — shared helpers: config/secret
  loading, logging setup, tokens.

## Tests

```
pytest
```
