# src/

The `src` package - installed under that literal name (see
`../pyproject.toml`), so every import in this codebase reads
`from src.<group>.foo import bar`, matching `mcp_server` and `ember_api`.

## Code

Entry points stay at the package root; everything else is grouped by concern.

- `server.py` - FastMCP entry point; `ask`/`interpret`/`status`/`cancel`/`decide`
  tools. `interpret` is the non-agentic, single-completion path ember_api
  uses for chat summarization; `ask` is the full tool-calling loop for
  free-form chat; `decide` answers a tool waiting for approval.
- `supervisor.py` - `python -m src.supervisor` (what `run.bat` runs):
  spawns one `src.server` child per enabled agent file, relays output,
  restarts crashed children with backoff.

### [`agents/`](agents/) - agent identity, delegation

- `agent_spec.py` - loads and validates one `agents/<id>.json` (identity,
  port, `llm`, `orchestrator`) into the process-wide
  `AgentSpec` the other modules read.
- `agent_config.py` - resolves the pinned provider+model from
  `.env` once at startup; fails loudly on a bad
  config.
- `delegation.py`, `agent_registry.py` - lets one agent hand a focused
  sub-question to another configured specialist mid-loop via a
  `delegate_to_agent` tool. An agent never lists itself in its roster;
  orchestrators delegate to specialists only. Bounded by a depth cap (2 hops) so a
  delegation chain can't run away. `agent_registry.py`'s
  `register()`/`deregister()` also upsert/remove this instance's own
  `{id, label, url}` in `../.data/agent_registry.json` (runtime state,
  gitignored) on startup/clean shutdown; ember_api reads it.
- `llm/model_tiers.py` - which model strength tiers an agent offers and how a requested tier resolves (clamped to the agent's min_tier/max_tier).
- `llm/reasoning_effort.py` - the reasoning effort (off/low/medium/high) an orchestrator may request of an agent; a request above the agent's `llm.max_effort` runs at the cap. Applied per turn through `llm_options.bind_effort`.
- `agent_routing.py` - per-turn roster of specialists for an orchestrator.
- `agent_events.py` - the progress events a specialist emits and an
  orchestrator re-emits upward (`agent_*`).

### [`llm/`](llm/README.md) - provider backends

Claude and OpenAI only, calling `mcp_client/mcp_upstream.py` for tools
(originally adapted from the retired chat_app's LLM layer).
`llm/llm_options.py` holds the per-agent LLM options (gateway, model,
limits) resolved from the agent file.

### [`mcp_client/`](mcp_client/) - upstream MCP connection

- `registry.py`, `config.py`, `transports.py`, `sync_wrapper.py` - a
  generic MCP-client layer (`McpClientRegistry`/`SyncMcpClient`), giving
  this project a persistent, namespaced connection to `mcp_server` instead
  of reconnecting per call.
- `mcp_upstream.py` - the only one adapted for this project's specific
  single-upstream, enabled-extensions-filtered use.
- `tool_progress.py` - per-tool progress reporting.

### [`core/`](core/) - shared plumbing

- `catalog.py`, `seed.py`, `config_files.py` - `@catalog` stub, `.example`
  seeding, and the paths/readers for `../configs/`.
- `internal_auth.py` - internal API token and requester identity.
- `chat_history.py` - accepts only caller-supplied `{role, content}` messages
  with a `user`/`assistant` role and string content. Privileged roles, extra
  fields, and structured tool activity are rejected before provider setup or
  history trimming; providers generate tool calls/results within their own loop.
- `approvals.py` - per-call tool approval handling.
- `usage_log.py` - append-only per-agent usage log.

Agent system prompts include a fixed instruction-priority rule, including in
the admin preview and with custom prompt text. User messages, documents, and
tool results cannot authorize replacing the configured identity, scope, or
instructions. This strengthens prompt-injection resistance; model adherence
is not guaranteed, so access controls and tool restrictions still need code
enforcement. Caller-supplied assistant text is conversation context, not
verified evidence of authorization.

## Runtime data (not code)

All runtime-data folders live one level up, at the project root rather
than under `src/` - nothing in them is package code, so they don't need
to sit alongside the modules that write to them:

- **[`../configs/`](../configs/README.md)** - structured settings,
  mostly gitignored (this project's real config files carry
  deployment-specific tuning, unlike `mcp_server`'s).
- **`../.env`** - credential values (provider, gateway, role, API keys,
  `INTERNAL_API_TOKEN`), gitignored; `../.env.example` is the committed twin.

- **`../.data/`** - state the program writes, gitignored:
  `agent_registry.json` (the running agents, see `agents/agent_registry.py`),
  `agent_definitions.json` (every agent file, enabled or not; the supervisor
  writes it at start) and `usage/YYYY-MM-DD.<agent id>.jsonl` (one usage row per finished `ask`,
  see `core/usage_log.py`; `AI_AGENT_USAGE_DIR` overrides the folder).

There is no `logs/` folder and no database: output goes to the console
(the supervisor prefixes each line with `[<agent id>] `), and
`ask`/`status`/`cancel` keep no state beyond the in-process registries
above and the registry and usage log in `.data/`.

See the root [`../README.md`](../README.md) for setup instructions.
