# Spec: Model tiers per gateway, chosen by the orchestrator per delegated task

Status: Implemented (see the plan docs/superpowers/plans/2026-10-08-model-tiers.md at the repo root).

## Problem

A gateway in `gateways/<provider>/<gateway>.json` has exactly one `model`, and an
agent's model is fixed when its process starts (`agent_spec.apply_to_environ`
sets `AI_AGENT_MODEL`). So a lookup and a hard multi-step analysis run on the
same model. The orchestrator (ember) picks which specialist handles a task
(`delegation.py`) but has no say in how strong a model that specialist uses.

## Goals

1. A gateway can offer several models of different strength (for Claude:
   haiku, sonnet, opus).
2. The orchestrator picks a strength for each delegated task, and is told what
   each strength is good for.
3. Each agent can cap the strengths it may run on (`min_tier` / `max_tier`), so
   a cheap specialist never runs on the strongest model by accident.
4. Existing configs, agent files and callers keep working unchanged.

## Non-goals

- Changing the orchestrator's own model per turn.
- Automatic escalation (retry on a stronger tier when an answer is poor).
- Cost-based or Laya-based tier selection; the model decides from the tier
  descriptions.
- UI changes in `ember_web` / `ember_api`. They never send a tier, so nothing
  there changes.

## Concepts

**Tier ladder.** A fixed, ordered set of names: `light < standard < heavy < extreme`.
Fixed names (not free-form) make `min_tier` / `max_tier` comparable and give
the orchestrator one vocabulary across every gateway. A gateway defines any
subset of the ladder.

**Effective tiers of an agent** = the tiers its gateway defines, intersected
with the agent's `[min_tier, max_tier]` range.

**Default model.** The model the agent runs when no tier is requested:
`llm.model` from the agent file if set, else the gateway's `model`. Unchanged
from today.

## Changes

### 1. Gateway config (`gateways/<provider>/<gateway>.json`, `src/llm/llm_config.py`)

Add an optional `models` object to a gateway block. `model` stays and remains
the default model.

```json
{
  "label": "Claude",
  "api_key": "{CLAUDE_API_KEY}",
  "model": "claude-sonnet-5",
  "models": {
    "light":    { "id": "claude-haiku-4-5", "use_for": "lookups, extraction, short rewrites, simple formatting" },
    "standard": { "id": "claude-sonnet-5",  "use_for": "most tasks" },
    "heavy":    { "id": "claude-opus-5",    "use_for": "multi-step reasoning, hard code or data analysis" }
  }
}
```

- `id` may be an `{ENV_VAR}` placeholder (Azure deployments, vLLM). Resolved by
  the existing `_resolve`; a tier whose id resolves to `None` is dropped.
- `use_for` is required, one line. It is the text the orchestrator reads.
- Unknown tier names or a missing `id` / `use_for` raise a `ValueError` naming
  the gateway and field at load time.
- New catalog function `llm_config.tiers(provider, gateway_name) ->
  dict[str, TierModel]` (`TierModel`: `id`, `use_for`), in ladder order. A
  gateway without `models` returns `{}`.
- `gateways/anthropic/claude.json` (the tracked preset) gets the same
  addition. Other gateways keep one `model` and gain `models` only when wanted.
  Gateways without `models` offer no choice.

### 2. Agent file (`src/agents/agent_spec.py`)

Two optional keys inside `llm`:

```json
"llm": { "provider": "anthropic", "gateway": "claude", "min_tier": "light", "max_tier": "standard" }
```

- Add `min_tier`, `max_tier` to `_LLM_KEYS` and to `LlmSpec` (`str | None`).
- Valid values: ladder names. `min_tier` above `max_tier` is an
  `AgentSpecError` naming the file. Laya agents reject both keys, like the other
  generation settings.
- Omitted = no bound on that side.
- `agent_spec` stays stdlib-only; it knows the ladder constant
  `TIERS = ("light", "standard", "heavy")` and nothing about gateways.
- Whether the gateway defines a tier inside the range is checked at startup
  (section 3), not here.

