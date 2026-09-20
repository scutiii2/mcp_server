"""Tests for tool_capabilities.py: refresh_from() (populating the maps
from a GET /capabilities-shaped response and persisting them to disk),
capability_for_tool()/capability_for_resource() (id lookup), and
label_for_capability()/is_real_capability()/known_capability_ids()
(display + toggle-eligibility).

conftest.py's autouse _isolated_tool_capabilities_cache fixture points
settings.capability_cache_path at a per-test tmp file and resets the
in-memory maps before/after each test, so none of this touches the real
cache file or leaks state between tests."""

from __future__ import annotations

import json
from unittest.mock import patch

from src.services import tool_capabilities
from src.services.tool_capabilities import (
    capability_for_resource,
    capability_for_tool,
    is_real_capability,
    known_capability_ids,
    label_for_capability,
    refresh_from,
    resource_capability_ids,
)

_SAMPLE = [
    {
        "name": "server",
        "enabled": True,
        "label": "Server Manager",
        "tools": ["parse_excel_input_tool", "check_sod_conflicts_tool"],
        "resources": [],
    },
    {
        "name": "reports",
        "enabled": True,
        "label": "Reports",
        "tools": ["tool_reports_list"],
        "resources": [],
    },
]


def test_capability_for_tool_reflects_a_refreshed_response():
    refresh_from(_SAMPLE)

    assert capability_for_tool("parse_excel_input_tool") == "server"
    assert capability_for_tool("check_sod_conflicts_tool") == "server"
    assert capability_for_tool("tool_reports_list") == "reports"


def test_unmapped_tool_falls_back_to_other_rather_than_raising():
    refresh_from(_SAMPLE)

    assert capability_for_tool("some_future_tool_not_in_the_response") == "other"


def test_unmapped_resource_falls_back_to_other_rather_than_raising():
    assert capability_for_resource("some_future_resource_not_in_the_response") == "other"


def test_tool_and_resource_namespaces_are_independent():
    """A resource name colliding with an unrelated tool name shouldn't
    accidentally pick up that tool's id - the two maps are keyed off
    completely separate namespaces."""
    refresh_from(_SAMPLE)

    assert capability_for_resource("tool_reports_list") == "other"
    assert capability_for_tool("reports") == "other"


def test_label_for_capability_returns_the_display_label():
    refresh_from(_SAMPLE)

    assert label_for_capability("server") == "Server Manager"
    assert label_for_capability("reports") == "Reports"
    assert label_for_capability("other") == "Other"


def test_label_for_capability_falls_back_to_the_id_itself():
    """A real capability id this process hasn't seen a label for yet
    still shows *something* meaningful, rather than "Other" (which would
    misleadingly suggest it has no real id at all)."""
    assert label_for_capability("some_future_capability") == "some_future_capability"


def test_is_real_capability_is_true_for_known_ids():
    refresh_from(_SAMPLE)

    assert is_real_capability("reports") is True
    assert is_real_capability("server") is True


def test_is_real_capability_is_true_for_an_id_this_process_has_not_seen():
    assert is_real_capability("some_future_capability") is True


def test_is_real_capability_is_false_for_the_fallback_group():
    assert is_real_capability("other") is False


def test_known_capability_ids_excludes_the_fallback_group():
    refresh_from(_SAMPLE)

    assert known_capability_ids() == {"server", "reports"}


def test_known_capability_ids_bootstraps_from_mcp_server_when_cold():
    """The cold-start gap this behavior exists to close: nothing has
    called refresh_from() yet (no live fetch, no cache on disk), but
    mcp_server IS reachable - known_capability_ids() must fetch it
    itself rather than reporting every real id as unknown just because
    of that ordering accident."""
    with patch("src.services.mcp_client.fetch_capabilities", return_value=_SAMPLE) as fake_fetch:
        assert known_capability_ids() == {"server", "reports"}
    fake_fetch.assert_called_once()

    # The bootstrap's own refresh_from() call left the maps populated -
    # a second call finds ids already known and doesn't fetch again.
    with patch("src.services.mcp_client.fetch_capabilities") as fake_fetch_again:
        assert known_capability_ids() == {"server", "reports"}
    fake_fetch_again.assert_not_called()


def test_known_capability_ids_stays_empty_when_mcp_server_is_unreachable():
    """A genuinely unreachable mcp_server must still report no known ids
    - same behavior as before the bootstrap existed, just reached after
    one failed attempt instead of skipping the attempt entirely."""
    with patch("src.services.mcp_client.fetch_capabilities", side_effect=ConnectionError("refused")):
        assert known_capability_ids() == set()


def test_resource_capability_ids_reflects_a_refreshed_response():
    with_resource = [
        {"name": "server", "enabled": True, "label": "Server Manager", "tools": [], "resources": ["role_kb"]},
    ]

    refresh_from(with_resource)

    assert resource_capability_ids() == {"server"}
    assert capability_for_resource("role_kb") == "server"


def test_refresh_from_replaces_the_previous_response_rather_than_merging():
    refresh_from(_SAMPLE)
    refresh_from([{"name": "other_cap", "enabled": True, "label": "Server Manager", "tools": ["tool_server_start"], "resources": []}])

    assert capability_for_tool("tool_server_start") == "other_cap"
    # "server"/"reports" from the first refresh are gone, not merged in.
    assert capability_for_tool("parse_excel_input_tool") == "other"
    assert known_capability_ids() == {"other_cap"}


def test_refresh_from_persists_to_the_configured_cache_path():
    refresh_from(_SAMPLE)

    saved = json.loads(tool_capabilities.settings.capability_cache_path.read_text(encoding="utf-8"))
    assert saved == _SAMPLE


def test_a_fresh_import_reloads_the_persisted_cache():
    """The scenario this module exists for: mcp_server was reachable at
    some point (refresh_from() ran and cached to disk), the process
    restarts (or, here, the module is reloaded as if it were a fresh
    import), and mcp_server hasn't been reached again yet - the cached
    mapping must still answer correctly rather than everything falling
    back to "other" until the next successful live fetch."""
    refresh_from(_SAMPLE)

    tool_capabilities._apply(tool_capabilities._load_cached())

    assert capability_for_tool("tool_reports_list") == "reports"
    assert label_for_capability("reports") == "Reports"


def test_a_failed_fetch_must_not_call_refresh_from_with_empty_data():
    """Documents the caller contract this module's docstring states:
    refresh_from() overwrites both the in-memory maps and the on-disk
    cache, so a caller must only invoke it with a successful fetch's
    result - calling it with [] on a failed fetch would wipe a good
    cache the moment mcp_server is briefly unreachable."""
    refresh_from(_SAMPLE)

    refresh_from([])  # what a caller must NOT do on a failed fetch

    assert capability_for_tool("tool_reports_list") == "other"
