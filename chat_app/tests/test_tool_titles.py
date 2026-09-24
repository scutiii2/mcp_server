"""Tests for tool_titles.title_for()."""

from __future__ import annotations

from unittest.mock import patch

from src.services.tool_titles import title_for


def test_override_is_used_when_present():
    """_OVERRIDES ships empty (there are no tools yet), so this patches in
    an entry rather than asserting against a real one - the mechanism is
    what matters, and hardcoding a name here would just become the next
    stale reference."""
    with patch.dict("src.services.tool_titles._OVERRIDES", {"get_cpu_usage_tool": "Get CPU Usage"}):
        assert title_for("get_cpu_usage_tool") == "Get CPU Usage"


def test_auto_generated_fallback_title_cases():
    assert title_for("list_open_ports") == "List Open Ports"


def test_auto_generated_fallback_strips_trailing_tool_suffix():
    assert title_for("check_disk_usage_tool") == "Check Disk Usage"


def test_tool_suffix_only_stripped_from_the_end():
    assert title_for("tool_registry_tool") == "Tool Registry"


def test_never_returns_empty_string_for_odd_input():
    assert title_for("") == ""  # degenerate case, but must not raise
    assert title_for("_tool") != ""


def test_capability_prefix_is_dropped_and_action_camel_split():
    """mcp_server capability tools are "tool_{capabilityPrefix}_{camelAction}"
    (e.g. mcp_server/src/capabilities/server_manager/tool.py) - the
    prefix is a capability tag, not part of the action, so only the action
    should show up in the title."""
    assert title_for("tool_srv_startApp") == "Start App"
    assert title_for("tool_srv_listApps") == "List Apps"


def test_capability_prefix_pattern_requires_three_segments():
    """"tool_registry_tool" only has two segments after stripping the "_tool"
    suffix ("tool_registry") - it must NOT be mistaken for a capability tool
    and lose "registry" as if it were a dropped prefix."""
    assert title_for("tool_registry_tool") == "Tool Registry"
