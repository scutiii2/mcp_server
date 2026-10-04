# Live Agent Trace + Streaming Replies — Phase 1 (Anthropic) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Anthropic-pinned `ai_agent` instance stream its final answer token-by-token and push each tool call it makes to the browser live, rendered as a collapsible step trace above the answer — matching Claude Code's own tool-call display — over the existing `/chat/api/chat` endpoint, replaced with an SSE version.

**Architecture:** `ai_agent`'s `ask()` MCP tool becomes async and reports each tool-call/token event via MCP's `ctx.report_progress(message=json.dumps(event))` — the only server→client push `streamable_http` gives a single `tools/call` without inventing a second transport. `chat_app`'s `ai_agent_client.py` gets an async-generator sibling to `ask()` that turns those progress notifications (plus the final tool result) into a stream of event dicts. `chat_api()` bridges that async generator onto a background thread (its own event loop) so the existing sync Flask route can `yield` Server-Sent-Events without moving the whole app to ASGI. `script.js` reads the SSE body with `fetch` + a stream reader, rendering steps live and appending answer text as `token` events arrive.

**Tech Stack:** Python 3.11, Flask (sync, WSGI), `mcp` SDK (`FastMCP`, `ClientSession`, `streamablehttp_client`), `anthropic` SDK (`AsyncAnthropic`, `client.messages.stream()`), vanilla JS (`fetch` + `ReadableStream`), pytest.

**Spec:** `chat_app/docs/superpowers/specs/2026-09-13-live-agent-trace-streaming-design.md`

## Global Constraints

