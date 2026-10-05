# .env

The actual credential values that `../configs/*.json` refers to by name
via `${VAR}` placeholders (e.g. `"password": "${SMTP_PASSWORD}"`), plus
the server's own deployment settings. One file, `mcp_server/.env`,
gitignored; `.env.example` is the committed template with every variable
and its explanation.

- **Server** - `MCP_HOST`, `MCP_PORT`. Not secrets in the "must never
  leak" sense, but deployment-specific and kept with the ones that are.
- **Internal API auth** - `INTERNAL_API_TOKEN`, the same value as
  ai_agent's and ember_api's. When set, every request to `/mcp` must carry
  it as `X-Internal-Token` (`services/internal_token.py`, else `401`), and
  `POST /upload` (`upload_routes.py`) always requires it. Blank leaves
  `/mcp` open, which is only safe while the port stays on `127.0.0.1`.
- **SMTP** - `SMTP_PASSWORD`, backing `config_email.json`'s `"password"`,
  and `TEAMS_WEBHOOK_URL`.
- **SSH** - `SSH_HOST_KEY_POLICY`, `SSH_KNOWN_HOSTS`. Applies to every SSH
  connection this server makes (`services/ssh.py`). No credentials.

`run.py` loads `.env` before anything else (`utils/env_file.py`). If it is
missing, it is built once: from the old `.secrets/secret_*.env` files when
they exist (values are copied over; the folder is left for you to delete),
otherwise from `.env.example`. A variable already set in the process
environment wins over the file.

In production, prefer having the service manager, container runtime, or
a secrets manager put these variables in the environment directly
instead of a file on disk - nothing else has to change for that to work.
