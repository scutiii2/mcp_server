# .secrets/

The actual credential values that `../configs/*.json` refers to by name
via `${VAR}` placeholders (e.g. `"password": "${SMTP_PASSWORD}"`).
Gitignored entirely except for the `.example` files and this README -
copy each `*.env.example` to the matching `*.env` and fill in real
values.

- **`secret_app.env`** - `MCP_HOST`, `MCP_PORT`, `MCP_PUBLIC_BASE_URL`.
  Not secrets in the "must never leak" sense, but deployment-specific and
  kept alongside the ones that are, same as `config_extensions.json`
  living next to `config_capabilities.json`.
- **`secret_smtp.env`** - `SMTP_PASSWORD`, backing `config_email.json`'s
  `"password"`.
- **`secret_ssh.env`** - `SSH_HOST_KEY_POLICY`, `SSH_KNOWN_HOSTS`. Applies
  to every SSH connection this server makes (`services/ssh.py`).
- **`secret_internal_api.env`** - `INTERNAL_API_TOKEN`, the same value as
  chat_app's, ai_agent's and ember_api's `secret_internal_api.env`. When
  set, every request to `/mcp` must carry it as `X-Internal-Token`
  (`services/internal_token.py`, else `401`), and `POST /upload`
  (`upload_routes.py`) always requires it. Blank leaves `/mcp` open, which
  is only safe while the port stays on `127.0.0.1`.

All of them are loaded by `run.py` before anything else (every `.env` file
in this folder, not a fixed list of names - a future capability that
needs its own secret adds a file here with no changes to `run.py`).

In production, prefer having the service manager, container runtime, or
a secrets manager put these variables in the environment directly
instead of a file on disk - nothing else has to change for that to work.
