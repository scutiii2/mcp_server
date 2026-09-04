# ai_agent design

Date: 2026-09-04
Status: Draft — pending user review

## Problem

Today `chat_app` talks directly to `mcp_server`: its Chat page runs an
LLM provider (`src/services/llm/{openai,claude,ollama}_provider.py`)
and a bounded tool-calling loop in-process, dispatching tool calls
through `src/services/mcp_client.py` (a per-call, reconnect-every-time
MCP client). Provider/model choice is a per-request dropdown, resolved
by `src/services/llm/router.py`.

```
chat_app  --(MCP, per-call reconnect)-->  mcp_server
```

The goal is a multi-agent future — several `ai_agentN` processes, each
pinned to a specific LLM, each capable of delegating sub-tasks to other
agents — sitting between `chat_app` and `mcp_server`:

```
chat_app
   ^          ^          ^
   |          |          |
   v          v          v
ai_agent1  ai_agent2  ai_agent3
   ^          ^          ^
   |          |          |
   v          v          v
        mcp_server
```

This spec covers the **first slice only**: standing up a single
`ai_agent` and migrating the Chat page's LLM+tool-loop onto it, so the
pattern is proven before it's generalized to N agents.

## Goal

A new, standalone top-level project, `ai_agent/`, that is simultaneously:

- an **MCP server** to `chat_app` (exposing one tool, `ask`, plus a
  small `status` tool for availability polling), and
