# _TODO.md

Deferred items — not scheduled, revisit when the trigger condition below is met.

## Treat mcp_server as a normal MCP, drop the "extensions" proxy (deferred 2026-09-21, rewritten 2026-10-05)

**Note**: chat_app was removed; ember_api now owns the MCP side the old text called "chat_app".

**Context**: Today mcp_server is a hub. External MCPs are added as "extensions" (`apps/mcp_server/configs/config_extensions.json`, `apps/mcp_server/src/extension_routes.py`, `/extensions` endpoint) and their tools arrive proxied as `{ext_id}__{tool}`. The file currently holds one live entry, `pdf_merger`. ember_api reaches mcp_server through one URL (`mcp_server_url` in `apps/Ember/ember_api/configs/config_app.json`, used by `apps/Ember/ember_api/src/services/mcp_proxy.py`) and passes extensions through (`apps/Ember/ember_api/src/routes/server_info.py`, `apps/Ember/ember_api/src/services/mcp_server_info.py`: list, add, remove). Each chat turn carries `enabled_extensions` from ember_api (`routes/chats.py`, `services/turns.py`, `services/agent_gateway.py`) to ai_agent (`apps/ai_agent/src/server.py`, `agents/agent_config.py`). `ai_agent` already has a multi-server registry (`configs/config_servers.json`, `McpClientRegistry`, tools namespaced `<server>__<tool>`), but it holds only the `main` entry (mcp_server). Goal: mcp_server is just one MCP entry among several, with no proxying.

**Target design**: ember_api and ai_agent connect to N MCP servers side by side (mcp_server, pdf_merger, github MCP, others). mcp_server exposes only its own capabilities.

**Plan (two steps, keeps the app working throughout)**:
1. Give ember_api a multi-server registry (reuse or share the ai_agent registry idea) and an MCP list config replacing the single `mcp_server_url`. Keep mcp_server's `/extensions` working meanwhile. ember_web gets add/remove MCP writing that list; the per-chat "extension" toggles become per-MCP toggles, and `enabled_extensions` becomes a list of server ids.
2. Migrate existing extensions (`pdf_merger`) to MCP entries, then delete the proxy in mcp_server: `extension_routes.py`, `config_extensions.json` and its `.example`, `extensions_config_path` in `src/config.py`, the `extensions` service, and extension mentions in `command_routes.py` / `capability_routes.py`. Keep `/commands`.

**Decision needed**: how ember_api and ai_agent share the MCP list. Options: one shared file (simple, breaks "each project self-contained") or ember_api as source of truth pushing it to ai_agent over the existing ask call (cleaner).

**Trade-offs**: less code in mcp_server, one concept instead of two, other MCPs stay available when mcp_server is down. External MCPs would skip whatever mcp_server adds on top: `capability_meta` registration, `ai_explain_result`, help entries. Check what ember_api's capability and tool listing (`server_info.py`, `mcp_server_info.py`) needs from mcp_server before deciding.

**Size**: medium to large. Touches:
- ember_api: `mcp_proxy.py`, `server_info.py`, `mcp_server_info.py`, `chats.py`, `turns.py`, `agent_gateway.py`, `config.py`, `config_validation.py`, the `ADMIN_MANAGE` permission text in `permissions.py`.
- ember_web: `api/ExtensionsClient.ts`, `api/ChatsClient.ts`, `components/AddExtensionModal.vue`, `components/ChatSettingsMenu.vue`, `stores/chat.ts`, `services/slashCommands.ts`, router pages.
- chat_cli: `src/api.py` (sends `enabled_extensions`).
- ai_agent: `config_servers.json` plumbing and `enabled_extensions` handling.
- mcp_server: routes and config above.
- Docs and the scaffold skills that mention extensions.

**Why not built now**: user asked to log it instead of implementing.

**Revisit when**: user wants this built. Start with step 1.

## More Ember ideas (added 2026-10-06)

Ideas from the "what more can we add" discussion; none designed yet.


**Revisit when**: user picks one; start with brainstorming a design.

## server_manager capability page (added 2026-10-06)

