# _TODO.md

Deferred items — not scheduled, revisit when the trigger condition below is met.

## Catalog item descriptions (added 2026-09-14)

Give each item found by the catalog its own description (catalog_service currently lacks per-item descriptions).

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
