# chat_cli — terminal chat client (design)

Date: 2026-09-25
Status: approved design, not yet implemented
Source: `_TODO.md` entry "Terminal chat client `chat_cli/`" (deferred 2026-09-21)

## Goal

A terminal client that behaves like chat_app's web chat for LLM
conversations: pick an ai_agent, ask questions, watch the answer stream in
token by token with tool-call progress, keep context across turns.

## Decisions

| Topic | Decision |
|---|---|
| Transport | Talk directly to ai_agent over MCP (streamable HTTP). No chat_app HTTP API, no login. |
| Scope | LLM chat only. No `/` mcp_server slash commands in v1. |
| History | In memory for the session only. Nothing written to disk. |
| Client code | Copy chat_app's `ask_stream` logic into chat_cli, tagged `@catalog`. No cross-project import, no shared package (repo invariant: each project self-contained). |
| Agent list | chat_cli's own `configs/config_agents.json`, kept current by ai_agent's `register()`/`deregister()` (adds chat_cli's path as a third target). |
| Libraries | `rich` (rendering), `prompt_toolkit` (input), `mcp` (client SDK). |

**Out of scope (v1):** slash commands, caveman mode, extension toggles
(`enabled_extensions` is always `[]`, the same safe default as the web
chat), attachments, saved chats, usage limits, auth.

**Known trade-off:** going direct skips chat_app's auth, permissions,
usage limits, auto-summarize and stored history.

## Layout

Follows the repo's root-project convention (same shape as `ai_agent/`,
`server_launcher/`):

```
chat_cli/
  src/
    __init__.py
    main.py          # entry: parse args (--agent ID), build parts, run REPL
    agent_client.py  # AgentClient: async ask_stream(), cancel(), status()
    agent_config.py  # load configs/config_agents.json -> list[AgentInfo]
    session.py       # ChatSession: in-memory history
    renderer.py      # StreamRenderer: draws stream events with rich
    repl.py          # ChatRepl: prompt loop, local commands, Ctrl+C
  configs/
    config_agents.json          # git-ignored, written by ai_agent
    config_agents.json.example  # format reference
  tests/
  .gitignore                    # .venv_chat_cli/, configs/config_agents.json (as chat_app)
  pyproject.toml
  README.md
  run.bat                       # venv: .venv_chat_cli
```

### Units

- **`AgentInfo`** — frozen dataclass `(id, label, url)`.
- **`agent_config.load_agents(path) -> list[AgentInfo]`** — reads
  `{"agents": [{id, label, url}, ...]}`. Missing file or empty list returns
  `[]`; malformed JSON raises `AgentConfigError` with the path.
- **`AgentClient`** — stateless, one MCP connection per call (same model as
  chat_app's `ai_agent_client.py`).
  - `async ask_stream(url, question, history, request_id) -> AsyncIterator[dict]`
    yields every `token` / `step_start` / `step_end` progress event, then
    exactly one terminal `final` or `error` event. Transport exceptions
    become `{"type": "error", "message": ..., "unplanned": True}`; an
    `isError` result becomes `{"type": "error", "message": <agent text>}`.
  - `async status(url) -> dict` — the agent's `status` tool.
  - `async cancel(url, request_id) -> dict` — the agent's `cancel` tool.
  - Keeps chat_app's rule of never raising inside the open
    `streamablehttp_client`/`ClientSession` blocks (anyio would wrap it in
    an `ExceptionGroup`).
- **`ChatSession`** — `history: list[{"role", "content"}]`,
  `add_turn(question, response)`, `clear()`. Only successful turns are added.
- **`StreamRenderer`** — takes a `rich.Console`; `handle(event)` per event,
  `finish()` to close the live region. No I/O besides the console.
- **`ChatRepl`** — wires the others: agent picker, prompt loop, local
  commands, cancel handling. Takes its collaborators as constructor
  arguments so tests can inject fakes.

All I/O is async: `prompt_toolkit`'s `PromptSession.prompt_async` for
input, `async for` over the stream. No threads.

## Runtime flow

### Startup

1. `run.bat` or `python -m src.main [--agent ID]`.
2. Load agents. If none: print the config path and point at
   `config_agents.json.example`, exit code 1.
3. Query every agent's `status()` concurrently (`asyncio.gather`, 3 s
   timeout each).
