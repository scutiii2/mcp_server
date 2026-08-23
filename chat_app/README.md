# AuthTemplate

A Flask app template that merges network-level security (rate limiting,
IP filtering, security headers, device fingerprinting) with a single
invite-only account, role/permission-based authorization, and an LLM
chat interface (OpenAI, Claude, and local Ollama models, with MCP
tool-calling).

## Requirements

- Python >= 3.11
- (optional) an MCP server reachable at `MCP_SERVER_URL` — enables tool
  calling from the Chat/Capabilities pages
- (optional) [Ollama](https://ollama.com) running locally — enables the
  local-model chat provider

## Setup

1. From `chat_app/`, install dependencies:

   ```
   pip install -e ".[dev]"
   ```

2. Copy the `.example` files under `src/secrets/` and `src/configs/` and
   fill in real values — see [Configuration](#configuration).

3. Run the app:

   ```
   run.bat
   ```

   (`run.bat` activates `.venv` and runs `py -m run`; the editable
   install puts `src/` on `sys.path` so `run` resolves to `src/run.py`.)

## Configuration

Both loaded once at boot by `src/run.py` (see
[`src/utils/README.md`](src/utils/README.md) for the loader itself):

- **`src/secrets/*.env`** — credentials, gitignored. Copy each
  `*.env.example` to the matching `*.env`:
  - `secret_app.env` — Flask `SECRET_KEY`.
  - `secret_db.env` — `DATABASE_URL` (SQLite under `data/app.db` if left blank).
  - `secret_bootstrap_admin.env` — the one admin account created on first boot.
  - `secret_smtp.env` — outbound mail for invite emails (optional; invites
    still work without it, just no auto-email delivery).
  - `secret_llm.env` — `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` (blank
    disables that provider), model names, `MCP_SERVER_URL`, `OLLAMA_BASE_URL`.
- **`src/configs/*.json`** — non-secret feature toggles, tracked in git.
  Copy each `.json.example` for the documented shape/defaults:
  - `config_chat.json` — `providers.ollama.models`: the locally-pulled
    Ollama models to offer in the chat provider dropdown (empty by
    default — Ollama shows no models until some are listed here).
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
