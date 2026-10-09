# configs

`config_app.json` - server and session settings. Created from
`config_app.json.example` on first run if missing; the real file is
gitignored.

| Key | Meaning |
|---|---|
| `host`, `port` | Where uvicorn listens. `EMBER_API_HOST` / `EMBER_API_PORT` override them. |
| `database_path` | SQLite file, relative to the ember_api folder. |
| `session_cookie_name` | Name of the login cookie. |
| `session_hours` | How long a login lasts. |
| `cookie_secure` | `true` once served over HTTPS (the cookie is then never sent over plain HTTP). |
| `default_role` | Role every newly registered account gets (created with `chat.use` + `tools.use` if missing). |
| `require_email_verification` | `true` (default): an account holds no permissions until its email is verified. `false`: unverified accounts work, registration sends no code, and `/api/auth/me` reports `email_verification_required: false`. |
| `agents_registry_path` | ai_agent's `.data/agent_registry.json` (relative to the ember_api folder). ember_api only proxies to agents listed there. |
| `agents_registry_url` | Optional. ai_agent's `GET /registry`, e.g. `http://10.0.0.5:9100/registry`, for an ai_agent in another directory or on another machine. Wins over `agents_registry_path`; sent with `INTERNAL_API_TOKEN` from `.env`. Fetched with a 3 s timeout and cached 5 s; if it stops answering, the last good list is used for 60 s, then there are no agents. Leave it out for a same-machine setup. |
| `mcp_server_url` | mcp_server's MCP endpoint the proxy forwards to. |
| `security` | Optional block; every key below has the default shown in the example, so it can be left out. |
| `security.trusted_proxies` | Peers allowed to name the real client in `X-Forwarded-For` (last hop only). Default loopback, for Vite's proxy. |
| `security.rate_limit` | `enabled`, `scope` (`ip` / `account` / `both`), `max_attempts` failed logins within `window_seconds` -> login refused (`429` + `Retry-After`) until `lockout_seconds` after the last failure. |
| `security.ip_filter` | `allow_list` / `deny_list` of addresses or CIDRs, checked on every request (`403`). Deny wins; a non-empty allow list refuses everything else. |
| `security.headers` | `enabled` adds nosniff, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer` and a locked-down CSP to every response; `hsts_max_age` > 0 adds HSTS (HTTPS only). |
| `security.fingerprint` | `enabled`: a login from a device the account never used (a hash of the `signals`: `user_agent`, `accept_language`, `ip_subnet` = /24 or /64 network) is written to the activity log - never blocked. Users see and forget their devices on the Account page. |
| `backup` | Optional block: `enabled` (default true), `every_hours` (24) and `keep` (14). ember_api copies its database to `data/backups/<name>-<UTC time>.db` at startup (unless the newest copy is younger than `every_hours`) and then every `every_hours`, keeping the newest `keep`. Uses SQLite's online backup, so it is safe while running, and checks each copy. A failure is written to the Errors log. `python -m scripts.backup_db` makes one now. |
| `usage` | Optional block (defaults as in the example). `six_hour_token_limit` / `weekly_token_limit`: rolling per-account token caps, `0` = unlimited; a new question over a cap gets `429`. `max_context_tokens_per_chat` + `auto_summarize_ratio`: when the last answer used that share of the smaller of the model's context window and this cap, the chat is summarized before the next question is sent. |
