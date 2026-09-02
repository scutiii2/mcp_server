# crafty_mcp_server

A standalone MCP server for controlling Minecraft worlds hosted on one
or more [Crafty Controller](https://craftycontrol.com/) instances - ten
tools: `crafty_world_register`, `crafty_world_remove`,
`crafty_world_list`, `crafty_world_start`, `crafty_world_stop`,
`crafty_world_restart`, `crafty_world_send_command`,
`crafty_world_get_status`, `crafty_set_default_base_url`, and
`crafty_ping_base_url`.

Extracted from `mcp_server`'s old built-in `crafty` capability so it can
run as its own process and be pulled into `mcp_server` (or any other MCP
client) as an extension, instead of living in-process.

## Running it

From `crafty_mcp_server/`:

```
python -m venv .venv
.venv\Scripts\activate      # Windows; `source .venv/bin/activate` on Linux/macOS
pip install -e ".[dev]"
python -m src.server
```

Defaults to `http://127.0.0.1:9100/mcp` - override with
`CRAFTY_MCP_HOST` / `CRAFTY_MCP_PORT`.

### Configuration

All via environment variables (no `secrets/*.env` loader here - this is
a much smaller project than `mcp_server`, so a plain `.env` you source
yourself, or your process manager's own env config, is enough):

- `CRAFTY_BASE_URL` / `CRAFTY_VERIFY_SSL` - the default Crafty Controller
  URL a `crafty_world_register` call falls back to when it doesn't name
  its own `base_url`. Same variable names `mcp_server`'s old capability
  used, in case a deployment had them set. Neither is required: you can
  always pass `base_url` explicitly, or call `crafty_set_default_base_url`
  at runtime instead (takes effect immediately, no restart).
- `CRAFTY_WORLDS_DB_PATH` - where the SQLite registry (world names,
  server ids, API tokens, verify_ssl, and the live-set default) lives.
  Defaults to `src/data/crafty_worlds.db`, relative to wherever you run
  the process from. Gitignored - see `.gitignore` in the repo root
  (`*.db` is ignored everywhere).

## Wiring it into mcp_server

Add an entry to `mcp_server/src/configs/config_extensions.json`:

```json
{
  "crafty": {
    "label": "Crafty",
    "description": "Control Minecraft worlds hosted on Crafty Controller.",
    "url": "http://127.0.0.1:9100/mcp"
  }
}
```

`mcp_server` picks this up at startup (or immediately via
`POST /extensions`), and every tool here shows up in `mcp_server`'s own
tool list, namespaced `crafty__crafty_world_register` etc. Slash commands
in chat_app become `/crafty crafty_world_register ...` (extension tools
are auto-registered under their real tool name, not a short alias - see
`mcp_server/src/services/commands.py` on chat_app's side).

## Live suggestions, proxied through

`src/suggestions.py` injects a live `enum` (currently-registered world
names, currently-known base URLs) into the relevant tools' schemas on
every `list_tools()` call - the same trick `mcp_server`'s own built-in
capabilities use for this. `mcp_server`'s extension proxy re-fetches
`list_tools()` from every connected extension on every call rather than
caching it from connect time, so those live values reach chat_app the
same way they would for a built-in capability - no special handling
needed on mcp_server's side for this project specifically. See
`mcp_server/src/infra/extensions.py`'s `merged_list_tools()` docstring
for the full mechanism, and this project's `src/server.py` for how the
suggestions get hooked into this server's own `list_tools()` response.

## Tests

```
pip install -e ".[dev]"
pytest
```
