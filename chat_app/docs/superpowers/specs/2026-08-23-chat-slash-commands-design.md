# Chat slash commands + bigger chat box

Date: 2026-08-23

## Problem

The chat box is small, and every message the user sends goes to an LLM
provider, even when what they actually want is to invoke a specific tool
directly (e.g. "generate me an OTP") without burning a model call or
depending on the model choosing to call the right tool. This adds:

1. A larger chat input/log area.
2. A `/capability tool key=value ...` command syntax that, when the
   input starts with `/`, bypasses the LLM entirely and calls an MCP
   tool directly.
3. A `@command(name=..., description=...)` decorator so `mcp_server`
   capability authors can opt individual tools into this syntax under a
   friendly alias, independent of the tool's internal function name.
4. A cascading autocomplete UI (capability -> tool -> params) in the
   chat input, driven by a live registry.

## Non-goals

- No changes to how the LLM chooses/calls tools during normal
  (non-`/`) chat turns.
- No permission/approval gating beyond what a tool already enforces
  itself (e.g. `verify_otp_tool`'s existing lockout behavior) - a
  command call is just a direct, unmediated `call_tool`, same trust
  level as a model-issued tool call.
- No support for multi-word unquoted param values beyond simple
  shell-like quoting (`key="a b c"`); nested/complex value types
  (arrays, objects) are out of scope for v1 - only scalar params.

## Server side (`mcp_server`) - the `@command` decorator + registry

New module: `mcp_server/src/mcp_server/commands.py`

```python
_COMMANDS: dict[tuple[str, str], CommandSpec] = {}

@dataclass(frozen=True)
class CommandSpec:
    capability: str   # inferred, e.g. "otp"
    name: str         # decorator's `name=`, e.g. "get_otp"
    description: str  # decorator's `description=`
    tool_name: str     # fn.__name__, the real MCP tool name to call

def command(name: str, description: str):
    def decorator(fn):
        capability = _infer_capability(fn.__module__)
        _COMMANDS[(capability, name)] = CommandSpec(capability, name, description, fn.__name__)
        return fn
    return decorator
```

`_infer_capability` splits `fn.__module__` (e.g.
`mcp_server.capabilities.otp.tool`) and takes the path segment right
after `capabilities`. This matches the existing convention documented
in `capabilities/__init__.py` (each capability owns a
`capabilities/<name>/` folder) and needs no separate hand-maintained
map, unlike `chat_app`'s existing `tool_capabilities.py`/`tool_titles.py`
(those exist specifically to avoid relying on MCP-protocol-level
grouping; this is a same-codebase, same-language import, not a wire
protocol assumption, so direct introspection is safe here).

`@command` is applied outermost, above `@mcp.tool(...)`:

```python
@command(name="get_otp", description="generate otp")
@mcp.tool(meta={"keywords": [...]})
def request_otp_tool(recipient: str | None = None) -> RequestOtpResult:
    ...
```

It does not wrap or alter the function's behavior or FastMCP's
registration - it only records metadata and returns `fn` unchanged, so
existing tests and direct calls to `request_otp_tool` are unaffected.

New endpoint in `mcp_server/src/mcp_server/extension_routes.py` (a
plain-HTTP sibling of the existing `/extensions` endpoint, not part of
the MCP protocol itself):

```
GET /commands
-> [{"capability": "otp", "name": "get_otp", "description": "generate otp", "tool_name": "request_otp_tool"}, ...]
```

Initial capabilities to decorate as the working example: `otp`
(`get_otp` -> `request_otp_tool`, `verify_otp` -> `verify_otp_tool`).
`host_health` is left undecorated for now (nothing about the design
requires every tool to opt in).

## `chat_app` side - unified registry, parsing, execution

New module: `chat_app/src/services/commands.py`

### Registry

```python
def build_command_registry(enabled_extensions: list[str]) -> dict:
    """
    {
      "<capability_id>": {
        "tools": {
          "<tool_id>": {
            "description": str,
            "tool_name": str,          # real MCP tool name to call
            "params": [
              {"name": str, "required": bool, "type": "string"|"integer"|"number"|"boolean"},
              ...
            ],
          },
          ...
        },
      },
      ...
    }
    """
```

Built from two sources, merged:

- **Built-in**: `mcp_client.fetch_commands()` (new function, same
  urllib pattern as `fetch_extensions()`) hits `mcp_server`'s
  `/commands`. Each entry's `tool_name` is cross-referenced against
  `mcp_client.list_tools()`'s live catalog to read that tool's real
  `inputSchema` (property names, `required` list, JSON-schema `type`)
  for the `params` list.
- **Extensions**: for every tool in `mcp_client.list_tools(enabled_extensions)`
  whose name is `{ext_id}__original_name` (i.e. already enabled, same
  filter `_tool_is_enabled` already applies for the LLM), auto-register
  a command: capability id = `ext_id`, tool id = `original_name`,
  description/params read directly from that tool's own
  name/description/`inputSchema` - no decorator involved, since this is
  third-party code. A capability id collision between a built-in
  capability and an extension id is resolved in favor of the built-in
  entry (extensions are attacker-influenced-config in a way built-ins
  aren't); this is a documented edge case, not expected in practice.

### Parsing

```python
def parse_command(text: str) -> ParsedCommand | CommandParseError:
    # "/otp verify_otp otp_id=abc123 code=000000"
    # -> capability="otp", tool="verify_otp", params={"otp_id": "abc123", "code": "000000"}
```

Tokenization: `shlex.split` (handles `key="value with spaces"`
quoting) after stripping the leading `/`. First token is the capability
id, second is the tool id, remaining tokens must each contain exactly
one `=`.

### Execution

```python
def execute_command(question: str, enabled_extensions: list[str]) -> str:
    # returns the text to show in the result bubble - either the
    # tool's output or a human-readable error - never raises for
    # user-facing input problems (unknown capability/tool, missing
    # required param, bad value, malformed syntax)
```

Resolves the registry entry, coerces each provided param value to its
schema type (int/float/bool parsing with a clear error on failure),
checks all `required` params are present, then calls the existing
`mcp_client.call_tool(tool_name, arguments)` and returns its text. Any
resolution/validation failure returns a short usage-style error message
instead (e.g. `Unknown command: /otp reset. Available: get_otp, verify_otp`).

### Wiring into `chat_api()`

In `chat_app/src/pages/Chat/__index__.py::chat_api()`, immediately
after the existing blank-question check:

```python
if question.startswith("/"):
    response_text = commands.execute_command(question, data.get("enabled_extensions", []))
    is_command = True
else:
    # existing router.run_chat(...) path
    is_command = False
```

The LLM is never invoked for `/`-prefixed input, matching or failing.
Chat history persistence, error logging, and the trace log all still
run the same as any other turn - `is_command` just skips setting
`provider_id`/`model_used`/`total_tokens` (there are none) and tags the
saved `assistant_entry` with `"kind": "command"` so the frontend knows
to render it with the system/amber style rather than the green
assistant one.

## UI changes (`chat_app/src/pages/Chat/`)

### Bigger chat box (`styles.css`)

- `.page-content { max-width: 720px }` -> widen (e.g. `960px`).
- `#log { min-height: 320px; max-height: 70vh }` -> taller
  (e.g. `min-height: 480px`).
- `#q` padding/font-size bumped slightly to match.

No behavioral change, no markup change.

### Cascading autocomplete (`chat.html` + `script.js` + `styles.css`)

New route `GET /api/chat/api/commands` (chat blueprint) returns
`commands.build_command_registry(enabled_extensions)` as JSON - reuses
the exact registry `execute_command` resolves against, so suggestions
and execution can never disagree. Fetched once on page load (like
providers/extensions) and re-fetched whenever the enabled-extensions
set changes (same hook point as the existing extension checkbox
`change` listener).

A new `<ul id="cmd-suggestions">` dropdown, absolutely positioned under
`#q`, hidden by default. Driven by a small state machine keyed off the
current `#q` value:

1. Value starts with `/` and has no space yet -> suggestions = capability
   ids, filtered by the text after `/`.
2. Value is `/cap ` plus a partial token with no second space -> suggestions
   = that capability's tool ids, filtered by the partial token.
3. Value is `/cap tool ` plus further text -> suggestions = that tool's
   param names (rendered as `name=`) not already present earlier in the
   string, required ones marked/sorted first.
4. Any value not starting with `/` -> dropdown hidden, normal LLM chat.

Interaction: ArrowUp/ArrowDown move a highlighted index, Tab or Enter
accepts the highlighted suggestion (inserting it plus a trailing space
at the current segment), Escape hides the dropdown, mouse click on an
item accepts it the same way. Accepting never sends the message -
Enter's existing "submit on Enter" behavior in `script.js` only fires
when the dropdown is closed; while it's open, Enter/Tab are consumed by
the dropdown instead.

## Testing

- `mcp_server`: unit tests for `_infer_capability` and the `@command`
  registry (decorating a fixture function, asserting the registry
  entry), plus a test hitting `/commands` for the otp capability.
- `chat_app`: unit tests for `parse_command` (valid, missing `=`,
  quoted values), `build_command_registry` (merges built-in +
  extension sources, respects `enabled_extensions`), and
  `execute_command` (happy path via a stubbed `mcp_client.call_tool`,
  unknown capability, unknown tool, missing required param, bad type).
- Manual browser verification of the resize and autocomplete
  interaction (typing, filtering, keyboard selection) - left to the
  user per their stated preference not to have this done via automated
  browser agents.
