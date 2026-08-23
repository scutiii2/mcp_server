# src/_fixtures/

Test-only fixtures - not real capabilities, not registered as tools or
resources, and not imported by `run.py`. The underscore prefix marks
this as internal scaffolding rather than a package another module
should import from in production code.

- **`reference_extension_server.py`** - a minimal, self-contained stdio
  MCP server (two trivial tools, `echo` and `add`) used to prove
  `infra/extensions.py`'s proxy mechanism against a real subprocess and
  the real MCP SDK, not a mock. Spawned by `tests/test_extensions.py`'s
  real-subprocess tests, and referenced by
  `../configs/config_extensions.json.example` as a working example
  extension entry. Invoked as `python -m src._fixtures.reference_extension_server`.

Add a fixture here only when a test genuinely needs a real, separate
process (or similarly heavyweight scaffolding) to prove something a
mock can't - most tests should mock at the boundary instead, the way
the rest of `tests/test_extensions.py` does.
