# ai_agent multi-agent (Phase 1) — design

Date: 2026-10-04
Status: approved in brainstorming, awaiting spec review
Scope: `ai_agent/` only. Phase 2 (`ember_api` + `ember_web`) is in
`2026-10-04-ember-multi-agent-design.md` and builds on the contracts defined here.

## Goal

Run several ai_agent instances at once, each defined by one file in
`ai_agent/agents/`, each with its own persona, focus, LLM settings and tool
scope. One agent is the orchestrator: it hands sub-questions to specialists,
optionally using Laya to pick which specialist fits. Token usage stays
traceable per agent, per provider and gateway, with timestamps. Every change in
this phase is additive: today's ember_api, ember_web and chat_app keep working
unchanged.

## Non-goals

- One process hosting many agents (approach B). Each agent stays its own process.
- Any change to chat_app code. chat_app is being sunset.
- Any visible ember change. That is Phase 2.
- Usage log retention or rotation.
- Specialist-to-specialist delegation. Delegation is hub-and-spoke.

## Architecture

```
run.bat -> py -m src.supervisor
            reads ai_agent/agents/*.json, validates all of them first
            spawns per enabled file: python -m src.server
                env AI_AGENT_FILE=<path>, AI_AGENT_PORT=<port>
            prefixes each child's stdout with "[<agent id>] "
            restarts a crashed child with backoff
            on exit, stops every child
```

- A child is today's `src/server.py`. When `AI_AGENT_FILE` is set it builds its
  configuration from that file; otherwise it builds the same in-memory spec from
  the existing env vars (`AI_AGENT_PROVIDER`, `AI_AGENT_GATEWAY`,
  `AI_AGENT_MODEL`, `AI_AGENT_ROLE`, `AI_AGENT_PORT`). The env-var path keeps dev
  runs and the existing tests working.
- server_launcher still sees one ai_agent instance (the supervisor), because
  `run.bat` now runs the supervisor module.
- Laya is loaded in a child whose file has `routing.laya: true` or
  `routing.allow_auto: true` (or whose tool shortlisting is on, as today).

## Agent file

Location: `ai_agent/agents/<id>.json`. The agent id is the file name stem and
must match `^[a-z0-9][a-z0-9-]{0,62}$`. `ai_agent/agents/` is gitignored;
`ai_agent/agents.example/` is committed and is copied into `agents/` on first
run when `agents/` is missing or empty, matching the `.example` convention in
`configs/`.

```json
{
  "label": "Calculator",
  "port": 9103,
  "enabled": true,
  "entry": false,
  "llm": {
    "provider": "anthropic",
    "gateway": "openrouter",
    "model": "claude-sonnet-5-5",
    "temperature": 0.0,
    "reasoning_effort": "high",
    "max_tokens": 4096,
    "max_tool_rounds": 6
  },
  "persona": "You are a precise mathematician. Show every step and check results.",
  "focus": "Arithmetic, algebra, percentages, unit conversion, compound interest.",
  "tools": { "allow": ["calc_*", "convert_*"], "deny": [] },
  "orchestrator": false
}
```

### Fields

| Field | Required | Default | Meaning |
|---|---|---|---|
| `label` | no | id | Display name. |
| `port` | yes | — | Port the child listens on. Unique across enabled files. |
| `enabled` | no | `true` | `false`: not spawned, not registered. |
| `entry` | no | `false` | The agent ember sends new turns to (Phase 2). Exactly one enabled file must set it. |
| `llm.provider` | yes | — | `anthropic` or `openai` (keys of `_PROVIDERS` in `agent_config.py`). |
| `llm.gateway` | no | provider default | A gateway key from `configs/config_llms.json` under that provider. |
| `llm.model` | no | gateway's `model` | Model id. |
| `llm.temperature` | no | unset (provider default) | Float 0–2. |
| `llm.reasoning_effort` | no | `off` | `off`, `low`, `medium`, `high`. Maps to the Anthropic thinking budget or OpenAI `reasoning_effort`. |
| `llm.max_tokens` | no | today's hard-coded value | Output token cap per model call. |
| `llm.max_tool_rounds` | no | `6` | Cap on the tool loop. |
| `persona` | no | `""` | Persona text placed in the system prompt. |
| `focus` | no | `""` | One-line summary of what the agent is good at. Used for the orchestrator roster and for Laya routing. Should be concrete. |
| `tools.allow` | no | `[]` (all) | fnmatch globs on mcp_server tool names without the `main__` prefix. Empty means all tools. |
| `tools.deny` | no | `[]` | Globs removed after `allow`. Deny wins. |
| `orchestrator` | no | `false` | Gets `delegate_to_agent` and the roster. |
| `routing.laya` | no | `false` | Use Laya to shortlist the roster each turn. Orchestrators only. |
| `routing.top_k` | no | `3` | Roster size after the Laya shortlist. |
| `routing.allow_auto` | no | `false` | Offer `agent_id: "auto"` on `delegate_to_agent`. `"auto"` always uses Laya to pick, regardless of `routing.laya`. |
| `routing.min_score` | no | unset | Signed cosine similarity (-1..1). `"auto"` errors when the best match scores below it; skipped when Laya returns no scores (only one specialist). |

