"""Reads a launch spec from a project folder (run.srvlnchr first, else run.bat) and builds server templates."""

from __future__ import annotations

from pathlib import Path

from .agent_files import AGENTS_DIR_NAME, entry_port, is_agent_project, read_agent_files
from .config import (
    _DESCRIPTION_RE, _LABEL_RE, _MODULE_RE, _NPM_SCRIPT_RE, _PROJECT_PORT_ENV, _SET_VAR_RE, _SKIP_RE, _VENV_RE,
    SELF_DIR_NAME,
)
from .models import LaunchSpec, ServerTemplate
from .specs import SPEC_FILE_NAME, SpecError, read_spec_file


def spec_from_bat(path: Path) -> LaunchSpec | None:
    """The spec a project's run.bat describes, or None when it is marked
    ``REM LAUNCHER: skip`` or doesn't match this repo's run.bat shape (the
    launcher doesn't guess at how to start it)."""
    project_dir = path.parent.resolve()
    key = project_dir.name
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    if _SKIP_RE.search(content):
        return None  # the bat says it is not a server

    venv_m = _VENV_RE.search(content)
    mod_m = _MODULE_RE.search(content)
    npm_m = _NPM_SCRIPT_RE.search(content)
    if venv_m and mod_m:
        runtime, venv, module = "python", venv_m.group(1), mod_m.group(1)
    elif npm_m and (project_dir / "package.json").exists():
        runtime, venv, module = "node", "", npm_m.group(1)
    else:
        return None

    set_vars = {m.group(1).upper(): m.group(2).strip() for m in _SET_VAR_RE.finditer(content)}
    port_var = next((k for k in set_vars if "PORT" in k), None)
    if port_var:
        port = int(set_vars[port_var]) if set_vars[port_var].isdigit() else 8000
    else:
        port_var, port = _PROJECT_PORT_ENV.get(key, (f"{key.upper()}_PORT", 8000))

    label_m = _LABEL_RE.search(content)
    desc_m = _DESCRIPTION_RE.search(content)
    return LaunchSpec(
        project_dir=project_dir, label=label_m.group(1) if label_m else key,
        description=desc_m.group(1) if desc_m else "", runtime=runtime, venv=venv, module=module,
        port_env_var=port_var, port=port, env={k: v for k, v in set_vars.items() if k != port_var},
        supports_args="%*" in content, source="bat",
    )


def read_project_spec(folder: Path) -> LaunchSpec | None:
    """The spec a project folder offers: its run.srvlnchr if it has one, else its
    run.bat. None when it has neither, or the file says it is not a server.
    Raises SpecError when a run.srvlnchr cannot be used."""
    spec_file = folder / SPEC_FILE_NAME
    if spec_file.is_file():
        return read_spec_file(spec_file)
    bat = folder / "run.bat"
    return spec_from_bat(bat) if bat.is_file() else None


def refreshed_spec(saved: LaunchSpec) -> LaunchSpec:
    """The saved spec brought up to date with the project's own file. The saved
    copy stands when the file is gone, unusable or marked skip, and a manual
    spec has no file to follow."""
    if saved.source == "manual":
        return saved
    try:
        return read_project_spec(saved.project_dir) or saved
    except SpecError:
        return saved


def template_from_spec(spec: LaunchSpec) -> ServerTemplate:
    working_dir = spec.project_dir.resolve()
    port = spec.port
    # A supervisor project (ai_agent) takes its ports from its agent files;
    # its entry agent's port is the one to start and track.
    agents = read_agent_files(working_dir / AGENTS_DIR_NAME) if is_agent_project(working_dir, spec.module) else []
    agents_port = entry_port(agents)
    if agents_port is not None:
        port = agents_port
    is_python = spec.runtime == "python"
    return ServerTemplate(
        key=spec.key,
        display_name=spec.label,
        description=spec.description,
        working_dir=working_dir,
        venv_python=(working_dir / f".venv_{spec.venv}" / "Scripts" / "python.exe").resolve() if is_python else None,
        module=spec.module,
        port_env_var=spec.port_env_var,
        default_port=port,
        extra_env_vars=dict(spec.env),
        supports_args=spec.supports_args,
        runtime=spec.runtime,
        agents=agents,
    )


def templates_from_specs(specs: list[LaunchSpec]) -> list[ServerTemplate]:
    """One template per spec. Keys are folder names, so the first to have a
    folder name wins; this launcher's own folder is never listed."""
    templates: list[ServerTemplate] = []
    seen: set[str] = set()
    for spec in specs:
        if spec.key == SELF_DIR_NAME or spec.key in seen:
            continue
        seen.add(spec.key)
        templates.append(template_from_spec(spec))
    return templates


def discover_templates(projects: list[Path]) -> list[ServerTemplate]:
    """Templates for project folders, read from their own run.srvlnchr / run.bat
    (a folder with neither, or one that is not a server, is left out)."""
    specs = [spec for folder in projects if (spec := read_project_spec(folder)) is not None]
    return templates_from_specs(specs)
