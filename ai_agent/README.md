# ai_agent

A standalone MCP agent, hard-pinned to one LLM provider+model, sitting
between `chat_app` and `mcp_server`:

```
chat_app  --(MCP: ask/interpret/status/cancel/decide)-->  ai_agent  --(MCP, persistent)-->  mcp_server
```

It is both an MCP *server* (to `chat_app`, exposing
`ask`/`interpret`/`status`/`cancel`/`decide`)
and an MCP *client* (to `mcp_server`, via a persistent connection - see
`src/mcp_upstream.py`). Run one agent per provider (see Agents) to back
`chat_app`'s Claude Agent / OpenAI Agent dropdown entries.

## Setup

1. Copy `secrets/secret_llm.env.example` to `secrets/secret_llm.env` and
   fill in `CLAUDE_API_KEY` and/or `GPT_API_KEY` (whichever provider(s)
   you're running), or the key(s) for whichever `AI_AGENT_GATEWAY` you're
   pointing at instead. Both can be set at once - one file backs every agent.

2. Make sure `mcp_server` is running (`mcp_server/run.bat`) -
   `ai_agent/configs/config_servers.json` points at its default
   `http://127.0.0.1:8010/mcp`.

3. Start the agents with `run.bat` (from `ai_agent/`). It creates
   `.venv_ai_agent` and installs this project into it in editable mode on
   first run, then runs `py -m src.supervisor`. See Agents below.

## Agents

Each ai_agent instance is defined by one file, `agents/<id>.json`. The file
name stem is the agent id (`^[a-z0-9][a-z0-9-]{0,62}$`). `agents/` is
gitignored; `agents.example/` is committed and is copied into `agents/` on
first run when `agents/` is missing or empty. Unknown keys are an error, so
typos are caught at startup.

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

| Field | Required | Default | Meaning |
|---|---|---|---|
| `label` | no | id | Display name. |
| `port` | yes | none | Port the child listens on. Unique across enabled files. |
| `enabled` | no | `true` | `false`: not spawned, not registered. |
| `entry` | no | `false` | The agent ember sends new turns to (Phase 2). Exactly one enabled file must set it. |
| `llm.provider` | yes | none | `anthropic` or `openai` (keys of `_PROVIDERS` in `agent_config.py`). |
| `llm.gateway` | no | provider default | A gateway key from `configs/config_llms.json` under that provider. |
| `llm.model` | no | gateway's `model` | Model id. |
| `llm.temperature` | no | unset (provider default) | Float 0-2. |
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
| `routing.min_score` | no | unset | Signed cosine similarity (-1 to 1). `"auto"` returns a tool error when the best match scores below it. Skipped when Laya returns no scores (only one specialist). |

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

Two examples ship in `agents.example/`: `claude-agent.json` (port 9100,
anthropic, `entry: true`, `orchestrator: true`) and `openai-agent.json`
(port 9102, openai). They keep today's two registry ids (`claude-agent`,
`openai-agent`), so stored chat turns that name them keep resolving;
`openai-agent.json` uses port 9102 (older example configs used 9101). Add
more specialists as extra files.

The gateway for a supervised agent comes from `llm.gateway` in
`agents/<id>.json`. Omitted, it is the provider's default gateway (`claude`
for anthropic, `gpt` for openai), pinned over `AI_AGENT_GATEWAY` and
`secret_llm.env`. `--gateway`, `--role`, `AI_AGENT_GATEWAY` and
`AI_AGENT_ROLE` only affect an instance started the old way (`python -m
src.server`, no agent file). Saved launcher presets that pass `--gateway` no
longer affect the supervisor.

Exactly one enabled file must set `entry: true`. The supervisor validates
every file before it starts anything and refuses to start, naming the file
and field, on a bad file, a shared port among enabled agents, or a wrong
number of entry agents.

`run.bat` starts all agents: it runs `python -m src.supervisor`, which
spawns one `python -m src.server` child per enabled file (env
`AI_AGENT_FILE`), prefixes each child's output with `[<agent id>] `, and
restarts a crashed child with backoff (1s, 2s, 4s... capped at 60s; left
stopped after 5 crashes within 5 minutes, the others keep running).

To run a single instance the old way (provider from env vars, no agent
file), skip `run.bat`:

```
set AI_AGENT_PROVIDER=openai
set AI_AGENT_PORT=9101
.venv_ai_agent\Scripts\python -m src.server --gateway openrouter
```

An instance started this way is an orchestrator, and `--gateway` takes
precedence over `AI_AGENT_GATEWAY`. Because `specialists()` excludes
orchestrators, two instances started the old way cannot delegate to each
other. The example above registers `openai-agent`, the same id as the shipped
`agents/openai-agent.json` - don't run both.

## Orchestrator and routing

An agent with `orchestrator: true` gets the `delegate_to_agent` tool;
specialists never do. Each turn the orchestrator's roster is built from the
registry: every registered agent that is not an orchestrator (and never the
agent itself), as lines of `<id> - <label>: <focus>`. Because it is per turn,
a specialist that starts or stops shows up without a restart. The
`agent_id` argument of `delegate_to_agent` is an enum of the roster ids. An
orchestrator may still answer directly when no specialist fits.

Routing options (`routing.*`, orchestrators only):

- `laya`: when true and there are more than `top_k` specialists with a
  `focus`, Laya ranks them against the user's question at the start of each
  turn and only the best `top_k` go into the roster. This flag only controls
  whether the roster is shortlisted.
