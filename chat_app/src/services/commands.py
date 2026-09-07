"""Chat slash-command registry, parsing, and execution.

"/<id> <tool> key=value ..." bypasses the LLM entirely (see
pages/Chat/__index__.py::chat_api) and calls an MCP tool directly. Two
sources feed the registry:

  - built-in: mcp_server's @command-decorated tools, discovered via
    mcp_client.fetch_commands() and cross-referenced against
    mcp_client.list_tools() for each tool's real parameter schema.
    Grouped by each capability's COMMAND_ID (mcp_client.fetch_capabilities()),
    not its real capability id - see build_command_registry()'s
    docstring for why.
  - extensions: every currently-enabled extension tool is
    auto-registered as a command under its extension id - there's no
    @command decorator possible for code chat_app doesn't own, so its
    own MCP name/description/inputSchema are used as-is.

An id collision between a built-in's COMMAND_ID and an extension's id
keeps the built-in entry - extensions are runtime, third-party config in
a way built-ins aren't.
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass, field

from src.services import attachments_store, mcp_client
from src.services.llm.settings import settings

EXTENSION_SEPARATOR = "__"


@dataclass(frozen=True)
class CommandParam:
    name: str
    required: bool
    type: str  # JSON-schema "type": "string" | "integer" | "number" | "boolean"
    # Whether the tool's JSON schema names a default at all, and what it
    # is - kept as two fields rather than one, since an optional param
    # whose default genuinely is null and a schema that names no default
    # at all both come back as `default=None` otherwise, and the
    # suggestion dropdown needs to tell those apart (see
    # pages/Chat/script.js's suggestion hint text).
    has_default: bool = False
    default: object = None
    # Known-good values for this param, when mcp_server's
    # infra/tool_suggestions.py put an `enum` in the schema - None (not
    # an empty list) when the schema names none, so the autocomplete can
    # tell "no suggestions available" from "suggestions happen to be
    # empty right now".
    enum: list[str] | None = None
    # A JSON-Schema `format` hint on this param, when the schema names
    # one - `"file"` is the one value execute_command() gives special
    # meaning to (resolve the typed value against this chat's attached
    # files instead of taking it literally). None when the schema names
    # no format, same "absent vs empty" distinction enum already makes.
    format: str | None = None


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


_NO_DEFAULT = object()  # sentinel: "default" key absent, distinct from a real default of None


def _params_from_schema(schema: dict | None) -> list[CommandParam]:
    schema = schema or {}
    properties = schema.get("properties") or {}
    required = set(schema.get("required") or [])
    params = []
    for prop_name, prop_schema in properties.items():
        prop_schema = prop_schema or {}
        default = prop_schema.get("default", _NO_DEFAULT)
        enum = prop_schema.get("enum")
        params.append(
            CommandParam(
                name=prop_name,
                required=prop_name in required,
                type=prop_schema.get("type", "string"),
                has_default=default is not _NO_DEFAULT,
                default=None if default is _NO_DEFAULT else default,
                enum=list(enum) if enum else None,
                format=prop_schema.get("format"),
            )
        )
    return params


def build_command_registry(enabled_extensions: list[str] | None) -> dict[str, dict[str, RegisteredCommand]]:
    """{command_id: {tool_id: RegisteredCommand}}

    Grouped by COMMAND_ID (mcp_server's short "/<id> <tool> ..." alias
    for a capability - see infra/capability_metadata.py on that side),
    not the real capability id spec["capability"] names: the real id is
    what config_capabilities.json/PATCH /capabilities/{name} need, but
    nothing here ever sends this grouping key back to mcp_server - it
    only exists so a person has something short to type. Falls back to
    the real id itself for any capability GET /capabilities didn't
    report a command_id for (unreachable mcp_server, or a real
    capability id this deployment's mcp_server predates).
    """
    live_tools = {tool.name: tool for tool in mcp_client.list_tools(enabled_extensions)}
    command_id_by_capability = {c["name"]: c.get("command_id") or c["name"] for c in mcp_client.fetch_capabilities()}
    registry: dict[str, dict[str, RegisteredCommand]] = {}

    for spec in mcp_client.fetch_commands():
        tool = live_tools.get(spec["tool_name"])
        params = _params_from_schema(getattr(tool, "inputSchema", None) if tool else None)
        command_id = command_id_by_capability.get(spec["capability"], spec["capability"])
        registry.setdefault(command_id, {})[spec["name"]] = RegisteredCommand(
            capability=command_id,
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


def execute_command(question: str, enabled_extensions: list[str] | None, chat_id: str | None = None) -> str:
    """Resolves and runs a "/" command, returning the text to show in
    the result bubble. Never raises for a user-facing input problem -
    those come back as a short "❌ ..." usage message instead.

    chat_id is only consulted for a param whose schema names
    format: "file" - its typed value is looked up as an attachment
    filename in that chat rather than taken literally. Defaults to
    None so every existing two-argument call site keeps working."""
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

        arguments: dict[str, object] = {}
        for name, value in parsed.params.items():
            param = params_by_name[name]
            if param.format == "file":
                text = attachments_store.read_attachment_text(settings.attachments_dir, chat_id, value)
                if text is None:
                    raise CommandError(
                        f"No attachment named {value!r} in this chat. Attach it first, then try again."
                    )
                arguments[name] = text
            else:
                arguments[name] = _coerce(value, param.type, name)
        return mcp_client.call_tool(entry.tool_name, arguments)
    except CommandError as exc:
        return f"❌ {exc}"
