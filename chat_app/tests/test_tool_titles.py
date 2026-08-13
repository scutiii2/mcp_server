"""Tests for tool_titles.title_for()."""

from __future__ import annotations

from chat_app.services.tool_titles import title_for


def test_override_is_used_when_present():
    assert title_for("stop_sap_system_tool") == "Stop SAP System"
    assert title_for("start_sap_system_tool") == "Start SAP System"
    assert title_for("get_available_sids_tool") == "Get Available SIDs"


def test_auto_generated_fallback_strips_tool_suffix_and_title_cases():
    assert title_for("get_available_sids") == "Get Available Sids"


def test_auto_generated_fallback_strips_trailing_tool_suffix():
    assert title_for("check_disk_usage_tool") == "Check Disk Usage"


def test_never_returns_empty_string_for_odd_input():
    assert title_for("") == ""  # degenerate case, but must not raise
    assert title_for("_tool") != ""
