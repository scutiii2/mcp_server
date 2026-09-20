"""Tests for chat_app's "/" command registry, parser, and executor -
see src/services/commands.py. mcp_client itself is mocked throughout,
same convention as test_mcp_client.py."""

from __future__ import annotations

import io
from types import SimpleNamespace
from unittest.mock import patch
from urllib.error import HTTPError

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


def test_build_command_registry_captures_an_optional_params_default_value():
    tool = _tool(
        "register_tool",
        input_schema={
            "properties": {
                "name": {"type": "string"},
                "base_url": {"type": "string", "default": None},
                "verify_ssl": {"type": "boolean", "default": True},
            },
            "required": ["name"],
        },
    )
    specs = [{"capability": "widgets", "name": "register", "description": "register", "tool_name": "register_tool"}]
    with patch.object(commands.mcp_client, "fetch_commands", return_value=specs), patch.object(
        commands.mcp_client, "list_tools", return_value=[tool]
    ):
        registry = commands.build_command_registry([])

    by_name = {p.name: p for p in registry["widgets"]["register"].params}
    assert by_name["name"].has_default is False
    assert by_name["base_url"].has_default is True
    assert by_name["base_url"].default is None
    assert by_name["verify_ssl"].has_default is True
    assert by_name["verify_ssl"].default is True


def test_build_command_registry_reads_a_params_format_metadata():
    tool = _tool(
        "parse_tool",
        input_schema={
            "properties": {
                "file_path": {"type": "string", "format": "file"},
                "system_label": {"type": "string"},
            },
            "required": ["file_path"],
        },
    )
    specs = [{"capability": "server", "name": "parse", "description": "parse", "tool_name": "parse_tool"}]
    with patch.object(commands.mcp_client, "fetch_commands", return_value=specs), patch.object(
        commands.mcp_client, "list_tools", return_value=[tool]
    ):
        registry = commands.build_command_registry([])

    by_name = {p.name: p for p in registry["server"]["parse"].params}
    assert by_name["file_path"].format == "file"
    assert by_name["system_label"].format is None


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


def test_build_command_registry_adds_a_synthetic_help_entry_for_a_built_in_capability():
    with patch.object(commands.mcp_client, "fetch_commands", return_value=_otp_command_specs()), patch.object(
        commands.mcp_client, "list_tools", return_value=_otp_tools()
    ):
        registry = commands.build_command_registry([])

    help_entry = registry["otp"]["help"]
    assert help_entry.tool_name == "help"
    param_names = {p.name for p in help_entry.params}
    assert param_names == {"target", "command"}


def test_build_command_registry_help_entrys_command_examples_list_the_real_commands():
    with patch.object(commands.mcp_client, "fetch_commands", return_value=_otp_command_specs()), patch.object(
        commands.mcp_client, "list_tools", return_value=_otp_tools()
    ):
        registry = commands.build_command_registry([])

    command_param = next(p for p in registry["otp"]["help"].params if p.name == "command")
    assert command_param.examples == ["get_otp", "verify_otp"]


def test_build_command_registry_help_entrys_target_examples_are_the_four_targets():
    with patch.object(commands.mcp_client, "fetch_commands", return_value=_otp_command_specs()), patch.object(
        commands.mcp_client, "list_tools", return_value=_otp_tools()
    ):
        registry = commands.build_command_registry([])

    target_param = next(p for p in registry["otp"]["help"].params if p.name == "target")
    assert target_param.examples == ["all", "tools", "commands", "workflow"]
    assert target_param.has_default is True
    assert target_param.default == "all"


def test_build_command_registry_does_not_add_help_for_an_extension_only_capability():
    ext_tools = [_tool("reference__echo", input_schema={"properties": {}, "required": []})]
    with patch.object(commands.mcp_client, "fetch_commands", return_value=[]), patch.object(
        commands.mcp_client, "list_tools", return_value=ext_tools
    ):
        registry = commands.build_command_registry(["reference"])

    assert "help" not in registry["reference"]


