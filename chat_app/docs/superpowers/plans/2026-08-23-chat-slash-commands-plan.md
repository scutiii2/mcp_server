# Chat slash commands + bigger chat box Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a chat message that starts with `/` call an MCP tool directly (`/capability tool key=value ...`), bypassing the LLM entirely, with a `@command` decorator for `mcp_server` capability authors to opt in, a cascading capability→tool→param autocomplete in the chat input, and a bigger chat box.

**Architecture:** `mcp_server` gains a small standalone registry (`commands.py`) that a `@command` decorator writes into (capability id auto-inferred from the module path), exposed over a new plain-HTTP `GET /commands` endpoint alongside the existing `/extensions` one. `chat_app` merges that with its own live MCP tool catalog (built-ins get their param schema from `list_tools()`; every *enabled* extension tool is auto-registered as a command too, since we don't own that code to decorate) into one registry, used both to parse/execute `/` input (in place of calling the LLM router) and to drive the input's autocomplete dropdown.

**Tech Stack:** Python (FastMCP, Starlette, Flask), vanilla JS (no build step, no JS test runner in this repo — JS changes are verified manually in-browser, not via automated tests, matching this project's existing convention), pytest.

**Spec:** [chat_app/docs/superpowers/specs/2026-08-23-chat-slash-commands-design.md](../specs/2026-08-23-chat-slash-commands-design.md)

## Global Constraints

- Command params use `key=value` syntax (quoted with `shlex` rules for values containing spaces), never bare positional args.
- Slash commands may invoke both built-in `mcp_server` capability tools (opted in via `@command`) and any currently-*enabled* extension tool (auto-registered, no decorator possible) — same enabled/disabled toggle the LLM path already respects.
- Any input starting with `/` NEVER reaches the LLM, whether or not it resolves to a real command — an unresolvable `/` command is a usage error, not a fallback to normal chat.
- A capability id collision between a built-in capability and an extension keeps the built-in entry.
- `@command`'s capability id is inferred from the decorated function's module path (`mcp_server.capabilities.<name>.tool` → `<name>`) — never hand-maintained in a separate map.
- Command result bubbles render with the existing `.msg.system` (amber) CSS class, not `.msg.assistant` (green) — visually distinct from an LLM answer — but the `role` value persisted in chat history/sent back to the LLM stays `"assistant"` (only a sibling `"kind": "command"` field marks it), so past command turns still read correctly as context on later LLM turns.

---

### Task 1: `@command` decorator and registry (`mcp_server`)

**Files:**
- Create: `mcp_server/src/mcp_server/commands.py`
- Test: `mcp_server/tests/test_commands.py`

**Interfaces:**
- Produces: `mcp_server.commands.CommandSpec` (frozen dataclass: `capability: str`, `name: str`, `description: str`, `tool_name: str`); `mcp_server.commands.command(name: str, description: str)` (decorator, returns the function unchanged); `mcp_server.commands.all_commands() -> list[CommandSpec]`; module-level `mcp_server.commands._COMMANDS: dict[tuple[str, str], CommandSpec]` (test-visible for isolation via `monkeypatch.setattr`).

- [ ] **Step 1: Write the failing tests**

```python
# mcp_server/tests/test_commands.py
"""Tests for the @command decorator and its registry - see
mcp_server/commands.py. Each test gets its own empty registry via
monkeypatch (swapping the module's _COMMANDS dict for the duration of
the test) rather than mutating the real one in place, so this file
can't clobber registrations other test files rely on being real (e.g.
a future test_otp_commands.py, which asserts against the actual
otp capability's registrations)."""

from __future__ import annotations

import pytest

from mcp_server import commands


@pytest.fixture(autouse=True)
def _isolated_registry(monkeypatch):
    monkeypatch.setattr(commands, "_COMMANDS", {})


def test_infer_capability_reads_the_segment_after_capabilities():
    assert commands._infer_capability("mcp_server.capabilities.otp.tool") == "otp"


def test_infer_capability_rejects_a_module_with_no_capabilities_segment():
    with pytest.raises(ValueError, match="Cannot infer a capability id"):
        commands._infer_capability("mcp_server.infra.email")


def test_command_records_capability_name_description_and_tool_name():
    def fake_tool_fn():
        ...

    fake_tool_fn.__module__ = "mcp_server.capabilities.widgets.tool"

    decorated = commands.command(name="make_widget", description="build a widget")(fake_tool_fn)

    assert decorated is fake_tool_fn  # unchanged, still directly callable
    spec = commands._COMMANDS[("widgets", "make_widget")]
    assert spec == commands.CommandSpec(
        capability="widgets", name="make_widget", description="build a widget", tool_name="fake_tool_fn"
    )


def test_all_commands_returns_every_registered_spec():
    def fn_a():
        ...

    def fn_b():
        ...

    fn_a.__module__ = "mcp_server.capabilities.otp.tool"
    fn_b.__module__ = "mcp_server.capabilities.otp.tool"

    commands.command(name="get_otp", description="generate otp")(fn_a)
    commands.command(name="verify_otp", description="verify otp")(fn_b)

    assert set(commands.all_commands()) == {
        commands.CommandSpec("otp", "get_otp", "generate otp", "fn_a"),
        commands.CommandSpec("otp", "verify_otp", "verify otp", "fn_b"),
    }
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd mcp_server && python -m pytest tests/test_commands.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'mcp_server.commands'`

- [ ] **Step 3: Implement `commands.py`**

```python
# mcp_server/src/mcp_server/commands.py
"""Registry for chat-invocable commands - tools opted in via @command.

Independent of FastMCP's own tool registration (`@mcp.tool()` in
server.py): `@command` just records {capability, name, description,
tool_name} here, for mcp_server's own `/commands` endpoint
(command_routes.py) to expose to chat_app. The MCP tool call itself
still goes through the normal `call_tool` protocol - this registry only
answers "what commands exist and which real tool do they call."

Capability id is inferred from the decorated function's module path
(e.g. "mcp_server.capabilities.otp.tool" -> "otp"), matching the
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
        "mcp_server.capabilities.<name> package."
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd mcp_server && python -m pytest tests/test_commands.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add mcp_server/src/mcp_server/commands.py mcp_server/tests/test_commands.py
git commit -m "feat: add @command decorator and registry to mcp_server"
```

---

### Task 2: `GET /commands` endpoint, wired into the server

**Files:**
- Create: `mcp_server/src/mcp_server/command_routes.py`
- Modify: `mcp_server/src/mcp_server/run.py:94-134` (add the import and install call next to `install_extension_routes`)
- Test: `mcp_server/tests/test_command_routes.py`

**Interfaces:**
- Consumes: `mcp_server.commands.CommandSpec`, `mcp_server.commands.all_commands()`, `mcp_server.commands._COMMANDS` (Task 1).
- Produces: `mcp_server.command_routes.install_command_routes(app: starlette.applications.Starlette) -> None`, mounting `GET /commands` which returns `[{"capability": str, "name": str, "description": str, "tool_name": str}, ...]`.

- [ ] **Step 1: Write the failing tests**

```python
# mcp_server/tests/test_command_routes.py
"""Tests for GET /commands - same Starlette TestClient pattern as
test_extension_routes.py. Uses monkeypatch to swap in an isolated
registry per test, same reasoning as test_commands.py."""

from __future__ import annotations

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

from mcp_server import commands
from mcp_server.command_routes import install_command_routes


@pytest.fixture
def client():
    app = Starlette()
    install_command_routes(app)
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def _isolated_registry(monkeypatch):
    monkeypatch.setattr(commands, "_COMMANDS", {})


def test_list_commands_returns_every_registered_command(client):
    def fn():
        ...

    fn.__module__ = "mcp_server.capabilities.otp.tool"
    commands.command(name="get_otp", description="generate otp")(fn)

    response = client.get("/commands")

    assert response.status_code == 200
    assert response.json() == [
        {"capability": "otp", "name": "get_otp", "description": "generate otp", "tool_name": "fn"}
    ]


def test_list_commands_returns_empty_list_when_none_registered(client):
    response = client.get("/commands")

    assert response.status_code == 200
    assert response.json() == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd mcp_server && python -m pytest tests/test_command_routes.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'mcp_server.command_routes'`

- [ ] **Step 3: Implement `command_routes.py`**

```python
# mcp_server/src/mcp_server/command_routes.py
"""HTTP endpoint for the chat-invocable command registry: GET /commands.

Mounted the same way extension_routes.py's /extensions is (see run.py):
a plain HTTP route alongside the MCP surface, not a tool - chat_app's
command execution/autocomplete path polls this, no model ever calls
it.
"""

from __future__ import annotations

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse

from mcp_server import commands


def _spec_json(spec: commands.CommandSpec) -> dict[str, str]:
    return {
        "capability": spec.capability,
        "name": spec.name,
        "description": spec.description,
        "tool_name": spec.tool_name,
    }


async def list_commands(request: Request) -> JSONResponse:
    return JSONResponse([_spec_json(spec) for spec in commands.all_commands()])


def install_command_routes(app: Starlette) -> None:
    app.add_route("/commands", list_commands, methods=["GET"])
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd mcp_server && python -m pytest tests/test_command_routes.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Wire it into `run.py`**

In `mcp_server/src/mcp_server/run.py`, find this block (around line 94-95):

```python
        from mcp_server.approval_routes import install_approval_routes
        from mcp_server.extension_routes import install_extension_routes
        from mcp_server.infra import approvals
```

Replace it with:

```python
        from mcp_server.approval_routes import install_approval_routes
        from mcp_server.command_routes import install_command_routes
        from mcp_server.extension_routes import install_extension_routes
        from mcp_server.infra import approvals
```

Then find (around line 130-134):

```python
        install_approval_routes(app)
        # Where a human (or chat_app's sidebar) checks what's connected -
        # also a plain HTTP route, same reasoning: nothing here is
        # something a model needs to call. See extension_routes.py.
        install_extension_routes(app)
```

Replace it with:

```python
        install_approval_routes(app)
        # Where a human (or chat_app's sidebar) checks what's connected -
        # also a plain HTTP route, same reasoning: nothing here is
        # something a model needs to call. See extension_routes.py.
        install_extension_routes(app)
        # Where chat_app discovers which built-in tools are invocable as
        # "/" commands - also a plain HTTP route, same reasoning. See
        # command_routes.py.
        install_command_routes(app)
```

- [ ] **Step 6: Commit**

```bash
git add mcp_server/src/mcp_server/command_routes.py mcp_server/tests/test_command_routes.py mcp_server/src/mcp_server/run.py
git commit -m "feat: expose GET /commands and wire it into the server"
```

---

### Task 3: Decorate the `otp` capability's tools as commands

**Files:**
- Modify: `mcp_server/src/mcp_server/capabilities/otp/tool.py`
- Test: `mcp_server/tests/test_otp_commands.py`

**Interfaces:**
- Consumes: `mcp_server.commands.command` (Task 1).

- [ ] **Step 1: Write the failing test**

```python
# mcp_server/tests/test_otp_commands.py
"""Regression coverage: the otp capability's tools are registered as
chat-invocable commands - see mcp_server/commands.py. Uses the real,
process-wide registry (no isolation fixture) - importing the tool
module is what runs the @command decorator, same reasoning as
test_tool_keywords.py's own comment on why these imports "look
unused"."""

from __future__ import annotations

from mcp_server import commands
from mcp_server.capabilities.otp import tool as otp_tool  # noqa: F401


def test_otp_commands_are_registered_under_the_otp_capability():
    by_name = {spec.name: spec for spec in commands.all_commands() if spec.capability == "otp"}

    assert by_name["get_otp"].tool_name == "request_otp_tool"
    assert by_name["get_otp"].description == "generate otp"
    assert by_name["verify_otp"].tool_name == "verify_otp_tool"
    assert by_name["verify_otp"].description == "verify otp"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd mcp_server && python -m pytest tests/test_otp_commands.py -v`
Expected: FAIL with `KeyError: 'get_otp'`

- [ ] **Step 3: Decorate the tools**

In `mcp_server/src/mcp_server/capabilities/otp/tool.py`, add the import:

```python
from mcp_server.commands import command
```

next to the existing `from mcp_server.server import mcp` import, then change:

```python
@mcp.tool(meta={"keywords": ["otp", "passcode", "code", "verify", "identity", "email"]})
def request_otp_tool(recipient: str | None = None) -> RequestOtpResult:
```

to:

```python
@command(name="get_otp", description="generate otp")
@mcp.tool(meta={"keywords": ["otp", "passcode", "code", "verify", "identity", "email"]})
def request_otp_tool(recipient: str | None = None) -> RequestOtpResult:
```

and change:

```python
@mcp.tool(meta={"keywords": ["otp", "passcode", "code", "verify"]})
def verify_otp_tool(otp_id: str, code: str) -> VerifyOtpResult:
```

to:

```python
@command(name="verify_otp", description="verify otp")
@mcp.tool(meta={"keywords": ["otp", "passcode", "code", "verify"]})
def verify_otp_tool(otp_id: str, code: str) -> VerifyOtpResult:
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd mcp_server && python -m pytest tests/test_otp_commands.py tests/test_otp_domain.py tests/test_tool_keywords.py -v`
Expected: PASS — includes the pre-existing otp/keyword tests to confirm the decorator didn't change the tools' own behavior or registration.

- [ ] **Step 5: Commit**

```bash
git add mcp_server/src/mcp_server/capabilities/otp/tool.py mcp_server/tests/test_otp_commands.py
git commit -m "feat: expose otp's tools as /otp get_otp and /otp verify_otp commands"
```

---

### Task 4: `mcp_client.fetch_commands()` (`chat_app`)

**Files:**
- Modify: `chat_app/src/services/mcp_client.py` (add after `fetch_extensions`, currently ending around line 121)
- Test: `chat_app/tests/test_mcp_client.py` (add after `test_fetch_extensions_builds_url_from_mcp_server_base_and_returns_parsed_json`, currently ending around line 121)

**Interfaces:**
- Produces: `src.services.mcp_client.fetch_commands() -> list[dict[str, Any]]`, each dict shaped `{"capability": str, "name": str, "description": str, "tool_name": str}` (mirrors Task 2's `/commands` JSON shape exactly).

- [ ] **Step 1: Write the failing test**

In `chat_app/tests/test_mcp_client.py`, add (right after `test_fetch_extensions_builds_url_from_mcp_server_base_and_returns_parsed_json`, before the `def _fake_response(payload):` helper):

```python
def test_fetch_commands_builds_url_from_mcp_server_base_and_returns_parsed_json():
    """/commands is a sibling of /extensions on the same origin - same
    reasoning as fetch_extensions() above."""
    fake_payload = [
        {"capability": "otp", "name": "get_otp", "description": "generate otp", "tool_name": "request_otp_tool"}
    ]
    captured_url = {}

    def _fake_urlopen(url, timeout=None):
        captured_url["url"] = url

        class _FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return json.dumps(fake_payload).encode("utf-8")

        return _FakeResponse()

    with patch("src.services.mcp_client.urlopen", side_effect=_fake_urlopen):
        result = mcp_client.fetch_commands()

    assert result == fake_payload
    assert captured_url["url"] == "http://127.0.0.1:8010/commands"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd chat_app && python -m pytest tests/test_mcp_client.py::test_fetch_commands_builds_url_from_mcp_server_base_and_returns_parsed_json -v`
Expected: FAIL with `AttributeError: module 'src.services.mcp_client' has no attribute 'fetch_commands'`

- [ ] **Step 3: Implement `fetch_commands()`**

In `chat_app/src/services/mcp_client.py`, add after `fetch_extensions()` (after the line `return json.loads(response.read().decode("utf-8"))` that closes it, before `def add_extension(...)`):

```python
def _commands_url() -> str:
    """mcp_server's /commands endpoint - a sibling of /extensions on the
    same origin, built the same way (see _extensions_url() above)."""
    split = urlsplit(settings.mcp_server_url)
    return f"{split.scheme}://{split.netloc}/commands"


def fetch_commands() -> list[dict[str, Any]]:
    """The built-in chat-command registry from mcp_server's plain-HTTP
    /commands endpoint - see mcp_server/command_routes.py. Same failure
    behavior as fetch_extensions() above: raises on any failure, caller
    decides how to surface it."""
    with urlopen(_commands_url(), timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd chat_app && python -m pytest tests/test_mcp_client.py -v`
Expected: PASS (all tests in the file, including the new one)

- [ ] **Step 5: Commit**

```bash
git add chat_app/src/services/mcp_client.py chat_app/tests/test_mcp_client.py
git commit -m "feat: add mcp_client.fetch_commands() for mcp_server's /commands endpoint"
```

---

### Task 5: Command registry, parser, and executor (`chat_app`)

**Files:**
- Create: `chat_app/src/services/commands.py`
- Test: `chat_app/tests/test_commands.py`

**Interfaces:**
- Consumes: `src.services.mcp_client.fetch_commands()` (Task 4), `src.services.mcp_client.list_tools(enabled_extensions)`, `src.services.mcp_client.call_tool(name, arguments)` (both pre-existing).
- Produces: `src.services.commands.CommandParam` (frozen dataclass: `name: str`, `required: bool`, `type: str`); `src.services.commands.RegisteredCommand` (frozen dataclass: `capability: str`, `name: str`, `description: str`, `tool_name: str`, `params: list[CommandParam]`); `src.services.commands.ParsedCommand` (frozen dataclass: `capability: str`, `tool: str`, `params: dict[str, str]`); `src.services.commands.CommandError(Exception)`; `src.services.commands.build_command_registry(enabled_extensions: list[str] | None) -> dict[str, dict[str, RegisteredCommand]]`; `src.services.commands.parse_command(text: str) -> ParsedCommand` (raises `CommandError`); `src.services.commands.execute_command(question: str, enabled_extensions: list[str] | None) -> str` (never raises for user-facing input problems — returns a `"❌ ..."` string instead).

- [ ] **Step 1: Write the failing tests**

```python
# chat_app/tests/test_commands.py
"""Tests for chat_app's "/" command registry, parser, and executor -
see src/services/commands.py. mcp_client itself is mocked throughout,
same convention as test_mcp_client.py."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from src.services import commands


def _tool(name, description="", input_schema=None):
    return SimpleNamespace(name=name, description=description, inputSchema=input_schema or {})


OTP_SCHEMA = {"properties": {"recipient": {"type": "string"}}, "required": []}
VERIFY_SCHEMA = {
    "properties": {"otp_id": {"type": "string"}, "code": {"type": "string"}},
    "required": ["otp_id", "code"],
}


def _otp_tools():
    return [
        _tool("request_otp_tool", input_schema=OTP_SCHEMA),
        _tool("verify_otp_tool", input_schema=VERIFY_SCHEMA),
    ]


def _otp_command_specs():
    return [
        {"capability": "otp", "name": "get_otp", "description": "generate otp", "tool_name": "request_otp_tool"},
        {"capability": "otp", "name": "verify_otp", "description": "verify otp", "tool_name": "verify_otp_tool"},
    ]


# --- parse_command ---------------------------------------------------------


def test_parse_command_reads_capability_tool_and_key_value_params():
    parsed = commands.parse_command("/otp verify_otp otp_id=abc123 code=000000")

    assert parsed.capability == "otp"
    assert parsed.tool == "verify_otp"
    assert parsed.params == {"otp_id": "abc123", "code": "000000"}


def test_parse_command_supports_quoted_values_with_spaces():
    parsed = commands.parse_command('/otp get_otp recipient="a b@example.com"')

    assert parsed.params == {"recipient": "a b@example.com"}


def test_parse_command_rejects_a_token_with_no_equals_sign():
    try:
        commands.parse_command("/otp verify_otp otp_id")
        raise AssertionError("expected CommandError")
    except commands.CommandError as exc:
        assert "key=value" in str(exc)


def test_parse_command_rejects_missing_tool():
    try:
        commands.parse_command("/otp")
        raise AssertionError("expected CommandError")
    except commands.CommandError:
        pass


# --- build_command_registry -------------------------------------------------


def test_build_command_registry_reads_built_in_commands_and_their_param_schemas():
    with patch.object(commands.mcp_client, "fetch_commands", return_value=_otp_command_specs()), patch.object(
        commands.mcp_client, "list_tools", return_value=_otp_tools()
    ):
        registry = commands.build_command_registry([])

    entry = registry["otp"]["verify_otp"]
    assert entry.tool_name == "verify_otp_tool"
    assert entry.description == "verify otp"
    assert {p.name: p.required for p in entry.params} == {"otp_id": True, "code": True}


def test_build_command_registry_auto_registers_enabled_extension_tools():
    ext_tools = _otp_tools() + [
        _tool(
            "reference__echo",
            description="Echoes input.",
            input_schema={"properties": {"text": {"type": "string"}}, "required": ["text"]},
        )
    ]
    with patch.object(commands.mcp_client, "fetch_commands", return_value=_otp_command_specs()), patch.object(
        commands.mcp_client, "list_tools", return_value=ext_tools
    ):
        registry = commands.build_command_registry(["reference"])

    entry = registry["reference"]["echo"]
    assert entry.tool_name == "reference__echo"
    assert entry.description == "Echoes input."
    assert entry.params == [commands.CommandParam(name="text", required=True, type="string")]


def test_build_command_registry_a_built_in_capability_id_wins_over_a_same_named_extension():
    ext_tools = _otp_tools() + [_tool("otp__sneaky", description="not the real otp", input_schema={})]
    with patch.object(commands.mcp_client, "fetch_commands", return_value=_otp_command_specs()), patch.object(
        commands.mcp_client, "list_tools", return_value=ext_tools
    ):
        registry = commands.build_command_registry(["otp"])

    assert "sneaky" not in registry["otp"]
    assert "get_otp" in registry["otp"]


# --- execute_command ---------------------------------------------------------


def test_execute_command_happy_path_calls_call_tool_with_coerced_arguments():
    with patch.object(commands.mcp_client, "fetch_commands", return_value=_otp_command_specs()), patch.object(
        commands.mcp_client, "list_tools", return_value=_otp_tools()
    ), patch.object(commands.mcp_client, "call_tool", return_value="OTP sent.") as call_tool:
        result = commands.execute_command("/otp get_otp recipient=a@example.com", [])

    assert result == "OTP sent."
    call_tool.assert_called_once_with("request_otp_tool", {"recipient": "a@example.com"})


def test_execute_command_reports_unknown_capability():
    with patch.object(commands.mcp_client, "fetch_commands", return_value=_otp_command_specs()), patch.object(
        commands.mcp_client, "list_tools", return_value=_otp_tools()
    ):
        result = commands.execute_command("/nope get_otp", [])

    assert result.startswith("❌")
    assert "nope" in result


def test_execute_command_reports_missing_required_param():
    with patch.object(commands.mcp_client, "fetch_commands", return_value=_otp_command_specs()), patch.object(
        commands.mcp_client, "list_tools", return_value=_otp_tools()
    ):
        result = commands.execute_command("/otp verify_otp otp_id=abc123", [])

    assert result.startswith("❌")
    assert "code" in result


def test_execute_command_coerces_integer_params():
    tool = _tool("count_tool", input_schema={"properties": {"n": {"type": "integer"}}, "required": ["n"]})
    specs = [{"capability": "widgets", "name": "count", "description": "count things", "tool_name": "count_tool"}]
    with patch.object(commands.mcp_client, "fetch_commands", return_value=specs), patch.object(
        commands.mcp_client, "list_tools", return_value=[tool]
    ), patch.object(commands.mcp_client, "call_tool", return_value="5") as call_tool:
        result = commands.execute_command("/widgets count n=5", [])

    assert result == "5"
    call_tool.assert_called_once_with("count_tool", {"n": 5})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd chat_app && python -m pytest tests/test_commands.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.services.commands'`

- [ ] **Step 3: Implement `commands.py`**

```python
# chat_app/src/services/commands.py
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd chat_app && python -m pytest tests/test_commands.py -v`
Expected: PASS (10 tests)

- [ ] **Step 5: Commit**

```bash
git add chat_app/src/services/commands.py chat_app/tests/test_commands.py
git commit -m "feat: add chat_app command registry, parser, and executor"
```

---

### Task 6: Wire commands into `chat_api()`, bypassing the LLM for `/` input

**Files:**
- Modify: `chat_app/src/pages/Chat/__index__.py:1-32` (import) and `:142-272` (`chat_api`)
- Test: `chat_app/tests/test_chat_page.py`

**Interfaces:**
- Consumes: `src.services.commands.execute_command(question, enabled_extensions)` (Task 5).

- [ ] **Step 1: Write the failing tests**

In `chat_app/tests/test_chat_page.py`, add near the top (with the other imports):

```python
from src.services import commands
```

Then add these tests (after `test_chat_api_unexpected_error_produces_log_entry_and_safe_response`):

```python
def test_chat_api_command_input_never_calls_the_llm_router(tmp_path, monkeypatch):
    app = _build_chat_test_app(tmp_path, monkeypatch)
    account_id = _create_account(app, "commanduser", ["chat.access"])
    client = app.test_client()
    _login_as(client, account_id)

    with patch.object(chat_index, "commands") as fake_commands, patch.object(
        chat_index.router, "run_chat"
    ) as fake_run_chat:
        fake_commands.execute_command.return_value = "OTP sent."
        response = client.post("/chat/api/chat", json={"question": "/otp get_otp", "history": []})

    assert response.status_code == 200
    body = response.get_json()
    assert body["response"] == "OTP sent."
    assert body["kind"] == "command"
    fake_run_chat.assert_not_called()
    fake_commands.execute_command.assert_called_once_with("/otp get_otp", [])


def test_chat_api_non_command_input_still_uses_the_llm_router(tmp_path, monkeypatch):
    app = _build_chat_test_app(tmp_path, monkeypatch)
    account_id = _create_account(app, "noncommanduser", ["chat.access"])
    client = app.test_client()
    _login_as(client, account_id)

    from src.services.llm.base import ChatResult

    fake_result = ChatResult(response="hi back", provider_id="openai", model="gpt-5.6-sol")
    with patch.object(chat_index.router, "run_chat", return_value=fake_result) as fake_run_chat:
        response = client.post("/chat/api/chat", json={"question": "hi", "history": []})

    assert response.status_code == 200
    body = response.get_json()
    assert body["kind"] == "assistant"
    fake_run_chat.assert_called_once()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd chat_app && python -m pytest tests/test_chat_page.py -k command -v`
Expected: FAIL (`chat_index` has no attribute `commands`; `body["kind"]` KeyError)

- [ ] **Step 3: Implement the wiring**

In `chat_app/src/pages/Chat/__index__.py`, add the import next to the other `src.services` imports:

```python
from src.services import chats_store, commands, log_service
```

(replacing the existing `from src.services import chats_store, log_service` line).

Then replace the whole `chat_api()` function body, from `data = request.get_json(silent=True) or {}` through the final `return jsonify(...)`, with:

```python
    data = request.get_json(silent=True) or {}
    question = (data.get("question") or "").strip()
    if not question:
        return jsonify({"response": "Please enter a question."})

    is_command = question.startswith("/")
    tools_used: list[str] = []
    tool_calls: list[ToolCallRecord] = []
    recursive_rounds: list[RecursiveRoundRecord] = []
    provider_id = ""
    model_used = ""
    total_tokens = None
    llm_history = [{"role": m.get("role"), "content": m.get("content")} for m in data.get("history", [])]

    chat_id = data.get("chat_id")
    if chat_id is not None:
        if chats_store.get_chat(settings.chats_db_path, current_user.username, chat_id) is None:
            chat_id = None
    if chat_id is None:
        try:
            chat_id = chats_store.save_chat(settings.chats_db_path, current_user.username, None, [])
        except Exception as error:  # noqa: BLE001 - persistence must not block the chat answer itself
            log_service.log_error(
                db.session, current_user, source="chat.start",
                message=f"{type(error).__name__}: {error}"[:_MESSAGE_MAX], details=traceback.format_exc(),
            )
            chat_id = None

    start = time.monotonic()
    if is_command:
        # A "/" command is a direct tool call, never the LLM - see
        # docs/superpowers/specs/2026-08-23-chat-slash-commands-design.md.
        response_text = commands.execute_command(question, data.get("enabled_extensions", []))
    else:
        try:
            result = router.run_chat(
                question,
                llm_history,
                data.get("provider"),
                data.get("model"),
                data.get("enabled_extensions", []),
                chat_id=chat_id,
            )
            response_text = result.response
            tools_used = result.tools_used
            tool_calls = result.tool_calls
            recursive_rounds = result.recursive_rounds
            provider_id = result.provider_id
            model_used = result.model
            total_tokens = result.total_tokens
        except ValueError as error:
            # Deliberately verbatim: the router raises these with wording meant
            # for whoever is chatting ("Claude is rate-limited right now - try
            # again in 42s, or pick another provider"). No internals, safe to
            # show as-is.
            response_text = f"❌ {error}"
        except Exception as error:  # noqa: BLE001 - unplanned; text is untrusted for display
            log_service.log_error(
                db.session, current_user, source="chat.answer",
                message=f"{type(error).__name__}: {error}"[:_MESSAGE_MAX], details=traceback.format_exc(),
            )
            response_text = "❌ Something went wrong while answering your question. Check the Logs page (Errors tab) for details."
    elapsed_seconds = round(time.monotonic() - start, 1)

    history_in = list(data.get("history", []))
    current_turn = [{"role": "user", "content": question}]
    if history_in and history_in[-1] == current_turn[0]:
        current_turn = []
    assistant_entry: dict = {"role": "assistant", "content": response_text, "elapsed_seconds": elapsed_seconds}
    if is_command:
        assistant_entry["kind"] = "command"
    if provider_id:
        assistant_entry["provider_id"] = provider_id
    if model_used:
        assistant_entry["model"] = model_used
    if total_tokens is not None:
        assistant_entry["total_tokens"] = total_tokens
    if recursive_rounds:
        assistant_entry["recursive_rounds"] = len(recursive_rounds)
    transcript = history_in + current_turn + [assistant_entry]
    try:
        chat_id = chats_store.save_chat(settings.chats_db_path, current_user.username, chat_id, transcript)
    except chats_store.UnknownChat:
        try:
            chat_id = chats_store.save_chat(settings.chats_db_path, current_user.username, None, transcript)
        except Exception as error:  # noqa: BLE001 - persistence must not break the chat answer itself
            log_service.log_error(
                db.session, current_user, source="chat.save",
                message=f"{type(error).__name__}: {error}"[:_MESSAGE_MAX], details=traceback.format_exc(),
            )
            chat_id = None
    except Exception as error:  # noqa: BLE001 - persistence must not break the chat answer itself
        log_service.log_error(
            db.session, current_user, source="chat.save",
            message=f"{type(error).__name__}: {error}"[:_MESSAGE_MAX], details=traceback.format_exc(),
        )
        chat_id = None

    if chat_id is not None:
        try:
            trace_message = f"{question[:80]} → {provider_id or 'error'}/{model_used or '-'}, {elapsed_seconds}s"
            trace_details = json.dumps(
                {
                    "tool_calls": [
                        {"name": c.name, "arguments": c.arguments, "result": c.result} for c in tool_calls
                    ],
                    "recursive_rounds": [
                        {"round": r.round, "response": r.response, "converged": r.converged}
                        for r in recursive_rounds
                    ],
                    "response": response_text,
                    "total_tokens": total_tokens,
                }
            )
            log_service.log_chat_trace(
                db.session, current_user, source="chat.turn",
                message=trace_message[:_TRACE_MESSAGE_MAX], details=trace_details,
            )
        except Exception as error:  # noqa: BLE001 - a trace write must not break the chat answer itself
            log_service.log_error(
                db.session, current_user, source="chat.trace",
                message=f"{type(error).__name__}: {error}"[:_MESSAGE_MAX], details=traceback.format_exc(),
            )

    return jsonify(
        {
            "response": response_text,
            "tools_used": tools_used,
            "provider_id": provider_id,
            "model": model_used,
            "total_tokens": total_tokens,
            "elapsed_seconds": elapsed_seconds,
            "recursive_rounds": len(recursive_rounds),
            "chat_id": chat_id,
            "kind": "command" if is_command else "assistant",
        }
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd chat_app && python -m pytest tests/test_chat_page.py -v`
Expected: PASS (every test in the file, including the two new ones)

- [ ] **Step 5: Commit**

```bash
git add chat_app/src/pages/Chat/__index__.py chat_app/tests/test_chat_page.py
git commit -m "feat: bypass the LLM router for slash-command chat input"
```

---

### Task 7: `GET /api/commands` route for the frontend registry

**Files:**
- Modify: `chat_app/src/pages/Chat/__index__.py` (add a route near `extensions_api`, around line 52-61)
- Test: `chat_app/tests/test_chat_page.py`

**Interfaces:**
- Consumes: `src.services.commands.build_command_registry`, `src.services.commands.RegisteredCommand`, `src.services.commands.CommandParam` (Task 5).
- Produces: `GET /chat/api/commands?enabled_extensions=a,b,c` returning `{capability_id: {tool_id: {"description": str, "params": [{"name": str, "required": bool, "type": str}, ...]}, ...}, ...}`.

- [ ] **Step 1: Write the failing test**

Add to `chat_app/tests/test_chat_page.py` (after the two tests added in Task 6):

```python
def test_commands_api_returns_the_registry_as_json(tmp_path, monkeypatch):
    app = _build_chat_test_app(tmp_path, monkeypatch)
    account_id = _create_account(app, "commandsapiuser", ["chat.access"])
    client = app.test_client()
    _login_as(client, account_id)

    fake_registry = {
        "otp": {
            "get_otp": commands.RegisteredCommand(
                capability="otp",
                name="get_otp",
                description="generate otp",
                tool_name="request_otp_tool",
                params=[commands.CommandParam(name="recipient", required=False, type="string")],
            )
        }
    }
    with patch.object(chat_index.commands, "build_command_registry", return_value=fake_registry) as fake_build:
        response = client.get("/chat/api/commands?enabled_extensions=reference,other")

    assert response.status_code == 200
    assert response.get_json() == {
        "otp": {
            "get_otp": {
                "description": "generate otp",
                "params": [{"name": "recipient", "required": False, "type": "string"}],
            }
        }
    }
    fake_build.assert_called_once_with(["reference", "other"])


def test_commands_api_requires_chat_access_permission(tmp_path, monkeypatch):
    app = _build_chat_test_app(tmp_path, monkeypatch)
    account_id = _create_account(app, "nocommandsapiaccess", [])
    client = app.test_client()
    _login_as(client, account_id)

    response = client.get("/chat/api/commands")

    assert response.status_code == 403
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd chat_app && python -m pytest tests/test_chat_page.py -k commands_api -v`
Expected: FAIL with a 404 (route doesn't exist yet)

- [ ] **Step 3: Implement the route**

In `chat_app/src/pages/Chat/__index__.py`, add right after `extensions_api()` (after its `return jsonify(...)` line, before `def _forward_extension_error`):

```python
@blueprint.route("/api/commands")
@require_permission("chat.access")
def commands_api():
    enabled = request.args.get("enabled_extensions", "")
    enabled_extensions = [e for e in enabled.split(",") if e]
    registry = commands.build_command_registry(enabled_extensions)
    return jsonify(
        {
            capability: {
                tool_id: {
                    "description": entry.description,
                    "params": [
                        {"name": p.name, "required": p.required, "type": p.type} for p in entry.params
                    ],
                }
                for tool_id, entry in tools.items()
            }
            for capability, tools in registry.items()
        }
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd chat_app && python -m pytest tests/test_chat_page.py -v`
Expected: PASS (every test in the file)

- [ ] **Step 5: Commit**

```bash
git add chat_app/src/pages/Chat/__index__.py chat_app/tests/test_chat_page.py
git commit -m "feat: add GET /api/commands for the frontend command registry"
```

---

### Task 8: Bigger chat box (CSS only)

**Files:**
- Modify: `chat_app/src/pages/Chat/styles.css:33-37,62-71,153-160`

**Interfaces:** none (pure styling, no behavior change).

- [ ] **Step 1: Widen the page and taller the log**

In `chat_app/src/pages/Chat/styles.css`, change:

```css
.page-content {
  max-width: 720px;
  margin: 40px auto;
  padding: 0 20px;
}
```

to:

```css
.page-content {
  max-width: 960px;
  margin: 40px auto;
  padding: 0 20px;
}
```

Change:

```css
#log {
  min-height: 320px;
  max-height: 70vh;
  border: 1px solid var(--panel-border);
  border-radius: 10px;
  padding: 4px;
  margin-bottom: 12px;
  background: white;
  overflow-y: auto;
}
```

to:

```css
#log {
  min-height: 480px;
  max-height: 75vh;
  border: 1px solid var(--panel-border);
  border-radius: 10px;
  padding: 4px;
  margin-bottom: 12px;
  background: white;
  overflow-y: auto;
}
```

Change:

```css
#row { display: flex; gap: 8px; }
#q {
  flex: 1;
  padding: 10px 12px;
  border: 1px solid var(--panel-border);
  border-radius: 6px;
  font-size: 14px;
}
```

to:

```css
#row { display: flex; gap: 8px; }
#q-wrap { position: relative; flex: 1; }
#q {
  width: 100%;
  padding: 14px 16px;
  border: 1px solid var(--panel-border);
  border-radius: 6px;
  font-size: 15px;
}
```

(`#q-wrap` is added here in preparation for Task 10's autocomplete dropdown, which needs a positioned parent around `#q` — see that task for the matching `chat.html` markup change. `#q` itself switches from `flex: 1` to `width: 100%` since `#q-wrap` now carries the flex sizing.)

- [ ] **Step 2: Manually verify in-browser**

Start the app (`python -m chat_app.run` or the project's existing run script), open `/chat/`, and confirm the log area and input are visibly larger than before. This is a pure CSS change with no automated test in this repo's suite (there's no CSS regression test here) — leave this check to whoever reviews the running app.

- [ ] **Step 3: Commit**

```bash
git add chat_app/src/pages/Chat/styles.css
git commit -m "style: make the chat log and input larger"
```

---

### Task 9: Render command results distinctly in the chat log

**Files:**
- Modify: `chat_app/src/pages/Chat/script.js:718,726,832-833`

**Interfaces:**
- Consumes: `data.kind` / `message.kind` — `"command"` or `"assistant"`, from Task 6/7's JSON shapes.

- [ ] **Step 1: Update `send()`'s success handler**

In `chat_app/src/pages/Chat/script.js`, change (around line 716-718):

```js
    const finalTimerText = formatTimerText(elapsedMs, data.total_tokens, modelLabel(data.provider_id, data.model), data.recursive_rounds);
    timerEl.textContent = finalTimerText;
    const assistantWrap = appendMsg('assistant', data.response);
```

to:

```js
    const finalTimerText = formatTimerText(elapsedMs, data.total_tokens, modelLabel(data.provider_id, data.model), data.recursive_rounds);
    timerEl.textContent = finalTimerText;
    // A command result never came from the LLM - render it with the
    // amber "system" style instead of the green "assistant" one, even
    // though the persisted role/history entry stays "assistant" (see
    // below) so it still reads correctly as context on later LLM turns.
    const displayRole = data.kind === 'command' ? 'system' : 'assistant';
    const assistantWrap = appendMsg(displayRole, data.response);
```

Then change (around line 726):

```js
    const assistantTurn = { role: 'assistant', content: data.response, elapsed_seconds: data.elapsed_seconds };
```

to:

```js
    const assistantTurn = { role: 'assistant', content: data.response, elapsed_seconds: data.elapsed_seconds };
    if (data.kind === 'command') assistantTurn.kind = 'command';
```

- [ ] **Step 2: Update `loadChat()`'s replay**

Change (around line 831-833):

```js
    for (const message of chat.messages) {
      const wrap = appendMsg(message.role, message.content);
      const turn = { role: message.role, content: message.content };
```

to:

```js
    for (const message of chat.messages) {
      const displayRole = message.kind === 'command' ? 'system' : message.role;
      const wrap = appendMsg(displayRole, message.content);
      const turn = { role: message.role, content: message.content };
      if (message.kind) turn.kind = message.kind;
```

- [ ] **Step 3: Manually verify in-browser**

Send a normal chat message and confirm it still renders green ("Assistant" label). Once Task 6/7 are deployed together with a real `/otp get_otp` command available, sending `/otp get_otp` should render with the amber system style and no "Assistant" label, and reloading that same chat (refresh the page) should render it the same way. Leave this check to whoever reviews the running app — this repo has no JS test runner (see the plan's Tech Stack note).

- [ ] **Step 4: Commit**

```bash
git add chat_app/src/pages/Chat/script.js
git commit -m "feat: render command results with the system style, not assistant"
```

---

### Task 10: Cascading capability → tool → param autocomplete

**Files:**
- Modify: `chat_app/src/pages/Chat/chat.html:21-24` (wrap `#q`, add the suggestion list)
- Modify: `chat_app/src/pages/Chat/styles.css` (add `.cmd-suggestions` styles)
- Modify: `chat_app/src/pages/Chat/script.js` (add `loadCommands()`, suggestion computation/rendering/acceptance, and wire it into the existing input/keydown/init/extension-toggle code)

**Interfaces:**
- Consumes: `GET /chat/api/commands` (Task 7).

- [ ] **Step 1: Update the markup**

In `chat_app/src/pages/Chat/chat.html`, change:

```html
    <div id="row">
      <input id="q" type="text" placeholder="Ask a question...">
      <button id="send-btn" type="button">Send</button>
    </div>
```

to:

```html
    <div id="row">
      <div id="q-wrap">
        <input id="q" type="text" placeholder="Ask a question... (start with / for commands)" autocomplete="off">
        <ul id="cmd-suggestions" class="cmd-suggestions hidden"></ul>
      </div>
      <button id="send-btn" type="button">Send</button>
    </div>
```

- [ ] **Step 2: Add the dropdown styles**

In `chat_app/src/pages/Chat/styles.css`, add after the `#q:focus-visible, select:focus-visible, button:focus-visible { ... }` rule (around line 165):

```css
.cmd-suggestions {
  position: absolute;
  bottom: 100%;
  left: 0;
  right: 0;
  margin: 0 0 4px;
  padding: 4px;
  list-style: none;
  background: white;
  border: 1px solid var(--panel-border);
  border-radius: 8px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.12);
  max-height: 220px;
  overflow-y: auto;
  z-index: 10;
}
.cmd-suggestions.hidden { display: none; }
.cmd-suggestion {
  padding: 6px 10px;
  border-radius: 6px;
  cursor: pointer;
  font-size: 13px;
  display: flex;
  justify-content: space-between;
  gap: 8px;
}
.cmd-suggestion.active { background: var(--code-bg); }
.cmd-suggestion-desc { color: var(--ink-muted); font-size: 12px; white-space: nowrap; }
```

- [ ] **Step 3: Add the JS state, computation, and rendering**

In `chat_app/src/pages/Chat/script.js`, add near the top with the other module-level state (after the existing `let extensionsById = {};` block, around line 10):

```js
let commandsRegistry = {}; // capability -> { toolId: { description, params: [{name, required, type}] } }
let currentSuggestions = []; // [{ stage: 'capability'|'tool'|'param', text, display, hint }]
let activeSuggestionIndex = -1;
```

Add these functions (a good spot is right after `currentEnabledExtensions()`, around line 351):

```js
async function loadCommands() {
  try {
    const params = new URLSearchParams({ enabled_extensions: currentEnabledExtensions().join(',') });
    const res = await fetch(`/chat/api/commands?${params}`);
    commandsRegistry = await res.json();
  } catch (err) {
    // Suggestions are a convenience, not required to send a command by
    // hand - a failed fetch just means no autocomplete this cycle.
    commandsRegistry = {};
  }
}

function computeCommandSuggestions(value) {
  if (!value.startsWith('/')) return [];
  const body = value.slice(1);
  const spaceIndex1 = body.indexOf(' ');

  if (spaceIndex1 === -1) {
    const partial = body;
    return Object.keys(commandsRegistry)
      .filter(cap => cap.startsWith(partial))
      .sort()
      .map(cap => ({ stage: 'capability', text: cap, display: `/${cap}`, hint: '' }));
  }

  const capability = body.slice(0, spaceIndex1);
  const tools = commandsRegistry[capability];
  if (!tools) return [];
  const afterCapability = body.slice(spaceIndex1 + 1);
  const spaceIndex2 = afterCapability.indexOf(' ');

  if (spaceIndex2 === -1) {
    const partial = afterCapability;
    return Object.keys(tools)
      .filter(t => t.startsWith(partial))
      .sort()
      .map(t => ({ stage: 'tool', text: t, display: t, hint: tools[t].description }));
  }

  const toolId = afterCapability.slice(0, spaceIndex2);
  const tool = tools[toolId];
  if (!tool) return [];
  const paramsText = afterCapability.slice(spaceIndex2 + 1);
  const endsWithSpace = paramsText.endsWith(' ') || paramsText.length === 0;
  const tokens = paramsText.trim().length ? paramsText.trim().split(/\s+/) : [];
  const typedNames = new Set(tokens.map(t => t.split('=')[0]).filter(Boolean));
  const currentToken = !endsWithSpace && tokens.length ? tokens[tokens.length - 1] : '';
  if (currentToken.includes('=')) return []; // already typing a value, nothing to suggest

  return tool.params
    .filter(p => !typedNames.has(p.name) && p.name.startsWith(currentToken))
    .sort((a, b) => Number(b.required) - Number(a.required) || a.name.localeCompare(b.name))
    .map(p => ({ stage: 'param', text: `${p.name}=`, display: `${p.name}=`, hint: p.required ? 'required' : 'optional' }));
}

function renderCommandSuggestions(suggestions) {
  currentSuggestions = suggestions;
  activeSuggestionIndex = suggestions.length ? 0 : -1;
  const list = document.getElementById('cmd-suggestions');
  list.innerHTML = '';
  suggestions.forEach((item, index) => {
    const li = document.createElement('li');
    li.className = `cmd-suggestion${index === 0 ? ' active' : ''}`;
    const label = document.createElement('span');
    label.textContent = item.display;
    li.appendChild(label);
    if (item.hint) {
      const hint = document.createElement('span');
      hint.className = 'cmd-suggestion-desc';
      hint.textContent = item.hint;
      li.appendChild(hint);
    }
    li.addEventListener('mousedown', e => {
      e.preventDefault(); // keep focus on #q instead of blurring to the <li>
      acceptSuggestion(item);
    });
    list.appendChild(li);
  });
  list.classList.toggle('hidden', suggestions.length === 0);
}

function hideCommandSuggestions() {
  currentSuggestions = [];
  activeSuggestionIndex = -1;
  document.getElementById('cmd-suggestions').classList.add('hidden');
}

function updateCommandSuggestions() {
  renderCommandSuggestions(computeCommandSuggestions(document.getElementById('q').value));
}

function moveSuggestionActive(delta) {
  if (!currentSuggestions.length) return;
  activeSuggestionIndex = (activeSuggestionIndex + delta + currentSuggestions.length) % currentSuggestions.length;
  [...document.getElementById('cmd-suggestions').children].forEach((li, index) => {
    li.classList.toggle('active', index === activeSuggestionIndex);
  });
}

function acceptSuggestion(item) {
  const input = document.getElementById('q');
  const value = input.value;
  const body = value.slice(1);
  const spaceIndex1 = body.indexOf(' ');

  let newValue;
  if (item.stage === 'capability') {
    newValue = `/${item.text} `;
  } else if (item.stage === 'tool') {
    const capability = body.slice(0, spaceIndex1);
    newValue = `/${capability} ${item.text} `;
  } else {
    const capability = body.slice(0, spaceIndex1);
    const afterCapability = body.slice(spaceIndex1 + 1);
    const spaceIndex2 = afterCapability.indexOf(' ');
    const toolId = afterCapability.slice(0, spaceIndex2);
    const paramsText = afterCapability.slice(spaceIndex2 + 1);
    const endsWithSpace = paramsText.endsWith(' ') || paramsText.length === 0;
    const tokens = paramsText.trim().length ? paramsText.trim().split(/\s+/) : [];
    if (!endsWithSpace && tokens.length) {
      tokens[tokens.length - 1] = item.text;
    } else {
      tokens.push(item.text);
    }
    newValue = `/${capability} ${toolId} ${tokens.join(' ')}`;
  }

  input.value = newValue;
  updateCommandSuggestions();
  input.focus();
}
```

- [ ] **Step 4: Wire it into `send()`, the input/keydown listeners, and the init/extension-toggle code**

In `send()`, add right after `input.value = '';` (around line 626):

```js
  hideCommandSuggestions();
```

Replace the existing keydown listener (around line 1076-1078):

```js
document.getElementById('q').addEventListener('keydown', e => {
  if (e.key === 'Enter') send();
});
```

with:

```js
document.getElementById('q').addEventListener('input', updateCommandSuggestions);
document.getElementById('q').addEventListener('keydown', e => {
  if (currentSuggestions.length) {
    if (e.key === 'ArrowDown') { e.preventDefault(); moveSuggestionActive(1); return; }
    if (e.key === 'ArrowUp') { e.preventDefault(); moveSuggestionActive(-1); return; }
    if (e.key === 'Tab' || e.key === 'Enter') { e.preventDefault(); acceptSuggestion(currentSuggestions[activeSuggestionIndex]); return; }
    if (e.key === 'Escape') { e.preventDefault(); hideCommandSuggestions(); return; }
  }
  if (e.key === 'Enter') send();
});
```

In the extension checkbox's `change` listener (around line 299-307), change:

```js
    checkbox.addEventListener('change', () => {
      if (checkbox.checked) {
        enabledExtensions.add(ext.id);
      } else {
        enabledExtensions.delete(ext.id);
      }
      saveEnabledExtensionsToStorage();
      updateExtToggleButtonLabel();
    });
```

to:

```js
    checkbox.addEventListener('change', () => {
      if (checkbox.checked) {
        enabledExtensions.add(ext.id);
      } else {
        enabledExtensions.delete(ext.id);
      }
      saveEnabledExtensionsToStorage();
      updateExtToggleButtonLabel();
      loadCommands(); // which extension tools count as commands just changed
    });
```

Near the init block at the bottom (around line 1101-1102), change:

```js
loadExtensions();
setInterval(loadExtensions, 15000); // same cadence as the provider poll above
```

to:

```js
loadExtensions();
setInterval(loadExtensions, 15000); // same cadence as the provider poll above

loadCommands();
setInterval(loadCommands, 15000); // same cadence as the extension poll above
```

- [ ] **Step 5: Manually verify in-browser**

Open `/chat/`, type `/`, confirm a dropdown of capability ids appears (e.g. `otp`) and narrows as you keep typing; select one (click or Tab/Enter), confirm the tool-id list appears next; select a tool, confirm the param-name list appears (`required` ones first); confirm ArrowUp/ArrowDown move the highlight, Escape closes the dropdown, and typing something that doesn't start with `/` never shows it. This repo has no JS test runner (see the plan's Tech Stack note) — leave this check to whoever reviews the running app.

- [ ] **Step 6: Commit**

```bash
git add chat_app/src/pages/Chat/chat.html chat_app/src/pages/Chat/styles.css chat_app/src/pages/Chat/script.js
git commit -m "feat: add cascading capability/tool/param autocomplete to the chat input"
```