**Context**: Capability pages are built (spec: `docs/superpowers/specs/2026-10-06-capability-pages-design.md`); only `generator` has a `gui/page.json`. `server_manager` (start, stop, restart, list Docker apps on the host; fetch an app's log) is the other built-in capability. Skipped for now.

- **Simple page, no code change**: a `gui/page.json` with an app list `table` (`tool_srv_listApps`) and one form each for start, stop and restart (typed container name; a dropdown needs an `options_url` on the tool's `name` parameter).
- **Proper control panel, needs the page format extended**: row actions on a table (a Start/Stop/Restart button per app), download cards (so the log download works on the page), and several tools in one section (a list that refreshes after an action).
- Note: these tools are not approval-gated; anyone with `tools.use` could stop any app on the host (see the capability README).

**Revisit when**: user wants it built.

## Verify Firecrawl against the live API (added 2026-10-07)

The capability exists at `apps/mcp_server/src/capabilities/firecrawl/`, but its tests mock HTTP calls. Live verification remains:

- Configure `FIRECRAWL_API_KEY` if needed, or use `FIRECRAWL_API_URL` for self-hosted Firecrawl.
- Try `/scrape page` on a real URL, then check map links and crawl `data` against the v2 response shapes.

## Run apps in Docker to test the server_manager tools (added 2026-10-07)

**Context**: The `server_manager` tools (`apps/mcp_server/src/capabilities/server_manager/`) talk to the Docker socket via `docker.from_env()` and act on containers by name. Checked 2026-10-07: their 23 unit tests pass, but they cannot work on the dev PC. There is no Docker (no CLI, no Docker Desktop, no engine pipe), and the apps run as plain Windows processes through `server_launcher`, so `list` would show no app containers. On ZimaOS, `apps/mcp_server/zima_host.yaml` runs `mcp_server` as a container but does not mount `/var/run/docker.sock`, so the tools fail there too.

**Plan**:
- **Dockerfiles**: one per app; none exist. Python apps (`mcp_server`, `ai_agent`, `ember_api`, `pdf_merger`, `video_downloader`, `catalog_service`) on `python:3.13-slim` plus `pip install .`. Web apps (`ember_web`, `pdf_merger_web`, `video_downloader_web`) need a Node build stage, then nginx or the Vite dev server.
- **Compose file**: one `docker-compose.yml` with a fixed `container_name` per app (these are the names `/server start <name>` uses).
- **Networking**: configs hard-code `127.0.0.1` (`ai_agent/configs/config_servers.json`, `ember_api/configs/config_app.json` `mcp_server_url`, `mcp_server/configs/config_extensions.json`). In containers these become service names such as `http://mcp_server:8010/mcp`, and each service must bind `0.0.0.0`. Use env overrides or a docker config variant.
- **Docker socket**: mount `/var/run/docker.sock` into the `mcp_server` container. This gives it root-equivalent control of the host. Dev PC needs Docker Desktop with WSL2.
- **Data**: volumes for `ember_api/data` and `ai_agent/.data`.
- **Self-stop**: `/server stop mcp-server` kills the server running the tool; expected, but it cannot be restarted from the same chat.
- `server_launcher` stays as the local-process manager; containers are a second way to run the apps.

**Smallest first step**: compose with `mcp_server` plus one app (for example `pdf_merger`), enough to test `list`, `restart` and `logs`.

**SMTP credential rotation (repository cleaned 2026-10-09)**: `zima_host.yaml` now loads credentials from the deployment's gitignored `.env`; the inline password is removed. Still required: revoke the exposed password at the mail provider, put a replacement `SMTP_PASSWORD` in the deployment `.env`, recreate the container and verify email delivery. The old password remains in Git history until revoked.

**Revisit when**: user wants it built (Docker Desktop installed first).

## Verify specialist agents and consider follow-up features (added 2026-10-07)

The agents are implemented. These manual checks remain unverified:

- **Email Assistant** (`email-assistant`, port 9112): paste an email and check its summary, triage and draft reply.
- **Data Analyst** (`data-analyst`, port 9113): attach a CSV, ask for a total and a top 5, and check the results.
- **Scheduler** (`scheduler`, port 9114): watch a local URL that is down, bring it up, and check that the requester receives one email and the Watchers page records the outcome. Configure `config_email.json` and `SMTP_PASSWORD` if needed.
- **Ember routing**: check delegation across the specialist roster with Laya routing enabled.

Optional follow-up features, not implemented:

- **Email**: read-only IMAP mailbox access, then saved drafts. Decide credentials in `.env` and treat mail content as untrusted. The existing email service provides SMTP sending for watchers.
- **Data analysis**: sandboxed code execution, `.xls` support, charts and downloadable results.
- **Scheduling**: recurring monitoring, alerts on every change, log/file patterns, other recipients (requires an allowed-domains rule), SMS or push.

**Revisit when**: user wants the manual checks run or picks a follow-up feature.

## Close the agentic-harness gaps in ai_agent (added 2026-10-09)

**Context**: Review on 2026-10-09 found `apps/ai_agent` is a tool-calling agent runtime with delegation and approvals (tool loop in `src/llm/anthropic_provider.py` and `openai_provider.py`, `delegate_to_agent`, `approvals.review`, `ask_user`), not yet a full agentic harness. Missing pieces, easiest first. Do them together as one batch.

1. **Budget and stuck-loop guard — done** (`160df65`): shared guard in both provider loops; per-agent `llm.max_turn_tokens` and `llm.max_turn_seconds` beside `max_tool_rounds` (defaults 100,000 tokens / 300 seconds). Stops before a third consecutive identical tool call; intervening work resets the repetition count. Tokens are checked at response boundaries, so one response can exceed the cap.
2. **Cancel through delegation — done** (`1d8f203`): unique child request IDs linked to the parent; forwards Stop to each peer's MCP `cancel` tool. Deadline cancellation survives parent cleanup and late delegate startup; late worker events are dropped. Cancellation remains cooperative for tools already running.
3. **Plan/todo tool — done** (`5069200`): local `update_plan` tool with per-turn pending / in_progress / done checklists, offered by both providers. Live `plan_update` snapshots retain delegated-agent identity; small Ember API pass-through, reconnect snapshots, and Ember web panel make them visible.
4. **Tool-activity persistence across turns**: `validate_history` (`src/core/chat_history.py`) accepts text only, so earlier tool calls are lost. Store calls and results in `ember_api` in a provider-neutral format, send them back, relax the validator. Medium.
5. **Compaction/summarizing**: replace `token_limits.trim_history_to_fit` (drops old messages) with a summary; needs an extra LLM call, a trigger rule and a place to keep summaries. Works better after item 4. Medium to hard.
6. **Persistent memory**: facts that outlive a chat; store, read/write tools, per-user scoping, forget rules. Retrieval quality is the hard part. Hard.
7. **Sandboxed workspace (files and shell)**: isolated per-user directory and a limited command runner, fitted to the approval flow. Real security risk. Best as a new `mcp_server` capability, not inside `ai_agent`. Hardest.

Items 1 to 3 are cheap; 4 and 5 fit together; 6 and 7 are separate projects.

**Revisit when**: user wants to start; brainstorm a design, then take 1 to 3 first.

## Build mini_games: chess and Tetris against a Laya-assisted bot (added 2026-10-09)

**Context**: Player fights a bot in chess or Tetris inside Ember, at no billing cost. Designed 2026-10-09 as three specs; only spec 1 is written and planned. Laya reads text only (512-token window), so a conventional engine proposes and scores moves and Laya picks among the top candidates, with the engine's best move as fallback. Standalone project `apps/mini_games/` (port 8060), no LLM calls.

- **Spec 1, backend** (designed, planned, not built): `docs/superpowers/specs/2026-10-09-mini-games-backend-design.md`, plan `docs/superpowers/plans/2026-10-09-mini-games-backend.md` (12 tasks; its code was run against 144 passing tests in a scratch copy). Task 12 needs the real `laya` package and decides per game whether Laya or `variety` is the default picker.
- **Spec 2, not written**: `ember_api` proxy routes for mini_games and an `ember_web` `/mini_games` page with the boards. The Tetris gravity loop runs in the browser.
- **Spec 3, not written**: mcp_server extension entry (`config_extensions.json`) with tools to start and play a game from chat, a chat "Play" card, and a floating modal that opens from `/mini_games`. Overturns nothing: it reuses the same backend, and `ember` stays the only entry agent.

**Open points**: Tetris garbage lines, session persistence across restarts, and more games are out of scope for v1.

**Revisit when**: user picks execution for the plan (subagent-driven or inline), then write spec 2.
