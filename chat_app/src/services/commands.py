"""Chat slash-command registry, parsing, and execution.

"/<capability> <tool> key=value ..." bypasses the LLM entirely (see
pages/Chat/__index__.py::chat_api) and calls an MCP tool directly. Two
sources feed the registry:

  - built-in: mcp_server's @command-decorated tools, discovered via
    mcp_client.fetch_commands() and cross-referenced against
    mcp_client.list_tools() for each tool's real parameter schema.
  - extensions: every currently-enabled extension tool is
    auto-registered as a command under its extension id - there's no
    @command decorator possible for code chat_app doesn't own, so its
    own MCP name/description/inputSchema are used as-is.

A capability id collision between a built-in and an extension keeps
the built-in entry - extensions are runtime, third-party config in a
way built-ins aren't.
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass, field

from src.services import mcp_client

EXTENSION_SEPARATOR = "__"


@dataclass(frozen=True)
class CommandParam:
    name: str
    required: bool
    type: str  # JSON-schema "type": "string" | "integer" | "number" | "boolean"


@dataclass(frozen=True)
class RegisteredCommand:
    capability: str
    name: str
    description: str
    tool_name: str
    params: list[CommandParam] = field(default_factory=list)


@dataclass(frozen=True)
class ParsedCommand:
    capability: str
    tool: str
    params: dict[str, str]


class CommandError(Exception):
    """A user-facing problem with a "/" command - unknown
    capability/tool, malformed syntax, missing/bad param. Its message
    is safe to show verbatim in the chat log."""


def _params_from_schema(schema: dict | None) -> list[CommandParam]:
    schema = schema or {}
    properties = schema.get("properties") or {}
    required = set(schema.get("required") or [])
    return [
        CommandParam(name=prop_name, required=prop_name in required, type=(prop_schema or {}).get("type", "string"))
        for prop_name, prop_schema in properties.items()
    ]


def build_command_registry(enabled_extensions: list[str] | None) -> dict[str, dict[str, RegisteredCommand]]:
    """{capability_id: {tool_id: RegisteredCommand}}"""
    live_tools = {tool.name: tool for tool in mcp_client.list_tools(enabled_extensions)}
    registry: dict[str, dict[str, RegisteredCommand]] = {}

    for spec in mcp_client.fetch_commands():
        tool = live_tools.get(spec["tool_name"])
        params = _params_from_schema(getattr(tool, "inputSchema", None) if tool else None)
        registry.setdefault(spec["capability"], {})[spec["name"]] = RegisteredCommand(
            capability=spec["capability"],
            name=spec["name"],
            description=spec["description"],
            tool_name=spec["tool_name"],
            params=params,
        )

    for name, tool in live_tools.items():
        ext_id, sep, original_name = name.partition(EXTENSION_SEPARATOR)
        if not sep:
            continue  # a built-in tool, not extension-namespaced
        if ext_id in registry:
            continue  # a built-in capability id wins over a same-named extension
        registry.setdefault(ext_id, {})[original_name] = RegisteredCommand(
            capability=ext_id,
            name=original_name,
            description=getattr(tool, "description", "") or "",
            tool_name=name,
            params=_params_from_schema(getattr(tool, "inputSchema", None)),
        )

    return registry


def parse_command(text: str) -> ParsedCommand:
    """Parses "/capability tool key=value key2=\"value 2\"". Raises
    CommandError with a user-facing message for anything malformed."""
    body = text[1:].strip()  # drop the leading "/"
    if not body:
        raise CommandError("Empty command - expected /<capability> <tool> [key=value ...]")

    try:
        tokens = shlex.split(body)
    except ValueError as exc:  # unbalanced quotes
        raise CommandError(f"Could not parse command: {exc}") from exc

    if len(tokens) < 2:
        raise CommandError("A command needs both a capability and a tool: /<capability> <tool> [key=value ...]")

    capability, tool, *param_tokens = tokens
    params: dict[str, str] = {}
    for token in param_tokens:
        if "=" not in token:
            raise CommandError(f"Expected key=value, got {token!r}")
        key, _, value = token.partition("=")
        if not key:
            raise CommandError(f"Expected key=value, got {token!r}")
        params[key] = value

    return ParsedCommand(capability=capability, tool=tool, params=params)


def _coerce(value: str, param_type: str, param_name: str) -> object:
    if param_type == "integer":
        try:
            return int(value)
        except ValueError:
            raise CommandError(f"{param_name!r} must be an integer, got {value!r}") from None
    if param_type == "number":
        try:
            return float(value)
        except ValueError:
            raise CommandError(f"{param_name!r} must be a number, got {value!r}") from None
    if param_type == "boolean":
        lowered = value.lower()
        if lowered in {"true", "1", "yes"}:
            return True
        if lowered in {"false", "0", "no"}:
            return False
        raise CommandError(f"{param_name!r} must be a boolean (true/false), got {value!r}")
    return value  # "string" and anything unrecognized passes through as-is


def execute_command(question: str, enabled_extensions: list[str] | None) -> str:
    """Resolves and runs a "/" command, returning the text to show in
    the result bubble. Never raises for a user-facing input problem -
    those come back as a short "❌ ..." usage message instead."""
    try:
        parsed = parse_command(question)
        registry = build_command_registry(enabled_extensions)
        tools = registry.get(parsed.capability)
        if tools is None:
            available = ", ".join(sorted(registry)) or "(none registered)"
            raise CommandError(f"Unknown capability {parsed.capability!r}. Available: {available}")
        entry = tools.get(parsed.tool)
        if entry is None:
            available = ", ".join(sorted(tools)) or "(none)"
            raise CommandError(f"Unknown command /{parsed.capability} {parsed.tool!r}. Available: {available}")

        params_by_name = {p.name: p for p in entry.params}
        missing = [p.name for p in entry.params if p.required and p.name not in parsed.params]
        if missing:
            raise CommandError(
                f"Missing required param(s) for /{parsed.capability} {parsed.tool}: {', '.join(missing)}"
            )
        unknown = [name for name in parsed.params if name not in params_by_name]
        if unknown:
            raise CommandError(
                f"Unknown param(s) for /{parsed.capability} {parsed.tool}: {', '.join(unknown)}"
            )

        arguments = {
            name: _coerce(value, params_by_name[name].type, name) for name, value in parsed.params.items()
        }
        return mcp_client.call_tool(entry.tool_name, arguments)
    except CommandError as exc:
        return f"❌ {exc}"
