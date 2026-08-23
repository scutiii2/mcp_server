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
