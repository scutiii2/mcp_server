# ai_agent design

Date: 2026-09-07
Status: Implemented

## Problem

`chat_app` used to talk directly to `mcp_server`: its Chat page ran an
LLM provider (`src/services/llm/{openai,claude,ollama}_provider.py`) and
a bounded tool-calling loop in-process, dispatching tool calls through
`src/services/mcp_client.py` (a per-call, reconnect-every-time MCP
client). Provider/model choice was a per-request dropdown, resolved by
`src/services/llm/router.py`.

```
chat_app  --(MCP, per-call reconnect)-->  mcp_server
```

A sibling project explored inserting a third tier between the two: one
or more standalone `ai_agentN` processes, each hard-pinned to a specific
LLM, sitting between `chat_app` and `mcp_server` and holding a
persistent connection to it instead of reconnecting per call. This spec
adopts that architecture for this repo.

## Goal

A new, standalone top-level project, `ai_agent/`, that is simultaneously:

- an **MCP server** to `chat_app` (exposing `ask`, `status`, and
  `cancel`), and
- an **MCP client** to `mcp_server` (running the same tool-calling loop
  `claude_provider.py`/`openai_provider.py` ran in `chat_app` before,
  against a persistent connection).

Each `ai_agent` instance is **hard-pinned** to one LLM provider and
model at deploy time (env vars) - no per-request provider/model choice,
no cross-provider "automatic" fallback within one agent. Picking a
different LLM means standing up a different `ai_agent` instance.

Unlike the sibling project this pattern was adopted from, this slice
ports **both Claude and OpenAI** (run as two separate instances,
`claude-agent` on :9100 and `openai-agent` on :9101) and carries
`chat_app`'s **mid-turn cancellation** feature (the Stop button) across
the new process boundary via a third tool, `cancel`. Ollama support -
and the `staged_pipeline.py` enumerate/execute/conclude flow that
existed solely to make weak local models more reliable - is dropped
from `chat_app` entirely for this slice, to be revisited if/when an
Ollama-backed agent is designed.

## Architecture

```
chat_app (Flask, :5000)
   │  MCP: ask/status/cancel            (LLM Q&A only)
   ├────────────────► ai_agent (claude, :9100) ──┐
   │                                              │
   └────────────────► ai_agent (openai, :9101) ──┼──► mcp_server (:8010)
                                                   │      (persistent MCP
   MCP + plain HTTP: /extensions, /commands,      │       connection per
   /capabilities, /approvals  (unchanged) ─────────┘      agent instance)
```

`chat_app`'s Chat page is an MCP **client** to `ai_agent` for the LLM
Q&A path only. Everything else it does against `mcp_server` directly
(slash commands, extension/capability admin, approvals) is untouched.

## Project layout

```
ai_agent/
  pyproject.toml
  src/
    server.py            # FastMCP entry point - ask/status/cancel tools
    agent_config.py       # resolves AI_AGENT_PROVIDER/AI_AGENT_MODEL at startup
    llm/
      base.py             # ChatResult/ToolCallRecord/ChatCancelled/SYSTEM_PROMPT
      claude_provider.py
      openai_provider.py
      cooldown.py
      cancellation.py      # process-local, one registry per ai_agent instance
    mcp_upstream.py        # wraps sync_wrapper.SyncMcpClient
    registry.py, config.py, transports.py, sync_wrapper.py   # generic MCP-client layer
  configs/
    config_servers.json    # one entry: mcp_server
  secrets/
    secret_llm.env          # this instance's API key(s) + AI_AGENT_PROVIDER/AI_AGENT_MODEL
  tests/
```

