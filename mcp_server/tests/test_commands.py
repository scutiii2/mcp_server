"""Tests for the @command decorator and its registry - see
mcp_server/commands.py. Each test gets its own empty registry via
monkeypatch (swapping the module's _COMMANDS dict for the duration of
the test) rather than mutating the real one in place, so this file
can't clobber registrations other test files rely on being real (e.g.
test_otp_commands.py, which asserts against the actual otp
capability's registrations)."""

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
