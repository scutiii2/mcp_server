# Chat & Capabilities Pages Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Port MCPArchitecture's Chat (`/chat`) and Capabilities (`/capabilities`) pages, and the whole LLM chat subsystem behind them (three providers, staged-pipeline ask-user flow, per-user chat history, live MCP tool/resource browser), into this project's `chat_app`, adapted to its page/permission/security conventions.

**Architecture:** MCPArchitecture's `chat_app.*` package is re-rooted to `src.*` throughout (see the Import Rewrite Table below) and split across `src/services/llm/` (providers, router, staged pipeline), `src/services/mcp_client.py`, `src/services/chats_store.py`, and two new `src/pages/Chat/` / `src/pages/Capabilities/` page folders following this project's `__index__.py` blueprint convention. MCPArchitecture's own auth/session/CSRF stack is dropped entirely in favor of this project's `flask_login` + `authz` + security pipeline; its JSONL turn-trace and standalone error-reference files are dropped in favor of this project's `LogEntry`/`log_service`. A new project-wide `Sec-Fetch-Site`/Origin check replaces the CSRF-token protection these two pages' JSON `fetch()` calls don't carry.

**Tech Stack:** Flask, Flask-Login, Flask-SQLAlchemy, Flask-WTF (existing) + `mcp`, `pydantic`, `pydantic_core`, `openai`, `anthropic` (new). pytest (existing).

**Spec:** [docs/superpowers/specs/2026-08-22-chat-capabilities-port-design.md](../specs/2026-08-22-chat-capabilities-port-design.md)

