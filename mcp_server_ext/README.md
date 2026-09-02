# mcp_server_ext

A minimal, standalone MCP server - a template to copy when building a
real extension for `mcp_server` (see
[`mcp_server/src/infra/extensions.py`](../mcp_server/src/infra/extensions.py)).
Not wired into anything itself: running `mcp_server` never imports or
depends on this folder.

## What's here

`src/server.py` is a single-file example showing the shapes a real
extension usually needs:

- `echo` - the simplest possible tool.
- `summarize_numbers` - a tool with a typed list argument and a
  structured dict return, to show what FastMCP derives a tool's JSON
  schema from.
- `greeting://{name}` - a resource template (URI-addressed, read-only
  data instead of an action).

To build a real extension: copy this whole folder, rename it, replace
the example tools/resources with your own, and keep everything else
(own venv, `pyproject.toml`, the `mcp.run(transport="streamable-http")`
entry point) as-is unless you have a reason to change it.

## Running it

From `mcp_server_ext/`:

```
python -m venv .venv
.venv\Scripts\activate      # Windows; `source .venv/bin/activate` on Linux/macOS
pip install -e .
python -m src.server
```

Defaults to `http://127.0.0.1:9000/mcp` - override with the
`MCP_EXT_HOST` / `MCP_EXT_PORT` environment variables.

## Wiring it into mcp_server

Add an entry to `mcp_server/src/configs/config_extensions.json`
(mirroring the `"example-http"` entry already in that file's
`.example` twin):

```json
{
  "my-extension": {
    "label": "My Extension",
    "description": "What it does.",
    "url": "http://127.0.0.1:9000/mcp"
  }
}
```

`mcp_server` picks this up at startup (or immediately via
`POST /extensions` - see `extension_routes.py`), and every tool this
server exposes shows up in `mcp_server`'s own tool list, namespaced
`my-extension__<tool name>` - see
[`mcp_server/src/infra/extensions.py`](../mcp_server/src/infra/extensions.py)
for the full mechanism.
