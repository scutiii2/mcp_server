"""Tests for infra/tool_suggestions.py.

Patches at the provider boundary (load_hosts_config, load_email_config,
server_manager_domain.list_apps) rather than re-exercising config
parsing or Docker calls - those are already covered by
test_app_config.py and test_server_manager_domain.py. What's under test
here is only apply_suggestions()'s own behavior: which (tool, param)
pairs it touches, and that a broken provider never breaks the listing.
"""

from __future__ import annotations

from unittest.mock import patch

from mcp import types

from src.capabilities.server_manager.contract import AppInfo, AppListResult
from src.infra import tool_suggestions
from src.infra.app_config import EmailConfig


def _tool(tool_name: str, **properties: dict) -> types.Tool:
    return types.Tool(
        name=tool_name,
        inputSchema={"type": "object", "properties": {k: dict(v) for k, v in properties.items()}},
    )


def test_injects_enum_for_a_registered_tool_and_param():
    tool = _tool("get_host_health_tool", name={"type": "string"})
    with patch("src.infra.tool_suggestions.load_hosts_config", return_value={"zima": None, "desktop": None}):
        tool_suggestions.apply_suggestions([tool])

    assert tool.inputSchema["properties"]["name"]["enum"] == ["zima", "desktop"]


def test_leaves_a_param_with_no_registered_provider_untouched():
    tool = _tool("some_other_tool", name={"type": "string"})
    tool_suggestions.apply_suggestions([tool])

    assert "enum" not in tool.inputSchema["properties"]["name"]


def test_leaves_a_tool_with_no_properties_untouched():
    tool = types.Tool(name="list_apps_tool", inputSchema={"type": "object", "properties": {}})
    tool_suggestions.apply_suggestions([tool])  # must not raise

    assert tool.inputSchema["properties"] == {}


def test_a_raising_provider_drops_only_its_own_field_not_the_whole_tool():
    tool = _tool("get_host_health_tool", name={"type": "string"})
    with patch("src.infra.tool_suggestions.load_hosts_config", side_effect=FileNotFoundError("no config")):
        tool_suggestions.apply_suggestions([tool])  # must not raise

    assert "enum" not in tool.inputSchema["properties"]["name"]


def test_an_empty_result_leaves_no_enum_key_rather_than_an_empty_one():
    tool = _tool("start_app_tool", name={"type": "string"})
    with patch(
        "src.infra.tool_suggestions.server_manager_domain.list_apps",
        return_value=AppListResult(apps=[], report="No apps."),
    ):
        tool_suggestions.apply_suggestions([tool])

    assert "enum" not in tool.inputSchema["properties"]["name"]


def test_server_manager_apps_populate_start_stop_and_restart():
    apps = AppListResult(
        apps=[AppInfo(name="jellyfin", status="running", image="jellyfin/jellyfin")],
        report="jellyfin running",
    )
    tools = [_tool("start_app_tool", name={}), _tool("stop_app_tool", name={}), _tool("restart_app_tool", name={})]
    with patch("src.infra.tool_suggestions.server_manager_domain.list_apps", return_value=apps):
        tool_suggestions.apply_suggestions(tools)

    for tool in tools:
        assert tool.inputSchema["properties"]["name"]["enum"] == ["jellyfin"]


def test_otp_recipients_come_from_the_approver_list():
    config = EmailConfig(
        smtp_server="smtp.example.com",
        smtp_port=587,
        from_address="noreply@example.com",
        approver_emails=["owner@example.com", "backup@example.com"],
    )
    tool = _tool("request_otp_tool", recipient={"type": "string"})
    with patch("src.infra.tool_suggestions.load_email_config", return_value=config):
        tool_suggestions.apply_suggestions([tool])

    assert tool.inputSchema["properties"]["recipient"]["enum"] == ["owner@example.com", "backup@example.com"]
