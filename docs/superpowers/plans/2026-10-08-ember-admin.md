# ember_admin and Live Capability Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a separate admin web app (`apps/ember_admin`) and let `mcp_server` add, reload, and switch capabilities online or offline at runtime, with no restart of `mcp_server` or `ember_api`.

**Architecture:** `mcp_server` gets a folder scanner (`services/capability_loader.py`) that replaces the eight hard-wired import blocks in `run.py`, plus a `POST /capabilities/refresh` route. Going online always re-imports the capability from disk. `ember_api` proxies the new route (admin only) and passes through the richer status fields. `ember_admin` is a new Vue 3 + TS app that copies the Admin and Analytics pages from `ember_web` and adds Capabilities and Extensions pages. It reaches `ember_api` through a Vite `/api` proxy, so it shares the login.

**Tech Stack:** Python 3.11+, FastMCP (`mcp==1.28.0`), Starlette, FastAPI, pytest; Vue 3, TypeScript, Pinia, vue-router, Vite, vitest, Playwright.

**Spec:** `docs/superpowers/specs/2026-10-08-ember-admin-design.md`

## Global Constraints

- Admin and Analytics stay in `ember_web` too (copy, not move).
- Backend is `ember_api` only. No second backend, no second login system.
- Every offline to online switch re-imports the capability from disk.
- A newly discovered capability starts offline.
- Discovery is a folder scanner, not a manifest file.
- New `ember_api` routes need `admin.manage` and write an activity-log entry.
- Persist-then-apply stays for going offline: write `config_capabilities.json` first, then change the live server. Going online applies first (it can fail), then persists.
- One `asyncio.Lock` serializes load, unload and scan.
- Radius comes from the `--radius-*` tokens only (`radiusScale.test.ts` enforces it). Colors come from `style.css` tokens.
- Code comments follow each file's existing density. Commit messages end with `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.
- Never run git at the workspace root `D:\User\Documents\Programming`. Run git inside `Python/MCPServer`.
- Run mcp_server tests with `apps/mcp_server/.venv_mcp/Scripts/python.exe -m pytest` from `apps/mcp_server`.

## Spec refinements found while planning

These two points differ slightly from the spec. Task 11 updates the spec.

1. **No thread for the import.** The spec says the import runs in `asyncio.to_thread`. That would let the `@mcp.tool()` decorators mutate `mcp`'s tool dict from a worker thread while the event loop lists tools. The loader runs the import on the event-loop thread under the lock. A capability import takes milliseconds, so the stall is negligible.
2. **Explicit-offline capabilities still load at startup.** Today an offline capability's tools stay listed (greyed) because `run.py` imports every capability and then disables it. `ember_web` groups tools by that live list. So at startup a folder with an explicit config entry is imported, then disabled if its entry is offline. A folder with no entry is only discovered: its `META` is read, `tool.py` is not imported, and it lists no tools until its first Online.
3. **`ai_agent` needs no nudge.** `registry.list_tools()` asks every upstream live on each call (`apps/ai_agent/src/mcp_client/registry.py`, `_live_tools_for`). Running agents see a toggle or reload on their next turn. The status field is named `loaded` (not `discovered`).

## File Structure

```
apps/mcp_server/
  src/services/capability_meta.py        modify: add unregister()
  src/services/capability_registry.py    modify: add register_unloaded(), discard()
  src/commands.py                        modify: add remove_capability()
  src/services/app_config.py             modify: add migrate_capabilities_config()
  src/services/capability_loader.py      create: scan, load, unload, set_online, refresh
  src/capability_routes.py               modify: use the loader, add POST /capabilities/refresh
  src/run.py                             modify: replace the 8 import blocks with the loader
  tests/test_capability_loader.py        create
  tests/test_capability_routes.py        modify: new status fields, refresh route
  tests/test_app_config.py               modify: migration test
  tests/test_capability_registry.py      modify: new helper tests
  tests/test_commands.py                 modify: remove_capability test
  tests/test_capability_meta.py          create
apps/ember_api/
  src/services/mcp_server_info.py        modify: refresh_capabilities()
  src/routes/server_info.py              modify: CapabilityOut fields, POST /api/capabilities/refresh
  tests/test_server_info.py              modify
apps/ember_admin/                        create (new project)
  package.json, vite.config.ts, tsconfig*.json, index.html, run.bat, README.md, AGENTS.md, CLAUDE.md
  public/favicon.svg
  src/main.ts, App.vue, style.css
  src/router/index.ts, pages.ts, redirect.ts
  src/components/AdminNav.vue
  src/api/CapabilitiesAdminClient.ts, ExtensionsClient.ts (copied), ...
  src/views/CapabilitiesAdminView.vue, ExtensionsAdminView.vue, AdminView.vue (copied), AnalyticsView.vue (copied), LoginView.vue, NoAccessView.vue
  e2e/fakeApi.ts, e2e/admin.spec.ts, playwright.config.ts
```

---

## Part A: mcp_server

### Task 1: Registry helpers (meta, registry, commands)

Small pieces the loader needs so a capability can be unloaded and loaded again.

**Files:**
- Modify: `apps/mcp_server/src/services/capability_meta.py` (add `unregister`)
- Modify: `apps/mcp_server/src/services/capability_registry.py` (add `register_unloaded`, `discard`)
- Modify: `apps/mcp_server/src/commands.py` (add `remove_capability`)
- Create: `apps/mcp_server/tests/test_capability_meta.py`
- Modify: `apps/mcp_server/tests/test_capability_registry.py`, `apps/mcp_server/tests/test_commands.py`

**Interfaces:**
- Produces: `capability_meta.unregister(folder: str) -> None` (no error if absent)
- Produces: `capability_registry.register_unloaded(name: str, label: str) -> None` (raises `ValueError` if `name` is registered)
- Produces: `capability_registry.discard(mcp: FastMCP, name: str) -> None` (removes live tools and templates, then the handle; no error if absent)
- Produces: `commands.remove_capability(capability_id: str) -> None`

- [ ] **Step 1: Write the failing tests**

`apps/mcp_server/tests/test_capability_meta.py`:

```python
from __future__ import annotations

import pytest

from src.services import capability_meta


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    monkeypatch.setattr(capability_meta, "_BY_FOLDER", {})


def test_unregister_lets_the_folder_register_again():
    capability_meta.register(folder="widgets", id="wid", label="Widgets")

    capability_meta.unregister("widgets")

    assert capability_meta.for_folder("widgets") is None
    assert capability_meta.register(folder="widgets", id="wid2", label="W2").id == "wid2"


def test_unregister_of_an_unknown_folder_is_a_no_op():
    capability_meta.unregister("nothing")
```

Append to `apps/mcp_server/tests/test_commands.py`:

```python
def test_remove_capability_drops_only_that_capabilitys_commands():
    def fn_a():
        ...

    def fn_b():
        ...

    fn_a.__module__ = "src.capabilities.widgets.tool"
    fn_b.__module__ = "src.capabilities.gadgets.tool"
    commands.command(name="a", description="a", capability="wid")(fn_a)
    commands.command(name="b", description="b", capability="gad")(fn_b)

    commands.remove_capability("wid")

    assert [spec.capability for spec in commands.all_commands()] == ["gad"]
```

Append to `apps/mcp_server/tests/test_capability_registry.py` (it already clears `registry._REGISTRY` in a fixture and imports `FastMCP` and `registry`; reuse them):

```python
def test_register_unloaded_adds_an_offline_handle_with_no_tools():
    registry.register_unloaded("widgets", "Widgets")

    assert registry.names() == ["widgets"]
    assert registry.is_enabled("widgets") is False
    assert registry.label("widgets") == "Widgets"
    assert registry.tool_names("widgets") == []


def test_register_unloaded_refuses_a_taken_name():
    registry.register_unloaded("widgets", "Widgets")

    with pytest.raises(ValueError, match="already registered"):
        registry.register_unloaded("widgets", "Again")


def test_discard_removes_live_tools_and_the_handle():
    server = FastMCP(name="t")
    with registry.capturing(server, "widgets"):
        @server.tool()
        def make_widget() -> str:
            return "w"

    registry.discard(server, "widgets")

    assert registry.names() == []
    assert "make_widget" not in server._tool_manager._tools


def test_discard_of_an_unknown_name_is_a_no_op():
    registry.discard(FastMCP(name="t"), "nothing")
```

(If `pytest` is not imported at the top of `test_capability_registry.py`, add `import pytest`.)

- [ ] **Step 2: Run the tests to verify they fail**

Run (from `apps/mcp_server`): `.venv_mcp/Scripts/python.exe -m pytest tests/test_capability_meta.py tests/test_commands.py tests/test_capability_registry.py -q`
Expected: FAIL with `AttributeError` for `unregister`, `remove_capability`, `register_unloaded`, `discard`.

- [ ] **Step 3: Implement**

In `capability_meta.py`, after `register`:

```python
def unregister(folder: str) -> None:
    """Forget `folder`'s id/label so its package can register again after a
    reload (see capability_loader.py). A folder that never registered is fine."""
    _BY_FOLDER.pop(folder, None)
```

In `capability_registry.py`, after `set_enabled`:

```python
def register_unloaded(name: str, label: str) -> None:
    """Record a capability that exists on disk but has not been brought
    online: an offline handle with no tools. Going online replaces it with
    a captured one (capability_loader.py)."""
    if name in _REGISTRY:
        raise ValueError(f"Capability {name!r} is already registered")
    _REGISTRY[name] = _CapabilityHandle(enabled=False, label=label)


def discard(mcp: FastMCP, name: str) -> None:
    """Take `name` off the live server and forget it. Used before a reload,
    so the fresh import can capture again under the same name."""
    handle = _REGISTRY.get(name)
    if handle is None:
        return
    set_enabled(mcp, name, False)
    del _REGISTRY[name]
```

In `commands.py`, after `all_commands`:

```python
def remove_capability(capability_id: str) -> None:
    """Drop every command of one capability, so a reload can register them
    again without tripping over its own earlier entries."""
    for key in [key for key in _COMMANDS if key[0] == capability_id]:
        del _COMMANDS[key]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv_mcp/Scripts/python.exe -m pytest tests/test_capability_meta.py tests/test_commands.py tests/test_capability_registry.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd /d/User/Documents/Programming/Python/MCPServer
git add apps/mcp_server/src apps/mcp_server/tests
git commit -m "feat(mcp_server): helpers to unload and re-register a capability"
```

---

### Task 2: Config migration

On first run with the scanner, write explicit `enabled: true` entries for capabilities that exist but have no entry (such as `watchers`), then set a marker so later new folders default to offline.

**Files:**
- Modify: `apps/mcp_server/src/services/app_config.py` (add `migrate_capabilities_config` after `save_capabilities_config`)
- Modify: `apps/mcp_server/tests/test_app_config.py`

**Interfaces:**
- Produces: `migrate_capabilities_config(config_path: Path, ids: list[str]) -> None`. Idempotent. Marker key: `"_scanner": {"migrated": true}`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_app_config.py`; it already imports `json` and `Path`, if not add them, and the module as `app_config` or by name, match the file's existing import style)

```python
def test_migrate_capabilities_writes_missing_entries_once(tmp_path):
    path = tmp_path / "config_capabilities.json"
    path.write_text(json.dumps({"vault": {"enabled": False}}), encoding="utf-8")

    migrate_capabilities_config(path, ["vault", "watch"])

    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["vault"] == {"enabled": False}  # an explicit entry is kept
    assert saved["watch"] == {"enabled": True}  # a missing one stays on
    assert saved["_scanner"] == {"migrated": True}

    migrate_capabilities_config(path, ["vault", "watch", "newcomer"])

    assert "newcomer" not in json.loads(path.read_text(encoding="utf-8"))  # after the marker: offline by default


def test_migrate_capabilities_creates_a_missing_file(tmp_path):
    path = tmp_path / "config_capabilities.json"

    migrate_capabilities_config(path, ["vault"])

    assert json.loads(path.read_text(encoding="utf-8")) == {"vault": {"enabled": True}, "_scanner": {"migrated": True}}
```

Add `migrate_capabilities_config` to the file's import from `src.services.app_config`.

- [ ] **Step 2: Run to verify it fails**

Run: `.venv_mcp/Scripts/python.exe -m pytest tests/test_app_config.py -q`
Expected: FAIL (ImportError for `migrate_capabilities_config`)

- [ ] **Step 3: Implement** (in `app_config.py`, after `save_capabilities_config`)

```python
_SCANNER_MARKER = "_scanner"


