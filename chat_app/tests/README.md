# tests/

One test file per `src/` module or page, named `test_<name>.py` (e.g.
`src/services/security/ip_filter.py` → `test_ip_filter.py`,
`pages/Chat/` → `test_chat_page.py`). `conftest.py` holds a fixture every
test can use:

- **`app`** - a `Flask` app wired to a throwaway SQLite db under
  `tmp_path`, tables created and dropped per test. Most tests take this
  fixture (or `client = app.test_client()` built from it) rather than
  hitting the real `data/app.db`.

## Conventions

- Page tests (`test_*_page.py`) drive routes through `app.test_client()`
  and a logged-in session, not by calling view functions directly.
- Service tests (`test_ip_filter.py`, `test_rate_limit.py`,
  `test_headers.py`, `test_fingerprint.py`, `test_cross_site.py`) call
  the pure functions directly with plain dicts - no Flask app needed,
  per `services/security/README.md`'s "pure-function-first" design.
- `test_agent_registry.py`/`test_ai_agent_client.py` mock the MCP session
  (`test_mcp_client.py`'s existing pattern) rather than making a real
  network call to a running `ai_agent` instance - the LLM providers
  themselves are tested in the standalone `ai_agent/tests/`, not here.

## Adding a test file

New module or page under `src/` → new `test_<same name>.py` here,
following whichever existing file covers the closest kind (a page → a
`test_*_page.py`; a security module → `test_ip_filter.py`'s
pure-function style; an MCP client wrapper → `test_mcp_client.py`).
