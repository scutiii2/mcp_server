# _TODO.md

Deferred items — not scheduled, revisit when the trigger condition below is met.

## Catalog item descriptions (added 2026-09-14)

Give each item found by the catalog its own description (catalog_service currently lacks per-item descriptions).

## Toggleable caveman mode for chat_app AI agent responses (deferred 2026-09-15)

**Context**: Add a caveman-compression toggle button beside `provider-refresh-btn` in the AI agent selector row ([chat.html:24-31](chat_app/src/pages/Chat/chat.html:24-31)). Design was brainstormed and approved, not yet implemented.

**Approved design**:
- **UI**: boolean toggle button (`aria-pressed`) in `.selectors` div next to the refresh button. Active-state styling like `.ext-toggle-btn`. No emoji, no level picker — single on/off at "full" caveman intensity.
- **State**: `script.js` holds a `caveman` bool, persisted in `localStorage`, restored on page load. Included in the POST body already carrying `question, history, provider, model, enabled_extensions, chat_id, request_id` ([script.js:1380](chat_app/src/pages/Chat/script.js:1380)).
- **Wire-through** (mirrors existing per-request param path): `chat_api()` reads `data.get("caveman", False)` ([__index__.py:446+](chat_app/src/pages/Chat/__index__.py:446)) → `ai_agent_client.ask()/ask_stream()` gains a `caveman` param, passed into the MCP `ask` tool call args ([ai_agent_client.py:48-124](chat_app/src/services/ai_agent_client.py:48)) → `server.py`'s `ask()` MCP tool gains `caveman: bool = False`, forwards to `run_chat()` ([server.py:106](ai_agent/src/server.py:106)) → `anthropic_provider.py` (and `openai_provider.py` for parity) `run_chat()`: when `caveman=True`, append a compact caveman instruction block (core compression rules only, not the full skill doc — drop filler/articles, fragments OK, keep code/errors/numbers exact) to `SYSTEM_PROMPT` before `messages.create(...)`.
- **Mechanism choice**: prompt-level instruction, not a post-process regex filter — regex risks mangling code blocks/error strings/proper nouns, which the caveman skill explicitly avoids.

**Why not built now**: user asked to log it instead of implementing this session.

**Revisit when**: user wants this feature built — implementation order above (UI → state → wire-through → prompt injection) should still hold; re-confirm the RTK-style tool-output-filter idea was explicitly descoped (see conversation 2026-09-14/15) — only caveman is in scope here, not a second filter.

## ai_agent token/context optimization spec — remaining spec items (added 2026-09-16)

**Context**: [ai_agent/docs/spec_context_token_optimization.md](ai_agent/docs/spec_context_token_optimization.md) covers 5 changes. Items 1 (Anthropic `cache_control`) and 2 (history-cap safety net, `token_limits.trim_history_to_fit`) are done for both `anthropic_provider.py` and `openai_provider.py` — `openai_provider.py` was also converted to async with streaming/`on_event`/`display_label` for feature parity with `anthropic_provider.py` (session 2026-09-16).

**Still open**:
- Item 3: lower `AUTO_SUMMARIZE_THRESHOLD_RATIO` in [summarization.py:41](chat_app/src/services/summarization.py:41) from 0.8 to ~0.6.
- Item 4: confirm whether `log_attachment` ([summarization.py:189](chat_app/src/services/summarization.py:189)) is ever re-sent to the LLM (vs. audit/display only) — cap it if so.
- Pre-existing (unrelated) test failures noticed while verifying this session's change, not caused by it — still open: `test_anthropic_provider_streaming.py` (3 tests, `_tool_schemas` lambda signature mismatch), `test_token_limits.py::test_weekly_limit_returns_time_until_oldest_usage_expires`, `test_agent_config.py` (3 tests) + `test_server.py` (2 tests) — all `token_saver` kwarg mismatch in test fakes vs. `server.py`'s `ask()` signature.

**Revisit when**: continuing the token-optimization work — pick up at item 3.

## Terminal chat client `chat_cli/` (deferred 2026-09-21)

**Context**: A CLI that behaves like the chat_app web chat, so conversations can run in a terminal. Design chosen, not yet implemented.

**Approved design**:
- **Architecture**: option B. The CLI talks directly to `ai_agent` / `mcp_server`, reusing the logic in `chat_app/src/services/ai_agent_client.py` and `mcp_client.py`. It does not go through chat_app's HTTP API or login.
- **Location**: new top-level folder `chat_cli/`, laid out per the `root-project-scaffold` skill.
- **Features**: token streaming, tool-call progress display, and an agent picker (same agents as the web UI's Agent dropdown).
- **Suggested libraries**: `rich` for rendering, `prompt_toolkit` for input.

**Known trade-off**: going direct skips chat_app's auth, permissions, usage limits and stored chat history, and duplicates some of that logic. Attachments were not requested and are out of scope.

**Why not built now**: user asked to log it instead of implementing.

**Revisit when**: user wants this built. First check whether `ai_agent_client.py` can be imported or shared cleanly (for example via `catalog_service`) instead of copied. Decide whether the CLI keeps its own chat history.

## Consolidate secret .env and config .json files (deferred 2026-09-21)

**Context**: Many secret/config files are tiny (most under 300 bytes) and split by habit. Proposal to merge them; not approved for implementation yet.

**Proposed merges**:
- **chat_app secrets** (6 files to 2): `secret_app`, `secret_db`, `secret_internal_api`, `secret_mcp`, `secret_smtp` into `secret_chat_app.env`. `secret_bootstrap_admin.env` stays separate (isolated password, edited for a different reason).
- **mcp_server secrets**: merge `secret_app`, `secret_internal_api`, `secret_smtp` into one file. `secret_ssh.env` stays separate (more sensitive).
- **chat_app configs** (7 files to 3): `config_security_fingerprint`, `_headers`, `_ip_filter`, `_rate_limit` into one `config_security.json` with a top-level key per feature. `config_app` + `config_usage_limits` into `config_app.json`. `config_agents.json` stays.
- **mcp_server configs**: `config_capabilities` + `config_extensions` into `config_mcp_server.json`.
- **ai_agent**: leave alone. `config_llms.json` (3 KB) is edited on its own. Merging `config_servers` / `config_token_limits` / `config_ai_agent_roles` is optional and low value.

**Notes**:
- `INTERNAL_API_TOKEN` exists in both chat_app and mcp_server and must match. Do not share a file across projects (keeps each project self-contained).
- `chat_app/configs/config_agents.json` and `ai_agent/configs/config_agents.json` are identical (265 bytes). Check whether both are needed.

**Work involved**: update every loader, the `.example` twins, `config_validation.py` per-file checkers, tests, READMEs and the four scaffold skills (`aiagent-scaffold`, `chatapp-page-scaffold`, `mcp-capability-scaffold`, `root-project-scaffold`). Add a one-time migration that reads the old files when the new one is missing, so existing real secrets (for example the bootstrap admin password) are not lost. Trade-off: one typo can break several settings in a merged file, and a merged `config_security.json` reloads all four features together.

**Why not built now**: user asked to log it instead of implementing.

**Revisit when**: user wants this built. Start with chat_app (most files, plus the ConfigIssues validation to update).

## Treat mcp_server as a normal MCP, drop the "extensions" proxy (deferred 2026-09-21)

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

