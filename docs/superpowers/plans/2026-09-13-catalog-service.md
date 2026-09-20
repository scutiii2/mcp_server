# Catalog Service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `catalog_service`, a new standalone service that statically scans chat_app, mcp_server, and ai_agent for `@catalog`-decorated functions/classes, caches the result to disk, serves it cache-first over a small JSON API, and refreshes the cache in the background on every boot.

**Architecture:** A fourth sibling service (own folder, own venv, own `pyproject.toml`, same shape as chat_app/mcp_server/ai_agent). Its `src/scanner.py` uses Python's `ast` module to parse `.py` files under the other three projects' `src/` trees — never imports them — looking for a `@catalog` decorator on `FunctionDef`/`AsyncFunctionDef`/`ClassDef` nodes. Results are held in an in-memory registry (`src/registry.py`) backed by a JSON file cache (`src/cache.py`, atomic write). A small Starlette app (`src/routes.py`) serves the registry over HTTP. `@catalog` itself is a no-op identity decorator, duplicated as an identical stub into each of the three target projects (this repo has no shared package across them — see Global Constraints).

**Tech Stack:** Python 3.11, Starlette + uvicorn (plain ASGI routes, no FastMCP — this service exposes no MCP tools), stdlib `ast`/`json`/`threading`/`tempfile`, pytest + `starlette.testclient.TestClient` (needs `httpx`) for tests, hatchling build backend.

**Spec:** This plan **is** the spec — it was produced by a full grilling session (see conversation history; no separate spec file exists). Every locked decision from that session is restated in Global Constraints and the relevant task below, so this plan is self-contained.

## Global Constraints