4. Agent picker: numbered list, e.g.
   `1) OpenAI Agent — gpt-5  ✓ available`,
   `2) OpenRouter Agent  ✗ unreachable`. Unreachable or unavailable agents
   can still be picked. `--agent ID` skips the picker when that id is
   configured.

### A turn

1. Prompt `you › ` (in-memory input history, up arrow recall).
2. New `request_id = uuid4().hex`; call
   `ask_stream(url, question, session.history, request_id)`.
3. Renderer per event:
   - `token` — append text, redraw as `rich.markdown.Markdown` inside a
     `rich.live.Live` region.
   - `step_start` — print `⏳ <label or tool>` above the live region.
   - `step_end` — print `✓ <label>` or `✗ <label>: <first line of result>`.
   - `final` — render `response` as Markdown, then a dim footer:
     `<model> · <input_tokens>/<output_tokens> tokens · <elapsed>s`
     (fields omitted when absent). `cancelled: true` shows `⏹️ Cancelled`.
   - `error` — red `❌ <message>`.
4. On a non-cancelled `final`, `session.add_turn(question, response)`.

### Ctrl+C

- During a turn: call `cancel(url, request_id)` (best-effort; its failure
  is ignored), stop reading the stream, print `⏹️ Cancelled`, return to the
  prompt. The turn is not added to history.
- At the prompt: first press prints `Press Ctrl+C again or Ctrl+D to exit`;
  a second consecutive press exits. Ctrl+D exits immediately.

### Local commands

| Command | Action |
|---|---|
| `/agent` | Reload the config and reopen the picker. History is kept. |
| `/clear` | Clear history. |
| `/help` | List commands. |
| `/quit` | Exit. |

Any other `/...` input prints
`Slash commands are not supported in chat_cli; use the web chat.` and is
not sent to the agent.

## ai_agent change

`ai_agent/src/agent_registry.py`: add
`_CHAT_CLI_CONFIG_PATH = <repo>/chat_cli/configs/config_agents.json` to the
paths `register()` and `deregister()` update. `_update()` already tolerates
a missing target, so ai_agent keeps working when chat_cli is absent.

(Separate, pre-existing bug, tracked outside this spec: that module's
chat_app path points at `chat_app/src/configs/`, which does not exist.)

## Error handling

| Case | Behaviour |
|---|---|
| Config missing/empty | Message with path + example file, exit 1. |
| Config malformed | `AgentConfigError` message with path, exit 1. |
| Agent unreachable at `status()` | Picker shows `✗ unreachable`; still selectable. |
| Agent unreachable at `ask_stream` | Red error line, history unchanged, back to prompt. |
| Agent `isError` (rate limit, missing key) | Agent's message shown as-is. |
| Stream ends with no terminal event | `❌ Stream ended without a response`. |
| `cancel()` fails | Ignored; local stream still stopped. |
| Console cannot encode ⏳/✓/✗ | ASCII fallback `[..]` / `[ok]` / `[x]`, chosen from `console.encoding`. |

## Testing

pytest + pytest-asyncio; no real network.

- `test_agent_config.py` — valid, missing, empty, malformed files.
- `test_session.py` — `add_turn`, `clear`, `{role, content}` shape.
- `test_agent_client.py` — fake `streamablehttp_client`/`ClientSession`
  scripting progress messages: events pass through in order, `isError`
  maps to `error`, transport exception maps to `error` + `unplanned`.
- `test_renderer.py` — `Console(record=True, width=80)` fed a recorded
  event list; exported text contains step lines, markers, final Markdown,
  footer; ASCII fallback on a non-UTF-8 console.
- `test_repl.py` — fake client + `prompt_toolkit` `create_pipe_input`:
  `/clear` empties history, unknown `/x` shows the not-supported message and
  sends nothing, failed turn not added to history, cancel calls
  `cancel(url, request_id)`, `--agent` skips the picker.
- ai_agent: `register()` / `deregister()` also update chat_cli's path
  (tmp dirs, monkeypatched paths).

Manual end-to-end run is done by the user.