def test_execute_command_help_still_takes_the_special_path_even_though_it_is_now_registered():
    # The synthetic registry entry must never actually be dispatched
    # through mcp_client.call_tool() - execute_command()'s "tool == help"
    # check has to win before the registry lookup gets a chance to.
    with patch.object(commands.mcp_client, "fetch_commands", return_value=_otp_command_specs()), patch.object(
        commands.mcp_client, "list_tools", return_value=_otp_tools()
    ), patch.object(commands.mcp_client, "call_tool") as call_tool, patch.object(
        commands.mcp_client, "fetch_help", return_value={"message": "ok"}
    ) as fetch_help:
        result = commands.execute_command("/otp help", [])

    call_tool.assert_not_called()
    fetch_help.assert_called_once()
    assert not result.startswith("❌")


# --- /help (bare, top-level) -------------------------------------------------


def test_execute_command_bare_help_calls_fetch_help_index():
    fake_index = {
        "message": "...",
        "capabilities": [{"capability": "/otp", "label": "OTP", "summary": "...", "commands": "get_otp, help"}],
    }
    with patch.object(commands.mcp_client, "fetch_help_index", return_value=fake_index) as fetch_help_index:
        result = commands.execute_command("/help", [])

    fetch_help_index.assert_called_once_with()
    assert "/otp" in result
    assert not result.startswith("❌")


def test_execute_command_bare_help_never_calls_fetch_commands_or_the_registry():
    # Bare "/help" must short-circuit before parse_command()/the registry
    # even runs - parse_command() itself would reject a one-word command.
    with patch.object(commands.mcp_client, "fetch_help_index", return_value={"message": "ok"}), patch.object(
        commands.mcp_client, "fetch_commands"
    ) as fetch_commands:
        commands.execute_command("/help", [])

    fetch_commands.assert_not_called()


def test_execute_command_bare_help_surfaces_mcp_server_error_body():
    error_body = io.BytesIO(b'{"error": "mcp_server unreachable"}')
    http_error = HTTPError("http://mcp/commands/help", 502, "Bad Gateway", {}, error_body)
    with patch.object(commands.mcp_client, "fetch_help_index", side_effect=http_error):
        result = commands.execute_command("/help", [])

    assert result.startswith("❌")
    assert "mcp_server unreachable" in result


def test_execute_command_does_not_treat_a_help_flavored_capability_name_as_bare_help():
    # "/help_something" is a normal (if unregistered) capability name -
    # the bare-"/help" check must not fire on a prefix match.
    with patch.object(commands.mcp_client, "fetch_commands", return_value=[]), patch.object(
        commands.mcp_client, "list_tools", return_value=[]
    ), patch.object(commands.mcp_client, "fetch_help_index") as fetch_help_index:
        result = commands.execute_command("/help_something get_otp", [])

    fetch_help_index.assert_not_called()
    assert result.startswith("❌")
    assert "help_something" in result


# --- execute_command ---------------------------------------------------------


def test_execute_command_happy_path_calls_call_tool_with_coerced_arguments():
    with patch.object(commands.mcp_client, "fetch_commands", return_value=_otp_command_specs()), patch.object(
        commands.mcp_client, "list_tools", return_value=_otp_tools()
    ), patch.object(commands.mcp_client, "call_tool", return_value="OTP sent.") as call_tool:
        result = commands.execute_command("/otp get_otp recipient=a@example.com", [])

    assert result == "OTP sent."
    call_tool.assert_called_once_with("request_otp_tool", {"recipient": "a@example.com"}, headers=None)


def test_execute_command_forwards_on_progress_to_call_tool():
    on_progress = lambda message: None  # noqa: E731
    with patch.object(commands.mcp_client, "fetch_commands", return_value=_otp_command_specs()), patch.object(
        commands.mcp_client, "list_tools", return_value=_otp_tools()
    ), patch.object(commands.mcp_client, "call_tool", return_value="OTP sent.") as call_tool:
        commands.execute_command("/otp get_otp recipient=a@example.com", [], on_progress=on_progress)

    call_tool.assert_called_once_with(
        "request_otp_tool", {"recipient": "a@example.com"}, headers=None, on_progress=on_progress
    )


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
    call_tool.assert_called_once_with("count_tool", {"n": 5}, headers=None)


