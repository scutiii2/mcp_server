# mcp_server

A general-purpose MCP (Model Context Protocol) tool server: a proxy for other MCP
servers' tools ("extensions"), and a `server_manager` capability for
starting/stopping/restarting/listing managed apps. Built to be called by
`chat_app` or any other MCP client speaking streamable HTTP.

## Requirements

- Python >= 3.11
- An SMTP account for outbound mail (watcher notifications)


## Setup

1. Copy the `.example` files under `.secrets/` and `configs/` and
   fill in real values - see [Configuration](#configuration).

2. Run the server:

   ```
   run.bat
   ```

   (from `mcp_server/` - creates `.venv_mcp` and installs this project
   into it in editable mode on first run, then runs `py -m src.run`.)

## Configuration

Both loaded once at boot by `src/run.py`:

- **`.secrets/*.env`** - credentials, gitignored. Copy each
  `*.env.example` to the matching `*.env`. See
  [`docs/secrets.md`](docs/secrets.md).
- **`configs/*.json`** - structure, mostly committed. See
  [`configs/README.md`](configs/README.md).

## Code layout

See [`src/README.md`](src/README.md) for the full map - what lives
where, and where new code goes.

## Capabilities

Each tool this server offers lives under its own folder in
`src/capabilities/`, with its own README - see
[`src/capabilities/README.md`](src/capabilities/README.md) for the
shape every capability follows and how to add a new one:

- [`capabilities/server_manager`](src/capabilities/server_manager) - start/stop/restart/list managed apps (`/server ...`)

Every capability can be turned off without touching code, live - no
restart needed. `GET /capabilities` lists each one's current state;
`PATCH /capabilities/{name}` (body `{"enabled": bool}`) toggles it,
persists the change to `config_capabilities.json`, and adds/removes its
tools and resources from the running server, all in one request - see
`src/capability_routes.py` and `src/infra/README.md`'s
`capability_registry.py` entry. This is what chat_app's Capabilities
page's per-capability switch calls.

Client-readable URI resources follow the same pattern one level over -
see [`src/resources/README.md`](src/resources/README.md).

## Runtime state

Dot-prefixed folders hold untracked runtime state and secrets; plain
`configs/` folders are tracked.

- **`.data/`** - state shared across capabilities (`pending_requests.db`,
  `uploads/`).
- **`.logs/`** - `server.log` plus one file per error reference id,
  regenerated on every run.
- **`.cache/`** - regenerable shared cache, if any.
- **`specifics/<capability_name>/`** - the same layout (`.data/`,
  `.logs/`, `.cache/`, `.secrets/`, `configs/`) for state and config
  that a single capability owns outright. Only `configs/` is tracked.
  Documented in that capability's own README.

## Tests

```
pytest
```

## Docker

See `zima_host.yaml` for a ZimaOS "customized app" Docker Compose recipe.