`agent_config.py` reads `AI_AGENT_PROVIDER` (`anthropic` or `openai`) and
`AI_AGENT_MODEL` (blank = that provider's own default) once at startup
and resolves directly to that one provider module - no provider dict, no
automatic fallback. An unknown `AI_AGENT_PROVIDER` or a missing required
API key fails at startup (`AgentConfigError`), not on first request.

## Interface - the MCP tools ai_agent exposes

```python
@mcp.tool()
def ask(question: str, history: list[dict] | None = None,
        enabled_extensions: list[str] | None = None,
        request_id: str | None = None) -> dict:
    """Runs the tool-calling loop (up to 6 rounds) against mcp_server."""
    return {
        "response": str, "tools_used": list[str],
        "tool_calls": [{"name": str, "arguments": dict, "result": str}, ...],
        "total_tokens": int | None, "provider_id": str, "model": str,
        "cancelled": bool,
    }

@mcp.tool()
def status() -> dict:
    """Live availability of this agent's pinned provider."""
    return {"provider_id": str, "model": str, "available": bool,
            "reason": str | None, "cooldown_seconds_remaining": int}

@mcp.tool()
def cancel(request_id: str) -> dict:
    """Cooperatively cancels an in-flight ask() call on this instance."""
    return {"cancelled": bool}
```

## Cancellation across the process boundary

`chat_app`'s pre-existing cooperative cancellation (`cancellation.py`:
a `request_id`-keyed in-memory set, checked between rounds of the
tool-calling loop) moves into `ai_agent`, one independent copy per
instance - each agent only ever tracks the turns it itself is serving.
`ask` accepts an optional `request_id`; `agent_config.run_chat` wraps
the provider call in `cancellation.register(request_id)` /
`cancellation.clear(request_id)` (try/finally). When the provider's
per-round check (`cancellation.is_cancelled(request_id)`) trips, it
raises `ChatCancelled`, which `server.ask()` catches and turns into a
normal (non-error) structured result - `{"response": "⏹️ Cancelled.",
"cancelled": True, ...}` - rather than an MCP tool error, since a user
hitting Stop is an expected action, not a failure.

`chat_app`'s `cancel_chat_api()` route now needs to know **which agent**
is serving the in-flight turn to cancel it there: the frontend
(`script.js`) captures the selected agent id at send time
(`activeProviderId`, alongside the existing `activeRequestId`) and sends
it as `provider` in the `/api/chat/cancel` POST body, so a dropdown
change mid-flight can't misdirect the cancel call.

## Agent registry & dropdown (chat_app side)

- `chat_app/src/configs/config_agents.json`: a list of configured
  agents, each `{"id", "label", "url"}`. Adding a third agent later is
  just another entry + restart.
- `GET /chat/api/providers` returns one entry per **configured agent**,
  live-polled via that agent's `status` tool (`available`, `reason`,
  `cooldown_seconds_remaining`, `model`) - so a rate-limited or
  unreachable agent still shows up, greyed out with a reason.
- The frontend keeps the `provider` request-body key (holding an agent
  id now, not an LLM provider id) to avoid a wider frontend rename.
- No "Automatic" meta-entry - picking between agents automatically is
  deferred until there's a real heuristic worth encoding.

## A bug found (and fixed) during implementation

`chat_app/src/services/ai_agent_client.py`'s `_call_tool` originally
raised `AgentToolError` **inside** the nested `async with
streamablehttp_client(...)` / `async with ClientSession(...)` blocks.
Both of those run an anyio task group internally; an exception raised
while one is still open gets wrapped in a `BaseExceptionGroup` on
unwind (confirmed live against a running `mcp_server` + `ai_agent`: the
route's `except ai_agent_client.AgentToolError` clause never matched -
what actually propagated was an `ExceptionGroup` wrapping it, falling
into the generic `except Exception` branch and an unwanted error-log
entry). Fixed by moving the `isError` check and raise to **after** both
`async with` blocks exit cleanly.

## Addendum (same date): agent-to-agent delegation