**Source repository:** every file this plan ports FROM lives under `D:\User\Documents\Programming\Python\MCPArchitecture\chat_app\src\chat_app\` and `...\chat_app\tests\` (an additional working directory in this session — readable directly). Every file it ports TO lives under `D:\User\Documents\Programming\Python\MCPServer\chat_app\` (`src/...`, `tests/...`, relative paths below are relative to this `chat_app/` root unless stated otherwise).

## Global Constraints

- **Import Rewrite Table** — applied as an exact, global string replacement throughout every copied file (source AND ported test file), including inside `unittest.mock.patch(...)` target strings. Apply top-to-bottom (longer/more-specific patterns first) so a bare-package replacement doesn't clobber a more specific one already rewritten:
  | Old (MCPArchitecture) | New (this project) |
  |---|---|
  | `chat_app.services.llm.base` | `src.services.llm.base` |
  | `chat_app.services.llm.cooldown` | `src.services.llm.cooldown` |
  | `chat_app.services.llm.claude_provider` | `src.services.llm.claude_provider` |
  | `chat_app.services.llm.openai_provider` | `src.services.llm.openai_provider` |
  | `chat_app.services.llm.ollama_provider` | `src.services.llm.ollama_provider` |
  | `chat_app.services.llm.router` | `src.services.llm.router` |
  | `chat_app.services.llm.staged_pipeline` | `src.services.llm.staged_pipeline` |
  | `chat_app.services.llm.staged_plans_store` | `src.services.llm.staged_plans_store` |
  | `chat_app.services.llm` | `src.services.llm` |
  | `chat_app.services.mcp_client` | `src.services.mcp_client` |
  | `chat_app.services.tool_titles` | `src.services.tool_titles` |
  | `chat_app.services.tool_capabilities` | `src.services.tool_capabilities` |
  | `chat_app.infra.app_config` | `src.services.llm.app_config` |
  | `chat_app.chats.store` | `src.services.chats_store` |
  | `chat_app.chats` | `src.services.chats_store` |
  | `chat_app.config` | `src.services.llm.settings` |

  After editing a copied file, run `grep -n "chat_app" <file>` and confirm every remaining hit is inside a comment/docstring (harmless leftover prose, e.g. "already a chat_app dependency"), never inside executable code or a `patch(...)`/`patch.dict(...)` string. Fix any executable-code hit before moving on.
- Every ported **source** file keeps its original logic, docstrings, and comments verbatim except for the import rewrites above and any change called out explicitly in that file's task. Do not "clean up" or refactor ported code beyond what's specified.
- Secrets for the LLM subsystem live in `src/secrets/secret_llm.env` — **not** `secrets/secret_llm.env`; this project's `secrets/`, `data/`, and `configs/` directories all live under `src/` (`BASE_DIR = Path(__file__).resolve().parent` in `run.py` is `chat_app/src/`), matching where `secret_app.env`/`secret_db.env`/`config_security_*.json` already live — loaded by `run.py` the same way those already are, but **additionally merged into `os.environ`** (via `os.environ.setdefault`, so a real deployment env var always wins over the file) before any page is registered — see Task 1. This lets every ported provider file's own `os.getenv(...)` calls (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `OLLAMA_BASE_URL`, etc.) work completely unchanged, matching how MCPArchitecture's `run.py` calls `load_dotenv()` before any `chat_app.*` import.
- **`chats_db_path`/`staged_plans_db_path`/`chat_config_path` resolve against `BASE_DIR`, not the CWD.** MCPArchitecture's own `Settings` left these CWD-relative, which is exactly the bug this project's `run.py` already has a named fix for (`_resolve_sqlite_uri`'s docstring: a bare relative path "is otherwise resolved by sqlite against the process's working directory, which varies by how the app is launched... and silently breaks db file creation") — applied today to `app.db`. `src/services/llm/settings.py`'s `Settings` dataclass itself stays a plain `_env(...)`-based port (CWD-relative defaults, matching MCPArchitecture's shape, since it has no access to `BASE_DIR`), but Task 1's `run.py` diff sets `CHATS_DB_PATH`/`STAGED_PLANS_DB_PATH`/`CHAT_CONFIG_PATH` as absolute, `BASE_DIR`-resolved env vars (via `os.environ.setdefault`, so a real deployment env var still wins) before `Settings()` is ever instantiated — the same pattern already used for the API-key env vars, just also covering these three paths.
- New permissions (registered via `src.services.authz.register_permission`, enforced via `src.services.authz.require_permission`/`has_permission`): `chat.access`, `capabilities.view`, `capabilities.try`, `logs.chat.view`.
- `Chat/__index__.py` sets `CSRF_EXEMPT = True` and `Capabilities/__index__.py` sets `CSRF_EXEMPT = True` at module level — the mechanism `pages/__index__.py`'s `register_pages()` gains in Task 12 to exempt a blueprint from `Flask-WTF`'s `CSRFProtect` (when it's enabled at all) in favor of the new project-wide `Sec-Fetch-Site`/Origin check.
- **Chat's ported API routes get MCPServer's normal `/chat` url-prefix treatment, unlike the original.** MCPArchitecture's `chat_bp` had no blueprint-level `url_prefix`, so its API routes live at bare `/api/providers`, `/api/chat`, etc. (only the page itself is explicitly `/chat`). This project's `register_pages()` always applies `url_prefix=f"/{folder_name.lower()}"`, so once `Chat/__index__.py`'s routes are registered under folder `Chat`, every one of them — including the APIs — actually lives under `/chat/...`. `Capabilities/__index__.py` already matches (the original explicitly set `url_prefix="/capabilities"`). This means the ported `script.js` for Chat needs nine `fetch()` URLs changed from `/api/...` to `/chat/api/...` — enumerated exactly in Task 13. Capabilities' `script.js` needs no such change.
- **Layout adaptation for both pages' `styles.css`.** MCPArchitecture's pages are standalone HTML documents with a fixed-position sidebar, so both `styles.css` files set `body { ...; margin-left: 190px; }` (plus a matching `@media (max-width: 700px) { body { margin-left: 0; } }` reset) to reserve that sidebar's width. This project's `<body>` is a flexbox (`__shared__/shared.css`) with `.sidebar` and `<main>` as siblings — `<main>` already has its own `flex-grow`/`padding`, so a `margin-left` on `body` is not just unneeded, it visibly breaks the layout (double-reserving space, using the wrong width). Both edits in this plan: **delete** the `margin-left: 190px;` declaration from the `body` rule, and **delete** the whole `@media (max-width: 700px) { body { margin-left: 0; } }` block. Nothing else in either file changes.
- **Chat's history sidebar has nowhere to live and needs new markup+CSS, not a port.** MCPArchitecture's `_shared/template/sidebar.html`/`sidebar.css` (not ported — this project's own `__shared__/sidebar.html` replaces it) is where the "+ New chat" button and `#chat-history-list` panel actually lived; `script.js`'s `loadChatHistory()`/`buildChatHistoryItem()`/`startRenameChat()`/`deleteChatEntry()`/`addOptimisticChatEntry()` all target DOM elements/classes (`#chat-history-list`, `.chat-history-item`, `.chat-history-link`, `.chat-history-time`, `.chat-history-controls`, `.chat-history-rename-btn`, `.chat-history-delete-btn`, `.chat-history-rename-input`, `.chat-history-empty`, `.sidebar-new-chat-btn`) that exist nowhere in the ported `chat.html`/`styles.css` otherwise. Task 13 adds a small, purpose-built panel (new HTML block + new CSS rules, given in full in that task) inside Chat's own page content, to the left of the message log — not a port, since the original CSS for these classes lived in a file this plan deliberately doesn't bring over.
- MCPArchitecture's `modal.js`/`modal.css` (`_shared/template/`) **are** ported, verbatim, but scoped to the Chat page only (as `Chat/modal.js` / `Chat/modal.css`) rather than into `__shared__` — `script.js`'s `removeExtension()` and `deleteChatEntry()` both call `confirmModal(...)`, which this project's own `shared.js` has no equivalent of (`shared.js` only supports declarative `<form data-confirm>` confirmation, not an imperative `await confirmModal({...})` call). Capabilities' `script.js` never calls it, so Capabilities does not get these files.
- Follow existing page-folder conventions exactly: `template_folder="."`, `static_folder="."`, `static_url_path="/static"`, a `README.md`, `PAGE_PERMISSION`/`PAGE_DESCRIPTION`/`PAGE_LAYOUT` module constants (see `src/pages/README.md`).
- No manual `errors.report()`-style module — unexpected exceptions in the ported routes call `src.services.log_service.log_error(...)` directly, matching `run.py`'s existing global handler.
- `chat_config_path` (Ollama's desired-model list) is `src/configs/config_chat.json` by default — alongside the existing `config_security_*.json` files — not `config.json` at the repo root like the original.

---

### Task 1: LLM settings, secrets, Ollama config scaffold, dependencies

**Files:**
- Create: `src/secrets/secret_llm.env`
- Create: `src/secrets/secret_llm.env.example`
- Create: `src/configs/config_chat.json`
- Create: `src/services/llm/__init__.py`
- Create: `src/services/llm/settings.py`
- Modify: `pyproject.toml`
- Modify: `src/run.py`
- Test: `tests/test_llm_settings.py`

**Interfaces:**
- Produces: `src.services.llm.settings.settings` — a frozen dataclass instance with fields `mcp_server_url: str`, `openai_model: str`, `claude_model: str`, `chat_config_path: Path`, `chats_db_path: Path`, `staged_plans_db_path: Path`. Every later task that needs one of these reads it from here.

- [ ] **Step 1: Write the failing test**

Create `tests/test_llm_settings.py`:

```python
import os

import pytest


@pytest.fixture(autouse=True)
def _clear_llm_env(monkeypatch):
    for key in (
        "MCP_SERVER_URL", "OPENAI_MODEL", "CLAUDE_MODEL",
        "CHAT_CONFIG_PATH", "CHATS_DB_PATH", "STAGED_PLANS_DB_PATH",
    ):
        monkeypatch.delenv(key, raising=False)


def test_defaults_when_nothing_configured():
    from src.services.llm.settings import Settings

    settings = Settings()

    assert settings.mcp_server_url == "http://127.0.0.1:8010/mcp"
    assert settings.openai_model == "gpt-5.6-sol"
    assert settings.claude_model == "claude-sonnet-5"
    assert str(settings.chat_config_path) == "src/configs/config_chat.json"
    assert str(settings.chats_db_path) == "data/chats.db"
    assert str(settings.staged_plans_db_path) == "data/staged_plans.db"


def test_env_vars_override_defaults(monkeypatch):
    monkeypatch.setenv("MCP_SERVER_URL", "http://example.test/mcp")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-custom")

    from src.services.llm.settings import Settings

    settings = Settings()

    assert settings.mcp_server_url == "http://example.test/mcp"
    assert settings.openai_model == "gpt-custom"


def test_blank_env_var_counts_as_unset(monkeypatch):
    monkeypatch.setenv("OPENAI_MODEL", "")

    from src.services.llm.settings import Settings

    settings = Settings()

    assert settings.openai_model == "gpt-5.6-sol"


def test_create_app_resolves_llm_paths_against_base_dir(tmp_path, monkeypatch):
    """run.py's create_app() must set CHATS_DB_PATH/STAGED_PLANS_DB_PATH/
    CHAT_CONFIG_PATH as BASE_DIR-absolute paths, not leave them
    CWD-relative - see this task's Global Constraints note on why
    (the same class of bug _resolve_sqlite_uri already exists to fix for
    app.db)."""
    for key in ("CHATS_DB_PATH", "STAGED_PLANS_DB_PATH", "CHAT_CONFIG_PATH"):
        monkeypatch.delenv(key, raising=False)

    from src.run import BASE_DIR, create_app

    create_app({"SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'test.db'}", "TESTING": True})

    assert os.environ["CHATS_DB_PATH"] == str(BASE_DIR / "data" / "chats.db")
    assert os.environ["STAGED_PLANS_DB_PATH"] == str(BASE_DIR / "data" / "staged_plans.db")
    assert os.environ["CHAT_CONFIG_PATH"] == str(BASE_DIR / "configs" / "config_chat.json")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_llm_settings.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.services.llm'`

- [ ] **Step 3: Write minimal implementation**

Create `src/services/llm/__init__.py` (empty file — package marker).

Create `src/services/llm/settings.py`:

```python
"""LLM subsystem settings, read from environment variables.

secret_llm.env's values are merged into os.environ by run.py's
create_app() (via os.environ.setdefault, before any page is registered)
so every os.getenv() call here - and every provider's own direct
os.getenv() call for its API key - sees them without each module needing
to know how they got there. Mirrors chat_app.config.Settings' relevant
fields exactly (see docs/superpowers/specs/2026-08-22-chat-capabilities-
port-design.md).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _env(name: str, default: str) -> str:
    """os.getenv, but an empty value counts as unset."""
    value = os.getenv(name)
    return value if value else default


@dataclass(frozen=True)
class Settings:
    mcp_server_url: str = _env("MCP_SERVER_URL", "http://127.0.0.1:8010/mcp")
    openai_model: str = _env("OPENAI_MODEL", "gpt-5.6-sol")
    claude_model: str = _env("CLAUDE_MODEL", "claude-sonnet-5")
    chat_config_path: Path = Path(_env("CHAT_CONFIG_PATH", "src/configs/config_chat.json"))
    chats_db_path: Path = Path(_env("CHATS_DB_PATH", "data/chats.db"))
    staged_plans_db_path: Path = Path(_env("STAGED_PLANS_DB_PATH", "data/staged_plans.db"))


settings = Settings()
```

Create `src/configs/config_chat.json`:

```json
{}
```

Create `src/secrets/secret_llm.env.example`:

```
# MCP server the chat/capabilities pages talk to.
MCP_SERVER_URL=http://127.0.0.1:8010/mcp

# Leave blank to disable that provider - the chat page's provider
# dropdown grays it out with "(no API key)" rather than erroring.
OPENAI_API_KEY=
OPENAI_MODEL=gpt-5.6-sol

ANTHROPIC_API_KEY=
CLAUDE_MODEL=claude-sonnet-5

# Ollama needs no API key. Leave blank for the default
# http://localhost:11434/v1; set this if Ollama runs on another host.
OLLAMA_BASE_URL=
```

Create `src/secrets/secret_llm.env` (same content as the `.example` file above, blank values — this is the file `run.py` actually loads; fill in real keys locally, never commit real values here). Note `.gitignore` already excludes `src/secrets/*` except `*.env.example`, so this file stays untracked, same as `secret_app.env`/`secret_db.env`.

Modify `pyproject.toml` — change the `dependencies` list from:

```toml
dependencies = [
    "Flask>=3.0",
    "Flask-Login>=0.6",
    "Flask-Session>=0.8",
    "Flask-SQLAlchemy>=3.1",
    "Flask-WTF>=1.2",
    "Flask-Mail>=0.9",
    "python-dotenv>=1.0",
]
```

to:

```toml
dependencies = [
    "Flask>=3.0",
    "Flask-Login>=0.6",
    "Flask-Session>=0.8",
    "Flask-SQLAlchemy>=3.1",
    "Flask-WTF>=1.2",
    "Flask-Mail>=0.9",
    "python-dotenv>=1.0",
    "mcp>=1.28.0",
    "pydantic>=2.13.4",
    "pydantic_core>=2.46.4",
    "openai>=2.43.0",
    "anthropic>=0.121.0",
]
```

Modify `src/run.py` — add `import os` to the top-level imports (currently `import traceback` / `from pathlib import Path`):

```python
import os
import traceback
from pathlib import Path
```

Then, in `create_app()`, change:

```python
    app_secrets = load_env_secrets(BASE_DIR / "secrets" / "secret_app.env")
    db_secrets = load_env_secrets(BASE_DIR / "secrets" / "secret_db.env")
```

to:

```python
    app_secrets = load_env_secrets(BASE_DIR / "secrets" / "secret_app.env")
    db_secrets = load_env_secrets(BASE_DIR / "secrets" / "secret_db.env")
    llm_secrets = load_env_secrets(BASE_DIR / "secrets" / "secret_llm.env")
    for key, value in llm_secrets.items():
        if value:
            os.environ.setdefault(key, value)
    # BASE_DIR-resolved, not CWD-relative - same reasoning as
    # _resolve_sqlite_uri below for app.db. A real CHATS_DB_PATH/
    # STAGED_PLANS_DB_PATH/CHAT_CONFIG_PATH env var (including one already
    # set via secret_llm.env above) still wins - setdefault is a no-op once
    # the key is already present.
    os.environ.setdefault("CHATS_DB_PATH", str(BASE_DIR / "data" / "chats.db"))
    os.environ.setdefault("STAGED_PLANS_DB_PATH", str(BASE_DIR / "data" / "staged_plans.db"))
    os.environ.setdefault("CHAT_CONFIG_PATH", str(BASE_DIR / "configs" / "config_chat.json"))
```

(This runs before `register_pages(app)` further down, which is what matters — `Chat/__index__.py`'s imports transitively import `src.services.llm.settings`/the providers, whose own env reads must see `secret_llm.env`'s values, and these three resolved paths, already merged in.)

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_llm_settings.py -v`
Expected: PASS

- [ ] **Step 5: Install the new dependencies**

Run: `pip install -e ".[dev]"` from `chat_app/` (or the project's normal dependency-sync command) to pull in `mcp`, `pydantic`, `pydantic_core`, `openai`, `anthropic`.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml src/run.py src/services/llm/__init__.py src/services/llm/settings.py src/configs/config_chat.json src/secrets/secret_llm.env.example tests/test_llm_settings.py
git commit -m "feat: add LLM subsystem settings, secrets, and dependencies"
```

---

### Task 2: Port `services/llm/base.py` + `services/llm/cooldown.py`

**Files:**
- Create: `src/services/llm/base.py`
- Create: `src/services/llm/cooldown.py`
- Test: `tests/test_cooldown.py`

**Interfaces:**
- Consumes: nothing (leaf modules, zero internal imports).
- Produces: `src.services.llm.base.{SYSTEM_PROMPT, ToolCallRecord, RecursiveRoundRecord, ChatResult, ModelOption, RunChatFn, IsAvailableFn, ModelAvailability, ModelAvailabilityCheck, CheckModelsFn, ProviderSpec}`; `src.services.llm.cooldown.{DEFAULT_COOLDOWN_SECONDS, start_cooldown, seconds_remaining, is_in_cooldown, reset, extract_retry_after_seconds}`.

- [ ] **Step 1: Copy the source files verbatim**

Copy `MCPArchitecture/chat_app/src/chat_app/services/llm/base.py` to `src/services/llm/base.py` — **no changes** (this file has zero `chat_app.*` imports).

Copy `MCPArchitecture/chat_app/src/chat_app/services/llm/cooldown.py` to `src/services/llm/cooldown.py` — **no changes** (zero `chat_app.*` imports).

- [ ] **Step 2: Port the existing test file**

Copy `MCPArchitecture/chat_app/tests/test_cooldown.py` to `tests/test_cooldown.py`, then apply the Import Rewrite Table: line 7's `from chat_app.services.llm import cooldown` becomes `from src.services.llm import cooldown`. Nothing else in this file references `chat_app`.

- [ ] **Step 3: Run the tests**

Run: `pytest tests/test_cooldown.py -v`
Expected: PASS (all 9 tests)

- [ ] **Step 4: Commit**

```bash
git add src/services/llm/base.py src/services/llm/cooldown.py tests/test_cooldown.py
git commit -m "feat: port LLM base types and rate-limit cooldown tracker"
```

---

### Task 3: Port `services/mcp_client.py`

**Files:**
- Create: `src/services/mcp_client.py`
- Test: `tests/test_mcp_client.py`

**Interfaces:**
- Consumes: `src.services.llm.settings.settings` (Task 1).
- Produces: `src.services.mcp_client.{list_tools, call_tool, list_resource_templates, read_resource, fetch_extensions, add_extension, remove_extension}`.

- [ ] **Step 1: Copy the source file and rewrite its one import**

Copy `MCPArchitecture/chat_app/src/chat_app/services/mcp_client.py` to `src/services/mcp_client.py`. Change line 19 from:

```python
from chat_app.config import settings
```

to:

```python
from src.services.llm.settings import settings
```

No other changes.

- [ ] **Step 2: Port the existing test file**

Copy `MCPArchitecture/chat_app/tests/test_mcp_client.py` to `tests/test_mcp_client.py`. Apply the Import Rewrite Table throughout (the import on line 18, and every `patch("chat_app.services.mcp_client...")` / `patch("chat_app.config...")`-style target string used across the file's ~224 lines). Run `grep -n "chat_app" tests/test_mcp_client.py` afterward and fix any remaining executable-code hit.

- [ ] **Step 3: Run the tests**

Run: `pytest tests/test_mcp_client.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add src/services/mcp_client.py tests/test_mcp_client.py
git commit -m "feat: port MCP client wrapper"
```

---

### Task 4: Port `services/tool_titles.py` + `services/tool_capabilities.py`

**Files:**
- Create: `src/services/tool_titles.py`
- Create: `src/services/tool_capabilities.py`
- Test: `tests/test_tool_titles.py`
- Test: `tests/test_tool_capabilities.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `src.services.tool_titles.title_for(name) -> str`; `src.services.tool_capabilities.{capability_for_tool(name) -> str, capability_for_resource(name) -> str}`.

- [ ] **Step 1: Copy the source files verbatim**

Copy `MCPArchitecture/chat_app/src/chat_app/services/tool_titles.py` to `src/services/tool_titles.py` — no changes (zero `chat_app.*` imports).

Copy `MCPArchitecture/chat_app/src/chat_app/services/tool_capabilities.py` to `src/services/tool_capabilities.py` — no changes.

- [ ] **Step 2: Port the existing test files**

Copy `MCPArchitecture/chat_app/tests/test_tool_titles.py` to `tests/test_tool_titles.py`. Change line 7 `from chat_app.services.tool_titles import title_for` to `from src.services.tool_titles import title_for`, and line 15's `patch.dict("chat_app.services.tool_titles._OVERRIDES", ...)` target to `patch.dict("src.services.tool_titles._OVERRIDES", ...)`.

Copy `MCPArchitecture/chat_app/tests/test_tool_capabilities.py` to `tests/test_tool_capabilities.py`. Change line 5's import to `from src.services.tool_capabilities import capability_for_resource, capability_for_tool`.

- [ ] **Step 3: Run the tests**

Run: `pytest tests/test_tool_titles.py tests/test_tool_capabilities.py -v`
Expected: PASS (5 + 5 tests)

- [ ] **Step 4: Commit**

```bash
git add src/services/tool_titles.py src/services/tool_capabilities.py tests/test_tool_titles.py tests/test_tool_capabilities.py
git commit -m "feat: port tool title and capability-label lookups"
```

---

### Task 5: Port `services/llm/app_config.py`

**Files:**
- Create: `src/services/llm/app_config.py`
- Test: `tests/test_app_config.py`

**Interfaces:**
- Consumes: `src.services.llm.base.ModelOption` (Task 2).
- Produces: `src.services.llm.app_config.{load_config(path) -> dict, load_ollama_models(path) -> list[ModelOption]}`.

- [ ] **Step 1: Copy the source file and rewrite its one import**

Copy `MCPArchitecture/chat_app/src/chat_app/infra/app_config.py` to `src/services/llm/app_config.py`. Change line 24 from:

```python
from chat_app.services.llm.base import ModelOption
```

to:

```python
from src.services.llm.base import ModelOption
```

No other changes.

- [ ] **Step 2: Port the existing test file**

Copy `MCPArchitecture/chat_app/tests/test_app_config.py` to `tests/test_app_config.py`. Change lines 16-17:

```python
from chat_app.infra.app_config import load_ollama_models
from chat_app.services.llm.base import ModelOption
```

to:

```python
from src.services.llm.app_config import load_ollama_models
from src.services.llm.base import ModelOption
```

Run `grep -n "chat_app" tests/test_app_config.py` and fix any other executable-code hit across the file's ~248 lines (the rest is pure config-parsing test logic with `tmp_path`-written JSON, no other module references expected).

- [ ] **Step 3: Run the tests**

Run: `pytest tests/test_app_config.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add src/services/llm/app_config.py tests/test_app_config.py
git commit -m "feat: port Ollama desired-model config loader"
```

---

### Task 6: Port `services/llm/staged_plans_store.py`

**Files:**
- Create: `src/services/llm/staged_plans_store.py`
- Test: `tests/test_staged_plans_store.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `src.services.llm.staged_plans_store.{StagedPlan, save(db_path, chat_id, provider_id, model, plan, step_index, results, ttl_hours=24), get(db_path, chat_id) -> StagedPlan | None, delete(db_path, chat_id)}`.

- [ ] **Step 1: Copy the source file verbatim**

Copy `MCPArchitecture/chat_app/src/chat_app/services/llm/staged_plans_store.py` to `src/services/llm/staged_plans_store.py` — no changes (zero `chat_app.*` imports, pure `sqlite3`/stdlib).

- [ ] **Step 2: Port the existing test file**

Copy `MCPArchitecture/chat_app/tests/test_staged_plans_store.py` to `tests/test_staged_plans_store.py`. Change line 11 `from chat_app.services.llm import staged_plans_store` to `from src.services.llm import staged_plans_store`.

- [ ] **Step 3: Run the tests**

Run: `pytest tests/test_staged_plans_store.py -v`
Expected: PASS (8 tests)

- [ ] **Step 4: Commit**

```bash
git add src/services/llm/staged_plans_store.py tests/test_staged_plans_store.py
git commit -m "feat: port staged-plan ephemeral storage"
```

---

### Task 7: Port `services/llm/staged_pipeline.py`

**Files:**
- Create: `src/services/llm/staged_pipeline.py`
- Test: `tests/test_staged_pipeline.py`

**Interfaces:**
- Consumes: `src.services.llm.staged_plans_store` (Task 6), `src.services.llm.base.{ChatResult, ToolCallRecord}` (Task 2), `src.services.mcp_client.{call_tool, list_tools}` (Task 3).
- Produces: `src.services.llm.staged_pipeline.run(client, question, history, model_name, chat_id, enabled_extensions, db_path) -> ChatResult`.

- [ ] **Step 1: Copy the source file and rewrite its imports**

Copy `MCPArchitecture/chat_app/src/chat_app/services/llm/staged_pipeline.py` to `src/services/llm/staged_pipeline.py`. Change lines 19-21 from:

```python
from chat_app.services.llm import staged_plans_store
from chat_app.services.llm.base import ChatResult, ToolCallRecord
from chat_app.services.mcp_client import call_tool, list_tools
```

to:

```python
from src.services.llm import staged_plans_store
from src.services.llm.base import ChatResult, ToolCallRecord
from src.services.mcp_client import call_tool, list_tools
```

No other changes.

- [ ] **Step 2: Port the existing test file**

Copy `MCPArchitecture/chat_app/tests/test_staged_pipeline.py` to `tests/test_staged_pipeline.py`. Change lines 10-11:

```python
from chat_app.services.llm import staged_pipeline, staged_plans_store
from chat_app.services.llm.base import ToolCallRecord
```

to:

```python
from src.services.llm import staged_pipeline, staged_plans_store
from src.services.llm.base import ToolCallRecord
```

Run `grep -n "chat_app" tests/test_staged_pipeline.py` and fix any other executable-code hit across the file's ~493 lines (expect `patch("chat_app.services.mcp_client...")`-style call-tool mocks further down).

- [ ] **Step 3: Run the tests**

Run: `pytest tests/test_staged_pipeline.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add src/services/llm/staged_pipeline.py tests/test_staged_pipeline.py
git commit -m "feat: port staged enumerate-execute-conclude pipeline"
```

---

### Task 8: Port the three LLM providers (`claude_provider.py`, `openai_provider.py`, `ollama_provider.py`)

**Files:**
- Create: `src/services/llm/claude_provider.py`
- Create: `src/services/llm/openai_provider.py`
- Create: `src/services/llm/ollama_provider.py`
- Test: `tests/test_llm_providers.py`

**Interfaces:**
- Consumes: `src.services.llm.settings.settings` (Task 1), `src.services.llm.cooldown` (Task 2), `src.services.llm.base.*` (Task 2), `src.services.mcp_client.{call_tool, list_tools}` (Task 3), `src.services.llm.app_config.load_ollama_models` (Task 5), `src.services.llm.staged_pipeline` (Task 7).
- Produces: `src.services.llm.claude_provider.PROVIDER`, `src.services.llm.openai_provider.PROVIDER`, `src.services.llm.ollama_provider.PROVIDER` — each a `ProviderSpec` (Task 2's `base.py`), consumed by `router.py` in Task 9.

- [ ] **Step 1: Copy `claude_provider.py` and rewrite its imports**

Copy `MCPArchitecture/chat_app/src/chat_app/services/llm/claude_provider.py` to `src/services/llm/claude_provider.py`. Change lines 21-24 from:

```python
from chat_app.config import settings
from chat_app.services.llm import cooldown
from chat_app.services.llm.base import SYSTEM_PROMPT, ChatResult, ModelOption, ProviderSpec, ToolCallRecord
from chat_app.services.mcp_client import call_tool, list_tools
```

to:

```python
from src.services.llm.settings import settings
from src.services.llm import cooldown
from src.services.llm.base import SYSTEM_PROMPT, ChatResult, ModelOption, ProviderSpec, ToolCallRecord
from src.services.mcp_client import call_tool, list_tools
```

- [ ] **Step 2: Copy `openai_provider.py` and rewrite its imports**

Copy `MCPArchitecture/chat_app/src/chat_app/services/llm/openai_provider.py` to `src/services/llm/openai_provider.py`. Change lines 16-19 from:

```python
from chat_app.config import settings
from chat_app.services.llm import cooldown
from chat_app.services.llm.base import SYSTEM_PROMPT, ChatResult, ModelOption, ProviderSpec, ToolCallRecord
from chat_app.services.mcp_client import call_tool, list_tools
```

to the same `src.*` rewrite as Step 1.

- [ ] **Step 3: Copy `ollama_provider.py` and rewrite its imports**

Copy `MCPArchitecture/chat_app/src/chat_app/services/llm/ollama_provider.py` to `src/services/llm/ollama_provider.py`. Change lines 62-75 from:

```python
from chat_app.config import settings
from chat_app.infra.app_config import load_ollama_models
from chat_app.services.llm import staged_pipeline
from chat_app.services.llm.base import (
    SYSTEM_PROMPT,
    ChatResult,
    ModelAvailability,
    ModelAvailabilityCheck,
    ModelOption,
    ProviderSpec,
    RecursiveRoundRecord,
    ToolCallRecord,
)
from chat_app.services.mcp_client import call_tool, list_tools
```

to:

```python
from src.services.llm.settings import settings
from src.services.llm.app_config import load_ollama_models
from src.services.llm import staged_pipeline
from src.services.llm.base import (
    SYSTEM_PROMPT,
    ChatResult,
    ModelAvailability,
    ModelAvailabilityCheck,
    ModelOption,
    ProviderSpec,
    RecursiveRoundRecord,
    ToolCallRecord,
)
from src.services.mcp_client import call_tool, list_tools
```

Leave the inline `from openai import OpenAI` inside `_get_client()` untouched (third-party import, not a `chat_app.*` one).

- [ ] **Step 4: Port the existing test file**

Copy `MCPArchitecture/chat_app/tests/test_llm_providers.py` to `tests/test_llm_providers.py`. Change line 21-22 from:

```python
from chat_app.services.llm import claude_provider, cooldown, ollama_provider, openai_provider
from chat_app.services.llm.base import ChatResult, RecursiveRoundRecord, SYSTEM_PROMPT, ModelOption, ToolCallRecord
```

to:

```python
from src.services.llm import claude_provider, cooldown, ollama_provider, openai_provider
from src.services.llm.base import ChatResult, RecursiveRoundRecord, SYSTEM_PROMPT, ModelOption, ToolCallRecord
```

Then apply the Import Rewrite Table across the rest of the file's ~763 lines (every `patch("chat_app.services.llm...")` mock target). Run `grep -n "chat_app" tests/test_llm_providers.py` afterward and fix any remaining executable-code hit.

- [ ] **Step 5: Run the tests**

Run: `pytest tests/test_llm_providers.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/services/llm/claude_provider.py src/services/llm/openai_provider.py src/services/llm/ollama_provider.py tests/test_llm_providers.py
git commit -m "feat: port Claude, OpenAI, and Ollama LLM providers"
```

---

### Task 9: Port `services/llm/router.py`

**Files:**
- Create: `src/services/llm/router.py`
- Test: `tests/test_router.py`

**Interfaces:**
- Consumes: `src.services.llm.{claude_provider, cooldown, ollama_provider, openai_provider}` (Tasks 2, 8), `src.services.llm.base.{ChatResult, ProviderSpec}` (Task 2).
- Produces: `src.services.llm.router.{list_providers() -> list[dict], run_chat(question, history, provider_id, model_id=None, enabled_extensions=None, chat_id=None) -> ChatResult, AUTOMATIC_ID, DEFAULT_PROVIDER_ID}` — this is what `Chat/__index__.py` (Task 13) calls directly.

- [ ] **Step 1: Copy the source file and rewrite its imports**

Copy `MCPArchitecture/chat_app/src/chat_app/services/llm/router.py` to `src/services/llm/router.py`. Change lines 13-14 from:

```python
from chat_app.services.llm import claude_provider, cooldown, ollama_provider, openai_provider
from chat_app.services.llm.base import ChatResult, ProviderSpec
```

to:

```python
from src.services.llm import claude_provider, cooldown, ollama_provider, openai_provider
from src.services.llm.base import ChatResult, ProviderSpec
```

No other changes.

- [ ] **Step 2: Port the existing test file**

Copy `MCPArchitecture/chat_app/tests/test_router.py` to `tests/test_router.py`. Change lines 10-11:

```python
from chat_app.services.llm import cooldown, router
from chat_app.services.llm.base import ChatResult, ModelAvailability, ModelAvailabilityCheck, ModelOption
```

to:

```python
from src.services.llm import cooldown, router
from src.services.llm.base import ChatResult, ModelAvailability, ModelAvailabilityCheck, ModelOption
```

Run `grep -n "chat_app" tests/test_router.py` and fix any remaining hit across the file's ~365 lines.

- [ ] **Step 3: Run the tests**

Run: `pytest tests/test_router.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add src/services/llm/router.py tests/test_router.py
git commit -m "feat: port LLM provider router"
```

---

### Task 10: Port `chats_store.py`

**Files:**
- Create: `src/services/chats_store.py`
- Test: `tests/test_chats_store.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `src.services.chats_store.{UnknownChat, save_chat(db_path, username, chat_id, messages) -> str, list_chats(db_path, username) -> list[dict], get_chat(db_path, username, chat_id) -> dict | None, rename_chat(db_path, username, chat_id, title), delete_chat(db_path, username, chat_id)}` — consumed by `Chat/__index__.py` in Task 13.

- [ ] **Step 1: Copy the source file verbatim**

Copy `MCPArchitecture/chat_app/src/chat_app/chats/store.py` to `src/services/chats_store.py` — no changes (zero `chat_app.*` imports, pure `sqlite3`/stdlib). Note the relocation: this becomes a single module (`src/services/chats_store.py`), not a `chats/` sub-package — there is no `__init__.py` to also copy.

- [ ] **Step 2: Port the existing test file**

Copy `MCPArchitecture/chat_app/tests/test_chats_store.py` to `tests/test_chats_store.py`. Change line 7 `from chat_app.chats import store` to `from src.services import chats_store as store` (keeps every subsequent `store.save_chat(...)`-style call in the file working unchanged, since it's all via the `store` alias).

- [ ] **Step 3: Run the tests**

Run: `pytest tests/test_chats_store.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add src/services/chats_store.py tests/test_chats_store.py
git commit -m "feat: port per-user chat history store"
```

---

### Task 11: `log_service.log_chat_trace`

**Files:**
- Modify: `src/services/log_service.py`
- Test: `tests/test_log_service.py`

**Interfaces:**
- Consumes: `src.models.{Account, LogEntry}` (existing).
- Produces: `src.services.log_service.log_chat_trace(session, account, source, message, details=None) -> LogEntry` — writes `kind="chat_trace"`. Consumed by `Chat/__index__.py`'s `chat_api()` in Task 13, and read back by the Logs page's third tab in Task 15.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_log_service.py`:

```python
def test_log_chat_trace_writes_entry_for_account(app):
    with app.app_context():
        account = _make_account("svc_trace_user")

        entry = log_service.log_chat_trace(db.session, account, "chat.turn", "did a turn", details='{"tool_calls": []}')

        assert entry.id is not None
        assert entry.kind == "chat_trace"
        assert entry.account_id == account.id
        assert entry.source == "chat.turn"
        assert entry.message == "did a turn"
        assert entry.details == '{"tool_calls": []}'


def test_list_entries_filters_chat_trace_kind(app):
    with app.app_context():
        account = _make_account("svc_trace_filter_user")
        log_service.log_chat_trace(db.session, account, "chat.turn", "turn one")
        log_service.log_action(db.session, account, "a", "an action")

        traces = log_service.list_entries(db.session, "chat_trace", account_id=account.id)

        assert [e.message for e in traces] == ["turn one"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_log_service.py -v`
Expected: FAIL with `AttributeError: module 'src.services.log_service' has no attribute 'log_chat_trace'`

- [ ] **Step 3: Write minimal implementation**

In `src/services/log_service.py`, add (after `log_action`, before `log_error`, to keep the file's three "write" functions grouped before `list_entries`):

```python
def log_chat_trace(db_session, account: Account, source: str, message: str, details: str | None = None) -> LogEntry:
    entry = LogEntry(
        kind="chat_trace",
        account_id=account.id,
        source=source,
        message=message,
        details=details,
    )
    db_session.add(entry)
    db_session.commit()
    return entry
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_log_service.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/services/log_service.py tests/test_log_service.py
git commit -m "feat: add log_chat_trace for per-turn chat logging"
```

---

### Task 12: Cross-site protection and CSRF-exemption plumbing

**Files:**
- Create: `src/services/security/cross_site.py`
- Modify: `src/services/security/pipeline.py`
- Modify: `src/pages/__index__.py`
- Modify: `src/run.py`
- Test: `tests/test_cross_site.py`
- Test: `tests/test_pipeline.py`
- Test: `tests/test_pages_index.py`

**Interfaces:**
- Produces: `src.services.security.cross_site.check_cross_site() -> None` (raises via Flask `abort(403)` on rejection); `src.services.security.pipeline.register_security_pipeline(app, configs) -> CSRFProtect | None` (return type changed — was `-> None`); `src.pages.__index__.register_pages(app, pages_dir=..., package_prefix=..., csrf=None)` (new `csrf` parameter) — consumed by `Chat`/`Capabilities`' `CSRF_EXEMPT = True` module flag in Tasks 13-14.

- [ ] **Step 1: Write the failing test for `check_cross_site`**

Create `tests/test_cross_site.py`:

```python
from flask import Flask
from werkzeug.exceptions import Forbidden
import pytest

from src.services.security.cross_site import check_cross_site


@pytest.fixture
def app():
    return Flask(__name__)


def test_get_requests_are_always_allowed(app):
    with app.test_request_context("/", method="GET", headers={"Sec-Fetch-Site": "cross-site"}):
        assert check_cross_site() is None


def test_post_with_same_origin_sec_fetch_site_is_allowed(app):
    with app.test_request_context("/", method="POST", headers={"Sec-Fetch-Site": "same-origin"}):
        assert check_cross_site() is None


def test_post_with_none_sec_fetch_site_is_allowed(app):
    with app.test_request_context("/", method="POST", headers={"Sec-Fetch-Site": "none"}):
        assert check_cross_site() is None


def test_post_with_cross_site_sec_fetch_site_is_rejected(app):
    with app.test_request_context("/", method="POST", headers={"Sec-Fetch-Site": "cross-site"}):
        with pytest.raises(Forbidden):
            check_cross_site()


def test_post_with_no_sec_fetch_site_and_matching_origin_is_allowed(app):
    with app.test_request_context("/", method="POST", base_url="http://localhost", headers={"Origin": "http://localhost"}):
        assert check_cross_site() is None


def test_post_with_no_sec_fetch_site_and_mismatched_origin_is_rejected(app):
    with app.test_request_context("/", method="POST", base_url="http://localhost", headers={"Origin": "http://evil.example"}):
        with pytest.raises(Forbidden):
            check_cross_site()


def test_post_with_neither_header_is_allowed(app):
    """No Sec-Fetch-Site and no Origin: a non-browser client (curl, a
    script) - nothing to check against, so it passes, same as
    MCPArchitecture's own check_cross_site."""
    with app.test_request_context("/", method="POST"):
        assert check_cross_site() is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cross_site.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.services.security.cross_site'`

- [ ] **Step 3: Write minimal implementation**

Create `src/services/security/cross_site.py`:

```python
"""Cross-site request rejection for state-changing requests.

Stands in for a CSRF token on routes that are exempted from Flask-WTF's
CSRFProtect (see pages/__index__.py's CSRF_EXEMPT support) - Chat and
Capabilities' JSON fetch() calls don't carry one. Sec-Fetch-Site is set
by the browser itself and unsettable from page JavaScript, so when it's
present it's trustworthy; Origin is the fallback for a browser too old
to send Sec-Fetch-Site (or a non-browser client, which sends neither and
passes through - nothing to check against). Ported from
chat_app.security.check_cross_site (MCPArchitecture), which this
project's security pipeline had no equivalent of.
"""

from __future__ import annotations

from urllib.parse import urlparse

from flask import abort, request

_STATE_CHANGING = {"POST", "PUT", "PATCH", "DELETE"}


def check_cross_site() -> None:
    if request.method not in _STATE_CHANGING:
        return

    fetch_site = request.headers.get("Sec-Fetch-Site")
    if fetch_site is not None:
        if fetch_site in {"same-origin", "none"}:
            return
        abort(403, description=f"Cross-site {request.method} requests are not allowed.")

    origin = request.headers.get("Origin")
    if origin:
        origin_host = (urlparse(origin).netloc or "").lower()
        if origin_host != (request.host or "").lower():
            abort(403, description="Cross-origin requests are not allowed.")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_cross_site.py -v`
Expected: PASS

- [ ] **Step 5: Write the failing test for pipeline wiring**

`tests/test_pipeline.py` already has a `_build_test_app(tmp_path, ip_filter_config=None, rate_limit_config=None, headers_config=None)` helper that registers a GET-only `/ping` route and then calls `register_security_pipeline(app, configs)`. Append these tests, using that existing helper as-is:

```python
def test_pipeline_rejects_cross_site_post(tmp_path):
    app = _build_test_app(tmp_path)
    client = app.test_client()

    response = client.post("/ping", headers={"Sec-Fetch-Site": "cross-site"})

    assert response.status_code == 403


def test_pipeline_allows_same_origin_post(tmp_path):
    app = _build_test_app(tmp_path)
    client = app.test_client()

    response = client.post("/ping", headers={"Sec-Fetch-Site": "same-origin"})

    # /ping only handles GET - a 405 here (not 403) proves the cross-site
    # check let the request through to normal Flask routing, which then
    # rejects the method itself.
    assert response.status_code == 405


def test_register_security_pipeline_returns_csrf_extension_when_enabled(tmp_path):
    from flask import Flask
    from flask_wtf import CSRFProtect

    from src.models import db
    from src.services.security.pipeline import register_security_pipeline

    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{tmp_path / 'csrf_return_test.db'}"
    app.config["SECRET_KEY"] = "test-secret"
    db.init_app(app)
    with app.app_context():
        db.create_all()

    result = register_security_pipeline(
        app,
        {
            "config_security_headers": {
                "enabled": True,
                "content_security_policy": None,
                "hsts_max_age": None,
                "force_https": False,
                "csrf_enabled": True,
            }
        },
    )

    assert isinstance(result, CSRFProtect)


def test_register_security_pipeline_returns_none_when_csrf_disabled(tmp_path):
    from flask import Flask

    from src.models import db
    from src.services.security.pipeline import register_security_pipeline

    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{tmp_path / 'csrf_return_test2.db'}"
    app.config["SECRET_KEY"] = "test-secret"
    db.init_app(app)
    with app.app_context():
        db.create_all()

    result = register_security_pipeline(app, {"config_security_headers": {"enabled": False}})

    assert result is None
```

- [ ] **Step 6: Run test to verify it fails**

Run: `pytest tests/test_pipeline.py -v`
Expected: `test_pipeline_rejects_cross_site_post` FAILS (status 405, not 403 — nothing rejects the cross-site header yet). The other three may already pass by accident (same-origin was never blocked; the function already implicitly returns `None`) — that's fine, they become regression guards for Step 7's changes.

- [ ] **Step 7: Modify `pipeline.py`**

In `src/services/security/pipeline.py`, change:

```python
from flask import Flask, abort, redirect, request
from flask_wtf import CSRFProtect

from src.models import db
from src.services.security.headers import build_security_headers, should_force_https
from src.services.security.ip_filter import evaluate_ip
from src.services.security.rate_limit import check_rate_limit
from src.utils.config_loader import load_all_json_configs
```

to:

```python
from flask import Flask, abort, redirect, request
from flask_wtf import CSRFProtect

from src.models import db
from src.services.security.cross_site import check_cross_site
from src.services.security.headers import build_security_headers, should_force_https
from src.services.security.ip_filter import evaluate_ip
from src.services.security.rate_limit import check_rate_limit
from src.utils.config_loader import load_all_json_configs
```

Then change:

```python
def register_security_pipeline(app: Flask, configs: dict) -> None:
    ip_filter_config = configs.get("config_security_ip_filter", {"enabled": False})
    rate_limit_config = configs.get("config_security_rate_limit", {"enabled": False})
    headers_config = configs.get("config_security_headers", {"enabled": False})

    if headers_config.get("enabled", False) and headers_config.get("csrf_enabled", False):
        CSRFProtect(app)

    @app.before_request
    def _security_pipeline_before_request():
        ip_address = request.remote_addr or "unknown"

        if should_force_https(headers_config) and not request.is_secure:
            forced_url = request.url.replace("http://", "https://", 1)
            return redirect(forced_url, code=301)

        allowed, reason = evaluate_ip(ip_filter_config, ip_address)
        if not allowed:
            abort(403, description=reason)

        result = check_rate_limit(rate_limit_config, db.session, ip_address)
        if not result.allowed:
            abort(429, description=result.reason)

    @app.after_request
    def _security_pipeline_after_request(response):
        for header, value in build_security_headers(headers_config).items():
            response.headers[header] = value
        return response
```

to:

```python
def register_security_pipeline(app: Flask, configs: dict) -> CSRFProtect | None:
    ip_filter_config = configs.get("config_security_ip_filter", {"enabled": False})
    rate_limit_config = configs.get("config_security_rate_limit", {"enabled": False})
    headers_config = configs.get("config_security_headers", {"enabled": False})

    csrf_extension = None
    if headers_config.get("enabled", False) and headers_config.get("csrf_enabled", False):
        csrf_extension = CSRFProtect(app)

    @app.before_request
    def _security_pipeline_before_request():
        ip_address = request.remote_addr or "unknown"

        if should_force_https(headers_config) and not request.is_secure:
            forced_url = request.url.replace("http://", "https://", 1)
            return redirect(forced_url, code=301)

        allowed, reason = evaluate_ip(ip_filter_config, ip_address)
        if not allowed:
            abort(403, description=reason)

        result = check_rate_limit(rate_limit_config, db.session, ip_address)
        if not result.allowed:
            abort(429, description=result.reason)

        check_cross_site()

    @app.after_request
    def _security_pipeline_after_request(response):
        for header, value in build_security_headers(headers_config).items():
            response.headers[header] = value
        return response

    return csrf_extension
```

- [ ] **Step 8: Run test to verify it passes**

Run: `pytest tests/test_pipeline.py -v`
Expected: PASS (including every pre-existing test in this file — re-run the whole file, not just the two new tests, since the function signature changed)

- [ ] **Step 9: Write the failing test for `register_pages`'s CSRF exemption**

`tests/test_pages_index.py` doesn't currently mock page discovery at all (its existing tests call `register_pages(app)` against the real `src/pages/` directory) — none of the real pages set `CSRF_EXEMPT` yet at this point in the plan (Chat/Capabilities land in Tasks 13-14), so this test mocks `discover_page_modules`/`importlib.import_module` directly via `unittest.mock.patch.object` rather than relying on any real page. Append:

```python
def test_register_pages_exempts_csrf_only_when_flagged():
    from types import SimpleNamespace
    from unittest.mock import MagicMock, patch

    from flask import Blueprint, Flask

    import src.pages.__index__ as pages_index

    exempt_blueprint = Blueprint("exemptfake", __name__)
    normal_blueprint = Blueprint("normalfake", __name__)
    exempt_module = SimpleNamespace(blueprint=exempt_blueprint, CSRF_EXEMPT=True)
    normal_module = SimpleNamespace(blueprint=normal_blueprint)  # no CSRF_EXEMPT attribute at all

    def fake_import_module(name):
        return exempt_module if name.endswith(".ExemptFake.__index__") else normal_module

    app = Flask(__name__)
    app.config["SECRET_KEY"] = "test-secret"
    csrf = MagicMock()

    with patch.object(pages_index, "discover_page_modules", return_value=["ExemptFake", "NormalFake"]), \
         patch.object(pages_index.importlib, "import_module", side_effect=fake_import_module):
        pages_index.register_pages(app, csrf=csrf)

    csrf.exempt.assert_called_once_with(exempt_blueprint)


def test_register_pages_never_calls_exempt_when_csrf_is_none():
    from types import SimpleNamespace
    from unittest.mock import patch

    from flask import Blueprint, Flask

    import src.pages.__index__ as pages_index

    exempt_blueprint = Blueprint("exemptfake2", __name__)
    exempt_module = SimpleNamespace(blueprint=exempt_blueprint, CSRF_EXEMPT=True)

    app = Flask(__name__)
    app.config["SECRET_KEY"] = "test-secret"

    with patch.object(pages_index, "discover_page_modules", return_value=["ExemptFake2"]), \
         patch.object(pages_index.importlib, "import_module", return_value=exempt_module):
        pages_index.register_pages(app, csrf=None)  # must not raise
```

- [ ] **Step 10: Run test to verify it fails**

Run: `pytest tests/test_pages_index.py -v`
Expected: FAIL with `TypeError: register_pages() got an unexpected keyword argument 'csrf'`

- [ ] **Step 11: Modify `pages/__index__.py`**

Change:

```python
def register_pages(
    app: Flask, pages_dir: Path = PAGES_DIR, package_prefix: str = "src.pages"
) -> None:
    pages = []
    for folder_name in discover_page_modules(pages_dir):
        module = importlib.import_module(f"{package_prefix}.{folder_name}.__index__")
        blueprint = getattr(module, "blueprint")
        page_permission = getattr(module, "PAGE_PERMISSION", None)
        page_description = getattr(module, "PAGE_DESCRIPTION", None)
        page_layout = getattr(module, "PAGE_LAYOUT", "full")
        url_prefix = _url_prefix_for(folder_name)
        app.register_blueprint(blueprint, url_prefix=url_prefix)
        pages.append(
```

to:

```python
def register_pages(
    app: Flask, pages_dir: Path = PAGES_DIR, package_prefix: str = "src.pages", csrf=None
) -> None:
    pages = []
    for folder_name in discover_page_modules(pages_dir):
        module = importlib.import_module(f"{package_prefix}.{folder_name}.__index__")
        blueprint = getattr(module, "blueprint")
        page_permission = getattr(module, "PAGE_PERMISSION", None)
        page_description = getattr(module, "PAGE_DESCRIPTION", None)
        page_layout = getattr(module, "PAGE_LAYOUT", "full")
        url_prefix = _url_prefix_for(folder_name)
        app.register_blueprint(blueprint, url_prefix=url_prefix)
        if csrf is not None and getattr(module, "CSRF_EXEMPT", False):
            csrf.exempt(blueprint)
        pages.append(
```

(Everything after `pages.append(` is unchanged.)

- [ ] **Step 12: Run test to verify it passes**

Run: `pytest tests/test_pages_index.py -v`
Expected: PASS (whole file)

- [ ] **Step 13: Wire it up in `run.py`**

In `src/run.py`'s `create_app()`, change:

```python
    security_configs = load_security_configs(BASE_DIR / "configs")
    register_security_pipeline(app, security_configs)

    init_login_manager(app)
    init_mail(app, BASE_DIR / "secrets")
    register_pages(app)
```

to:

```python
    security_configs = load_security_configs(BASE_DIR / "configs")
    csrf_extension = register_security_pipeline(app, security_configs)

    init_login_manager(app)
    init_mail(app, BASE_DIR / "secrets")
    register_pages(app, csrf=csrf_extension)
```

- [ ] **Step 14: Run the full test suite to check for regressions**

Run: `pytest -v`
Expected: PASS (every previously-passing test still passes — `register_security_pipeline`'s signature change and the new `check_cross_site()` call in its `before_request` are the only behavior changes touching existing routes; confirm no existing test relied on the old `-> None` return or broke on the (very permissive, only rejects an actual mismatched cross-site POST/PUT/PATCH/DELETE) new check)

- [ ] **Step 15: Commit**

```bash
git add src/services/security/cross_site.py src/services/security/pipeline.py src/pages/__index__.py src/run.py tests/test_cross_site.py tests/test_pipeline.py tests/test_pages_index.py
git commit -m "feat: add cross-site request check and per-page CSRF exemption"
```

---

### Task 13: Chat page

**Files:**
- Create: `src/pages/Chat/__index__.py`
- Create: `src/pages/Chat/chat.html`
- Create: `src/pages/Chat/styles.css`
- Create: `src/pages/Chat/script.js`
- Create: `src/pages/Chat/modal.css`
- Create: `src/pages/Chat/modal.js`
- Create: `src/pages/Chat/README.md`
- Test: `tests/test_chat_page.py`

**Interfaces:**
- Consumes: `src.services.chats_store` (Task 10), `src.services.llm.router` (Task 9), `src.services.llm.base.{RecursiveRoundRecord, ToolCallRecord}` (Task 2), `src.services.llm.settings.settings` (Task 1), `src.services.mcp_client.{add_extension, fetch_extensions, remove_extension}` (Task 3), `src.services.log_service.{log_chat_trace, log_error}` (Task 11, existing), `src.services.authz.{register_permission, require_permission}` (existing).
- Produces: blueprint `chat`, routes `/chat/`, `/chat/api/providers`, `/chat/api/extensions` (GET/POST), `/chat/api/extensions/<id>` (DELETE), `/chat/api/chats` (GET), `/chat/api/chats/<id>` (GET/PATCH/DELETE), `/chat/api/chat` (POST). Permission `chat.access`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_chat_page.py`, following `tests/test_logs_page.py`'s exact app-building pattern (`_build_logs_test_app`/`_create_account`/`_login_as`) but for the chat page:

```python
import dataclasses
from unittest.mock import patch

from flask import Flask
from werkzeug.security import generate_password_hash

from src.models import Account, LogEntry, Permission, Role, db
from src.pages.__index__ import register_pages
from src.pages.Chat import __index__ as chat_index
from src.services.auth_service import init_login_manager
from src.services.email_service import init_mail

from pathlib import Path

_SHARED_TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "src" / "pages" / "__shared__"


def _build_chat_test_app(tmp_path, monkeypatch):
    # Isolate chats_db_path per test - src.services.llm.settings.settings
    # is a module-level singleton (see Task 1), and this test never goes
    # through run.py's create_app() (which is what resolves it against
    # BASE_DIR), so without this every test in this file would share one
    # real, un-isolated data/chats.db relative to wherever pytest's cwd
    # happens to be - the same dataclasses.replace + monkeypatch.setattr
    # pattern MCPArchitecture's own conftest.py used for this exact
    # problem (its chats_db fixture).
    monkeypatch.setattr(
        chat_index, "settings", dataclasses.replace(chat_index.settings, chats_db_path=tmp_path / "chats.db")
    )

    app = Flask(
        __name__,
        template_folder=str(_SHARED_TEMPLATES_DIR),
        static_folder=str(_SHARED_TEMPLATES_DIR),
        static_url_path="/shared/static",
    )
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{tmp_path / 'chat_test.db'}"
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["SECRET_KEY"] = "test-secret"
    app.config["MAIL_SUPPRESS_SEND"] = True

    db.init_app(app)
    with app.app_context():
        db.create_all()

    init_login_manager(app)
    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir()
    init_mail(app, secrets_dir)
    register_pages(app)

    return app


def _create_account(app, username, permission_names):
    with app.app_context():
        account = Account(
            username=username,
            email=f"{username}@example.com",
            password_hash=generate_password_hash("pw"),
        )
        if permission_names:
            role = Role(name=f"{username}_role")
            db.session.add(role)
            for name in permission_names:
                permission = db.session.query(Permission).filter_by(name=name).first()
                if permission is None:
                    permission = Permission(name=name)
                    db.session.add(permission)
                role.permissions.append(permission)
            account.roles.append(role)
        db.session.add(account)
        db.session.commit()
        return account.id


def _login_as(client, account_id):
    with client.session_transaction() as flask_session:
        flask_session["_user_id"] = str(account_id)
        flask_session["_fresh"] = True


def test_chat_page_requires_authentication(tmp_path, monkeypatch):
    app = _build_chat_test_app(tmp_path, monkeypatch)
    client = app.test_client()

    response = client.get("/chat/")

    assert response.status_code == 401


def test_chat_page_forbidden_without_chat_access_permission(tmp_path, monkeypatch):
    app = _build_chat_test_app(tmp_path, monkeypatch)
    account_id = _create_account(app, "nochataccess", [])
    client = app.test_client()
    _login_as(client, account_id)

    response = client.get("/chat/")

    assert response.status_code == 403


def test_chat_page_renders_with_chat_access_permission(tmp_path, monkeypatch):
    app = _build_chat_test_app(tmp_path, monkeypatch)
    account_id = _create_account(app, "chatuser", ["chat.access"])
    client = app.test_client()
    _login_as(client, account_id)

    response = client.get("/chat/")

    assert response.status_code == 200
    assert b"chat-history-list" in response.data


def test_chat_api_requires_chat_access_permission(tmp_path, monkeypatch):
    app = _build_chat_test_app(tmp_path, monkeypatch)
    account_id = _create_account(app, "nochatapi", [])
    client = app.test_client()
    _login_as(client, account_id)

    response = client.post("/chat/api/chat", json={"question": "hi"})

    assert response.status_code == 403


def test_chat_api_persists_chat_trace_log_entry_on_success(tmp_path, monkeypatch):
    app = _build_chat_test_app(tmp_path, monkeypatch)
    account_id = _create_account(app, "traceuser", ["chat.access"])
    client = app.test_client()
    _login_as(client, account_id)

    from src.services.llm.base import ChatResult

    fake_result = ChatResult(response="hello back", provider_id="openai", model="gpt-5.6-sol", total_tokens=42)
    with patch.object(chat_index.router, "run_chat", return_value=fake_result):
        response = client.post("/chat/api/chat", json={"question": "hi", "history": []})

    assert response.status_code == 200
    with app.app_context():
        traces = db.session.query(LogEntry).filter_by(kind="chat_trace", account_id=account_id).all()
        assert len(traces) == 1
        assert "hi" in traces[0].message


def test_chat_api_unexpected_error_produces_log_entry_and_safe_response(tmp_path, monkeypatch):
    app = _build_chat_test_app(tmp_path, monkeypatch)
    account_id = _create_account(app, "erroruser2", ["chat.access"])
    client = app.test_client()
    _login_as(client, account_id)

    with patch.object(chat_index.router, "run_chat", side_effect=RuntimeError("boom")):
        response = client.post("/chat/api/chat", json={"question": "hi", "history": []})

    assert response.status_code == 200
    assert "boom" not in response.get_json()["response"]
    with app.app_context():
        errors = db.session.query(LogEntry).filter_by(kind="error", account_id=account_id).all()
        assert len(errors) == 1
        assert "boom" in errors[0].details
```

Note: `chat_index.settings` is imported once at module scope above and reused by every test that follows — `monkeypatch.setattr` inside `_build_chat_test_app` rebinds that same module-level name for the duration of each test, auto-restored afterward.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_chat_page.py -v`
Expected: FAIL at collection — `ModuleNotFoundError: No module named 'src.pages.Chat'` (the module-level `from src.pages.Chat import __index__ as chat_index` import fails before any test runs, since that folder doesn't exist yet).

- [ ] **Step 3: Write `src/pages/Chat/__index__.py`**

```python
"""Chat page: LLM conversation UI, provider/extension APIs, and per-user
chat history. Ported from MCPArchitecture's
chat_app/src/chat_app/pages/chat/routes.py - see
docs/superpowers/specs/2026-08-22-chat-capabilities-port-design.md.
"""

from __future__ import annotations

import json
import time
import traceback
import urllib.error

from flask import Blueprint, jsonify, render_template, request
from flask_login import current_user

from src.models import db
from src.services import chats_store, log_service
from src.services.authz import register_permission, require_permission
from src.services.llm import router
from src.services.llm.base import RecursiveRoundRecord, ToolCallRecord
from src.services.llm.settings import settings
from src.services.mcp_client import add_extension, fetch_extensions, remove_extension

blueprint = Blueprint(
    "chat", __name__, template_folder=".", static_folder=".", static_url_path="/static"
)

PAGE_PERMISSION = "chat.access"
PAGE_DESCRIPTION = "Chat with the MCP-connected LLM."
PAGE_LAYOUT = "full"
CSRF_EXEMPT = True

register_permission("chat.access")

_MESSAGE_MAX = 200
_TRACE_MESSAGE_MAX = 500


@blueprint.route("/")
@require_permission("chat.access")
def index():
    return render_template("chat.html")


@blueprint.route("/api/providers")
@require_permission("chat.access")
def providers_api():
    return jsonify(router.list_providers())


@blueprint.route("/api/extensions")
@require_permission("chat.access")
def extensions_api():
    try:
        extensions = fetch_extensions()
        error = None
    except Exception as exc:  # noqa: BLE001 - surface any error to the sidebar
        extensions = []
        error = str(exc)
    return jsonify({"extensions": extensions, "error": error})


def _forward_extension_error(exc: urllib.error.HTTPError):
    try:
        body = json.loads(exc.read().decode("utf-8"))
        message = body.get("error") or f"mcp_server returned {exc.code}."
    except Exception:  # noqa: BLE001 - body wasn't parseable JSON
        message = f"mcp_server returned {exc.code}."
    return jsonify({"error": message}), exc.code


@blueprint.route("/api/extensions", methods=["POST"])
@require_permission("chat.access")
def add_extension_api():
    data = request.get_json(silent=True) or {}
    label = (data.get("label") or "").strip()
    url = (data.get("url") or "").strip()
    description = (data.get("description") or "").strip()
    if not label or not url:
        return jsonify({"error": "Label and URL are required."}), 400
    try:
        status = add_extension(label, url, description)
        return jsonify(status), 201
    except urllib.error.HTTPError as exc:
        return _forward_extension_error(exc)
    except Exception as exc:  # noqa: BLE001 - e.g. mcp_server unreachable
        return jsonify({"error": str(exc)}), 502


@blueprint.route("/api/extensions/<extension_id>", methods=["DELETE"])
@require_permission("chat.access")
def remove_extension_api(extension_id):
    try:
        remove_extension(extension_id)
        return "", 204
    except urllib.error.HTTPError as exc:
        return _forward_extension_error(exc)
    except Exception as exc:  # noqa: BLE001 - e.g. mcp_server unreachable
        return jsonify({"error": str(exc)}), 502


@blueprint.route("/api/chats")
@require_permission("chat.access")
def list_chats_api():
    return jsonify(chats_store.list_chats(settings.chats_db_path, current_user.username))


@blueprint.route("/api/chats/<chat_id>")
@require_permission("chat.access")
def get_chat_api(chat_id):
    chat = chats_store.get_chat(settings.chats_db_path, current_user.username, chat_id)
    if chat is None:
        return jsonify({"error": "Chat not found."}), 404
    return jsonify(chat)


@blueprint.route("/api/chats/<chat_id>", methods=["PATCH"])
@require_permission("chat.access")
def rename_chat_api(chat_id):
    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()
    if not title:
        return jsonify({"error": "Title must not be blank."}), 400
    try:
        chats_store.rename_chat(settings.chats_db_path, current_user.username, chat_id, title)
    except chats_store.UnknownChat:
        return jsonify({"error": "Chat not found."}), 404
    return "", 204


@blueprint.route("/api/chats/<chat_id>", methods=["DELETE"])
@require_permission("chat.access")
def delete_chat_api(chat_id):
    try:
        chats_store.delete_chat(settings.chats_db_path, current_user.username, chat_id)
    except chats_store.UnknownChat:
        return jsonify({"error": "Chat not found."}), 404
    return "", 204


@blueprint.route("/api/chat", methods=["POST"])
@require_permission("chat.access")
def chat_api():
    data = request.get_json(silent=True) or {}
    question = (data.get("question") or "").strip()
    if not question:
        return jsonify({"response": "Please enter a question."})

    tools_used: list[str] = []
    tool_calls: list[ToolCallRecord] = []
    recursive_rounds: list[RecursiveRoundRecord] = []
    provider_id = ""
    model_used = ""
    total_tokens = None
    llm_history = [{"role": m.get("role"), "content": m.get("content")} for m in data.get("history", [])]

    chat_id = data.get("chat_id")
    if chat_id is not None:
        if chats_store.get_chat(settings.chats_db_path, current_user.username, chat_id) is None:
            chat_id = None
    if chat_id is None:
        try:
            chat_id = chats_store.save_chat(settings.chats_db_path, current_user.username, None, [])
        except Exception as error:  # noqa: BLE001 - persistence must not block the chat answer itself
            log_service.log_error(
                db.session, current_user, source="chat.start",
                message=f"{type(error).__name__}: {error}"[:_MESSAGE_MAX], details=traceback.format_exc(),
            )
            chat_id = None

    start = time.monotonic()
    try:
        result = router.run_chat(
            question,
            llm_history,
            data.get("provider"),
            data.get("model"),
            data.get("enabled_extensions", []),
            chat_id=chat_id,
        )
        response_text = result.response
        tools_used = result.tools_used
        tool_calls = result.tool_calls
        recursive_rounds = result.recursive_rounds
        provider_id = result.provider_id
        model_used = result.model
        total_tokens = result.total_tokens
    except ValueError as error:
        # Deliberately verbatim: the router raises these with wording meant
        # for whoever is chatting ("Claude is rate-limited right now - try
        # again in 42s, or pick another provider"). No internals, safe to
        # show as-is.
        response_text = f"\u274c {error}"
    except Exception as error:  # noqa: BLE001 - unplanned; text is untrusted for display
        log_service.log_error(
            db.session, current_user, source="chat.answer",
            message=f"{type(error).__name__}: {error}"[:_MESSAGE_MAX], details=traceback.format_exc(),
        )
        response_text = "\u274c Something went wrong while answering your question. Check the Logs page (Errors tab) for details."
    elapsed_seconds = round(time.monotonic() - start, 1)

    history_in = list(data.get("history", []))
    current_turn = [{"role": "user", "content": question}]
    if history_in and history_in[-1] == current_turn[0]:
        current_turn = []
    assistant_entry: dict = {"role": "assistant", "content": response_text, "elapsed_seconds": elapsed_seconds}
    if provider_id:
        assistant_entry["provider_id"] = provider_id
    if model_used:
        assistant_entry["model"] = model_used
    if total_tokens is not None:
        assistant_entry["total_tokens"] = total_tokens
    if recursive_rounds:
        assistant_entry["recursive_rounds"] = len(recursive_rounds)
    transcript = history_in + current_turn + [assistant_entry]
    try:
        chat_id = chats_store.save_chat(settings.chats_db_path, current_user.username, chat_id, transcript)
    except chats_store.UnknownChat:
        try:
            chat_id = chats_store.save_chat(settings.chats_db_path, current_user.username, None, transcript)
        except Exception as error:  # noqa: BLE001 - persistence must not break the chat answer itself
            log_service.log_error(
                db.session, current_user, source="chat.save",
                message=f"{type(error).__name__}: {error}"[:_MESSAGE_MAX], details=traceback.format_exc(),
            )
            chat_id = None
    except Exception as error:  # noqa: BLE001 - persistence must not break the chat answer itself
        log_service.log_error(
            db.session, current_user, source="chat.save",
            message=f"{type(error).__name__}: {error}"[:_MESSAGE_MAX], details=traceback.format_exc(),
        )
        chat_id = None

    if chat_id is not None:
        try:
            trace_message = f"{question[:80]} \u2192 {provider_id or 'error'}/{model_used or '-'}, {elapsed_seconds}s"
            trace_details = json.dumps(
                {
                    "tool_calls": [
                        {"name": c.name, "arguments": c.arguments, "result": c.result} for c in tool_calls
                    ],
                    "recursive_rounds": [
                        {"round": r.round, "response": r.response, "converged": r.converged}
                        for r in recursive_rounds
                    ],
                    "response": response_text,
                    "total_tokens": total_tokens,
                }
            )
            log_service.log_chat_trace(
                db.session, current_user, source="chat.turn",
                message=trace_message[:_TRACE_MESSAGE_MAX], details=trace_details,
            )
        except Exception as error:  # noqa: BLE001 - a trace write must not break the chat answer itself
            log_service.log_error(
                db.session, current_user, source="chat.trace",
                message=f"{type(error).__name__}: {error}"[:_MESSAGE_MAX], details=traceback.format_exc(),
            )

    return jsonify(
        {
            "response": response_text,
            "tools_used": tools_used,
            "provider_id": provider_id,
            "model": model_used,
            "total_tokens": total_tokens,
            "elapsed_seconds": elapsed_seconds,
            "recursive_rounds": len(recursive_rounds),
            "chat_id": chat_id,
        }
    )
```

- [ ] **Step 4: Copy `styles.css` and adjust the layout rules**

Copy `MCPArchitecture/chat_app/src/chat_app/pages/chat/template/styles.css` to `src/pages/Chat/styles.css`. Change the `body` rule from:

```css
body {
  font-family: -apple-system, "Segoe UI", sans-serif;
  margin: 0;
  margin-left: 190px;
  padding: 0;
  background: var(--paper);
  color: var(--ink);
}
```

to:

```css
body {
  font-family: -apple-system, "Segoe UI", sans-serif;
  background: var(--paper);
  color: var(--ink);
}
```

Delete this block entirely (MCPServer's sidebar is a flex sibling, not fixed-position, so there is nothing to reset at this breakpoint):

```css
@media (max-width: 700px) {
  body { margin-left: 0; }
}
```

Then append this new block at the end of the file — the chat-history panel's layout and the "+ New chat" button, which lived in MCPArchitecture's own (unported) `_shared/template/sidebar.css`:

```css
/* Chat-history panel - new for this port. MCPArchitecture rendered
   #chat-history-list inside its own _shared sidebar (sidebar.css,
   not ported here - this project's own __shared__/sidebar.html
   replaces it and has no chat-history concept). script.js still
   targets these exact class/id names unchanged, so this panel
   supplies them as a column inside Chat's own page content instead. */
.chat-layout {
  display: flex;
  gap: 20px;
  align-items: flex-start;
}
.chat-history-panel {
  width: 220px;
  flex-shrink: 0;
  padding-top: 40px;
}
.sidebar-new-chat-btn {
  display: block;
  text-align: center;
  padding: 8px 12px;
  margin-bottom: 10px;
  border: 1px solid var(--panel-border);
  border-radius: 6px;
  background: white;
  color: var(--ink);
  text-decoration: none;
  font-size: 13px;
}
.sidebar-new-chat-btn:hover { background: #f5f5f4; }
.chat-history-list { display: flex; flex-direction: column; gap: 4px; }
.chat-history-empty { font-size: 12px; color: var(--ink-muted); font-style: italic; padding: 4px 8px; }
.chat-history-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  padding: 6px 8px;
  border-radius: 6px;
}
.chat-history-item:hover { background: #f5f5f4; }
.chat-history-item.active { background: var(--code-bg); }
.chat-history-text { display: flex; flex-direction: column; min-width: 0; }
.chat-history-link {
  font-size: 13px;
  color: var(--ink);
  text-decoration: none;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.chat-history-time { font-size: 11px; color: var(--ink-muted); }
.chat-history-controls { display: flex; gap: 2px; flex-shrink: 0; }
.chat-history-rename-btn, .chat-history-delete-btn {
  background: none;
  border: none;
  padding: 2px 4px;
  font-size: 13px;
  color: var(--ink-muted);
  cursor: pointer;
}
.chat-history-rename-btn:hover, .chat-history-delete-btn:hover { color: var(--ink); }
.chat-history-rename-input {
  font-size: 13px;
  padding: 2px 6px;
  border: 1px solid var(--rail-user);
  border-radius: 4px;
  width: 100%;
}
@media (max-width: 700px) {
  .chat-layout { flex-direction: column; }
  .chat-history-panel { width: 100%; padding-top: 0; }
}
```

Nothing else in this file changes.

- [ ] **Step 5: Copy `script.js` and fix the nine `/api/...` URLs**

Copy `MCPArchitecture/chat_app/src/chat_app/pages/chat/template/script.js` to `src/pages/Chat/script.js`. This project's `register_pages()` puts every Chat route under `/chat/...` (see Global Constraints), so change these nine `fetch()` call targets from `/api/...` to `/chat/api/...` — every other `/chat`-prefixed string in this file (`window.history.pushState`/`replaceState`, `location.href`, the `<a href>` builder in `buildChatHistoryItem`) is a **page** URL, already correct, and must NOT be touched:

1. `loadExtensions()`: `fetch('/api/extensions')` → `fetch('/chat/api/extensions')`
2. `submitAddExtension()`: `fetch('/api/extensions', {` → `fetch('/chat/api/extensions', {`
3. `removeExtension()`: `` fetch(`/api/extensions/${encodeURIComponent(ext.id)}`, { method: 'DELETE' }) `` → `` fetch(`/chat/api/extensions/${encodeURIComponent(ext.id)}`, { method: 'DELETE' }) ``
4. `loadProviders()`: `fetch('/api/providers')` → `fetch('/chat/api/providers')`
5. `send()`: `fetch('/api/chat', {` → `fetch('/chat/api/chat', {`
6. `loadChat()`: `` fetch(`/api/chats/${encodeURIComponent(chatId)}`) `` → `` fetch(`/chat/api/chats/${encodeURIComponent(chatId)}`) ``
7. `loadChatHistory()`: `fetch('/api/chats')` → `fetch('/chat/api/chats')`
8. `startRenameChat()`'s `commit()`: `` fetch(`/api/chats/${encodeURIComponent(chat.id)}`, {\n          method: 'PATCH', `` → `` fetch(`/chat/api/chats/${encodeURIComponent(chat.id)}`, {\n          method: 'PATCH', ``
9. `deleteChatEntry()`: `` fetch(`/api/chats/${encodeURIComponent(chat.id)}`, { method: 'DELETE' }); `` → `` fetch(`/chat/api/chats/${encodeURIComponent(chat.id)}`, { method: 'DELETE' }); ``

After editing, run `grep -n "fetch('/api\|fetch(\`/api" src/pages/Chat/script.js` and confirm it returns nothing (every remaining `/api/` reference should now read `/chat/api/`).

- [ ] **Step 6: Copy `modal.css` and `modal.js` verbatim**

Copy `MCPArchitecture/chat_app/src/chat_app/pages/_shared/template/modal.css` to `src/pages/Chat/modal.css` — no changes.

Copy `MCPArchitecture/chat_app/src/chat_app/pages/_shared/template/modal.js` to `src/pages/Chat/modal.js` — no changes (zero `chat_app.*` references, pure client-side).

- [ ] **Step 7: Write `chat.html`**

Create `src/pages/Chat/chat.html` — restructured from MCPArchitecture's standalone `chat/template/index.html` into this project's `extends`/block convention, moving the extensions-panel markup and message log into a new `.chat-layout` wrapper alongside the new chat-history panel (see Step 4):

```html
{% extends "base.html" %}
{% block title %}Chat{% endblock %}
{% block sidebar %}{% include "sidebar.html" %}{% endblock %}
{% block content %}
<link rel="stylesheet" href="{{ url_for('chat.static', filename='modal.css') }}">
<link rel="stylesheet" href="{{ url_for('chat.static', filename='styles.css') }}">
<div class="chat-layout">
  <aside class="chat-history-panel">
    <a href="/chat" class="sidebar-new-chat-btn">+ New chat</a>
    <div id="chat-history-list" class="chat-history-list"><p class="chat-history-empty">Loading...</p></div>
  </aside>
  <div class="page-content">
    <div class="toprow">
      <div class="selectors">
        <button id="ext-toggle-btn" type="button" class="ext-toggle-btn" aria-expanded="false" aria-controls="ext-panel">Extensions</button>
        <select id="model" class="hidden"><option>&mdash;</option></select>
        <select id="provider"><option>Loading providers...</option></select>
      </div>
    </div>
    <div id="log"></div>
    <div id="row">
      <input id="q" type="text" placeholder="Ask a question...">
      <button id="send-btn" onclick="send()">Send</button>
    </div>

    <div id="ext-overlay" class="ext-overlay hidden"></div>
    <aside id="ext-panel" class="ext-panel" aria-hidden="true">
      <div class="ext-panel-header">
        <h2>Extensions</h2>
        <button id="ext-close-btn" type="button" class="ext-close-btn" aria-label="Close extensions panel">&times;</button>
      </div>
      <p class="ext-sub">
        Tools proxied in from other MCP servers. Off by default - switch on
        the ones you want offered to the model for this chat.
      </p>
      <div id="ext-error-banner" class="ext-error-banner hidden"></div>
      <form id="ext-add-form" class="ext-add-form">
        <input id="ext-add-label" type="text" placeholder="Name" required>
        <input id="ext-add-url" type="text" placeholder="URL" required>
        <button id="ext-add-btn" type="submit">Add</button>
        <div id="ext-add-error" class="ext-add-error hidden">
          <p id="ext-add-error-text" class="ext-add-error-text"></p>
          <p id="ext-add-error-details" class="ext-add-error-details hidden"></p>
          <button id="ext-add-error-help-toggle" type="button" class="ext-add-error-help-toggle hidden" aria-expanded="false">Why might this happen?</button>
          <ul id="ext-add-error-help-list" class="ext-add-error-help-list hidden">
            <li>The server might be down or hasn't started yet.</li>
            <li>The URL might be wrong - check the host, port, and path.</li>
            <li>A firewall or network could be blocking the connection.</li>
            <li>The URL might not point to a running MCP server.</li>
          </ul>
        </div>
      </form>
      <div id="ext-list" class="ext-list"><p class="ext-empty">Loading...</p></div>
    </aside>
  </div>
</div>

<script src="https://cdnjs.cloudflare.com/ajax/libs/marked/16.3.0/lib/marked.umd.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/dompurify/3.4.13/purify.min.js"></script>
<script src="{{ url_for('chat.static', filename='modal.js') }}"></script>
<script src="{{ url_for('chat.static', filename='script.js') }}"></script>
{% endblock %}
```

- [ ] **Step 8: Write `README.md`**

Create `src/pages/Chat/README.md`:

```markdown
# Chat

LLM conversation UI: provider/model selection, an extensions (proxied
MCP server) toggle panel, per-user chat history (list/resume/rename/
delete), and the `/api/chat` turn endpoint. Ported from MCPArchitecture
- see `docs/superpowers/specs/2026-08-22-chat-capabilities-port-design.md`.

Gated by the `chat.access` permission (route-level, via
`@require_permission("chat.access")` on every route in this blueprint,
not just the page itself). `CSRF_EXEMPT = True`: this page's JSON
`fetch()` calls carry no CSRF token, relying instead on the project-wide
`Sec-Fetch-Site`/Origin check in `src/services/security/cross_site.py`.

Chat history is a dedicated SQLite file (`data/chats.db` by default,
`src/services/chats_store.py`), separate from `app.db` - see the spec's
"Persistence" section for why. Each turn is also logged as a
`kind="chat_trace"` `LogEntry` (`src/services/log_service.log_chat_trace`),
visible on the Logs page to any account holding `logs.chat.view`.
```

- [ ] **Step 9: Run tests to verify they pass**

Run: `pytest tests/test_chat_page.py -v`
Expected: PASS

- [ ] **Step 10: Manually smoke-test the page**

Start the app (`run.bat` or the project's normal dev-run command), log in as an account with `chat.access` granted (via the Admin page), and open `/chat/`. Confirm: the page renders with the sidebar, the "+ New chat" panel and extensions toggle are visible, sending a message (with at least one LLM provider's API key configured in `src/secrets/secret_llm.env`) produces a reply, and the chat appears in the history panel. Report back what you see rather than assuming it works from the tests alone.

- [ ] **Step 11: Commit**

```bash
git add src/pages/Chat/
git add tests/test_chat_page.py
git commit -m "feat: add Chat page"
```

---

### Task 14: Capabilities page

**Files:**
- Create: `src/pages/Capabilities/__index__.py`
- Create: `src/pages/Capabilities/capabilities.html`
- Create: `src/pages/Capabilities/styles.css`
- Create: `src/pages/Capabilities/script.js`
- Create: `src/pages/Capabilities/README.md`
- Modify: `src/pages/README.md`
- Test: `tests/test_capabilities_page.py`

**Interfaces:**
- Consumes: `src.services.mcp_client.{call_tool, fetch_extensions, list_resource_templates, list_tools, read_resource}` (Task 3), `src.services.tool_capabilities.{capability_for_resource, capability_for_tool}` (Task 4), `src.services.tool_titles.title_for` (Task 4), `src.services.authz.{has_permission, register_permission, require_login, require_permission}` (existing).
- Produces: blueprint `capabilities`, routes `/capabilities/`, `/capabilities/api/tools`, `/capabilities/api/resources`, `/capabilities/api/try/<tool_name>` (POST), `/capabilities/api/read-resource` (POST). Permissions `capabilities.view`, `capabilities.try`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_capabilities_page.py`, same app-building helpers as `tests/test_chat_page.py` (Task 13, Step 1) — copy `_build_chat_test_app`/`_create_account`/`_login_as` and rename the first to `_build_capabilities_test_app` (identical body):

```python
from unittest.mock import patch

from types import SimpleNamespace

from flask import Flask
from werkzeug.security import generate_password_hash

from src.models import Account, Permission, Role, db
from src.pages.__index__ import register_pages
from src.services.auth_service import init_login_manager
from src.services.email_service import init_mail

from pathlib import Path

_SHARED_TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "src" / "pages" / "__shared__"


def _build_capabilities_test_app(tmp_path):
    app = Flask(
        __name__,
        template_folder=str(_SHARED_TEMPLATES_DIR),
        static_folder=str(_SHARED_TEMPLATES_DIR),
        static_url_path="/shared/static",
    )
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{tmp_path / 'capabilities_test.db'}"
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["SECRET_KEY"] = "test-secret"
    app.config["MAIL_SUPPRESS_SEND"] = True

    db.init_app(app)
    with app.app_context():
        db.create_all()

    init_login_manager(app)
    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir()
    init_mail(app, secrets_dir)
    register_pages(app)

    return app


def _create_account(app, username, permission_names):
    with app.app_context():
        account = Account(
            username=username,
            email=f"{username}@example.com",
            password_hash=generate_password_hash("pw"),
        )
        if permission_names:
            role = Role(name=f"{username}_role")
            db.session.add(role)
            for name in permission_names:
                permission = db.session.query(Permission).filter_by(name=name).first()
                if permission is None:
                    permission = Permission(name=name)
                    db.session.add(permission)
                role.permissions.append(permission)
            account.roles.append(role)
        db.session.add(account)
        db.session.commit()
        return account.id


def _login_as(client, account_id):
    with client.session_transaction() as flask_session:
        flask_session["_user_id"] = str(account_id)
        flask_session["_fresh"] = True


def test_capabilities_page_requires_authentication(tmp_path):
    app = _build_capabilities_test_app(tmp_path)
    client = app.test_client()

    response = client.get("/capabilities/")

    assert response.status_code == 401


def test_capabilities_page_forbidden_without_either_permission(tmp_path):
    app = _build_capabilities_test_app(tmp_path)
    account_id = _create_account(app, "nocapaccess", [])
    client = app.test_client()
    _login_as(client, account_id)

    response = client.get("/capabilities/")

    assert response.status_code == 403


def test_capabilities_page_renders_with_view_permission(tmp_path):
    app = _build_capabilities_test_app(tmp_path)
    account_id = _create_account(app, "capviewer", ["capabilities.view"])
    client = app.test_client()
    _login_as(client, account_id)

    with patch("src.pages.Capabilities.__index__.list_tools", return_value=[]), \
         patch("src.pages.Capabilities.__index__.list_resource_templates", return_value=[]), \
         patch("src.pages.Capabilities.__index__.fetch_extensions", return_value=[]):
        response = client.get("/capabilities/")

    assert response.status_code == 200


def test_try_tool_forbidden_with_only_view_permission(tmp_path):
    app = _build_capabilities_test_app(tmp_path)
    account_id = _create_account(app, "capviewonly", ["capabilities.view"])
    client = app.test_client()
    _login_as(client, account_id)

    response = client.post("/capabilities/api/try/some_tool", json={})

    assert response.status_code == 403


def test_try_tool_allowed_with_try_permission(tmp_path):
    app = _build_capabilities_test_app(tmp_path)
    account_id = _create_account(app, "captryer", ["capabilities.try"])
    client = app.test_client()
    _login_as(client, account_id)

    with patch("src.pages.Capabilities.__index__.call_tool", return_value="ok result"):
        response = client.post("/capabilities/api/try/some_tool", json={})

    assert response.status_code == 200
    assert response.get_json() == {"status": "ok", "result": "ok result"}


def test_api_tools_forbidden_with_only_try_permission(tmp_path):
    app = _build_capabilities_test_app(tmp_path)
    account_id = _create_account(app, "captryonly", ["capabilities.try"])
    client = app.test_client()
    _login_as(client, account_id)

    response = client.get("/capabilities/api/tools")

    assert response.status_code == 403
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_capabilities_page.py -v`
Expected: FAIL — no `Capabilities` page exists yet, every request 404s.

- [ ] **Step 3: Write `src/pages/Capabilities/__index__.py`**

Copy the following as the full file content — this is MCPArchitecture's `pages/capabilities/routes.py` with its helper functions (`_fetch_extensions_or_empty`, `_serialize_tools`, `_group_tools_by_extension`, `_group_tools_by_capability`, `_group_resources_by_capability`, `_extract_uri_params`, `_serialize_resources`) kept verbatim (they have zero `chat_app.*`-specific dependencies beyond the already-rewritten imports below), and its routes rewired to this project's blueprint/permission conventions:

```python
"""Live capability browser for the MCP server's tool AND resource catalog.

Nothing here is hardcoded - every request calls list_tools()/
list_resource_templates() on the MCP server, so this page (and the
try-it console on it) always reflects whatever's actually registered
right now. Ported from MCPArchitecture's
chat_app/src/chat_app/pages/capabilities/routes.py - see
docs/superpowers/specs/2026-08-22-chat-capabilities-port-design.md.
"""

from __future__ import annotations

import re

from flask import Blueprint, abort, jsonify, render_template, request
from flask_login import current_user

from src.services.authz import has_permission, register_permission, require_login, require_permission
from src.services.mcp_client import (
    call_tool,
    fetch_extensions,
    list_resource_templates,
    list_tools,
    read_resource,
)
from src.services.tool_capabilities import capability_for_resource, capability_for_tool
from src.services.tool_titles import title_for


blueprint = Blueprint(
    "capabilities", __name__, template_folder=".", static_folder=".", static_url_path="/static"
)

PAGE_PERMISSION = ("capabilities.view", "capabilities.try")
PAGE_DESCRIPTION = "Browse and try MCP server tools and resources live."
PAGE_LAYOUT = "full"
CSRF_EXEMPT = True

register_permission("capabilities.view")
register_permission("capabilities.try")


def _fetch_extensions_or_empty() -> list[dict]:
    try:
        return fetch_extensions()
    except Exception:  # noqa: BLE001 - degrade to built-ins only, don't blank the page
        return []


def _serialize_tools(extensions: list[dict] | None = None) -> list[dict]:
    if extensions is None:
        extensions = _fetch_extensions_or_empty()
    enabled_ids = [extension["id"] for extension in extensions]

    tools = []
    for tool in list_tools(enabled_extensions=enabled_ids):
        ext_id, sep, _ = tool.name.partition("__")
        tools.append(
            {
                "name": tool.name,
                "title": title_for(tool.name),
                "description": tool.description or "",
                "input_schema": tool.inputSchema or {},
                "extension_id": ext_id if sep else None,
            }
        )
    return tools


def _group_tools_by_extension(tools: list[dict], extensions: list[dict]) -> list[dict]:
    tools_by_extension: dict[str, list[dict]] = {}
    for tool in tools:
        ext_id = tool["extension_id"]
        if ext_id is not None:
            tools_by_extension.setdefault(ext_id, []).append(tool)

    return [
        {
            "id": extension["id"],
            "label": extension.get("label") or extension["id"],
            "description": extension.get("description") or "",
            "status": extension.get("status"),
            "error": extension.get("error"),
            "tools": tools_by_extension.get(extension["id"], []),
        }
        for extension in extensions
    ]


def _group_tools_by_capability(tools: list[dict]) -> list[dict]:
    grouped: dict[str, list[dict]] = {}
    for tool in tools:
        if tool["extension_id"] is not None:
            continue
        label = capability_for_tool(tool["name"])
        grouped.setdefault(label, []).append(tool)

    return [{"label": label, "tools": tools_for_label} for label, tools_for_label in grouped.items()]


def _group_resources_by_capability(resources: list[dict]) -> list[dict]:
    grouped: dict[str, list[dict]] = {}
    for resource in resources:
        label = capability_for_resource(resource["name"])
        grouped.setdefault(label, []).append(resource)

    return [{"label": label, "resources": resources_for_label} for label, resources_for_label in grouped.items()]


def _extract_uri_params(uri_template: str) -> list[str]:
    return re.findall(r"\{(\w+)\}", uri_template)


def _serialize_resources() -> list[dict]:
    resources = []
    for template in list_resource_templates():
        uri_template = getattr(template, "uriTemplate", None) or getattr(template, "uri_template", "")
        name = getattr(template, "name", "") or ""
        resources.append(
            {
                "name": name,
                "title": title_for(name) if name else uri_template,
                "description": getattr(template, "description", "") or "",
                "uri_template": uri_template,
                "params": _extract_uri_params(uri_template),
            }
        )
    return resources


@blueprint.route("/")
@require_login()
def browse():
    if not (has_permission(current_user, "capabilities.view") or has_permission(current_user, "capabilities.try")):
        abort(403)

    extensions_catalog = _fetch_extensions_or_empty()

    try:
        tools = _serialize_tools(extensions_catalog)
        tools_error = None
    except Exception as exc:  # noqa: BLE001 - surface any error to the page
        tools = []
        tools_error = str(exc)

    try:
        resources = _serialize_resources()
        resources_error = None
    except Exception as exc:  # noqa: BLE001
        resources = []
        resources_error = str(exc)

    error = tools_error or resources_error
    extensions = _group_tools_by_extension(tools, extensions_catalog)
    tool_capability_groups = _group_tools_by_capability(tools)
    resource_capability_groups = _group_resources_by_capability(resources)
    return render_template(
        "capabilities.html",
        tools=tools,
        extensions=extensions,
        tool_capability_groups=tool_capability_groups,
        resources=resources,
        resource_capability_groups=resource_capability_groups,
        error=error,
    )


@blueprint.route("/api/tools")
@require_permission("capabilities.view")
def api_tools():
    return jsonify(_serialize_tools())


@blueprint.route("/api/resources")
@require_permission("capabilities.view")
def api_resources():
    return jsonify(_serialize_resources())


@blueprint.route("/api/try/<tool_name>", methods=["POST"])
@require_permission("capabilities.try")
def try_tool(tool_name: str):
    arguments = request.get_json(silent=True) or {}
    try:
        result = call_tool(tool_name, arguments)
        return jsonify({"status": "ok", "result": result})
    except Exception as exc:  # noqa: BLE001
        return jsonify({"status": "error", "message": str(exc)}), 500


@blueprint.route("/api/read-resource", methods=["POST"])
@require_permission("capabilities.try")
def read_resource_route():
    data = request.get_json(silent=True) or {}
    uri = (data.get("uri") or "").strip()
    if not uri:
        return jsonify({"status": "error", "message": "Missing uri"}), 400
    try:
        result = read_resource(uri)
        return jsonify({"status": "ok", "result": result})
    except Exception as exc:  # noqa: BLE001
        return jsonify({"status": "error", "message": str(exc)}), 500
```

- [ ] **Step 4: Copy `styles.css` and remove the same two layout rules**

Copy `MCPArchitecture/chat_app/src/chat_app/pages/capabilities/template/styles.css` to `src/pages/Capabilities/styles.css`. Change line 7 from:

```css
body { font-family: -apple-system, sans-serif; margin: 0; padding: 0; color: #1a1a1a; margin-left: 190px; }
```

to:

```css
body { font-family: -apple-system, sans-serif; color: #1a1a1a; }
```

Delete this block (lines 131-133):

```css
@media (max-width: 700px) {
  body { margin-left: 0; }
}
```

Nothing else in this file changes.

- [ ] **Step 5: Copy `script.js` verbatim**

Copy `MCPArchitecture/chat_app/src/chat_app/pages/capabilities/template/script.js` to `src/pages/Capabilities/script.js` — **no changes**. Its `fetch()` calls already target `/capabilities/api/try/${toolName}` and `/capabilities/api/read-resource`, which already match this project's auto-derived `/capabilities` url-prefix.

- [ ] **Step 6: Write `capabilities.html`**

Create `src/pages/Capabilities/capabilities.html` — restructured into the `extends`/block convention; the body content (everything from `<h1>MCP server capabilities</h1>` through the closing of the Resources section, including both Jinja macros) is copied verbatim from MCPArchitecture's `capabilities/template/index.html`:

```html
{% extends "base.html" %}
{% block title %}Capabilities{% endblock %}
{% block sidebar %}{% include "sidebar.html" %}{% endblock %}
{% block content %}
<link rel="stylesheet" href="{{ url_for('capabilities.static', filename='styles.css') }}">
<h1>MCP server capabilities</h1>
<p class="sub">{{ tools|length }} tools, {{ resources|length }} resources &mdash; fetched live from the MCP server just now.</p>

{% if error %}
<div class="error">Could not reach the MCP server: {{ error }}</div>
{% endif %}

<div class="capability-section open" id="tools-section">
  <div class="capability-section-header">
    <span class="capability-section-chevron">&#9656;</span>
    <h2>Tools</h2>
  </div>
  <div class="capability-section-body">
<p class="section-sub">Actions the model decides to invoke, with arguments.</p>

{% macro render_tool_card(tool) %}
<div class="tool" id="tool-{{ tool.name }}">
  <div class="tool-header" onclick="document.getElementById('tool-{{ tool.name }}').classList.toggle('open')">
    <div>
      <span class="badge badge-tool">tool</span>
      <div class="tool-title">{{ tool.title }}</div>
      <div class="tool-name">{{ tool.name }}</div>
      <div class="tool-desc">{{ tool.description or "No description" }}</div>
    </div>
  </div>
  <div class="tool-body">
    <form onsubmit="return runTool(event, '{{ tool.name }}')">
      {% set props = (tool.input_schema or {}).get('properties', {}) %}
      {% if props %}
        {% for field_name, field_schema in props.items() %}
        <label for="{{ tool.name }}-{{ field_name }}">{{ field_name }}{% if field_schema.description %} &mdash; {{ field_schema.description }}{% endif %}</label>
        <input type="text" id="{{ tool.name }}-{{ field_name }}" name="{{ field_name }}"
               placeholder="{{ field_schema.type or 'string' }}">
        {% endfor %}
      {% else %}
        <p class="tool-desc">No input parameters.</p>
      {% endif %}
      <button type="submit">Run</button>
    </form>
    <pre class="result" style="display:none"></pre>
  </div>
</div>
{% endmacro %}

{% for group in tool_capability_groups %}
<div class="capability-group" data-capability-label="{{ group.label }}">
  <div class="capability-group-header">
    <span class="capability-group-chevron">&#9656;</span>
    <span class="capability-group-label">{{ group.label }}</span>
    <span class="capability-group-count">{{ group.tools|length }} tool{{ '' if group.tools|length == 1 else 's' }}</span>
  </div>
  <div class="capability-group-body">
    {% for tool in group.tools %}
      {{ render_tool_card(tool) }}
    {% endfor %}
  </div>
</div>
{% endfor %}
{% if not tools %}
<p class="empty">No tools registered.</p>
{% endif %}

{% for extension in extensions %}
<div class="ext-group" data-extension-id="{{ extension.id }}">
  <div class="ext-group-header">
    <span class="ext-group-chevron">&#9656;</span>
    <span class="ext-status-dot {{ 'connected' if extension.status == 'connected' else 'error' }}"
          {% if extension.error %}title="{{ extension.error }}"{% endif %}></span>
    <span class="ext-group-label">{{ extension.label }}</span>
    <span class="ext-group-count">{{ extension.tools|length }} tool{{ '' if extension.tools|length == 1 else 's' }}</span>
    <label class="ext-switch">
      <input type="checkbox" class="ext-group-toggle">
      <span class="ext-switch-slider"></span>
    </label>
  </div>
  <div class="ext-group-body">
    <div class="ext-group-tools">
      {% for tool in extension.tools %}
        {{ render_tool_card(tool) }}
      {% endfor %}
    </div>
    <p class="ext-group-placeholder" style="display:none"></p>
  </div>
</div>
{% endfor %}
  </div>
</div>

<div class="capability-section open" id="resources-section">
  <div class="capability-section-header">
    <span class="capability-section-chevron">&#9656;</span>
    <h2>Resources</h2>
  </div>
  <div class="capability-section-body">
<p class="section-sub">Read-only, URI-addressed data &mdash; browsed and read directly, no model decision needed.</p>

{% macro render_resource_card(resource, resource_idx) %}
<div class="tool" id="resource-{{ resource_idx }}">
  <div class="tool-header" onclick="document.getElementById('resource-{{ resource_idx }}').classList.toggle('open')">
    <div>
      <span class="badge badge-resource">resource</span>
      <div class="tool-title">{{ resource.title }}</div>
      <div class="tool-name">{{ resource.uri_template }}</div>
      <div class="tool-desc">{{ resource.description or "No description" }}</div>
    </div>
  </div>
  <div class="tool-body">
    <form onsubmit="return readResourceForm(event, {{ resource.uri_template|tojson }}, {{ resource.params|tojson }})">
      {% if resource.params %}
        {% for param in resource.params %}
        <label for="resource-{{ resource_idx }}-{{ param }}">{{ param }}</label>
        <input type="text" id="resource-{{ resource_idx }}-{{ param }}" name="{{ param }}" placeholder="{{ param }}">
        {% endfor %}
      {% else %}
        <p class="tool-desc">No parameters &mdash; this resource has a fixed URI.</p>
      {% endif %}
      <button type="submit">Read</button>
    </form>
    <pre class="result" style="display:none"></pre>
  </div>
</div>
{% endmacro %}

{% for group in resource_capability_groups %}
{% set group_idx = loop.index %}
<div class="capability-group" data-capability-label="{{ group.label }}">
  <div class="capability-group-header">
    <span class="capability-group-chevron">&#9656;</span>
    <span class="capability-group-label">{{ group.label }}</span>
    <span class="capability-group-count">{{ group.resources|length }} resource{{ '' if group.resources|length == 1 else 's' }}</span>
  </div>
  <div class="capability-group-body">
    {% for resource in group.resources %}
      {{ render_resource_card(resource, group_idx ~ '-' ~ loop.index) }}
    {% endfor %}
  </div>
</div>
{% endfor %}
{% if not resources %}
<p class="empty">No resources registered.</p>
{% endif %}
  </div>
</div>

<script src="{{ url_for('capabilities.static', filename='script.js') }}"></script>
{% endblock %}
```

(The original also loaded `shared/sidebar.js` at the bottom — not needed here: this project's `__shared__/shared.js` is already loaded once by `base.html` for every page, including the sidebar-collapse/account-menu behavior this page relies on.)

- [ ] **Step 7: Write `README.md`**

Create `src/pages/Capabilities/README.md`:

```markdown
# Capabilities

Live browser for the MCP server's tool and resource catalog, grouped by
extension and by capability label, with a "try it" console that invokes
a tool or reads a resource directly (bypassing chat). Ported from
MCPArchitecture - see
`docs/superpowers/specs/2026-08-22-chat-capabilities-port-design.md`.

Two permissions: `capabilities.view` gates the page and its read-only
`/api/tools`/`/api/resources`; `capabilities.try` separately gates
`/api/try/<tool_name>` and `/api/read-resource`, since those actually
invoke real MCP tools with caller-supplied arguments. `PAGE_PERMISSION`
is a tuple of both - visible in `nav_pages` to an account holding
either one, same pattern as the Logs page. `CSRF_EXEMPT = True`: see
Chat's README for why.
```

- [ ] **Step 8: Update `src/pages/README.md`**

Add two new bullets to the `## Pages` list (alphabetically is not the existing order — match the existing list's convention of "most-linked-from-nav first, account-menu-only pages noted as such"; append these after the `Sample` entry):

```markdown
- [`Chat/`](Chat/README.md) — LLM conversation UI, provider/extension
  selection, and per-user chat history. Gated by `chat.access`.
- [`Capabilities/`](Capabilities/README.md) — live MCP tool/resource
  browser and try-it console. Gated by `capabilities.view` /
  `capabilities.try`.
```

- [ ] **Step 9: Run tests to verify they pass**

Run: `pytest tests/test_capabilities_page.py -v`
Expected: PASS

- [ ] **Step 10: Manually smoke-test the page**

With the app running and `mcp_server` reachable at the configured `MCP_SERVER_URL`, log in as an account with `capabilities.view` and/or `capabilities.try` granted, open `/capabilities/`, confirm the tool/resource accordions render, and (with `capabilities.try`) run a tool via its "Run" button. Report back what you see.

- [ ] **Step 11: Commit**

```bash
git add src/pages/Capabilities/ src/pages/README.md
git add tests/test_capabilities_page.py
git commit -m "feat: add Capabilities page"
```

---

### Task 15: Logs page — third `chat_trace` tab

**Files:**
- Modify: `src/pages/Logs/__index__.py`
- Modify: `src/pages/Logs/logs.html`
- Test: `tests/test_logs_page.py`

**Interfaces:**
- Consumes: `src.services.log_service.list_entries` (existing, `kind="chat_trace"` now populated by Task 13), `LogEntry` (existing).
- Produces: nothing new consumed elsewhere — this is the terminal read path for `chat_trace` entries.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_logs_page.py`:

```python
def test_logs_page_forbidden_without_any_of_three_permissions(tmp_path):
    app = _build_logs_test_app(tmp_path)
    account_id = _create_account(app, "nopermsuser2", [])
    client = app.test_client()
    _login_as(client, account_id)

    response = client.get("/logs/")

    assert response.status_code == 403


def test_logs_page_shows_only_chat_traces_tab_with_that_permission(tmp_path):
    app = _build_logs_test_app(tmp_path)
    account_id = _create_account(app, "chattraceonly", ["logs.chat.view"])
    client = app.test_client()
    _login_as(client, account_id)

    response = client.get("/logs/")

    assert response.status_code == 200
    assert b'data-tab="chat_traces"' in response.data
    assert b'data-tab="logs"' not in response.data
    assert b'data-tab="errors"' not in response.data


def test_chat_traces_tab_shows_entries_for_selected_account(tmp_path):
    app = _build_logs_test_app(tmp_path)
    account_id = _create_account(app, "chattraceuser", ["logs.chat.view"])

    with app.app_context():
        db.session.add(
            LogEntry(kind="chat_trace", account_id=account_id, source="chat.turn", message="hi there turn", details="{}")
        )
        db.session.commit()

    client = app.test_client()
    _login_as(client, account_id)

    response = client.get(f"/logs/?tab=chat_traces&chat_traces_actor={account_id}")

    assert response.status_code == 200
    assert b"hi there turn" in response.data
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_logs_page.py -v`
Expected: FAIL — `chat_traces` tab doesn't exist yet (`data-tab="chat_traces"` never appears; `logs.chat.view`-only account currently gets a 403 with no matching tab).

- [ ] **Step 3: Modify `src/pages/Logs/__index__.py`**

Add a third permission registration and a third `PAGE_PERMISSION` entry — change:

```python
PAGE_PERMISSION = ("logs.view", "logs.errors.view")
PAGE_DESCRIPTION = "View server and per-account activity and error logs."

register_permission("logs.view")
register_permission("logs.errors.view")
```

to:

```python
PAGE_PERMISSION = ("logs.view", "logs.errors.view", "logs.chat.view")
PAGE_DESCRIPTION = "View server and per-account activity, error, and chat-turn logs."

register_permission("logs.view")
register_permission("logs.errors.view")
register_permission("logs.chat.view")
```

In `index()`, extend the existing pattern for the third permission/tab — change:

```python
@blueprint.route("/")
@require_login()
def index():
    can_view_logs = has_permission(current_user, "logs.view")
    can_view_errors = has_permission(current_user, "logs.errors.view")
    if not (can_view_logs or can_view_errors):
        abort(403)

    accounts = db.session.query(Account).order_by(Account.username).all()
    allowed_tabs = [t for t, ok in (("logs", can_view_logs), ("errors", can_view_errors)) if ok]
    active_tab = request.args.get("tab", allowed_tabs[0])
    if active_tab not in allowed_tabs:
        active_tab = allowed_tabs[0]
    logs_actor = request.args.get("logs_actor", "server")
    errors_actor = request.args.get("errors_actor", "server")

    log_entries = None
    error_entries = None
    if can_view_logs:
        log_entries = log_service.list_entries(
            db.session, "action", _resolve_actor(logs_actor), limit=_ROW_LIMIT
        )
    if can_view_errors:
        error_entries = log_service.list_entries(
            db.session, "error", _resolve_actor(errors_actor), limit=_ROW_LIMIT
        )

    return render_template(
        "logs.html",
        can_view_logs=can_view_logs,
        can_view_errors=can_view_errors,
        active_tab=active_tab,
        accounts=accounts,
        logs_actor=logs_actor,
        errors_actor=errors_actor,
        log_entries=log_entries,
        error_entries=error_entries,
    )
```

to:

```python
@blueprint.route("/")
@require_login()
def index():
    can_view_logs = has_permission(current_user, "logs.view")
    can_view_errors = has_permission(current_user, "logs.errors.view")
    can_view_chat_traces = has_permission(current_user, "logs.chat.view")
    if not (can_view_logs or can_view_errors or can_view_chat_traces):
        abort(403)

    accounts = db.session.query(Account).order_by(Account.username).all()
    allowed_tabs = [
        t for t, ok in (
            ("logs", can_view_logs),
            ("errors", can_view_errors),
            ("chat_traces", can_view_chat_traces),
        ) if ok
    ]
    active_tab = request.args.get("tab", allowed_tabs[0])
    if active_tab not in allowed_tabs:
        active_tab = allowed_tabs[0]
    logs_actor = request.args.get("logs_actor", "server")
    errors_actor = request.args.get("errors_actor", "server")
    # "Server" (account_id=None) always yields zero rows for this tab - a
    # chat turn always belongs to a specific account - but the dropdown
    # keeps the same Server-first shape as the other two tabs for UI
    # consistency (see docs/superpowers/specs/2026-08-22-chat-
    # capabilities-port-design.md's "Defaults Flagged for Review").
    chat_traces_actor = request.args.get("chat_traces_actor", "server")

    log_entries = None
    error_entries = None
    chat_trace_entries = None
    if can_view_logs:
        log_entries = log_service.list_entries(
            db.session, "action", _resolve_actor(logs_actor), limit=_ROW_LIMIT
        )
    if can_view_errors:
        error_entries = log_service.list_entries(
            db.session, "error", _resolve_actor(errors_actor), limit=_ROW_LIMIT
        )
    if can_view_chat_traces:
        chat_trace_entries = log_service.list_entries(
            db.session, "chat_trace", _resolve_actor(chat_traces_actor), limit=_ROW_LIMIT
        )

    return render_template(
        "logs.html",
        can_view_logs=can_view_logs,
        can_view_errors=can_view_errors,
        can_view_chat_traces=can_view_chat_traces,
        active_tab=active_tab,
        accounts=accounts,
        logs_actor=logs_actor,
        errors_actor=errors_actor,
        chat_traces_actor=chat_traces_actor,
        log_entries=log_entries,
        error_entries=error_entries,
        chat_trace_entries=chat_trace_entries,
    )
```

- [ ] **Step 4: Replace `src/pages/Logs/logs.html`**

The current file (`{% block content %}` through `{% endblock %}`) is:

```html
<link rel="stylesheet" href="{{ url_for('logs.static', filename='style.css') }}">
<h1>Logs</h1>

<div data-tabs>
  <div class="tabs" role="tablist">
    {% if can_view_logs %}
    <button type="button" class="tab-btn{% if active_tab == 'logs' %} active{% endif %}" data-tab="logs">Logs</button>
    {% endif %}
    {% if can_view_errors %}
    <button type="button" class="tab-btn{% if active_tab == 'errors' %} active{% endif %}" data-tab="errors">Errors</button>
    {% endif %}
  </div>

  {% if can_view_logs %}
  <section class="tab-panel" data-tab-panel="logs"{% if active_tab != 'logs' %} hidden{% endif %}>
    <form method="get">
      <input type="hidden" name="tab" value="logs">
      {% if can_view_errors %}<input type="hidden" name="errors_actor" value="{{ errors_actor }}">{% endif %}
      <label for="logs_actor">Show entries for</label>
      <select id="logs_actor" name="logs_actor" onchange="this.form.submit()">
        <option value="server"{% if logs_actor == "server" %} selected{% endif %}>Server</option>
        {% for account in accounts %}
        <option value="{{ account.id }}"{% if logs_actor == account.id|string %} selected{% endif %}>{{ account.username }}</option>
        {% endfor %}
      </select>
    </form>

    <ul class="log-entries">
      {% for entry in log_entries %}
      <li class="log-entry">
        <span class="log-entry-time">{{ entry.created_at }}</span>
        <span class="log-entry-source">{{ entry.source }}</span>
        <span class="log-entry-message">{{ entry.message }}</span>
      </li>
      {% else %}
      <li class="log-entry-empty">No log entries yet.</li>
      {% endfor %}
    </ul>
  </section>
  {% endif %}

  {% if can_view_errors %}
  <section class="tab-panel" data-tab-panel="errors"{% if active_tab != 'errors' %} hidden{% endif %}>
    <form method="get">
      <input type="hidden" name="tab" value="errors">
      {% if can_view_logs %}<input type="hidden" name="logs_actor" value="{{ logs_actor }}">{% endif %}
      <label for="errors_actor">Show entries for</label>
      <select id="errors_actor" name="errors_actor" onchange="this.form.submit()">
        <option value="server"{% if errors_actor == "server" %} selected{% endif %}>Server</option>
        {% for account in accounts %}
        <option value="{{ account.id }}"{% if errors_actor == account.id|string %} selected{% endif %}>{{ account.username }}</option>
        {% endfor %}
      </select>
    </form>

    <ul class="log-entries">
      {% for entry in error_entries %}
      <li class="log-entry">
        <span class="log-entry-time">{{ entry.created_at }}</span>
        <span class="log-entry-source">{{ entry.source }}</span>
        <span class="log-entry-message">{{ entry.message }}</span>
        {% if entry.details %}
        <details class="log-entry-details">
          <summary>Details</summary>
          <pre>{{ entry.details }}</pre>
        </details>
        {% endif %}
      </li>
      {% else %}
      <li class="log-entry-empty">No error entries yet.</li>
      {% endfor %}
    </ul>
  </section>
  {% endif %}
</div>
{% endblock %}
```

Replace the whole `{% block content %}...{% endblock %}` body with (adds the third tab button, a `chat_traces_actor` hidden input to the two existing forms so switching tabs never loses the third tab's own selection, and a third panel reusing the exact `log-entries`/`log-entry`/`log-entry-details` structure the Errors panel already uses):

```html
{% extends "base.html" %}
{% block title %}Logs{% endblock %}
{% block sidebar %}{% include "sidebar.html" %}{% endblock %}
{% block content %}
<link rel="stylesheet" href="{{ url_for('logs.static', filename='style.css') }}">
<h1>Logs</h1>

<div data-tabs>
  <div class="tabs" role="tablist">
    {% if can_view_logs %}
    <button type="button" class="tab-btn{% if active_tab == 'logs' %} active{% endif %}" data-tab="logs">Logs</button>
    {% endif %}
    {% if can_view_errors %}
    <button type="button" class="tab-btn{% if active_tab == 'errors' %} active{% endif %}" data-tab="errors">Errors</button>
    {% endif %}
    {% if can_view_chat_traces %}
    <button type="button" class="tab-btn{% if active_tab == 'chat_traces' %} active{% endif %}" data-tab="chat_traces">Chat traces</button>
    {% endif %}
  </div>

  {% if can_view_logs %}
  <section class="tab-panel" data-tab-panel="logs"{% if active_tab != 'logs' %} hidden{% endif %}>
    <form method="get">
      <input type="hidden" name="tab" value="logs">
      {% if can_view_errors %}<input type="hidden" name="errors_actor" value="{{ errors_actor }}">{% endif %}
      {% if can_view_chat_traces %}<input type="hidden" name="chat_traces_actor" value="{{ chat_traces_actor }}">{% endif %}
      <label for="logs_actor">Show entries for</label>
      <select id="logs_actor" name="logs_actor" onchange="this.form.submit()">
        <option value="server"{% if logs_actor == "server" %} selected{% endif %}>Server</option>
        {% for account in accounts %}
        <option value="{{ account.id }}"{% if logs_actor == account.id|string %} selected{% endif %}>{{ account.username }}</option>
        {% endfor %}
      </select>
    </form>

    <ul class="log-entries">
      {% for entry in log_entries %}
      <li class="log-entry">
        <span class="log-entry-time">{{ entry.created_at }}</span>
        <span class="log-entry-source">{{ entry.source }}</span>
        <span class="log-entry-message">{{ entry.message }}</span>
      </li>
      {% else %}
      <li class="log-entry-empty">No log entries yet.</li>
      {% endfor %}
    </ul>
  </section>
  {% endif %}

  {% if can_view_errors %}
  <section class="tab-panel" data-tab-panel="errors"{% if active_tab != 'errors' %} hidden{% endif %}>
    <form method="get">
      <input type="hidden" name="tab" value="errors">
      {% if can_view_logs %}<input type="hidden" name="logs_actor" value="{{ logs_actor }}">{% endif %}
      {% if can_view_chat_traces %}<input type="hidden" name="chat_traces_actor" value="{{ chat_traces_actor }}">{% endif %}
      <label for="errors_actor">Show entries for</label>
      <select id="errors_actor" name="errors_actor" onchange="this.form.submit()">
        <option value="server"{% if errors_actor == "server" %} selected{% endif %}>Server</option>
        {% for account in accounts %}
        <option value="{{ account.id }}"{% if errors_actor == account.id|string %} selected{% endif %}>{{ account.username }}</option>
        {% endfor %}
      </select>
    </form>

    <ul class="log-entries">
      {% for entry in error_entries %}
      <li class="log-entry">
        <span class="log-entry-time">{{ entry.created_at }}</span>
        <span class="log-entry-source">{{ entry.source }}</span>
        <span class="log-entry-message">{{ entry.message }}</span>
        {% if entry.details %}
        <details class="log-entry-details">
          <summary>Details</summary>
          <pre>{{ entry.details }}</pre>
        </details>
        {% endif %}
      </li>
      {% else %}
      <li class="log-entry-empty">No error entries yet.</li>
      {% endfor %}
    </ul>
  </section>
  {% endif %}

  {% if can_view_chat_traces %}
  <section class="tab-panel" data-tab-panel="chat_traces"{% if active_tab != 'chat_traces' %} hidden{% endif %}>
    <form method="get">
      <input type="hidden" name="tab" value="chat_traces">
      {% if can_view_logs %}<input type="hidden" name="logs_actor" value="{{ logs_actor }}">{% endif %}
      {% if can_view_errors %}<input type="hidden" name="errors_actor" value="{{ errors_actor }}">{% endif %}
      <label for="chat_traces_actor">Show entries for</label>
      <select id="chat_traces_actor" name="chat_traces_actor" onchange="this.form.submit()">
        <option value="server"{% if chat_traces_actor == "server" %} selected{% endif %}>Server</option>
        {% for account in accounts %}
        <option value="{{ account.id }}"{% if chat_traces_actor == account.id|string %} selected{% endif %}>{{ account.username }}</option>
        {% endfor %}
      </select>
    </form>

    <ul class="log-entries">
      {% for entry in chat_trace_entries %}
      <li class="log-entry">
        <span class="log-entry-time">{{ entry.created_at }}</span>
        <span class="log-entry-source">{{ entry.source }}</span>
        <span class="log-entry-message">{{ entry.message }}</span>
        {% if entry.details %}
        <details class="log-entry-details">
          <summary>Details</summary>
          <pre>{{ entry.details }}</pre>
        </details>
        {% endif %}
      </li>
      {% else %}
      <li class="log-entry-empty">No chat-turn entries yet.</li>
      {% endfor %}
    </ul>
  </section>
  {% endif %}
</div>
{% endblock %}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_logs_page.py -v`
Expected: PASS (whole file — this task must not break any of the pre-existing Logs/Errors tab tests)

- [ ] **Step 6: Commit**

```bash
git add src/pages/Logs/__index__.py src/pages/Logs/logs.html tests/test_logs_page.py
git commit -m "feat: add chat-trace tab to Logs page"
```

---

### Task 16: End-to-end smoke test

**Files:**
- Test: `tests/test_chat_capabilities_integration.py`

**Interfaces:**
- Consumes: everything from Tasks 1-15.
- Produces: nothing — this task is pure verification that the whole feature boots together via the real `create_app()`, not the per-page throwaway apps the earlier tasks' tests build.

- [ ] **Step 1: Write the test**

Create `tests/test_chat_capabilities_integration.py`:

```python
"""Full-stack smoke test: the real create_app() (not a throwaway
per-page Flask app) boots with Chat and Capabilities registered,
correctly permission-gated, and CSRF-exempted."""

from __future__ import annotations

from werkzeug.security import generate_password_hash

from src.models import Account, Permission, Role, db


def test_app_boots_with_chat_and_capabilities_registered(tmp_path):
    # No chdir/tmp_path scaffolding for secrets/configs/data - run.py's
    # BASE_DIR is Path(__file__).resolve().parent, fixed to the real
    # chat_app/src/ regardless of cwd (that's the whole point of BASE_DIR
    # - see _resolve_sqlite_uri's docstring), so create_app() is already
    # directly testable with just a config override, exactly like
    # tests/test_app_factory.py's existing tests already do.
    from src.run import create_app

    app = create_app(
        {
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'app.db'}",
            "TESTING": True,
            "SECRET_KEY": "test-secret",
            "WTF_CSRF_ENABLED": False,
        }
    )

    page_names = {p["name"] for p in app.config["PAGES"]}
    assert "Chat" in page_names
    assert "Capabilities" in page_names

    with app.app_context():
        account = Account(
            username="fullstackuser", email="fullstackuser@example.com",
            password_hash=generate_password_hash("pw"),
        )
        role = Role(name="fullstack_role")
        db.session.add(role)
        for name in ("chat.access", "capabilities.view"):
            permission = Permission(name=name)
            db.session.add(permission)
            role.permissions.append(permission)
        account.roles.append(role)
        db.session.add(account)
        db.session.commit()
        account_id = account.id

    client = app.test_client()
    with client.session_transaction() as flask_session:
        flask_session["_user_id"] = str(account_id)
        flask_session["_fresh"] = True

    chat_response = client.get("/chat/")
    assert chat_response.status_code == 200

    capabilities_response = client.get("/capabilities/")
    assert capabilities_response.status_code == 200

    admin_response = client.get("/admin/")
    assert admin_response.status_code == 403  # no admin.* permission granted - unrelated page still gated normally
```

(`create_app()` accepts an optional `config: dict | None` override per its existing signature in `src/run.py` — this test relies on that to point `SQLALCHEMY_DATABASE_URI` at a temp file and disable CSRF for the test client, exactly the pattern `tests/test_app_factory.py`'s four existing tests already use with no additional scaffolding. `ensure_bootstrap_admin` reads the real `BASE_DIR / "secrets"` directory and is a no-op if `ADMIN_USERNAME`/`ADMIN_PASSWORD` aren't set there — it does not block `create_app()` from returning; `test_app_factory.py`'s existing passing tests are the proof this call sequence already works standalone.)

- [ ] **Step 2: Run the test**

Run: `pytest tests/test_chat_capabilities_integration.py -v`
Expected: PASS.

- [ ] **Step 3: Run the entire test suite**

Run: `pytest -v`
Expected: PASS — every test from every earlier task, plus every pre-existing test in the repo, all green.

- [ ] **Step 4: Commit**

```bash
git add tests/test_chat_capabilities_integration.py
git commit -m "test: add end-to-end smoke test for Chat and Capabilities"
```
