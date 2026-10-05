"""Autodetects launchable servers from each project's run.bat."""

from __future__ import annotations

import json
from pathlib import Path

from .config import (
    _DESCRIPTION_RE, _EXTRA_ROOTS_PATH, _LABEL_RE, _MODULE_RE, _NPM_SCRIPT_RE, _PROJECT_PORT_ENV, _SET_VAR_RE,
    _SKIP_RE, _VENV_RE, REPO_ROOT, SELF_DIR_NAME,
)
from .agent_files import AGENTS_DIR_NAME, entry_port, is_agent_project, read_agent_files
from .models import ServerTemplate


def project_roots(base: Path = REPO_ROOT, extra_roots_path: Path = _EXTRA_ROOTS_PATH) -> list[Path]:
    """This repo's root, then each existing folder listed in extra_roots.json
    (paths relative to ``base``). A missing or malformed file just means no
    extra roots - the launcher must still start."""
    roots = [base]
    try:
        raw = json.loads(extra_roots_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return roots
    if not isinstance(raw, list):
        return roots
    for entry in raw:
        if isinstance(entry, str):
            root = (base / entry).resolve()
            if root.is_dir() and root not in roots:
                roots.append(root)
    return roots


def discover_templates(roots: list[Path] | None = None) -> list[ServerTemplate]:
    """One template per */run.bat in each root. Template keys are folder
    names, so the first root to have a folder name wins."""
    templates: list[ServerTemplate] = []
    seen: set[str] = set()
    bat_paths = [bat for root in (roots or project_roots()) for bat in sorted(root.glob("*/run.bat"))]
    for bat_path in bat_paths:
        if bat_path.parent.name == SELF_DIR_NAME:
            continue  # this launcher's own run.bat is not a server to launch
        if bat_path.parent.name in seen:
            continue
        seen.add(bat_path.parent.name)
        working_dir = bat_path.parent.resolve()
        project_dir = bat_path.parent.name
        try:
            content = bat_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if _SKIP_RE.search(content):
            continue  # the bat says it is not a server

        venv_m = _VENV_RE.search(content)
        mod_m = _MODULE_RE.search(content)
        npm_m = _NPM_SCRIPT_RE.search(content)
        if venv_m and mod_m:
            runtime = "python"
            venv_python = (working_dir / f".venv_{venv_m.group(1)}" / "Scripts" / "python.exe").resolve()
            module = mod_m.group(1)
        elif npm_m and (working_dir / "package.json").exists():
            runtime = "node"
            venv_python = None
            module = npm_m.group(1)
        else:
            # Doesn't match this repo's established run.bat shape - skip
            # rather than guess at how to launch it.
            continue

        supports_args = "%*" in content

        set_vars = {m.group(1).upper(): m.group(2).strip() for m in _SET_VAR_RE.finditer(content)}
        port_var = next((k for k in set_vars if "PORT" in k), None)
        if port_var:
            default_port = int(set_vars[port_var]) if set_vars[port_var].isdigit() else 8000
        else:
            port_var, default_port = _PROJECT_PORT_ENV.get(project_dir, (f"{project_dir.upper()}_PORT", 8000))
        extra_env_vars = {k: v for k, v in set_vars.items() if k != port_var}

        # A supervisor project (ai_agent) takes its ports from its agent
        # files; its entry agent's port is the one to start and track.
        agents = read_agent_files(working_dir / AGENTS_DIR_NAME) if is_agent_project(working_dir, module) else []
        agents_port = entry_port(agents)
        if agents_port is not None:
            default_port = agents_port

        label_m = _LABEL_RE.search(content)
        desc_m = _DESCRIPTION_RE.search(content)
        label = label_m.group(1) if label_m else project_dir
        description = desc_m.group(1) if desc_m else ""

        display_name = label

        templates.append(
            ServerTemplate(
                key=project_dir,
                display_name=display_name,
                description=description,
                working_dir=working_dir,
                venv_python=venv_python,
                module=module,
                port_env_var=port_var,
                default_port=default_port,
                extra_env_vars=extra_env_vars,
                supports_args=supports_args,
                runtime=runtime,
                agents=agents,
            )
        )
    return templates
