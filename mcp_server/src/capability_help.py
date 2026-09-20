"""Structured `/<capability> help` data - backs GET /commands/help and
GET /commands/help/{capability}.

Each capability keeps its own `help.json` next to its `README.md`
(`capabilities/<folder>/help.json`), hand-maintained rather than parsed
out of the README at request time: the README stays the narrative doc a
person reads, `help.json` stays a small, stable shape a client renders,
and the two are free to drift in wording without one having to be
scraped from the other. See `capabilities/README.md`'s "Adding a new
tool" section for the schema new capabilities should follow when they
add their own.

Not a tool: mounted as a plain HTTP route by `help_routes.py`, the same
"nothing here a model needs to call" reasoning `command_routes.py`
documents for `GET /commands` - chat_app's `commands.py` intercepts
`/<capability> help ...` before it ever reaches the tool registry and
calls this instead (see that module's docstring).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.services import capability_meta, capability_registry

_CAPABILITIES_DIR = Path(__file__).resolve().parent / "capabilities"

_TARGETS = {"all", "tools", "commands", "workflow"}


class HelpError(Exception):
    """A user-facing problem resolving `/<capability> help` - unknown
    capability, missing help.json, or an unknown target/command name.
    Its message is safe to show verbatim in the chat log, same
    convention as chat_app's own CommandError."""


def _label(capability_id: str) -> str:
    try:
        return capability_registry.label(capability_id)
    except KeyError:
        return capability_id


def _load(capability_id: str) -> dict[str, Any]:
    folder = capability_meta.folder_for_id(capability_id)
    if folder is None:
        raise HelpError(f"Unknown capability {capability_id!r}")
    path = _CAPABILITIES_DIR / folder / "help.json"
    if not path.exists():
        raise HelpError(f"No help available for capability {capability_id!r}")
    return json.loads(path.read_text(encoding="utf-8"))


def _tool_row(capability_id: str, tool: dict[str, Any]) -> dict[str, Any]:
    commands = tool.get("commands") or []
    slash_commands = ", ".join(f"/{capability_id} {name}" for name in commands) or "none (MCP-only)"
    return {
        "tool": tool["name"],
        "purpose": tool["purpose"],
        "connection": tool["connection"],
        "slash_command": slash_commands,
    }


def _param_text(param: dict[str, Any]) -> str:
    if param["required"]:
        qualifier = "required"
    elif param.get("default") is None:
        qualifier = "optional"
    else:
        qualifier = f"optional, default {param['default']!r}"
    return f"{param['name']} ({qualifier}) - {param['description']}"


def _command_row(capability_id: str, command: dict[str, Any]) -> dict[str, Any]:
    params = command.get("params") or []
    return {
        "slash_command": f"/{capability_id} {command['name']}",
        "parameters": "; ".join(_param_text(p) for p in params) or "None.",
    }


def _workflow_row(step: dict[str, Any]) -> dict[str, Any]:
    row = {"sequence": step["sequence"], "tool": step["tool"], "explanation": step["explanation"]}
    if step.get("ai_only_step"):
        row["ai_only_step"] = "Yes"
    return row


def _find_command(data: dict[str, Any], command_name: str) -> dict[str, Any]:
    for command in data.get("commands") or []:
        if command["name"] == command_name:
            return command
    known = ", ".join(sorted(c["name"] for c in data.get("commands") or [])) or "(none)"
    raise HelpError(f"Unknown command {command_name!r}. Available: {known}")


def build_index() -> dict[str, Any]:
    """The JSON body `GET /commands/help` (no capability path segment)
    returns - one row per currently-enabled built-in capability, for
    chat_app's bare top-level `/help` command (see `help_routes.py` /
    chat_app's `commands.py::_execute_help_index()`). Same generic
    `message` + `list[dict]` shape as `build_help()`, so it renders
    through the same table formatter with no special-casing.

    Skips a registered capability with no `help.json` on disk instead of
    raising - unlike `build_help()`'s per-capability lookup, a single
    capability missing its file shouldn't break the whole index for
    every other one.
    """
    rows: list[dict[str, Any]] = []
    for name in sorted(capability_registry.names()):
        if not capability_registry.is_enabled(name):
            continue
        folder = capability_meta.folder_for_id(name)
        if folder is None:
            continue
        path = _CAPABILITIES_DIR / folder / "help.json"
        if not path.exists():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        command_names = sorted({c["name"] for c in data.get("commands") or []} | {"help"})
        rows.append(
            {
                "capability": f"/{name}",
                "label": _label(name),
                "summary": data.get("summary", ""),
                "commands": ", ".join(command_names),
            }
        )
    return {
        "message": "Every capability listed below also answers `/<capability> help` for its full "
        "tool/command/workflow detail, or `/<capability> help command=<name>` for one command.",
        "capabilities": rows,
    }


def build_help(capability_id: str, target: str = "all", command: str | None = None) -> dict[str, Any]:
    """The JSON body `GET /commands/help/{capability}` returns.

    Shaped so chat_app's existing generic result formatter
    (`command_formatting.py`) renders it with no capability-specific
    code: a `message` string plus zero or more `list[dict]` fields, each
    dict sharing the same keys across its rows - exactly the shape every
    other command result already follows.

    `command` (a sub-command name like `"list"`) takes priority over
    `target` when both are given - it answers "explain this one command"
    rather than "show me a whole table". Raises `HelpError` for an
    unknown capability, target, or command name.
    """
    data = _load(capability_id)
    label = _label(capability_id)

    if command:
        cmd = _find_command(data, command)
        tool = next((t for t in data.get("tools") or [] if t["name"] == cmd["tool"]), None)
        message = f"`/{capability_id} {command}`"
        if tool is not None:
            message += f" - {tool['purpose']}"
        result: dict[str, Any] = {"message": message, "commands": [_command_row(capability_id, cmd)]}
        if tool is not None:
            result["tools"] = [_tool_row(capability_id, tool)]
        steps = [_workflow_row(s) for s in data.get("workflow") or [] if s.get("tool") == cmd["tool"]]
        if steps:
            result["workflow"] = steps
        return result

    if target not in _TARGETS:
        raise HelpError(f"Unknown help target {target!r}. Expected one of: {', '.join(sorted(_TARGETS))}")

    summary = data.get("summary", "")
    result = {"message": f"**/{capability_id}** - {label}\n\n{summary}".strip()}
    if target in {"all", "tools"}:
        result["tools"] = [_tool_row(capability_id, t) for t in data.get("tools") or []]
    if target in {"all", "commands"}:
        result["commands"] = [_command_row(capability_id, c) for c in data.get("commands") or []]
    if target in {"all", "workflow"}:
        result["workflow"] = [_workflow_row(s) for s in data.get("workflow") or []]
    return result
