# mcp_server: src/configs + src/secrets + src/data restructure, per-capability READMEs, capability toggles

Status: approved by user (chat, 2026-08-23). Ready for implementation planning.

## Motivation

`mcp_server` currently keeps `config.json`, `.env`, `data/`, and `logs/` at
the project root, all as a single undifferentiated config file and a
single `.env`. `chat_app` already solved this with a `src/configs/` +
`src/secrets/` split (committed JSON structure vs. gitignored `.env`
credential files) plus a `src/data/` for runtime state. This spec brings
`mcp_server` to the same shape, adds a README to every capability folder
and to each new top-level `src/` directory, and adds a config-driven
on/off toggle per capability (`host_health`, `otp` today).

Three decisions were confirmed with the user before this doc was written:

1. Toggle mechanism: a `config_capabilities.json` file, read once at
   startup; `run.py` skips a capability's import (and therefore its tool
   registration) when disabled.
2. `config.json` is fully split into one committed JSON file per concern
   (`config_hosts.json`, `config_email.json`, `config_extensions.json`,
   `config_capabilities.json`) under `src/configs/`, with real secret
   values living in `.env` files under `src/secrets/` — mirroring
   `chat_app` file-for-file rather than keeping one big file.
3. Shared runtime state (`pending_requests.db`, SMTP/SSH credentials)
   stays general, under `src/data/` and `src/secrets/`. Only state a
   single capability owns outright (`otp.db`) moves inside that
   capability's own folder.

## Target layout

```
mcp_server/
  README.md                                   # NEW - top-level overview + links
  docs/superpowers/specs/...                   # this file
  src/
    configs/                                   # committed, non-secret structure
      config_hosts.json          (+.example)   # was config.json's "hosts" section
      config_email.json          (+.example)   # was config.json's "email" section
      config_extensions.json     (+.example)   # was config.json's "extensions" section
      config_capabilities.json   (+.example)   # NEW - per-capability enabled flag
      README.md                                # NEW
    secrets/                                   # gitignored; real credential values
      secret_app.env             (+.example)   # MCP_HOST, MCP_PORT, MCP_PUBLIC_BASE_URL
      secret_smtp.env            (+.example)   # SMTP_PASSWORD
      secret_ssh.env             (+.example)   # SSH_HOST_KEY_POLICY, SSH_KNOWN_HOSTS,
                                                #   ZIMA_SSH_PASSWORD, DESKTOP_SSH_PASSWORD
      README.md                                # NEW
    data/                                      # gitignored; shared runtime state
      pending_requests.db                      # capability-agnostic (infra/approvals.py)
      README.md                                # NEW
    logs/                                      # relocated under src/, same idea as chat_app
      server.log
      errors/<reference>.log
    mcp_server/                                # the Python package - unchanged location
      capabilities/
        host_health/
          README.md                            # NEW
          contract.py / domain.py / tool.py     # unchanged
        otp/
          README.md                             # NEW
          data/
            otp.db                              # MOVED here - only this capability touches it
          contract.py / domain.py / tool.py     # unchanged
      infra/ ...                                # unchanged except path-producing call sites
      resources/host_health/ ...                # unchanged (see "host_health README" note below)
  tests/                                        # updated fixtures, see "Test impact"
```

Removed: root-level `.env`, `config.json`, `config.json.example`,
`.env.example`, `data/`, `logs/`. Real secret values in the current
`.env` (`SMTP_PASSWORD`, `ZIMA_SSH_PASSWORD`) and the current
`config.json` (host inventory, approver emails) are migrated into the
new files, not discarded — this is a live deployment.

## Settings (`config.py`)

`config_path: Path` is removed. New fields:

```python
configs_dir: Path = Path(_env("MCP_CONFIGS_DIR", "src/configs"))
data_dir:    Path = Path(_env("MCP_DATA_DIR", "src/data"))
log_dir:     Path = Path(_env("MCP_LOG_DIR", "src/logs"))          # default changes, field itself doesn't
```

`secrets_dir` is deliberately **not** a `Settings` field: it has to be
known *before* `Settings` exists, since `Settings`' own field defaults
read `os.getenv()` at import time (same chicken-and-egg reason
`CONFIG_PATH` had to be resolved via `.env` before `mcp_server.config`
was imported today). `run.py` hardcodes `Path("src/secrets")` as the one
place that knows where to look, and loads every `*.env` file in it via
`load_dotenv()` before importing `mcp_server.config` — generalizing the
single `load_dotenv()` call that's already there today.

