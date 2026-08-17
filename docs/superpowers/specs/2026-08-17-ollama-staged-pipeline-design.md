# Staged enumerate-execute-conclude pipeline for Ollama models

Status: approved by user, pending implementation plan
Date: 2026-08-17
Scope: `chat_app` only, plus a small `mcp_server` fix needed to carry tool
metadata through the extension proxy. Opt-in per Ollama model — every other
provider (and every non-opted-in Ollama model) is byte-for-byte unchanged.

## Motivation

Small local models (the reason `ollama_provider.py` exists at all — see its
module docstring) are unreliable at picking the right tool out of a large
schema list and at multi-step planning inside one reasoning pass. Today's
`_tool_loop` sends the model the full tool list every round and lets it
free-run tool calls until it produces plain text, capped at
`_MAX_TOOL_CALL_ROUNDS`.

Goal: for models that opt in, replace that single loop with a staged
pipeline that (1) deterministically shrinks the tool list before the model
ever sees it, and (2) breaks the turn into several small, separately-billed
requests — Enumerate a plan, Execute it one step at a time, Conclude with a
plain-language answer — so each individual request stays small enough for a
weak model's context and reasoning budget. A plan step may need to ask the
user something; that pauses the turn and resumes on the next message rather
than being skipped.

Non-goals:
- Any change to OpenAI/Claude providers, or to non-opted-in Ollama models —
  `_tool_loop` stays exactly as it is for everyone else.
- Embedding/ML-based tool retrieval — filtering is deliberately a plain
  deterministic keyword match, not a new dependency.
- Cross-provider generality (a `ProviderSpec`-level abstraction) — out of
  scope; this is Ollama-specific by design (see the rejected "Approach C"
  in this feature's brainstorming discussion).

## Current behavior (for reference)

`ollama_provider.run_chat()` builds `messages`, calls `_tool_loop()` once
(then again per `recursive_chain` review round if enabled), and returns a
`ChatResult`. `_tool_loop()` sends the *entire* filtered tool list
(`_tool_schemas(enabled_extensions)`, no relevance filtering) on every
round, and keeps looping tool-call rounds until the model emits plain text
or `_MAX_TOOL_CALL_ROUNDS` is hit.

`chat_api` (`pages/chat/routes.py`) is a single synchronous
`POST /api/chat` per turn: it reads `history`+`question` from the request,
calls `router.run_chat(...)`, and returns one `response` string. There is no
existing mechanism for a turn to pause mid-request and resume on a later
one — this design adds the first one.

## Design

### 1. Activation: `staged_pipeline` flag per model

`ModelOption` (`services/llm/base.py`) gains a new field:

```python
staged_pipeline: bool = False
```

Parsed in `infra/app_config.py.load_ollama_models()` exactly like
`recursive_chain` is today: optional, defaults `False`, must be a bool if
present, fails loudly (not silently) if malformed. `config.json.example`
gets a commented example entry.

`ollama_provider.run_chat()` branches once, right where it currently calls
`_tool_loop()`:

```python
if _staged_pipeline_enabled(model_name):
    return staged_pipeline.run(client, question, history, model_name,
                                chat_id, enabled_extensions)
# else: today's _tool_loop() path, unchanged
```

`recursive_chain` and `staged_pipeline` are mutually exclusive concepts
(the staged pipeline's own Conclude phase is its "final answer" step,
analogous to what `recursive_chain` reviews) — `staged_pipeline` takes
precedence if both are somehow set on the same model; the implementation
plan should add a startup validation error for that combination rather than
silently picking one, since it likely indicates a config mistake.

This requires `chat_id` to reach `ollama_provider.run_chat()`, which it
does not today (see `services/llm/base.py`'s `RunChatFn` signature) — the
call chain from `chat_api` through `router.run_chat` down to each
provider's `run_chat` needs `chat_id` threaded through as a new parameter.
`chat_api` must also ensure a `chat_id` exists *before* calling
`router.run_chat` (today it's only assigned by `chats_store.save_chat`
*after* the LLM call returns) — the plan should cover minting the id early
(a `secrets.token_urlsafe(12)` call, matching `chats_store.save_chat`'s own
id generation) when the incoming request has none, so a paused plan always
has a stable key to resume against on the next request.

### 2. Tool keyword metadata

Tools declare keywords via MCP's native `meta` field (`Tool._meta` on the
wire), which the installed `mcp` package and FastMCP's `@mcp.tool()`
decorator already support — no new protocol mechanism needed:

```python
@mcp.tool(meta={"keywords": ["disk", "cpu", "memory", "uptime", "health"]})
def get_host_health_tool(...): ...
```

Applied to `mcp_server`'s two capability tool files (`host_health/tool.py`,
`otp/tool.py`, 3 tools total today).

