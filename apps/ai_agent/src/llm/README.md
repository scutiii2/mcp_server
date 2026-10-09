# src/llm/

Claude and OpenAI providers (Ollama only through an OpenAI-compatible
gateway). Each provider calls `src.mcp_client.mcp_upstream` for tools, and
each instance pins one provider+model (see `../agents/agent_config.py`)
rather than routing between several per request. Under the supervisor the
agent file's `llm` block sets `AI_AGENT_PROVIDER`/`AI_AGENT_GATEWAY`/
`AI_AGENT_MODEL` before these modules load (`../agents/agent_spec.py`).
Originally adapted from the retired chat_app's LLM layer.

- **`base_provider.py`** - shared types (`ChatCancelled`, `ToolCallRecord`,
  `ChatResult`). No per-request provider or model choice lives here:
  each instance has exactly one.
- **`anthropic_provider.py`** - Anthropic Messages API provider, pinned
  when the provider is `anthropic` (agent file `llm.provider`, or
  `AI_AGENT_PROVIDER` for an instance started without one).
- **`openai_provider.py`** - OpenAI Responses API provider, pinned when
  the provider is `openai`.
- **`laya_provider.py`** - local Triage Assistant with fixed category, severity
  and investigation decisions. No tools, text generation, cloud fallback or
  API key. Inference runs in a worker thread; weights load before registration.
  Imports only when `laya` is the selected provider.
- **`llm_options.py`** - one agent's `llm` settings (temperature,
  reasoning effort, max tokens, tool rounds) as request kwargs; a
  parameter the API rejects with a 400 is dropped for the rest of the
  process, with one warning.
- **`token_limits.py`** - per-request output/context/tool-round caps from
  `../../configs/config_tuning.json`; an agent file can lower its own.
- **`llm_config.py`** - loads `../../gateways/<provider>/<gateway>.json`
  per-gateway `base_url`/`model` presets; resolves `"{ENV_VAR_NAME}"`
  placeholders against the process environment, never a literal secret.
- **`agent_roles.py`** - builds `SYSTEM_PROMPT` once, at import time,
  for both providers, from the agent file: identity line
  (`Ember: <role>`), `persona`, then `instructions` (or the built-in
  default). An orchestrator's prompt also gets the roster, rebuilt each turn.
- **`cancellation.py`** - cooperative cancellation registry for
  in-flight chat turns, local to this process. A turn can't be aborted
  mid-network-call, so a process-wide flag is checked between
  tool-calling rounds instead.
- **`cooldown.py`** - process-wide rate-limit cooldown tracking. The one
  deliberate exception to this project's "no module-level mutable
  state" rule: a provider's rate-limit status is genuinely process-wide,
  not per-session.
- **`model_limits.py`** - context-window sizes for the usage bar, matched
  by substring against known model-name prefixes (`AI_AGENT_MODEL` is a
  free-form env var, not an enum), with a conservative fallback for
  anything unlisted.
