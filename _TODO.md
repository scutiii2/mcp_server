# _TODO.md

Deferred items — not scheduled, revisit when the trigger condition below is met.

## Catalog item descriptions (added 2026-09-14)

Give each item found by the catalog its own description (catalog_service currently lacks per-item descriptions).

## One .env per project, and merge the small configs (deferred 2026-09-21, rewritten 2026-10-05)

**Context**: Secrets and settings are split into many tiny files. ai_agent already uses a single `ai_agent/.env` (with `.env.example`); mcp_server and ember_api still use several `secret_*.env` files. Not approved for implementation yet.

**Secrets: one `.env` per project, like ai_agent**
- **mcp_server** (done 2026-10-05): `.secrets/secret_*.env` merged into `mcp_server/.env` (+ `.env.example`); `MCP_HOST` / `MCP_PORT` stay there. `run.py` builds `.env` from an old `.secrets/` folder on first start (`src/utils/env_file.py`). Delete the legacy `.secrets/` real files once `.env` is confirmed.
- **ember_api** (code done 2026-10-05): `secrets/secret_bootstrap_admin.env`, `secret_internal_api.env` and `secret_smtp.env` merged into `ember_api/.env`; `src/utils/env_file.py` builds `.env` from an old `secrets/` folder on first start, else from `.env.example` (the example file still has to be created by hand: Claude's write to `.env*` is denied). Delete the legacy `secrets/` real files once `.env` is confirmed, and update `ember_api/secrets/README.md`.
- `INTERNAL_API_TOKEN` stays in each project's own `.env` and must match across ember_api, ai_agent and mcp_server. Do not share one file across projects (each project stays self-contained).

**Configs: stay in `configs/`; which ones can merge**
- **mcp_server** (decided 2026-10-05: no merge): `config_capabilities.json` (42 B) and `config_extensions.json` stay separate. Merging needs wrapper keys and rewrites of the loaders and savers in `app_config.py` plus four test files, and `config_extensions.json` is deleted by the extensions-proxy item below, leaving `config_capabilities.json` alone. Both savers are synchronous read-modify-write, so one process cannot interleave them (no shared writer needed). `config_email.json` (example only, gitignored by path unlike the other two) looks dead: `Settings.email_config_path` has no caller in `src/`, `load_email_config` is used only by tests, and nothing loads the `EmailConfig` that `services/email.py` takes. Check `watcher` / `email` before removing it.
- **ai_agent**: `config_limits.json` and `config_tool_selection.json` are both small runtime tuning (token limits, tool shortlist) and can merge into one file (name to decide, for example `config_tuning.json`).
- **Keep separate**: `ai_agent/configs/config_gateways.json` (3 KB, provider endpoints), `prompts.json` (persona text), `config_servers.json` (the MCP server list, reworked by the extensions item below), and `ai_agent/data/agent_registry.json` (runtime registry, lives in `data/`, not a config).
- **Nothing to merge**: ember_api already has the single `configs/config_app.json`; `chat_cli/configs/` has one file. `catalog_service/configs/` not checked.

**Work involved**:
- Update every loader, the `.example` twins, `.gitignore` entries and any `run.bat` first-run copy step to match ai_agent's `.env` handling.
- Update `ember_api/src/services/config_validation.py` per-file checkers (mcp_server has no equivalent file), tests, READMEs (including `ember_api/secrets/README.md`) and the scaffold skills. Edit the skills under `.agents/skills/` (`aiagent-scaffold`, `mcp-capability-scaffold`, `root-project-scaffold`, `ember-feature-scaffold`), then sync to `.claude/skills/`; the pre-commit check enforces the match.
- Add a one-time migration that reads the old files when the new one is missing, so existing real secrets (for example the bootstrap admin password) are not lost.
- Fix stale comments in `ai_agent/.env.example` (it still mentions `secret_llm.env`, `secret.env` and chat_app).

**Trade-off**: one typo in a merged file can break several settings at once.

**Why not built now**: user asked to log it instead of implementing.

**Revisit when**: user wants this built. mcp_server and ember_api secrets are done; configs are what is left.

## Treat mcp_server as a normal MCP, drop the "extensions" proxy (deferred 2026-09-21, rewritten 2026-10-05)

**Note**: chat_app was removed; ember_api now owns the MCP side the old text called "chat_app".

**Context**: Today mcp_server is a hub. External MCPs are added as "extensions" (`mcp_server/configs/config_extensions.json`, `mcp_server/src/extension_routes.py`, `/extensions` endpoint) and their tools arrive proxied as `{ext_id}__{tool}`. The file currently holds one live entry, `pdf_merger`. ember_api reaches mcp_server through one URL (`mcp_server_url` in `ember_api/configs/config_app.json`, used by `ember_api/src/services/mcp_proxy.py`) and passes extensions through (`ember_api/src/routes/server_info.py`, `ember_api/src/services/mcp_server_info.py`: list, add, remove). Each chat turn carries `enabled_extensions` from ember_api (`routes/chats.py`, `services/turns.py`, `services/agent_gateway.py`) to ai_agent (`ai_agent/src/server.py`, `agents/agent_config.py`). `ai_agent` already has a multi-server registry (`configs/config_servers.json`, `McpClientRegistry`, tools namespaced `<server>__<tool>`), but it holds only the `main` entry (mcp_server). Goal: mcp_server is just one MCP entry among several, with no proxying.

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