def migrate_capabilities_config(config_path: Path, ids: list[str]) -> None:
    """Once, when the folder scanner first runs: write ``enabled: true`` for
    every capability that has no entry, then set a marker.

    Before the scanner, "no entry" meant enabled, and ``watchers`` relies on
    that. After it, a folder that appears later with no entry is offline until
    an admin brings it online. The marker is what tells the two apart, so
    nothing that is on today goes dark on the next restart. Does nothing once
    the marker is there.
    """
    data = load_config(config_path) if config_path.exists() else {}
    if _SCANNER_MARKER in data:
        return
    for capability_id in ids:
        data.setdefault(capability_id, {"enabled": True})
    data[_SCANNER_MARKER] = {"migrated": True}
    _write_config(config_path, data)
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv_mcp/Scripts/python.exe -m pytest tests/test_app_config.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd /d/User/Documents/Programming/Python/MCPServer
git add apps/mcp_server/src/services/app_config.py apps/mcp_server/tests/test_app_config.py
git commit -m "feat(mcp_server): one-time config migration for the capability scanner"
```

---

### Task 3: The capability loader

The core. Scans folders, loads (always a fresh import), unloads, rolls back on failure, serializes with a lock.

**Files:**
- Create: `apps/mcp_server/src/services/capability_loader.py`
- Create: `apps/mcp_server/tests/test_capability_loader.py`

**Interfaces:**
- Consumes (Task 1): `capability_meta.unregister`, `capability_registry.register_unloaded`, `capability_registry.discard`, `commands.remove_capability`
- Consumes (Task 2): `migrate_capabilities_config`
- Produces:
  - `class CapabilityError(Exception)` with class attribute `status: int = 400`; subclasses `UnknownCapability` (`status = 404`) and `CapabilityLoadError` (`status = 409`)
  - `@dataclass class CapabilityRecord: folder: str; id: str; label: str; loaded: bool = False; missing: bool = False; load_error: str | None = None`
  - `class CapabilityLoader(mcp: FastMCP, package: str, config_path: Path)` with:
    - `scan() -> None`
    - `startup() -> None`
    - `async refresh() -> None`
    - `async set_online(name: str, online: bool) -> None`
    - `records() -> list[CapabilityRecord]`
    - `record_for(name: str) -> CapabilityRecord | None`

- [ ] **Step 1: Write the failing tests**

`apps/mcp_server/tests/test_capability_loader.py`:

```python
"""CapabilityLoader against fixture packages in a temp folder.

Each test writes a package ``<unique>/capabilities/<folder>/`` with the
same shape as a real capability (__init__.py registers META, tool.py
registers a tool and a command), puts its parent on sys.path, and points a
loader at it. ``src.server.mcp`` is swapped for a fresh FastMCP because a
fixture's tool.py does ``from src.server import mcp`` at import time.
"""

from __future__ import annotations

import asyncio
import json
import sys
import uuid
from pathlib import Path

import pytest
from mcp.server.fastmcp import FastMCP

from src import commands
from src.services import capability_meta, capability_registry
from src.services.capability_loader import (
    CapabilityLoader,
    CapabilityLoadError,
    UnknownCapability,
)


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    monkeypatch.setattr(capability_meta, "_BY_FOLDER", {})
    monkeypatch.setattr(commands, "_COMMANDS", {})
    monkeypatch.setattr(capability_registry, "_REGISTRY", {})


@pytest.fixture
def mcp(monkeypatch):
    server = FastMCP(name="test")
    monkeypatch.setattr("src.server.mcp", server)
    return server


@pytest.fixture
def package(tmp_path, monkeypatch):
    """A fresh importable package ``<name>.capabilities`` under tmp_path."""
    name = f"fx_{uuid.uuid4().hex[:8]}"
    root = tmp_path / name / "capabilities"
    root.mkdir(parents=True)
    (tmp_path / name / "__init__.py").write_text("")
    (root / "__init__.py").write_text("")
    monkeypatch.syspath_prepend(str(tmp_path))
    yield name, root
    for key in [key for key in sys.modules if key == name or key.startswith(name + ".")]:
        del sys.modules[key]


def write_capability(root: Path, folder: str, capability_id: str, tool_name: str, returns: str = "v1", tool_source: str | None = None) -> None:
    directory = root / folder
    directory.mkdir(exist_ok=True)
    (directory / "__init__.py").write_text(
        "from src.services import capability_meta\n"
        f'META = capability_meta.register(folder="{folder}", id="{capability_id}", label="{folder.title()}")\n'
    )
    (directory / "tool.py").write_text(
        tool_source
        or (
            "from src.commands import command\n"
            "from src.server import mcp\n\n"
            f'@command(name="run", description="Run")\n'
            f"@mcp.tool()\n"
            f"def {tool_name}() -> str:\n"
            f'    return "{returns}"\n'
        )
    )


@pytest.fixture
def loader_for(mcp, package, tmp_path):
    name, root = package

    def make() -> CapabilityLoader:
        return CapabilityLoader(mcp, f"{name}.capabilities", tmp_path / "config_capabilities.json")

    return make


def run(coro):
    return asyncio.run(coro)


def tool_names(mcp: FastMCP) -> set[str]:
    return set(mcp._tool_manager._tools)


def test_scan_registers_a_new_folder_offline_without_importing_its_tools(loader_for, package, mcp):
    _, root = package
    write_capability(root, "widgets", "wid", "tool_wid_run")
    loader = loader_for()

    loader.scan()

    record = loader.record_for("wid")
    assert (record.folder, record.label, record.loaded, record.missing) == ("widgets", "Widgets", False, False)
    assert capability_registry.is_enabled("wid") is False
    assert tool_names(mcp) == set()


def test_set_online_loads_the_tools_and_commands_and_persists(loader_for, package, mcp, tmp_path):
    _, root = package
    write_capability(root, "widgets", "wid", "tool_wid_run")
    loader = loader_for()
    loader.scan()

    run(loader.set_online("wid", True))

    assert tool_names(mcp) == {"tool_wid_run"}
    assert loader.record_for("wid").loaded is True
    assert [spec.tool_name for spec in commands.all_commands()] == ["tool_wid_run"]
    assert json.loads((tmp_path / "config_capabilities.json").read_text()) == {"wid": {"enabled": True}}


def test_going_online_again_picks_up_edited_code(loader_for, package, mcp):
    _, root = package
    write_capability(root, "widgets", "wid", "tool_wid_run", returns="v1")
    loader = loader_for()
    loader.scan()
    run(loader.set_online("wid", True))
    run(loader.set_online("wid", False))
    assert "tool_wid_run" not in tool_names(mcp)

    write_capability(root, "widgets", "wid", "tool_wid_run", returns="v2")
    run(loader.set_online("wid", True))

    tool = mcp._tool_manager._tools["tool_wid_run"]
    assert tool.fn() == "v2"
    assert len(commands.all_commands()) == 1  # no duplicate-key error, no leftovers


def test_a_broken_import_rolls_back_to_offline_and_keeps_the_error(loader_for, package, mcp):
    _, root = package
    write_capability(root, "widgets", "wid", "tool_wid_run")
    loader = loader_for()
    loader.scan()
    write_capability(
        root, "widgets", "wid", "tool_wid_run",
        tool_source=(
            "from src.server import mcp\n\n"
            "@mcp.tool()\n"
            "def tool_wid_half() -> str:\n"
            '    return "half"\n\n'
            "raise RuntimeError('boom')\n"
        ),
    )

    with pytest.raises(CapabilityLoadError, match="boom"):
        run(loader.set_online("wid", True))

    record = loader.record_for("wid")
    assert record.loaded is False
    assert "boom" in record.load_error
    assert tool_names(mcp) == set()  # the half-registered tool is gone
    assert capability_registry.is_enabled("wid") is False


def test_a_duplicate_tool_name_is_refused_and_leaves_the_other_capability_alone(loader_for, package, mcp):
    _, root = package
    write_capability(root, "widgets", "wid", "tool_shared")
    write_capability(root, "gadgets", "gad", "tool_shared")
    loader = loader_for()
    loader.scan()
    run(loader.set_online("wid", True))

    with pytest.raises(CapabilityLoadError, match="tool_shared"):
        run(loader.set_online("gad", True))

    assert tool_names(mcp) == {"tool_shared"}
    assert loader.record_for("wid").loaded is True
    assert loader.record_for("gad").loaded is False


def test_a_removed_folder_is_marked_missing_and_cannot_go_online(loader_for, package):
    import shutil

    _, root = package
    write_capability(root, "widgets", "wid", "tool_wid_run")
    loader = loader_for()
    loader.scan()
    shutil.rmtree(root / "widgets")

    run(loader.refresh())

    assert loader.record_for("wid").missing is True
    with pytest.raises(CapabilityLoadError, match="no longer exists"):
        run(loader.set_online("wid", True))


def test_refresh_finds_a_folder_added_while_running(loader_for, package):
    _, root = package
    loader = loader_for()
    loader.scan()
    assert loader.records() == []

    write_capability(root, "widgets", "wid", "tool_wid_run")
    run(loader.refresh())

    assert [record.id for record in loader.records()] == ["wid"]


def test_an_import_error_in_a_new_folder_does_not_stop_the_scan(loader_for, package):
    _, root = package
    (root / "broken").mkdir()
    (root / "broken" / "__init__.py").write_text("raise RuntimeError('bad init')\n")
    write_capability(root, "widgets", "wid", "tool_wid_run")
    loader = loader_for()

    loader.scan()

    broken = loader.record_for("broken")
    assert "bad init" in broken.load_error
    assert loader.record_for("wid").load_error is None


def test_set_online_of_an_unknown_name_is_unknown(loader_for):
    with pytest.raises(UnknownCapability):
        run(loader_for().set_online("nope", True))


def test_going_offline_persists_first_and_hides_the_tools(loader_for, package, mcp, tmp_path):
    _, root = package
    write_capability(root, "widgets", "wid", "tool_wid_run")
    loader = loader_for()
    loader.scan()
    run(loader.set_online("wid", True))

    run(loader.set_online("wid", False))

    assert tool_names(mcp) == set()
    assert json.loads((tmp_path / "config_capabilities.json").read_text()) == {"wid": {"enabled": False}}
    assert loader.record_for("wid").loaded is True  # still captured, so the tools stay listable


def test_startup_loads_configured_folders_and_applies_offline(loader_for, package, mcp, tmp_path):
    _, root = package
    write_capability(root, "widgets", "wid", "tool_wid_run")
    write_capability(root, "gadgets", "gad", "tool_gad_run")
    (tmp_path / "config_capabilities.json").write_text(json.dumps({"gad": {"enabled": False}}))
    loader = loader_for()

    loader.startup()

    assert loader.record_for("wid").loaded is True  # migrated to enabled
    assert capability_registry.is_enabled("wid") is True
    assert loader.record_for("gad").loaded is True  # imported, so its tools stay listed
    assert capability_registry.is_enabled("gad") is False
    assert "tool_gad_run" not in tool_names(mcp)


def test_startup_leaves_a_folder_added_after_the_migration_offline(loader_for, package, tmp_path):
    _, root = package
    write_capability(root, "widgets", "wid", "tool_wid_run")
    loader = loader_for()
    loader.startup()

    write_capability(root, "gadgets", "gad", "tool_gad_run")
    second = loader_for()
    second._records.clear()
    for key in [key for key in sys.modules if key.endswith("capabilities.gadgets")]:
        del sys.modules[key]
    capability_registry._REGISTRY.clear()
    capability_meta._BY_FOLDER.clear()
    second.startup()

    assert second.record_for("gad").loaded is False
    assert capability_registry.is_enabled("gad") is False


def test_concurrent_toggles_do_not_interleave(loader_for, package, mcp):
    _, root = package
    write_capability(root, "widgets", "wid", "tool_wid_run")
    loader = loader_for()
    loader.scan()

    async def hammer():
        await asyncio.gather(*(loader.set_online("wid", True) for _ in range(5)), loader.set_online("wid", False))

    run(hammer())

    assert len(commands.all_commands()) == 1
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv_mcp/Scripts/python.exe -m pytest tests/test_capability_loader.py -q`
Expected: FAIL (`ModuleNotFoundError: src.services.capability_loader`)

- [ ] **Step 3: Implement** `apps/mcp_server/src/services/capability_loader.py`

```python
"""Finds capability folders and brings them online, offline, or back after an edit.

``run.py`` used to import each capability by hand at startup, so a new
capability needed a restart. The loader replaces that: it lists the folders
of ``src/capabilities/``, reads each package's ``META`` (id and label), and
loads the ones the config says to. ``POST /capabilities/refresh`` runs the
same scan on the live server, so a folder dropped in while it runs appears.

Going online always imports the capability fresh: its old state is removed
(tools, resource templates, ``@command`` entries, ``META``), every module
under its folder is purged from ``sys.modules``, and the package is imported
again inside ``capability_registry.capturing()``. ``importlib.reload`` would
miss submodules such as ``domain.py``. Only the capability's own folder is
purged; a shared ``src.services`` module edited meanwhile is not reloaded.

Everything runs on the event-loop thread under one lock. The decorators in a
capability's ``tool.py`` mutate ``mcp``'s tool dict, and a worker thread
would race the loop that lists tools. An import takes milliseconds.

A failed import rolls back to offline and keeps the error text in the
record, so one broken capability never takes the server or its siblings down.
"""

