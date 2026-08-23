# capabilities/crafty/

Control Minecraft worlds hosted on one or more Crafty Controller
instances - ten tools: `crafty_world_register`, `crafty_world_remove`,
`crafty_world_list`, `crafty_world_start`, `crafty_world_stop`,
`crafty_world_restart`, `crafty_world_send_command`,
`crafty_world_get_status`, `crafty_set_default_base_url`, and
`crafty_ping_base_url`, also invocable as `/crafty
register|remove|list|start|stop|restart|send_command|status|set_default_base_url|ping`.

Unlike `server_manager` (Docker containers already on this host) or
`host_health` (a fixed inventory in `config_hosts.json`), what this
capability controls isn't fixed at deploy time - a world only becomes
usable once `crafty_world_register` is called, naming which Crafty
instance it's on, which server id Crafty knows it as, and an API token
scoped to that server.

**Default `base_url`/`verify_ssl`**, used by a `crafty_world_register`
call that doesn't supply its own (useful when every world lives on the
same Crafty instance), resolve in this order:

1. The value stored by `crafty_set_default_base_url` - takes effect
   immediately, no restart needed.
2. `CRAFTY_BASE_URL` / `CRAFTY_VERIFY_SSL` from the environment
   (`../../secrets/*.env`).

Neither is required: a deployment with no default just has to pass
`base_url` explicitly on every `crafty_world_register` call.
`crafty_ping_base_url` checks either one is actually reachable, before
committing to a `crafty_world_register` call - it needs no registered
world, just a URL (explicit, or resolved the same way).

**Owns:** `data/crafty_worlds.db` - `infra/crafty_registry.py`'s SQLite
store of registered worlds (name, base_url, server_id, API token,
verify_ssl) and the live-set default base_url/verify_ssl. Created
automatically on first use. Deliberately **not** a `config_*.json` file:
every other config loader in this codebase keeps secrets out of config
by having it only name an environment variable, but a token handed to
`crafty_world_register` at runtime has no such variable to name - it's
supplied live. The token never appears in `crafty_world_list`'s output
or any other tool result - see `contract.py`'s docstring.

**Toggle:** `"crafty"` in `../../configs/config_capabilities.json`.
Disabling it removes all ten tools; registered worlds and the stored
default stay in `data/crafty_worlds.db` and reappear if it's re-enabled.
