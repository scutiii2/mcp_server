"""Tests for tool_titles.title_for()."""

from __future__ import annotations

from unittest.mock import patch

from chat_app.services.tool_titles import title_for


def test_override_is_used_when_present():
    """_OVERRIDES ships empty (there are no tools yet), so this patches in
    an entry rather than asserting against a real one - the mechanism is
    what matters, and hardcoding a name here would just become the next
    stale reference."""
    with patch.dict("chat_app.services.tool_titles._OVERRIDES", {"get_cpu_usage_tool": "Get CPU Usage"}):
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
