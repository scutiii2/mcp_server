# src/infra/

Shared infrastructure: thin clients and loaders every capability reuses,
rather than each one inventing its own. Nothing here knows about `mcp`
or any specific capability - see each capability's own `domain.py` for
where that logic lives instead.

- **`app_config.py`** - loaders for the four `../configs/config_*.json`
  files (`load_hosts_config`/`load_host_config`, `load_email_config`,
  `load_extensions_config`/`load_extension_config`, plus
  `save_extension_config`/`delete_extension_config` for the runtime
  add/remove routes, and `load_capabilities_config`/
  `capability_enabled`/`save_capabilities_config` for the capability
  toggle). Read its module docstring first - the `${VAR}` substitution
  convention and per-entry resolution behavior are documented there
  once rather than repeated per loader.
- **`capability_registry.py`** - the live half of the capability
  toggle: `capturing()` wraps a capability's import block in
  `../imports.py` and records exactly what it registered; `set_enabled()` adds/removes
  those tools/resource templates from the running `mcp` instance.
  `capability_routes.py`'s `PATCH /capabilities/{name}` is the only
  caller outside startup. Read its module docstring for why this reaches
  into a couple of FastMCP's private dicts (no public way to remove a
  resource template) and why it captures actual `Tool`/`ResourceTemplate`
  objects rather than bare functions.
- **`capability_metadata.py`** - the static half: `title_for()`/
  `command_id_for()` read a capability's optional `TITLE`/`COMMAND_ID`
  (set in that capability's own `__init__.py`), falling back to the real
  id when unset. `title_for()`/`command_id_for()` feed `GET
  /capabilities`; `validate_command_ids()` runs once at startup (see
  `../imports.py`) to fail loudly if two capabilities would collide on
  the same `COMMAND_ID`.
- **`ssh.py`** - `SSHClient`, the one paramiko-connecting code path in
  this server. Host-key verification, auth fallback (key then
  password), and command execution all go through here.
- **`email.py`** - `send_email()`, stdlib `smtplib` wrapper supporting
  the three transports `config_email.json`'s `"security"` can name
  (`starttls` / `ssl` / `none`).
- **`pending_requests.py`** - SQLite-backed store for approval-gated /
  resumable requests. Capability-agnostic: `capability` is just a label
  on the row, so one store serves every `GatedCapability` (see
  `approvals.py`) rather than each growing its own table.
- **`approvals.py`** - the human-approval gate: `register()` a
  `GatedCapability`, call `request_approval()` from a tool instead of
  doing the irreversible thing directly. Read its module docstring for
  the threat model (prompt injection) this exists to defend against.
- **`otp.py`** - one-time-passcode minting, storage, and verification.
  Owned exclusively by `capabilities/otp/` - nothing else calls this
  module. Contrast with `pending_requests.py` above, which several
  capabilities could share.
- **`extensions.py`** - connects out to other MCP servers as a client
  and re-exposes their tools as this server's own, namespaced. The
  proxying/aggregation engine behind `config_extensions.json` and the
  `/extensions` HTTP routes.

## Adding a new infra client

Only add a module here if more than one capability needs it, or if it's
a new kind of external connection (a new protocol, a new kind of
credential) - a client only one capability uses belongs in that
capability's own `domain.py` instead. Follow `ssh.py`'s or `email.py`'s
shape: a small, typed surface that raises rather than swallowing errors,
so a capability's `domain.py` can decide what a failure means for it.
