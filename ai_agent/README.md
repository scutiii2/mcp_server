# ai_agent

A standalone MCP agent, hard-pinned to one LLM provider+model, sitting
between `chat_app` and `mcp_server`:

```
chat_app  --(MCP: ask/status)-->  ai_agent  --(MCP, persistent)-->  mcp_server
```

It is both an MCP *server* (to `chat_app`, exposing `ask`/`status`) and
an MCP *client* (to `mcp_server`, via a persistent connection - see
`src/mcp_upstream.py`).

## Setup

1. From `ai_agent/`, install dependencies:

   ```
   pip install -e .
   ```

2. Copy `secrets/secret_llm.env.example` to `secrets/secret_llm.env` and
   set `AI_AGENT_PROVIDER` (`claude` or `openai`), optionally
   `AI_AGENT_MODEL`, and the matching API key.

3. Make sure `mcp_server` is running (`run_mcp.bat` from the repo
   root) - `ai_agent/configs/config_servers.json` points at its default
   `http://127.0.0.1:8010/mcp`.

4. Run it:

   ```
   run_ai_agent.bat
   ```

   (from the repo root; activates `venv_ai_agent` and runs `py -m
   src.server`.) Defaults to `http://127.0.0.1:9100/mcp` - override with
   `AI_AGENT_HOST`/`AI_AGENT_PORT`.

## Project layout

- `src/server.py` - FastMCP entry point; `ask`/`status` tools.
- `src/agent_config.py` - resolves the pinned provider+model from
  `secrets/secret_llm.env` once at startup; fails loudly on a bad config.
- `src/llm/` - copied from `chat_app/src/services/llm/` (Claude and
  OpenAI only - see this project's design spec for why Ollama is
  deferred), adapted to call `src/mcp_upstream.py` instead of
  chat_app's own MCP client.
- `src/mcp_upstream.py`, `src/registry.py`, `src/config.py`,
  `src/transports.py`, `src/sync_wrapper.py` - copied from
  `mcp_client_template/` (see that project's README for the general
  client pattern); `mcp_upstream.py` is the only one adapted for this
  project's specific single-upstream, enabled-extensions-filtered use.

See
[`docs/superpowers/specs/2026-09-04-ai-agent-mcp-layer-design.md`](../docs/superpowers/specs/2026-09-04-ai-agent-mcp-layer-design.md)
for the full design rationale.
