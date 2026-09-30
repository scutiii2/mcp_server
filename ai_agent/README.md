# ai_agent

A standalone MCP agent, hard-pinned to one LLM provider+model, sitting
between `chat_app` and `mcp_server`:

```
chat_app  --(MCP: ask/interpret/status/cancel/decide)-->  ai_agent  --(MCP, persistent)-->  mcp_server
```

It is both an MCP *server* (to `chat_app`, exposing
`ask`/`interpret`/`status`/`cancel`/`decide`)
and an MCP *client* (to `mcp_server`, via a persistent connection - see
`src/mcp_upstream.py`). Run two instances - one per provider - to back
`chat_app`'s Claude Agent / OpenAI Agent dropdown entries.

## Setup

1. Copy `secrets/secret_llm.env.example` to `secrets/secret_llm.env` and
   fill in `CLAUDE_API_KEY` and/or `GPT_API_KEY` (whichever provider(s)
   you're running), or the key(s) for whichever `AI_AGENT_GATEWAY` you're
   pointing at instead. Both can be set at once - one file backs both
   instances below.

2. Make sure `mcp_server` is running (`mcp_server/run.bat`) -
   `ai_agent/configs/config_servers.json` points at its default
   `http://127.0.0.1:8010/mcp`.

3. Run an instance:

   ```
   run.bat
   ```

   (from `ai_agent/` - creates `.venv_ai_agent` and installs this project
   into it in editable mode on first run, then runs `py -m src.server`.)
   Defaults to `AI_AGENT_PROVIDER=anthropic`, `AI_AGENT_PORT=9100`.

   To run a second instance side by side (e.g. openai on `9101`), set
   both env vars first so the two don't collide:

   ```
   set AI_AGENT_PROVIDER=openai
   set AI_AGENT_PORT=9101
   run.bat
   ```

   Override `AI_AGENT_HOST` if you need a non-default bind address.
   `server_launcher` (repo root) does the same thing per-instance
   through its own field editor, without needing to `set` anything by
   hand.

   To run against a different gateway block for this process only,
   without editing `secret_llm.env`, pass `--gateway` (forwarded straight
   through by `run.bat`):

   ```
   run.bat --gateway openrouter
   ```

   Takes precedence over `AI_AGENT_GATEWAY`.

## Asking before tools run

`ask` takes `approval_mode` and `allowed_tools` (`src/approvals.py`):

- `off` (default): tools run as before. chat_app never sets a mode.
- `ask`: before each tool that is not in `allowed_tools`, the agent emits an
  `approval_request` event (tool, label, arguments) and waits. The tool runs only
  after the `decide(request_id, step_id, decision)` tool answers `allow` or
  `always` (also stop asking about that tool for the rest of the turn). `deny`,
  no answer within 4 minutes, or a Stop all mean it does not run, and the model
  is told so in place of a result. `delegate_to_agent` asks like any tool.
- `deny`: a tool that would need asking is refused at once. A delegated agent
  gets this from a turn that asks, since it cannot reach the user.

`status` reports `tool_approval: true`, so a caller that needs tools asked about
(ember_api) can refuse an older agent that would ignore the option.

## Roles

Copy `configs/config_ai_agent_roles.json.example` to
`configs/config_ai_agent_roles.json` before running - like `secret_llm.env`
above, the real file is gitignored so a fresh checkout only has the
`.example` twin, and `ai_agent` (and its tests) won't start without it.

To run with a specific AI agent persona (a set of system-prompt instructions
tailored to a domain or use case), pass `--role` or set `AI_AGENT_ROLE`:

```
python -m src.server --role ops_specialist
```

or in `secret_llm.env`:

```
AI_AGENT_ROLE=ops_specialist
```

The CLI flag takes precedence over the environment variable, which takes
precedence over the `default_role` in `configs/config_ai_agent_roles.json`.

An unknown role id fails loudly at startup, naming the bad id and the valid
alternatives - no silent fallback. Role selection is fixed for the process
lifetime; there is no per-request or runtime override.

One role ships out of the box:
- `generic` (the default) - empty persona, preserving the original hardcoded
  system prompt behavior.

To add a new role, edit `configs/config_ai_agent_roles.json` and add an entry
under `roles` with a `label` (human-readable name) and `persona`
(system-prompt instructions):

```json
{
  "my_role": {
    "label": "My Custom Role",
    "persona": "You are an expert in ... "
  }
}
```

No code change is required - the new role is available immediately on the next
process restart.

**Limitation:** the agent registry (`src/agent_registry.py`) derives an
instance's id and label from its provider alone, not its role. Running two
instances of the *same* provider with different `--role`/`AI_AGENT_ROLE`
values is not currently supported - the second instance's `register()` call
overwrites the first's entry under the same id, and the first instance's
`deregister()` on shutdown then deletes the second (still-running)
instance's entry. Only one role per provider at a time is supported; mixing
roles across providers (e.g. `anthropic` as `ops_specialist`, `openai` as
`generic`) is unaffected. Fixing this properly (role-aware agent ids) would
touch `chat_app`'s persisted turn data and is left for a separate plan.

## Security

- **`/mcp` needs the internal token** once `INTERNAL_API_TOKEN` is set in
  `secrets/secret_internal_api.env` (created from its `.example` on first
  run; same value as mcp_server's, chat_app's and ember_api's). Without it
  a request gets `401`. The agent sends the same token on its own calls to
  mcp_server and to peer agents (`src/internal_auth.py`).
- **The asking user travels on**: `ask()` reads `X-Requester-Username` /
  `X-Requester-Email` from the request (ember_api and chat_app set them),
  and every mcp_server tool it calls during that turn gets the user in the
  call's `_meta.requester` - the agent's one mcp_server session is shared by
  every user, so a header can't carry it. A delegated agent gets it as
  headers. The model never sets either.

## Project layout

- **`configs/*.json`** - structured settings, mostly gitignored. See
  [`configs/README.md`](configs/README.md).
- **`secrets/*.env`** - credential values, gitignored. See
  [`secrets/README.md`](secrets/README.md).

See [`src/README.md`](src/README.md) for the full code map - what lives
where, and where new code goes.

See
[`docs/superpowers/specs/2026-09-07-ai-agent-mcp-layer-design.md`](../docs/superpowers/specs/2026-09-07-ai-agent-mcp-layer-design.md)
for the full design rationale.
