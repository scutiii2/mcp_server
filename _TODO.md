# _TODO.md

Deferred items — not scheduled, revisit when the trigger condition below is met.

## server_launcher folder structure (added 2026-09-14)

Make `server_launcher`'s file structure match `chat_app`'s (package layout: `src/`, etc.) — still a standalone app, just not one god file (`server_launcher.py` currently holds everything).

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

## server_launcher: show applied preset per running instance (added 2026-09-16)

**Context**: `server_launcher.py`'s `Preset` (name, port, env_vars, args - see `_load_presets`/`_save_presets`) is applied to the launch-form fields (`apply_preset()`) before starting an instance, but the running `Instance` itself doesn't remember which preset (if any) it was started with.

**Ask**: for each running instance, show which preset was selected when it was started - so the instance list/detail view names the preset instead of just port/template.

**Revisit when**: implementing - likely needs `Instance` to carry a `preset_name: str | None`, set at start time (whatever currently calls `apply_preset()` / launches from the form should stash the active preset's name), and a small label added wherever running instances are rendered (`_adopt_running_instances`/instance list rendering).

