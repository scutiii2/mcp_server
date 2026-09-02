# mcp_client_template design

Status: approved for planning, not yet implemented.

## Problem

Today there is no reusable *client*-side template in this repo. The only
real MCP client is `chat_app/src/services/mcp_client.py`, and it is
hardcoded to a single upstream: `settings.mcp_server_url` (`mcp_server`).
Every other server-to-server connection (`mcp_server` → `crafty_mcp_server`,
`mcp_server` → a copy of `mcp_server_ext`) is aggregated **server-side**,
inside `mcp_server/src/infra/extensions.py`.

There is a template for building a new MCP *server* extension
(`mcp_server_ext/`, "copy this folder"), but nothing equivalent for
building a new MCP *client* that talks to several servers at once —
the main `mcp_server` hub, other custom servers directly (bypassing the
hub), and ordinary third-party MCP servers such as a Gmail integration.

## Goal

A standalone, copyable template folder — `mcp_client_template/` — that
any future app can drop in and configure to pull tools from an
arbitrary set of MCP servers, merged into one tool catalog, with one
`call_tool()` dispatch. It is a library, not a server: no HTTP
endpoints of its own.

Explicitly **not** in scope for this iteration:
- Replacing or touching `chat_app/src/services/mcp_client.py`. It keeps
  talking to `mcp_server` only, unchanged.
- Runtime add/remove-server HTTP routes. That capability already exists
  for extensions on `mcp_server`'s side; this template is a library
  used by a host process, not an admin surface.
- Real OAuth token-refresh flows. The auth config is shaped so this can
  be added later without a redesign, but no OAuth client is built now.

## Architecture

`mcp_client_template/` generalizes the proven pattern in
[`mcp_server/src/infra/extensions.py`](../../../mcp_server/src/infra/extensions.py):
connect out to N configured servers (stdio subprocess or streamable
HTTP), merge their tool lists under a namespaced name, dispatch calls
by namespace prefix, isolate each server's failures from the others.

The key difference from `extensions.py`: that module distinguishes
"this server's own FastMCP tools" from "proxied tools" because it *is*
a server with tools of its own. `mcp_client_template` has no tools of
its own — every configured server, including the main `mcp_server`, is
just another entry in the same config, namespaced the same way
(`main__ping_host`, `crafty__crafty_world_start`, `gmail__send_email`).

```
Host app (chat_app, or any future app)
        │
        ▼
McpClientRegistry  (mcp_client_template/src/registry.py)
        │  connect_all() at startup, persistent sessions
        ├──► main    (http)  → mcp_server's /mcp
        ├──► crafty  (http)  → crafty_mcp_server directly
        └──► gmail   (http)  → a third-party MCP server, bearer auth
```

## Components

### `configs/config_servers.json`
One entry per server. Same two-transport shape as
`mcp_server/src/configs/config_extensions.json`, plus an `auth` block:

```json
{
  "main": {
    "label": "Main MCP Server",
    "description": "This repo's own mcp_server hub.",
    "transport": "http",
    "url": "http://127.0.0.1:8000/mcp"
  },
  "crafty": {
    "label": "Crafty (direct)",
    "description": "crafty_mcp_server reached directly, bypassing mcp_server's own proxy.",
    "transport": "http",
    "url": "http://127.0.0.1:9100/mcp"
  },
  "gmail": {
    "label": "Gmail",
    "description": "Placeholder for a real Gmail MCP server - fill in url and env var.",
    "transport": "http",
    "url": "https://example.invalid/mcp",
    "auth": { "type": "bearer_env", "env_var": "GMAIL_MCP_TOKEN" }
  }
}
```

`auth.type` starts with three values: `"none"` (default), `"header"`
(a fixed extra header, e.g. a static API key), `"bearer_env"` (an
`Authorization: Bearer <value>` header, value read from the named
environment variable at connect time — never stored in the config
file itself). This is intentionally the minimum that covers "normal
MCP servers like Gmail" without committing to OAuth's token-refresh
machinery, which is a distinct, larger piece of work if it turns out
to be needed later.

### `src/config.py`
Loads and validates `config_servers.json` into a small dataclass per
server (mirrors `mcp_server/src/infra/app_config.py`'s
`ExtensionConfig`, but with the added `auth` field).

