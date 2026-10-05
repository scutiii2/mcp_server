# src/

The `src` package - installed under that literal name (see
`../pyproject.toml`), so every import in this codebase reads
`from src.<group>.foo import bar`, matching `chat_app`/`mcp_server`'s layout.

## Code

Entry points stay at the package root; everything else is grouped by concern.

- `server.py` - FastMCP entry point; `ask`/`interpret`/`status`/`cancel`
  tools. `interpret` is the non-agentic, single-completion path used for
  chat summarization; `ask` is the full tool-calling loop for free-form chat.
- `supervisor.py` - `python -m src.supervisor` (what `run.bat` runs):
  spawns one `src.server` child per enabled agent file, relays output,
  restarts crashed children with backoff.

### [`agents/`](agents/) - agent identity, routing, delegation

- `agent_spec.py` - loads and validates one `agents/<id>.json` (identity,
  port, `llm`, `orchestrator`, `routing`) into the process-wide
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
  `{id, label, url}` in `../data/agent_registry.json` (runtime state,
  gitignored) and `chat_app`'s copy, on startup/clean shutdown.
- `agent_routing.py` - per-turn roster of specialists for an orchestrator
  (optionally Laya-shortlisted) and the `agent_id="auto"` pick.
- `agent_events.py` - the progress events a specialist emits and an
  orchestrator re-emits upward (`agent_*`).

### [`llm/`](llm/README.md) - provider backends

Adapted from `chat_app/src/services/llm/` (Claude and OpenAI only),
calling `mcp_client/mcp_upstream.py` instead of chat_app's own MCP client.
`llm/llm_options.py` holds the per-agent LLM options (gateway, model,
limits) resolved from the agent file.

### [`mcp_client/`](mcp_client/) - upstream MCP connection

- `registry.py`, `config.py`, `transports.py`, `sync_wrapper.py` - a
  generic MCP-client layer (`McpClientRegistry`/`SyncMcpClient`), giving
  this project a persistent, namespaced connection to `mcp_server` instead
  of reconnecting per call.
- `mcp_upstream.py` - the only one adapted for this project's specific
  single-upstream, enabled-extensions-filtered use.
- `tool_selection.py`, `tool_progress.py` - Laya tool shortlist and
  per-tool progress reporting.

### [`core/`](core/) - shared plumbing

- `catalog.py`, `seed.py`, `config_files.py` - `@catalog` stub, `.example`
  seeding, and the paths/readers for `../configs/`.
- `internal_auth.py` - internal API token and requester identity.
- `approvals.py` - per-call tool approval handling.
- `usage_log.py` - append-only per-agent usage log.

## Runtime data (not code)

All runtime-data folders live one level up, at the project root rather
than under `src/` - nothing in them is package code, so they don't need
to sit alongside the modules that write to them:

- **[`../configs/`](../configs/README.md)** - structured settings,
  mostly gitignored (this project's real config files carry
  deployment-specific tuning, unlike `chat_app`/`mcp_server`'s).
- **`../.env`** - credential values (provider, gateway, role, API keys,
  `INTERNAL_API_TOKEN`), gitignored; `../.env.example` is the committed twin.

Unlike `chat_app`/`mcp_server`, this project has no `data/` or `logs/`
folder: it holds no database and does its own file logging nowhere -
`ask`/`status`/`cancel` are stateless beyond the in-process registries
above.

See the root [`../README.md`](../README.md) for setup instructions.
