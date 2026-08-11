# SAP AIOps — greenfield scaffold

Two independent Python packages, one MCP tool server and one Flask chat
app, talking over HTTP. This is a starter skeleton, not a finished system —
one real tool (`stop_sap_system`) is built end-to-end through all three
layers so you have a working pattern to copy for the rest.

## Layout

```
mcp_server/                        MCP tool server (port 8010)
├── pyproject.toml
├── src/mcp_server/
│   ├── run.py                     entrypoint — imports capabilities/*, starts uvicorn
│   ├── server.py                  shared FastMCP instance
│   ├── config.py                  settings (config path, host, port)
│   ├── infra/                     SSH client, config loader — shared across all capabilities
│   │   ├── ssh.py
│   │   └── sap_config.py
│   └── capabilities/               one self-contained folder per tool
│       └── control/
│           ├── contract.py         Pydantic request/result models
│           ├── domain.py           pure business logic, no MCP/paramiko imports
│           └── tool.py             thin @mcp.tool() wrapper — only place the decorator appears
└── tests/
    └── test_control_domain.py     domain tests — no SSH, no MCP, no network

chat_app/                          Flask chat + capabilities browser (port 5009)
├── pyproject.toml
├── tests/
│   ├── conftest.py                 Flask app/test-client fixtures
│   ├── test_chat_routes.py         /chat + /api/chat, run_chat mocked
│   ├── test_capabilities_routes.py /capabilities routes, list_tools/call_tool mocked
│   └── test_mcp_client.py          OpenAI schema-reshaping logic
└── src/chat_app/
    ├── run.py                     entrypoint — python -m chat_app.run
    ├── app.py                     create_app()
    ├── config.py
    ├── services/
    │   ├── mcp_client.py          the only place this process talks to the MCP server
    │   └── openai_service.py      tool-calling loop, schemas pulled live from mcp_client
    ├── routes/
    │   ├── chat.py                /chat page + /api/chat
    │   └── capabilities.py        /capabilities — the tool browser
    └── templates/
        ├── chat.html
        └── capabilities.html
```

## Running it

Each package is independently installable:

```bash
cd mcp_server && pip install -e ".[dev]"
cd ../chat_app && pip install -e ".[dev]"
```

Copy the `.env.example` in each package to `.env` and fill in real values —
both `run.py` entrypoints load their local `.env` automatically via
`python-dotenv` before anything reads a setting, so this is all you need
per package. Required either way: `SAP_CONFIG_PATH` in `mcp_server/.env`,
`OPENAI_API_KEY` in `chat_app/.env`. Everything else has a working default.

Then start both processes:

```bash
# terminal 1
cd mcp_server && python -m mcp_server.run

# terminal 2
cd chat_app && python -m chat_app.run
```

Open `http://127.0.0.1:5009/capabilities` to browse and test-call every
registered tool directly — no chat, no OpenAI, just the raw tool catalog
and a form per tool generated from its Pydantic schema. Open `/chat` for
the actual assistant.

## Adding a new tool

Follow the pattern in `capabilities/control/` — one self-contained folder
per tool:

1. `mkdir capabilities/<name>/` with an `__init__.py`.
2. **`capabilities/<name>/contract.py`** — Pydantic request/result models.
3. **`capabilities/<name>/domain.py`** — the real logic. Takes typed input,
   returns typed output, imports `infra/` but never `mcp` or `flask`. This
   is what you unit test.
4. **`capabilities/<name>/tool.py`** — a few lines: load config, call the
   domain function, return its result. `@mcp.tool()` appears here and
   nowhere else.
5. Add `from mcp_server.capabilities.<name> import tool as <name>_tool` to
   `run.py`.

Everything a capability needs (its contract, domain logic, and tool
wrapper) lives together in one folder — no jumping between three parallel
top-level directories to see one tool's full picture. Only genuinely
shared code (`infra/ssh.py`, `infra/sap_config.py`) stays outside
`capabilities/`, since every capability uses the same SSH client and
config loader.

Nothing needs to change on the Flask side — `/capabilities` and `/chat`
both pick up new tools automatically via `list_tools()`.

## What this deliberately avoids from the legacy codebase

- No module-level mutable globals (`CACHED_DUMPS`-style state). Scope
  request-specific state per-session on the Flask side; keep MCP tools
  stateless.
- No duplicated SSH-connect implementations — `infra/ssh.py` is the only
  one.
- No untyped `dict` config with silent `{}` fallback on error —
  `infra/sap_config.py` fails loudly at load time.
- No hand-maintained tool description strings separate from what OpenAI
  and the capabilities page see — one Pydantic schema, one description,
  everywhere.

## Known gaps in this scaffold

- Only `stop_sap_system` is implemented; the other eight legacy tool
  categories (monitoring, jobs, kernel, rename, conversion, provisioning,
  etc.) still need their own `capabilities/<name>/` folder following the
  same pattern.
- No auth on `/capabilities` or `/chat` yet — add the same
  `requires_basic_auth` pattern used in the migrated Flask app before
  exposing this beyond localhost.
- Dependencies (`mcp`, `pydantic`, `paramiko`, `flask`, `openai`) aren't
  installed in the environment this was built in, so everything here is
  syntax-checked but not runtime-verified — run the test suite yourself
  after `pip install -e ".[dev]"`.
