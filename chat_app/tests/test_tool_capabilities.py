"""Tests for tool_capabilities.py: capability_for_tool()/
capability_for_resource() (reverse lookup over live mcp_server data) and
is_real_capability() (toggle-eligibility). Display labels are a separate
concern - they come from the same live capabilities_meta (title/
command_id, see pages/Capabilities/__index__.py's
_fetch_capabilities_meta_or_empty and _capability_group_meta)."""

from __future__ import annotations

from src.services.tool_capabilities import (
    capability_for_resource,
    capability_for_tool,
    is_real_capability,
    resource_capability_ids,
)

CAPABILITIES_META = {
    "host_health": {"enabled": True, "tools": ["get_host_health_tool"], "resources": ["host_health"]},
    "otp": {"enabled": True, "tools": ["request_otp_tool", "verify_otp_tool"], "resources": []},
    "crafty": {
        "enabled": True,
        "tools": [
            "crafty_world_register",
            "crafty_world_list",
            "crafty_world_start",
            "crafty_world_stop",
            "crafty_world_restart",
            "crafty_world_send_command",
            "crafty_world_get_status",
            "crafty_set_default_base_url",
            "crafty_world_remove",
            "crafty_ping_base_url",
        ],
        "resources": [],
    },
}


def test_known_builtin_tools_map_to_their_capability_id():
    assert capability_for_tool("get_host_health_tool", CAPABILITIES_META) == "host_health"
    assert capability_for_tool("request_otp_tool", CAPABILITIES_META) == "otp"
    assert capability_for_tool("verify_otp_tool", CAPABILITIES_META) == "otp"


def test_crafty_tools_map_to_the_crafty_capability_id():
    for tool_name in CAPABILITIES_META["crafty"]["tools"]:
        assert capability_for_tool(tool_name, CAPABILITIES_META) == "crafty"


def test_unmapped_tool_falls_back_to_other_rather_than_raising():
    assert capability_for_tool("some_future_tool_not_in_the_map", CAPABILITIES_META) == "other"


def test_unmapped_tool_falls_back_to_other_when_capabilities_meta_is_empty():
    """An unreachable mcp_server (see _fetch_capabilities_meta_or_empty)
    degrades to an empty meta dict, not a crash."""
    assert capability_for_tool("get_host_health_tool", {}) == "other"


def test_known_resource_maps_to_its_capability_id():
    assert capability_for_resource("host_health", CAPABILITIES_META) == "host_health"


def test_unmapped_resource_falls_back_to_other_rather_than_raising():
    assert capability_for_resource("some_future_resource_not_in_the_map", CAPABILITIES_META) == "other"


def test_tool_and_resource_namespaces_are_independent():
    """A resource name colliding with an unrelated tool name shouldn't
    accidentally pick up that tool's id - the two maps are keyed off
    completely separate namespaces."""
    assert capability_for_resource("request_otp_tool", CAPABILITIES_META) == "other"
    assert capability_for_tool("host_health", CAPABILITIES_META) == "other"


def test_resource_capability_ids_returns_only_capabilities_owning_a_resource():
    assert resource_capability_ids(CAPABILITIES_META) == {"host_health"}


def test_resource_capability_ids_empty_when_capabilities_meta_is_empty():
    assert resource_capability_ids({}) == set()


def test_is_real_capability_is_true_for_known_ids():
    assert is_real_capability("host_health") is True
    assert is_real_capability("otp") is True


def test_is_real_capability_is_true_for_an_id_not_seen_yet():
    assert is_real_capability("some_future_capability") is True


def test_is_real_capability_is_false_for_the_fallback_group():
    assert is_real_capability("other") is False
