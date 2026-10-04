# src/services/llm/

What's left of the LLM layer behind the Chat page, now that provider
selection, the tool-calling loop, and Ollama support have all moved to
the standalone `ai_agent/` project (see its own README and
`docs/superpowers/specs/2026-09-07-ai-agent-mcp-layer-design.md`).

- **`settings.py`** - `mcp_server_url` (used by `../mcp_client.py` for
  slash commands/admin, not the Chat Q&A path) and `chats_db_path`.

The Chat page's provider dropdown now picks a configured `ai_agent`
instance (`../agent_registry.py`, `../../../configs/config_agents.json`)
rather than an LLM provider from this folder - see
`../ai_agent_client.py` for how a question actually reaches one.

## Adding a new agent

Configuring another `ai_agent` instance (a third provider, or a second
instance of one already supported) needs no code here - add an entry to
`../../../configs/config_agents.json` and start another instance via
`ai_agent/run.bat` (override `AI_AGENT_PROVIDER`/`AI_AGENT_PORT` first).
Adding support for an LLM provider
`ai_agent` doesn't yet have is a change to `ai_agent/src/llm/`, not this
folder.
