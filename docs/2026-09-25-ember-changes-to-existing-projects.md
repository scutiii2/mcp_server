# Changes to chat_app, ai_agent, mcp_server and server_launcher for ember

**Date:** 2026-09-25 · **Branch:** `home` · **Range:** `4d257f8..85142a4`

Building the two new root projects - `ember_web/` (Vue 3 + TypeScript
frontend) and `ember_api/` (FastAPI backend that owns ember's accounts and
proxies MCP) - touched the existing projects only lightly. This note records
what changed in them, what was added and later removed again, and why, so
nobody has to reconstruct it from the commit history.

## Summary

| Project | Net change | Behavior change for existing users |
|---|---|---|
| chat_app | none | none |
| ai_agent | `main()` starts the MCP app via `uvicorn` explicitly | none (same app, host, port, log level) |
| mcp_server | none (CORS added, then removed) | none |
| server_launcher | detects and runs npm projects | new "Ember Web" entry; Python projects unchanged |

Net diff for these four projects: 7 files, +76 / -12 lines
(`git diff --stat 4d257f8..HEAD -- chat_app ai_agent mcp_server server_launcher`).

## How the architecture got here

1. **First design:** the ember_web browser called ai_agent and mcp_server
   directly over MCP. That needed CORS on both servers (`be5b686`) and a
   way for the browser to discover agents (`list_agents` tool, `2817177`).
2. **Auth decision:** instead of reusing chat_app's login, ember got its own
   backend, **ember_api**, with its own accounts, and all MCP traffic now
   goes browser -> ember_api -> ai_agent / mcp_server, the same
   server-to-server pattern chat_app uses.
3. **Cleanup** (`85142a4`): with no browser calling ai_agent or mcp_server
   anymore, the CORS middleware and the `list_agents` tool were removed.

## chat_app

**No changes.** chat_app's code, config and database are untouched.

- ember_api *mirrors* chat_app's auth logic (werkzeug password hashes,
  bootstrap admin, invite codes, email-verification codes, role/permission
  tables) but in its own database (`ember_api/data/ember_api.db`). Accounts
  are **not shared**: a chat_app user can't log into ember_web with the same
  credentials unless an account is created there too.
- Because the logic is copied, a security fix in
  `chat_app/src/services/auth_service.py` or `otp_service.py` may need the
  same fix in `ember_api/src/services/`.
- `ember_api/secrets/secret_smtp.env` and `secret_internal_api.env` use the
  same keys as chat_app's; the internal token should have the same value
  everywhere if it's used.

## ai_agent

**File:** `ai_agent/src/server.py`

**Net change** - `main()` no longer calls `mcp.run(transport="streamable-http")`;
it builds the same Starlette app and runs it itself:

```python
app = mcp.streamable_http_app()
uvicorn.run(app, host=HOST, port=PORT, log_level=mcp.settings.log_level.lower())
```

This is exactly what the MCP SDK's `run_streamable_http_async()` does
internally (checked in the installed SDK), so chat_app and every other
caller see no difference. It stays this way so middleware can be added in
one place later (e.g. an `X-Internal-Token` check).

**Added, then removed:**

| What | Added | Removed | Why removed |
|---|---|---|---|
| `CORSMiddleware` allowing `http://127.0.0.1:5173` / `http://localhost:5173`, exposing `Mcp-Session-Id` | `be5b686` | `85142a4` | the browser no longer calls ai_agent |
| `list_agents()` MCP tool returning the agent registry | `2817177` | `85142a4` | ember_api reads `configs/config_agents.json` itself; chat_app never used the tool |

**Still relevant to ember:** ember_api reads ai_agent's registry file
(`ai_agent/configs/config_agents.json`, path configurable as
`agents_registry_path` in `ember_api/configs/config_app.json`) and only
proxies to agents listed there. Through the proxy, a browser may call only
`ask`, `cancel` and `status`, and `ask` without the `depth` argument (see
`ember_api/src/services/mcp_policy.py`).

## mcp_server

**File:** `mcp_server/src/run.py`

