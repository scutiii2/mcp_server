"""Tests for tool_capabilities.capability_for_tool()/capability_for_resource()."""

from __future__ import annotations

from src.services.tool_capabilities import capability_for_resource, capability_for_tool


def test_known_builtin_tools_map_to_their_capability_label():
    assert capability_for_tool("get_host_health_tool") == "Host Health"
    assert capability_for_tool("request_otp_tool") == "OTP"
    assert capability_for_tool("verify_otp_tool") == "OTP"


def test_unmapped_tool_falls_back_to_other_rather_than_raising():
    assert capability_for_tool("some_future_tool_not_in_the_map") == "Other"


def test_known_resource_maps_to_its_capability_label():
    assert capability_for_resource("host_health") == "Host Health"


def test_unmapped_resource_falls_back_to_other_rather_than_raising():
    assert capability_for_resource("some_future_resource_not_in_the_map") == "Other"


def test_tool_and_resource_namespaces_are_independent():
    """A resource name colliding with an unrelated tool name shouldn't
    accidentally pick up that tool's label - the two maps are keyed off
    completely separate namespaces."""
    assert capability_for_resource("request_otp_tool") == "Other"
    assert capability_for_tool("host_health") == "Other"
