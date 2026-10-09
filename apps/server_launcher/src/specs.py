"""Launch specs: what to run for a project, as read from its run.srvlnchr (JSON),
parsed from its run.bat, or typed in by hand. The launcher keeps its own copy of
every spec it lists, so a server still starts when the project's file is erased."""

from __future__ import annotations

import json
import re
from pathlib import Path

from .models import LaunchSpec

SPEC_FILE_NAME = "run.srvlnchr"
_RUNTIMES = ("python", "node")
_NAME_RE = re.compile(r"\w+")
_ENV_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


class SpecError(ValueError):
    """A spec file or form value cannot be used; the message says why."""


def _text(data: dict, name: str) -> str:
    value = data.get(name, "")
    return value.strip() if isinstance(value, str) else ""


def spec_to_dict(spec: LaunchSpec, *, saved: bool = False) -> dict:
    """The JSON form. A project's own run.srvlnchr omits ``project_dir`` and
    ``source`` (the file's folder is the project); the launcher's saved copy has both."""
    data = {
        "label": spec.label, "description": spec.description, "runtime": spec.runtime,
        "venv": spec.venv, "module": spec.module, "port_env_var": spec.port_env_var, "port": spec.port,
        "env": spec.env, "supports_args": spec.supports_args,
    }
    if saved:
        data = {"project_dir": str(spec.project_dir), "source": spec.source, **data}
    return data


def spec_from_dict(data: object, project_dir: Path, source: str) -> LaunchSpec | None:
    """A validated spec, or None when the file says ``"skip": true`` (not a server).
    Raises SpecError for anything the launcher cannot run."""
    if not isinstance(data, dict):
        raise SpecError("the file must hold a JSON object")
    if data.get("skip") is True:
        return None
    runtime = data.get("runtime", "python")
    if runtime not in _RUNTIMES:
        raise SpecError('"runtime" must be "python" or "node"')
    module = _text(data, "module")
    if not module:
        raise SpecError('"module" is required (the python module, or the npm script)')
    venv = _text(data, "venv")
    if runtime == "python" and not _NAME_RE.fullmatch(venv):
        raise SpecError('"venv" is required for python: the x of the .venv_x folder')
    if runtime == "node" and not (project_dir / "package.json").is_file():
        raise SpecError("a node project needs a package.json")
    port = data.get("port", 8000)
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise SpecError('"port" must be a number from 1 to 65535')
    env = data.get("env", {})
    if not isinstance(env, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in env.items()):
        raise SpecError('"env" must be an object of text values')
    port_var = _text(data, "port_env_var") or f"{project_dir.name.upper()}_PORT"
    return LaunchSpec(
        project_dir=project_dir, label=_text(data, "label") or project_dir.name, description=_text(data, "description"),
        runtime=runtime, venv=venv if runtime == "python" else "", module=module, port_env_var=port_var, port=port,
        env={k.upper(): v for k, v in env.items()}, supports_args=data.get("supports_args") is True, source=source,
    )


def read_spec_file(path: Path) -> LaunchSpec | None:
    """Read a project's run.srvlnchr; its folder is the project."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as error:
        raise SpecError(f"cannot read {path.name}") from error
    except json.JSONDecodeError as error:
        raise SpecError(f"{path.name} is not valid JSON ({error.msg})") from error
    return spec_from_dict(data, path.parent.resolve(), "srvlnchr")


def read_saved_spec(path: Path) -> LaunchSpec | None:
    """Read one of the launcher's own saved copies; None when it cannot be used."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        project_dir = Path(data["project_dir"])
        source = data.get("source")
        return spec_from_dict(data, project_dir, source if source in ("bat", "srvlnchr", "manual") else "manual")
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, SpecError):
        return None


def build_manual_spec(
    folder: Path, label: str, runtime: str, venv: str, module: str, port_env_var: str, port: str, env_text: str,
    supports_args: bool,
) -> LaunchSpec:
    """The spec behind the manual setup form (option 3); SpecError names the bad field."""
    env: dict[str, str] = {}
    for line in env_text.splitlines():
        line = line.strip()
        if not line:
            continue
        name, sep, value = line.partition("=")
        if not sep or not _ENV_NAME_RE.fullmatch(name.strip()):
            raise SpecError(f"env line {line!r} must look like NAME=value")
        env[name.strip()] = value.strip()
    try:
        port_number = int(port.strip())
    except ValueError:
        raise SpecError('"port" must be a number from 1 to 65535') from None
    spec = spec_from_dict(
        {
            "label": label.strip(), "runtime": runtime, "venv": venv.strip(), "module": module.strip(),
            "port_env_var": port_env_var.strip(), "port": port_number, "env": env, "supports_args": supports_args,
        },
        folder.resolve(), "manual",
    )
    assert spec is not None
    return spec