from __future__ import annotations

import asyncio
import importlib
import logging
import pkgutil
import sys
import traceback
from dataclasses import dataclass
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.tools import tool_manager

from src import commands
from src.services import capability_meta, capability_registry
from src.services.app_config import (
    capability_enabled,
    load_capabilities_config,
    migrate_capabilities_config,
    save_capabilities_config,
)

logger = logging.getLogger(__name__)

# How much of a traceback is kept for the admin app to show.
TRACEBACK_LINES = 20
_DUPLICATE_PREFIX = "Tool already exists: "


class CapabilityError(Exception):
    """A capability request that cannot be done; ``status`` is the HTTP code."""

    status = 400


class UnknownCapability(CapabilityError):
    status = 404


class CapabilityLoadError(CapabilityError):
    status = 409


@dataclass
class CapabilityRecord:
    folder: str
    id: str
    label: str
    # True once tool.py was imported and captured (even while switched off).
    loaded: bool = False
    # The folder no longer exists on disk.
    missing: bool = False
    load_error: str | None = None


class _DuplicateToolWatcher(logging.Handler):
    """FastMCP does not raise for a second tool of the same name: it logs a
    warning and keeps the first. This catches that warning during an import."""

    def __init__(self) -> None:
        super().__init__(logging.WARNING)
        self.names: set[str] = set()

    def emit(self, record: logging.LogRecord) -> None:
        message = record.getMessage()
        if message.startswith(_DUPLICATE_PREFIX):
            self.names.add(message[len(_DUPLICATE_PREFIX):])


def _short_error(error: BaseException) -> str:
    lines = "".join(traceback.format_exception(error)).strip().splitlines()
    return "\n".join(lines[-TRACEBACK_LINES:])


class CapabilityLoader:
    def __init__(self, mcp: FastMCP, package: str, config_path: Path) -> None:
        self._mcp = mcp
        self._package = package
        self._config_path = config_path
        self._records: dict[str, CapabilityRecord] = {}  # by folder
        self._lock = asyncio.Lock()

    # --- reading -------------------------------------------------------------

    def records(self) -> list[CapabilityRecord]:
        return sorted(self._records.values(), key=lambda record: record.id)

    def record_for(self, name: str) -> CapabilityRecord | None:
        return next((record for record in self._records.values() if record.id == name), None)

    # --- discovery -----------------------------------------------------------

    def scan(self) -> None:
        """Find folders; read each new one's META without importing its tools."""
        importlib.invalidate_caches()
        package = importlib.import_module(self._package)
        found = {m.name for m in pkgutil.iter_modules(package.__path__) if m.ispkg and not m.name.startswith("_")}
        for folder in sorted(found - self._records.keys()):
            self._records[folder] = self._discover(folder)
        for folder, record in self._records.items():
            record.missing = folder not in found

    def _discover(self, folder: str) -> CapabilityRecord:
        try:
            meta = importlib.import_module(f"{self._package}.{folder}").META
            capability_registry.register_unloaded(meta.id, meta.label)
        except Exception as error:  # noqa: BLE001 - one bad folder must not stop the scan
            logger.warning("Capability folder %r cannot be read: %s", folder, error)
            return CapabilityRecord(folder, folder, folder, load_error=_short_error(error))
        return CapabilityRecord(folder, meta.id, meta.label)

    def startup(self) -> None:
        """Scan, migrate the config once, then load every folder that has an
        entry; a folder with ``enabled: false`` is imported and then switched off
        (its tools stay listed). A folder with no entry stays unloaded."""
        self.scan()
        ids = [record.id for record in self._records.values() if record.load_error is None]
        migrate_capabilities_config(self._config_path, ids)
        config = load_capabilities_config(self._config_path)
        for record in self._records.values():
            if record.load_error is not None or record.id not in config:
                continue
            try:
                self._load(record)
            except CapabilityLoadError as error:
                logger.warning("Capability %r did not load: %s", record.id, error)
                continue
            if not capability_enabled(config, record.id):
                capability_registry.set_enabled(self._mcp, record.id, False)

    async def refresh(self) -> None:
        async with self._lock:
            self.scan()

    # --- switching -----------------------------------------------------------

    async def set_online(self, name: str, online: bool) -> None:
        """Online: fresh import, then persist (a failed import changes nothing
        on disk). Offline: persist, then hide the tools. A capability that was
        registered outside the scanner is only toggled, not reloaded."""
        async with self._lock:
            record = self.record_for(name)
            if record is None:
                if name not in capability_registry.names():
                    raise UnknownCapability(f"Unknown capability {name!r}")
                save_capabilities_config(self._config_path, name, online)
                capability_registry.set_enabled(self._mcp, name, online)
                return
            if not online:
                save_capabilities_config(self._config_path, record.id, False)
                if record.loaded:
                    capability_registry.set_enabled(self._mcp, record.id, False)
                return
            if record.missing:
                raise CapabilityLoadError(f"The folder of capability {name!r} no longer exists")
            self._load(record)
            try:
                save_capabilities_config(self._config_path, record.id, True)
            except Exception:
                capability_registry.set_enabled(self._mcp, record.id, False)
                raise

    # --- loading -------------------------------------------------------------

    def _load(self, record: CapabilityRecord) -> None:
        self._unload(record)
        self._purge(record.folder)
        tools_before = set(self._mcp._tool_manager._tools)
        templates_before = set(self._mcp._resource_manager._templates)
        watcher = _DuplicateToolWatcher()
        tool_manager.logger.addHandler(watcher)
        capability_id, label = record.id, record.label
        try:
            meta = importlib.import_module(f"{self._package}.{record.folder}").META
            capability_id, label = meta.id, meta.label
            with capability_registry.capturing(self._mcp, meta.id, label=meta.label):
                importlib.import_module(f"{self._package}.{record.folder}.tool")
            if watcher.names:
                raise CapabilityLoadError(
                    f"Tool name already used by another capability: {', '.join(sorted(watcher.names))}"
                )
        except Exception as error:
            self._roll_back(capability_id, label, tools_before, templates_before)
            record.id, record.label, record.loaded = capability_id, label, False
            record.load_error = str(error) if isinstance(error, CapabilityLoadError) else _short_error(error)
            if isinstance(error, CapabilityLoadError):
                raise
            raise CapabilityLoadError(record.load_error) from error
        finally:
            tool_manager.logger.removeHandler(watcher)
        record.id, record.label, record.loaded, record.load_error = meta.id, meta.label, True, None

    def _unload(self, record: CapabilityRecord) -> None:
        capability_registry.discard(self._mcp, record.id)
        commands.remove_capability(record.id)
        capability_meta.unregister(record.folder)
        record.loaded = False

    def _purge(self, folder: str) -> None:
        prefix = f"{self._package}.{folder}"
        for name in [name for name in sys.modules if name == prefix or name.startswith(prefix + ".")]:
            del sys.modules[name]
        importlib.invalidate_caches()

    def _roll_back(self, capability_id: str, label: str, tools_before: set[str], templates_before: set[str]) -> None:
        """Undo a failed import: whatever it half-registered goes, and the
        capability stays listed as an offline handle with no tools."""
        capability_registry.discard(self._mcp, capability_id)
        for name in set(self._mcp._tool_manager._tools) - tools_before:
            self._mcp.remove_tool(name)
        for uri in set(self._mcp._resource_manager._templates) - templates_before:
            self._mcp._resource_manager._templates.pop(uri, None)
        commands.remove_capability(capability_id)
        capability_registry.register_unloaded(capability_id, label)
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv_mcp/Scripts/python.exe -m pytest tests/test_capability_loader.py -q`
Expected: PASS (13 tests). `test_startup_leaves_a_folder_added_after_the_migration_offline` simulates a restart by building a second loader after clearing the three registries and the new folder's `sys.modules` entries; keep that shape. Do not weaken the other tests.

- [ ] **Step 5: Commit**

```bash
cd /d/User/Documents/Programming/Python/MCPServer
git add apps/mcp_server/src/services/capability_loader.py apps/mcp_server/tests/test_capability_loader.py
git commit -m "feat(mcp_server): capability loader that scans folders and reloads on online"
```

---

### Task 4: Routes and startup wiring

**Files:**
- Modify: `apps/mcp_server/src/capability_routes.py`
- Modify: `apps/mcp_server/src/run.py` (lines 29-100 and the `install_capability_routes` / watchers lines in `_serve`)
- Modify: `apps/mcp_server/tests/test_capability_routes.py`
- Modify: `apps/mcp_server/configs/config_capabilities.json.example` (no change needed: left as is)

**Interfaces:**
- Consumes (Task 3): `CapabilityLoader`, `CapabilityError`
- Produces: `install_capability_routes(app: Starlette, loader: CapabilityLoader) -> None`
- Produces: `GET /capabilities` entries gain `load_error: str | None`, `missing: bool`, `loaded: bool`
- Produces: `POST /capabilities/refresh` returns the same list as `GET /capabilities`
- Produces: `PATCH /capabilities/{name}` returns 409 `{"error": "<message>"}` when going online fails

- [ ] **Step 1: Update and add tests** in `tests/test_capability_routes.py`

1. Change the `client` fixture to build a loader and pass it:

```python
from src.services.capability_loader import CapabilityLoader  # add to imports


@pytest.fixture
def client(test_mcp, config_path, monkeypatch):
    monkeypatch.setattr("src.capability_routes.mcp", test_mcp)  # remove this line if `mcp` is no longer imported by the module

    loader = CapabilityLoader(test_mcp, "src.capabilities", config_path)
    app = Starlette()
    install_capability_routes(app, loader)
    with TestClient(app) as test_client:
        yield test_client
```

(Drop the `settings`/`replace(config.settings, ...)` patching: the loader now holds the config path. Remove the unused `config` and `replace` imports only if nothing else in the file uses them.)

2. Everywhere the file compares a status dict, add the three new fields. For a registry-only capability (registered through `capturing`, no folder record) the values are `"load_error": None, "missing": False, "loaded": True`. Example for the GET test:

```python
assert response.json() == [
    {"name": "gadgets", "enabled": True, "label": "gadgets", "tools": ["make_gadget"], "resources": [], "has_gui": False,
     "load_error": None, "missing": False, "loaded": True},
    {"name": "widgets", "enabled": True, "label": "widgets", "tools": ["make_widget"], "resources": [], "has_gui": False,
     "load_error": None, "missing": False, "loaded": True},
]
```

Do the same for the two PATCH tests that compare a full body (the disabled one keeps `"enabled": False`).

3. Add:

```python
def test_refresh_returns_the_capability_list(client):
    response = client.post("/capabilities/refresh")

    assert response.status_code == 200
    assert [entry["name"] for entry in response.json()] == ["gadgets", "widgets"]


def test_patch_online_that_fails_to_load_is_409_with_the_message(test_mcp, config_path, tmp_path, monkeypatch):
    loader = CapabilityLoader(test_mcp, "src.capabilities", config_path)

    async def refuse(name, online):
        from src.services.capability_loader import CapabilityLoadError

        raise CapabilityLoadError("boom")

    monkeypatch.setattr(loader, "set_online", refuse)
    app = Starlette()
    install_capability_routes(app, loader)
    with TestClient(app) as test_client:
        response = test_client.patch("/capabilities/widgets", json={"enabled": True})

    assert response.status_code == 409
    assert response.json() == {"error": "boom"}


def test_get_lists_a_discovered_but_unloaded_capability(test_mcp, config_path):
    from src.services import capability_registry
    from src.services.capability_loader import CapabilityRecord

    loader = CapabilityLoader(test_mcp, "src.capabilities", config_path)
    capability_registry.register_unloaded("fresh", "Fresh")
    loader._records["fresh"] = CapabilityRecord("fresh", "fresh", "Fresh")
    app = Starlette()
    install_capability_routes(app, loader)
    with TestClient(app) as test_client:
        entry = next(e for e in test_client.get("/capabilities").json() if e["name"] == "fresh")

    assert entry == {"name": "fresh", "enabled": False, "label": "Fresh", "tools": [], "resources": [], "has_gui": False,
                     "load_error": None, "missing": False, "loaded": False}
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv_mcp/Scripts/python.exe -m pytest tests/test_capability_routes.py -q`
Expected: FAIL (`install_capability_routes() takes 1 positional argument`)

- [ ] **Step 3: Implement** `capability_routes.py`

Replace the imports and the body from `_status_json` down with:

```python
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse

