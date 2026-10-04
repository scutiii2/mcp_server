# secrets/

Real values for this `ai_agent` instance, gitignored — copy
`secret_llm.env.example` to `secret_llm.env` and fill it in. Only the
`.example` files and this README are committed; see the root
`.gitignore`'s `/ai_agent/secrets/*` block.

- **`secret_llm.env`** - provider, gateway, role and API keys.
- **`secret_internal_api.env`** - `INTERNAL_API_TOKEN`, the same value as
  mcp_server's, chat_app's and ember_api's. When set, `/mcp` requires it
  and the agent sends it to mcp_server and peer agents. Created blank from
  its `.example` on first run.
