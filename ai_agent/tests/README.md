# tests/

One test file per `src/` module, mirroring `chat_app`'s convention: mock
the SDK client / `mcp_upstream` boundary, never make a real network or
API call.

- **`test_agent_config.py`** - provider/model resolution, including the
  fail-loud `AgentConfigError` paths.
- **`test_claude_provider.py`, `test_openai_provider.py`** - the 6-round
  tool-calling loop, cancellation checkpoint, and rate-limit cooldown,
  with the SDK client and `src.mcp_upstream` both mocked.
- **`test_server.py`** - the `ask`/`status`/`cancel` FastMCP tool
  contracts, with `agent_config` mocked.
