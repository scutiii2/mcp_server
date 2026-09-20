# src/llm/

Adapted from `chat_app/src/services/llm/` (Claude and OpenAI only -
Ollama is out of scope for this slice): each provider here calls
`src.mcp_upstream` instead of chat_app's own MCP client, and this
project pins one provider+model per instance (see `../agent_config.py`)
rather than routing between several per request.

- **`base_provider.py`** - shared types (`ChatCancelled`, `ToolCallRecord`,
  `ChatResult`) carried over from chat_app's `services/llm/base.py`.
  Everything chat_app needed for its per-request provider dropdown
  (`ProviderSpec`, `ModelOption`, `ModelAvailability*`, the Ollama-only
  `RecursiveRoundRecord`) has no equivalent need here.
- **`anthropic_provider.py`** - Anthropic Messages API provider, pinned
  by `agent_config.py` when `AI_AGENT_PROVIDER=anthropic`.
- **`openai_provider.py`** - OpenAI Responses API provider, pinned when
  `AI_AGENT_PROVIDER=openai`.
- **`llm_config.py`** - loads `../../configs/config_llms.json`'s
  per-gateway `base_url`/`model` presets; resolves `"{ENV_VAR_NAME}"`
  placeholders against the process environment, never a literal secret.
- **`agent_roles.py`** - resolves this instance's active persona
  (`AI_AGENT_ROLE`) from `../../configs/config_ai_agent_roles.json`,
  once, at import time; fails loudly on an unknown role id. Exposes
  `SYSTEM_PROMPT`, imported by both providers in place of
  `base_provider`'s old constant.
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