The `routing.*` fields are only allowed when `orchestrator` is true; `agent_spec` rejects a file that sets them on a non-orchestrator.

An orchestrator file adds the routing block:

```json
{
  "port": 9100,
  "entry": true,
  "llm": { "provider": "anthropic" },
  "orchestrator": true,
  "routing": { "laya": true, "top_k": 3, "allow_auto": true, "min_score": 0.2 }
}
```

Unknown keys are an error, so typos are caught at startup.

### Validation (supervisor, before spawning anything)

The supervisor refuses to start, and names the file and field, when:

- a file is not valid JSON, has an unknown key, or a field has the wrong type or range;
- `port` or `llm.provider` is missing;
- two enabled files share a port;
- the number of enabled files with `entry: true` is not exactly one;
- `routing.*` is set on a non-orchestrator;
- an id does not match the id pattern.

Gateway names and API keys are not checked by the supervisor; the child already
fails loudly at import for those (`AgentConfigError`), and the supervisor treats
that as a crash (see Errors).

### Shared prompt parts

`configs/config_ai_agent_roles.json` keeps `app_name`, `app_description` and
`tool_use_instructions`. Its `roles` map and `default_role` remain only for the
env-var path (`AI_AGENT_ROLE`). An agent file's `persona` replaces the role
persona.

System prompt order: identity line, persona, roster (orchestrators only),
tool_use_instructions.

### Migration

`agents.example/` ships:

- `claude-agent.json` — port 9100, `llm.provider: anthropic`, `entry: true`,
  `orchestrator: true`, persona from today's default role.
- `openai-agent.json` — port 9102, `llm.provider: openai`.

These keep today's two registry ids (`claude-agent`, `openai-agent`), so stored
chat turns that name them keep resolving; `openai-agent.json` uses port 9102
(older example configs used 9101). New specialists are added
as extra files.

## Supervisor (`src/supervisor.py`)

- Async (`asyncio`), using `asyncio.create_subprocess_exec` for each child, so
  reading child output never blocks other children.
- Child command: the same interpreter (`sys.executable`) with `-m src.server`,
  plus the env vars above. Child stdout and stderr are merged and each line is
  written to the supervisor's stdout as `[<id>] <line>`.
- Startup: validate all files; remove registry entries whose id matches an agent
  file (leftovers from a crashed run) using `agent_registry.deregister`; spawn
  children.
- Crash (child exits while the supervisor is running): call
  `agent_registry.deregister(id)` on its behalf, then restart after a backoff of
  1s, 2s, 4s… capped at 60s. After 5 crashes within 5 minutes the child is
  marked failed and not restarted; the supervisor logs this and keeps the
  others running.
- Shutdown (Ctrl+C, SIGTERM, or the supervisor exiting): send each child a
  terminate, wait up to 10s, then kill. Children deregister themselves on clean
  exit; the supervisor deregisters any that did not.
- Registry entries the supervisor does not own (an id with no agent file, for
  example a dev `server.py` on another port) are never touched.

## Registry

Each child calls `agent_registry.register` with its agent id (not the
provider-derived id). On the env-var path the id is still
`agent_id_for(provider)`, so it stays `claude-agent` or `openai-agent`.

Registry entry, in both `config_agents.json` copies (ai_agent and chat_app):

```json
{
  "id": "calculator",
  "label": "Calculator",
  "url": "http://127.0.0.1:9103/mcp",
  "entry": false,
  "orchestrator": false,
  "focus": "Arithmetic, algebra, percentages, unit conversion, compound interest."
}
```

The new keys are optional for readers. A missing `entry` or `orchestrator` reads
as `false`, a missing `focus` as `""`. Today's readers (ember_api's
`AgentDirectory`, chat_app's registry) only read `id`, `label` and `url`, so
they are unaffected. chat_app's copy keeps being written until chat_app is
retired; its dropdown will list every agent, which is accepted.

