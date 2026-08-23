# mcp_server

A general-purpose MCP (Model Context Protocol) tool server: SSH host
health checks, email one-time-passcode verification, a human-approval
gate for irreversible actions, and a proxy for other MCP servers'
tools ("extensions"). Built to be called by `chat_app` or any other MCP
client speaking streamable HTTP.

## Requirements

- Python >= 3.11
- An SMTP account for outbound mail (OTP codes, approval-request emails)
- (optional) one or more SSH-reachable hosts for the host-health capability

## Setup

1. From `mcp_server/`, install dependencies:

   ```
   pip install -e ".[dev]"
   ```

2. Copy the `.example` files under `src/secrets/` and `src/configs/` and
   fill in real values - see [Configuration](#configuration).

3. Run the server:

   ```
   run_mcp_server.bat
   ```

   (from the repo root; activates `venv_mcp` and runs `py -m src.run`.)

## Configuration

Both loaded once at boot by `src/run.py`:

- **`src/secrets/*.env`** - credentials, gitignored. Copy each
  `*.env.example` to the matching `*.env`. See
  [`src/secrets/README.md`](src/secrets/README.md).
- **`src/configs/*.json`** - structure, mostly committed. See
  [`src/configs/README.md`](src/configs/README.md).

## Code layout

See [`src/README.md`](src/README.md) for the full map - what lives
where, and where new code goes.

## Capabilities

Each tool this server offers lives under its own folder in
`src/capabilities/`, with its own README - see
[`src/capabilities/README.md`](src/capabilities/README.md) for the
shape every capability follows and how to add a new one:

- [`capabilities/host_health/README.md`](src/capabilities/host_health/README.md)
- [`capabilities/otp/README.md`](src/capabilities/otp/README.md)

Every capability can be turned off without touching code - see
`src/configs/README.md`'s section on `config_capabilities.json`.

Client-readable URI resources follow the same pattern one level over -
see [`src/resources/README.md`](src/resources/README.md).

## Runtime state

- **`src/data/README.md`** - state shared across capabilities.
- Each capability's own `data/` folder (e.g.
  `capabilities/otp/data/`), when it has one - documented in that
  capability's own README.
- **`src/logs/`** - `server.log` plus one file per error reference id,
  regenerated on every run.

## Tests

```
pytest
```

## Docker

See `zima_host.yaml` for a ZimaOS "customized app" Docker Compose recipe.
