# src/

The `src` package - installed under that literal name (see
`../pyproject.toml`), so every import in this codebase reads
`from src.foo import bar`, matching `chat_app`/`mcp_server`'s layout.

## Code

- **[`llm/`](llm/README.md)** - adapted from `chat_app/src/services/llm/`
  (Claude and OpenAI only), calling `mcp_upstream.py` instead of
  chat_app's own MCP client.
- `server.py` - FastMCP entry point; `ask`/`interpret`/`status`/`cancel`
  tools. `interpret` is the non-agentic, single-completion path used for
  chat summarization; `ask` is the full tool-calling loop for free-form chat.
- `agent_config.py` - resolves the pinned provider+model from
  `../secrets/secret_llm.env` once at startup; fails loudly on a bad
  config.
- `delegation.py`, `agent_registry.py` - lets one agent hand a focused
  sub-question to another configured agent (or itself) mid-loop via a
  `delegate_to_agent` tool. Bounded by a depth cap (2 hops) so a
  delegation chain can't run away. `agent_registry.py`'s
  `register()`/`deregister()` also upsert/remove this instance's own
  `{id, label, url}` in both `../configs/config_agents.json` and
  `chat_app`'s copy, on startup/clean shutdown.
- `mcp_upstream.py`, `registry.py`, `config.py`, `transports.py`,
  `sync_wrapper.py` - a generic MCP-client layer
  (`McpClientRegistry`/`SyncMcpClient`), giving this project a
  persistent, namespaced connection to `mcp_server` instead of
  reconnecting per call; `mcp_upstream.py` is the only one adapted for
  this project's specific single-upstream, enabled-extensions-filtered
  use.

## Runtime data (not code)

All runtime-data folders live one level up, at the project root rather
than under `src/` - nothing in them is package code, so they don't need
to sit alongside the modules that write to them:

- **[`../configs/`](../configs/README.md)** - structured settings,
  mostly gitignored (this project's real config files carry
  deployment-specific tuning, unlike `chat_app`/`mcp_server`'s).
- **[`../secrets/`](../secrets/README.md)** - credential values,
  gitignored.

Unlike `chat_app`/`mcp_server`, this project has no `data/` or `logs/`
folder: it holds no database and does its own file logging nowhere -
`ask`/`status`/`cancel` are stateless beyond the in-process registries
above.

See the root [`../README.md`](../README.md) for setup instructions.
