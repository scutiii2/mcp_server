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
