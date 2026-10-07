# _TODO.md

Deferred items — not scheduled, revisit when the trigger condition below is met.

## Merge the small configs; clean up legacy secrets (deferred 2026-09-21, rewritten 2026-10-07)

**Context**: Secrets are done: every project (ai_agent, mcp_server, ember_api) now has one `.env` plus `.env.example`. What is left is the legacy cleanup and merging the small config files. Catalog item descriptions (older item) were already built and were removed from this file on 2026-10-07.

**Secrets (done, checked 2026-10-07)**
- **mcp_server**: `.secrets/secret_*.env` merged into `apps/mcp_server/.env`; `run.py` builds `.env` from an old `.secrets/` folder on first start (`src/utils/env_file.py`). The 4 legacy `.secrets/secret_*.env` files were deleted 2026-10-07; the empty `.secrets/` folder is left.
- **ember_api**: merged into `apps/ember_api/.env` with a `.env.example`; the legacy `secrets/` folder is gone. Nothing left.
- **ai_agent**: stale comments in `.env.example` are fixed.
- `INTERNAL_API_TOKEN` stays in each project's own `.env` and must match across ember_api, ai_agent and mcp_server. Do not share one file across projects (each project stays self-contained).

**Configs: stay in `configs/`; which ones can merge**
- **mcp_server** (decided 2026-10-05: no merge): `config_capabilities.json` (42 B) and `config_extensions.json` stay separate. Merging needs wrapper keys and rewrites of the loaders and savers in `app_config.py` plus four test files, and `config_extensions.json` is deleted by the extensions-proxy item below, leaving `config_capabilities.json` alone. Both savers are synchronous read-modify-write, so one process cannot interleave them (no shared writer needed). `config_email.json` (example only, gitignored by path unlike the other two) looks dead: `Settings.email_config_path` has no caller in `src/`, `load_email_config` is used only by tests, and nothing loads the `EmailConfig` that `services/email.py` takes. Check `watcher` / `email` before removing it.
- **ai_agent**: `config_limits.json` and `config_tool_selection.json` are both small runtime tuning (token limits, tool shortlist) and can merge into one file (name to decide, for example `config_tuning.json`).
- **Keep separate**: `apps/ai_agent/configs/config_gateways.json` (3 KB, provider endpoints), `prompts.json` (persona text), `config_servers.json` (the MCP server list, reworked by the extensions item below), and `apps/ai_agent/data/agent_registry.json` (runtime registry, lives in `data/`, not a config).
- **Nothing to merge**: ember_api already has the single `configs/config_app.json`; `apps/chat_cli/configs/` has one file. `apps/catalog_service/configs/` not checked.

**Work involved (configs only)**:
- Merge `config_limits.json` and `config_tool_selection.json` in ai_agent: update the loaders, the `.example` twins, `.gitignore` entries and any first-run copy step.
- Update `apps/ember_api/src/services/config_validation.py` per-file checkers, tests, READMEs and the scaffold skills. Edit the skills under `.agents/skills/`, then sync to `.claude/skills/`; the pre-commit check enforces the match.

**Trade-off**: one typo in a merged file can break several settings at once.

**Why not built now**: small gain; not approved.

**Revisit when**: user wants this built. Only the ai_agent config merge is left.

## Treat mcp_server as a normal MCP, drop the "extensions" proxy (deferred 2026-09-21, rewritten 2026-10-05)

**Note**: chat_app was removed; ember_api now owns the MCP side the old text called "chat_app".

**Context**: Today mcp_server is a hub. External MCPs are added as "extensions" (`apps/mcp_server/configs/config_extensions.json`, `apps/mcp_server/src/extension_routes.py`, `/extensions` endpoint) and their tools arrive proxied as `{ext_id}__{tool}`. The file currently holds one live entry, `pdf_merger`. ember_api reaches mcp_server through one URL (`mcp_server_url` in `apps/ember_api/configs/config_app.json`, used by `apps/ember_api/src/services/mcp_proxy.py`) and passes extensions through (`apps/ember_api/src/routes/server_info.py`, `apps/ember_api/src/services/mcp_server_info.py`: list, add, remove). Each chat turn carries `enabled_extensions` from ember_api (`routes/chats.py`, `services/turns.py`, `services/agent_gateway.py`) to ai_agent (`apps/ai_agent/src/server.py`, `agents/agent_config.py`). `ai_agent` already has a multi-server registry (`configs/config_servers.json`, `McpClientRegistry`, tools namespaced `<server>__<tool>`), but it holds only the `main` entry (mcp_server). Goal: mcp_server is just one MCP entry among several, with no proxying.

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

