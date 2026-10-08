"""Finds capability folders and brings them online, offline, or back after an edit.

``run.py`` used to import each capability by hand at startup, so a new
capability needed a restart. The loader replaces that: it lists the folders
of ``src/capabilities/``, reads each package's ``META`` (id and label), and
loads the ones the config says to. ``POST /capabilities/refresh`` runs the
same scan on the live server, so a folder dropped in while it runs appears.

Going online always imports the capability fresh: its old state is removed
(tools, resource templates, ``@command`` entries, ``META``), every module
under its folder is purged from ``sys.modules``, its ``__pycache__`` folders
are deleted, and the package is imported again inside
``capability_registry.capturing()``. ``importlib.reload`` would miss
submodules such as ``domain.py``. The ``__pycache__`` delete matters because
Python trusts a cached ``.pyc`` when the source has the same mtime (whole
seconds) and size, so a quick same-size edit would otherwise run old code.
Only the capability's own folder is purged; a shared ``src.services`` module
edited meanwhile is not reloaded.

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
import shutil
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
        # Stale bytecode: same mtime (whole seconds) and size would be trusted.
        package_dir = Path(importlib.import_module(self._package).__path__[0]) / folder
        for cache in package_dir.rglob("__pycache__"):
            shutil.rmtree(cache, ignore_errors=True)
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