**Net change: none.** `CORSMiddleware` (same settings as ai_agent's) was
added after `IdentityContextMiddleware` in `be5b686` and removed in
`85142a4`.

**Still relevant to ember:** ember_api's proxy calls mcp_server's `/mcp`
with `X-Requester-Username` / `X-Requester-Email` set from the logged-in
ember account (headers the browser sends are dropped), which
`IdentityContextMiddleware` reads exactly as it does for chat_app. It also
sends `X-Internal-Token` when `ember_api/secrets/secret_internal_api.env`
sets one.

## server_launcher

**Commit:** `6a8f900` · **Files:** `src/models.py`, `src/config.py`,
`src/discovery.py`, `src/processes.py`, `src/instance.py`, `src/window.py`

The launcher previously understood only Python projects (a `run.bat` with
`call .venv_<name>\Scripts\activate` and `py -m <module>`). It now also runs
**npm projects**, which is how ember_web shows up as "Ember Web".
(ember_api is a normal Python project and needed no launcher change.)

| File | Change |
|---|---|
| `models.py` | `ServerTemplate` gains `runtime` (`"python"` or `"node"`); `venv_python` may be `None`; `module` holds the npm script name for node projects; new `command_summary` property for the UI. |
| `config.py` | New `_NPM_SCRIPT_RE` matching `npm run <script>`. |
| `discovery.py` | If the Python patterns don't match, a `run.bat` with `npm run <script>` next to a `package.json` becomes a `"node"` template. Port/label/description parsing is shared. |
| `processes.py` | `_ensure_runtime()` dispatches to the existing `_ensure_venv()` or the new `_ensure_node_modules()` (runs `npm install` when `node_modules` is missing). `_build_launch_args()` runs `npm.cmd run <script> -- <extra args>` for node projects and sets `NO_COLOR=1` so Vite's log is plain text in the log pane. |
| `instance.py` | Calls `_ensure_runtime()` instead of `_ensure_venv()`. |
| `window.py` | Detail pane shows `template.command_summary` instead of building the python command string itself. |

Stopping is unchanged: `_kill_pid_tree()` already uses `taskkill /F /T`,
which also ends the `node` child that npm starts.

**Verified:** the launcher's 19 existing tests pass; discovery lists all
projects with the right runtime/port; ember_web was started and stopped
through `_spawn()` / `_kill_pid_tree()` on a test port.

## Commits

| Commit | Subject | Touches |
|---|---|---|
| `be5b686` | Add CORS to ai_agent and mcp_server for browser clients | ai_agent, mcp_server |
| `6a8f900` | Let server_launcher detect and run npm projects | server_launcher |
| `2817177` | Let ember_web pick which ai_agent to chat with | ai_agent (`list_agents`), ember_web |
| `85142a4` | Drop direct-browser CORS and list_agents now that ember_api proxies | ai_agent, mcp_server, ember_api README |

Everything else on the branch in this range is ember_web / ember_api only.

## Operating notes

- **Ports:** mcp_server 8010, ai_agent 9100 (+ further instances, e.g.
  9102), chat_app 5000, ember_api 8030, ember_web 5173.
- **Internal token on `/mcp`** (since 2026-09-26, see below): ai_agent and
  mcp_server reject `/mcp` requests without `X-Internal-Token` once
  `INTERNAL_API_TOKEN` is set. Use one value in all four
  `secret_internal_api.env` files (mcp_server, ai_agent, chat_app,
  ember_api). With it blank, keep both servers on `127.0.0.1`.
- After pulling these changes, restart ai_agent and mcp_server once.

## 2026-09-26: internal token and user identity

Both former open follow-ups are done.

| Project | Change |
|---|---|
| mcp_server | `services/internal_token.py`: pure-ASGI middleware, `401` on `/mcp` without the right `X-Internal-Token` (constant-time) when `INTERNAL_API_TOKEN` is set; added in `run.py`, which also prints whether it's on. `identity_context.py`: `current_username()` / `current_email()` fall back to the tool call's `_meta.requester` when no identity header came. `extensions.py` logs `tool call <name> by <user>`. |
| ai_agent | `src/internal_auth.py`: the token (from new `secrets/secret_internal_api.env`, seeded from its `.example`), the same middleware on `/mcp`, and the asking user. `ask()` reads `X-Requester-*` from the request and binds it for the turn; `mcp_upstream.call_tool` sends it as `_meta.requester` (the one upstream session serves every user); the upstream session and `delegate_to_agent` sessions carry the token (`registry` / `transports` gained `extra_headers`, `call_tool` gained `meta`). |
| chat_app | `src/services/internal_auth.py`'s `mcp_headers()` adds the token to every MCP session to mcp_server and ai_agent (`mcp_client.py`, `ai_agent_client.py`); `run.py` copies the token into the environment. |
| ember_api | nothing in code (it already sent the token); its `secret_internal_api.env` now needs the value. |

Restart mcp_server, ai_agent, chat_app and ember_api after setting the
token; a caller without it gets `401` from `/mcp`.
