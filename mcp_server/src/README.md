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
- **[`services/`](services/README.md)** - shared clients (SSH, email, the
  config-file loader, the pending-requests store) every capability
  reuses.
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
  configuration (bind host/port, where `configs/`/`.data/`/`.logs/` live).
- `commands.py` - the `@command` registry backing chat_app's `/`
  slash-command autocomplete; capability id is inferred from the
  decorated function's module path.
- `errors.py` - turns an unexpected exception into a safe-to-display
  message plus a logged reference id.
- `extension_routes.py`, `command_routes.py`,
  `capability_routes.py` - plain HTTP routes (not MCP tools) mounted
  alongside the MCP surface: where extensions are listed/added/removed, where chat_app discovers
  slash commands, and where a capability is turned on/off live.

## Runtime data (not code)

All runtime-data folders live one level up, at the project root rather
than under `src/` - nothing in them is package code, so they don't need
to sit alongside the modules that write to them:

- **[`../configs/`](../configs/README.md)** - structured settings,
  mostly committed.
- **[`../.secrets/`](../docs/secrets.md)** - credential values,
  gitignored.
- `../.data/` - runtime state shared across capabilities, gitignored.
- `../specifics/<capability_name>/` - state and config one capability
  owns outright (`.data/`, `.logs/`, `.cache/`, `.secrets/` gitignored;
  `configs/` tracked).
- `../.logs/` - `server.log` plus one file per error reference id,
  regenerated on every run, entirely gitignored.

See the root [`../README.md`](../README.md) for setup instructions.
