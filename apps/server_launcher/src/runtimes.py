"""Finds the python and node a project needs, and words the warning when they are missing."""

from __future__ import annotations

import functools
import shutil
import subprocess

from .models import ServerTemplate

MIN_PYTHON = (3, 11)
_PYTHON_CANDIDATES = (["py", "-3"], ["python"], ["python3"])
_VERSION_CHECK = f"import sys; sys.exit(0 if sys.version_info >= {MIN_PYTHON} else 1)"
_PYTHON_WARNING = (
    f"Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]} or newer was not found. Download it from python.org, tick "
    '"Add python.exe to PATH" in the installer so it is in the environment variables, then close and reopen the launcher.'
)
_NODE_WARNING = (
    "Node.js (node and npm) was not found. Download it from nodejs.org and make sure it is in the environment "
    "variables (PATH), then close and reopen the launcher."
)


@functools.cache
def find_python() -> list[str] | None:
    """The command that starts a usable python (3.11+), e.g. ["py", "-3"], or None.
    Each candidate is run, not just looked up: Windows ships a stub python.exe
    that opens the Store, which a PATH lookup alone would take for python. Found
    once per run - a PATH change needs the launcher restarted anyway."""
    for command in _PYTHON_CANDIDATES:
        if shutil.which(command[0]) is None:
            continue
        try:
            done = subprocess.run(
                [*command, "-c", _VERSION_CHECK], capture_output=True, timeout=15, creationflags=subprocess.CREATE_NO_WINDOW,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if done.returncode == 0:
            return command
    return None


@functools.cache
def find_node() -> bool:
    """Whether node and npm are both on PATH."""
    return shutil.which("node") is not None and shutil.which("npm") is not None


def runtime_warning(template: ServerTemplate) -> str | None:
    """Why this project cannot start on this machine, or None. A python project
    needs python only to build its venv, so it is fine without python on PATH
    once the venv exists; a node project always needs node to run."""
    if template.runtime == "node":
        return None if find_node() else _NODE_WARNING
    if template.venv_python is not None and template.venv_python.exists():
        return None
    return None if find_python() else _PYTHON_WARNING