- `top_k`: roster size after the shortlist (default 3).
- `allow_auto`: adds `"auto"` to the `agent_id` enum. `agent_id: "auto"`
  always uses Laya to choose the specialist for the sub-question, even when
  `routing.laya` is false. The tool result begins with
  `Delegated to <id> (<label>).`
- `min_score`: signed cosine similarity (-1 to 1, unset by default). `"auto"`
  returns a tool error when the best match scores below it, and the check is
  skipped when Laya returns no scores (only one specialist).

If Laya is not installed or fails, the roster falls back to every
specialist and `"auto"` returns a tool error asking the model to pick an
explicit id; a turn is never blocked. Laya is an optional extra:

```
pip install -e ".[laya]"
```

Specialist activity streams to the orchestrator's caller as `agent_start`,
`agent_end` and `agent_token` events, and a specialist's own `step_*`
events pass through stamped with its `agent_id`. A specialist's step ids can
collide with the orchestrator's, so consumers key on `(agent_id, id)`.

## Usage log

Every completed `ask` appends one JSON line to
`data/usage/YYYY-MM-DD.<agent id>.jsonl` (UTC date; one file per agent per
day, so no two processes write the same file). Each line is the `agent_usage`
row the `ask` result carries, plus `request_id` and `depth`:

- `agent_id`, `agent_label`
- `provider_id`, `gateway` (`null` when the provider is used directly), `model`
- `input_tokens`, `output_tokens`, `total_tokens`
- `started_at`, `finished_at` (UTC ISO-8601 with milliseconds)
- `delegated_by` (`null` for the top-level agent)
- `request_id`, `depth`

Set `AI_AGENT_USAGE_DIR` to write somewhere else. A cancelled turn writes no
line; only completed asks do. A write failure logs a warning and never fails
the turn. `data/usage/` is gitignored.

## Asking before tools run

`ask` takes `approval_mode` and `allowed_tools` (`src/approvals.py`):

- `off` (default): tools run as before. chat_app never sets a mode.
- `ask`: before each tool that is not in `allowed_tools`, the agent emits an
  `approval_request` event (tool, label, arguments) and waits. The tool runs only
  after the `decide(request_id, step_id, decision)` tool answers `allow` or
  `always` (also stop asking about that tool for the rest of the turn). `deny`,
  no answer within 4 minutes, or a Stop all mean it does not run, and the model
  is told so in place of a result. `delegate_to_agent` asks like any tool.
- `deny`: a tool that would need asking is refused at once. A delegated agent
  gets this from a turn that asks, since it cannot reach the user.

`status` reports `tool_approval: true`, so a caller that needs tools asked about
(ember_api) can refuse an older agent that would ignore the option.

## Roles

Copy `configs/config_ai_agent_roles.json.example` to
`configs/config_ai_agent_roles.json` before running - like `secret_llm.env`
above, the real file is gitignored so a fresh checkout only has the
`.example` twin, and `ai_agent` (and its tests) won't start without it.

To run with a specific AI agent persona (a set of system-prompt instructions
tailored to a domain or use case), pass `--role` or set `AI_AGENT_ROLE`:

```
python -m src.server --role ops_specialist
```

or in `secret_llm.env`:

```
AI_AGENT_ROLE=ops_specialist
```

The CLI flag takes precedence over the environment variable, which takes
precedence over the `default_role` in `configs/config_ai_agent_roles.json`.

An agent file's `persona` replaces the role. `AI_AGENT_ROLE` / `--role` apply
only to an instance started without an agent file.

An unknown role id fails loudly at startup, naming the bad id and the valid
alternatives - no silent fallback. Role selection is fixed for the process
lifetime; there is no per-request or runtime override.

One role ships out of the box:
- `generic` (the default) - empty persona, preserving the original hardcoded
  system prompt behavior.

To add a new role, edit `configs/config_ai_agent_roles.json` and add an entry
under `roles` with a `label` (human-readable name) and `persona`
(system-prompt instructions):

```json
{
  "my_role": {
    "label": "My Custom Role",
    "persona": "You are an expert in ... "
  }
}
```

No code change is required - the new role is available immediately on the next
process restart.

Agent files give each instance its own id, so any number of same-provider agents can run side by side.

## Security

- **`/mcp` needs the internal token** once `INTERNAL_API_TOKEN` is set in
  `secrets/secret_internal_api.env` (created from its `.example` on first
  run; same value as mcp_server's, chat_app's and ember_api's). Without it
  a request gets `401`. The agent sends the same token on its own calls to
  mcp_server and to peer agents (`src/internal_auth.py`).
- **The asking user travels on**: `ask()` reads `X-Requester-Username` /
  `X-Requester-Email` from the request (ember_api and chat_app set them),
  and every mcp_server tool it calls during that turn gets the user in the
  call's `_meta.requester` - the agent's one mcp_server session is shared by
  every user, so a header can't carry it. A delegated agent gets it as
  headers. The model never sets either.

## Project layout

- **`configs/*.json`** - structured settings, mostly gitignored. See
  [`configs/README.md`](configs/README.md).
- **`secrets/*.env`** - credential values, gitignored. See
  [`secrets/README.md`](secrets/README.md).

See [`src/README.md`](src/README.md) for the full code map - what lives
where, and where new code goes.

See
[`docs/superpowers/specs/2026-09-07-ai-agent-mcp-layer-design.md`](../docs/superpowers/specs/2026-09-07-ai-agent-mcp-layer-design.md)
for the full design rationale.
