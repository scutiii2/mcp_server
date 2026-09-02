# mcp_client_template

A minimal, standalone MCP *client* - a template to copy when building an
app that needs to pull tools from several MCP servers at once: this
repo's own `mcp_server` hub, other custom servers reached directly
(`crafty_mcp_server`, a copy of `mcp_server_ext`), and ordinary
third-party MCP servers (Gmail, or anything else). Not wired into
anything itself: no other project in this repo imports or depends on
this folder.

It's the client-side counterpart to `mcp_server_ext/` (a template for
building a new MCP *server*) and generalizes the aggregation pattern
already proven in
[`mcp_server/src/infra/extensions.py`](../mcp_server/src/infra/extensions.py) -
connect out to N servers, merge their tool lists under a namespaced
name, dispatch calls by namespace, isolate each server's failures from
the others. The difference: this has no tools of its own, so every
configured server - including `mcp_server` itself - is symmetric.

## What's here

- `src/config.py` - loads and validates `configs/config_servers.json`.
- `src/transports.py` - opens a session for one server (stdio or HTTP),
  resolving its `auth` block into HTTP headers.
- `src/registry.py` - `McpClientRegistry`: connects to every configured
  server, merges their tools into one namespaced catalog, dispatches
  calls. Async.
- `src/sync_wrapper.py` - `SyncMcpClient`: optional blocking wrapper
  around `McpClientRegistry` for a synchronous host app.
- `src/_fixtures/reference_server.py` - a trivial stdio server (`echo`,
  `add`) used only by this template's own tests.

To build a real client: copy this whole folder into your project, rename
it and the `name =` in `pyproject.toml`, drop `src/_fixtures/` (it exists
only for this template's own tests), and write your config_servers.json
- see [Configuring servers](#configuring-servers) below. Keep everything
else (own venv, the async-first `McpClientRegistry`, the optional
`sync_wrapper.py`) as-is unless you have a reason to change it.

## Setting it up standalone

From your copy of this folder (own venv, separate from this repo's
shared `venv_mcp` - a copy living in a different project won't have that
available):

```
python -m venv .venv
.venv\Scripts\activate      # Windows; `source .venv/bin/activate` on Linux/macOS
pip install -e ".[dev]"
```

Then follow [Configuring servers](#configuring-servers) and
[Using it](#using-it-async) below - there's no `mcp.run(...)` entry
point to launch here, since this is a client library, not a server; your
own app's code is what calls into it.

## Configuring servers

Copy `configs/config_servers.json.example` to `configs/config_servers.json`
and edit it. Three examples are included, one per category:

- **`main`** - this repo's own `mcp_server`, reached over HTTP the same
  way `chat_app` does today.
- **`crafty`** - a custom server (`crafty_mcp_server`) reached *directly*
  over HTTP, bypassing `mcp_server`'s own extension proxy. Point this at
  a copy of `mcp_server_ext` the same way.
- **`gmail`** - a placeholder for a "normal" third-party MCP server.
  Replace `url` with the real endpoint; `auth.type: "bearer_env"` reads
  the bearer token from the named environment variable at connect time
  (never store the token in the config file itself).

Each entry is either `"transport": "http"` (needs `url`) or
`"transport": "stdio"` (needs `command`, optionally `args`) - never both.
The optional `auth` block supports three types:

| `type`        | Extra fields                    | Effect                                            |
|---------------|----------------------------------|----------------------------------------------------|
| `none`        | (default if `auth` is omitted)   | No extra headers.                                  |
| `header`      | `header_name`, `header_value`    | A fixed extra header (e.g. a static API key).      |
| `bearer_env`  | `env_var`                        | `Authorization: Bearer <value of that env var>`.   |

A malformed entry raises `ConfigError` as soon as `load_servers_config()`
runs - a bad config fails loudly at startup rather than as a confusing
connect failure later.

## Using it (async)

```python
import asyncio
from pathlib import Path

from src.registry import McpClientRegistry

async def main() -> None:
    registry = McpClientRegistry()
    await registry.connect_all(Path("configs/config_servers.json"))

    for tool in await registry.list_tools():
        print(tool.name)  # e.g. "main__ping_host", "crafty__crafty_world_start"

    result = await registry.call_tool("crafty__crafty_world_list", {})
    print(result.structuredContent)

    await registry.aclose()

asyncio.run(main())
```

## Using it (sync host apps)

```python
from pathlib import Path
from src.sync_wrapper import SyncMcpClient

client = SyncMcpClient()
client.connect_all(Path("configs/config_servers.json"))
tools = client.list_tools()
result = client.call_tool("main__ping_host", {"host": "example.com"})
client.close()
```

Prefer this over reconnecting per call (the way `chat_app`'s current
single-server client does) whenever the host app is synchronous but
still wants persistent connections - especially important for stdio
subprocess servers, where reconnecting per call means respawning a
process every time.

## Tests

Inside this repo, from the repo root, using the shared `venv_mcp`:

```
venv_mcp/Scripts/python.exe -m pytest mcp_client_template/tests -v
```

In a standalone copy (see [Setting it up standalone](#setting-it-up-standalone)
above), from your own venv instead:

```
pytest tests -v
```

## Not in this template (yet)

- Runtime add/remove-server routes - `mcp_server`'s own `/extensions`
  endpoints already cover that for its own extensions; this template is
  a library, not an admin surface.
- Real OAuth token-refresh flows - the `auth` block is shaped so this
  can be added later (a fourth `auth.type`) without a redesign.

See
[`docs/superpowers/specs/2026-09-03-mcp-client-template-design.md`](../docs/superpowers/specs/2026-09-03-mcp-client-template-design.md)
for the full design rationale.