**Extension proxy fix (`mcp_server/infra/extensions.py`):**
`ExtensionRegistry._connect_one` currently builds `_ProxiedTool.definition`
copying only `name`/`description`/`inputSchema`/`outputSchema` from the
upstream `types.Tool` — `meta`, `annotations`, and `icons` are silently
dropped. This must be fixed to copy all of them, so an extension author who
declares `meta={"keywords": [...]}` on their own server has it survive the
proxy. This is a real bug independent of this feature (it also drops
`annotations`/`icons` today) and should be fixed as part of this work since
the feature depends on it.

A tool with no declared `keywords` is always kept by the filter (fail-open
— see §3) — an unannotated extension tool never becomes silently
uncallable, it's just not filtered as tightly.

### 3. `staged_pipeline.py` — the five phases

New file, `chat_app/services/llm/staged_pipeline.py`. Entry point:

```python
def run(client, question, history, model_name, chat_id,
        enabled_extensions) -> ChatResult: ...
```

**0. Resume check.** Look up `chat_id` in `staged_plans_store`. A row found
with matching `provider_id`/`model` means this turn's `question` is the
answer to a paused `ask_user` step — skip to phase 3 (Execute), continuing
from the stored `step_index`/`results`. No row, or a row whose `model`
doesn't match the model this turn is using (switched models mid-pause):
discard/ignore it and start fresh at phase 1. An expired row (past
`expires_at`) is treated the same as no row.

**1. Filter.** `list_tools(enabled_extensions)` tools are scored against
`question`: lowercase-tokenize the question, lowercase-compare against each
tool's `meta.get("keywords", [])`, keep any tool with ≥1 token overlap plus
every tool with no declared keywords. Cap the kept set at a max count
(`_MAX_FILTERED_TOOLS`, e.g. 8), highest-match-count first, ties broken by
original order — bounding this list is the actual point of the filter.

**2. Enumerate.** One Ollama call: filtered tools' *names + descriptions*
only (not full JSON schemas — keeps this request small), plus `question`,
system-prompted to return a JSON array of steps:
`[{"type": "tool_call" | "reasoning" | "ask_user", "detail": "..."}]`.
Parsed defensively (reusing the spirit of `_extract_fallback_tool_call`'s
recovery approach) — a response that isn't valid JSON, isn't a list, has
more than `_MAX_PLAN_STEPS` entries, or has any entry with an unrecognized
`type`, degrades to a single implicit `tool_call` step wrapping the raw
`question`, rather than failing the turn.

**3. Execute.** Walk plan steps from `step_index` onward:
- `tool_call`: filter tools again, scoped to *this step's* `detail` text
  (tighter than the original question), run one bounded round of
  tool-calling (reusing `call_tool`/`ToolCallRecord`, capped at a per-step
  round limit) against just that subset. Record the result.
- `reasoning`: one small Ollama call with no tools offered, given the
  step's `detail` plus a compact summary of prior results (not the full
  transcript — small-context is the point) — appends its output as this
  step's result.
- `ask_user`: **stop here.** Persist
  `{provider_id, model, plan, step_index, results}` to `staged_plans_store`
  with the step's `detail` as the pending question, and return a
  `ChatResult` whose `response` *is* that question. No Conclude call this
  turn.

An overall per-turn call budget (`_MAX_TOTAL_CALLS`) bounds Enumerate +
every Execute call combined; hitting it jumps straight to Conclude with
whatever results exist so far, rather than continuing indefinitely. A tool
failure inside a step is caught and recorded as that step's result text
(`"Tool 'x' failed: ..."`), same recovery pattern as `_tool_loop` today —
it doesn't abort the plan.

**4. Conclude.** Once every step has executed (no more `ask_user` pauses),
one final Ollama call, given all accumulated step results, is
system-prompted to produce a single plain-language answer — explicitly
instructed not to return JSON or a step-by-step transcript, since this text
goes straight to the user the same way `_tool_loop`'s return value does
today. Delete the `staged_plans` row for this `chat_id` (if any) on
completion — nothing survives past a finished turn.

