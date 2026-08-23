# tests/

One test file per `src/` module, named `test_<module>.py` (e.g.
`src/infra/ssh.py` → `test_ssh.py`, `src/capabilities/otp/domain.py` →
`test_otp_domain.py`). `conftest.py` holds one autouse fixture
(`log_dir`) that points `errors.py` at a throwaway directory for every
test, so nothing writes into the real `src/logs/` as a side effect of
running the suite.

## Conventions

- Prefer a real temp file over mocking the filesystem: `tmp_path` (a
  built-in pytest fixture) plus a small `_write()`/`_config()` helper
  that serializes JSON to it - see `test_app_config.py`,
  `test_host_health_capability.py`. Exercises the real loader, not a
  stand-in for it.
- Mock at the network/subprocess boundary, not above it:
  `unittest.mock.patch("src.module.path.function", ...)` for things
  that would otherwise hit SMTP, SSH, or a real MCP connection (see
  `test_otp_domain.py`, `test_host_health_domain.py`,
  `test_extensions.py`). The string target has to match the real
  post-flatten import path (`src.foo.bar`, not `mcp_server.foo.bar`).
- `test_extensions.py` also has a handful of tests that spawn the real
  `src/_fixtures/reference_extension_server.py` subprocess rather than
  mocking - see that file's own docstring for why (proving the real SDK
  protocol against a mock can't be proven by a mock of it).
- `dataclasses.replace(settings, field=...)` to override one `Settings`
  field for a test, rather than monkeypatching individual attributes -
  see `test_approval_routes.py`, `test_errors.py`. `Settings` is a
  frozen dataclass, so this is the only way to get a modified copy.
- Test names read as a sentence describing the property under test
  (`test_a_broken_extension_does_not_prevent_a_working_sibling`, not
  `test_extension_2`) - a failing test's name should say what broke
  without reading its body.

## Adding a test file

New module under `src/` → new `test_<same name>.py` here, following
whichever existing file covers the closest kind of module (a capability
domain module → `test_otp_domain.py`/`test_host_health_domain.py`; an
HTTP route module → `test_approval_routes.py`/`test_extension_routes.py`;
an infra client → `test_ssh.py`/`test_email.py`).