Added a generic `delegate_to_agent` tool, available to every agent
whenever `ai_agent/configs/config_agents.json` (a new, per-instance copy
of the same `{id, label, url}` shape as `chat_app`'s own file - including
each agent's own entry, since self-delegation is allowed) lists at least
one agent. Answers the question "does using a subagent need another
`ai_agent` process?": no, for delegating to an already-running sibling or
to itself; yes, only for a genuinely distinct specialized subagent (its
own system prompt/tool scope/model) - which is exactly the seam this
architecture already provides.

- `src/delegation.py` owns the tool schema (`TOOL_NAME`,
  `tool_description()` built dynamically from the configured agents,
  `TOOL_PARAMETERS`) and `call(agent_id, question, depth)`, which raises
  `ValueError` for an unknown `agent_id` or once `depth` reaches the
  hardcoded cap (`_MAX_DELEGATION_DEPTH = 2`), otherwise calls the
  target's `ask` tool over a fresh per-call MCP connection (the same
  `_call_tool` shape as `chat_app/src/services/ai_agent_client.py`,
  including its "raise only after both `async with` blocks exit"
  fix - confirmed live that raising inside them still wraps the
  exception in a `BaseExceptionGroup` otherwise).
- `claude_provider.py`/`openai_provider.py`'s `_tool_schemas()` append
  this one more entry (only when `delegation.is_available()`), and their
  round loop's per-tool-call dispatch runs through a tiny `_dispatch()`
  that special-cases the delegate tool name and otherwise falls through
  to today's `call_tool()` - wrapped by the exact same `except Exception`
  that already turns a failed call into readable tool-result text, so no
  new error-shape handling was needed for delegation failures.
- `run_chat`/`ask` gained an optional `depth: int = 0` parameter, set
  only by a delegating peer's own `delegation.call()` - `chat_app` never
  sets it, so its existing calls are completely unaffected.
- Cancellation is **not** propagated into a delegated call - `chat_app`'s
  Stop button has no visibility past the top-level agent it called. A
  delegated call always passes `request_id=None`. Documented limitation,
  not a bug.
- Verified live against real running instances (dummy API keys, same
  constraint as the base slice): the depth cap rejects instantly with no
  network call; an unknown `agent_id` fails with a clear message listing
  what's actually configured; a real `claude-agent` -> `openai-agent`
  MCP call over the network correctly propagates `openai-agent`'s real
  (401, dummy-key) tool error back as a plain exception with the message
  intact; `_tool_schemas()` against the real config correctly includes
  the delegate tool with its dynamically-built description.

## Testing

Following this repo's existing convention (mock the SDK/MCP boundary,
never a live API call):

- `ai_agent/tests/`: `test_agent_config.py` (resolution + fail-loud
  paths, `run_chat`'s register/clear wrapping), `test_claude_provider.py`
  / `test_openai_provider.py` (schema reshaping, availability, the
  rate-limit-starts-cooldown path, the cancellation checkpoint),
  `test_cancellation.py`, `test_server.py` (the `ask`/`status`/`cancel`
  tool contracts, including the `ChatCancelled` -> clean-result path).
- `chat_app/tests/test_agent_registry.py`, `test_ai_agent_client.py`
  (including the `isError` -> `AgentToolError` translation, exercised
  through a real `asyncio.run()` call rather than an async test function
  - this repo has no pytest-asyncio plugin installed).
- `chat_app/tests/test_chat_page.py`'s `/api/chat`, `/api/chat/cancel`,
  and `/api/providers` tests updated to mock `ai_agent_client`/
  `agent_registry` instead of `router`/`cancellation`.
- Manually verified end-to-end against a real running `mcp_server` +
  `ai_agent` (claude) + `chat_app`: MCP handshake, live `status`/`ask`/
  `cancel` tool calls, the dropdown's live availability labels
  (`"Claude Agent - claude-sonnet-5"`, `"OpenAI Agent (unreachable)"`),
  and the `AgentToolError` clean-error path in the browser (no real
  Anthropic/OpenAI API keys were available in this environment, so
  `ask` itself was verified failing cleanly with a real 401 from
  Anthropic rather than returning a real answer).
