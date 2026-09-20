# src/

The `src` package - installed under that literal name (see
`../pyproject.toml`), so every import in this codebase reads
`from src.foo import bar`.

## Code

- **[`pages/`](pages/README.md)** - one folder per page (a Flask
  blueprint, auto-discovered at boot). Start here for "how do I add a
  new page."
- **[`services/`](services/README.md)** - business logic; route
  handlers stay thin, logic that touches the DB or makes a policy
  decision lives here.
  - **[`services/security/`](services/security/README.md)** - the
    network-security pipeline (rate limiting, IP filtering, headers,
    fingerprinting, cross-site rejection).
  - **[`services/llm/`](services/llm/README.md)** - the LLM
    settings and MCP-client wrappers behind the Chat page (LLM providers
    and the tool-calling loop now live in the standalone `ai_agent/`
    project - see its README).
- **[`models/`](models/README.md)** - SQLAlchemy models, one file per
  table.
- **[`utils/`](utils/README.md)** - small, single-purpose helpers.
- `run.py` - `create_app()`, the Flask application factory. Loads
  secrets/configs, wires the DB, security pipeline, login manager,
  mail, and every page blueprint.
- `internal_routes.py` - non-user-facing HTTP routes for calls *from*
  `mcp_server` (not a page - deliberately excluded from `pages/`'s
  auto-discovery), authenticated with a shared static token instead of
  a login session. No routes registered today.

## Runtime data (not code)

None of the runtime-data folders live under `src/` - they all sit one
level up, at the project root, since nothing in them is package code:

- **[`../configs/`](../configs/README.md)** - structured settings,
  mostly committed.
- **[`../secrets/`](../secrets/README.md)** - credential values,
  gitignored.
- **[`../data/`](../data/README.md)** - SQLite databases, gitignored.
- `../logs/` - daily-rotating text logs, gitignored.

See the root [`../README.md`](../README.md) for setup instructions.
