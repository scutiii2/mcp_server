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
  console script). Loads secrets, reads the capability toggle, wires up
  every enabled capability/resource, and serves.
- `server.py` - the shared `FastMCP` instance every capability/resource
  registers onto.
- `config.py` - `Settings`, the process-level env-var-driven
  configuration (bind host/port, where `configs/`/`data/`/`logs/` live).
- `commands.py` - the `@command` registry backing chat_app's `/`
  slash-command autocomplete; capability id is inferred from the
  decorated function's module path.
- `errors.py` - turns an unexpected exception into a safe-to-display
  message plus a logged reference id.
- `approval_routes.py`, `extension_routes.py`, `command_routes.py` -
  plain HTTP routes (not MCP tools) mounted alongside the MCP surface:
  where a human approves a gated action, where extensions are
  listed/added/removed, and where chat_app discovers slash commands.

## Runtime data (not code)

- **[`configs/`](configs/README.md)** - structured settings, mostly
  committed.
- **[`secrets/`](secrets/README.md)** - credential values, gitignored.
- **[`data/`](data/README.md)** - runtime state shared across
  capabilities.
- `logs/` - `server.log` plus one file per error reference id,
  regenerated on every run, entirely gitignored.

See the root [`../README.md`](../README.md) for setup instructions.