`register` gains keyword arguments for the new keys. Its existing file lock is
reused.

## Per-agent runtime settings

- **Tool scope:** the list of mcp_server tool schemas offered to the model is
  filtered by `tools.allow` / `tools.deny` before tool shortlisting. A glob that
  matches no tool logs one warning at startup. A model calling a tool outside
  the scope gets a tool error, the same as an unknown tool today.
- **delegate_to_agent:** offered only when `orchestrator: true`. Specialists
  never get it. `_MAX_DELEGATION_DEPTH` stays 2.
- **LLM knobs:** `temperature`, `reasoning_effort`, `max_tokens` and
  `max_tool_rounds` are passed into both providers. A model that rejects a
  parameter (unsupported `temperature` with thinking, or `reasoning_effort` on a
  non-reasoning model) logs one warning and the parameter is dropped for that
  agent from then on.

## Orchestrator

- **Roster:** built per turn from the registry: every registered agent with
  `orchestrator: false`, as lines of `<id> — <label>: <focus>`. Per turn means a
  specialist that starts or stops is reflected without a restart.
- **delegate_to_agent schema:** `agent_id` is an enum of the roster ids, plus
  `"auto"` when `routing.allow_auto` is true. The tool description lists the
  roster.
- An orchestrator may still answer directly when no specialist fits.
- An instance started from env vars (no agent file) is an orchestrator, so it
  still gets `delegate_to_agent`. The roster never includes the agent itself.

## Laya routing (`src/agent_routing.py`)

Reuses `ToolRanker` and `LayaToolRanker` from `src/tool_selection.py` (the same
shared ranker instance), with options `{agent_id: focus}`. Agents with an empty
`focus` are not ranked.

- **Roster shortlist:** when `routing.laya` is true and there are more than
  `routing.top_k` specialists, Laya ranks them against the user's question at
  turn start; only the top `top_k` go into the roster and the enum. With
  `top_k` or fewer specialists nothing is ranked.
- **Auto pick:** `delegate_to_agent(agent_id="auto", question=...)` ranks all
  registered specialists against the sub-question and delegates to the top one.
  The tool result begins with `Delegated to <id> (<label>).` so the model and
  the user can see the choice.
- **Score threshold:** `routing.min_score` (signed cosine similarity, -1..1,
  default unset). `"auto"` returns a tool error when the best match scores below
  it. The check is skipped when Laya returns no scores (only one specialist).
- **Failures:** Laya not installed, model load error, or ranking error → the
  roster falls back to all specialists, and `"auto"` returns a tool error asking
  the model to pick an explicit id. A turn is never blocked.
- Ranking runs on a worker thread (`anyio.to_thread.run_sync`).

## Live agent activity events

Every event an agent sends through `on_event` (`token`, `token_reset`,
`step_start`, `step_progress`, `step_end`, `usage`) gains `agent_id` and
`agent_label`.

New event types:

```json
{"type": "agent_start", "agent_id": "calculator", "agent_label": "Calculator",
 "delegated_by": "claude-agent", "question": "What is 15% of 2,340?",
 "step_id": "<delegate_to_agent step id>", "at": "2026-10-04T09:12:03.512Z"}
{"type": "agent_end", "agent_id": "calculator", "agent_label": "Calculator",
 "ok": true, "step_id": "<same>", "at": "2026-10-04T09:12:07.044Z"}
{"type": "agent_token", "agent_id": "calculator", "agent_label": "Calculator",
 "step_id": "<same>", "text": "15% of 2,340 is "}
```

- The orchestrator emits `agent_start` before a delegated call and `agent_end`
  after it (`ok: false` on error).
- `delegation._call_tool` passes a `progress_callback` to `session.call_tool`.
  Each progress message from the specialist (a JSON-encoded event) is decoded
  and re-emitted upward through a ContextVar sink (same pattern as
  `src/tool_progress.py`) into the orchestrator's `on_event`. The sink hops from
  the delegation worker thread back onto the orchestrator's event loop via
  `asyncio.run_coroutine_threadsafe`.
- A specialist's `token` events are re-emitted as `agent_token` (with the text)
  so they never mix into the orchestrator's answer stream; `token_reset`
  becomes `agent_token` with `"reset": true`. Its `step_*` events pass through
  with their own `agent_id`. Its `usage` events are dropped: the specialist's
  final usage still arrives in `agent_usage`.
