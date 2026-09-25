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
