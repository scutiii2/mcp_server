# Spec: Context/Token Optimization for ai_agent LLM Providers

Status: DRAFT — not implemented. For review only.

## Problem

Every `run_chat` round in `anthropic_provider.py` and `openai_provider.py` resends
the full static system prompt, full tool schema list, and full unbounded
conversation history as fresh input tokens. Anthropic prompt caching is unused.
chat_app only prunes history reactively, late (80% of context window), and its
`log_attachment` transcript grows without bound. mcp_server tool results are
returned to the LLM without size/field pruning.

## Goals

1. Cut redundant input-token billing on repeated rounds/turns of the same session.
2. Cap unbounded growth points (history, log_attachment, raw tool output).
3. No behavior change to conversation quality or existing public function signatures.

## Non-goals

- Switching providers or SDK versions.
- Summarization quality improvements (existing chat_app summarizer stays as-is).
- OpenAI-side caching code — OpenAI Responses API caches automatically server-side
  for repeated prefixes >1024 tokens; no client change applies there.

## Changes

### 1. Anthropic prompt caching (ai_agent/src/llm/anthropic_provider.py)

- Add `cache_control: {"type": "ephemeral"}` to:
  - the system prompt block (~line 301)
  - the last entry of the `tools` array passed to `client.messages.create`/`.stream`
    (~line 278-282)
- Anthropic caches everything before and including the marked block, so system
  prompt + tool schemas become a cache hit on rounds 2-6 of the same `run_chat`
  call, and across turns while the prefix (system + tools) is unchanged.
- No signature change. Purely additive to the request payload construction.

### 2. History safety net inside ai_agent (anthropic_provider.py:275, openai_provider.py:201)

- Add a defensive cap (token-count based, reuse `token_limits`) inside
  `run_chat` before building `messages`: if `history` alone exceeds a
  configurable threshold (e.g. `token_limits.max_context_tokens(...) * 0.5`),
  drop oldest turns (keep most-recent N) before appending the new question.
- Rationale: today ai_agent trusts chat_app's summarizer entirely. Any other
  caller of `run_chat` (direct MCP client, future integration) gets no
  protection.
- This is a fallback, not a replacement for chat_app's summarizer — chat_app
  should still summarize proactively; this only prevents unbounded blowup for
  callers that skip that path.

### 3. Lower chat_app auto-summarize threshold (chat_app/src/services/summarization.py:41)

- Change `AUTO_SUMMARIZE_THRESHOLD_RATIO` from `0.8` to a lower value (proposed
  `0.6`) so summarization triggers earlier, before most turns run near max
  context.
- Single constant change, no structural change to summarization logic.

### 4. Cap log_attachment growth (chat_app/src/services/summarization.py:189)

- `log_attachment` currently grows by unbounded concatenation
  (`prior_log + new_range_text`) forever. Confirm first whether this content is
  ever re-sent to the LLM (vs. stored only for audit/display).
  - If audit-only: leave as-is, out of scope.
  - If re-sent: cap it the same way `summary` is capped (`SUMMARY_TOKEN_CAP`),
    or exclude it from any future LLM-facing context assembly.

### 5. Trim raw tool output before it reaches the LLM (mcp_server)

- `<capability>/domain.py:1626` (`fetchall()` result) and `domain.py:181`
  (raw SSH stdout): add a size/row cap or summarization step in the
  capability's `tool.py` result formatting layer before the string is returned
  through `call_tool` — not in `domain.py` itself, to keep the raw-data layer
  reusable for non-LLM callers.
- Needs a per-capability decision on what "safe to truncate" means (row count
  cap vs. char cap vs. structured summary) — flag for capability owner review,
  not a blanket truncation utility.

## Verification plan (when implemented)

- Unit test: `anthropic_provider.run_chat` request payload includes
  `cache_control` on system + tools blocks.
- Unit test: history-cap logic drops oldest turns when over threshold, keeps
  most recent, doesn't drop the newly appended user question.
- Manual: run a multi-round tool-calling conversation, confirm Anthropic usage
  response reports `cache_read_input_tokens` > 0 on rounds 2+.
- Regression: existing chat_app summarization tests still pass with new
  threshold constant.

## Open questions

- Confirm with capability owners whether `log_attachment` is ever placed back
  into LLM-facing context, or purely a display/audit artifact.
- Confirm acceptable history-cap threshold value with whoever owns
  `token_limits` config.
