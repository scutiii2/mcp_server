"""Registry for chat-invocable commands - tools opted in via @command.

Independent of FastMCP's own tool registration (`@mcp.tool()` in
server.py): `@command` just records {capability, name, description,
tool_name} here, for this server's own `/commands` endpoint
(command_routes.py) to expose to chat_app. The MCP tool call itself
still goes through the normal `call_tool` protocol - this registry only
answers "what commands exist and which real tool do they call."

Capability id is inferred from the decorated function's module path
(e.g. "src.capabilities.server_manager.tool" -> folder
"server_manager"), then looked up in capability_meta.py for that
folder's registered short id ("server") - falling back to the folder
name itself for a capability that hasn't registered one. This is what
lets every @command call in a capability's tool.py omit `capability=`
entirely rather than repeating the same string at every one of its
tools: the id is declared once, in that capability's __init__.py (see
capability_meta.py's docstring), not per-command here.

No separate hand-maintained map needed for any of this, unlike
chat_app's tool_capabilities.py/tool_titles.py (those exist to avoid
relying on MCP *wire protocol* grouping across package versions; this
is a same-codebase Python import, not a wire assumption).
"""

from __future__ import annotations

from dataclasses import dataclass

from src.services import capability_meta


@dataclass(frozen=True)
class CommandSpec:
    capability: str
    name: str
    description: str
    tool_name: str


_COMMANDS: dict[tuple[str, str], CommandSpec] = {}


def _infer_capability(module_name: str) -> str:
    parts = module_name.split(".")
    if "capabilities" in parts:
        index = parts.index("capabilities")
        if index + 1 < len(parts):
            folder = parts[index + 1]
            meta = capability_meta.for_folder(folder)
            return meta.id if meta is not None else folder
    raise ValueError(
        f"Cannot infer a capability id from module {module_name!r} - "
        "@command must decorate a function defined inside a "
        "src.capabilities.<name> package."
    )


def command(name: str, description: str, capability: str | None = None):
    """Mark an already-@mcp.tool()-decorated function as invocable from
    chat as `/<capability> <name> key=value ...`. Does not alter the
    function or FastMCP's registration - only records metadata.

    `capability` defaults to the id inferred from the module's
    `src.capabilities.<name>` package path via `capability_meta.py` -
    normally you never pass it: register the id once in
    `capabilities/<name>/__init__.py` (`capability_meta.register(...)`)
    and every `@command` in that capability's `tool.py` picks it up
    automatically, which is also what makes the chat-facing id shorter
    than the folder name (e.g. `/role ...` instead of
    `/server_manager ...`) without repeating `capability="server"`
    on every single tool. Pass it explicitly only for a one-off
    exception - a command that genuinely needs a different id than the
    rest of its capability.

    Whatever id ends up here must match the string passed to
    `capability_registry.capturing()` for the same capability in
    `run.py` (both should be reading the same `capability_meta` entry):
    `command_routes.py`'s `/commands` endpoint looks up
    `capability_registry.is_enabled(spec.capability)` to decide whether
    to list a command at all, so a mismatch there means a disabled
    capability's commands keep showing up (the lookup fails open on
    `KeyError`) rather than a hard error - the kind of bug that hides
    until someone disables the capability and notices nothing changed.
    """

    def decorator(fn):
        capability_id = capability or _infer_capability(fn.__module__)
        _COMMANDS[(capability_id, name)] = CommandSpec(
            capability=capability_id, name=name, description=description, tool_name=fn.__name__
        )
        return fn

    return decorator


def all_commands() -> list[CommandSpec]:
    return list(_COMMANDS.values())