New computed properties on `Settings`, replacing `config_path` at every
call site:

```python
@property
def hosts_config_path(self) -> Path: return self.configs_dir / "config_hosts.json"
@property
def email_config_path(self) -> Path: return self.configs_dir / "config_email.json"
@property
def extensions_config_path(self) -> Path: return self.configs_dir / "config_extensions.json"
@property
def capabilities_config_path(self) -> Path: return self.configs_dir / "config_capabilities.json"
```

`pending_requests_path` keeps its name and its `PENDING_REQUESTS_PATH`
env override, but its default becomes `self.data_dir / "pending_requests.db"`
(computed, since it needs `data_dir`) rather than a bare literal.

`otp_path` keeps its name and its `OTP_PATH` env override; only its
*default* changes, to point inside the capability that owns it:
`Path(_env("OTP_PATH", "src/mcp_server/capabilities/otp/data/otp.db"))`.
This is the one place a capability's data location is named outside its
own folder, and it's unavoidable without inventing a second
settings-like mechanism — the existing `Settings` dataclass stays the
single source of truth for every path in the process, which is also
what `errors.py`/`logging_setup.py`/tests already assume.

## Config file split (`infra/app_config.py`)

Each new `config_*.json` file's **top-level content is exactly the
content of the old section it replaces** — no wrapper key. E.g.
`config_hosts.json` is `{"zima": {...}, "desktop": {...}}` directly,
not `{"hosts": {"zima": {...}}}`. `config_email.json` is the email
object directly. This drops a layer of nesting from every loader and
matches how `chat_app`'s own per-concern JSON files work (each file's
top level *is* its content).

Consequences for `app_config.py`:

- `load_config(path)` stays as the generic "read+parse one JSON file"
  primitive, now called once per concern instead of once for the whole
  document.
- `resolve_section(..., where=...)` calls change from `where="hosts"` /
  `where="email"` to `where=""` (resolving the whole loaded document),
  since there's no longer an outer key to descend past. Error messages
  keep naming the right file (`config_path` in the error already names
  the specific file, e.g. `config_email.json`), so this loses no
  diagnostic value.
- `_hosts_section`, `load_email_config`, `_extensions_section` drop
  their `KeyError` for "section missing from the document" (a file
  that's just the wrong shape now fails as "not a JSON object" instead,
  via the existing `load_config` check) — this is a minor simplification,
  not a behavior most callers depended on.
