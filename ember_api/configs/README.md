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
| `agents_registry_path` | ai_agent's `configs/config_agents.json` (relative to the ember_api folder). ember_api only proxies to agents listed there. |
| `mcp_server_url` | mcp_server's MCP endpoint the proxy forwards to. |
| `security` | Optional block; every key below has the default shown in the example, so it can be left out. |
| `security.trusted_proxies` | Peers allowed to name the real client in `X-Forwarded-For` (last hop only). Default loopback, for Vite's proxy. |
| `security.rate_limit` | `enabled`, `scope` (`ip` / `account` / `both`), `max_attempts` failed logins within `window_seconds` -> login refused (`429` + `Retry-After`) until `lockout_seconds` after the last failure. |
| `security.ip_filter` | `allow_list` / `deny_list` of addresses or CIDRs, checked on every request (`403`). Deny wins; a non-empty allow list refuses everything else. |
| `security.headers` | `enabled` adds nosniff, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer` and a locked-down CSP to every response; `hsts_max_age` > 0 adds HSTS (HTTPS only). |