### 4. `staged_plans_store.py` — pause/resume storage

New file, mirroring `mcp_server/infra/pending_requests.py`'s pattern
(SQLite, opaque JSON payload, TTL-based expiry) — chosen specifically
because it's already this codebase's answer to "state that must outlive one
request but shouldn't be an in-memory dict, and shouldn't be permanent."

```sql
CREATE TABLE IF NOT EXISTS staged_plans (
    chat_id     TEXT PRIMARY KEY,
    provider_id TEXT NOT NULL,
    model       TEXT NOT NULL,
    plan        TEXT NOT NULL,   -- JSON: [{type, detail}, ...]
    step_index  INTEGER NOT NULL,
    results     TEXT NOT NULL,   -- JSON: accumulated step results
    created_at  TEXT NOT NULL,
    expires_at  TEXT NOT NULL
)
```

One row per `chat_id`, present only while paused on `ask_user`. TTL default
24 hours (long enough to answer overnight, short enough that an abandoned
chat doesn't linger indefinitely) — not configurable via `config.json`;
a constant in the module, same as `_MAX_TOOL_CALL_ROUNDS` today.

Functions: `save(db_path, chat_id, provider_id, model, plan, step_index,
results, *, ttl_hours=24)`, `get(db_path, chat_id) -> StagedPlan | None`
(`None` for missing *or* expired — expiry is opaque to callers, same
"fails closed, quietly" shape as `pending_requests.get` plus an inline
expiry check), `delete(db_path, chat_id)`.

`chat_app/config.py` gains `staged_plans_db_path`, following the
`users_db_path`/`chats_db_path` convention exactly: own file
(`data/staged_plans.db` default), own `STAGED_PLANS_DB_PATH` env var.

### 5. Guardrail constants (new, alongside existing ones in `ollama_provider.py`/`staged_pipeline.py`)

- `_MAX_FILTERED_TOOLS` (e.g. 8) — cap on the Filter phase's output.
- `_MAX_PLAN_STEPS` (e.g. 8) — cap on the Enumerate phase's output.
- `_MAX_TOTAL_CALLS` (e.g. 20) — cap on Enumerate+Execute combined calls
  for one turn.
- Per-step tool-call round cap, reusing `_MAX_TOOL_CALL_ROUNDS`'s existing
  value rather than inventing a second constant with the same meaning.

Every cap fails into "produce a usable degraded result," never into raising
out of the turn — consistent with every existing guardrail in
`ollama_provider.py`.

## Testing

- `staged_plans_store.py`: create/get/delete/expiry, mirroring
  `mcp_server/tests/test_pending_requests.py`'s shapes.
- `staged_pipeline.py` (mocking the Ollama client, same style
  `test_llm_providers.py` already uses): filter scoring (keyword match,
  fail-open for unlabeled tools, the `_MAX_FILTERED_TOOLS` cap);
  Enumerate parsing (valid plan, malformed/oversized/unrecognized-type
  degrading to the single-step fallback); a full happy-path run with no
  `ask_user` steps; an `ask_user` pause, then a second `run()` call
  simulating the next turn to prove resume continues from the right
  `step_index`; a model-mismatch resume falling back to a fresh plan; every
  guardrail constant actually triggering its degraded path; a tool failure
  inside a step being recorded and not aborting the plan.
- `infra/extensions.py`: a regression test proving `meta`/`annotations`/
  `icons` survive `_connect_one` into `_ProxiedTool.definition` (currently
  dropped).
- `infra/app_config.py`: `staged_pipeline` flag parsing/validation,
  mirroring the existing `recursive_chain` tests; the
  both-flags-set-is-an-error case from §1.
- `pages/chat/routes.py`: `chat_id` is minted before the LLM call when
  absent (needed for a first-turn pause to have a stable key).

## Open items for the implementation plan (not decided here, deliberately)

- Exact wording of the Enumerate/Execute/Conclude system prompts —
  implementation detail, will need real iteration against an actual small
  model, not something to lock down in a design doc.
- Exact numeric values for `_MAX_FILTERED_TOOLS`/`_MAX_PLAN_STEPS`/
  `_MAX_TOTAL_CALLS` — the design fixes their *existence and purpose*, not
  their tuned values; the plan/implementation should pick starting values
  and note they're adjustable.
- `config.json.example`'s new commented `staged_pipeline` example entry
  and any README/`docs` mention of the feature.