- A specialist's step ids are its own, so a nested id can collide with one of
  the orchestrator's. Consumers must key steps on `(agent_id, id)`, never on
  `id` alone.
- Nested events from a second hop keep the innermost agent's `agent_id`.
- `at` is UTC ISO-8601 with milliseconds.

Compatibility: ember_api's relay (`ember_api/src/services/turns.py`) forwards
only known event types, so `agent_start`, `agent_end` and `agent_token` are
dropped by today's ember, and the extra keys on `step_*` events are ignored.

## Token usage

### agent_usage rows

Each row in the `ask` result's `agent_usage` list gains fields. Existing fields
stay.

```json
{
  "agent_id": "calculator",
  "agent_label": "Calculator",
  "provider_id": "anthropic",
  "gateway": "openrouter",
  "model": "claude-sonnet-5-5",
  "input_tokens": 1234,
  "output_tokens": 210,
  "total_tokens": 1444,
  "started_at": "2026-10-04T09:12:03.512Z",
  "finished_at": "2026-10-04T09:12:07.044Z",
  "delegated_by": "claude-agent"
}
```

- Each agent stamps its own row. `started_at` is when its `ask` began,
  `finished_at` when it returned. Delegated rows carry the specialist's times.
- `delegated_by` is `null` for the top-level agent.
- `gateway` is the resolved gateway key, or `null` for a provider used directly.
- Laya ranking uses no LLM tokens and produces no row.

### Usage log

Every child appends one JSON line per completed `ask` to
`ai_agent/data/usage/YYYY-MM-DD.<agent id>.jsonl` (UTC date), holding the row
above plus `request_id` and `depth`. This makes usage visible for callers that
bypass ember (chat_cli, direct MCP calls, tests).

- One file per agent per day, so no two processes write the same file. Within a
  child, appends are serialized with a `threading.Lock` around a write on a
  worker thread.
- A write failure logs a warning and never fails the turn.
- `ai_agent/data/usage/` is gitignored.

## Errors

| Case | Behavior |
|---|---|
| Invalid agent file (see Validation) | Supervisor exits before spawning, naming file and field. |
| Port already in use | That child fails to bind and exits; handled as a crash. |
| Missing API key or unknown gateway | Child exits at import (`AgentConfigError`); handled as a crash; marked failed after 5 tries. |
| Child crash | Deregister, restart with backoff, re-register on start. |
| Specialist down or erroring during a turn | `delegate_to_agent` returns a tool error naming the agent; `agent_end` with `ok: false`. |
| Laya failure | Full roster; `"auto"` returns a tool error asking for an explicit id. |
| Tool glob matches nothing | One warning at startup. |
| Unsupported LLM parameter | One warning, parameter dropped for that agent. |
| Usage log write fails | Warning; turn unaffected. |

## Testing (pytest, `ai_agent/tests`)

- Agent spec loading: defaults, every validation error, env-var fallback spec.
- Supervisor with fake child commands: spawn, line prefixing, crash →
  deregister + restart, backoff cap, failed after 5 crashes, clean shutdown,
  stale-entry cleanup, entries it does not own left alone.
- Registry: agent-id registration, new keys written, old entries without keys read.
- Tool scope: allow, deny, deny-wins, empty allow, unmatched glob warning;
  `delegate_to_agent` only for orchestrators.
- LLM knobs reach both providers (existing provider fakes); unsupported
  parameter dropped with a warning.
- Routing with a fake `ToolRanker`: shortlist above and at `top_k`, auto pick,
  failure fallbacks.
- Events: `agent_id` stamping, `agent_start`/`agent_end` around delegation,
  forwarding through a fake progress callback, `token` → `agent_token`,
  two-hop nesting.
- Usage: row shape, timestamps, `delegated_by`, JSONL append, write failure.
- All existing tests stay green.

## Files

New: `src/agent_spec.py` (load + validate), `src/supervisor.py`,
`src/agent_routing.py`, `src/agent_events.py` (stamping + forwarding sink),
`src/usage_log.py`, `agents.example/claude-agent.json`,
`agents.example/openai-agent.json`, tests for each.

Changed: `src/server.py`, `src/agent_config.py`, `src/llm/agent_roles.py`,
`src/llm/anthropic_provider.py`, `src/llm/openai_provider.py`,
`src/llm/base_provider.py`, `src/delegation.py`, `src/agent_registry.py`,
`run.bat`, `README.md`, `.gitignore`.