### 3. Resolution (`src/llm/model_tiers.py`, new)

One small module, no provider imports:

- `effective_tiers(provider, gateway, min_tier, max_tier) -> list[TierInfo]`
  Gateway tiers filtered to the range. Logs a warning when the agent sets a
  cap but its gateway defines no tier inside the range (the cap then has no
  effect and the agent offers no choice).
- `resolve(requested, effective, default_model, agent_id) -> Resolution`
  - `requested` is `None` or a ladder name.
  - `None`, or no effective tiers: `Resolution(model=default_model, tier=None, note="")`.
  - `requested` in effective tiers: that tier's model id.
  - `requested` outside the range or not defined by the gateway: use the
    **nearest effective tier** (ties go to the weaker tier, cheaper) and set
    `note`, e.g. `"heavy is not available for pdf-assistant; ran on standard"`.
  - Invalid string (not a ladder name): treated as `None` with a note.

The agent applies this to **its own** request, whatever the caller sent. A
caller (the orchestrator, or anything that reaches the `ask` tool) can never
push an agent outside its own cap.

### 4. Agent registry publishes tiers (`src/agents/agent_registry.py`)

The registry entry written for each agent (around line 225, next to `llm`)
gains `tiers`: the agent's effective tiers as a list of
`{"tier", "id", "use_for"}`, empty when none. The agent computes it from its
own spec and gateway when it registers, so the orchestrator never reads
another process's gateway config.

### 5. Roster and delegate tool (`agent_spec.RosterEntry`, `agent_routing.py`, `delegation.py`)

- `RosterEntry` gains `tiers: tuple[TierInfo, ...] = ()` (default keeps existing
  constructors and tests valid). `agent_routing.specialists()` fills it from the
  registry entry.
- `delegation.tool_parameters` adds an optional property:
  `"model_tier": {"type": "string", "enum": ["light", "standard", "heavy"], "description": "Strength of the model the specialist runs on. Omit for its default."}`.
  The property is added only when at least one roster entry has two or more
  tiers; otherwise the schema is unchanged from today.
- `delegation.tool_description` appends, per specialist that offers a choice,
  its tiers with `use_for`, for example:
  `researcher: light = lookups ..., standard = most tasks ...`.
  Specialists with fewer than two tiers get no extra text.
- `delegation.call(agent_id, question, depth, model_tier=None)` passes
  `model_tier` in the `ask` arguments. With `agent_id="auto"` the chosen
  specialist receives the tier as given.
- `anthropic_provider._dispatch` and `openai_provider._dispatch` call a new shared
  `delegation.dispatch(arguments, depth)`, which passes `model_tier` to `call()` only when set.
- The `delegate_to_agent` result is prefixed with the resolution note when the
  specialist clamped the request, so the orchestrator learns the cap.
  `ask` returns it as a new `model_note` field next to `model`; `delegation.call`
  reads it.

### 6. Specialist `ask` (`src/server.py`, `src/agents/agent_config.py`, providers)

- `ask(..., model_tier: str | None = None)`, new last-but-one keyword before
  `ctx`. Default `None` keeps every existing caller unchanged.
- `agent_config.run_chat(..., model_tier=None)` calls `model_tiers.resolve`
  with the agent's `MODEL or provider DEFAULT_MODEL` as the default, then passes
  the resolved id as the existing `model` argument of the provider's `run_chat`
  (both providers already take `model: str | None`). No provider loop changes.
- The sync OpenAI path gets the same `model` value.
- `ChatResult.model` already carries the model that ran; `server.ask` also
  returns `model_tier` and `model_note`.
  `model_tier` is present only when set, so existing result and row shapes are unchanged.
- Context-window and token-limit checks keep using `PROVIDER_ID` and the
  resolved model through the existing `context_window_for`.

### 7. Usage log (`src/core/usage_log.py`)

`own_row` records `model_tier` (nullable) beside `model`, so usage per tier is
visible with no schema break (new key, old rows lack it). Readers that do not
know the key ignore it.
Both keys are present only when set, so existing result and row shapes are unchanged. The registry record likewise carries tiers only when non-empty.

