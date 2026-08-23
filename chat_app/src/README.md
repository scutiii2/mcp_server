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
    provider/router layer behind the Chat page.
- **[`models/`](models/README.md)** - SQLAlchemy models, one file per
  table.
- **[`utils/`](utils/README.md)** - small, single-purpose helpers.
- `run.py` - `create_app()`, the Flask application factory. Loads
  secrets/configs, wires the DB, security pipeline, login manager,
  mail, and every page blueprint.

## Runtime data (not code)

- **[`configs/`](configs/README.md)** - structured settings, mostly
  committed.
- **[`secrets/`](secrets/README.md)** - credential values, gitignored.
- **[`data/`](data/README.md)** - SQLite databases, gitignored.
- **[`instance/`](instance/README.md)** - Flask's own default instance
  folder.

See the root [`../README.md`](../README.md) for setup instructions.
