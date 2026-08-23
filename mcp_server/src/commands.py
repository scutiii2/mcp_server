"""Registry for chat-invocable commands - tools opted in via @command.

Independent of FastMCP's own tool registration (`@mcp.tool()` in
server.py): `@command` just records {capability, name, description,
tool_name} here, for this server's own `/commands` endpoint
(command_routes.py) to expose to chat_app. The MCP tool call itself
still goes through the normal `call_tool` protocol - this registry only
answers "what commands exist and which real tool do they call."

Capability id is inferred from the decorated function's module path
(e.g. "src.capabilities.otp.tool" -> "otp"), matching the
capabilities/<name>/ folder convention documented in
capabilities/__init__.py - no separate hand-maintained map needed,
unlike chat_app's tool_capabilities.py/tool_titles.py (those exist to
avoid relying on MCP *wire protocol* grouping across package versions;
this is a same-codebase Python import, not a wire assumption).
"""

from __future__ import annotations

from dataclasses import dataclass


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
            return parts[index + 1]
    raise ValueError(
        f"Cannot infer a capability id from module {module_name!r} - "
        "@command must decorate a function defined inside a "
        "src.capabilities.<name> package."
    )


def command(name: str, description: str):
    """Mark an already-@mcp.tool()-decorated function as invocable from
    chat as `/<capability> <name> key=value ...`. Does not alter the
    function or FastMCP's registration - only records metadata."""

    def decorator(fn):
        capability = _infer_capability(fn.__module__)
        _COMMANDS[(capability, name)] = CommandSpec(
            capability=capability, name=name, description=description, tool_name=fn.__name__
        )
        return fn

    return decorator


def all_commands() -> list[CommandSpec]:
    return list(_COMMANDS.values())
