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

"/<capability> help [target=...] [command=...]" is the one reserved
tool name: execute_command() intercepts it before the registry lookup
above and calls mcp_server's plain-HTTP /commands/help/{capability}
endpoint instead (see _execute_help() and mcp_client.fetch_help()) -
deliberately not a real command/tool, so it's documentation about a
capability's tools/commands/workflow, never something an AI agent can
invoke over MCP. build_command_registry() still adds a synthetic entry
for it (see _help_command()) for every built-in capability, purely so
the Chat page's suggestion box offers it the same as a real command -
execute_command() never dispatches through that entry, since its own
"tool == help" check above runs first.

Bare "/help" (no capability at all) is the other reserved top-level
name: execute_command() checks for it before parse_command() even runs
(parse_command() itself requires a capability *and* a tool, which a
one-word "/help" doesn't have) and calls mcp_server's
GET /commands/help - no capability path segment - instead, which lists
every built-in capability with its description and full command list
(see _execute_help_index() and mcp_client.fetch_help_index()).

Every command calls its tool directly - no command is ever routed through
an AI agent. A tool that benefits from an AI explanation says so with
``ai_explain_result`` in its MCP meta, which ai_agent reads when the tool
is run from a chat prompt (see ai_agent's tool description handling).

The tool's raw result text is run through
command_formatting.format_command_result() before it comes back from
execute_command() - see that module for why.
"""

from __future__ import annotations

import json
import shlex
from dataclasses import dataclass, field
from typing import Callable
from urllib.error import HTTPError

from flask_login import current_user

from src.services import mcp_client
from src.services.command_formatting import format_command_result

EXTENSION_SEPARATOR = "__"

# These tools need the authenticated caller's real identity for an audit
# trail - never something typed on the command line, or
# even a declared tool parameter an LLM could set itself (see mcp_server's
# services/identity_context.py module docstring for why that was changed).
# Attached out-of-band as an HTTP header on the underlying MCP call instead
# (mcp_client.call_tool's `headers`), read by mcp_server's
# IdentityContextMiddleware into a per-request contextvar - the same trust
# boundary. Maps tool name -> which kind of identity it
# needs; "username" identities are supported too (see _IDENTITY_HEADERS).
_IDENTITY_INJECTED_TOOLS: dict[str, str] = {}
# (header name, user attribute to read) per identity kind - the header
# names must match mcp_server's services/identity_context.py
# REQUESTER_USERNAME_HEADER/REQUESTER_EMAIL_HEADER exactly.
_IDENTITY_HEADERS = {
    "email": ("X-Requester-Email", "email"),
    "username": ("X-Requester-Username", "username"),
}


def _identity_headers_for(tool_name: str, user) -> dict[str, str] | None:
    kind = _IDENTITY_INJECTED_TOOLS.get(tool_name)
    if kind is None:
        return None
    header_name, attr = _IDENTITY_HEADERS[kind]
    return {header_name: getattr(user, attr)}


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
    # JSON Schema `examples` - non-binding value suggestions (as opposed
    # to `enum`, which would actually constrain what's accepted). Powers
    # the "start typing a value after `name=`" suggestion stage in
    # pages/Chat/script.js, the same list the mcp_server tool itself
    # advertises to a model deciding what to pass. Empty for a param
    # whose schema names none - most of them.
    examples: list[str] = field(default_factory=list)
    # JSON Schema `format` - e.g. "file" for a param a tool's Pydantic
    # field annotates with `json_schema_extra={"format": "file"}` (see
    # a mcp_server tool).
    # None for every param whose schema doesn't set one, which is most of
    # them. Lets the Chat page's command-form modal render a file picker
    # instead of a plain text input for that param.
    format: str | None = None
    # Server-side hints for how the Chat form renders this param (a tool
    # sets them with ``Field(json_schema_extra={"input": ..., ...})``, or
    # they come from standard schema keys). ``input`` names the widget:
    # "text" | "textarea" | "password" | "number" | "range" | "date" |
    # "select" | "checkbox" | "file"; None lets the form infer it from
    # type/enum/examples. ``options_url`` is a path on mcp_server that
    # returns the select's options (see mcp_client.fetch_options); the
    # Chat page's /api/commands route resolves it into ``options``.
    input: str | None = None
    options_url: str | None = None
    enum: list[str] = field(default_factory=list)
    minimum: float | None = None
    maximum: float | None = None
    step: float | None = None
    max_length: int | None = None
    pattern: str | None = None
    # Select wiring (see pages/Chat/command_form_modal.js): `depends_on`
    # names another param whose value fills a {placeholder} in
    # `options_url`; `sets` fills other params from the chosen option
    # ({param: option field}); `shows` lists read-only lines from it
    # ({label: option field}); `initial` prefills a text box
    # ("{timestamp}" is replaced with the current time).
    depends_on: str | None = None
    sets: dict[str, str] = field(default_factory=dict)
    shows: dict[str, str] = field(default_factory=dict)
    initial: str | None = None


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

_HELP_PARAMS = {"target", "command"}


def _command_error_from_http_error(exc: HTTPError) -> CommandError:
    """Shared by both help paths below: mcp_server's help endpoints
    return ``{"error": "..."}`` on a 4xx (see help_routes.py), and this
    turns that into the same "safe to show verbatim" CommandError every
    other user-facing failure in this module already is."""
    try:
        body = json.loads(exc.read().decode("utf-8"))
        message = body.get("error", str(exc))
    except Exception:  # noqa: BLE001 - a malformed error body still needs a message
        message = str(exc)
    return CommandError(message)


def _execute_help_index() -> str:
    """Bare ``/help`` - lists every enabled built-in capability with its
    description and full command list, from mcp_server's
    ``GET /commands/help`` (no capability path segment - see
    mcp_client.fetch_help_index() / mcp_server's help_routes.py). See
    module docstring for why this bypasses parse_command()/the registry
    entirely rather than being a real command."""
    try:
        result = mcp_client.fetch_help_index()
    except HTTPError as exc:
        raise _command_error_from_http_error(exc) from exc
    return format_command_result(json.dumps(result))


def _execute_help(parsed: ParsedCommand) -> str:
    """``/<capability> help [target=...] [command=...]`` - deliberately
    not a registered command/tool (see module docstring's "built-in"
    bullet): every real command comes from mcp_server's live tool
    registry, but help.json is capability documentation, not something
    an AI agent should ever be able to call over MCP. execute_command()
    special-cases ``tool == "help"`` before it ever reaches the registry
    lookup below, and this hits mcp_server's plain-HTTP
    ``/commands/help/{capability}`` endpoint instead (see
    mcp_client.fetch_help / mcp_server's help_routes.py).
    """
    unknown = set(parsed.params) - _HELP_PARAMS
    if unknown:
        raise CommandError(
            f"Unknown param(s) for /{parsed.capability} help: {', '.join(sorted(unknown))}. "
            f"Expected target=all|tools|commands|workflow, or command=<name>."
        )
    target = parsed.params.get("target", "all")
    command = parsed.params.get("command")
    try:
        result = mcp_client.fetch_help(parsed.capability, target=target, command=command)
    except HTTPError as exc:
        raise _command_error_from_http_error(exc) from exc
    return format_command_result(json.dumps(result))


def _schema_value(prop_schema: dict, key: str):
    """A schema key from the property itself or, for an ``X | None`` param
    (which Pydantic wraps in ``anyOf``), from whichever branch sets it."""
    if key in prop_schema:
        return prop_schema[key]
    for branch in prop_schema.get("anyOf") or []:
        if isinstance(branch, dict) and key in branch:
            return branch[key]
    return None


def _params_from_schema(schema: dict | None) -> list[CommandParam]:
    schema = schema or {}
    properties = schema.get("properties") or {}
    required = set(schema.get("required") or [])
    params = []
    for prop_name, prop_schema in properties.items():
        prop_schema = prop_schema or {}
        default = prop_schema.get("default", _NO_DEFAULT)
        params.append(
            CommandParam(
                name=prop_name,
                required=prop_name in required,
                type=prop_schema.get("type", "string"),
                has_default=default is not _NO_DEFAULT,
                default=None if default is _NO_DEFAULT else default,
                # Pydantic emits `examples` at the property's top level
                # even for an `X | None` param (whose `type` instead sits
                # under `anyOf` - see `type` above), so no anyOf-digging
                # is needed here.
                examples=list(prop_schema.get("examples") or []),
                format=prop_schema.get("format"),
                input=prop_schema.get("input"),
                options_url=prop_schema.get("options_url"),
                enum=[str(v) for v in (_schema_value(prop_schema, "enum") or [])],
                minimum=_schema_value(prop_schema, "minimum"),
                maximum=_schema_value(prop_schema, "maximum"),
                step=prop_schema.get("step"),
                max_length=_schema_value(prop_schema, "maxLength"),
                pattern=_schema_value(prop_schema, "pattern"),
                depends_on=prop_schema.get("depends_on"),
                sets=dict(prop_schema.get("sets") or {}),
                shows=dict(prop_schema.get("shows") or {}),
                initial=prop_schema.get("initial"),
            )
        )
    return params


_HELP_TARGETS = ["all", "tools", "commands", "workflow"]


def _help_command(capability: str, existing: dict[str, RegisteredCommand]) -> RegisteredCommand:
    """Synthetic ``/<capability> help`` entry - not backed by a real
    @command-decorated tool the way every other entry here is (see this
    module's docstring on why "help" is special-cased in
    execute_command() rather than ever being dispatched through this
    RegisteredCommand). Still worth surfacing in the registry so the
    Chat page's suggestion box offers it like any other command;
    ``command``'s examples list every real sub-command name this
    capability already has, so typing ``/<capability> help command=``
    suggests one to ask about.
    """
    return RegisteredCommand(
        capability=capability,
        name="help",
        description="Show this capability's tools/commands/workflow tables, or detail for one command.",
        tool_name="help",
        params=[
            CommandParam(
                name="target",
                required=False,
                type="string",
                has_default=True,
                default="all",
                examples=list(_HELP_TARGETS),
            ),
            CommandParam(
                name="command",
                required=False,
                type="string",
                has_default=False,
                default=None,
                examples=sorted(existing),
            ),
        ],
    )


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

    # Every built-in capability seen above gets a "help" entry too - only
    # built-ins, since mcp_server's /commands/help/{capability} endpoint
    # (capability_help.py) only knows built-in capabilities' help.json
    # files, not extensions. Added only now that each capability's full
    # command dict is built, so `existing` reflects every real command -
    # and before the extension loop below, so an extension can never
    # pick up a "help" entry it has no server-side backing for.
    for capability, existing in list(registry.items()):
        existing["help"] = _help_command(capability, existing)

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


def execute_command(
    question: str, enabled_extensions: list[str] | None, user=None,
    on_progress: Callable[[str], None] | None = None,
) -> str:
    """Resolves and runs a "/" command, returning the text to show in
    the result bubble. Never raises for a
    user-facing input problem - those come back as a short "❌ ..." usage
    message instead.

    ``user`` is the identity to inject into an identity-requiring tool's
    request headers (see ``_IDENTITY_INJECTED_TOOLS``). Defaults to
    ``current_user`` - the Flask-Login proxy - for callers still on the
    request thread; a caller running this off-thread (e.g. a background
    job worker, where the proxy resolves to no user) must pass the
    already-captured user object explicitly instead.

    ``on_progress`` receives each live progress message a long-running tool
    reports while it runs (see mcp_client.call_tool).
    """
    if user is None:
        user = current_user
    try:
        # Bare "/help" - no capability, so parse_command() (which
        # requires both a capability and a tool) can't handle it. Must
        # run before that call, not after: "/help" has too few tokens
        # for parse_command() to accept at all. See module docstring.
        if question[1:].strip() == "help":
            return _execute_help_index()

        parsed = parse_command(question)
        registry = build_command_registry(enabled_extensions)
        tools = registry.get(parsed.capability)
        if tools is None:
            available = ", ".join(sorted(registry)) or "(none registered)"
            raise CommandError(f"Unknown capability {parsed.capability!r}. Available: {available}")
        if parsed.tool == "help":
            return _execute_help(parsed)
        entry = tools.get(parsed.tool)
        if entry is None:
            available = ", ".join(sorted(tools)) or "(none)"
            raise CommandError(f"Unknown command /{parsed.capability} {parsed.tool!r}. Available: {available}")

        identity_headers = _identity_headers_for(entry.tool_name, user)

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

        # Only passed when set, so a caller that never asks for progress
        # (and any test stub of call_tool) keeps the old call shape.
        extra = {"on_progress": on_progress} if on_progress else {}
        return format_command_result(mcp_client.call_tool(entry.tool_name, arguments, headers=identity_headers, **extra))
    except CommandError as exc:
        return f"❌ {exc}"