# --- identity injection -------------------------------------------------


def _identity_tool(name):
    # No identity field in the schema at all - it's no longer a declared
    # tool parameter (see mcp_server's services/identity_context.py); the
    # caller's identity is attached out-of-band as an HTTP header instead
    # (mcp_client.call_tool's `headers`), never part of `arguments`.
    return _tool(
        name,
        input_schema={
            "properties": {"system_name": {"type": "string"}},
            "required": ["system_name"],
        },
    )


def test_execute_command_sends_requester_email_header_for_email_identity_tools():
    tool = _identity_tool("tool_server_start")
    specs = [{"capability": "server", "name": "start", "description": "start", "tool_name": "tool_server_start"}]
    fake_user = SimpleNamespace(email="alice@example.com", username="alice")
    with patch.object(commands.mcp_client, "fetch_commands", return_value=specs), patch.object(
        commands.mcp_client, "list_tools", return_value=[tool]
    ), patch.object(commands.mcp_client, "call_tool", return_value="ok") as call_tool, patch.object(
        commands, "current_user", fake_user
    ), patch.dict(commands._IDENTITY_INJECTED_TOOLS, {"tool_server_start": "email"}):
        commands.execute_command("/server start system_name=srv-demo", [])

    call_tool.assert_called_once_with(
        "tool_server_start", {"system_name": "srv-demo"},
        headers={"X-Requester-Email": "alice@example.com"},
    )


def test_execute_command_sends_requester_username_header_for_username_identity_tools():
    tool = _identity_tool("tool_server_restart")
    specs = [{"capability": "server", "name": "restart", "description": "restart", "tool_name": "tool_server_restart"}]
    fake_user = SimpleNamespace(email="alice@example.com", username="alice")
    with patch.object(commands.mcp_client, "fetch_commands", return_value=specs), patch.object(
        commands.mcp_client, "list_tools", return_value=[tool]
    ), patch.object(commands.mcp_client, "call_tool", return_value="ok") as call_tool, patch.object(
        commands, "current_user", fake_user
    ), patch.dict(commands._IDENTITY_INJECTED_TOOLS, {"tool_server_restart": "username"}):
        commands.execute_command("/server restart system_name=srv-demo", [])

    call_tool.assert_called_once_with(
        "tool_server_restart", {"system_name": "srv-demo"},
        headers={"X-Requester-Username": "alice"},
    )


# --- /<capability> help -----------------------------------------------------


def test_execute_command_help_calls_fetch_help_with_target_and_formats_result():
    with patch.object(commands.mcp_client, "fetch_commands", return_value=_otp_command_specs()), patch.object(
        commands.mcp_client, "list_tools", return_value=_otp_tools()
    ), patch.object(
        commands.mcp_client,
        "fetch_help",
        return_value={"message": "help text", "tools": [{"tool": "request_otp_tool"}]},
    ) as fetch_help:
        result = commands.execute_command("/otp help target=tools", [])

    fetch_help.assert_called_once_with("otp", target="tools", command=None)
    assert "help text" in result
    assert "request_otp_tool" in result


def test_execute_command_help_defaults_target_to_all():
    with patch.object(commands.mcp_client, "fetch_commands", return_value=_otp_command_specs()), patch.object(
        commands.mcp_client, "list_tools", return_value=_otp_tools()
    ), patch.object(commands.mcp_client, "fetch_help", return_value={"message": "ok"}) as fetch_help:
        commands.execute_command("/otp help", [])

    fetch_help.assert_called_once_with("otp", target="all", command=None)


def test_execute_command_help_passes_command_param_through():
    with patch.object(commands.mcp_client, "fetch_commands", return_value=_otp_command_specs()), patch.object(
        commands.mcp_client, "list_tools", return_value=_otp_tools()
    ), patch.object(commands.mcp_client, "fetch_help", return_value={"message": "ok"}) as fetch_help:
        commands.execute_command("/otp help command=get_otp", [])

    fetch_help.assert_called_once_with("otp", target="all", command="get_otp")