- `save_extension_config` / `delete_extension_config` write to
  `settings.extensions_config_path` instead of `settings.config_path`,
  and write/read the extensions map directly (no `"extensions"` wrapper
  key) — this is the one config file mutated at runtime (via
  `extension_routes.py`'s POST/DELETE `/extensions`), so this path
  matters beyond startup.

New in `app_config.py`:

```python
def load_capabilities_config(config_path: Path) -> dict[str, dict[str, Any]]:
    """Read config_capabilities.json. Missing file -> {} (nothing disabled)."""

def capability_enabled(config: dict[str, dict[str, Any]], name: str) -> bool:
    """True unless the capability is present and explicitly {"enabled": false}."""
    return config.get(name, {}).get("enabled", True)
```

A capability *absent* from the file, or the file itself missing, is
enabled by default — a fresh or partially-filled toggle file must never
silently disable everything. This mirrors the "a deployment is allowed
to have half its secrets present" principle already documented at the
top of `app_config.py`.

## Capability toggle (`run.py`)

Read once, at the same point `.env`/logging are set up (before the
capability imports that currently sit at module level):

```python
from mcp_server.infra.app_config import capability_enabled, load_capabilities_config

_capabilities_config = load_capabilities_config(settings.capabilities_config_path)

if capability_enabled(_capabilities_config, "host_health"):
    from mcp_server.capabilities.host_health import tool as host_health_tool  # noqa: E402,F401
    from mcp_server.resources.host_health import resource as host_health_resource  # noqa: E402,F401
if capability_enabled(_capabilities_config, "otp"):
    from mcp_server.capabilities.otp import tool as otp_tool  # noqa: E402,F401
```

Importing a capability's `tool`/`resource` module is what runs its
`@mcp.tool()`/`@mcp.resource()` decorator and registers it (this is
already how `run.py`'s comment describes the existing unconditional
imports) — skipping the import fully disables the capability: it won't
appear in `list_tools()`, `/commands`, or the capabilities page in
`chat_app`. No changes needed in `chat_app` for this to work; it already
treats the tool list as the source of truth.

The startup banner (inside `_serve()`) gets one more line:

```
f"  Capabilities: {', '.join(sorted(name for name in ('host_health', 'otp') if capability_enabled(_capabilities_config, name))) or 'none'}",
```

`host_health` registers both a tool and a resource under one toggle
entry — they're "the same domain logic underneath" per `run.py`'s
existing comment, so one flag governs both.

## READMEs

New files, each explaining: what lives in the directory, which
capability (if any) owns it, and the `.example` convention for anything
gitignored:

- `mcp_server/README.md` — top-level overview: what this server is,
  how to run it (`run_mcp_server.bat` / `python -m mcp_server.run`),
  and links to the READMEs below.
- `src/configs/README.md` — what each `config_*.json` is, the `${VAR}`
  substitution convention (point at `app_config.py`'s docstring for the
  full explanation rather than duplicating it), and that
  `config_capabilities.json` is where a capability gets turned off.
- `src/secrets/README.md` — what each `secret_*.env` backs, the
  `.example` convention, and the "service manager / secrets manager in
  production instead of a file on disk" note already in the current
  `.env.example`.
- `src/data/README.md` — explains `pending_requests.db` is shared
  runtime state (not tied to one capability), and that a capability
  with its own data lives at `capabilities/<name>/data/` instead —
  pointing at `capabilities/otp/README.md` as the example.
- `capabilities/host_health/README.md` — what it does, that it reads
  `config_hosts.json` (+ SSH secrets via `infra/ssh.py`), that it owns
  no data/secrets of its own, and how to disable it.
- `capabilities/otp/README.md` — what it does, that it owns
  `data/otp.db`, that it reads `config_email.json` + `secret_smtp.env`
  (shared, not owned), and how to disable it.

`capabilities/__init__.py`'s existing "add a new capability" docstring
gets one more line: add a README, and add the new capability's toggle
entry to `config_capabilities.json` (+ `.example`).

## Migration / call-site impact (implementation detail, not exhaustive here)

Every current reader of `settings.config_path` moves to the specific
`*_config_path` property for what it actually reads:
`approval_routes.py` (via `infra/approvals.py`'s `load_email_config`),
`infra/approvals.py` itself, `extension_routes.py`,
`infra/extensions.py`, `capabilities/host_health/domain.py` +
`tool.py`, `capabilities/otp/tool.py`, `resources/host_health/resource.py`.
`errors.py` and `logging_setup.py` already take `log_dir` as a
parameter/read `settings.log_dir` — only the default value they resolve
to changes, no call-site change needed there.

`zima_host.yaml` (the Docker Compose recipe) drops `CONFIG_PATH`,
`PENDING_REQUESTS_PATH`, and `OTP_PATH` from its `environment:` block —
since `working_dir: /app` and the new defaults are already
`/app`-relative (`src/configs`, `src/data`, etc.), they resolve
correctly with no override needed. `MCP_LOG_DIR` similarly can drop to
its new default unless a deployment wants logs outside the mounted
volume.

Tests: `tests/conftest.py`'s `log_dir` fixture and every test file that
currently builds a fixture `config.json` / points `settings.config_path`
at a tmp file (`test_app_config.py`, `test_approval_routes.py`,
`test_command_routes.py`, `test_extension_routes.py`,
`test_extensions.py`, `test_host_health_capability.py`,
`test_host_health_domain.py`, `test_otp_commands.py`,
`test_otp_domain.py`, `test_otp_store.py`, `test_pending_requests.py`,
`test_ssh.py`) get updated to the new per-file fixtures and settings
shape. This is implementation work for the plan, not enumerated line by
line here.

`.gitignore` at the repo root gets its `.env` / `config.json` / `*.db`
patterns re-anchored to the new `src/` locations (mirroring how
`chat_app/.gitignore` already ignores `src/secrets/*` /
`!src/secrets/*.example` / `src/data/` / `src/logs/`).

## Out of scope

- No change to `chat_app` — it already treats `mcp_server`'s tool list
  as the source of truth and needs no changes for the toggle to work.
- No change to the *shape* of `HostConfig` / `EmailConfig` /
  `ExtensionConfig` — only which file each is read from.
- No new capability is being added; `host_health` and `otp` are the
  only two toggle entries this spec creates.
