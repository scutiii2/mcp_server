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