def test_execute_command_help_does_not_require_help_to_be_a_registered_command():
    # "help" is deliberately never in the registry (see commands.py's
    # module docstring) - it must still work for a capability whose real
    # commands ARE registered, without hitting the "Unknown command"
    # branch that would fire if it looked help up in the registry.
    with patch.object(commands.mcp_client, "fetch_commands", return_value=_otp_command_specs()), patch.object(
        commands.mcp_client, "list_tools", return_value=_otp_tools()
    ), patch.object(commands.mcp_client, "fetch_help", return_value={"message": "ok"}):
        result = commands.execute_command("/otp help", [])

    assert not result.startswith("❌")


def test_execute_command_help_rejects_unknown_param():
    with patch.object(commands.mcp_client, "fetch_commands", return_value=_otp_command_specs()), patch.object(
        commands.mcp_client, "list_tools", return_value=_otp_tools()
    ):
        result = commands.execute_command("/otp help bogus=1", [])

    assert result.startswith("❌")
    assert "bogus" in result


def test_execute_command_help_reports_unknown_capability():
    with patch.object(commands.mcp_client, "fetch_commands", return_value=_otp_command_specs()), patch.object(
        commands.mcp_client, "list_tools", return_value=_otp_tools()
    ):
        result = commands.execute_command("/nope help", [])

    assert result.startswith("❌")
    assert "nope" in result


def test_execute_command_help_surfaces_mcp_server_error_body():
    error_body = io.BytesIO(b'{"error": "Unknown help target \'bogus\'"}')
    http_error = HTTPError("http://mcp/commands/help/otp", 400, "Bad Request", {}, error_body)
    with patch.object(commands.mcp_client, "fetch_commands", return_value=_otp_command_specs()), patch.object(
        commands.mcp_client, "list_tools", return_value=_otp_tools()
    ), patch.object(commands.mcp_client, "fetch_help", side_effect=http_error):
        result = commands.execute_command("/otp help target=bogus", [])

    assert result.startswith("❌")
    assert "Unknown help target" in result


def test_execute_command_rejects_a_typed_identity_value_since_it_is_not_a_real_param():
    # requested_by_username isn't in the tool's schema at all any more (see
    # _identity_tool above) - typing it on the command line hits the
    # ordinary "unknown param" path rather than silently overriding
    # anything, since there's no tool-schema field left for it to collide
    # with.
    tool = _identity_tool("tool_server_restart")
    specs = [{"capability": "server", "name": "restart", "description": "restart", "tool_name": "tool_server_restart"}]
    fake_user = SimpleNamespace(email="alice@example.com", username="alice")
    with patch.object(commands.mcp_client, "fetch_commands", return_value=specs), patch.object(
        commands.mcp_client, "list_tools", return_value=[tool]
    ), patch.object(commands.mcp_client, "call_tool", return_value="ok") as call_tool, patch.object(
        commands, "current_user", fake_user
    ):
        result = commands.execute_command("/server restart system_name=srv-demo requested_by_username=someone-else", [])

    assert result.startswith("❌")
    assert "requested_by_username" in result
    call_tool.assert_not_called()


def test_params_from_schema_reads_the_input_hints():
    schema = {
        "properties": {
            "capability": {"type": "string", "input": "select", "options_url": "/system/check-capabilities"},
            "level": {"type": "integer", "minimum": 1, "maximum": 5, "input": "range", "step": 1},
            "mode": {"type": "string", "enum": ["fast", "slow"]},
            "note": {"anyOf": [{"type": "string", "maxLength": 20, "pattern": "^[a-z]+$"}, {"type": "null"}]},
        }
    }

    params = {p.name: p for p in commands._params_from_schema(schema)}

    assert params["capability"].input == "select"
    assert params["capability"].options_url == "/system/check-capabilities"
    assert (params["level"].minimum, params["level"].maximum, params["level"].step, params["level"].input) == (1, 5, 1, "range")
    assert params["mode"].enum == ["fast", "slow"]
    assert (params["note"].max_length, params["note"].pattern) == (20, "^[a-z]+$")