- Wire protocol is exactly the spec's `step_start` / `step_end` / `token` / `final` / `error` event shapes — no extra event types, no renamed fields.
- `/chat/api/chat` is replaced in place (spec decision #12) — no parallel JSON endpoint.
- A client that ignores `step_start`/`step_end`/`token` and only reads `final` must get byte-for-byte the same fields `chat_api()` returns today (spec's "Wire protocol" section) — every existing consumer of that JSON shape keeps working.
- Phase 1 touches only the Anthropic path. `openai_provider.py` and its pinned instances keep working exactly as before (no events, one batch response) — Phase 3's job, not this plan's.
- A failed tool call is a `step_end` with `"ok": false`, never silently dropped (spec decision #10).
- A tool with no `display_label` in its `meta` falls back to raw tool name + truncated arguments (spec decision #11) — the fallback is client-side (`script.js`), not server-side, so no format decision is baked into the wire event itself (`step_start` always carries both `tool` and, when set, `label`).

---

## File Structure

- Modify `mcp_server/src/capabilities/sap_sum_monitoring/tool.py`, `sap_role_remediation/tool.py`, `sap_readiness_check/tool.py`, `sap_addon_uninstall/tool.py` — add `display_label` to each `@mcp.tool(meta={...})` call.
- Modify `ai_agent/src/llm/base_provider.py` — add the `StepEvent`/`on_event` shared type.
- Modify `ai_agent/src/llm/anthropic_provider.py` — `AsyncAnthropic`, async `run_chat`, `on_event` calls, final-round streaming.
- Modify `ai_agent/src/agent_config.py` — async `run_chat`, thread `on_event` through, still supports a sync (non-streaming) provider module.
- Modify `ai_agent/src/server.py` — async `ask()` tool, `ctx: Context` param, `on_event` closure.
- Modify `chat_app/src/services/ai_agent_client.py` — add `ask_stream()` async generator alongside the existing `ask()`.
- Create `chat_app/src/services/sse.py` — the sync/async bridge (`stream_async_generator`) + SSE frame encoding, reusable by any future streaming route.
- Modify `chat_app/src/pages/Chat/__index__.py` — `chat_api()` returns a streaming `Response`.
- Modify `chat_app/src/pages/Chat/script.js` — SSE consumer, live step-trace rendering, incremental token rendering.
- Modify `chat_app/src/pages/Chat/styles.css` — step-trace styling.
- Modify `chat_app/tests/test_chat_page.py` — rewrite the `/api/chat` tests for the SSE contract.
- Create `chat_app/tests/test_sse.py` — unit tests for the bridge helper.
- Create `ai_agent/tests/test_anthropic_provider_streaming.py` (or extend the existing provider test file if one exists — check `ai_agent/tests/` first) — unit tests for `on_event` firing.

---

### Task 1: `display_label` on every SAP tool

**Files:**
- Modify: `mcp_server/src/capabilities/sap_sum_monitoring/tool.py`, `mcp_server/src/capabilities/sap_role_remediation/tool.py`, `mcp_server/src/capabilities/sap_readiness_check/tool.py`, `mcp_server/src/capabilities/sap_addon_uninstall/tool.py`
- Test: `mcp_server/tests/test_capability_help.py` (or a new `mcp_server/tests/test_tool_display_labels.py` if that file doesn't already cover tool metadata — check first)

**Interfaces:**
- Produces: every `@mcp.tool(meta={...})` in these four files carries a `"display_label"` string key, present-tense-during / past-tense-after neutral phrasing (e.g. `"Checking SUM status"`), read later by `anthropic_provider._tool_schemas()` via `tool.meta` (Task 3).

- [ ] **Step 1: Write the failing test**

```python
# mcp_server/tests/test_tool_display_labels.py
from src.server import mcp


def test_every_sap_tool_has_a_display_label():
    sap_prefixes = ("get_sum_status_tool", "start_sum_watcher_tool")  # extend as needed
    tools = mcp._tool_manager._tools
    missing = [
        name for name, tool in tools.items()
        if name in sap_prefixes and not (tool.meta or {}).get("display_label")
    ]
    assert missing == [], f"tools missing display_label: {missing}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest mcp_server/tests/test_tool_display_labels.py -v`
Expected: FAIL — `display_label` not in `tool.meta`.

- [ ] **Step 3: Add `display_label` to each tool's `meta`**

In each of the four `tool.py` files, extend every existing `@mcp.tool(meta={"keywords": [...]})` to `@mcp.tool(meta={"keywords": [...], "display_label": "<friendly phrase>"})`. Example (`sap_sum_monitoring/tool.py:53`):

```python
@command(name="status", description="Get SUM Status")
@mcp.tool(meta={"keywords": [...], "display_label": "Checking SUM status"})
def get_sum_status_tool(system_name: SystemLabel) -> SumStatusResult:
```

Pick a short present-participle phrase per tool from its existing `description=` in the `@command` decorator (e.g. `description="Get SUM Status"` → `"Checking SUM status"`) — every tool in these four files already has one to draw from, so this is mechanical, not new copywriting.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest mcp_server/tests/test_tool_display_labels.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add mcp_server/src/capabilities/sap_sum_monitoring/tool.py mcp_server/src/capabilities/sap_role_remediation/tool.py mcp_server/src/capabilities/sap_readiness_check/tool.py mcp_server/src/capabilities/sap_addon_uninstall/tool.py mcp_server/tests/test_tool_display_labels.py
git commit -m "feat(mcp_server): add display_label to SAP tool meta"
```

---

### Task 2: Shared event type in `base_provider.py`

**Files:**
- Modify: `ai_agent/src/llm/base_provider.py`
- Test: `ai_agent/tests/test_base_provider.py` (create if it doesn't exist)

**Interfaces:**
- Produces: `OnEvent = Callable[[dict[str, Any]], Awaitable[None]]` type alias, and a `step_event(kind, **fields) -> dict` helper that stamps `{"type": kind, **fields}` — used by Task 3's provider loop and Task 5's `server.py` closure so both sides agree on the exact dict shape without duplicating literals.

- [ ] **Step 1: Write the failing test**

```python
# ai_agent/tests/test_base_provider.py
from src.llm.base_provider import step_event


def test_step_event_stamps_type():
    event = step_event("step_start", id="1", tool="x", arguments={})
    assert event == {"type": "step_start", "id": "1", "tool": "x", "arguments": {}}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest ai_agent/tests/test_base_provider.py -v`
Expected: FAIL — `ImportError: cannot import name 'step_event'`

- [ ] **Step 3: Implement**

Add to `ai_agent/src/llm/base_provider.py` (after the existing imports, before `ChatCancelled`):

```python
from typing import Any, Awaitable, Callable

OnEvent = Callable[[dict[str, Any]], Awaitable[None]]
"""Async callback a streaming-capable provider's run_chat calls once per
step_start/step_end/token event, in order, from inside its own
tool-calling loop. None when the caller (agent_config.run_chat) doesn't
want live events - every call site must no-op cleanly when this is None,
never assume it's set."""


def step_event(kind: str, **fields: Any) -> dict[str, Any]:
    """Stamps a `type` key onto an event dict - the one place that shape
    is defined, so server.py's ctx.report_progress(message=json.dumps(...))
    and chat_app's SSE frames agree on field names without repeating the
    literal "type" key at every call site."""
    return {"type": kind, **fields}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest ai_agent/tests/test_base_provider.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add ai_agent/src/llm/base_provider.py ai_agent/tests/test_base_provider.py
git commit -m "feat(ai_agent): add shared step_event/OnEvent for streaming providers"
```

---

### Task 3: `anthropic_provider.py` — async, streaming, `on_event`

**Files:**
- Modify: `ai_agent/src/llm/anthropic_provider.py`
- Test: `ai_agent/tests/test_anthropic_provider_streaming.py` (create — check `ai_agent/tests/` for an existing `test_anthropic_provider.py` first and extend that instead if present)

**Interfaces:**
- Consumes: `step_event`, `OnEvent` from Task 2 (`src.llm.base_provider`).
- Produces: `run_chat(question, history, model=None, enabled_extensions=None, request_id=None, depth=0, on_event: OnEvent | None = None) -> ChatResult` is now `async def`. Emits, in order, per round: one `step_start` + one `step_end` per tool call; on the final (non-tool-use) round, one `token` event per text chunk from `client.messages.stream()`. `_tool_schemas()` also returns each tool's `display_label` (from `tool.meta`) alongside `name`/`description`/`input_schema`, threaded into `step_start`'s `label` field. `SUPPORTS_STREAMING = True` module-level flag, read by Task 4's `agent_config.py`.

- [ ] **Step 1: Write the failing test**

```python
# ai_agent/tests/test_anthropic_provider_streaming.py
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.llm import anthropic_provider


@pytest.mark.asyncio
async def test_run_chat_emits_step_events_around_a_tool_call(monkeypatch):
    events = []

    async def on_event(event):
        events.append(event)

    tool_block = MagicMock(type="tool_use", name="get_sum_status_tool", input={"system_name": "s4e"}, id="t1")
    first_response = MagicMock(stop_reason="tool_use", content=[tool_block])
    first_response.usage.input_tokens = 10
    first_response.usage.output_tokens = 5

    final_stream = MagicMock()
    final_stream.text_stream = _fake_async_iter(["Hello", " world"])
    final_stream.get_final_message = AsyncMock(
        return_value=MagicMock(usage=MagicMock(input_tokens=8, output_tokens=2))
    )
    stream_cm = MagicMock()
    stream_cm.__aenter__ = AsyncMock(return_value=final_stream)
    stream_cm.__aexit__ = AsyncMock(return_value=False)

    client = MagicMock()
    client.messages.create = AsyncMock(return_value=first_response)
    client.messages.stream = MagicMock(return_value=stream_cm)

    monkeypatch.setattr(anthropic_provider, "_get_client", lambda: client)
    monkeypatch.setattr(anthropic_provider, "_dispatch", lambda name, args, depth: "SUM is RUNNING at 42%")
    monkeypatch.setattr(anthropic_provider, "_tool_schemas", lambda enabled_extensions=None: [])

    result = await anthropic_provider.run_chat("status?", [], on_event=on_event)

    assert result.response == "Hello world"
    step_starts = [e for e in events if e["type"] == "step_start"]
    step_ends = [e for e in events if e["type"] == "step_end"]
    tokens = [e for e in events if e["type"] == "token"]
    assert step_starts and step_starts[0]["tool"] == "get_sum_status_tool"
    assert step_ends and step_ends[0]["ok"] is True
    assert [t["text"] for t in tokens] == ["Hello", " world"]


def _fake_async_iter(items):
    async def gen():
        for item in items:
            yield item
    return gen()
```

(Add `pytest-asyncio` to `ai_agent`'s test dependencies if not already present — check `ai_agent/requirements*.txt` / `pyproject.toml` first; `asyncio_mode = "auto"` in `pytest.ini`/`pyproject.toml` avoids needing `@pytest.mark.asyncio` on every test if the project prefers that instead.)

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest ai_agent/tests/test_anthropic_provider_streaming.py -v`
Expected: FAIL — `run_chat()` isn't a coroutine / `client.messages.create` still called synchronously / no events emitted.

- [ ] **Step 3: Implement**

In `ai_agent/src/llm/anthropic_provider.py`:

```python
from anthropic import AsyncAnthropic, AsyncAnthropicBedrock, AsyncAnthropicVertex, RateLimitError
from src.llm.base_provider import BaseProvider, ChatCancelled, ChatResult, OnEvent, ToolCallRecord, step_event
```

Swap `Anthropic`/`AnthropicBedrock`/`AnthropicVertex` for their `Async*` equivalents everywhere in `_Anthropic.get_client()` (same constructor kwargs — the async SDK classes are drop-in). `SUPPORTS_STREAMING = True` at module level, near `PROVIDER_ID`.

Give every tool schema its label:

```python
def _tool_schemas(enabled_extensions: list[str] | None = None) -> list[dict[str, Any]]:
    schemas = [
        {
            "name": tool.name,
            "description": tool.description or "",
            "input_schema": tool.inputSchema or {"type": "object", "properties": {}},
            "display_label": (tool.meta or {}).get("display_label") if hasattr(tool, "meta") else None,
        }
        for tool in list_tools(enabled_extensions)
    ]
    if delegation.is_available():
        schemas.append({
            "name": delegation.TOOL_NAME,
            "description": delegation.tool_description(),
            "input_schema": delegation.TOOL_PARAMETERS,
            "display_label": None,
        })
    return schemas
```

(`display_label` isn't a real Anthropic `tools=` schema field — build the Anthropic-facing schema and a separate `name -> display_label` lookup dict from the same list, rather than sending the extra key to the API.)

`run_chat` becomes async, drops `display_label` before sending `tools=` to the API, calls `on_event` around each tool dispatch, and streams the final round:

```python
async def run_chat(
    question: str,
    history: list[dict[str, Any]],
    model: str | None = None,
    enabled_extensions: list[str] | None = None,
    request_id: str | None = None,
    depth: int = 0,
    on_event: OnEvent | None = None,
) -> ChatResult:
    client = _get_client()
    model_name = model or DEFAULT_MODEL
    messages: list[dict[str, Any]] = [*history, {"role": "user", "content": question}]
    tools_used: list[str] = []
    tool_calls: list[ToolCallRecord] = []
    schemas = _tool_schemas(enabled_extensions)
    labels = {s["name"]: s.pop("display_label") for s in schemas}
    total_tokens = 0
    context_tokens = 0

    try:
        for _ in range(6):
            if cancellation.is_cancelled(request_id):
                raise ChatCancelled()
            response = await client.messages.create(
                model=model_name, max_tokens=2048, system=SYSTEM_PROMPT, messages=messages, tools=schemas,
            )
            total_tokens += response.usage.input_tokens + response.usage.output_tokens
            context_tokens = response.usage.input_tokens

            if response.stop_reason != "tool_use":
                text_parts: list[str] = []
                async with client.messages.stream(
                    model=model_name, max_tokens=2048, system=SYSTEM_PROMPT, messages=messages, tools=schemas,
                ) as stream:
                    async for chunk in stream.text_stream:
                        text_parts.append(chunk)
                        if on_event:
                            await on_event(step_event("token", text=chunk))
                    final_message = await stream.get_final_message()
                total_tokens += final_message.usage.input_tokens + final_message.usage.output_tokens
                return ChatResult(
                    response="".join(text_parts), tools_used=tools_used, tool_calls=tool_calls,
                    provider_id=PROVIDER_ID, model=model_name, total_tokens=total_tokens, context_tokens=context_tokens,
                )

            messages.append({"role": "assistant", "content": response.content})
            tool_results: list[dict[str, Any]] = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                tools_used.append(block.name)
                step_id = block.id
                if on_event:
                    await on_event(step_event(
                        "step_start", id=step_id, tool=block.name, label=labels.get(block.name), arguments=block.input,
                    ))
                try:
                    result_text = _dispatch(block.name, block.input, depth)
                    ok = True
                except Exception as error:
                    result_text = f"Tool '{block.name}' failed: {error}"
                    ok = False
                if on_event:
                    await on_event(step_event("step_end", id=step_id, ok=ok, result=result_text))
                tool_calls.append(ToolCallRecord(name=block.name, arguments=block.input, result=result_text))
                tool_results.append({"type": "tool_result", "tool_use_id": block.id, "content": result_text})
            messages.append({"role": "user", "content": tool_results})
    except RateLimitError as error:
        seconds = cooldown.extract_retry_after_seconds(error) or cooldown.DEFAULT_COOLDOWN_SECONDS
        cooldown.start_cooldown(PROVIDER_ID, seconds)
        raise

    return ChatResult(
        response="Reached maximum tool-call rounds without a final answer.", tools_used=tools_used, tool_calls=tool_calls,
        provider_id=PROVIDER_ID, model=model_name, total_tokens=total_tokens, context_tokens=context_tokens,
    )
```

`run_interpret` stays synchronous/unchanged — it never streams (spec Non-goals).

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest ai_agent/tests/test_anthropic_provider_streaming.py -v`
Expected: PASS

- [ ] **Step 5: Run the full existing `ai_agent` provider test suite to check nothing else broke**

Run: `pytest ai_agent/tests/ -v`
Expected: PASS (fix any test still mocking the old sync `Anthropic`/`client.messages.create` shape — update those mocks to `AsyncMock`, same pattern as Step 1 above).

- [ ] **Step 6: Commit**

```bash
git add ai_agent/src/llm/anthropic_provider.py ai_agent/tests/test_anthropic_provider_streaming.py
git commit -m "feat(ai_agent): stream Anthropic tool steps and final tokens via on_event"
```

---

### Task 4: `agent_config.py` — async wrapper, sync-provider fallback

**Files:**
- Modify: `ai_agent/src/agent_config.py`
- Test: `ai_agent/tests/test_agent_config.py` (extend existing, or create)

**Interfaces:**
- Consumes: `anthropic_provider.SUPPORTS_STREAMING` (Task 3), `OnEvent` (Task 2).
- Produces: `run_chat(question, history, enabled_extensions, request_id=None, depth=0, on_event: OnEvent | None = None) -> ChatResult`, now `async def`. Awaits an async-capable provider module directly; runs a still-sync provider module (Phase 1: `openai_provider`) in a worker thread via `anyio.to_thread.run_sync` so it doesn't block the event loop, silently ignoring `on_event` for that path (Phase 3 fixes this).

- [ ] **Step 1: Write the failing test**

```python
# ai_agent/tests/test_agent_config.py
import pytest
from unittest.mock import AsyncMock, patch

from src import agent_config
from src.llm.base_provider import ChatResult


@pytest.mark.asyncio
async def test_run_chat_awaits_async_provider_and_forwards_on_event():
    fake_result = ChatResult(response="hi")
    with patch.object(agent_config, "_PROVIDER_MODULE") as module:
        module.run_chat = AsyncMock(return_value=fake_result)
        events_seen = []

        async def on_event(e):
            events_seen.append(e)

        result = await agent_config.run_chat("q", [], [], on_event=on_event)

        assert result is fake_result
        module.run_chat.assert_awaited_once()
        assert module.run_chat.call_args.kwargs["on_event"] is on_event
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest ai_agent/tests/test_agent_config.py -v`
Expected: FAIL — `run_chat` isn't awaitable / doesn't accept `on_event`.

- [ ] **Step 3: Implement**

```python
import inspect
import anyio

async def run_chat(
    question: str,
    history: list[dict[str, Any]],
    enabled_extensions: list[str],
    request_id: str | None = None,
    depth: int = 0,
    on_event: Any = None,
) -> ChatResult:
    cancellation.register(request_id)
    try:
        if inspect.iscoroutinefunction(_PROVIDER_MODULE.run_chat):
            return await _PROVIDER_MODULE.run_chat(
                question, history, MODEL, enabled_extensions, request_id, depth, on_event=on_event,
            )
        # Phase 1: openai_provider is still sync - run it off the event
        # loop thread so a slow completion doesn't block other requests
        # this ai_agent process is serving. on_event is dropped here on
        # purpose: a sync provider has nowhere to await it from (Phase 3
        # converts openai_provider the same way Task 3 did anthropic_provider).
        return await anyio.to_thread.run_sync(
            lambda: _PROVIDER_MODULE.run_chat(question, history, MODEL, enabled_extensions, request_id, depth)
        )
    finally:
        cancellation.clear(request_id)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest ai_agent/tests/test_agent_config.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add ai_agent/src/agent_config.py ai_agent/tests/test_agent_config.py
git commit -m "feat(ai_agent): make agent_config.run_chat async, bridge sync providers"
```

---

### Task 5: `server.py` — async `ask()` tool, `ctx.report_progress`

**Files:**
- Modify: `ai_agent/src/server.py`
- Test: `ai_agent/tests/test_server_ask.py` (create — check `ai_agent/tests/` for an existing server test file first)

**Interfaces:**
- Consumes: `agent_config.run_chat(..., on_event=...)` (Task 4).
- Produces: `ask()` is now `async def ask(question, history=None, enabled_extensions=None, request_id=None, depth=0, ctx: Context) -> dict[str, Any]` — same return shape as today (spec's Global Constraints). Internally builds `on_event` as a closure calling `await ctx.report_progress(0, None, json.dumps(event))`.

- [ ] **Step 1: Write the failing test**

```python
# ai_agent/tests/test_server_ask.py
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from src import server
from src.llm.base_provider import ChatResult


@pytest.mark.asyncio
async def test_ask_relays_events_via_ctx_report_progress(monkeypatch):
    async def fake_run_chat(question, history, enabled_extensions, request_id, depth, on_event=None):
        await on_event({"type": "step_start", "id": "1", "tool": "x"})
        return ChatResult(response="done")

    monkeypatch.setattr(server.agent_config, "run_chat", fake_run_chat)
    ctx = MagicMock()
    ctx.report_progress = AsyncMock()

    result = await server.ask.fn("q", ctx=ctx)

    assert result["response"] == "done"
    ctx.report_progress.assert_awaited_once()
    _, _, message = ctx.report_progress.call_args.args
    assert json.loads(message) == {"type": "step_start", "id": "1", "tool": "x"}
```

(`server.ask.fn` — FastMCP's `@mcp.tool()` wraps the function in a `Tool` object; its original callable is reachable as `.fn`. Confirm this attribute name against the installed `mcp` package — `mcp/server/fastmcp/tools/base.py` — before relying on it; adjust the test if the SDK names it differently.)

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest ai_agent/tests/test_server_ask.py -v`
Expected: FAIL — `ask` isn't a coroutine / doesn't accept `ctx`.

- [ ] **Step 3: Implement**

```python
import json
from mcp.server.fastmcp import Context

@mcp.tool()
async def ask(
    question: str,
    history: list[dict[str, Any]] | None = None,
    enabled_extensions: list[str] | None = None,
    request_id: str | None = None,
    depth: int = 0,
    ctx: Context | None = None,
) -> dict[str, Any]:
    """Ask this agent a question. ... (docstring unchanged)"""
    async def on_event(event: dict[str, Any]) -> None:
        if ctx is not None:
            await ctx.report_progress(0, None, json.dumps(event))

    try:
        result = await agent_config.run_chat(
            question, history or [], enabled_extensions or [], request_id, depth, on_event=on_event,
        )
    except ChatCancelled:
        return _cancelled_result()
    return {
        "response": result.response,
        "tools_used": result.tools_used,
        "tool_calls": [
            {"name": c.name, "arguments": c.arguments, "result": c.result} for c in result.tool_calls
        ],
        "total_tokens": result.total_tokens,
        "context_tokens": result.context_tokens,
        "context_window": agent_config.status()["context_window"],
        "provider_id": result.provider_id,
        "model": result.model,
        "cancelled": False,
    }
```

`interpret`, `status`, `cancel` stay unchanged (sync, no `ctx`).

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest ai_agent/tests/test_server_ask.py -v`
Expected: PASS

- [ ] **Step 5: Manual smoke check — real MCP round trip**

Run: `python -m ai_agent.src.server` in one terminal (with `CLAUDE_API_KEY` configured), then in another:
```bash
python -c "
import asyncio
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

async def main():
    async with streamablehttp_client('http://127.0.0.1:9100/mcp') as (r, w, _):
        async with ClientSession(r, w) as s:
            await s.initialize()
            events = []
            async def on_progress(p, t, m):
                events.append(m)
            result = await s.call_tool('ask', {'question': 'say hi'}, progress_callback=on_progress)
            print('events:', events)
            print('final:', result.structuredContent)

asyncio.run(main())
"
```
Expected: `events` shows at least one `token` message (JSON string); `final` has a non-empty `response`.

- [ ] **Step 6: Commit**

```bash
git add ai_agent/src/server.py ai_agent/tests/test_server_ask.py
git commit -m "feat(ai_agent): ask() reports live step/token events via MCP progress"
```

---

### Task 6: `chat_app/src/services/sse.py` — the async/sync bridge

**Files:**
- Create: `chat_app/src/services/sse.py`
- Test: `chat_app/tests/test_sse.py`

**Interfaces:**
- Produces: `stream_async_generator(factory: Callable[[], AsyncIterator[dict]]) -> Iterator[dict]` — a plain sync generator/iterator any Flask view can loop over. `encode_sse(event: dict) -> bytes` — `b"data: <json>\n\n"`.

- [ ] **Step 1: Write the failing test**

```python
# chat_app/tests/test_sse.py
import json

from src.services.sse import encode_sse, stream_async_generator


def test_encode_sse_shape():
    assert encode_sse({"type": "token", "text": "hi"}) == b'data: {"type": "token", "text": "hi"}\n\n'


def test_stream_async_generator_yields_in_order():
    async def factory():
        async def gen():
            yield {"type": "step_start", "id": "1"}
            yield {"type": "final", "response": "ok"}
        async for item in gen():
            yield item

    items = list(stream_async_generator(factory))
    assert items == [{"type": "step_start", "id": "1"}, {"type": "final", "response": "ok"}]


def test_stream_async_generator_turns_an_exception_into_an_error_event():
    async def factory():
        raise RuntimeError("boom")
        yield  # pragma: no cover - unreachable, makes this an async generator

    items = list(stream_async_generator(factory))
    assert items == [{"type": "error", "message": "boom"}]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest chat_app/tests/test_sse.py -v`
Expected: FAIL — `ModuleNotFoundError: src.services.sse`

- [ ] **Step 3: Implement**

```python
"""Bridges an async generator (an MCP client's live event stream) onto a
plain synchronous iterator, so a normal Flask view - this whole app stays
WSGI/sync, not ASGI - can `yield` Server-Sent Events without every route
that needs one learning asyncio. Runs the async generator to completion
on a dedicated background thread with its own event loop; the calling
thread just drains a thread-safe queue.Queue.
"""

from __future__ import annotations

import asyncio
import json
import queue
import threading
from typing import Any, AsyncIterator, Callable, Iterator

_SENTINEL = object()


def encode_sse(event: dict[str, Any]) -> bytes:
    return f"data: {json.dumps(event)}\n\n".encode("utf-8")


def stream_async_generator(factory: Callable[[], AsyncIterator[dict[str, Any]]]) -> Iterator[dict[str, Any]]:
    q: queue.Queue = queue.Queue()

    def worker() -> None:
        async def drain() -> None:
            try:
                async for item in factory():
                    q.put(item)
            except Exception as exc:  # noqa: BLE001 - surfaced to the caller as a stream event, never raised across threads
                q.put({"type": "error", "message": str(exc)})
            finally:
                q.put(_SENTINEL)

        asyncio.run(drain())

    threading.Thread(target=worker, daemon=True).start()
    while True:
        item = q.get()
        if item is _SENTINEL:
            return
        yield item
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest chat_app/tests/test_sse.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add chat_app/src/services/sse.py chat_app/tests/test_sse.py
git commit -m "feat(chat_app): add async-generator-to-SSE bridge helper"
```

---

### Task 7: `ai_agent_client.py` — `ask_stream()`

**Files:**
- Modify: `chat_app/src/services/ai_agent_client.py`
- Test: `chat_app/tests/test_ai_agent_client.py` (extend existing, or create)

**Interfaces:**
- Produces: `async def ask_stream(url, question, history, enabled_extensions, request_id=None) -> AsyncIterator[dict]` — yields every relayed progress event (`step_start`/`step_end`/`token`, verbatim from `json.loads(message)`) then exactly one terminal `{"type": "final", **structuredContent}` or `{"type": "error", "message": ...}`.

- [ ] **Step 1: Write the failing test**

```python
# chat_app/tests/test_ai_agent_client.py (add to existing file)
import pytest

from src.services import ai_agent_client


@pytest.mark.asyncio
async def test_ask_stream_relays_progress_then_final(monkeypatch):
    class FakeResult:
        isError = False
        structuredContent = {"response": "hi", "tools_used": []}

    class FakeSession:
        async def initialize(self):
            pass

        async def call_tool(self, name, arguments, progress_callback=None):
            await progress_callback(0, None, '{"type": "step_start", "id": "1"}')
            await progress_callback(0, None, '{"type": "token", "text": "hi"}')
            return FakeResult()

    class FakeCtx:
        async def __aenter__(self):
            return (None, None, None)

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(ai_agent_client, "streamablehttp_client", lambda url: FakeCtx())
    monkeypatch.setattr(
        ai_agent_client,
        "ClientSession",
        lambda read, write: type("C", (), {"__aenter__": lambda self: _wrap(FakeSession()), "__aexit__": lambda self, *a: _false()})(),
    )

    events = [e async for e in ai_agent_client.ask_stream("http://x", "q", [], [])]

    assert events[0] == {"type": "step_start", "id": "1"}
    assert events[1] == {"type": "token", "text": "hi"}
    assert events[-1] == {"type": "final", "response": "hi", "tools_used": []}


async def _wrap(value):
    return value


async def _false():
    return False
```

(This mock is fiddly because `ClientSession` is itself an async context manager — if it's awkward to monkeypatch cleanly, prefer patching at the `ai_agent_client._call_tool_streaming` level with a fake `session_factory`, or extract the `async with streamablehttp_client(...) / ClientSession(...)` block into a small seam function the test can replace outright. Use whichever keeps the test readable; the behavior being verified — events relayed in order, terminated by exactly one `final`/`error` — is what matters, not the mock's shape.)

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest chat_app/tests/test_ai_agent_client.py -v`
Expected: FAIL — `AttributeError: module 'src.services.ai_agent_client' has no attribute 'ask_stream'`

- [ ] **Step 3: Implement**

```python
import json
from typing import Any, AsyncIterator

async def ask_stream(
    url: str,
    question: str,
    history: list[dict[str, Any]],
    enabled_extensions: list[str],
    request_id: str | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Streaming sibling of ask() - same one-connection-per-call shape,
    but yields every step_start/step_end/token progress event live as it
    arrives, then exactly one terminal final/error event built from the
    same structuredContent ask() returns in one shot."""
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

    async def on_progress(progress: float, total: float | None, message: str | None) -> None:
        if message:
            await queue.put(json.loads(message))

    async def run() -> None:
        try:
            async with streamablehttp_client(url) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool(
                        "ask",
                        {
                            "question": question,
                            "history": history,
                            "enabled_extensions": enabled_extensions,
                            "request_id": request_id,
                        },
                        progress_callback=on_progress,
                    )
            if result.isError:
                parts = [getattr(block, "text", str(block)) for block in result.content]
                await queue.put({"type": "error", "message": "\n".join(parts) if parts else "ask failed"})
            else:
                await queue.put({"type": "final", **(result.structuredContent or {})})
        except Exception as exc:  # noqa: BLE001 - surfaced as a stream event, matching _call_tool's own broad catch reasoning
            await queue.put({"type": "error", "message": str(exc)})
        finally:
            await queue.put(None)

    task = asyncio.ensure_future(run())
    try:
        while True:
            item = await queue.get()
            if item is None:
                break
            yield item
    finally:
        await task
```

The existing blocking `ask()` stays untouched (still used by `summarization.py` and anywhere else that wants one shot, non-streaming).

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest chat_app/tests/test_ai_agent_client.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add chat_app/src/services/ai_agent_client.py chat_app/tests/test_ai_agent_client.py
git commit -m "feat(chat_app): add ai_agent_client.ask_stream for live events"
```

---

### Task 8: `chat_api()` — SSE response

**Files:**
- Modify: `chat_app/src/pages/Chat/__index__.py`
- Test: `chat_app/tests/test_chat_page.py` (rewrite the `/api/chat`-touching tests: `test_chat_api_persists_chat_trace_log_entry_on_success`, `test_chat_api_unexpected_error_produces_log_entry_and_safe_response`, `test_chat_api_agent_tool_error_shown_verbatim`, `test_chat_api_command_input_never_calls_the_agent`, `test_chat_api_requires_chat_access_permission` stays as-is — permission check happens before streaming starts)

**Interfaces:**
- Consumes: `ai_agent_client.ask_stream` (Task 7), `stream_async_generator`/`encode_sse` (Task 6).
- Produces: `POST /chat/api/chat` now returns `200 text/event-stream`; final frame's JSON is exactly today's response body (`response`, `tools_used`, `provider_id`, `model`, `total_tokens`, `context_tokens`, `context_window`, `elapsed_seconds`, `recursive_rounds`, `chat_id`, `kind`) plus `"type": "final"`.

- [ ] **Step 1: Write the failing tests**

Replace the four tests named above in `chat_app/tests/test_chat_page.py` with SSE-aware versions:

```python
def _read_sse_events(response):
    body = response.get_data(as_text=True)
    events = []
    for frame in body.split("\n\n"):
        frame = frame.strip()
        if frame.startswith("data: "):
            events.append(json.loads(frame[len("data: "):]))
    return events


def test_chat_api_persists_chat_trace_log_entry_on_success(tmp_path, monkeypatch):
    app = _build_chat_test_app(tmp_path, monkeypatch)
    account_id = _create_account(app, "traceuser", ["chat.access"])
    client = app.test_client()
    _login_as(client, account_id)

    async def fake_ask_stream(url, question, history, enabled_extensions, request_id=None):
        yield {"type": "final", "response": "hello back", "tools_used": [], "tool_calls": [],
               "provider_id": "openai", "model": "gpt-5.6-sol", "total_tokens": 42, "cancelled": False}

    with patch.object(chat_index.ai_agent_client, "ask_stream", fake_ask_stream):
        response = client.post("/chat/api/chat", json={"question": "hi", "history": []})

    assert response.status_code == 200
    assert response.mimetype == "text/event-stream"
    events = _read_sse_events(response)
    final = events[-1]
    assert final["type"] == "final"
    assert final["response"] == "hello back"
    with app.app_context():
        traces = db.session.query(LogEntry).filter_by(kind="chat_trace", account_id=account_id).all()
        assert len(traces) == 1
        assert "hi" in traces[0].message
```

Apply the same `fake_ask_stream`-as-async-generator pattern to the other three tests (`side_effect=RuntimeError` becomes `raise RuntimeError("boom")` inside the async generator before any `yield`; the `AgentToolError` case yields `{"type": "error", "message": str(error)}` instead of `final`). `test_chat_api_command_input_never_calls_the_agent` is unaffected in spirit but now asserts `fake_ask.assert_not_called()` on `ask_stream` instead of `ask`, and reads the command's reply via `_read_sse_events(response)[-1]` instead of `response.get_json()`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest chat_app/tests/test_chat_page.py -k chat_api -v`
Expected: FAIL — route still returns plain JSON, `response.mimetype` is `application/json`.

- [ ] **Step 3: Implement**

In `chat_app/src/pages/Chat/__index__.py`, add imports:

```python
from src.services.sse import encode_sse, stream_async_generator
```

Replace the body of `chat_api()` from `start = time.monotonic()` onward with a generator that yields SSE frames, doing today's persistence work only once the terminal event arrives:

```python
@blueprint.route("/api/chat", methods=["POST"])
@require_permission("chat.access")
def chat_api():
    data = request.get_json(silent=True) or {}
    question = (data.get("question") or "").strip()
    if not question:
        return Response(encode_sse({"type": "final", "response": "Please enter a question."}), mimetype="text/event-stream")

    request_id = data.get("request_id")
    is_command = question.startswith("/")
    llm_history = _llm_history_from_messages(data.get("history", []))

    chat_id = data.get("chat_id")
    if chat_id is not None:
        if chats_store.get_chat(settings.chats_db_path, current_user.username, chat_id) is None:
            chat_id = None
    if chat_id is None:
        try:
            chat_id = chats_store.save_chat(settings.chats_db_path, current_user.username, None, [])
        except Exception as error:  # noqa: BLE001 - persistence must not block the chat answer itself
            log_service.log_error(
                db.session, current_user, source="chat.start",
                message=f"{type(error).__name__}: {error}"[:_MESSAGE_MAX], details=traceback.format_exc(),
            )
            chat_id = None

    start = time.monotonic()
    user = current_user._get_current_object()  # captured for the generator, which runs after the request context that provides current_user has moved on

    def event_source():
        if is_command:
            response_text = commands.execute_command(
                question, data.get("enabled_extensions", []), agent_id=data.get("provider")
            )
            yield {"type": "final", "response": response_text, "kind": "command"}
            return

        agent = agent_registry.resolve_agent(data.get("provider"))
        if agent is None:
            yield {"type": "final", "response": "❌ No ai_agent is configured - add one to configs/config_agents.json.", "kind": "assistant"}
            return

        history = llm_history
        if chat_id is not None:
            summarized_messages = _maybe_auto_summarize(chat_id, agent["url"])
            if summarized_messages is not None:
                history = _llm_history_from_messages(summarized_messages)

        try:
            async def factory():
                async for event in ai_agent_client.ask_stream(
                    agent["url"], question, history, data.get("enabled_extensions", []), request_id
                ):
                    yield event

            for event in stream_async_generator(factory):
                if event["type"] == "error":
                    yield {"type": "final", "response": f"❌ {event['message']}", "kind": "assistant"}
                    return
                if event["type"] == "final":
                    payload = dict(event)
                    payload["kind"] = "assistant"
                    if payload.get("cancelled"):
                        payload.setdefault("response", "⏹️ Cancelled.")
                    yield payload
                    return
                yield event
        except Exception as error:  # noqa: BLE001 - unplanned; text is untrusted for display
            log_service.log_error(
                db.session, user, source="chat.answer",
                message=f"{type(error).__name__}: {error}"[:_MESSAGE_MAX], details=traceback.format_exc(),
            )
            yield {"type": "final", "response": "❌ Something went wrong while answering your question. Check the Logs page (Errors tab) for details.", "kind": "assistant"}

    def generate():
        for event in event_source():
            if event["type"] != "final":
                yield encode_sse(event)
                continue

            elapsed_seconds = round(time.monotonic() - start, 1)
            response_text = event.get("response", "")
            tools_used = event.get("tools_used", [])
            tool_calls = event.get("tool_calls", [])
            provider_id = event.get("provider_id", "")
            model_used = event.get("model", "")
            total_tokens = event.get("total_tokens")
            context_tokens = event.get("context_tokens")
            context_window = event.get("context_window")
            kind = event.get("kind", "assistant")

            history_in = None
            if chat_id is not None:
                stored_chat = chats_store.get_chat(settings.chats_db_path, user.username, chat_id)
                if stored_chat is not None:
                    history_in = stored_chat["messages"]
            if history_in is None:
                history_in = list(data.get("history", []))
            current_turn = [{"role": "user", "content": question}]
            if history_in and history_in[-1] == current_turn[0]:
                current_turn = []
            assistant_entry: dict = {"role": "assistant", "content": response_text, "elapsed_seconds": elapsed_seconds}
            if kind == "command":
                assistant_entry["kind"] = "command"
            if provider_id:
                assistant_entry["provider_id"] = provider_id
            if model_used:
                assistant_entry["model"] = model_used
            if total_tokens is not None:
                assistant_entry["total_tokens"] = total_tokens
            if context_tokens is not None:
                assistant_entry["context_tokens"] = context_tokens
            if context_window is not None:
                assistant_entry["context_window"] = context_window
            transcript = history_in + current_turn + [assistant_entry]

            saved_chat_id = chat_id
            try:
                saved_chat_id = chats_store.save_chat(settings.chats_db_path, user.username, chat_id, transcript)
            except chats_store.UnknownChat:
                try:
                    saved_chat_id = chats_store.save_chat(settings.chats_db_path, user.username, None, transcript)
                except Exception as error:  # noqa: BLE001 - persistence must not break the chat answer itself
                    log_service.log_error(
                        db.session, user, source="chat.save",
                        message=f"{type(error).__name__}: {error}"[:_MESSAGE_MAX], details=traceback.format_exc(),
                    )
                    saved_chat_id = None
            except Exception as error:  # noqa: BLE001 - persistence must not break the chat answer itself
                log_service.log_error(
                    db.session, user, source="chat.save",
                    message=f"{type(error).__name__}: {error}"[:_MESSAGE_MAX], details=traceback.format_exc(),
                )
                saved_chat_id = None

            if saved_chat_id is not None:
                try:
                    trace_message = f"{question[:80]} → {provider_id or 'error'}/{model_used or '-'}, {elapsed_seconds}s"
                    trace_details = json.dumps({"tool_calls": tool_calls, "response": response_text, "total_tokens": total_tokens})
                    log_service.log_chat_trace(
                        db.session, user, source="chat.turn",
                        message=trace_message[:_TRACE_MESSAGE_MAX], details=trace_details,
                    )
                except Exception as error:  # noqa: BLE001 - a trace write must not break the chat answer itself
                    log_service.log_error(
                        db.session, user, source="chat.trace",
                        message=f"{type(error).__name__}: {error}"[:_MESSAGE_MAX], details=traceback.format_exc(),
                    )

            yield encode_sse({
                "type": "final", "response": response_text, "tools_used": tools_used, "provider_id": provider_id,
                "model": model_used, "total_tokens": total_tokens, "context_tokens": context_tokens,
                "context_window": context_window, "elapsed_seconds": elapsed_seconds, "recursive_rounds": 0,
                "chat_id": saved_chat_id, "kind": kind,
            })

    return Response(stream_with_context(generate()), mimetype="text/event-stream")
```

Add `stream_with_context` to the `flask` import at the top of the file (`from flask import Blueprint, Response, jsonify, render_template, request, stream_with_context`).

Note: this drops the old `recursive_rounds` computation (it was always `len(recursive_rounds)` off an always-empty local list in the pre-existing code — dead weight carried over verbatim as `0`, not a regression) and folds `_MESSAGE_MAX`/`_TRACE_MESSAGE_MAX` truncation through unchanged.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest chat_app/tests/test_chat_page.py -v`
Expected: PASS (all tests in this file, not just the four rewritten ones — check for any other test that posts to `/api/chat` and asserts on `response.get_json()`).

- [ ] **Step 5: Commit**

```bash
git add chat_app/src/pages/Chat/__index__.py chat_app/tests/test_chat_page.py
git commit -m "feat(chat_app): stream /api/chat as SSE, replacing the JSON response"
```

---

### Task 9: `script.js` — SSE consumer + live trace UI

**Files:**
- Modify: `chat_app/src/pages/Chat/script.js`
- Test: manual (Task 9's own step 4) — this repo's JS has no unit test harness in scope here; verified via the running app.

**Interfaces:**
- Consumes: the SSE stream from Task 8, `appendMsg` (existing), `renderMarkdown` (existing).
- Produces: a new `appendTrace()` helper building a `<div class="msg-trace">` of `<details class="trace-step">` rows above the assistant bubble; `send()`'s `fetch` call rewritten to read the streaming body instead of `res.json()`.

- [ ] **Step 1: Add the trace-row builder**

Near `appendMsg` (`script.js:1640`), add:

```javascript
// One <details> row per tool call, live: created open+pending on
// step_start, filled in and closed on step_end. Mirrors Claude Code's
// own tool-call trace - checkmark once resolved, red mark on failure,
// raw tool name + truncated args when the tool has no display_label
// (see mcp_server's capability_meta / tool.py meta={"display_label":...}).
const _traceRows = new Map(); // step id -> <details> element, scoped per in-flight turn

function appendTrace() {
  const wrap = document.createElement('div');
  wrap.className = 'msg-trace';
  document.getElementById('log').appendChild(wrap);
  document.getElementById('log').scrollTop = document.getElementById('log').scrollHeight;
  return wrap;
}

function truncateArgs(args) {
  const text = JSON.stringify(args ?? {});
  return text.length > 120 ? `${text.slice(0, 117)}...` : text;
}

function traceStepStart(traceEl, event) {
  const row = document.createElement('details');
  row.className = 'trace-step trace-step-pending';
  const summary = document.createElement('summary');
  const icon = document.createElement('span');
  icon.className = 'trace-step-icon';
  icon.textContent = '⏳';
  const label = document.createElement('span');
  label.className = 'trace-step-label';
  label.textContent = event.label || `${event.tool} — ${truncateArgs(event.arguments)}`;
  summary.appendChild(icon);
  summary.appendChild(label);
  row.appendChild(summary);
  const pre = document.createElement('pre');
  pre.className = 'trace-step-detail';
  pre.textContent = `${event.tool}\n${JSON.stringify(event.arguments ?? {}, null, 2)}`;
  row.appendChild(pre);
  traceEl.appendChild(row);
  _traceRows.set(event.id, { row, icon, pre });
}

function traceStepEnd(event) {
  const entry = _traceRows.get(event.id);
  if (!entry) return;
  entry.row.classList.remove('trace-step-pending');
  entry.row.classList.add(event.ok ? 'trace-step-ok' : 'trace-step-failed');
  entry.icon.textContent = event.ok ? '✓' : '✗';
  entry.pre.textContent += `\n\n${event.result ?? ''}`;
}
```

- [ ] **Step 2: Rewrite `send()`'s fetch to consume the SSE stream**

Replace `script.js:1355-1436` (the `const res = await fetch(...)` block through the end of the `try`) with:

```javascript
    const res = await fetch('/chat/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        question: llmQuestion,
        history: priorHistory,
        provider: selectedProvider,
        model: selectedModel,
        enabled_extensions: currentEnabledExtensions(),
        chat_id: currentChatId,
        request_id: activeRequestId,
      }),
      signal: activeAbortController.signal,
    });

    if (!res.ok) {
      throw new Error(`Server responded with ${res.status}`);
    }

    _traceRows.clear();
    let traceEl = null;
    let assistantWrap = null;
    let assistantContent = null;
    let streamedText = '';
    let data = null;

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const frames = buffer.split('\n\n');
      buffer = frames.pop(); // last element may be a partial frame - keep it for the next read
      for (const frame of frames) {
        if (!frame.startsWith('data: ')) continue;
        const event = JSON.parse(frame.slice('data: '.length));

        if (event.type === 'step_start') {
          if (thinkingEl.isConnected) thinkingEl.remove();
          if (!traceEl) traceEl = appendTrace();
          traceStepStart(traceEl, event);
        } else if (event.type === 'step_end') {
          traceStepEnd(event);
        } else if (event.type === 'token') {
          if (thinkingEl.isConnected) thinkingEl.remove();
          if (!assistantWrap) {
            assistantWrap = appendMsg('assistant', '');
            assistantContent = assistantWrap.querySelector('.msg-content');
          }
          streamedText += event.text;
          renderMarkdown(assistantContent, streamedText);
        } else if (event.type === 'final') {
          data = event;
        }
      }
    }

    thinkingEl.remove();

    const elapsedMs = typeof data.elapsed_seconds === 'number' ? data.elapsed_seconds * 1000 : Date.now() - requestStartTime;
    const finalTimerText = formatTimerText(elapsedMs, data.total_tokens, modelLabel(data.provider_id, data.model), data.recursive_rounds);
    timerEl.textContent = finalTimerText;
    const displayRole = data.kind === 'command' ? 'command' : 'assistant';
    if (!assistantWrap) {
      // No token events arrived (a command reply, or an error) - render
      // the whole thing in one shot, same as the pre-streaming behavior.
      assistantWrap = appendMsg(displayRole, data.response);
    } else if (data.response !== streamedText) {
      // Final text is authoritative - covers a dropped/out-of-order
      // progress notification without leaving the bubble stale.
      renderMarkdown(assistantContent, data.response);
    }
    assistantWrap.appendChild(timerEl);
    const assistantTurn = { role: 'assistant', content: data.response, elapsed_seconds: data.elapsed_seconds };
    if (data.kind === 'command') assistantTurn.kind = 'command';
    if (data.provider_id) assistantTurn.provider_id = data.provider_id;
    if (data.model) assistantTurn.model = data.model;
    if (typeof data.total_tokens === 'number') assistantTurn.total_tokens = data.total_tokens;
    if (typeof data.context_tokens === 'number') assistantTurn.context_tokens = data.context_tokens;
    if (typeof data.context_window === 'number') assistantTurn.context_window = data.context_window;
    if (data.recursive_rounds) assistantTurn.recursive_rounds = data.recursive_rounds;
    history.push(assistantTurn);
    lastContextTokens = typeof data.context_tokens === 'number' ? data.context_tokens : null;
    lastContextWindow = typeof data.context_window === 'number' ? data.context_window : null;
    refreshContextUsage();
    playNotificationSound();

    if (data.chat_id && data.chat_id !== currentChatId) {
      currentChatId = data.chat_id;
      window.history.pushState(null, '', `/chat?id=${encodeURIComponent(currentChatId)}`);
    }
    if (data.chat_id) {
      loadChatHistory();
    } else {
      removeOptimisticChatEntry();
    }
```

The `catch (err)` block (AbortError / generic failure handling) and the `finally` block below stay unchanged — an aborted `reader.read()` rejects the same way an aborted `fetch()` did, so `cancelSend()`'s existing `AbortError` handling needs no change (Phase 2 verifies this for real rather than assuming it).

- [ ] **Step 3: `renderMarkdown` must accept being called repeatedly on the same container**

Check `renderMarkdown` (`script.js:1794`) — confirm it does `container.innerHTML = DOMPurify.sanitize(marked.parse(text))` (full replace, not append) so calling it again with a longer `streamedText` re-renders cleanly each time rather than duplicating content. If it currently appends instead of replacing, change it to always set `innerHTML` fresh — full re-parse per token is wasteful at high token rates but correct; only optimize (e.g. throttle to every N tokens or every 50ms) if manual testing (Step 4) shows visible jank.

- [ ] **Step 4: Manual browser verification**

Start the app (`preview_start`), open the Chat page, ask a question that triggers at least one SAP tool call. Confirm: trace rows appear live with a spinner, flip to a checkmark; the answer bubble fills in incrementally rather than popping in all at once; a normal (non-streaming-triggering) `/` command still renders correctly; Stop still aborts cleanly (full verification is Phase 2, but nothing here should have broken it). Screenshot the trace + streaming text as proof.

- [ ] **Step 5: Commit**

```bash
git add chat_app/src/pages/Chat/script.js
git commit -m "feat(chat_app): render live tool-call trace and stream answer tokens"
```

---

### Task 10: `styles.css` — trace UI

**Files:**
- Modify: `chat_app/src/pages/Chat/styles.css`

**Interfaces:**
- Consumes: `.msg-trace`, `.trace-step`, `.trace-step-pending`/`-ok`/`-failed`, `.trace-step-icon`, `.trace-step-label`, `.trace-step-detail` (Task 9's class names).

- [ ] **Step 1: Add trace styles**

Near the existing `.msg-attachment`/`.msg-error-details` rules (`styles.css:212`, `:326` — same `<details>`-based collapsible pattern, reuse its look):

```css
.msg-trace { margin: 4px 0 8px; display: flex; flex-direction: column; gap: 4px; }

.trace-step {
  border: 1px solid var(--panel-border);
  border-radius: 6px;
  padding: 2px 8px;
  font-size: 12px;
}
.trace-step summary {
  cursor: pointer;
  list-style: none;
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--ink-muted);
  padding: 4px 0;
}
.trace-step summary::-webkit-details-marker { display: none; }
.trace-step-icon { width: 14px; text-align: center; }
.trace-step-pending .trace-step-icon { animation: trace-spin 1s linear infinite; }
.trace-step-ok .trace-step-icon { color: #2e7d32; }
.trace-step-failed .trace-step-icon { color: #c0392b; }
.trace-step-failed summary { color: #c0392b; }
.trace-step-detail {
  margin: 0 0 6px;
  padding: 6px 8px;
  background: var(--panel-bg-muted, rgba(0,0,0,0.04));
  border-radius: 4px;
  font-size: 11px;
  white-space: pre-wrap;
  overflow-x: auto;
}

@keyframes trace-spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
```

Check `--panel-bg-muted` exists in this file's `:root` block already — if not, use a literal fallback matching the existing dark/light theme tokens (grep the file for how `.msg-error-details pre` (`styles.css:215`) sets its background and match that instead of inventing a new token).

- [ ] **Step 2: Manual verification**

Reload the Chat page in both light and dark theme (if this app supports theme toggling — check `chat.html`/`styles.css` for a `data-theme` or `prefers-color-scheme` block first); confirm trace rows are legible in both, spinner animates, checkmark/✗ colors read clearly against the row background.

- [ ] **Step 3: Commit**

```bash
git add chat_app/src/pages/Chat/styles.css
git commit -m "style(chat_app): style the live tool-call trace"
```

---

## Self-Review Notes

- **Spec coverage:** decisions #1 (single component) → Tasks 8-10 serve every agent through the one route/UI; #2/#11 (label + fallback) → Task 1 + Task 9's `traceStepStart`; #3 (real streaming) → Task 3; #4/#5 (visible, live) → Task 9; #6 (single SSE stream) → Task 8's one `Response`; #7 → explicitly deferred to Phase 2, not silently dropped; #8 → Task 1; #9 (Anthropic first) → this whole plan is Phase 1; #10 (failed step shown) → Task 3's `ok=False` path + Task 9's `.trace-step-failed`; #12 (replace in place) → Task 8 replaces `chat_api()` rather than adding a second route.
- **Type consistency:** `OnEvent`/`step_event` (Task 2) used identically in Task 3 (provider), Task 5 (`server.py`'s closure), Task 7 (`ai_agent_client` relays the same dict shape verbatim); the SSE event `type` values (`step_start`/`step_end`/`token`/`final`/`error`) are the same five strings from the spec through Tasks 3, 5, 7, 8, 9 — no renaming at any hop.
- **Known open edge case, not blocking Phase 1:** `agent_config.py`'s sync-provider fallback (Task 4) runs `openai_provider.run_chat` in a worker thread with `on_event=None` — an OpenAI-pinned instance gets zero trace/streaming until Phase 3, exactly per spec's Non-goals; confirmed not a silent gap.