### `src/transports.py`
Given one server's config, opens either `stdio_client` or
`streamablehttp_client`, applying the resolved `auth` header for HTTP.
Isolated in its own module so the auth-resolution logic (env var
lookup) has one place to live and one place to unit test without
spinning up a real connection.

### `src/registry.py` — `McpClientRegistry`
The core, generalized from `ExtensionRegistry`:

- `connect_all(config_path)` — connect to every configured server,
  isolated per server (a bad one is recorded with `status="error"` and
  never blocks the others or raises out of startup) — same reasoning
  and the same TCP-reachability pre-check (`_check_tcp_reachable`)
  `extensions.py` already had to add to avoid corrupting anyio's
  cancel-scope tree on a real connect failure.
- `list_tools()` — merged catalog, fetched live from every connected
  server on each call (not a startup snapshot), so a server's tools
  changing at runtime is reflected without a restart — same reasoning
  as `merged_list_tools()` in `extensions.py`.
- `call_tool(name, arguments)` — splits `name` on the namespace
  separator, routes to that server's session.
- `aclose()` — closes every open connection; the host app calls this
  on shutdown.
- No `add()`/`remove()` at runtime for v1 (see Explicitly out of
  scope). Config changes require a restart of the host process, same
  as `mcp_server`'s own extensions did before the runtime add/remove
  routes were built on top of the same registry shape — that layer can
  be added later on top of this without changing the core.

### `src/sync_wrapper.py` (optional)
For a synchronous host app (e.g. a Flask process) that wants
persistent connections rather than chat_app's current per-request
connect/disconnect: a background thread owns one long-lived event
loop running the async `McpClientRegistry`; this module exposes
blocking `list_tools()`/`call_tool()` that hand work to that thread and
block for the result. Documented as opt-in — the core registry is
async-first and usable directly by an async host with no wrapper at
all.

### `src/_fixtures/reference_server.py`
Copy of `mcp_server/src/_fixtures/reference_extension_server.py`: a
trivial stdio MCP server (`echo`, `add`) used only so tests can spawn a
real subprocess and exercise the real protocol, not a mock of it.

### Tests
Mirrors `mcp_server/tests/test_extensions.py`'s approach:
- Connect isolation (one server down doesn't block others).
- Namespacing correctness.
- Merged `list_tools()` across servers.
- `call_tool()` dispatch by namespace.
- Config loading/validation, including each `auth.type`.
- One stdio-transport test (the reference fixture as a real
  subprocess) and one http-transport test (a small FastMCP server
  started in-process for the test).

### `README.md`
What this is, the three example config entries and what each
demonstrates, async usage, the optional sync wrapper, and a short
"why" section that points back at `extensions.py`'s docstring rather
than re-deriving the same reasoning (live-refresh tool lists, per-server
failure isolation, persistent vs per-call connections) in two places.

## Data flow

1. Host app starts, calls `await registry.connect_all(config_path)`
   once.
2. Host app calls `await registry.list_tools()` to get one merged,
   namespaced catalog — same shape chat_app's LLM tool loop already
   consumes from a single server today.
3. Host app calls `await registry.call_tool(namespaced_name, args)`;
   the registry routes it to the right upstream session.
4. On shutdown, host app calls `await registry.aclose()`.

## Error handling

Same model as `extensions.py`: a server that's down, refused, or times
out at connect is recorded as `status="error"` with the error message,
never raised out of `connect_all()`. Its tools are simply absent from
`list_tools()`. A `call_tool()` for an unrecognized/dead namespace
raises — the caller is expected to only call names it just got back
from `list_tools()`, same contract `extensions.py.call()` already
documents.

## Open questions to revisit if requirements change

- If a real Gmail (or other OAuth-only) integration becomes concrete,
  `auth.type` will need a fourth value handling token refresh — likely
  its own small module rather than inline in `transports.py`.
- If a host app needs to add/remove a server at runtime (mirroring
  `mcp_server`'s `/extensions` POST/DELETE), that's an additive layer
  on top of `McpClientRegistry`, not a redesign — `add()`/`remove()`
  plus a mutation lock, same shape `ExtensionRegistry` already proves
  out.