from src import capability_gui
from src.services import capability_registry
from src.services.capability_loader import CapabilityError, CapabilityLoader


def _status_json(loader: CapabilityLoader, name: str) -> dict[str, object]:
    record = loader.record_for(name)
    known = name in capability_registry.names()
    return {
        "name": name,
        "enabled": known and capability_registry.is_enabled(name),
        "label": capability_registry.label(name) if known else record.label,
        "tools": capability_registry.tool_names(name) if known else [],
        "resources": capability_registry.resource_names(name) if known else [],
        # True only when a valid page exists and the capability is on, so a link never leads to a 404.
        "has_gui": known and capability_gui.load_page(name) is not None,
        "load_error": record.load_error if record else None,
        "missing": record.missing if record else False,
        "loaded": record.loaded if record else known,
    }


def _all_names(loader: CapabilityLoader) -> list[str]:
    return sorted(set(capability_registry.names()) | {record.id for record in loader.records()})


def _list(loader: CapabilityLoader) -> JSONResponse:
    return JSONResponse([_status_json(loader, name) for name in _all_names(loader)])


def install_capability_routes(app: Starlette, loader: CapabilityLoader) -> None:
    """Add the capability status/toggle/refresh routes to an existing Starlette app."""

    async def list_capabilities(request: Request) -> JSONResponse:
        return _list(loader)

    async def refresh_capabilities(request: Request) -> JSONResponse:
        await loader.refresh()
        return _list(loader)

    async def capability_gui_page(request: Request) -> JSONResponse:
        name = request.path_params["name"]
        if name not in capability_registry.names():
            return JSONResponse({"error": f"Unknown capability {name!r}"}, status_code=404)
        page = capability_gui.load_page(name)
        if page is None:
            return JSONResponse({"error": f"Capability {name!r} has no page"}, status_code=404)
        return JSONResponse(page.model_dump(mode="json", exclude_none=True))

    async def update_capability(request: Request) -> JSONResponse:
        name = request.path_params["name"]
        if name not in _all_names(loader):
            return JSONResponse({"error": f"Unknown capability {name!r}"}, status_code=404)
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001 - malformed JSON is a 400, not a 500
            return JSONResponse({"error": "Request body must be valid JSON"}, status_code=400)
        if not isinstance(body, dict) or not isinstance(body.get("enabled"), bool):
            return JSONResponse({"error": "'enabled' (a boolean) is required"}, status_code=400)
        try:
            await loader.set_online(name, body["enabled"])
        except CapabilityError as error:
            return JSONResponse({"error": str(error)}, status_code=error.status)
        return JSONResponse(_status_json(loader, name))

    app.add_route("/capabilities", list_capabilities, methods=["GET"])
    app.add_route("/capabilities/refresh", refresh_capabilities, methods=["POST"])
    app.add_route("/capabilities/{name}/gui", capability_gui_page, methods=["GET"])
    app.add_route("/capabilities/{name}", update_capability, methods=["PATCH"])
```

Update the module docstring: mention `POST /capabilities/refresh`, the `load_error` / `missing` / `loaded` fields, the 409 on a failed online, and that going online re-imports the capability. Keep the "Persist-then-apply" paragraph but say it applies to going offline; going online applies first and persists after.

Then `run.py`: replace lines 29-100 (everything from `_capabilities_config = load_capabilities_config(...)` through the `for _name in capability_registry.names(): ... set_enabled(...)` loop, including the long comment and the eight `capturing` blocks) with:

```python
# Capabilities are found by scanning src/capabilities/ (services/capability_loader.py),
# not imported by hand here: a folder added later appears on POST /capabilities/refresh
# with no restart. Each folder's __init__.py declares its id and label (META); one
# with a config entry is loaded now, one without stays offline until an admin brings it online.
capability_loader = CapabilityLoader(mcp, "src.capabilities", settings.capabilities_config_path)
capability_loader.startup()
```

Fix the imports at the top of `run.py`: remove `from src.services.app_config import capability_enabled, load_capabilities_config`; add `from src.services.capability_loader import CapabilityLoader  # noqa: E402` (keep `capability_registry`, still used by the banner).

In `_serve()`:
- change `install_capability_routes(app)` to `install_capability_routes(app, capability_loader)`;
- replace the watchers resume block:

```python
        # Restart the watchers that were running when the server last stopped.
        if "watch" in capability_registry.names() and capability_registry.is_enabled("watch"):
            from src.capabilities.watchers.utils.user_watcher import UserWatcher

            UserWatcher.resume_all(settings.watchers_dir)
```

(The `watchers` import that used `watchers.META.id` is gone, so the id is the literal `"watch"` from `capabilities/watchers/__init__.py`.)

Also update the comment above `install_capability_routes(app, ...)` to mention refresh.

- [ ] **Step 4: Run the whole mcp_server suite**

Run: `.venv_mcp/Scripts/python.exe -m pytest -q`
Expected: PASS (531 before, plus the new tests; any failure in `test_capability_gui.py` / `test_command_routes.py` that monkeypatches `capability_routes.mcp` means a leftover `mcp` import is needed: re-add `from src.server import mcp` only if a test still patches it).

- [ ] **Step 5: Smoke test startup against the real folders**