### 8. Orchestrator guidance (`agents/ember.json`)

Add to `instructions`: when delegating to a specialist that lists model tiers,
pick the lightest tier whose description fits the task; use `heavy` only for
multi-step reasoning or hard analysis; omit `model_tier` when unsure. Shipped
caps in the repo's agent files (starting point, adjustable):

| Agent | min_tier | max_tier |
|-------|----------|----------|
| pdf-assistant, scheduler, server-ops | none | `standard` |
| researcher, data-analyst, repo-helper, log-analyst, vault-librarian, usage-analyst, email-assistant, triage-assistant | none | none |
| reviewer, planner | `standard` | none |

(`ember` itself and Laya triage get no caps.)

**Note:** `agents/*.json` and `gateways/<provider>/*.json` are tracked directly. Agent caps and gateway models are edited in those files; the admin UI writes the same agent definitions.

## Data flow

1. User asks ember something.
2. Ember's roster (from the registry) lists each specialist with its allowed
   tiers and `use_for`.
3. Ember calls `delegate_to_agent(agent_id="researcher", question=..., model_tier="light")`.
4. The `researcher` process receives `model_tier`, clamps it to its own range,
   picks the model id, and runs its tool loop on that model.
5. The answer returns with `model`, `model_tier`, `model_note`; usage rows
   record the tier.

## Error handling

- Unknown or disallowed tier: never an error; clamp with a note (a failed
  delegation wastes a round and the model cannot fix it better than the clamp
  does).
- Gateway block with a malformed `models`: `ValueError` at load, naming
  gateway and field; the supervisor fails once, loudly, like other bad config.
- `min_tier`/`max_tier` out of order or unknown name: `AgentSpecError` naming
  the file.
- A cap that leaves no tier the gateway defines: warning at startup, behaves
  as no choice (default model).

## Testing (pytest, `apps/ai_agent/tests/`)

- `llm_config`: `tiers()` parses a block, drops an unresolved-placeholder tier,
  rejects an unknown tier name and a missing `use_for`, returns `{}` without
  `models`.
- `agent_spec`: accepts `min_tier`/`max_tier`; rejects unknown names,
  `min` above `max`, and use on Laya.
- `model_tiers.resolve`: exact match; below range clamps up; above range clamps
  down; gateway lacks the tier, so nearest, ties to the weaker; `None` and
  invalid string; no effective tiers.
- `delegation`: schema has no `model_tier` when no specialist has 2+ tiers;
  description lists tiers only for specialists that offer a choice; `call`
  passes `model_tier` to `ask`; result carries the clamp note.
- `server.ask` / `agent_config.run_chat`: with `model_tier="light"` the provider
  receives the light model id; without it, the old default; a cap overrides a
  too-strong request.
- Existing delegation, roster and provider tests pass unchanged.

## Files touched

`gateways/<provider>/<gateway>.json`, `src/llm/llm_config.py`,
`src/llm/model_tiers.py` (new), `src/agents/agent_spec.py`,
`src/agents/agent_registry.py`, `src/agents/agent_routing.py`,
`src/agents/delegation.py`, `src/agents/agent_config.py`, `src/server.py`,
`src/llm/anthropic_provider.py`, `src/llm/openai_provider.py` (dispatch only),
`src/core/usage_log.py`, `agents/*.json` (caps, ember instructions),
`src/README.md` / `configs/README.md`, tests.

## Decisions

- **Fixed ladder, not free-form names.** Needed for comparable caps and one
  vocabulary for the orchestrator.
- **Cap lives in the agent's `llm` block.** It describes model use, and the
  existing `_LLM_KEYS` validation covers it.
- **Clamp, not reject.** See Error handling.
- **Agent enforces its own cap.** The orchestrator's view can be stale or
  bypassed; the specialist is the authority.
- **Registry carries tiers.** Avoids cross-process gateway config reads, and
  matches how `focus` already reaches the roster.