Overlaps with the config-consolidation item above: `config_extensions.json` would be deleted rather than merged.

**Why not built now**: user asked to log it instead of implementing.

**Revisit when**: user wants this built. Start with step 1.

## Chat folders: reordering and folder names in search (added 2026-10-06)

**Context**: Chat folders, pins and drag and drop are merged to `main` (spec: `docs/superpowers/specs/2026-10-05-chat-folders-pins-design.md`). Two parts were left out on purpose; each needs its own design.

- **Folder reordering UI**: the API already supports it (`PATCH /api/chat-folders/{id}` with `position`, and `foldersClient.reorder` / the folders store `reorder` exist). Missing: a way to reorder in the sidebar (drag a folder header, or Move up / Move down in the folder "..." menu).
- **Folder names in search hits**: search results are a flat list and do not say which folder a chat is in. Show the folder name on each hit (needs `folder_id` in the search hit rows from ember_api, or a lookup in the store).

**Revisit when**: user wants these built.

## More Ember ideas (added 2026-10-06)

Ideas from the "what more can we add" discussion; none designed yet.

- **Attachments with the pdf-assistant**: attachments exist (`ember_web/src/api/AttachmentsClient.ts`, `ember_api/src/routes/attachments.py`) as of 2026-10-07; unchecked whether the pdf-assistant reads them. Verify, then drop this bullet.
- **Per-user quotas**: limit usage per account (builds on the existing usage gauges).
- **Notifications when a long answer finishes**: for example a browser notification or a title badge when the tab is in the background.
- **Mobile and PWA support**: installable app, touch layout, offline shell.

**Revisit when**: user picks one; start with brainstorming a design.

## server_manager capability page (added 2026-10-06)