- Python `>=3.11`, hatchling build backend, dev deps under `[project.optional-dependencies] dev`, matching every existing project in this repo (`mcp_server/pyproject.toml`, `chat_app/pyproject.toml`).
- The three existing apps (chat_app, mcp_server, ai_agent) have **zero shared code today** and are documented as separate processes with no cross-imports (`docs/System_Overview_Documentation.md:17`) — this plan must not create a new shared package to satisfy that invariant. `@catalog` is duplicated, not imported from one place.
- Scanning is **static AST parsing only** — never import/execute the three target codebases. A file that fails to parse is skipped with a logged warning; it never aborts the rest of the scan.
- Cache is a single JSON file, written atomically (temp file + `os.replace`) so a concurrent `GET` never reads a half-written file.
- Service binds `127.0.0.1:8020` by default (existing ports in this repo: chat_app `:5000`, mcp_server `:8010`, ai_agent `:9100`/`:9101` — `:8020` doesn't collide).
- No authentication on the API — read-only, non-sensitive metadata (matches the repo's own documented reasoning for mcp_server's default bind, `mcp_server/src/config.py:36-42`, applied here to justify *no* token rather than requiring one).
- `GET /catalog` and `GET /catalog/{id}` must never block on a scan in progress — always return immediately from whatever is currently in memory, with a `status` field (`"scanning"` or `"ready"`) alongside the entries.
- Locked entry schema (every task's output must match this exactly):
  ```json
  {
    "id": "chat_app.src.services.foo.bar",
    "type": "function",
    "name": "bar",
    "description": "...",
    "project": "chat_app",
    "file": "src/services/foo.py",
    "line": 42,
    "parameters": [{"name": "x", "annotation": "str", "default": null}],
    "methods": ["method_a", "method_b"]
  }
  ```
  `methods` is present **only** when `"type": "class"`. `parameters` only covers positional-or-keyword parameters (`posonlyargs` + `args`) — `*args`/`**kwargs`/keyword-only parameters are out of scope (the locked schema doesn't need them; adding handling for them now would be unrequested scope).
- A parameter's `"default"` is the exact source text of its default expression via `ast.unparse` (e.g. `"5"`, `"'hi'"`, `"None"` for a literal `None` default) — **not** JSON `null`. JSON `null` means "this parameter has no default at all". These are different and both must be tested.
- **Assumption flagged for review:** this plan adds `run_catalog.bat` at the repo root (mirroring `run_mcp.bat`) but does **not** wire it into `run_all.bat` — same precedent as ai_agent, which `run_all.bat:21-23` explicitly starts separately. Flag if you wanted it auto-started with the other two.

---

### Task 1: Project scaffold + Settings

**Files:**
- Create: `catalog_service/pyproject.toml`
- Create: `catalog_service/src/__init__.py`
- Create: `catalog_service/src/config.py`
- Create: `catalog_service/configs/config_sources.json`
- Create: `catalog_service/.gitignore`
- Test: `catalog_service/tests/__init__.py`
- Test: `catalog_service/tests/test_config.py`

**Interfaces:**
- Produces: `src.config.Settings` (frozen dataclass: `host: str`, `port: int`, `configs_dir: Path`, `cache_path: Path`, property `sources_config_path -> Path`, method `sources() -> list[tuple[str, Path]]`) and module-level `settings = Settings()`. Every later task imports `from src.config import settings`.

- [ ] **Step 1: Create the package skeleton and pyproject.toml**

`catalog_service/pyproject.toml`:
```toml
[project]
name = "catalog_service"
version = "0.1.0"
description = "Cross-project reuse catalog for chat_app, mcp_server, and ai_agent"
requires-python = ">=3.11"
dependencies = [
    "starlette>=0.37,<1.0",
    "uvicorn==0.49.0",
]

[project.optional-dependencies]
dev = ["pytest>=8.0", "httpx>=0.27"]

[project.scripts]
catalog-service = "src.run:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src"]
```

`catalog_service/src/__init__.py`: empty file.

`catalog_service/tests/__init__.py`: empty file.

`catalog_service/.gitignore`:
```
venv_catalog/
data/catalog_cache.json
__pycache__/
*.pyc
```

- [ ] **Step 2: Write the failing tests for Settings**

`catalog_service/tests/test_config.py`:
```python
from __future__ import annotations

import importlib
import json
from pathlib import Path

from src.config import Settings


def test_defaults():
    settings = Settings()
    assert settings.host == "127.0.0.1"
    assert settings.port == 8020
    assert settings.configs_dir == Path("configs")
    assert settings.cache_path == Path("data/catalog_cache.json")


def test_sources_config_path_joins_configs_dir(tmp_path):
    settings = Settings(configs_dir=tmp_path)
    assert settings.sources_config_path == tmp_path / "config_sources.json"


def test_sources_reads_project_path_pairs(tmp_path):
    config_file = tmp_path / "config_sources.json"
    config_file.write_text(
        json.dumps([{"project": "chat_app", "path": "../chat_app/src"}]),
        encoding="utf-8",
    )
    settings = Settings(configs_dir=tmp_path)

    assert settings.sources() == [("chat_app", Path("../chat_app/src"))]


def test_env_override_for_port(monkeypatch):
    monkeypatch.setenv("CATALOG_PORT", "9999")
    from src import config

    importlib.reload(config)
    try:
        assert config.settings.port == 9999
    finally:
        monkeypatch.delenv("CATALOG_PORT", raising=False)
        importlib.reload(config)
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `cd catalog_service && python -m pytest tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.config'` (or `src`).

- [ ] **Step 4: Implement Settings**

`catalog_service/src/config.py`:
```python
"""Server-wide settings.

Deliberately plain (no external settings library) - same convention as
mcp_server/src/config.py.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path


def _env(name: str, default: str) -> str:
    value = os.getenv(name)
    return value if value else default


@dataclass(frozen=True)
class Settings:
    host: str = _env("CATALOG_HOST", "127.0.0.1")
    port: int = int(_env("CATALOG_PORT", "8020"))
    configs_dir: Path = Path(_env("CATALOG_CONFIGS_DIR", "configs"))
    cache_path: Path = Path(_env("CATALOG_CACHE_PATH", "data/catalog_cache.json"))

    @property
    def sources_config_path(self) -> Path:
        return self.configs_dir / "config_sources.json"

    def sources(self) -> list[tuple[str, Path]]:
        """Reads configs/config_sources.json: a JSON array of
        {"project": <name>, "path": <path to that project's src/ dir>}."""
        raw = json.loads(self.sources_config_path.read_text(encoding="utf-8"))
        return [(entry["project"], Path(entry["path"])) for entry in raw]


settings = Settings()
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd catalog_service && python -m pytest tests/test_config.py -v`
Expected: PASS (4 tests).

- [ ] **Step 6: Create the real source-paths config**

`catalog_service/configs/config_sources.json`:
```json
[
  {"project": "chat_app", "path": "../chat_app/src"},
  {"project": "mcp_server", "path": "../mcp_server/src"},
  {"project": "ai_agent", "path": "../ai_agent/src"}
]
```

- [ ] **Step 7: Commit**

```bash
git add catalog_service/pyproject.toml catalog_service/src/__init__.py catalog_service/src/config.py catalog_service/configs/config_sources.json catalog_service/.gitignore catalog_service/tests/__init__.py catalog_service/tests/test_config.py
git commit -m "feat(catalog_service): scaffold project and add Settings"
```

---

### Task 2: Catalog entry models

**Files:**
- Create: `catalog_service/src/models.py`
- Test: `catalog_service/tests/test_models.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `Parameter` (frozen dataclass: `name: str`, `annotation: str | None`, `default: str | None`), `CatalogEntry` (frozen dataclass: `id: str`, `type: str`, `name: str`, `description: str`, `project: str`, `file: str`, `line: int`, `parameters: list[Parameter]`, `methods: list[str] | None = None`), method `CatalogEntry.to_dict() -> dict`. Task 3/4/5 (scanner) construct these; Task 7 (registry) calls `.to_dict()`.

- [ ] **Step 1: Write the failing tests**

`catalog_service/tests/test_models.py`:
```python
from __future__ import annotations

from src.models import CatalogEntry, Parameter


def test_function_entry_to_dict_has_no_methods_key():
    entry = CatalogEntry(
        id="chat_app.src.services.foo.bar",
        type="function",
        name="bar",
        description="Does a thing.",
        project="chat_app",
        file="src/services/foo.py",
        line=42,
        parameters=[Parameter(name="x", annotation="str", default=None)],
    )

    data = entry.to_dict()

    assert data == {
        "id": "chat_app.src.services.foo.bar",
        "type": "function",
        "name": "bar",
        "description": "Does a thing.",
        "project": "chat_app",
        "file": "src/services/foo.py",
        "line": 42,
        "parameters": [{"name": "x", "annotation": "str", "default": None}],
    }
    assert "methods" not in data


def test_class_entry_to_dict_includes_methods_key():
    entry = CatalogEntry(
        id="mcp_server.src.services.foo.Bar",
        type="class",
        name="Bar",
        description="A reusable base.",
        project="mcp_server",
        file="src/services/foo.py",
        line=10,
        parameters=[],
        methods=["method_a", "method_b"],
    )

    data = entry.to_dict()

    assert data["methods"] == ["method_a", "method_b"]
```

- [ ] **Step 2: Run to verify failure**

Run: `cd catalog_service && python -m pytest tests/test_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.models'`.

- [ ] **Step 3: Implement the models**

`catalog_service/src/models.py`:
```python
"""The catalog entry shape returned by the API - see the locked schema in
docs/superpowers/plans/2026-09-13-catalog-service.md's Global Constraints.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Parameter:
    name: str
    # ast.unparse() of the annotation expression, or None if unannotated.
    annotation: str | None
    # ast.unparse() of the default expression, or None if there is no
    # default at all. A literal `None` default (`def f(x=None)`) unparses
    # to the *string* "None" - distinct from this field being absent.
    default: str | None


@dataclass(frozen=True)
class CatalogEntry:
    id: str
    type: str  # "function" or "class"
    name: str
    description: str
    project: str
    file: str
    line: int
    parameters: list[Parameter] = field(default_factory=list)
    methods: list[str] | None = None  # only set for type == "class"

    def to_dict(self) -> dict:
        data: dict = {
            "id": self.id,
            "type": self.type,
            "name": self.name,
            "description": self.description,
            "project": self.project,
            "file": self.file,
            "line": self.line,
            "parameters": [
                {"name": p.name, "annotation": p.annotation, "default": p.default}
                for p in self.parameters
            ],
        }
        if self.methods is not None:
            data["methods"] = self.methods
        return data
```

- [ ] **Step 4: Run to verify pass**

Run: `cd catalog_service && python -m pytest tests/test_models.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add catalog_service/src/models.py catalog_service/tests/test_models.py
git commit -m "feat(catalog_service): add CatalogEntry/Parameter models"
```

---

### Task 3: AST scanner — functions

**Files:**
- Create: `catalog_service/src/scanner.py`
- Test: `catalog_service/tests/test_scanner_functions.py`

**Interfaces:**
- Consumes: `Parameter`, `CatalogEntry` from `src.models`.
- Produces: `_is_catalog_decorator(node: ast.expr) -> bool`, `_decorator_overrides(node: ast.expr) -> dict[str, str]`, `_extract_parameters(args: ast.arguments, *, skip_first: bool = False) -> list[Parameter]`, `_function_entry(project: str, dotted_module: str, file_rel: str, node: ast.FunctionDef | ast.AsyncFunctionDef) -> CatalogEntry`. Task 4 adds `_class_entry` reusing `_extract_parameters`/`_decorator_overrides`. Task 5 adds `scan_project`/`_scan_file` calling `_function_entry`.

- [ ] **Step 1: Write the failing tests**

`catalog_service/tests/test_scanner_functions.py`:
```python
from __future__ import annotations

import ast

from src.scanner import _decorator_overrides, _extract_parameters, _function_entry, _is_catalog_decorator


def _parse_function(source: str) -> ast.FunctionDef:
    tree = ast.parse(source)
    return tree.body[0]


def test_is_catalog_decorator_matches_bare_name():
    node = _parse_function("@catalog\ndef f(): pass")
    assert _is_catalog_decorator(node.decorator_list[0]) is True


def test_is_catalog_decorator_matches_call_form():
    node = _parse_function("@catalog(name='x')\ndef f(): pass")
    assert _is_catalog_decorator(node.decorator_list[0]) is True


def test_is_catalog_decorator_rejects_other_decorators():
    node = _parse_function("@staticmethod\ndef f(): pass")
    assert _is_catalog_decorator(node.decorator_list[0]) is False


def test_decorator_overrides_empty_for_bare_decorator():
    node = _parse_function("@catalog\ndef f(): pass")
    assert _decorator_overrides(node.decorator_list[0]) == {}


def test_decorator_overrides_reads_name_and_description():
    node = _parse_function("@catalog(name='renamed', description='custom')\ndef f(): pass")
    assert _decorator_overrides(node.decorator_list[0]) == {
        "name": "renamed",
        "description": "custom",
    }


def test_extract_parameters_no_default_is_json_null():
    node = _parse_function("def f(x): pass")
    params = _extract_parameters(node.args)
    assert params == [__import__("src.models", fromlist=["Parameter"]).Parameter("x", None, None)]


def test_extract_parameters_literal_none_default_is_the_string_none():
    node = _parse_function("def f(x=None): pass")
    params = _extract_parameters(node.args)
    assert params[0].default == "None"


def test_extract_parameters_captures_annotation_and_default():
    node = _parse_function("def f(x: str = 'hi'): pass")
    params = _extract_parameters(node.args)
    assert params[0].name == "x"
    assert params[0].annotation == "str"
    assert params[0].default == "'hi'"


def test_extract_parameters_skip_first_drops_self():
    node = _parse_function("def f(self, x): pass")
    params = _extract_parameters(node.args, skip_first=True)
    assert [p.name for p in params] == ["x"]


def test_function_entry_uses_docstring_when_no_override():
    node = _parse_function("@catalog\ndef greet(name: str):\n    'Says hello.'\n    pass")
    entry = _function_entry("chat_app", "src.services.foo", "src/services/foo.py", node)

    assert entry.id == "chat_app.src.services.foo.greet"
    assert entry.type == "function"
    assert entry.name == "greet"
    assert entry.description == "Says hello."
    assert entry.project == "chat_app"
    assert entry.file == "src/services/foo.py"
    assert entry.line == 1
    assert [p.name for p in entry.parameters] == ["name"]


def test_function_entry_prefers_explicit_overrides_over_docstring():
    node = _parse_function(
        "@catalog(name='renamed', description='custom')\ndef greet():\n    'ignored'\n    pass"
    )
    entry = _function_entry("chat_app", "src.services.foo", "src/services/foo.py", node)

    assert entry.name == "renamed"
    assert entry.description == "custom"
    assert entry.id == "chat_app.src.services.foo.renamed"
```

- [ ] **Step 2: Run to verify failure**

Run: `cd catalog_service && python -m pytest tests/test_scanner_functions.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.scanner'`.

- [ ] **Step 3: Implement the scanner's function-handling half**

`catalog_service/src/scanner.py`:
```python
"""Static AST scan for @catalog-decorated functions and classes.

Deliberately never imports the code it scans (see Global Constraints in
docs/superpowers/plans/2026-09-13-catalog-service.md) - everything here
reads source text and ast nodes only, never executes anything from the
scanned project.
"""

from __future__ import annotations

import ast
import logging
from pathlib import Path

from src.models import CatalogEntry, Parameter

logger = logging.getLogger(__name__)


def _is_catalog_decorator(node: ast.expr) -> bool:
    if isinstance(node, ast.Name):
        return node.id == "catalog"
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        return node.func.id == "catalog"
    return False


def _catalog_decorator(
    node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef,
) -> ast.expr | None:
    for dec in node.decorator_list:
        if _is_catalog_decorator(dec):
            return dec
    return None


def _decorator_overrides(node: ast.expr) -> dict[str, str]:
    """Reads string-literal name=/description= keywords off a
    @catalog(...) call. A bare @catalog (an ast.Name, not an ast.Call)
    has no keywords to read, so this returns {}."""
    overrides: dict[str, str] = {}
    if not isinstance(node, ast.Call):
        return overrides
    for kw in node.keywords:
        if (
            kw.arg in ("name", "description")
            and isinstance(kw.value, ast.Constant)
            and isinstance(kw.value.value, str)
        ):
            overrides[kw.arg] = kw.value.value
    return overrides


def _extract_parameters(args: ast.arguments, *, skip_first: bool = False) -> list[Parameter]:
    """Positional-or-keyword parameters only (posonlyargs + args) - the
    locked catalog schema doesn't need *args/**kwargs/keyword-only
    parameters, so extracting them isn't attempted (YAGNI).

    skip_first drops the leading parameter (self/cls) for methods.
    """
    positional = list(args.posonlyargs) + list(args.args)
    num_defaults = len(args.defaults)
    default_offset = len(positional) - num_defaults
    pairs = [
        (arg, args.defaults[i - default_offset] if i >= default_offset else None)
        for i, arg in enumerate(positional)
    ]
    if skip_first and pairs:
        pairs = pairs[1:]
    return [
        Parameter(
            name=arg.arg,
            annotation=ast.unparse(arg.annotation) if arg.annotation else None,
            default=ast.unparse(default) if default is not None else None,
        )
        for arg, default in pairs
    ]


def _function_entry(
    project: str,
    dotted_module: str,
    file_rel: str,
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> CatalogEntry:
    dec = _catalog_decorator(node)
    overrides = _decorator_overrides(dec) if dec is not None else {}
    name = overrides.get("name", node.name)
    description = overrides.get("description") or ast.get_docstring(node) or ""
    return CatalogEntry(
        id=f"{project}.{dotted_module}.{name}",
        type="function",
        name=name,
        description=description,
        project=project,
        file=file_rel,
        line=node.lineno,
        parameters=_extract_parameters(node.args),
    )
```

- [ ] **Step 4: Run to verify pass**

Run: `cd catalog_service && python -m pytest tests/test_scanner_functions.py -v`
Expected: PASS (11 tests).

- [ ] **Step 5: Commit**

```bash
git add catalog_service/src/scanner.py catalog_service/tests/test_scanner_functions.py
git commit -m "feat(catalog_service): scan @catalog-decorated functions via AST"
```

---

### Task 4: AST scanner — classes

**Files:**
- Modify: `catalog_service/src/scanner.py`
- Test: `catalog_service/tests/test_scanner_classes.py`

**Interfaces:**
- Consumes: `_catalog_decorator`, `_decorator_overrides`, `_extract_parameters` from Task 3.
- Produces: `_class_entry(project: str, dotted_module: str, file_rel: str, node: ast.ClassDef) -> CatalogEntry`. Task 5's `_scan_file` calls this for every decorated `ast.ClassDef`.

- [ ] **Step 1: Write the failing tests**

`catalog_service/tests/test_scanner_classes.py`:
```python
from __future__ import annotations

import ast

from src.scanner import _class_entry


def _parse_class(source: str) -> ast.ClassDef:
    tree = ast.parse(source)
    return tree.body[0]


def test_class_entry_captures_init_params_excluding_self():
    node = _parse_class(
        "@catalog\n"
        "class Widget:\n"
        "    'A reusable widget.'\n"
        "    def __init__(self, size: int):\n"
        "        self.size = size\n"
    )
    entry = _class_entry("chat_app", "src.services.widgets", "src/services/widgets.py", node)

    assert entry.type == "class"
    assert entry.name == "Widget"
    assert entry.description == "A reusable widget."
    assert entry.id == "chat_app.src.services.widgets.Widget"
    assert [p.name for p in entry.parameters] == ["size"]


def test_class_entry_lists_public_methods_only():
    node = _parse_class(
        "@catalog\n"
        "class Widget:\n"
        "    def __init__(self): pass\n"
        "    def render(self): pass\n"
        "    def resize(self): pass\n"
        "    def _internal(self): pass\n"
    )
    entry = _class_entry("chat_app", "src.services.widgets", "src/services/widgets.py", node)

    assert entry.methods == ["render", "resize"]


def test_class_entry_with_no_init_has_no_parameters():
    node = _parse_class("@catalog\nclass Widget:\n    def render(self): pass\n")
    entry = _class_entry("chat_app", "src.services.widgets", "src/services/widgets.py", node)

    assert entry.parameters == []
    assert entry.methods == ["render"]


def test_class_entry_respects_name_override():
    node = _parse_class("@catalog(name='RenamedWidget')\nclass Widget:\n    pass\n")
    entry = _class_entry("chat_app", "src.services.widgets", "src/services/widgets.py", node)

    assert entry.name == "RenamedWidget"
    assert entry.id == "chat_app.src.services.widgets.RenamedWidget"
```

- [ ] **Step 2: Run to verify failure**

Run: `cd catalog_service && python -m pytest tests/test_scanner_classes.py -v`
Expected: FAIL with `ImportError: cannot import name '_class_entry' from 'src.scanner'`.

- [ ] **Step 3: Implement `_class_entry`**

Append to `catalog_service/src/scanner.py`:
```python
def _class_entry(
    project: str,
    dotted_module: str,
    file_rel: str,
    node: ast.ClassDef,
) -> CatalogEntry:
    dec = _catalog_decorator(node)
    overrides = _decorator_overrides(dec) if dec is not None else {}
    name = overrides.get("name", node.name)
    description = overrides.get("description") or ast.get_docstring(node) or ""

    init_node = next(
        (
            n
            for n in node.body
            if isinstance(n, ast.FunctionDef) and n.name == "__init__"
        ),
        None,
    )
    parameters = _extract_parameters(init_node.args, skip_first=True) if init_node else []

    methods = sorted(
        n.name
        for n in node.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and not n.name.startswith("_")
    )

    return CatalogEntry(
        id=f"{project}.{dotted_module}.{name}",
        type="class",
        name=name,
        description=description,
        project=project,
        file=file_rel,
        line=node.lineno,
        parameters=parameters,
        methods=methods,
    )
```

- [ ] **Step 4: Run to verify pass**

Run: `cd catalog_service && python -m pytest tests/test_scanner_classes.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add catalog_service/src/scanner.py catalog_service/tests/test_scanner_classes.py
git commit -m "feat(catalog_service): scan @catalog-decorated classes via AST"
```

---

### Task 5: AST scanner — multi-file project walk

**Files:**
- Modify: `catalog_service/src/scanner.py`
- Test: `catalog_service/tests/test_scan_project.py`

**Interfaces:**
- Consumes: `_function_entry`, `_class_entry`, `_catalog_decorator` from Tasks 3/4.
- Produces: `scan_project(project: str, root: Path) -> list[CatalogEntry]`. Task 7 (registry) calls this once per configured project.

- [ ] **Step 1: Write the failing tests**

`catalog_service/tests/test_scan_project.py`:
```python
from __future__ import annotations

from pathlib import Path

from src.scanner import scan_project


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_scan_project_finds_decorated_function_across_nested_files(tmp_path):
    project_root = tmp_path / "chat_app"
    src_root = project_root / "src"
    _write(
        src_root / "services" / "foo.py",
        "from src.utils.catalog import catalog\n\n"
        "@catalog\n"
        "def bar(x: int):\n"
        "    'Adds one.'\n"
        "    return x + 1\n",
    )

    entries = scan_project("chat_app", src_root)

    assert len(entries) == 1
    entry = entries[0]
    assert entry.id == "chat_app.src.services.foo.bar"
    assert entry.file == "src/services/foo.py"
    assert entry.project == "chat_app"


def test_scan_project_ignores_undecorated_functions(tmp_path):
    src_root = tmp_path / "chat_app" / "src"
    _write(src_root / "services" / "foo.py", "def bar():\n    pass\n")

    assert scan_project("chat_app", src_root) == []


def test_scan_project_skips_file_with_syntax_error_and_keeps_going(tmp_path, caplog):
    src_root = tmp_path / "chat_app" / "src"
    _write(src_root / "broken.py", "def bar(:\n    pass\n")
    _write(
        src_root / "ok.py",
        "@catalog\ndef good():\n    'fine'\n    pass\n",
    )

    import logging

    with caplog.at_level(logging.WARNING):
        entries = scan_project("chat_app", src_root)

    assert [e.id for e in entries] == ["chat_app.src.ok.good"]
    assert any("broken.py" in message for message in caplog.messages)


def test_scan_project_returns_empty_list_for_missing_directory(tmp_path):
    assert scan_project("chat_app", tmp_path / "does_not_exist") == []
```

- [ ] **Step 2: Run to verify failure**

Run: `cd catalog_service && python -m pytest tests/test_scan_project.py -v`
Expected: FAIL with `ImportError: cannot import name 'scan_project' from 'src.scanner'`.

- [ ] **Step 3: Implement `scan_project`**

Append to `catalog_service/src/scanner.py`:
```python
def _dotted_module(file_rel: str) -> str:
    dotted = file_rel.replace("\\", "/").removesuffix(".py").replace("/", ".")
    return dotted.removesuffix(".__init__")


def _scan_file(project: str, root: Path, file_path: Path) -> list[CatalogEntry]:
    file_rel = str(file_path.relative_to(root.parent)).replace("\\", "/")
    dotted_module = _dotted_module(file_rel)
    source = file_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(file_path))

    entries: list[CatalogEntry] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and _catalog_decorator(node):
            entries.append(_function_entry(project, dotted_module, file_rel, node))
        elif isinstance(node, ast.ClassDef) and _catalog_decorator(node):
            entries.append(_class_entry(project, dotted_module, file_rel, node))
    return entries


def scan_project(project: str, root: Path) -> list[CatalogEntry]:
    """Walks every .py file under `root`, returning a CatalogEntry for each
    @catalog-decorated function/class found. A file that fails to parse
    (SyntaxError, bad encoding) is skipped with a logged warning - it never
    aborts the rest of the scan. `root` should point at a project's src/
    directory (paths in results are relative to its parent)."""
    if not root.exists():
        return []
    entries: list[CatalogEntry] = []
    for file_path in sorted(root.rglob("*.py")):
        try:
            entries.extend(_scan_file(project, root, file_path))
        except (SyntaxError, UnicodeDecodeError) as error:
            logger.warning("catalog scan: skipping %s (%s)", file_path, error)
    return entries
```

- [ ] **Step 4: Run to verify pass**

Run: `cd catalog_service && python -m pytest tests/test_scan_project.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Run the full scanner test suite together**

Run: `cd catalog_service && python -m pytest tests/test_scanner_functions.py tests/test_scanner_classes.py tests/test_scan_project.py -v`
Expected: PASS (19 tests total).

- [ ] **Step 6: Commit**

```bash
git add catalog_service/src/scanner.py catalog_service/tests/test_scan_project.py
git commit -m "feat(catalog_service): walk a project's source tree during scan"
```

---

### Task 6: Cache read/write

**Files:**
- Create: `catalog_service/src/cache.py`
- Test: `catalog_service/tests/test_cache.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `load_cache(path: Path) -> list[dict] | None`, `save_cache_atomic(path: Path, entries: list[dict]) -> None`. Task 7 (registry) calls both.

- [ ] **Step 1: Write the failing tests**

`catalog_service/tests/test_cache.py`:
```python
from __future__ import annotations

from src.cache import load_cache, save_cache_atomic


def test_load_cache_returns_none_when_file_missing(tmp_path):
    assert load_cache(tmp_path / "missing.json") is None


def test_save_then_load_round_trips(tmp_path):
    path = tmp_path / "data" / "catalog_cache.json"
    entries = [{"id": "a.b.c", "type": "function"}]

    save_cache_atomic(path, entries)

    assert load_cache(path) == entries


def test_save_creates_parent_directories(tmp_path):
    path = tmp_path / "nested" / "dir" / "catalog_cache.json"

    save_cache_atomic(path, [])

    assert path.exists()


def test_load_cache_returns_none_for_corrupt_file(tmp_path):
    path = tmp_path / "catalog_cache.json"
    path.write_text("not json", encoding="utf-8")

    assert load_cache(path) is None


def test_save_leaves_no_temp_files_behind(tmp_path):
    path = tmp_path / "catalog_cache.json"

    save_cache_atomic(path, [{"id": "a"}])

    assert list(tmp_path.iterdir()) == [path]
```

- [ ] **Step 2: Run to verify failure**

Run: `cd catalog_service && python -m pytest tests/test_cache.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.cache'`.

- [ ] **Step 3: Implement the cache module**

`catalog_service/src/cache.py`:
```python
"""JSON file cache for the scanned catalog entries.

Writes are atomic (temp file + os.replace) so a concurrent GET /catalog
never observes a half-written file - see Global Constraints in
docs/superpowers/plans/2026-09-13-catalog-service.md.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


def load_cache(path: Path) -> list[dict] | None:
    """Returns the cached entry-dicts, or None if no cache file exists yet
    (first run) or the file is unreadable/corrupt."""
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def save_cache_atomic(path: Path, entries: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as tmp_file:
            json.dump(entries, tmp_file)
            tmp_file.flush()
            os.fsync(tmp_file.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        os.unlink(tmp_name)
        raise
```

- [ ] **Step 4: Run to verify pass**

Run: `cd catalog_service && python -m pytest tests/test_cache.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add catalog_service/src/cache.py catalog_service/tests/test_cache.py
git commit -m "feat(catalog_service): add atomic JSON cache read/write"
```

---

### Task 7: Registry (cache-first serving + background refresh)

**Files:**
- Create: `catalog_service/src/registry.py`
- Test: `catalog_service/tests/test_registry.py`

**Interfaces:**
- Consumes: `scanner.scan_project` (Task 5), `cache.load_cache`/`cache.save_cache_atomic` (Task 6).
- Produces: `load_initial(cache_path: Path) -> None`, `current() -> tuple[str, list[dict]]`, `get_by_id(entry_id: str) -> dict | None`, `refresh(sources: list[tuple[str, Path]], cache_path: Path) -> None`. Task 8 (routes) calls all four.

- [ ] **Step 1: Write the failing tests**

`catalog_service/tests/test_registry.py`:
```python
from __future__ import annotations

import threading
import time

import pytest

from src import registry


@pytest.fixture(autouse=True)
def reset_registry():
    registry._entries = []
    registry._status = "scanning"
    yield
    registry._entries = []
    registry._status = "scanning"


def test_load_initial_serves_cached_entries_as_ready(tmp_path):
    cache_path = tmp_path / "catalog_cache.json"
    from src.cache import save_cache_atomic

    save_cache_atomic(cache_path, [{"id": "a.b.c"}])

    registry.load_initial(cache_path)

    assert registry.current() == ("ready", [{"id": "a.b.c"}])


def test_load_initial_leaves_scanning_when_no_cache_exists(tmp_path):
    registry.load_initial(tmp_path / "missing.json")

    assert registry.current() == ("scanning", [])


def test_get_by_id_finds_matching_entry(tmp_path):
    registry._entries = [{"id": "a.b.c"}, {"id": "x.y.z"}]
    registry._status = "ready"

    assert registry.get_by_id("x.y.z") == {"id": "x.y.z"}


def test_get_by_id_returns_none_when_missing():
    registry._entries = [{"id": "a.b.c"}]
    registry._status = "ready"

    assert registry.get_by_id("nope") is None


def test_refresh_sets_scanning_immediately_and_ready_after_background_scan(
    monkeypatch, tmp_path
):
    started = threading.Event()
    release = threading.Event()

    def fake_scan_project(project, root):
        started.set()
        release.wait(timeout=2)
        return []

    monkeypatch.setattr(registry.scanner, "scan_project", fake_scan_project)
    cache_path = tmp_path / "catalog_cache.json"

    registry.refresh([("chat_app", tmp_path)], cache_path)

    assert registry.current()[0] == "scanning"
    assert started.wait(timeout=2)
    release.set()

    for _ in range(100):
        if registry.current()[0] == "ready":
            break
        time.sleep(0.02)

    assert registry.current() == ("ready", [])
    assert cache_path.exists()
```

- [ ] **Step 2: Run to verify failure**

Run: `cd catalog_service && python -m pytest tests/test_registry.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.registry'`.

- [ ] **Step 3: Implement the registry**

`catalog_service/src/registry.py`:
```python
"""In-memory catalog state: cache-first at boot, refreshed in the
background. Module-level mutable state, single-process only - same
deliberate exception ai_agent/src/llm/cooldown.py documents for its own
module-level cooldown dict.
"""

from __future__ import annotations

import threading
from pathlib import Path

from src import cache, scanner

_lock = threading.Lock()
_entries: list[dict] = []
_status: str = "scanning"


def load_initial(cache_path: Path) -> None:
    """Cache-first boot: serve whatever was on disk from the last run
    immediately. Leaves status "scanning" (the default) when no cache
    exists yet - the first refresh() call will populate it."""
    global _entries, _status
    cached = cache.load_cache(cache_path)
    if cached is not None:
        with _lock:
            _entries = cached
            _status = "ready"


def current() -> tuple[str, list[dict]]:
    with _lock:
        return _status, list(_entries)


def get_by_id(entry_id: str) -> dict | None:
    with _lock:
        return next((entry for entry in _entries if entry["id"] == entry_id), None)


def refresh(sources: list[tuple[str, Path]], cache_path: Path) -> None:
    """Fire-and-forget: marks status "scanning" immediately, then rescans
    every configured project on a background daemon thread. Returns before
    the scan finishes - callers (routes.py's POST /catalog/refresh, and
    run.py at boot) never block on it."""
    global _status
    with _lock:
        _status = "scanning"
    threading.Thread(target=_run_refresh, args=(sources, cache_path), daemon=True).start()


def _run_refresh(sources: list[tuple[str, Path]], cache_path: Path) -> None:
    global _entries, _status
    scanned: list[dict] = []
    for project, root in sources:
        scanned.extend(entry.to_dict() for entry in scanner.scan_project(project, root))
    cache.save_cache_atomic(cache_path, scanned)
    with _lock:
        _entries = scanned
        _status = "ready"
```

- [ ] **Step 4: Run to verify pass**

Run: `cd catalog_service && python -m pytest tests/test_registry.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add catalog_service/src/registry.py catalog_service/tests/test_registry.py
git commit -m "feat(catalog_service): add cache-first registry with background refresh"
```

---

### Task 8: HTTP routes + entry point

**Files:**
- Create: `catalog_service/src/routes.py`
- Create: `catalog_service/src/run.py`
- Test: `catalog_service/tests/test_routes.py`
- Test: `catalog_service/tests/test_run.py`

**Interfaces:**
- Consumes: `registry.current`, `registry.get_by_id`, `registry.refresh`, `registry.load_initial` (Task 7); `settings` (Task 1).
- Produces: `install_catalog_routes(app: Starlette) -> None`, `build_app() -> Starlette`, `main() -> None`.

- [ ] **Step 1: Write the failing route tests**

`catalog_service/tests/test_routes.py`:
```python
from __future__ import annotations

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

from src import registry
from src.routes import install_catalog_routes


@pytest.fixture
def client():
    app = Starlette()
    install_catalog_routes(app)
    with TestClient(app) as test_client:
        yield test_client


def test_get_catalog_returns_status_and_entries(monkeypatch, client):
    monkeypatch.setattr(registry, "current", lambda: ("ready", [{"id": "a.b.c"}]))

    response = client.get("/catalog")

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "entries": [{"id": "a.b.c"}]}


def test_get_catalog_entry_found(monkeypatch, client):
    monkeypatch.setattr(registry, "get_by_id", lambda entry_id: {"id": entry_id})

    response = client.get("/catalog/chat_app.src.services.foo.bar")

    assert response.status_code == 200
    assert response.json() == {"id": "chat_app.src.services.foo.bar"}


def test_get_catalog_entry_missing_is_404(monkeypatch, client):
    monkeypatch.setattr(registry, "get_by_id", lambda entry_id: None)

    response = client.get("/catalog/does.not.exist")

    assert response.status_code == 404
    assert "does.not.exist" in response.json()["error"]


def test_post_refresh_triggers_registry_refresh_and_returns_immediately(monkeypatch, client):
    calls = []
    monkeypatch.setattr(
        registry, "refresh", lambda sources, cache_path: calls.append((sources, cache_path))
    )

    response = client.post("/catalog/refresh")

    assert response.status_code == 200
    assert response.json() == {"status": "scanning"}
    assert len(calls) == 1


def test_health_returns_ok(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

- [ ] **Step 2: Run to verify failure**

Run: `cd catalog_service && python -m pytest tests/test_routes.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.routes'`.

- [ ] **Step 3: Implement the routes**

`catalog_service/src/routes.py`:
```python
"""Plain HTTP JSON routes for the catalog - no auth (see Global
Constraints in docs/superpowers/plans/2026-09-13-catalog-service.md: this
serves read-only, non-sensitive metadata).
"""

from __future__ import annotations

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse

from src import registry
from src.config import settings


async def get_catalog(request: Request) -> JSONResponse:
    status, entries = registry.current()
    return JSONResponse({"status": status, "entries": entries})


async def get_catalog_entry(request: Request) -> JSONResponse:
    entry_id = request.path_params["entry_id"]
    entry = registry.get_by_id(entry_id)
    if entry is None:
        return JSONResponse({"error": f"Unknown catalog id {entry_id!r}"}, status_code=404)
    return JSONResponse(entry)


async def refresh_catalog(request: Request) -> JSONResponse:
    registry.refresh(settings.sources(), settings.cache_path)
    return JSONResponse({"status": "scanning"})


async def health(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


def install_catalog_routes(app: Starlette) -> None:
    app.add_route("/catalog", get_catalog, methods=["GET"])
    app.add_route("/catalog/{entry_id}", get_catalog_entry, methods=["GET"])
    app.add_route("/catalog/refresh", refresh_catalog, methods=["POST"])
    app.add_route("/health", health, methods=["GET"])
```

- [ ] **Step 4: Run to verify the route tests pass**

Run: `cd catalog_service && python -m pytest tests/test_routes.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Write the failing entry-point test**

`catalog_service/tests/test_run.py`:
```python
from __future__ import annotations

from starlette.testclient import TestClient

from src.run import build_app


def test_build_app_wires_up_health_route():
    with TestClient(build_app()) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

- [ ] **Step 6: Run to verify it fails**

Run: `cd catalog_service && python -m pytest tests/test_run.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.run'`.

- [ ] **Step 7: Implement the entry point**

`catalog_service/src/run.py`:
```python
"""Entry point for the catalog service.

Run with:
    python -m src.run
"""

from __future__ import annotations

import logging

import uvicorn
from starlette.applications import Starlette

from src import registry
from src.config import settings
from src.routes import install_catalog_routes


def build_app() -> Starlette:
    app = Starlette()
    install_catalog_routes(app)
    return app


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    # Cache-first: serve whatever's on disk from the last run immediately,
    # then always kick a fresh background scan so the cache doesn't go
    # stale across restarts - see Global Constraints.
    registry.load_initial(settings.cache_path)
    registry.refresh(settings.sources(), settings.cache_path)
    print(f"Catalog service: http://{settings.host}:{settings.port}", flush=True)
    uvicorn.run(build_app(), host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()
```

- [ ] **Step 8: Run to verify it passes**

Run: `cd catalog_service && python -m pytest tests/test_run.py -v`
Expected: PASS (1 test).

- [ ] **Step 9: Run the whole catalog_service test suite**

Run: `cd catalog_service && python -m pytest -v`
Expected: PASS (all tests from Tasks 1-8).

- [ ] **Step 10: Commit**

```bash
git add catalog_service/src/routes.py catalog_service/src/run.py catalog_service/tests/test_routes.py catalog_service/tests/test_run.py
git commit -m "feat(catalog_service): add HTTP routes and entry point"
```

---

### Task 9: `@catalog` decorator stub in chat_app, mcp_server, ai_agent

**Files:**
- Create: `chat_app/src/utils/catalog.py`
- Create: `mcp_server/src/utils/catalog.py`
- Create: `ai_agent/src/catalog.py` (ai_agent has no `utils/` package today — flat `src/`, per repo recon — so this lands directly in `src/`, matching that project's own layout)
- Test: `chat_app/tests/test_catalog_decorator.py`
- Test: `mcp_server/tests/test_catalog_decorator.py`
- Test: `ai_agent/tests/test_catalog_decorator.py`

**Interfaces:**
- Produces (identical in all three): `catalog(_obj=None, *, name: str | None = None, description: str | None = None)` — an identity decorator. Nothing in catalog_service imports this; `scanner.py` (Task 3-5) only recognizes the literal text `catalog` in decorator syntax.

- [ ] **Step 1: Write the failing test for chat_app**

`chat_app/tests/test_catalog_decorator.py`:
```python
from src.utils.catalog import catalog


def test_bare_decorator_returns_function_unchanged():
    @catalog
    def sample():
        """docstring"""
        return 1

    assert sample() == 1
    assert sample.__doc__ == "docstring"


def test_decorator_with_overrides_returns_function_unchanged():
    @catalog(name="renamed", description="custom")
    def sample():
        return 2

    assert sample() == 2


def test_decorator_on_class_returns_class_unchanged():
    @catalog
    class Sample:
        def __init__(self, x: int):
            self.x = x

    instance = Sample(5)
    assert instance.x == 5
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd chat_app && python -m pytest tests/test_catalog_decorator.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.utils.catalog'`.

- [ ] **Step 3: Implement the decorator in chat_app**

`chat_app/src/utils/catalog.py`:
```python
"""Marks a function or class as part of the cross-project reuse catalog.

This decorator is a no-op at runtime - it exists only so decorated source
imports cleanly when chat_app runs. The standalone catalog_service (see
docs/superpowers/plans/2026-09-13-catalog-service.md) finds decorated
functions/classes by statically parsing this file's source with Python's
`ast` module; it never imports this module or calls this function. Any
name=/description= passed here is read out of the decorator's own source
text by that static scan, not by executing this code.

This file is deliberately duplicated identically into mcp_server and
ai_agent rather than shared - see the plan's Global Constraints for why
(this repo has no shared package across the three apps).
"""

from __future__ import annotations

from typing import Callable, TypeVar

T = TypeVar("T")


def catalog(
    _obj: T | None = None, *, name: str | None = None, description: str | None = None
) -> T | Callable[[T], T]:
    def decorator(obj: T) -> T:
        return obj

    if _obj is not None:
        return decorator(_obj)
    return decorator
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd chat_app && python -m pytest tests/test_catalog_decorator.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Duplicate identically into mcp_server**

`mcp_server/src/utils/catalog.py`: byte-identical to `chat_app/src/utils/catalog.py` from Step 3.

`mcp_server/tests/test_catalog_decorator.py`: byte-identical to `chat_app/tests/test_catalog_decorator.py` from Step 1 (import path `from src.utils.catalog import catalog` is the same — mcp_server already has a `src/utils/` package).

Run: `cd mcp_server && python -m pytest tests/test_catalog_decorator.py -v`
Expected: PASS (3 tests).

- [ ] **Step 6: Duplicate into ai_agent (flat `src/`, no `utils/` package)**

`ai_agent/src/catalog.py`: same content as Step 3, unchanged.

`ai_agent/tests/test_catalog_decorator.py`:
```python
from src.catalog import catalog


def test_bare_decorator_returns_function_unchanged():
    @catalog
    def sample():
        """docstring"""
        return 1

    assert sample() == 1
    assert sample.__doc__ == "docstring"


def test_decorator_with_overrides_returns_function_unchanged():
    @catalog(name="renamed", description="custom")
    def sample():
        return 2

    assert sample() == 2


def test_decorator_on_class_returns_class_unchanged():
    @catalog
    class Sample:
        def __init__(self, x: int):
            self.x = x

    instance = Sample(5)
    assert instance.x == 5
```

Run: `cd ai_agent && python -m pytest tests/test_catalog_decorator.py -v`
Expected: PASS (3 tests).

- [ ] **Step 7: Commit**

```bash
git add chat_app/src/utils/catalog.py chat_app/tests/test_catalog_decorator.py
git add mcp_server/src/utils/catalog.py mcp_server/tests/test_catalog_decorator.py
git add ai_agent/src/catalog.py ai_agent/tests/test_catalog_decorator.py
git commit -m "feat: add @catalog no-op decorator to chat_app, mcp_server, ai_agent"
```

---

### Task 10: Launch script

**Files:**
- Create: `run_catalog.bat` (repo root)

**Interfaces:**
- Consumes: `catalog_service/pyproject.toml`'s console entry point (`py -m src.run`, same invocation style as `run_mcp.bat`).
- Produces: nothing consumed by later tasks — this is the last task.

- [ ] **Step 1: Create the launch script**

`run_catalog.bat`:
```bat
@echo off
REM Activate the virtual environment
call .\venv_catalog\Scripts\activate

REM Change directory to catalog_service
cd /d "%~dp0catalog_service"

:run
REM Run the catalog service
py -m src.run

echo.
echo ----------------------------------------
echo  Catalog service stopped.
choice /C RQ /N /M "Press [R] to restart, [Q] to quit: "
if errorlevel 2 goto :end
if errorlevel 1 goto :run

:end
```

This deliberately mirrors `run_mcp.bat` line for line (same restart-prompt pattern), with `venv_catalog` as the venv name and `catalog_service` as the target directory. It is **not** added to `run_all.bat` — see the flagged assumption in Global Constraints.

- [ ] **Step 2: Manually verify the service boots**

Run (from repo root, after creating `venv_catalog` and `pip install -e ./catalog_service[dev]` into it once):
```bash
run_catalog.bat
```
Expected: console prints `Catalog service: http://127.0.0.1:8020`, then a `GET http://127.0.0.1:8020/health` in a browser or `curl` returns `{"status": "ok"}`.

- [ ] **Step 3: Commit**

```bash
git add run_catalog.bat
git commit -m "feat(catalog_service): add root-level launch script"
```

---

## After all tasks

Full-repo sanity check — run every affected project's test suite once more together:

```bash
cd catalog_service && python -m pytest -v
cd ../chat_app && python -m pytest tests/test_catalog_decorator.py -v
cd ../mcp_server && python -m pytest tests/test_catalog_decorator.py -v
cd ../ai_agent && python -m pytest tests/test_catalog_decorator.py -v
```

All should pass with zero changes to any existing test in those three projects — Task 9 only ever *adds* a new file plus a new test file to each, never touches existing code.
