# src/services/llm/

The LLM provider/router layer behind the Chat page - provider
selection and MCP tool-calling.

- **`base.py`** - `ProviderSpec` (the shape every provider implements),
  `SYSTEM_PROMPT`, `ChatResult`, `ToolCallRecord`. Read this first - it
  defines the contract everything else in this folder fills in.
- **`router.py`** - `_PROVIDERS` registry and `list_providers()` /
  `run_chat()` dispatch. The only file that imports every provider
  module directly - routes only ever go through here.
- **`openai_provider.py`, `claude_provider.py`, `ollama_provider.py`**
  - one `ProviderSpec` each, built against that provider's own wire
  format (OpenAI Responses API, Anthropic Messages API, Ollama's local
  API). `ollama_provider.py`'s module docstring explains why it's the
  one provider with a live `check_models` and why it's excluded from
  `router.AUTOMATIC_ORDER`.
- **`cooldown.py`** - shared rate-limit/cooldown state used by more
  than one provider.
- **`settings.py`** - env-var-driven settings for this layer
  (`CHAT_CONFIG_PATH`, model overrides, `MCP_SERVER_URL`,
  `OLLAMA_BASE_URL`).
- **`app_config.py`** - loader for `../../configs/config_chat.json`
  (the provider/model list shown in the UI).

## Adding a new provider

1. `<name>_provider.py` - build a `PROVIDER = ProviderSpec(...)`
   following `openai_provider.py`'s shape: `id`, `label`, `has_api_key`,
   `is_available`, `run_chat`, `models`, `default_model_id`, and
   `check_models` only if the provider needs live per-model
   availability (see `ollama_provider.py` for why).
2. Register it in `router.py`'s `_PROVIDERS` dict, and add it to
   `AUTOMATIC_ORDER` if it should ever be picked automatically rather
   than only by explicit selection.
3. Any new credential it needs goes in `../../secrets/secret_llm.env`
   (+ `.example`), read through `settings.py`.
