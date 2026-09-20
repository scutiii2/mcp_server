"""Autodetects launchable servers from each project's run.bat."""

from __future__ import annotations

from .config import (
    _DESCRIPTION_RE, _LABEL_RE, _MODULE_RE, _PROJECT_PORT_ENV, _SET_VAR_RE, _VENV_RE, REPO_ROOT, SELF_DIR_NAME,
)
from .models import ServerTemplate


def discover_templates() -> list[ServerTemplate]:
    templates: list[ServerTemplate] = []
    for bat_path in sorted(REPO_ROOT.glob("*/run.bat")):
        if bat_path.parent.name == SELF_DIR_NAME:
            continue  # this launcher's own run.bat is not a server to launch
        working_dir = bat_path.parent.resolve()
        project_dir = bat_path.parent.name
        try:
            content = bat_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        venv_m = _VENV_RE.search(content)
        mod_m = _MODULE_RE.search(content)
        if not (venv_m and mod_m):
            # Doesn't match this repo's established run.bat shape - skip
            # rather than guess at how to launch it.
            continue

        venv_python = (working_dir / f".venv_{venv_m.group(1)}" / "Scripts" / "python.exe").resolve()
        module = mod_m.group(1)
        supports_args = "%*" in content

        set_vars = {m.group(1).upper(): m.group(2).strip() for m in _SET_VAR_RE.finditer(content)}
        port_var = next((k for k in set_vars if "PORT" in k), None)
        if port_var:
            default_port = int(set_vars[port_var]) if set_vars[port_var].isdigit() else 8000
        else:
            port_var, default_port = _PROJECT_PORT_ENV.get(project_dir, (f"{project_dir.upper()}_PORT", 8000))
        extra_env_vars = {k: v for k, v in set_vars.items() if k != port_var}

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
            )
        )
    return templates