- an **MCP client** to `mcp_server` (running the same tool-calling loop
  `claude_provider.py` runs today, against a persistent connection
  instead of chat_app's current reconnect-per-call one).

Each `ai_agent` instance is **hard-pinned** to one LLM provider and
model at deploy time (env vars) — no per-request provider/model choice,
no cross-provider "automatic" fallback within one agent. Picking a
different LLM means standing up a different `ai_agent` instance, which
is exactly the seam the multi-agent future needs.

## Non-Goals (this slice)

- **No second or third agent.** `chat_app`'s agent registry is built to
  hold N agents, but only one is configured. Multi-agent selection
  logic ("automatic: pick the best agent") is not designed here.
- **No sub-agent delegation.** A `delegate_to_agent`-style tool (an
  agent calling another agent, or itself, mid-loop) is deferred until a
  second agent exists to delegate to — there's nothing meaningful to
  prove with only one agent in place. The tool-loop is structured so
  this can be added later without rework (it's just another tool in the
  same loop that already calls `mcp_server`'s tools).
- **No change to slash commands or the admin surface.** `/` commands
  (`services/commands.py`) and extension/capability management
  (`fetch_extensions`, `add_extension`, `remove_extension`,
  `fetch_capabilities`, `set_capability_enabled` in
  `src/services/mcp_client.py`) are unaffected — `chat_app` keeps
  talking to `mcp_server` directly for those, exactly as it does today.
  Only the "ask the LLM a question" path moves to `ai_agent`.
- **No change to `mcp_server`.**

## Architecture (this slice)

```
chat_app  --(MCP: ask/status)-->  ai_agent  --(MCP, persistent)-->  mcp_server
   |                                                                    ^
   +----(MCP + plain HTTP: /extensions, /commands, /capabilities)------+
        (unchanged admin/slash-command path)
```

`chat_app`'s Chat page becomes an MCP **client** to `ai_agent` for the
LLM Q&A path only. Everything else it does today against `mcp_server`
directly (slash commands, extension/capability admin) is untouched.

## Code reuse strategy

`ai_agent` is built by copying and adapting two templates already in
this repo, rather than writing either half from scratch:

- **Server side** — [`mcp_server_ext/`](../../../mcp_server_ext/README.md)'s
  FastMCP / `mcp.run(transport="streamable-http")` pattern.
- **Client side** (talking to `mcp_server`) —
  [`mcp_client_template/`](../../../mcp_client_template/README.md)'s
  `McpClientRegistry`, connected once at startup and reused for every
  tool call, replacing the reconnect-per-call pattern
  `chat_app/src/services/mcp_client.py` uses today.

`ai_agent`'s LLM-provider code
(`base.py`/`claude_provider.py`/`openai_provider.py`/`ollama_provider.py`/
`cooldown.py`) is **copied from `chat_app/src/services/llm/`** and then
deleted from `chat_app`, rather than extracted into a shared package.
This matches how `mcp_server_ext`/`mcp_client_template` are already
"copy this folder, keep it standalone" templates with no cross-project
runtime dependency. `router.py`'s multi-provider `AUTOMATIC_ORDER`
dispatch is dropped entirely — a hard-pinned agent never chooses
between providers, so there's nothing left for a router to route.
Copying this file 2-3 more times once agent2/agent3 exist is an
accepted, small duplication cost — extracting a shared package is
deferred until that duplication is actually felt.

## Project layout & config

```
ai_agent/
  pyproject.toml
  src/
    server.py            # FastMCP entry point, adapted from mcp_server_ext/src/server.py
    agent_config.py       # resolves AI_AGENT_PROVIDER/AI_AGENT_MODEL at startup
    llm/
      base.py             # copied from chat_app/src/services/llm/
      claude_provider.py
      openai_provider.py
      ollama_provider.py
      cooldown.py
    mcp_upstream.py        # wraps mcp_client_template's McpClientRegistry
  configs/
    config_servers.json    # mcp_client_template shape, one entry: mcp_server
  secrets/
    secret_llm.env          # this instance's API key(s) + AI_AGENT_PROVIDER/AI_AGENT_MODEL
  tests/
```

`agent_config.py` reads `AI_AGENT_PROVIDER` (e.g. `claude`) and
`AI_AGENT_MODEL` (blank = that provider's own default) once at startup
and resolves directly to that one provider module's `run_chat` — no
provider dict, no automatic fallback. An unknown `AI_AGENT_PROVIDER` or
a missing required API key fails at startup, not on first request
(same convention `mcp_client_template`'s `ConfigError` already uses for
a malformed `config_servers.json`).

## Interface — the MCP tools ai_agent exposes

```python
@mcp.tool()
async def ask(question: str, history: list[dict], enabled_extensions: list[str] = []) -> dict:
    """Ask this agent a question. Runs its own tool-calling loop against
    mcp_server (up to 6 rounds) before returning."""
    ...
    return {
        "response": str,
        "tools_used": list[str],
        "tool_calls": [{"name": str, "arguments": dict, "result": str}, ...],
        "total_tokens": int | None,
        "provider_id": str,
        "model": str,
    }

@mcp.tool()
async def status() -> dict:
    """Live availability of this agent's pinned provider."""
    return {
        "provider_id": str,
        "model": str,
        "available": bool,
        "reason": str | None,
        "cooldown_seconds_remaining": int,
    }
```

`ask` mirrors today's `run_chat(question, history, model,
enabled_extensions)` minus `model`/`provider` (removed — hard-pinned).
FastMCP derives the input schema from the type-hinted signature (same
as `mcp_server_ext`'s `summarize_numbers` example) and returns a
structured dict, read via `result.structuredContent` — the same
pattern `mcp_client_template`'s own usage example already shows. This
preserves every field `chat_api()` needs for its trace log and UI
("tools used" chip, token count); nothing is lost by crossing MCP
instead of a direct Python call.

`ask`'s internals are today's `claude_provider.run_chat` body,
unchanged, except `call_tool`/`list_tools` go through a persistent
`McpClientRegistry` (connected once in a FastMCP lifespan hook) instead
of chat_app's reconnect-per-call `mcp_client.py` — a real latency win
across a 6-round loop that today's code doesn't have.
`enabled_extensions` filtering (today's `_tool_is_enabled` in
`mcp_client.py`) moves into `ai_agent`, filtering the registry's tool
list before building `tool_schemas`.

## Data flow

**`chat_app`'s `chat_api()`:**

1. `router.run_chat(...)` is deleted from the non-command branch. A new
   `services/ai_agent_client.py` calls the resolved agent's `ask` tool
   with `{question, history: llm_history, enabled_extensions}` and
   unpacks the structured result into the same `response_text`/
   `tools_used`/`tool_calls`/`total_tokens` locals the rest of
   `chat_api()` already uses. Chat persistence, trace logging, and the
   JSON response to the browser are **unchanged** — this is the one
   seam that changes.
2. `provider_id`/`model` (shown in the UI, saved to the trace) are no
   longer chosen by `chat_app` — they come back from `ask`'s own
   result, sourced from the agent's `agent_config.py`.

**Inside `ai_agent`'s `ask`:** identical control flow to today's
`claude_provider.run_chat` — build `messages` from `history` +
`question`, loop up to 6 rounds calling the pinned provider's API, and
on a tool-use response call `registry.call_tool(name, arguments)`
against the persistent `mcp_server` connection.

## Agent registry & dropdown (chat_app side)

The Chat page keeps its provider dropdown, repurposed to mean **which
agent**, not which LLM:

- New non-secret config, `chat_app/src/configs/config_agents.json`
  (same role as today's `config_chat.json`): a list of configured
  agents, each `{"id": "claude-agent", "label": "Claude Agent", "url":
  "http://localhost:9100/mcp"}`. Adding agent2/agent3 later is just
  another entry + restart.
- `GET /api/providers` (route name can stay, or become `/api/agents`)
  returns one entry per **configured agent**: `{id, label, available,
  provider_id, model}` — `provider_id`/`model` are read live from that
  agent's `status` tool, so the dropdown can show e.g. "Claude Agent —
  claude-sonnet-5" without `chat_app` needing to know that mapping
  itself.
- **Availability check:** `chat_app`'s `/api/providers` route calls
  `status` on every configured agent (the same live-poll pattern
  `ollama_provider.check_models()` already uses today), so a
  rate-limited or unreachable agent still shows up in the dropdown,
  greyed out with a reason — same UX as today's rate-limited provider
  entries.
- The frontend's chat request body key changes from `provider`/`model`
  to `agent_id`; `chat_api()` looks up that id in the agent registry,
  resolves its URL, and calls `ask` on it.
- No "Automatic" meta-entry in this slice — with one agent configured
  the dropdown has exactly one real choice. "Pick the best agent
  automatically" is left for whenever a second agent actually exists.

## Error handling

- **`ai_agent` unreachable from `chat_app`** (connection refused/
  timeout): falls into `chat_api()`'s existing `except Exception`
  branch — logged, generic "❌ Something went wrong..." message.
  Unchanged in spirit; the failure just now happens one hop further
  out (an MCP call to `ai_agent` instead of an in-process
  `router.run_chat()` call).
- **The pinned provider is rate-limited** (e.g. a Claude 429) mid-`ask`
  call: `ai_agent`'s copy of `cooldown.py` starts the cooldown exactly
  as it does today, and `ask` raises with the same user-facing wording
  chat_app generates today (`"{label} is rate-limited right now - try
  again in {n}s"`). FastMCP surfaces a raised exception as a tool-call
  error; `ai_agent_client` catches it and formats it the same `"❌
  {message}"` way `chat_api()`'s `except ValueError` branch does today.
- **6-round cap hit inside `ask`:** unchanged behavior — still a
  *successful* result (`"Reached maximum tool-call rounds without a
  final answer."` as `response`, with real `tools_used`/`tool_calls`/
  `total_tokens` attached). It now happens inside `ai_agent` instead of
  inside `chat_app`'s process, but the shape returned to the user is
  identical.
- **`mcp_server` unreachable from `ai_agent`:** a single failed tool
  call inside the loop is swallowed per-call, unchanged from today
  (`except Exception: result_text = f"Tool '{name}' failed:
  {error}"` — the LLM sees the failure as a tool result and can react
  to it). If the persistent `McpClientRegistry` connection itself is
  down when `ask` starts, that's a hard failure — same as today's
  behavior when `chat_app` can't reach `mcp_server` at all. No
  degraded/offline mode is designed here; that would be scope beyond
  "migrate the existing loop."

## Testing

Following this repo's existing convention
(`chat_app/tests/test_llm_providers.py`: unit-test schema reshaping and
availability logic with mocks, never a live API call):

- **`ai_agent` unit tests:** `agent_config.py`'s provider/model
  resolution and its fail-at-startup behavior on bad config (mirrors
  `mcp_client_template`'s `ConfigError` tests); each copied provider
  file's existing test coverage carries over unchanged (it's the same
  code).
- **`ask`/`status` tool tests:** mock the pinned provider's client
  (same `unittest.mock.patch` pattern `test_llm_providers.py` already
  uses) and mock `McpClientRegistry.call_tool`/`list_tools` (following
  `mcp_client_template/tests/test_registry.py`'s pattern of exercising
  the registry against its own `_fixtures/reference_server.py` stdio
  server) — verify the 6-round cap, multi-tool-call-per-round, and
  `enabled_extensions` filtering behave identically to today's
  provider-loop coverage.
- **`chat_app`-side:** `tests/test_chat_page.py`'s existing `/api/chat`
  tests are updated to mock `ai_agent_client` instead of
  `router.run_chat`; a new small test file covers `config_agents.json`
  loading and the `/api/providers` status-poll route, mirroring
  `tests/test_llm_settings.py`'s style.
- **No live-model integration test** for either project, consistent
  with the existing rule that `run_chat`'s actual API call is never
  exercised live.

## Defaults Flagged for Review

- `GET /api/providers`'s route name/URL is left as-is in this spec
  (semantics change, path doesn't) to minimize frontend churn; flag if
  you'd rather rename it to `/api/agents` now while everything else is
  being touched anyway.
- `status`'s `cooldown_seconds_remaining`/`reason` fields assume
  `ai_agent`'s `cooldown.py` copy is byte-for-byte identical to
  today's — true at migration time, but the two will drift
  independently once both exist; no shared-package sync mechanism is
  proposed (see "Code reuse strategy" above).
- `config_agents.json`'s exact shape (flat list vs. keyed-by-id object)
  isn't pinned down — either works with the `{id, label, url}` fields
  described above; pick whichever the implementation plan finds
  easier to validate, following `config_servers.json`'s existing
  shape as the closer precedent.
