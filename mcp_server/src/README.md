# src/

The `src` package - installed under that literal name (see
`../pyproject.toml`'s wheel target), so every import in this codebase
reads `from src.foo import bar`, matching chat_app's layout.

## Code

- **[`capabilities/`](capabilities/README.md)** - one folder per
  model-callable tool. Start here for "how do I add a new thing this
  server can do."
- **[`resources/`](resources/README.md)** - one folder per
  client-readable URI resource.
- **[`infra/`](infra/README.md)** - shared clients (SSH, email, the
  config-file loader, the pending-requests store) every capability
  reuses.
- **[`services/`](services/README.md)** - business logic that spans more
  than one capability or infra client. Empty today.
- **[`utils/`](utils/README.md)** - small, single-purpose helpers with
  no knowledge of any specific capability.
- **[`_fixtures/`](_fixtures/README.md)** - test-only scaffolding, not
  production code.
- `run.py` - the entry point (`python -m src.run`, or the `mcp-server`
  console script). Loads secrets, imports `imports.py` (below), and
  serves.
- `imports.py` - imports every built-in capability/resource onto `mcp`
  and applies its configured enabled/disabled state. Split out of
  `run.py` so the list (which grows by one block per capability, see
  `capabilities/README.md`'s "Add a new capability") doesn't crowd out
  `run.py`'s own job.
- `server.py` - the shared `FastMCP` instance every capability/resource
  registers onto.
- `tool_response.py` - `respond()`, wraps a capability's result model
  into a `CallToolResult` whose visible text is that model's own
  `report`/`message` field instead of a JSON dump. Every `tool.py`
  return statement goes through this - see
  `capabilities/README.md`'s "Chat-readable results, not JSON".
- `config.py` - `Settings`, the process-level env-var-driven
  configuration (bind host/port, where `configs/`/`data/`/`logs/` live).
- `commands.py` - the `@command` registry backing chat_app's `/`
  slash-command autocomplete; capability id is inferred from the
  decorated function's module path.
- `errors.py` - turns an unexpected exception into a safe-to-display
  message plus a logged reference id.
- `approval_routes.py`, `extension_routes.py`, `command_routes.py`,
  `capability_routes.py` - plain HTTP routes (not MCP tools) mounted
  alongside the MCP surface: where a human approves a gated action,
  where extensions are listed/added/removed, where chat_app discovers
  slash commands, and where a capability is turned on/off live.

## Runtime data (not code)

- **[`configs/`](configs/README.md)** - structured settings, mostly
  committed.
- **[`secrets/`](secrets/README.md)** - credential values, gitignored.
- **[`data/`](data/README.md)** - runtime state shared across
  capabilities.
- `logs/` - `server.log` plus one file per error reference id,
  regenerated on every run, entirely gitignored.

See the root [`../README.md`](../README.md) for setup instructions.
