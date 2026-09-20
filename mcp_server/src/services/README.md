# src/services/

Shared infrastructure: thin clients and loaders every capability reuses,
rather than each one inventing its own. Nothing here knows about `mcp`
or any specific capability - see each capability's own `domain.py` for
where that logic lives instead.

- **`app_config.py`** - loaders for every `../../configs/config_*.json`
  file: `load_email_config`,
  `load_extensions_config`/`load_extension_config`, plus
  `save_extension_config`/`delete_extension_config` for the runtime
  add/remove routes, `load_capabilities_config`/`capability_enabled`/
  `save_capabilities_config` for the capability toggle.
  Read its module docstring first - the `${VAR}` substitution convention
  and per-entry resolution behavior are documented there once rather
  than repeated per loader.
- **`capability_registry.py`** - the live half of the capability
  toggle: `capturing()` wraps a capability's import block in `run.py`
  and records exactly what it registered; `set_enabled()` adds/removes
  those tools/resource templates from the running `mcp` instance.
  `capability_routes.py`'s `PATCH /capabilities/{name}` is the only
  caller outside startup. Read its module docstring for why this reaches
  into a couple of FastMCP's private dicts (no public way to remove a
  resource template) and why it captures actual `Tool`/`ResourceTemplate`
  objects rather than bare functions.
- **`ssh.py`** - `SSHClient`, the one paramiko-connecting code path in
  this server. Host-key verification, auth fallback (key then
  password), and command execution all go through here.
- **`email.py`** - `send_email()`, stdlib `smtplib` wrapper supporting
  the three transports `config_email.json`'s `"security"` can name
  (`starttls` / `ssl` / `none`).
- **`extensions.py`** - connects out to other MCP servers as a client
  and re-exposes their tools as this server's own, namespaced. The
  proxying/aggregation engine behind `config_extensions.json` and the
  `/extensions` HTTP routes.

## Adding a new services client

Only add a module here if more than one capability needs it, or if it's
a new kind of external connection (a new protocol, a new kind of
credential) - a client only one capability uses belongs in that
capability's own `domain.py` instead. Follow `ssh.py`'s or `email.py`'s
shape: a small, typed surface that raises rather than swallowing errors,
so a capability's `domain.py` can decide what a failure means for it.
