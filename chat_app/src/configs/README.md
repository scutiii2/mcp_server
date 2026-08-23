# src/configs/

Structured, mostly-committed settings - feature toggles and tuning
values, never credentials (those go in `../secrets/`).

- **`config_chat.json`** - LLM provider/model list. Loaded independently
  via `CHAT_CONFIG_PATH` (`src/services/llm/settings.py`), not through
  the loader below - it's read by `services/llm/app_config.py`, not the
  security pipeline.
- **`config_security_ip_filter.json`, `config_security_rate_limit.json`,
  `config_security_headers.json`** - one per `services/security/`
  module, each `{"enabled": false}` by default if the file is missing.
  Loaded together by `utils/config_loader.py`'s `load_all_json_configs()`
  (every `*.json` in this folder, keyed by filename stem), then picked
  out by stem name in `services/security/pipeline.py`.
- **`config_security_fingerprint.json`** - read directly by
  `pages/Auth/__index__.py`, not through `load_all_json_configs()` -  a
  third, standalone loading path since only that one route needs it.

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
  give it its own `CHAT_CONFIG_PATH`-style dedicated env var and loader
  function, following `config_chat.json`'s pattern, rather than folding
  it into `load_all_json_configs()`'s generic dict.
