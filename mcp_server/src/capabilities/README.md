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
  return its result. `@mcp.tool()` appears here and nowhere else.

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
2. `capabilities/<name>/contract.py`.
3. `capabilities/<name>/domain.py`.
4. `capabilities/<name>/tool.py`.
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