**Context**: Capability pages are built (spec: `docs/superpowers/specs/2026-10-06-capability-pages-design.md`); only `generator` has a `gui/page.json`. `server_manager` (start, stop, restart, list Docker apps on the host; fetch an app's log) is the other built-in capability. Skipped for now.

- **Simple page, no code change**: a `gui/page.json` with an app list `table` (`tool_srv_listApps`) and one form each for start, stop and restart (typed container name; a dropdown needs an `options_url` on the tool's `name` parameter).
- **Proper control panel, needs the page format extended**: row actions on a table (a Start/Stop/Restart button per app), download cards (so the log download works on the page), and several tools in one section (a list that refreshes after an action).
- Note: these tools are not approval-gated; anyone with `tools.use` could stop any app on the host (see the capability README).

**Revisit when**: user wants it built.

## Firecrawl web scraping (added 2026-10-07)

**Status**: built 2026-10-07 as the `firecrawl` capability in mcp_server (id `scrape`, label "Web Scraping"; `apps/mcp_server/src/capabilities/firecrawl/`). Untested against the real Firecrawl API: unit tests mock the HTTP calls.

**Decided**: a capability that calls the Firecrawl REST API (`/v2/scrape`, `/v2/map`, `/v2/crawl`), the same endpoints https://github.com/firecrawl/firecrawl-mcp-server wraps; not an extension, so it does not depend on the extensions-proxy item above. Three tools: `/scrape page`, `/scrape map`, `/scrape crawl` (limit 25 pages, waits up to 60 s). Kept beside `web_research` (Tavily): Tavily for search and quick reads, Firecrawl for JavaScript-heavy pages and whole sites. Config: `FIRECRAWL_API_KEY` and optional `FIRECRAWL_API_URL` (self-hosted) in `apps/mcp_server/.env`.

**Left out on purpose**: Firecrawl's search (`web_research` does it) and its LLM-based extract.

**Still to do**: add `FIRECRAWL_API_KEY` to the real `.env`, then try `/scrape page` on a real URL. Check the v2 response shapes (map links, crawl `data`) against the live API.

## Run apps in Docker to test the server_manager tools (added 2026-10-07)

**Context**: The `server_manager` tools (`apps/mcp_server/src/capabilities/server_manager/`) talk to the Docker socket via `docker.from_env()` and act on containers by name. Checked 2026-10-07: their 23 unit tests pass, but they cannot work on the dev PC. There is no Docker (no CLI, no Docker Desktop, no engine pipe), and the apps run as plain Windows processes through `server_launcher`, so `list` would show no app containers. On ZimaOS, `apps/mcp_server/zima_host.yaml` runs `mcp_server` as a container but does not mount `/var/run/docker.sock`, so the tools fail there too.

**Plan**:
- **Dockerfiles**: one per app; none exist. Python apps (`mcp_server`, `ai_agent`, `ember_api`, `pdf_merger`, `video_downloader`, `catalog_service`) on `python:3.13-slim` plus `pip install .`. Web apps (`ember_web`, `pdf_merger_web`, `video_downloader_web`) need a Node build stage, then nginx or the Vite dev server.
- **Compose file**: one `docker-compose.yml` with a fixed `container_name` per app (these are the names `/server start <name>` uses).
- **Networking**: configs hard-code `127.0.0.1` (`ai_agent/configs/config_servers.json`, `ember_api/configs/config_app.json` `mcp_server_url`, `mcp_server/configs/config_extensions.json`). In containers these become service names such as `http://mcp_server:8010/mcp`, and each service must bind `0.0.0.0`. Use env overrides or a docker config variant.
- **Docker socket**: mount `/var/run/docker.sock` into the `mcp_server` container. This gives it root-equivalent control of the host. Dev PC needs Docker Desktop with WSL2.
- **Data**: volumes for `ember_api/data` and `ai_agent/data`.
- **Self-stop**: `/server stop mcp-server` kills the server running the tool; expected, but it cannot be restarted from the same chat.
- `server_launcher` stays as the local-process manager; containers are a second way to run the apps.

**Smallest first step**: compose with `mcp_server` plus one app (for example `pdf_merger`), enough to test `list`, `restart` and `logs`.

**Side issue** (still open 2026-10-07, security): `apps/mcp_server/zima_host.yaml` line 16 has an SMTP password in plain text, checked into the repo. Move it to a gitignored env file and rotate the password. Worth doing before the Docker work.

**Revisit when**: user wants it built (Docker Desktop installed first).

## More ai_agent agents: Email, Data Analyst, Scheduler (added 2026-10-07)

**Context**: Planner, Log Analyst, Researcher, Usage Analyst, Vault Librarian and Repo Helper are built (agent files in `apps/ai_agent/agents/`, tools in `apps/mcp_server/src/capabilities/`). Three agents from the same list were left out because each needs a decision or a missing piece first. Add an agent file with the `aiagent-scaffold` skill and a tool with `mcp-capability-scaffold`.

- **Email Assistant**: draft, summarize and triage mail.
  - Needs a new mcp_server capability; `config_email.json.example` exists, but the item above says it looks dead (`email_config_path` has no caller in `src/`), so check `services/email.py` first.
  - It acts outward, so decide: mailbox and credentials (`.env`); read access or draft only; whether it may send, and who approves each send (the ember tool approval card, or a separate step).
  - Safest start: draft only, no send tool.
- **Data Analyst**: CSV/XLSX in, summary out, mirroring the PDF assistant's upload flow.
  - Decide how it computes. Running arbitrary code on an upload needs a sandbox. Smaller option: fixed tools only (describe, filter, group by, top N) with no code execution.
  - Needs an upload path for tabular files (reuse `POST /upload` and `services/downloads.py`) and output as a table or a download.
- **Scheduler / Watcher agent**: create and explain watchers in plain language.
  - Blocked: there is no generic watcher-creation tool. Watchers exist only inside a capability (`JobWatcher` in `services/watcher.py`), so an agent has nothing to call.
  - Needs a design for user-defined watchers first (what to poll, how often, who gets the email), then a tool, then the agent.

**Also to check once the new agents run**: with 10 agents Ember may route badly. If so, set `"routing": {"laya": true}` in `agents/ember.json`.

**Revisit when**: user picks one; start with its open decisions.

## Video downloader app

Built on 2026-10-06 as `Python/VideoDownloader` (service `video_downloader` plus web app `video_downloader_web`). See its README and `_TODO.md` for deferred features.
