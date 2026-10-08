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
import os
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

    write_capability(root, "widgets", "wid", "tool_wid_run", returns="version-two-edited")
    run(loader.set_online("wid", True))

    tool = mcp._tool_manager._tools["tool_wid_run"]
    assert tool.fn() == "version-two-edited"
    assert len(commands.all_commands()) == 1  # no duplicate-key error, no leftovers


def test_going_online_again_ignores_a_stale_bytecode_cache(loader_for, package, mcp, monkeypatch):
    # Same size and same mtime: Python would trust the cached .pyc unless the
    # loader deletes the capability's __pycache__.
    monkeypatch.setattr(sys, "dont_write_bytecode", False)  # PYTHONDONTWRITEBYTECODE may be set
    _, root = package
    write_capability(root, "widgets", "wid", "tool_wid_run", returns="v1")
    loader = loader_for()
    loader.scan()
    run(loader.set_online("wid", True))
    tool_file = root / "widgets" / "tool.py"
    original = tool_file.stat()
    assert list((root / "widgets").glob("__pycache__/tool*.pyc"))
    run(loader.set_online("wid", False))

    write_capability(root, "widgets", "wid", "tool_wid_run", returns="v2")
    os.utime(tool_file, ns=(original.st_atime_ns, original.st_mtime_ns))
    assert tool_file.stat().st_size == original.st_size
    run(loader.set_online("wid", True))

    assert mcp._tool_manager._tools["tool_wid_run"].fn() == "v2"


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
