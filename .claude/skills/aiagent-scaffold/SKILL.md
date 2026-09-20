---
name: aiagent-scaffold
description: Add a new AI agent persona/role, a new running ai_agent instance (for chat_app's Agent dropdown / delegate_to_agent), or a brand-new LLM provider backend to the ai_agent project. Use whenever the user asks to add an AI agent, a new persona/role for the assistant, a new provider or model family (beyond Claude/OpenAI), a new gateway (OpenRouter/Bedrock/Vertex/Azure/etc), or wants another agent instance available for delegation — even if they only describe the desired behavior ("I want an agent that specializes in X", "hook up a Gemini-backed agent") without naming ai_agent or these files explicitly.
---

# ai_agent scaffolding

"Adding an AI agent" in this repo means one of three genuinely different
things — figure out which one before touching anything, since they
touch different files and one is pure config while another is real
code:

| Want | What it is | Code change? |
|---|---|---|
| A new persona/domain expert (e.g. "cost analyst", "release manager") using an existing provider | **Role** | No |
| Another live instance answering in chat_app's Agent dropdown / delegate-able via `delegate_to_agent` | **Instance** | No (just config + a launcher) |
| Support for a model family that isn't Claude or OpenAI (Gemini, a bare Ollama/vLLM box not reachable through the OpenAI-compatible shim, etc.) | **Provider** | Yes |

Read `ai_agent/README.md`'s "Roles" and "Project layout" sections — the
source of truth this skill compresses — if anything below is unclear
about the running shape (`chat_app --MCP--> ai_agent --MCP--> mcp_server`,
one provider+model pinned per instance).

**REQUIRED SUB-SKILL:** Use checking-the-catalog before writing any new
reusable function/class here (a provider helper, a config loader, a
formatter) — check `catalog_service` for an existing tagged building
block in chat_app/mcp_server/ai_agent before designing the interface
from scratch.

## Path 1 — New role/persona (config only)

A role is a system-prompt persona layered onto whichever provider an
instance is already running — it does not pick a model or a provider.

1. Edit `ai_agent/configs/config_ai_agent_roles.json` (copy from the
   `.example` first if it doesn't exist yet — the real file is
   gitignored and the process refuses to start without it):

   ```json
   {
     "my_role": {
       "label": "My Custom Role",
       "persona": "You are an expert in ... reference the specific tools/domain concepts this role should reach for."
     }
   }
   ```

2. No code change, no restart-the-whole-repo — just restart the
   `ai_agent` instance(s) that should use it, with `--role my_role` or
   `AI_AGENT_ROLE=my_role` in `secrets/secret_llm.env`. CLI flag beats
   env var beats `default_role`.
3. Write the persona the way `configs/config_ai_agent_roles.json.example`'s
   `ops_specialist` entry does: name the specific tools/terminology/
   domain vocabulary the role should reach for, not a vague "be an
   expert" — the persona is the entire behavioral difference between
   roles, so vagueness there is a role that doesn't actually behave
   differently from `generic`.
4. **Know the limitation before promising a customer two personas on
   one provider at once:** `agent_registry.py` derives an instance's
   registered id from its *provider* alone (`claude-agent`,
   `openai-agent`), not its role. Two `anthropic` instances running
   different roles will overwrite each other's registry entry and each
   other's clean-shutdown deregistration. One role per provider,
   running at a time, is the supported shape today — different roles
   per *different* providers (anthropic as one role, openai as
   `generic`) is fine.

## Path 2 — New running instance (config + launcher, no code)

Use this when you want a *second* delegate-able agent to show up in
chat_app's Agent dropdown and be reachable via `delegate_to_agent` —
typically another instance of an *existing* provider pinned to a
different role, or the same provider through a different gateway.

1. Pick a free port (9100/9101 are taken by the anthropic/openai
   examples) and, if it's a new provider id, confirm `agent_registry.py`'s
   `_AGENT_ID_PREFIX` handles it sensibly — an id not in that dict just
   falls back to `"{provider_id}-agent"`, which is fine for a brand-new
   provider but worth a glance if you're deliberately trying to match
   an existing id.
2. There is one `ai_agent/run.bat` (default: `AI_AGENT_PROVIDER=anthropic`,
   `AI_AGENT_PORT=9100`) — a new instance means setting
   `AI_AGENT_PROVIDER`/`AI_AGENT_PORT` (and `AI_AGENT_ROLE`/
   `AI_AGENT_GATEWAY` if relevant) before calling it, not copying the bat:
   ```
   set AI_AGENT_PROVIDER=openai
   set AI_AGENT_PORT=9101
   ai_agent\run.bat
   ```
   these env vars are the entire identity of an instance.
   `server_launcher.py` (repo root) does the same thing per-instance
   through its own field editor — pick `ai_agent` there, edit the fields,
   press Start — without needing a shell at all.
3. That's it for config: **do not hand-edit `config_agents.json`** in
   either `ai_agent/configs/` or `chat_app/src/configs/`. `agent_registry.py`'s
   `register()`/`deregister()` upsert this instance's `{id, label, url}`
   into *both* copies automatically on clean startup/shutdown — a
   manual edit will just be overwritten (or silently drift, since a
   crash instead of a clean shutdown leaves a stale entry behind — that's
   the one case where a manual removal from both files is warranted, and
   only then).
4. Start it and confirm it shows up in chat_app's Agent dropdown without
   restarting chat_app itself.

## Path 3 — New LLM provider backend (real code)

Use this only when the model family genuinely isn't reachable through
the existing Anthropic Messages API or OpenAI-compatible Responses API
shims — most "new" model needs are actually a new **gateway block**
under the existing `openai` or `anthropic` provider in
`config_llms.json` (see below), not a new provider module. Check that
first: `openrouter`, `bedrock`, `vertex`, `litellm`, `groq`,
`fireworks`, `together`, `ollama`, `vllm`, `azure`, `deepinfra`,
`perplexity` are already wired as gateways, each just a `base_url`/
`api_key` swap in `configs/config_llms.json` under the matching
provider — no new module needed for any of those.

If you do need a real new provider (a structurally different API, e.g.
Google's native SDK rather than an OpenAI-compatible endpoint):

1. Add `src/llm/<name>_provider.py`, modeled on `anthropic_provider.py`
   (the smaller of the two — `openai_provider.py`'s Responses API loop
   is more involved). It must define, at minimum:
   - A `_<Name>(BaseProvider)` class with `PROVIDER_ID`, `DEFAULT_MODEL_FALLBACK`,
     and `has_api_key()` (check whatever `config_llms.json`/env shape this
     provider's secrets take — see `llm_config.gateway()`).
   - Module-level `PROVIDER_ID`, `DEFAULT_MODEL`, `VENDOR_LABEL`,
     `has_api_key`, `is_available` (mirrors every existing provider
     module's tail — `agent_config.py` and `server.py`'s status route
     call these as bare module functions, not class methods).
   - `run_chat(question, history, model, enabled_extensions, request_id, depth, on_event=None) -> ChatResult`
     — the tool-calling loop: fetch tool schemas from `src.mcp_upstream`,
     call the model, dispatch any tool/function calls through
     `_dispatch()` (checking `delegation.TOOL_NAME` first, same as
     `anthropic_provider.py`'s `_dispatch`), loop until a final text
     answer or a round cap, checking `cancellation.is_cancelled(request_id)`
     between rounds so a mid-flight cancel actually stops it.
     Two valid shapes, both supported by `agent_config.py`'s
     `run_chat()` (it checks `inspect.iscoroutinefunction(_PROVIDER_MODULE.run_chat)`):
     - **Sync** (simplest, no live trace/token streaming): a plain
       `def`, `on_event` accepted but ignorable — dispatched via
       `anyio.to_thread.run_sync`, and any `on_event` the caller passed
       is silently dropped since a thread-offloaded sync call has no
       way to stream events back incrementally.
     - **Async with live streaming** (what `anthropic_provider.py` does —
       copy it for this shape): `async def`, set `SUPPORTS_STREAMING = True`
       at module level, and around each tool call emit
       `await on_event(step_event("step_start", id=..., tool=..., label=..., arguments=...))`
       / `step_event("step_end", id=..., ok=..., result=...)` (both from
       `src.llm.base_provider`), stream **every** round (not just the last) via the SDK's own
       streaming call, emitting `step_event("token", text=chunk)` per
       chunk; if a round turns out to contain tool calls, emit
       `step_event("token_reset")` so the client drops the text already
       shown. Run `_dispatch` via `anyio.to_thread.run_sync` (delegation
       calls `asyncio.run` and would fail inside the running loop), and
       when echoing output items back to OpenAI strip SDK-only fields
       (`parsed_arguments`) or the next request 400s. `on_event` may be
       `None` (e.g. `run_interpret`'s non-streaming callers) — guard
       every emit with `if on_event is not None:`. This is what
       ultimately reaches chat_app as SSE frames — see
       `server.py`'s `ask()` tool (`ctx.report_progress(0, None, json.dumps(event))`)
       and `chat_app/src/services/sse.py` on the other end.
   - `run_interpret(text, model) -> ChatResult` — one non-agentic
     completion, no tools offered (used to finish an AI-required
     `mcp_server` tool's result — see `server.py`'s `interpret` tool).
   - Report token spend, never enforce it: return the response's
     `total_tokens` (and `context_tokens`) on the `ChatResult`, nothing
     more. ai_agent keeps no usage store and applies no rolling
     6-hour/weekly cap — chat_app records each `ask`/`interpret`
     `total_tokens` per user in its own `usage.db` and owns the caps
     (`configs/config_usage_limits.json`, `services/usage_limits.py`).
     Only the per-request `max_output_tokens`/`max_context_tokens`/`max_tool_rounds` in
     `configs/config_token_limits.json` live here.
   - Wrap rate-limit errors into `cooldown.start_cooldown(PROVIDER_ID, seconds)`
     and re-raise, same pattern as the existing providers, so `is_available()`
     correctly reflects a provider that just got rate-limited.
2. Register it in `agent_config.py`'s `_PROVIDERS` dict:

   ```python
   from src.llm import <name>_provider
   _PROVIDERS["<provider_id>"] = <name>_provider
   ```

   This is the single point that makes `AI_AGENT_PROVIDER=<provider_id>`
   a valid value — an id missing from this dict fails loudly at startup
   with the list of valid alternatives, by design (no silent fallback).
3. Add a top-level block for it in both `configs/config_llms.json` and
   `.json.example`, following the existing shape — a default gateway
   (e.g. `"<provider_id>": {"<default_gateway>": {"label": ..., "api_key": "{<PROVIDER>_API_KEY}", "model": ...}}}`).
4. Add the real secret var name to `secrets/secret_llm.env.example`
   (and your own gitignored `secret_llm.env`) — whatever `{PLACEHOLDER}`
   you referenced in step 3.
5. If the new model family's context window matters for the usage bar,
   add a substring-matched entry to `src/llm/model_limits.py`'s
   `CONTEXT_WINDOWS` (e.g. `"gemini-2": 1_000_000`) — unlisted models
   just get `DEFAULT_CONTEXT_WINDOW`, which is a safe but probably wrong
   fallback for a real provider you're adding deliberately.
6. Optionally add a `run_ai_agent_<name>.bat` per Path 2 above so it's
   as easy to start as the two existing instances.

## Logging (there isn't any)

Unlike `chat_app`/`mcp_server`, `ai_agent` has no logging module and no `logs/` folder — see `ai_agent/src/README.md`. It's stateless beyond its in-process registries. Don't import either app's `logging_setup` here (separate venvs, no shared deps between projects — same convention `services/app_config.py` documents elsewhere in this repo) and don't bolt a one-off logger onto a single role/instance/provider. If a feature genuinely needs durable logs here, that's a cross-cutting change to `ai_agent` itself, not something a single scaffold step should invent.

## Verify before calling it done

- **Role**: restart the instance with `--role <id>`, confirm the
  process doesn't fail at startup (an unknown role id fails loudly by
  design) and that a chat turn's tone/tool usage matches the persona.
- **Instance**: start it, check `GET` on chat_app's agent list (or just
  the dropdown) shows the new entry, then Ctrl+C it cleanly and confirm
  the entry disappears from both `config_agents.json` copies.
- **Provider**: `python -m src.server` with the new `AI_AGENT_PROVIDER`
  set — a missing/bad API key should fail loudly at import time
  (`AgentConfigError`), not on the first request. Then run one real
  `ask` turn that triggers a tool call, to exercise the dispatch loop,
  and one that doesn't, to exercise the plain-text return path. If
  written async with `on_event`, drive it from chat_app's Chat page
  (not a bare script) and confirm `step_start`/`step_end`/`token` SSE
  events actually arrive live — a `run_chat` that's syntactically
  correct but never calls `on_event` still returns a fine final
  `ChatResult`, so this only surfaces by watching the trace UI update
  mid-turn, not from `ask`'s return value alone.
