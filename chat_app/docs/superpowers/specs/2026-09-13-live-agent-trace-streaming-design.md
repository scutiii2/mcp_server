# Live agent trace + streaming replies

Date: 2026-09-13

## Problem

`chat_api()` (`chat_app/src/pages/Chat/__index__.py:445`) is a single
request/response round trip: the browser waits with a "thinking..."
placeholder, then the whole answer (and, buried in `tool_calls`, which
tools ran) lands at once. Two things are missing users want visible:

1. **Which tools the agent called, live**, the way Claude Code's own
   tool-call trace renders — a collapsible list of steps with a
   checkmark once each resolves, not just a wall of prose at the end.
2. **The final answer streaming in**, word by word, instead of
   appearing as one block after however many seconds/tool rounds it
   took.

Both pieces of data already exist server-side (`ai_agent/src/server.py`'s
`ask()` returns `tool_calls`; the Anthropic SDK supports token
streaming) — they're just not surfaced live.

## Non-goals (this phase)

- No change to `interpret()`, `status()`, slash commands (`is_command`
  branch of `chat_api()`), or the OpenAI-pinned provider path — see
  Phase 3.
- No new cancel/stop feature — `ai_agent/src/llm/cancellation.py` +
  `script.js`'s `activeAbortController`/`cancelSend()` already do this
  end to end; Phase 2 only has to confirm it survives the move to SSE.
- No bidirectional transport (WebSocket) — one-way server push (SSE)
  covers everything asked for.

## Decisions (grilled 2026-09-13)

| # | Decision | Chosen |
|---|---|---|
| 1 | Scope | All agents in the one Chat page share the same trace/streaming UI (chat_app has one chat page; multiple agent instances via the provider dropdown, not multiple pages). |
| 2 | Trace content | Friendly paraphrase when available, raw tool name + truncated args as fallback — matches Claude Code's own trace rendering. |
| 3 | Streaming mechanism | Real token-by-token streaming from the LLM API, not a client-side typing animation over a static string. |
| 4 | Trace visibility | Visible by default, above the answer, each step individually expandable — not hidden behind a toggle. |
| 5 | Step reveal timing | Live — each step appears (and resolves) as it happens, not as one batch before the text starts. |
| 6 | Transport | One SSE stream per turn, ordered events, not two channels. |
| 7 | Cancel/stop | Already built (see Non-goals) — Phase 2 verifies it under SSE. |
| 8 | Friendly label source | `mcp_server`'s existing per-tool `@mcp.tool(meta={...})` dict (see `sap_sum_monitoring/tool.py:53`) gets a new `display_label` key — one source of truth, no separate map to keep in sync. |
| 9 | Provider order | Anthropic first (Phase 1), cancel/stop verification (Phase 2), OpenAI port (Phase 3) — in that order. |
| 10 | Failed step display | A tool call that raises shows as a failed step (its own icon), not silently folded into the final answer text. |
| 11 | Missing-label fallback | Confirmed: raw tool name + truncated arguments when a tool has no `display_label`. |
| 12 | `/chat/api/chat` endpoint | Replaced in place (SSE). Only consumer is `script.js:1356` plus `chat_app/tests/test_chat_page.py` — no external caller to keep a JSON fallback for. |

## Wire protocol

One SSE response per turn, `Content-Type: text/event-stream`, each
frame `data: <json>\n\n`. Event `type` values, in the order they can
appear:

```jsonc
{"type": "step_start", "id": "1", "tool": "sap_sum_monitoring__get_sum_status_tool", "label": "Checking SUM status", "arguments": {...}}
{"type": "step_end",   "id": "1", "ok": true,  "result": "..."}          // ok:false on a failed step
{"type": "token",      "text": "The "}                                   // repeated, final-round text only
{"type": "final",      "response": "...", "tools_used": [...], "tool_calls": [...], "provider_id": "...", "model": "...", "total_tokens": 123, "context_tokens": 45, "context_window": 200000, "cancelled": false, "elapsed_seconds": 4.2, "chat_id": "...", "kind": "assistant"}
{"type": "error",      "message": "..."}                                 // in place of "final", terminates the stream
```

Exactly one of `final` or `error` always ends the stream. `step_start`/
`step_end`/`token` are purely additive — a client that ignores them and
waits for `final` still gets the exact same payload `chat_api()`
returns today (`response`, `tools_used`, `provider_id`, ... — see
`__index__.py:626-640`), so replaying today's non-streaming contract on
top of the new one costs nothing extra.

Carried MCP-side as `ctx.report_progress(progress, total, message)`
(`message` = the JSON above, `progress`/`total` unused, always `0`/
`None`) — the only server→client push MCP's `streamable_http` transport
offers mid-call, since `ask()` stays one `tools/call` from chat_app's
point of view (see Phase 1 plan's Architecture section for why this
beats inventing a second transport).

## Later phases

- **Phase 2** — confirm/adapt the existing cancel/stop flow
  (`cancellation.py`, `/api/chat/cancel`) against the new SSE
  `/api/chat`: aborting the fetch mid-stream, the server noticing at
  its next between-round or between-token checkpoint, closing the SSE
  response cleanly.
- **Phase 3** — port the same `on_event`/streaming pattern from
  `anthropic_provider.py` to `openai_provider.py`, reusing Phase 1's
  wire protocol and frontend unchanged.

Each phase gets its own plan doc under `docs/superpowers/plans/`,
written once the prior phase's actual contract exists.
