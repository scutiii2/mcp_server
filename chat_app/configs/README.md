# src/configs/

Structured, mostly-committed settings - feature toggles and tuning
values, never credentials (those go in `../secrets/`).

- **`config_agents.json`** - the configured `ai_agent` instances the Chat
  page's provider dropdown can send questions to (`{id, label, url}`
  each). Loaded independently by `services/agent_registry.py`, not
  through the loader below - it has nothing to do with the security
  pipeline. No `.example` twin: none of its fields are sensitive (a
  localhost URL isn't a secret), so the real file is committed directly,
  same treatment as `mcp_server`'s own `config_extensions.json`. Each
  `ai_agent` instance now upserts/removes its own entry here on
  startup/shutdown (see `ai_agent/src/agent_registry.py`) - a manual edit
  is still possible, but no longer required for a new instance to show
  up.
- **`config_security_ip_filter.json`, `config_security_rate_limit.json`,
  `config_security_headers.json`** - one per `services/security/`
  module, each `{"enabled": false}` by default if the file is missing.
  Loaded together by `utils/config_loader.py`'s `load_all_json_configs()`
  (every `*.json` in this folder, keyed by filename stem), then picked
  out by stem name in `services/security/pipeline.py`.
- **`config_security_fingerprint.json`** - read directly by
  `pages/Auth/__index__.py`, not through `load_all_json_configs()` -  a
  third, standalone loading path since only that one route needs it.
- **`config_usage_limits.json`** - `six_hour_token_limit`,
  `weekly_token_limit`, `max_context_tokens_per_chat`. Loaded directly by
  `services/usage_limits.py` at import, its own standalone loading path
  (same treatment as `config_agents.json`) since it's unrelated to the
  security pipeline.

Every file has a committed `.example` twin with the same shape - none
of these carry secrets, so the real files are committed too (unlike
`../secrets/`).

## Adding a new config file

- A new `config_security_<name>.json` for a new security-pipeline
  module: drop the file here (+ `.example`), then add
  `configs.get("config_security_<name>", {"enabled": False})` in
  `services/security/pipeline.py` - `load_all_json_configs()` already
  picks up any `*.json` here automatically, so that's the only other
  change needed.
- Anything else (a new feature area unrelated to the security pipeline):
  give it its own dedicated loader function, following
  `config_agents.json`'s pattern, rather than folding it into
  `load_all_json_configs()`'s generic dict.
