"""Tests for tool_capabilities.py: capability_for_tool()/
capability_for_resource() (id lookup) and is_real_capability()
(toggle-eligibility). Display labels are no longer this file's concern -
they come live from mcp_server's GET /capabilities (title/command_id,
see pages/Capabilities/__index__.py's _fetch_capabilities_meta_or_empty
and _capability_group_meta)."""

from __future__ import annotations

from src.services.tool_capabilities import (
    capability_for_resource,
    capability_for_tool,
    is_real_capability,
)


def test_known_builtin_tools_map_to_their_capability_id():
    assert capability_for_tool("get_host_health_tool") == "host_health"
    assert capability_for_tool("request_otp_tool") == "otp"
    assert capability_for_tool("verify_otp_tool") == "otp"


def test_crafty_tools_map_to_the_crafty_capability_id():
    assert capability_for_tool("crafty_world_register") == "crafty"
    assert capability_for_tool("crafty_world_list") == "crafty"
    assert capability_for_tool("crafty_world_start") == "crafty"
    assert capability_for_tool("crafty_world_stop") == "crafty"
    assert capability_for_tool("crafty_world_restart") == "crafty"
    assert capability_for_tool("crafty_world_send_command") == "crafty"
    assert capability_for_tool("crafty_world_get_status") == "crafty"
    assert capability_for_tool("crafty_set_default_base_url") == "crafty"
    assert capability_for_tool("crafty_world_remove") == "crafty"
    assert capability_for_tool("crafty_ping_base_url") == "crafty"


def test_unmapped_tool_falls_back_to_other_rather_than_raising():
    assert capability_for_tool("some_future_tool_not_in_the_map") == "other"


def test_known_resource_maps_to_its_capability_id():
    assert capability_for_resource("host_health") == "host_health"


def test_unmapped_resource_falls_back_to_other_rather_than_raising():
    assert capability_for_resource("some_future_resource_not_in_the_map") == "other"


def test_tool_and_resource_namespaces_are_independent():
    """A resource name colliding with an unrelated tool name shouldn't
    accidentally pick up that tool's id - the two maps are keyed off
    completely separate namespaces."""
    assert capability_for_resource("request_otp_tool") == "other"
    assert capability_for_tool("host_health") == "other"


def test_is_real_capability_is_true_for_known_ids():
    assert is_real_capability("host_health") is True
    assert is_real_capability("otp") is True


def test_is_real_capability_is_true_for_an_id_this_map_has_not_caught_up_with():
    assert is_real_capability("some_future_capability") is True


def test_is_real_capability_is_false_for_the_fallback_group():
    assert is_real_capability("other") is False