Run (from `apps/mcp_server`): `.venv_mcp/Scripts/python.exe -c "from src.server import mcp; from src.services.capability_loader import CapabilityLoader; from pathlib import Path; import tempfile; p=Path(tempfile.mkdtemp())/'c.json'; l=CapabilityLoader(mcp,'src.capabilities',p); l.startup(); print([(r.id, r.loaded, r.load_error) for r in l.records()])"`
Expected: nine records (`data`, `firecrawl`'s id, `gen`, `repo`, `scrape`, `server`, `usage`, `vault`, `watch`, `web`; match the real folders), all `loaded True`, all `None` errors. If a capability needs a `.env` value to import, its record shows the error: fix by reading the message, not by hiding it.

- [ ] **Step 6: Commit**

```bash
cd /d/User/Documents/Programming/Python/MCPServer
git add apps/mcp_server
git commit -m "feat(mcp_server): scanner-driven startup, reload on online, POST /capabilities/refresh"
```

---

## Part B: ember_api

### Task 5: Proxy the refresh route and the new status fields

**Files:**
- Modify: `apps/ember_api/src/services/mcp_server_info.py` (after `set_capability`)
- Modify: `apps/ember_api/src/routes/server_info.py` (`CapabilityOut`, new route after `switch_capability`)
- Modify: `apps/ember_api/tests/test_server_info.py`

**Interfaces:**
- Consumes (Task 4): mcp_server `POST /capabilities/refresh` returns a list of status dicts
- Produces: `McpServerInfo.refresh_capabilities(account: Account) -> list[dict[str, Any]]`
- Produces: `POST /api/capabilities/refresh` (permission `admin.manage`) returns `list[CapabilityOut]`; writes an activity-log entry `mcp.capability_refresh` with message `"Refreshed capabilities"`
- Produces: `CapabilityOut` gains `load_error: str | None = None`, `missing: bool = False`, `loaded: bool = True`

- [ ] **Step 1: Write the failing tests** (append to `tests/test_server_info.py`)

In the `mcp_server` fake handler (above), add before the final `return`:

```python
    if path == "/capabilities/refresh" and request.method == "POST":
        return httpx.Response(200, json=[
            *CAPABILITIES,
            {"name": "fresh", "enabled": False, "label": "Fresh", "tools": [], "resources": [], "has_gui": False,
             "load_error": None, "missing": False, "loaded": False},
        ])
```

(Place it above the existing `/capabilities/server_manager` branches so the path match is unambiguous.)

Then add tests:

```python
def test_capabilities_refresh_is_admin_only_and_logged(client_factory, email: FakeEmailSender, upstream: FakeUpstream) -> None:
    upstream.handler = mcp_server
    admin = as_admin(client_factory())

    refreshed = admin.post("/api/capabilities/refresh")

    assert refreshed.status_code == 200, refreshed.text
    assert [c["name"] for c in refreshed.json()] == ["server_manager", "fresh"]
    assert refreshed.json()[1]["loaded"] is False
    assert upstream.requests[-1].method == "POST" and upstream.requests[-1].url.path == "/capabilities/refresh"
    messages = [entry["message"] for entry in admin.get("/api/logs/action").json()]
    assert "Refreshed capabilities" in messages

    member = client_factory()
    make_member(member, email)
    login(member, "alice")
    assert member.post("/api/capabilities/refresh").status_code == 403


def test_capability_status_carries_the_load_error(client_factory, upstream: FakeUpstream) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/capabilities":
            return httpx.Response(200, json=[{**CAPABILITIES[0], "enabled": False, "load_error": "boom", "loaded": False}])
        return mcp_server(request)

    upstream.handler = handler
    admin = as_admin(client_factory())

    entry = admin.get("/api/capabilities").json()[0]

    assert (entry["load_error"], entry["loaded"], entry["missing"]) == ("boom", False, False)
```

(Check `/api/logs/action` returns a list of entries with `message`, as the existing extension test at the bottom of the file does with `params={"actor": ...}`; reuse its exact call shape if the unparameterized call is not accepted.)

- [ ] **Step 2: Run to verify they fail**

Run (from `apps/ember_api`, with its venv, as `run.bat` sets up; the venv python is in that folder): `python -m pytest tests/test_server_info.py -q`
Expected: FAIL (404 for `/api/capabilities/refresh`; missing `load_error` key)

- [ ] **Step 3: Implement**

`mcp_server_info.py`, after `set_capability`:

```python
    async def refresh_capabilities(self, account: Account) -> list[dict[str, Any]]:
        """mcp_server scans its capabilities folder again; returns the new list."""
        body = await self._request("POST", "/capabilities/refresh", account)
        return body if isinstance(body, list) else []
```

`server_info.py`: in `CapabilityOut`, after `has_gui`:

```python
    # Why the capability could not be brought online (a trimmed traceback), else null.
    load_error: str | None = None
    # Its folder is gone from mcp_server's disk.
    missing: bool = False
    # Its tools were imported (true even while switched off); false for a folder only discovered.
    loaded: bool = True
```

and after `switch_capability`:

```python
@router.post("/capabilities/refresh")
async def refresh_capabilities(
    account: Account = Depends(require_admin),
    info: McpServerInfo = Depends(get_server_info),
    logs: LogWriter = Depends(get_log_writer),
) -> list[CapabilityOut]:
    """mcp_server looks for capability folders added while it runs; a new one
    is listed offline. Admins only, like switching."""
    capabilities = [CapabilityOut(**r) for r in await _call(info.refresh_capabilities(account)) if isinstance(r, dict)]
    await logs.action(account, "mcp.capability_refresh", "Refreshed capabilities")
    return capabilities
```

Update the module docstring's sentence on switching to mention that going online reloads the capability's code and that refresh needs `admin.manage`.

- [ ] **Step 4: Run to verify they pass, then the suite**

Run: `python -m pytest tests/test_server_info.py -q` then `python -m pytest -q`
Expected: PASS (839 before, plus new)

- [ ] **Step 5: Commit**

```bash
cd /d/User/Documents/Programming/Python/MCPServer
git add apps/ember_api
git commit -m "feat(ember_api): proxy capability refresh and the load_error/missing/loaded fields"
```

---

## Part C: ember_admin

Skills to follow: `ember-design-system` (tokens, radius, pill controls) and `ember-feature-scaffold` (ember_api conventions). Memory: the user tests UI manually; do not spawn browser verification. Build checks are `npx vue-tsc -b`, `npm test`, `npm run test:e2e`.

### Task 6: Scaffold the project and copy the Admin and Analytics pages

**Files:** everything under `apps/ember_admin/` listed in File Structure, except the two new views and their client.

**Interfaces:**
- Produces: `apps/ember_admin` that builds, serves on `EMBER_ADMIN_PORT` (default 5175), logs in against `ember_api`, and shows Admin and Analytics. A nav component `AdminNav.vue` listing pages by permission.
- Produces (`src/router/pages.ts`): `LOG_PERMISSIONS: string[]`, `ANALYTICS_PERMISSIONS: string[]`, `ADMIN_PAGES: AdminPage[]` with `AdminPage = { to: string; label: string; icon: string[]; permission: string | string[] }`

- [ ] **Step 1: Copy the files**

Run from `D:/User/Documents/Programming/Python/MCPServer/apps` (Git Bash). The list is the import closure of `AdminView`, `AnalyticsView`, `auth` store, `LoginView`, `NoAccessView`, `style.css`; each file's `.test.ts` is copied if it exists.

```bash
cd /d/User/Documents/Programming/Python/MCPServer/apps
SRC=ember_web/src; DST=ember_admin/src
mkdir -p ember_admin/public "$DST"
FILES="
api/AdminClient.ts api/AuthClient.ts api/LogsClient.ts api/SettingsClient.ts api/TrafficClient.ts api/http.ts
api/ExtensionsClient.ts api/CommandsClient.ts api/AttachmentsClient.ts
components/AuthCard.vue components/BaseModal.vue components/CopyButton.vue components/DeleteButton.vue
components/LockSwitch.vue components/LogEntries.vue components/SegmentedControl.vue components/ToggleSwitch.vue
components/infoPage.css
components/admin/AccountDrawer.vue components/admin/AccountsPanel.vue components/admin/ConfirmModal.vue
components/admin/InvitesPanel.vue components/admin/RoleEditor.vue components/admin/RolesPanel.vue
components/admin/SettingsPanel.vue components/admin/StatTile.vue components/admin/admin.css
components/analytics/ActivityChart.vue components/analytics/BarList.vue components/analytics/HourHeatmap.vue
components/analytics/KindStatTile.vue components/analytics/LineChart.vue components/analytics/Sparkline.vue
components/analytics/StatTile.vue components/analytics/TrafficPanel.vue components/analytics/useBucketCursor.ts
router/redirect.ts stores/auth.ts style.css
utils/clipboard.ts utils/errors.ts utils/logAnalytics.ts utils/trafficAnalytics.ts
views/AdminView.vue views/AnalyticsView.vue views/LoginView.vue views/NoAccessView.vue
radiusScale.test.ts
"
for f in $FILES; do
  mkdir -p "$DST/$(dirname "$f")"; cp "$SRC/$f" "$DST/$f"
  t="${f%.*}.test.ts"; [ -f "$SRC/$t" ] && cp "$SRC/$t" "$DST/$t"
done
cp ember_web/public/favicon.svg ember_admin/public/
cp ember_web/tsconfig.json ember_web/tsconfig.app.json ember_web/tsconfig.node.json ember_web/index.html ember_admin/
```

`CommandsClient.ts` imports `AttachmentsClient.ts` (already in the list); `CapabilityInfo` is extended in Task 7. If a copied file imports something not in `$DST`, `vue-tsc` (Step 6) names it: copy that file the same way. Do not copy `ember_web`'s `router/pages.ts`, `App.vue`, `main.ts`, or router: they are written below.

- [ ] **Step 2: Write `package.json`, `vite.config.ts`, `run.bat`**

`apps/ember_admin/package.json` (same dependency versions as `ember_web`, minus `@modelcontextprotocol/sdk`, `dompurify`, `markdown-it`, `@types/markdown-it`; add them back only if `vue-tsc` shows a copied file needs them):

```json
{
  "name": "ember_admin",
  "private": true,
  "version": "0.0.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "vue-tsc -b && vite build",
    "preview": "vite preview",
    "test": "vitest run",
    "test:e2e": "playwright test"
  },
  "dependencies": {
    "pinia": "^4.0.3",
    "vue": "^3.5.42",
    "vue-router": "^5.3.1"
  },
  "devDependencies": {
    "@playwright/test": "^1.63.0",
    "@types/node": "^24.13.3",
    "@vitejs/plugin-vue": "^6.0.8",
    "@vue/test-utils": "^2.5.1",
    "@vue/tsconfig": "^0.9.1",
    "jsdom": "^29.1.1",
    "typescript": "~6.0.2",
    "vite": "^8.3.0",
    "vitest": "^5.0.2",
    "vue-tsc": "^3.3.11"
  }
}
```

`apps/ember_admin/vite.config.ts`: copy `ember_web/vite.config.ts` and change only the port line: `port: Number(process.env.EMBER_ADMIN_PORT ?? 5175),`, and the top comment's first sentence to "ember_admin: everything under /api goes to ember_api...". Keep the `apiProxy`, CSP, `cssTarget`, `test`, `server.host`, `preview` blocks unchanged.

`apps/ember_admin/run.bat`: copy `ember_web/run.bat`, replacing `ember_web` with `ember_admin`, `EMBER_WEB_PORT` with `EMBER_ADMIN_PORT`, `5173` with `5175`, and:

```
REM LABEL: Ember Admin
REM DESCRIPTION: Vue 3 + TypeScript admin app for ember: accounts, analytics, capabilities and extensions, through ember_api.
```

Edit `ember_admin/index.html`: set `<title>Ember Admin</title>`.

- [ ] **Step 3: Write `pages.ts`, router, `main.ts`, `App.vue`, `AdminNav.vue`**

`src/router/pages.ts`:

```ts
/** The pages of the admin app, in nav order, with the permission each needs
 * (a list: any one of them). One list, so the nav and the router cannot drift. */

// The Analytics page shows whichever log kinds these allow.
export const LOG_PERMISSIONS = ["logs.view", "logs.errors.view", "logs.chat.view"];
// ...and its Traffic tab needs traffic.view; any one of these opens the page.
export const ANALYTICS_PERMISSIONS = [...LOG_PERMISSIONS, "traffic.view"];

export interface AdminPage {
  to: string;
  label: string;
  /** SVG path data (24x24, stroked) drawn as the page's icon. */
  icon: string[];
  permission: string | string[];
}

export const ADMIN_PAGES: AdminPage[] = [
  { to: "/capabilities", label: "Capabilities", icon: ["m12.83 2.18a2 2 0 0 0-1.66 0L2.6 6.08a1 1 0 0 0 0 1.83l8.58 3.91a2 2 0 0 0 1.66 0l8.58-3.9a1 1 0 0 0 0-1.83z", "m22 17.65-9.17 4.16a2 2 0 0 1-1.66 0L2 17.65", "m22 12.65-9.17 4.16a2 2 0 0 1-1.66 0L2 12.65"], permission: "admin.manage" },
  { to: "/extensions", label: "Extensions", icon: ["M12 2v6", "M8 8h8v4a4 4 0 0 1-8 0z", "M12 16v6"], permission: ["admin.manage", "extensions.manage"] },
  { to: "/analytics", label: "Analytics", icon: ["M22 12h-4l-3 9L9 3l-3 9H2"], permission: ANALYTICS_PERMISSIONS },
  { to: "/admin", label: "Admin", icon: ["M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"], permission: "admin.manage" },
];
```

`src/router/index.ts`:

```ts
import { createRouter, createWebHistory, type RouteLocationRaw } from "vue-router";
import { useAuthStore } from "../stores/auth";
import { ADMIN_PAGES, ANALYTICS_PERMISSIONS } from "./pages";

declare module "vue-router" {
  interface RouteMeta {
    /** Reachable without logging in (login). */
    guestOnly?: boolean;
    /** The ember_api permission the page needs; a list = any one of them. */
    permission?: string | string[];
  }
}

function allowed(needed: string | string[], has: (p: string) => boolean): boolean {
  return Array.isArray(needed) ? needed.some(has) : has(needed);
}

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/", redirect: "/capabilities" },
    { path: "/capabilities", name: "capabilities", component: () => import("../views/CapabilitiesAdminView.vue"), meta: { permission: "admin.manage" } },
    { path: "/extensions", name: "extensions", component: () => import("../views/ExtensionsAdminView.vue"), meta: { permission: ["admin.manage", "extensions.manage"] } },
    { path: "/analytics", name: "analytics", component: () => import("../views/AnalyticsView.vue"), meta: { permission: ANALYTICS_PERMISSIONS } },
    { path: "/admin", name: "admin", component: () => import("../views/AdminView.vue"), meta: { permission: "admin.manage" } },
    { path: "/login", name: "login", component: () => import("../views/LoginView.vue"), meta: { guestOnly: true } },
    { path: "/no-access", name: "no-access", component: () => import("../views/NoAccessView.vue") },
    { path: "/:pathMatch(.*)*", redirect: "/" },
  ],
});

// ember_api enforces every permission itself; the guard keeps the UI from
// showing pages whose calls would be refused.
router.beforeEach(async (to): Promise<true | RouteLocationRaw> => {
  const auth = useAuthStore();
  await auth.ensureLoaded();
  if (!auth.account) {
    return to.meta.guestOnly ? true : { name: "login", query: to.fullPath === "/" ? {} : { redirect: to.fullPath } };
  }
  const home = ADMIN_PAGES.find((p) => allowed(p.permission, auth.hasPermission));
  if (to.meta.guestOnly) return { name: home ? routeName(home.to) : "no-access" };
  const needed = to.meta.permission;
  if (needed && !allowed(needed, auth.hasPermission)) return { name: home ? routeName(home.to) : "no-access" };
  if (to.name === "no-access" && home) return { name: routeName(home.to) };
  return true;
});

function routeName(path: string): string {
  return path.slice(1);
}
```

`src/main.ts`:

```ts
import { createApp } from "vue";
import { createPinia } from "pinia";
import "./style.css";
import App from "./App.vue";
import { router } from "./router";

createApp(App).use(createPinia()).use(router).mount("#app");
```

(`useTheme` is not copied: the page follows the system theme via `color-scheme: light dark` in `style.css`.)

`src/components/AdminNav.vue` (a left rail on wide screens, a bottom bar on narrow; follow `ember-design-system` tokens; radius only through `--radius-*`):

```vue
<script setup lang="ts">
import { computed } from "vue";
import { RouterLink, useRoute } from "vue-router";
import { useAuthStore } from "../stores/auth";
import { ADMIN_PAGES } from "../router/pages";

const auth = useAuthStore();
const route = useRoute();

const pages = computed(() =>
  ADMIN_PAGES.filter((p) => (Array.isArray(p.permission) ? p.permission.some(auth.hasPermission) : auth.hasPermission(p.permission))),
);
</script>

<template>
  <nav class="nav" aria-label="Admin sections">
    <RouterLink to="/" class="brand">Ember Admin</RouterLink>
    <RouterLink v-for="page in pages" :key="page.to" :to="page.to" class="item" :aria-current="route.path === page.to ? 'page' : undefined">
      <svg viewBox="0 0 24 24" aria-hidden="true"><path v-for="d in page.icon" :key="d" :d="d" /></svg>
      <span>{{ page.label }}</span>
    </RouterLink>
    <button v-if="auth.account" type="button" class="signout" @click="auth.logout()">Sign out</button>
  </nav>
</template>

<style scoped>
.nav {
  display: flex;
  flex-direction: column;
  gap: 4px;
  width: 200px;
  padding: 16px 12px;
  border-right: 1px solid var(--border);
  background: var(--surface);
}
.brand {
  margin-bottom: 12px;
  font-weight: 700;
  color: var(--accent);
  text-decoration: none;
}
.item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  border-radius: var(--radius-md);
  color: var(--text);
  text-decoration: none;
}
.item:hover {
  background: var(--bg);
}
.item[aria-current="page"] {
  color: var(--accent);
  background: var(--bg);
  font-weight: 600;
}
.item svg {
  width: 20px;
  height: 20px;
  fill: none;
  stroke: currentColor;
  stroke-width: 1.8;
  stroke-linecap: round;
  stroke-linejoin: round;
}
.signout {
  margin-top: auto;
  padding: 8px 10px;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: transparent;
  color: var(--muted);
  font: inherit;
  cursor: pointer;
}
:is(a, button):focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}
@media (max-width: 767px) {
  .nav {
    flex-direction: row;
    width: auto;
    overflow-x: auto;
    padding: 8px 12px;
    border-right: none;
    border-bottom: 1px solid var(--border);
  }
  .brand,
  .signout {
    display: none;
  }
}
</style>
```

`src/App.vue`:

```vue
<script setup lang="ts">
import { storeToRefs } from "pinia";
import { watch } from "vue";
import { RouterView, useRoute, useRouter } from "vue-router";
import AdminNav from "./components/AdminNav.vue";
import { useAuthStore } from "./stores/auth";

const auth = useAuthStore();
const { account } = storeToRefs(auth);
const route = useRoute();
const router = useRouter();

// The session can end mid-page (expired, or logged out elsewhere): any 401
// clears the account, and this sends the user back to the login page.
watch(account, (now) => {
  if (!now && !route.meta.guestOnly) void router.replace({ name: "login" });
});
</script>

<template>
  <div class="shell">
    <AdminNav v-if="account" />
    <main class="page"><RouterView :key="account?.id ?? 'guest'" /></main>
  </div>
</template>

<style scoped>
.shell {
  display: flex;
  flex: 1;
  min-height: 0;
}
.page {
  flex: 1;
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
@media (max-width: 767px) {
  .shell {
    flex-direction: column;
  }
}
</style>
```

Edit the copied `style.css`: first comment line "ember_web theme" becomes "ember_admin theme (same tokens as ember_web)".

Edit the copied `LoginView.vue` and `AuthCard.vue` only if `vue-tsc` fails: `LoginView` links to a `register` route that does not exist here. Remove the register `RouterLink` (and any "forgot"/"register" links) from `LoginView.vue`; admins are created through ember_web's invites.

- [ ] **Step 4: Install and type-check**

Run (from `apps/ember_admin`): `npm install` then `npx vue-tsc -b`
Expected: no errors. For each "Cannot find module" error, copy that file from `ember_web/src` the same way as Step 1 and repeat. Two views that do not exist yet (`CapabilitiesAdminView.vue`, `ExtensionsAdminView.vue`) are lazy imports; create empty placeholders that Tasks 7 and 8 replace:

```vue
<script setup lang="ts"></script>
<template><section class="info-page"><div class="column"><h2>Coming next</h2></div></section></template>
```

(Write the same stub to both files now so `vue-tsc` passes. Tasks 7 and 8 overwrite them fully.)

- [ ] **Step 5: Run the copied tests**

Run: `npm test`
Expected: PASS for the copied Admin, Analytics, admin components, chart components and `radiusScale.test.ts`. A copied test that imports a module you did not copy fails with the file name: copy it. A copied test that asserts ember_web-specific behavior (a nav link to a page that does not exist here) is edited minimally, not deleted.

- [ ] **Step 6: Commit**

```bash
cd /d/User/Documents/Programming/Python/MCPServer
git add apps/ember_admin
git commit -m "feat(ember_admin): scaffold the app with Admin and Analytics copied from ember_web"
```

(`node_modules` and `dist` stay out: check `apps/ember_admin/.gitignore` exists; if not, copy `ember_web/.gitignore`. `ember_web` is tracked in this repo's `.gitignore`; confirm with `git status --short` that no `node_modules` is staged.)

---

### Task 7: Capabilities page

**Files:**
- Create: `apps/ember_admin/src/api/CapabilitiesAdminClient.ts`
- Create: `apps/ember_admin/src/api/CapabilitiesAdminClient.test.ts`
- Overwrite: `apps/ember_admin/src/views/CapabilitiesAdminView.vue`
- Create: `apps/ember_admin/src/views/CapabilitiesAdminView.test.ts`

**Interfaces:**
- Consumes (Task 5): `GET /api/capabilities`, `PATCH /api/capabilities/{name}` (409 → thrown `ApiError` with the message), `POST /api/capabilities/refresh`
- Produces: `capabilitiesAdminClient.list() / .setOnline(name, online) / .refresh()`; type `CapabilityStatus`

- [ ] **Step 1: Write the failing client test**

`src/api/CapabilitiesAdminClient.test.ts`:

```ts
import { afterEach, describe, expect, it, vi } from "vitest";
import { capabilitiesAdminClient } from "./CapabilitiesAdminClient";

afterEach(() => vi.restoreAllMocks());

function stubFetch(status: number, body: unknown) {
  const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(body), { status }));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("capabilitiesAdminClient", () => {
  it("lists capabilities", async () => {
    stubFetch(200, [{ name: "vault", enabled: true }]);
    expect(await capabilitiesAdminClient.list()).toEqual([{ name: "vault", enabled: true }]);
  });

  it("switches one capability with PATCH", async () => {
    const fetchMock = stubFetch(200, { name: "vault", enabled: true });
    await capabilitiesAdminClient.setOnline("vault", true);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/capabilities/vault");
    expect(init.method).toBe("PATCH");
    expect(JSON.parse(init.body)).toEqual({ enabled: true });
  });

  it("refreshes with POST", async () => {
    const fetchMock = stubFetch(200, []);
    await capabilitiesAdminClient.refresh();
    expect(fetchMock.mock.calls[0][0]).toBe("/api/capabilities/refresh");
    expect(fetchMock.mock.calls[0][1].method).toBe("POST");
  });

  it("surfaces the server's message when going online fails", async () => {
    stubFetch(400, { detail: "boom" });
    await expect(capabilitiesAdminClient.setOnline("vault", true)).rejects.toThrow("boom");
  });
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `npx vitest run src/api/CapabilitiesAdminClient.test.ts`
Expected: FAIL (cannot resolve `./CapabilitiesAdminClient`)

- [ ] **Step 3: Implement the client**

`src/api/CapabilitiesAdminClient.ts`:

```ts
import { apiRequest } from "./http";
import type { CapabilityInfo } from "./CommandsClient";

/** A built-in mcp_server capability as the admin sees it: `enabled` is online,
 * `load_error` why it could not be brought online, `missing` its folder is
 * gone, `loaded` its tools were imported (false for a folder only discovered). */
export interface CapabilityStatus extends CapabilityInfo {
  load_error: string | null;
  missing: boolean;
  loaded: boolean;
}

const enc = encodeURIComponent;

/** ember_api's capability switchboard, for admins (admin.manage). Going online
 * re-imports the capability's code; refresh finds folders added while mcp_server runs. */
export const capabilitiesAdminClient = {
  list: () => apiRequest<CapabilityStatus[]>("GET", "/api/capabilities"),
  setOnline: (name: string, online: boolean) =>
    apiRequest<CapabilityStatus>("PATCH", `/api/capabilities/${enc(name)}`, { enabled: online }),
  refresh: () => apiRequest<CapabilityStatus[]>("POST", "/api/capabilities/refresh"),
};
```

- [ ] **Step 4: Run to verify it passes**

Run: `npx vitest run src/api/CapabilitiesAdminClient.test.ts`
Expected: PASS

- [ ] **Step 5: Write the failing view test**

`src/views/CapabilitiesAdminView.test.ts`:

```ts
import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { capabilitiesAdminClient, type CapabilityStatus } from "../api/CapabilitiesAdminClient";
import CapabilitiesAdminView from "./CapabilitiesAdminView.vue";

function cap(over: Partial<CapabilityStatus>): CapabilityStatus {
  return { name: "vault", enabled: true, label: "Vault", tools: ["tool_vault_search"], resources: [], has_gui: false, load_error: null, missing: false, loaded: true, ...over };
}

beforeEach(() => {
  vi.spyOn(capabilitiesAdminClient, "list").mockResolvedValue([
    cap({}),
    cap({ name: "fresh", label: "Fresh", enabled: false, loaded: false, tools: [] }),
    cap({ name: "broken", label: "Broken", enabled: false, load_error: "RuntimeError: boom" }),
    cap({ name: "gone", label: "Gone", enabled: false, missing: true }),
  ]);
});
afterEach(() => vi.restoreAllMocks());

async function mounted() {
  const wrapper = mount(CapabilitiesAdminView);
  await flushPromises();
  return wrapper;
}

describe("CapabilitiesAdminView", () => {
  it("shows each capability with its state", async () => {
    const wrapper = await mounted();
    const rows = wrapper.findAll("[data-test=capability]");
    expect(rows.map((r) => r.attributes("data-state"))).toEqual(["online", "new", "error", "missing"]);
  });

  it("shows the load error text on the row", async () => {
    const wrapper = await mounted();
    expect(wrapper.find("[data-name=broken] [data-test=load-error]").text()).toContain("RuntimeError: boom");
  });

  it("brings a capability online and waits for the server before showing it", async () => {
    const set = vi.spyOn(capabilitiesAdminClient, "setOnline").mockResolvedValue(cap({ name: "fresh", enabled: true, loaded: true }));
    const wrapper = await mounted();
    const toggle = wrapper.find("[data-name=fresh] input[type=checkbox]");

    await toggle.setValue(true);
    expect(set).toHaveBeenCalledWith("fresh", true);
    expect((toggle.element as HTMLInputElement).disabled).toBe(true); // pending
    await flushPromises();

    expect(wrapper.find("[data-name=fresh]").attributes("data-state")).toBe("online");
  });

  it("keeps a capability offline and shows the error when going online fails", async () => {
    vi.spyOn(capabilitiesAdminClient, "setOnline").mockRejectedValue(new Error("boom in tool.py"));
    const wrapper = await mounted();

    await wrapper.find("[data-name=fresh] input[type=checkbox]").setValue(true);
    await flushPromises();

    expect(wrapper.find("[data-name=fresh]").attributes("data-state")).not.toBe("online");
    expect(wrapper.find("[data-name=fresh] [data-test=row-error]").text()).toContain("boom in tool.py");
  });

  it("refresh reloads the list", async () => {
    const refresh = vi.spyOn(capabilitiesAdminClient, "refresh").mockResolvedValue([cap({}), cap({ name: "newest", label: "Newest", enabled: false, loaded: false })]);
    const wrapper = await mounted();

    await wrapper.find("[data-test=refresh]").trigger("click");
    await flushPromises();

    expect(refresh).toHaveBeenCalled();
    expect(wrapper.findAll("[data-test=capability]")).toHaveLength(2);
  });

  it("cannot bring a missing capability online", async () => {
    const wrapper = await mounted();
    expect((wrapper.find("[data-name=gone] input[type=checkbox]").element as HTMLInputElement).disabled).toBe(true);
  });
});
```

- [ ] **Step 6: Run to verify it fails**

Run: `npx vitest run src/views/CapabilitiesAdminView.test.ts`
Expected: FAIL (the stub view has no rows)

- [ ] **Step 7: Implement the view** (overwrite `src/views/CapabilitiesAdminView.vue`)

```vue
<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { capabilitiesAdminClient, type CapabilityStatus } from "../api/CapabilitiesAdminClient";
import ToggleSwitch from "../components/ToggleSwitch.vue";
import { errorMessage } from "../utils/errors";
import "../components/infoPage.css";

const capabilities = ref<CapabilityStatus[]>([]);
const loading = ref(true);
const error = ref("");
const refreshing = ref(false);
// A switch waits for the server's answer: the name is here while its call is in flight.
const pending = ref<Set<string>>(new Set());
const rowErrors = ref<Record<string, string>>({});

type State = "online" | "offline" | "new" | "error" | "missing";

function stateOf(c: CapabilityStatus): State {
  if (c.missing) return "missing";
  if (c.enabled) return "online";
  if (c.load_error) return "error";
  if (!c.loaded) return "new";
  return "offline";
}

const STATE_LABELS: Record<State, string> = {
  online: "Online",
  offline: "Offline",
  new: "New, offline",
  error: "Failed to load",
  missing: "Folder missing",
};

const rows = computed(() => capabilities.value.map((c) => ({ c, state: stateOf(c) })));

async function load(): Promise<void> {
  try {
    capabilities.value = await capabilitiesAdminClient.list();
    error.value = "";
  } catch (err) {
    error.value = errorMessage(err);
  } finally {
    loading.value = false;
  }
}

async function refresh(): Promise<void> {
  refreshing.value = true;
  try {
    capabilities.value = await capabilitiesAdminClient.refresh();
    error.value = "";
  } catch (err) {
    error.value = errorMessage(err);
  } finally {
    refreshing.value = false;
  }
}

async function setOnline(c: CapabilityStatus, online: boolean): Promise<void> {
  pending.value = new Set(pending.value).add(c.name);
  delete rowErrors.value[c.name];
  try {
    const updated = await capabilitiesAdminClient.setOnline(c.name, online);
    capabilities.value = capabilities.value.map((x) => (x.name === c.name ? updated : x));
  } catch (err) {
    rowErrors.value[c.name] = errorMessage(err);
    // The server rolled back; read the real state (and its load_error) again.
    await load();
  } finally {
    const next = new Set(pending.value);
    next.delete(c.name);
    pending.value = next;
  }
}

onMounted(load);
</script>

<template>
  <section class="info-page capabilities-admin">
    <div class="column">
      <header class="head">
        <div>
          <h2>Capabilities</h2>
          <p class="intro">
            Offline hides a capability's tools from every client. Going online loads its code from disk again, so edit
            while it is offline. Refresh finds capability folders added while mcp_server runs; they start offline.
          </p>
        </div>
        <button type="button" class="refresh" data-test="refresh" :disabled="refreshing" @click="refresh">
          {{ refreshing ? "Refreshing…" : "Refresh" }}
        </button>
      </header>
      <p v-if="error" class="error" role="alert">{{ error }}</p>
      <p v-if="loading" class="muted">Loading…</p>
      <ul v-else class="list">
        <li v-for="{ c, state } in rows" :key="c.name" class="card cap" data-test="capability" :data-name="c.name" :data-state="state">
          <div class="top">
            <div class="who">
              <strong>{{ c.label ?? c.name }}</strong>
              <code>{{ c.name }}</code>
              <span class="state" :class="state">{{ STATE_LABELS[state] }}</span>
            </div>
            <ToggleSwitch
              :checked="c.enabled"
              :disabled="pending.has(c.name) || c.missing"
              :aria-label="`${c.label ?? c.name} online`"
              @change="setOnline(c, ($event.target as HTMLInputElement).checked)"
            />
          </div>
          <p class="tools">{{ c.tools.length }} tool{{ c.tools.length === 1 ? "" : "s" }}<template v-if="!c.loaded"> · not loaded yet</template></p>
          <pre v-if="c.load_error" class="load-error" data-test="load-error">{{ c.load_error }}</pre>
          <p v-if="rowErrors[c.name]" class="error" role="alert" data-test="row-error">{{ rowErrors[c.name] }}</p>
        </li>
      </ul>
    </div>
  </section>
</template>

<style scoped>
.head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 14px;
}
.refresh {
  padding: 6px 16px;
  border: none;
  border-radius: var(--radius-full);
  cursor: pointer;
  font: inherit;
  font-weight: 600;
  color: var(--accent-contrast);
  background: var(--accent);
}
.refresh:disabled {
  opacity: 0.6;
  cursor: default;
}
.list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin: 0;
  padding: 0;
  list-style: none;
}
.top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.who {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}
.who code {
  color: var(--muted);
}
.state {
  padding: 1px 8px;
  border-radius: var(--radius-sm);
  font-size: 0.8em;
  background: var(--surface);
}
.state.online {
  color: var(--success);
}
.state.error,
.state.missing {
  color: var(--danger);
}
.tools {
  margin: 6px 0 0;
  font-size: 0.9em;
  color: var(--muted);
}
.load-error {
  margin: 8px 0 0;
  padding: 8px 10px;
  max-height: 220px;
  overflow: auto;
  border-radius: var(--radius-md);
  background: var(--code-bg);
  font: 0.8em/1.4 var(--mono);
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
.error {
  color: var(--danger);
}
.muted {
  color: var(--muted);
}
</style>
```

(`.card` styling comes from `infoPage.css`. `errorMessage` is in the copied `utils/errors.ts`.)

- [ ] **Step 8: Run to verify they pass, then type-check**

Run: `npx vitest run src/views/CapabilitiesAdminView.test.ts src/api/CapabilitiesAdminClient.test.ts` then `npx vue-tsc -b`
Expected: PASS, no type errors. If the toggle test cannot find `input[type=checkbox]`, the `ToggleSwitch` forwards attributes to its inner input (`inheritAttrs: false` + `v-bind="$attrs"`), so `:checked` / `:disabled` / `@change` reach it as intended: check the selector, not the component.

- [ ] **Step 9: Commit**

```bash
cd /d/User/Documents/Programming/Python/MCPServer
git add apps/ember_admin
git commit -m "feat(ember_admin): Capabilities page with online/offline, refresh and load errors"
```

---

### Task 8: Extensions page

**Files:**
- Overwrite: `apps/ember_admin/src/views/ExtensionsAdminView.vue`
- Create: `apps/ember_admin/src/views/ExtensionsAdminView.test.ts`

**Interfaces:**
- Consumes: `extensionsClient` (copied `src/api/ExtensionsClient.ts`: `list()`, `add({label,url,description})`, `remove(id)`), `ConfirmModal` props `open, title, message, confirmLabel, danger, busy` and events `confirm`, `close`

- [ ] **Step 1: Write the failing test**

`src/views/ExtensionsAdminView.test.ts`:

```ts
import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { extensionsClient, type ExtensionInfo } from "../api/ExtensionsClient";
import ExtensionsAdminView from "./ExtensionsAdminView.vue";

const NOTES: ExtensionInfo = { id: "notes", label: "Notes", description: "", status: "connected", error: null, tools: ["notes__add"], web_url: null };
const WIKI: ExtensionInfo = { id: "wiki", label: "Wiki", description: "", status: "error", error: "connection refused", tools: [] };

beforeEach(() => {
  vi.spyOn(extensionsClient, "list").mockResolvedValue([NOTES, WIKI]);
});
afterEach(() => vi.restoreAllMocks());

async function mounted() {
  const wrapper = mount(ExtensionsAdminView, { attachTo: document.body });
  await flushPromises();
  return wrapper;
}

describe("ExtensionsAdminView", () => {
  it("lists extensions with their status and error", async () => {
    const wrapper = await mounted();
    expect(wrapper.findAll("[data-test=extension]")).toHaveLength(2);
    expect(wrapper.find("[data-id=wiki]").text()).toContain("connection refused");
  });

  it("adds an extension and shows it", async () => {
    const add = vi.spyOn(extensionsClient, "add").mockResolvedValue({ ...WIKI, id: "docs", label: "Docs" });
    const wrapper = await mounted();

    await wrapper.find("[data-test=label]").setValue("Docs");
    await wrapper.find("[data-test=url]").setValue("http://docs.internal/mcp");
    await wrapper.find("form").trigger("submit");
    await flushPromises();

    expect(add).toHaveBeenCalledWith({ label: "Docs", url: "http://docs.internal/mcp", description: "" });
    expect(wrapper.find("[data-id=docs]").exists()).toBe(true);
  });

  it("removes an extension only after the confirm", async () => {
    const remove = vi.spyOn(extensionsClient, "remove").mockResolvedValue(undefined);
    const wrapper = await mounted();

    await wrapper.find("[data-id=notes] [data-test=remove]").trigger("click");
    expect(remove).not.toHaveBeenCalled();
    await wrapper.findComponent({ name: "ConfirmModal" }).vm.$emit("confirm");
    await flushPromises();

    expect(remove).toHaveBeenCalledWith("notes");
    expect(wrapper.find("[data-id=notes]").exists()).toBe(false);
  });

  it("shows the server's message when adding fails", async () => {
    vi.spyOn(extensionsClient, "add").mockRejectedValue(new Error("must be an http:// or https:// URL"));
    const wrapper = await mounted();

    await wrapper.find("[data-test=label]").setValue("Bad");
    await wrapper.find("[data-test=url]").setValue("ftp://x");
    await wrapper.find("form").trigger("submit");
    await flushPromises();

    expect(wrapper.find("[data-test=add-error]").text()).toContain("must be an http");
  });
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `npx vitest run src/views/ExtensionsAdminView.test.ts`
Expected: FAIL (the stub view has no rows)

- [ ] **Step 3: Implement** (overwrite `src/views/ExtensionsAdminView.vue`)

```vue
<script setup lang="ts">
import { onMounted, ref } from "vue";
import { extensionsClient, type ExtensionInfo } from "../api/ExtensionsClient";
import ConfirmModal from "../components/admin/ConfirmModal.vue";
import { errorMessage } from "../utils/errors";
import "../components/infoPage.css";

const extensions = ref<ExtensionInfo[]>([]);
const loading = ref(true);
const error = ref("");

const label = ref("");
const url = ref("");
const description = ref("");
const adding = ref(false);
const addError = ref("");

const removing = ref<ExtensionInfo | null>(null);
const removeBusy = ref(false);
const removeError = ref("");

async function load(): Promise<void> {
  try {
    extensions.value = await extensionsClient.list();
    error.value = "";
  } catch (err) {
    error.value = errorMessage(err);
  } finally {
    loading.value = false;
  }
}

async function add(): Promise<void> {
  adding.value = true;
  addError.value = "";
  try {
    const created = await extensionsClient.add({ label: label.value, url: url.value, description: description.value });
    extensions.value = [...extensions.value, created];
    label.value = url.value = description.value = "";
  } catch (err) {
    addError.value = errorMessage(err);
  } finally {
    adding.value = false;
  }
}

async function confirmRemove(): Promise<void> {
  const target = removing.value;
  if (!target) return;
  removeBusy.value = true;
  removeError.value = "";
  try {
    await extensionsClient.remove(target.id);
    extensions.value = extensions.value.filter((e) => e.id !== target.id);
    removing.value = null;
  } catch (err) {
    removeError.value = errorMessage(err);
  } finally {
    removeBusy.value = false;
  }
}

onMounted(load);
</script>

<template>
  <section class="info-page extensions-admin">
    <div class="column">
      <h2>Extensions</h2>
      <p class="intro">Other MCP servers mcp_server re-exposes. An extension that is unreachable is still added; it shows its error here.</p>
      <p v-if="error" class="error" role="alert">{{ error }}</p>
      <p v-if="loading" class="muted">Loading…</p>
      <ul v-else class="list">
        <li v-for="e in extensions" :key="e.id" class="card ext" data-test="extension" :data-id="e.id">
          <div class="top">
            <div class="who">
              <strong>{{ e.label }}</strong>
              <code>{{ e.id }}</code>
              <span class="state" :class="e.status">{{ e.status === "connected" ? "Connected" : "Error" }}</span>
            </div>
            <button type="button" class="remove" data-test="remove" @click="removing = e; removeError = ''">Remove</button>
          </div>
          <p v-if="e.description" class="muted">{{ e.description }}</p>
          <p class="muted">{{ e.tools.length }} tool{{ e.tools.length === 1 ? "" : "s" }}</p>
          <p v-if="e.error" class="error">{{ e.error }}</p>
        </li>
      </ul>

      <h3>Add an extension</h3>
      <form class="add" @submit.prevent="add">
        <input v-model="label" data-test="label" type="text" placeholder="Name" required maxlength="80" autocomplete="off" />
        <input v-model="url" data-test="url" type="text" placeholder="http://host:port/mcp" required maxlength="500" autocomplete="off" />
        <input v-model="description" type="text" placeholder="What it is for (optional)" maxlength="500" autocomplete="off" />
        <button type="submit" class="primary" :disabled="adding">{{ adding ? "Adding…" : "Add" }}</button>
      </form>
      <p v-if="addError" class="error" role="alert" data-test="add-error">{{ addError }}</p>
    </div>

    <ConfirmModal
      :open="removing !== null"
      title="Remove extension"
      :message="removeError || `Remove ${removing?.label ?? ''}? Every account that selected it loses it, and its tools disappear from mcp_server.`"
      confirm-label="Remove"
      danger
      :busy="removeBusy"
      @confirm="confirmRemove"
      @close="removing = null"
    />
  </section>
</template>

<style scoped>
.list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin: 0 0 20px;
  padding: 0;
  list-style: none;
}
.top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.who {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}
.who code,
.muted {
  color: var(--muted);
}
.state {
  padding: 1px 8px;
  border-radius: var(--radius-sm);
  font-size: 0.8em;
  background: var(--surface);
}
.state.connected {
  color: var(--success);
}
.state.error {
  color: var(--danger);
}
.add {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.add input {
  flex: 1 1 200px;
  min-width: 0;
  padding: 6px 10px;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  color: var(--text);
  background: var(--bg);
  font: inherit;
}
.primary {
  padding: 6px 16px;
  border: none;
  border-radius: var(--radius-full);
  cursor: pointer;
  font: inherit;
  font-weight: 600;
  color: var(--accent-contrast);
  background: var(--accent);
}
.remove {
  padding: 4px 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: transparent;
  color: var(--danger);
  font: inherit;
  cursor: pointer;
}
.error {
  color: var(--danger);
}
:is(button, input):focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}
</style>
```

- [ ] **Step 4: Run to verify it passes, then type-check**

Run: `npx vitest run src/views/ExtensionsAdminView.test.ts` then `npx vue-tsc -b`
Expected: PASS, no type errors. `ConfirmModal` wraps `BaseModal` (a `<dialog>`); in jsdom the test emits `confirm` on the component directly, as written, so `showModal` support is not needed.

- [ ] **Step 5: Commit**

```bash
cd /d/User/Documents/Programming/Python/MCPServer
git add apps/ember_admin
git commit -m "feat(ember_admin): Extensions page with list, add and confirmed remove"
```

---

### Task 9: End-to-end test against a fake API

**Files:**
- Create: `apps/ember_admin/playwright.config.ts`
- Create: `apps/ember_admin/e2e/fakeApi.ts`
- Create: `apps/ember_admin/e2e/admin.spec.ts`

**Interfaces:**
- Produces: `npm run test:e2e` in `apps/ember_admin`: builds the app, serves it on port 5198, answers every `/api` call from a fake, and fails on any unlisted call.

- [ ] **Step 1: Write the config and the fake**

`playwright.config.ts`: copy `ember_web/playwright.config.ts`, with `EMBER_E2E_PORT ?? 5198`.

`e2e/fakeApi.ts`:

```ts
import type { Page, Route } from "@playwright/test";

/** A stand-in for ember_api: answers the calls the admin app makes, so the
 * built app runs in a real browser without ember_api or mcp_server. Any call
 * not listed is recorded in `unexpected`, and the test fails on it. */

export const ADMIN_ACCOUNT = {
  id: 1,
  username: "root",
  email: "root@example.com",
  email_verified: true,
  roles: ["Administrator"],
  permissions: ["chat.use", "tools.use", "admin.manage", "extensions.manage", "logs.view", "traffic.view"],
};

export interface FakeCapability {
  name: string;
  enabled: boolean;
  label: string;
  tools: string[];
  resources: string[];
  has_gui: boolean;
  load_error: string | null;
  missing: boolean;
  loaded: boolean;
}

export interface FakeState {
  capabilities: FakeCapability[];
  /** Folders a Refresh will discover. */
  discoverable: FakeCapability[];
  /** Names whose next "online" fails. */
  failing: Set<string>;
  unexpected: string[];
}

export function newState(): FakeState {
  const cap = (name: string, over: Partial<FakeCapability> = {}): FakeCapability => ({
    name, enabled: true, label: name[0].toUpperCase() + name.slice(1), tools: [`tool_${name}_run`], resources: [],
    has_gui: false, load_error: null, missing: false, loaded: true, ...over,
  });
  return {
    capabilities: [cap("vault"), cap("gen")],
    discoverable: [cap("fresh", { enabled: false, loaded: false, tools: [] })],
    failing: new Set(["fresh"]),
    unexpected: [],
  };
}

const json = (route: Route, body: unknown, status = 200) =>
  route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

export async function installFakeApi(page: Page, state: FakeState): Promise<void> {
  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const { pathname } = new URL(request.url());
    const method = request.method();

    if (pathname === "/api/auth/me") return json(route, ADMIN_ACCOUNT);
    if (pathname === "/api/capabilities" && method === "GET") return json(route, state.capabilities);
    if (pathname === "/api/capabilities/refresh" && method === "POST") {
      for (const found of state.discoverable) if (!state.capabilities.some((c) => c.name === found.name)) state.capabilities.push(found);
      return json(route, state.capabilities);
    }
    const patch = pathname.match(/^\/api\/capabilities\/([^/]+)$/);
    if (patch && method === "PATCH") {
      const name = decodeURIComponent(patch[1]);
      const target = state.capabilities.find((c) => c.name === name);
      const { enabled } = request.postDataJSON() as { enabled: boolean };
      if (!target) return json(route, { detail: `Unknown capability '${name}'` }, 404);
      if (enabled && state.failing.has(name)) {
        target.load_error = "RuntimeError: boom in tool.py";
        return json(route, { detail: "RuntimeError: boom in tool.py" }, 400);
      }
      target.enabled = enabled;
      if (enabled) { target.loaded = true; target.load_error = null; target.tools = [`tool_${name}_run`]; }
      return json(route, target);
    }
    if (pathname === "/api/extensions" && method === "GET") return json(route, []);

    state.unexpected.push(`${method} ${pathname}`);
    return json(route, { detail: "not faked" }, 404);
  });
}
```

- [ ] **Step 2: Write the spec**

`e2e/admin.spec.ts`:

```ts
import { expect, test } from "@playwright/test";
import { installFakeApi, newState } from "./fakeApi";

test("an admin refreshes, sees a failed load, then brings a fixed capability online", async ({ page }) => {
  const state = newState();
  await installFakeApi(page, state);

  await page.goto("/capabilities");
  await expect(page.locator("[data-name=vault]")).toHaveAttribute("data-state", "online");
  await expect(page.locator("[data-name=fresh]")).toHaveCount(0);

  // A folder added on disk appears on Refresh, offline.
  await page.locator("[data-test=refresh]").click();
  await expect(page.locator("[data-name=fresh]")).toHaveAttribute("data-state", "new");

  // Going online fails: the row stays offline and shows the error.
  await page.locator("[data-name=fresh] .toggle").click();
  await expect(page.locator("[data-name=fresh] [data-test=row-error]")).toContainText("boom in tool.py");
  await expect(page.locator("[data-name=fresh]")).toHaveAttribute("data-state", "error");

  // The code is fixed; online now works.
  state.failing.delete("fresh");
  await page.locator("[data-name=fresh] .toggle").click();
  await expect(page.locator("[data-name=fresh]")).toHaveAttribute("data-state", "online");

  // Taking a capability offline.
  await page.locator("[data-name=vault] .toggle").click();
  await expect(page.locator("[data-name=vault]")).toHaveAttribute("data-state", "offline");

  expect(state.unexpected).toEqual([]);
});
```

- [ ] **Step 3: Run it**

Run (from `apps/ember_admin`): `npm run test:e2e`
Expected: PASS (1 test). The browser is the installed Chrome (`channel: "chrome"`), as for `ember_web`. If the `.toggle` click does not flip the switch, the `ToggleSwitch` hides its input; clicking the label (`.toggle`) is correct, check the selector.

- [ ] **Step 4: Commit**

```bash
cd /d/User/Documents/Programming/Python/MCPServer
git add apps/ember_admin/playwright.config.ts apps/ember_admin/e2e
git commit -m "test(ember_admin): e2e of refresh, failed online and a fixed online against a fake API"
```

---

### Task 10: Docs, launcher check and agent instructions

**Files:**
- Create: `apps/ember_admin/README.md`, `apps/ember_admin/AGENTS.md`, `apps/ember_admin/CLAUDE.md`
- Modify: `apps/mcp_server/README.md` and `apps/mcp_server/src/capabilities/README.md` (the "Add a new capability" section: step on `run.py` is gone)
- Modify: `apps/mcp_server/configs/README.md` (the `_scanner` marker and default-offline rule)
- Verify: `server_launcher` lists the new project

- [ ] **Step 1: Write `apps/ember_admin/README.md`**

Cover, in this order: what it is (admin app for ember, runs on 5175, `EMBER_ADMIN_PORT`); how to run (`run.bat`, needs `ember_api` and `mcp_server` running, log in with an account that has `admin.manage`; a login made in ember_web also works because cookies are not port-scoped); pages and the permission each needs; how Capabilities works (offline, online reloads from disk, Refresh finds new folders, new folders start offline, a failed load shows its error and stays offline); tests (`npm test`, `npm run test:e2e`); that Admin and Analytics are copies of `ember_web`'s and drift until one is removed.

- [ ] **Step 2: Write `AGENTS.md` and `CLAUDE.md`**

`apps/ember_admin/AGENTS.md`:

```markdown
# ember_admin

Project note: `Brain/Projects/ember_admin.md` in the Obsidian vault (`../../../../Brain/` from this folder), once it exists.

Vue 3 + TypeScript admin app for ember. It talks only to `ember_api` through the Vite `/api` proxy. Follow the `ember-design-system` and `ember-feature-scaffold` skills for UI and API conventions.

## Rules
- `src/views/AdminView.vue`, `AnalyticsView.vue` and the components they use are copies of `ember_web`'s. A fix to one is usually needed in the other until the `ember_web` copy is removed.
- Radius only through the `--radius-*` tokens, colors only through `style.css` tokens. `radiusScale.test.ts` enforces it.
- A switch that calls the server stays pending until the server answers; never show a state it did not confirm.
- Checks: `npx vue-tsc -b`, `npm test`, `npm run test:e2e`.
```

`apps/ember_admin/CLAUDE.md`: the single line `@AGENTS.md`.

- [ ] **Step 3: Update the mcp_server docs**

In `apps/mcp_server/src/capabilities/README.md`, in "Add a new capability", remove the step that says to add the import block to `run.py` and replace it with: "Create the folder with its `__init__.py` (`META`) and `tool.py`. Press Refresh on the Capabilities page of ember_admin (or `POST /capabilities/refresh`): the capability appears offline. Switch it online to load it. After editing its code, switch it offline and online again to reload it. Shared modules outside the capability's folder (`src/services/...`) are not reloaded: restart for those. A capability that keeps background state (watchers) should not be reloaded while that state is in use." Keep the rest of the step numbering consistent.

In `apps/mcp_server/configs/README.md`, add under the capabilities config: "`_scanner` is a marker the loader writes on first run. Before it, a capability with no entry is on; after it, a folder with no entry starts offline."

In `apps/mcp_server/README.md`, add `POST /capabilities/refresh` and the `load_error` / `missing` / `loaded` status fields where `GET /capabilities` is described.

- [ ] **Step 4: Check the launcher sees the new project**

Run: `cd /d/User/Documents/Programming/Python/MCPServer/apps/server_launcher && python -c "from src import *" 2>/dev/null; grep -rn "LABEL" src/*.py | head -3`
Then read how projects are detected (`README.md` line 18: it autodetects every `<project>/run.bat`) and confirm `apps/ember_admin/run.bat` has the `REM LABEL:` and `REM DESCRIPTION:` lines. Do not edit `server_launcher` unless detection needs a port registry entry: check `apps/server_launcher` for where `EMBER_WEB_PORT` or `5173` appears (`grep -rn "5173\|EMBER_WEB_PORT" apps/server_launcher`) and add `ember_admin`/`5175`/`EMBER_ADMIN_PORT` in the same place and shape if it lists ports per project. Run `server_launcher`'s tests (`pytest` in its folder) if you edit it.

- [ ] **Step 5: Commit**

```bash
cd /d/User/Documents/Programming/Python/MCPServer
git add apps/ember_admin apps/mcp_server apps/server_launcher
git commit -m "docs: ember_admin README and agent instructions; capability folder workflow"
```

---

### Task 11: Update the spec and run every suite

**Files:**
- Modify: `docs/superpowers/specs/2026-10-08-ember-admin-design.md`

- [ ] **Step 1: Update the spec** to match what the plan found (the three refinements above): in "Agent tool lists" replace the unverified paragraph with "`ai_agent` lists tools live from every upstream on each call (`registry.list_tools` → `_live_tools_for`), so a toggle or reload reaches running agents on their next turn. No notification is needed."; in "Going online" replace "`asyncio.to_thread`" statements with "runs on the event-loop thread under the lock"; in "Discovery" note that a folder with an explicit config entry is imported at startup and then switched off if offline, and replace `discovered` with `loaded` in the status fields; in "Error handling > Concurrency" drop the `to_thread` sentence.

- [ ] **Step 2: Run every suite**

Run:
```bash
cd /d/User/Documents/Programming/Python/MCPServer/apps/mcp_server && .venv_mcp/Scripts/python.exe -m pytest -q
cd ../ember_api && python -m pytest -q
cd ../ember_admin && npx vue-tsc -b && npm test && npm run test:e2e
cd ../ember_web && npm test
```
Expected: all PASS. `ember_web` is untouched, its suite confirms no copy step modified it.

- [ ] **Step 3: Commit**

```bash
cd /d/User/Documents/Programming/Python/MCPServer
git add docs
git commit -m "docs: align the ember_admin spec with what the plan found"
```

- [ ] **Step 4: Hand off to the user**

Tell the user: the code is done and tested in unit and e2e form; they test live. Live check list: start `mcp_server` and `ember_api`, run `apps/ember_admin/run.bat`, log in, open Capabilities, drop a new capability folder into `apps/mcp_server/src/capabilities/`, press Refresh, bring it online, edit its `tool.py`, switch it off and on, and confirm the new tool shows in a chat. Also: `watchers` should still be online after an `mcp_server` restart (the migration), and `ember_web`'s Capabilities page still lists the same tools.

---

## Self-review (run against the spec)

- **Goal 1, Admin and Analytics port:** Task 6.
- **Goal 2, extensions list/add/remove:** Task 8 (routes already exist; `extensions.manage` for add/remove, as `ember_api` enforces).
- **Goal 3, online/offline with reload on online:** Tasks 1, 3, 4 (loader, routes), 7 (UI).
- **Goal 4, add without restart, Refresh button:** Tasks 3 (`scan`, `refresh`), 4 (`POST /capabilities/refresh`), 5 (proxy), 7 (button).
- **New folder starts offline; migration keeps `watchers` on:** Tasks 2, 3 (`startup`), tests in both.
- **Failure rollback, `load_error`, duplicate tool 409, missing folder, lock:** Task 3 tests (one per case).
- **`ember_api` admin-only + activity log:** Task 5.
- **No agent nudge:** spec refinement 3, Task 11.
- **Names consistent across tasks:** `CapabilityLoader`, `CapabilityRecord`, `CapabilityLoadError`, `UnknownCapability`, `set_online`, `refresh`, `record_for`, `records`, `register_unloaded`, `discard`, `remove_capability`, `unregister`, `migrate_capabilities_config`, `refresh_capabilities`, `capabilitiesAdminClient.{list,setOnline,refresh}`, `CapabilityStatus`, fields `load_error`/`missing`/`loaded`: used identically everywhere.
- **Known limits (stated, not hidden):** a module outside the capability's folder is not reloaded; reloading `watchers` while watchers run is unsafe (documented in Task 10); an extension is not reloaded (out of scope in the spec).
