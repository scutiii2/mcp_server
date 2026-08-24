# src/capabilities/

One folder per tool, self-contained. `host_health/` and `otp/` are the
two existing capabilities - see each one's own README for what it does.

## Shape of a capability

Each subfolder holds everything specific to that capability, in three
files:

- **`contract.py`** - Pydantic request/result models. The shape a tool
  call takes in and returns.
- **`domain.py`** - the real logic. Typed in, typed out, imports only
  `infra/` (never `mcp` or anything MCP-protocol-specific). This is the
  file you unit test, and the only one that needs to know nothing about
  how it's invoked.
- **`tool.py`** - a few lines: load config, call the domain function,
  return its result *wrapped in `tool_response.respond()`* (see
  "Chat-readable results, not JSON" below). `@mcp.tool()` appears here
  and nowhere else.

Shared infrastructure (`infra/ssh.py`, `infra/email.py`,
`infra/app_config.py`, `infra/pending_requests.py`) stays one level up,
at `src/infra/` - every capability reuses the same clients and config
loader rather than each folder inventing its own.

`otp/` is the worked example of all three files together: two tools, a
domain module that imports only `infra/`, and a contract whose shape
carries a security property (the passcode is deliberately absent from
the result model - see `otp/domain.py`'s docstring).

A different pattern lives at `src/infra/extensions.py`: proxied
external tools, connected out to other MCP servers as a client and
re-exposed here under a namespaced name, rather than written by hand in
this repo at all. Reach for a capability when you're wrapping logic
that lives in this codebase; reach for an extension when you're
exposing an MCP server that already exists elsewhere.

## Chat-readable results, not JSON

Left to itself, FastMCP turns any non-`str` tool return value into the
tool call's visible text by JSON-dumping it (see
`mcp.server.fastmcp.utilities.func_metadata._convert_to_content`) - the
reason a tool call used to show up as a raw JSON blob in chat_app's Chat
and Capabilities pages, and in any other MCP client's transcript.

Every `contract.py` result model in this repo carries a `report` or
`message` field written specifically to be relayed to a person verbatim
- that convention already existed; what was missing was actually using
it as the visible text instead of burying it inside the JSON envelope.
`src/tool_response.py`'s `respond()` is what does that: it builds the
`CallToolResult` FastMCP returns to the client, with `content` set to
that `report`/`message` field (or, for a result with neither, one
`field: value` line per field - never a JSON dump) and
`structuredContent` set to the full model, so a non-chat client can
still get every field.

Every `tool.py` return statement should be wrapped in it:

```python
return respond(domain.check(settings.hosts_config_path, name))
```

The function's own return-type annotation stays the result model
(`-> HostHealthResult`, not `-> CallToolResult`) - FastMCP builds the
tool's advertised output schema from that annotation and separately
validates `structuredContent` against it at call time, so the
annotation should keep describing the data, not `respond()`'s wrapper.
A new `contract.py` result model should follow the same convention: add
a `report` (for a result centered on a table/listing) or `message` (for
a confirmation) field, so `respond()` picks it up automatically -
`otp/contract.py`'s docstring explains the one exception worth knowing
(a field deliberately *not* added because it's a secret).

This lives in `src/tool_response.py` at the top level, not under
`infra/`, because it imports `mcp.types` and is only ever called from a
`tool.py` - `infra/` stays free of anything MCP-protocol-specific (see
`infra/README.md`).

## Add a new capability

1. `mkdir capabilities/<name>/` with an `__init__.py`. Optionally give
   it a `TITLE` (what chat_app's Capabilities page displays) and a
   `COMMAND_ID` (a shorter alias for chat_app's "/<id> <tool> ..."
   slash commands, when `<name>` itself is long enough to be annoying
   to type) - both fall back to `<name>` itself if omitted:

   ```python
   TITLE = "Host Health"
   COMMAND_ID = "host"
   ```

   See `infra/capability_metadata.py`'s docstring for the full
   contract - in particular, `<name>` (the folder name) stays the *real*
   capability id everywhere else (`config_capabilities.json`'s key,
   `commands.py`'s `@command` inference, the `capability_registry.capturing(mcp, "<name>")`
   call in `imports.py` from step 7 below); `COMMAND_ID` is a display
   alias for chat_app only, never a substitute for it.
2. `capabilities/<name>/contract.py` - give each result model a
   `report` or `message` field (see "Chat-readable results, not JSON"
   above).
3. `capabilities/<name>/domain.py`.
4. `capabilities/<name>/tool.py` - return `respond(...)` around the
   domain call, not the domain call's result directly.
5. `capabilities/<name>/README.md` - what it reads (which
   `../configs/*.json` files, which `../secrets/*.env` files), what (if
   anything) it owns under its own `data/` or `secrets/`, and how to
   toggle it off. `host_health/README.md` and `otp/README.md` are the
   templates.
6. Add a toggle entry to `../configs/config_capabilities.json` and
   `config_capabilities.json.example`:

   ```json
   { "<name>": { "enabled": true } }
   ```

7. In `imports.py`, wrap the import in
   `capability_registry.capturing(mcp, "<name>")`, following
   `host_health`/`otp`:

   ```python
   with capability_registry.capturing(mcp, "<name>"):
       from src.capabilities.<name> import tool as <name>_tool
   ```

   Importing the module is what runs its `@mcp.tool()` decorator and
   registers it; `capturing()` records exactly what got registered so
   the capability can be disabled - and, unlike the old "skip the
   import" mechanism, re-enabled live - later. See
   `infra/README.md`'s `capability_registry.py` entry for how toggling
   actually works, and `capability_routes.py` for the
   `PATCH /capabilities/{name}` route chat_app's Capabilities page
   calls to do it.

If the new capability wraps a resource (a client-readable URI, not just
a model-callable tool - see `src/resources/README.md`), have the
capability import the resource's `domain.py`, not the other way around:
the resource owns the logic, and the capability wrapper stays additive
so deleting it leaves the resource untouched. `host_health` is the
worked example of that split too.
