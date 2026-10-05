# _TODO.md

Deferred items — not scheduled, revisit when the trigger condition below is met.

## Catalog item descriptions (added 2026-09-14)

Give each item found by the catalog its own description (catalog_service currently lacks per-item descriptions).

## Terminal chat client `chat_cli/` (deferred 2026-09-21)

**Context**: A CLI that behaves like the ember web chat, so conversations can run in a terminal. Design chosen, not yet implemented.

**Approved design**:
- **Architecture**: option B. The CLI talks directly to `ai_agent` / `mcp_server`, reusing the logic of the old `chat_app` `ai_agent_client.py` and `mcp_client.py` (chat_app was removed 2026-10-05; recover them from git history). It does not go through ember_api's HTTP API or login.
- **Location**: new top-level folder `chat_cli/`, laid out per the `root-project-scaffold` skill.
- **Features**: token streaming, tool-call progress display, and an agent picker (same agents as the web UI's Agent dropdown).
- **Suggested libraries**: `rich` for rendering, `prompt_toolkit` for input.

**Known trade-off**: going direct skips ember_api's auth, permissions, usage limits and stored chat history, and duplicates some of that logic. Attachments were not requested and are out of scope.

**Why not built now**: user asked to log it instead of implementing.

**Revisit when**: user wants this built. First check whether the old `ai_agent_client.py` logic can be imported or shared cleanly (for example via `catalog_service`) instead of copied. Decide whether the CLI keeps its own chat history.

## Consolidate secret .env and config .json files (deferred 2026-09-21)

**Context**: Many secret/config files are tiny (most under 300 bytes) and split by habit. Proposal to merge them; not approved for implementation yet.

**Proposed merges**:
- **mcp_server secrets**: merge `secret_app`, `secret_internal_api`, `secret_smtp` into one file. `secret_ssh.env` stays separate (more sensitive).
- **mcp_server configs**: `config_capabilities` + `config_extensions` into `config_mcp_server.json`.
- **ai_agent**: split by concern instead of merged (done): `config_limits`, `config_servers`, `config_tool_selection`, `config_gateways`, `prompts.json`, and the runtime registry at `data/agent_registry.json`.

**Notes**:
- `INTERNAL_API_TOKEN` exists in ember_api, ai_agent and mcp_server and must match. Do not share a file across projects (keeps each project self-contained).

**Work involved**: update every loader, the `.example` twins, `config_validation.py` per-file checkers, tests, READMEs and the scaffold skills (`aiagent-scaffold`, `mcp-capability-scaffold`, `root-project-scaffold`). Add a one-time migration that reads the old files when the new one is missing, so existing real secrets (for example the bootstrap admin password) are not lost. Trade-off: one typo can break several settings in a merged file, and a merged `config_security.json` reloads all four features together.

**Why not built now**: user asked to log it instead of implementing.

**Revisit when**: user wants this built. Start with ember_api or mcp_server.

## Treat mcp_server as a normal MCP, drop the "extensions" proxy (deferred 2026-09-21)

**Note (2026-10-05)**: chat_app was removed. Read "chat_app" below as ember_api (`services/mcp_proxy.py`), which now owns the MCP proxying.

**Context**: Today mcp_server is a hub: external MCPs are added as "extensions" (`mcp_server/configs/config_extensions.json`, `/extensions` endpoint) and their tools arrive proxied as `{ext_id}__{tool}`. `ai_agent` already has a multi-server list (`configs/config_servers.json`, `McpClientRegistry`, tools namespaced `<server>__<tool>`) with mcp_server as the single `main` entry. `chat_app` (`services/mcp_client.py`) connects to mcp_server only and manages extensions through its `/extensions` endpoint. Goal: chat_app lists MCPs directly, mcp_server is just one entry, no proxying.

**Target design**: chat_app and ai_agent connect to N MCP servers side by side (mcp_server, github MCP, others). mcp_server exposes only its own capabilities.

**Plan (two steps, keeps the app working throughout)**:
1. Give chat_app a multi-server registry (reuse or share the ai_agent registry idea) and an MCP list config replacing `MCP_SERVER_URL`. Keep mcp_server's `/extensions` working meanwhile. Capabilities page gets add/remove MCP writing that config; Chat page "extension" toggles become per-MCP toggles (`_tool_is_enabled` filters by server id).
2. Migrate existing extensions to MCP entries, then delete the proxy in mcp_server (`extension_routes.py`, `config_extensions.json`, `/extensions`, extension code in `command_routes.py` / `capability_routes.py`). Keep `/commands`.

**Decision needed**: how chat_app and ai_agent share the MCP list. Options: one shared file (simple, breaks "each project self-contained") or chat_app as source of truth pushing it to ai_agent over the existing `ask` tool call (cleaner).

**Trade-offs**: less code in mcp_server, one concept instead of two, other MCPs stay available when mcp_server is down. External MCPs would skip whatever mcp_server adds on top (`capability_meta` registration, `ai_explain_result`, help entries). Check what `chat_app/src/services/tool_capabilities.py` needs before deciding.

**Size**: medium to large. Touches chat_app services and the Capabilities and Chat pages, ai_agent config plumbing, mcp_server routes, docs, and the scaffold skills that mention extensions. Overlaps with the config-consolidation item above (`config_extensions.json` would be deleted rather than merged).

**Why not built now**: user asked to log it instead of implementing.

**Revisit when**: user wants this built. Start with step 1.

## Traffic tab on the Analytics page (deferred 2026-10-05)

**Context**: The Analytics page (`ember_web/src/views/AnalyticsView.vue`, `ember_api/src/services/log_analytics.py`) charts log entries only. Nothing records network traffic today; the existing data is `log_entries`, `login_attempts` and usage rows. Design approved in chat, not started.

**Approved design**:
- **Capture** (ember_api): a pure-ASGI `TrafficMiddleware` records route template, method, status class and time to first response byte per request (no bodies, query strings, IPs or usernames). Upstream calls (MCP proxy, agent gateway, server tools) go through a `traffic.timed("ai_agent", "ask")` wrapper: target, tool, ok/failed, duration. A `TrafficRecorder` keeps counters in memory and flushes every 30s and on shutdown in a background task, never per request.
- **Storage**: new table `traffic_buckets` (hour, kind `http`|`upstream`, name, status class, latency band <=50/100/250/500/1000/2500/5000/>5000 ms, count, total ms) so p50/p95 work without storing every request. Needs an Alembic migration. Purge older than 90 days at startup, like logs.
- **Read side**: `GET /api/traffic/analytics?range=24h|7d|30d|90d` (totals vs previous period, requests per bucket by status class, p50/p95 per bucket, busiest and slowest routes, upstream calls per target with failure rate). New permission `traffic.view` (Administrator gets it automatically, Member does not).
- **ember_web**: third tab **Overview | Traffic | Entries**: KPI tiles (requests, error rate, p95, upstream failures), requests over time by 2xx/3xx, 4xx, 5xx, latency lines, slowest/busiest route bar lists, upstream per target. Generalise `ActivityChart` to take generic series instead of log kinds and add a small `LineChart`. Nav shows the page for any `logs.*` or `traffic.view`.

**Steps** (one approval each): 1) recorder, middleware, upstream wrapper, table and migration, with tests. 2) read endpoint and permission, tests, README. 3) generalise `ActivityChart`, add `LineChart`. 4) Traffic tab.

**Known trade-offs**: history starts at deploy; up to 30s of counts lost on a crash; times are UTC.

**Why not built now**: user asked to log it instead of implementing.

**Revisit when**: user wants this built. Start with step 1 and list the exact files before editing.
