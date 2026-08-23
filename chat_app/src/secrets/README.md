# src/secrets/

Credentials, gitignored except for the `.example` files and this
README. Copy each `*.env.example` to the matching `*.env` and fill in
real values. Each is loaded into its own isolated dict via
`utils/config_loader.py`'s `load_env_secrets()` (`dotenv_values()`,
never merged wholesale into `os.environ`), so one topic's secrets never
leak into another's - `secret_llm.env`'s keys are the one deliberate
exception (`run.py` merges them into `os.environ` with `setdefault`,
since `services/llm/settings.py` reads plain env vars).

- **`secret_app.env`** - Flask `SECRET_KEY`.
- **`secret_db.env`** - `DATABASE_URL` (SQLite under `../data/app.db` if
  left blank).
- **`secret_bootstrap_admin.env`** - the one admin account created on
  first boot (`services/auth_service.ensure_bootstrap_admin`).
- **`secret_smtp.env`** - outbound mail for invite emails. Optional -
  invites still work without it, just no auto-email delivery.
- **`secret_llm.env`** - `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` (blank
  disables that provider), model names, `MCP_SERVER_URL`,
  `OLLAMA_BASE_URL`.

## Adding a new secret file

Name it `secret_<topic>.env`, add the matching `.example`, and load it
with `load_env_secrets(BASE_DIR / "secrets" / "secret_<topic>.env")` at
the point that needs it (`run.py` for anything read at boot, or inline
in whichever service owns that topic) - don't add a new topic's keys to
an existing file, the one-file-per-topic split is what keeps one
secret's blast radius from covering another's.
