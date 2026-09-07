# ai_agent

A standalone MCP agent, hard-pinned to one LLM provider+model, sitting
between `chat_app` and `mcp_server`:

```
chat_app  --(MCP: ask/status/cancel)-->  ai_agent  --(MCP, persistent)-->  mcp_server
```

It is both an MCP *server* (to `chat_app`, exposing `ask`/`status`/`cancel`)
and an MCP *client* (to `mcp_server`, via a persistent connection - see
`src/mcp_upstream.py`). Run two instances - one per provider - to back
`chat_app`'s Claude Agent / OpenAI Agent dropdown entries.

## Setup

1. From `ai_agent/`, create a venv and install dependencies:

   ```
   python -m venv ../venv_ai_agent
   ..\venv_ai_agent\Scripts\activate
   pip install -e .
   ```

2. Copy `secrets/secret_llm.env.example` to `secrets/secret_llm.env` and
   fill in `ANTHROPIC_API_KEY` and/or `OPENAI_API_KEY` (whichever
   provider(s) you're running). Both can be set at once - one file backs
   both instances below.

3. Make sure `mcp_server` is running (`run_mcp.bat` from the repo root) -
   `ai_agent/configs/config_servers.json` points at its default
   `http://127.0.0.1:8010/mcp`.

4. Run one or both instances from the repo root:

   ```
   run_ai_agent_claude.bat
   run_ai_agent_openai.bat
   ```

   These pin `AI_AGENT_PROVIDER`/`AI_AGENT_PORT` explicitly (`claude`/`9100`
   and `openai`/`9101`) so the two can run side by side without drifting.
   Override `AI_AGENT_HOST` if you need a non-default bind address.

## Project layout

- `src/server.py` - FastMCP entry point; `ask`/`status`/`cancel` tools.
- `src/agent_config.py` - resolves the pinned provider+model from
  `secrets/secret_llm.env` once at startup; fails loudly on a bad config.
- `src/llm/` - adapted from `chat_app/src/services/llm/` (Claude and
  OpenAI only - Ollama is out of scope for this slice), calling
  `src/mcp_upstream.py` instead of chat_app's own MCP client.
  `cancellation.py` is process-local: each `ai_agent` instance tracks
  only the in-flight turns it itself is serving.
- `src/delegation.py`, `src/agent_registry.py` - lets one agent hand a
  focused sub-question to another configured agent (or itself) mid-loop
  via a `delegate_to_agent` tool, offered alongside `mcp_server`'s own
  tools whenever `configs/config_agents.json` lists at least one agent.
  Bounded by a depth cap (2 hops) so a delegation chain can't run away.
- `src/mcp_upstream.py`, `src/registry.py`, `src/config.py`,
  `src/transports.py`, `src/sync_wrapper.py` - a generic MCP-client
  layer (`McpClientRegistry`/`SyncMcpClient`), giving this project a
  persistent, namespaced connection to `mcp_server` instead of
  reconnecting per call; `mcp_upstream.py` is the only one adapted for
  this project's specific single-upstream, enabled-extensions-filtered
  use.

See
[`docs/superpowers/specs/2026-09-07-ai-agent-mcp-layer-design.md`](../docs/superpowers/specs/2026-09-07-ai-agent-mcp-layer-design.md)
for the full design rationale.
