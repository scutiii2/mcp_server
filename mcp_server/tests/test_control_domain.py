"""Domain-layer tests - no SSH connection, no MCP server, no network at all.

This is the payoff of keeping business logic out of the @mcp.tool()
function: stop_sap_system's "what does success mean" logic is testable
in milliseconds, in CI, with nothing running.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from mcp_server.capabilities.control.contract import StopSapRequest
from mcp_server.capabilities.control.domain import stop_sap_system
from mcp_server.infra.sap_config import AppConfig, SapServerConfig
from mcp_server.infra.ssh import SSHCommandResult


def test_stop_sap_system_no_server_configured() -> None:
    config = AppConfig(sap_server=[])

    result = stop_sap_system(StopSapRequest(sid="E4G"), config=config)

    assert result.success is False
    assert "E4G" in result.message


def test_stop_sap_system_success() -> None:
    config = AppConfig(
        sap_server=[SapServerConfig(sid="E4G", host="e4g-host", user="root", password="x")]
    )
    fake_ssh = MagicMock()
    fake_ssh.__enter__.return_value = fake_ssh
    fake_ssh.run.return_value = SSHCommandResult(stdout="stopsap completed\n", stderr="", exit_status=0)

    with patch("mcp_server.capabilities.control.domain.SSHClient", return_value=fake_ssh):
        result = stop_sap_system(StopSapRequest(sid="e4g"), config=config)

    assert result.success is True
    assert "completed" in result.message
    fake_ssh.run.assert_called_once_with("su - e4gadm -c 'stopsap'")


def test_stop_sap_system_reports_ssh_error_text() -> None:
    config = AppConfig(sap_server=[SapServerConfig(sid="E4G", host="e4g-host", password="x")])
    fake_ssh = MagicMock()
    fake_ssh.__enter__.return_value = fake_ssh
    fake_ssh.run.return_value = SSHCommandResult(stdout="Error: instance already stopped\n", stderr="", exit_status=0)

    with patch("mcp_server.capabilities.control.domain.SSHClient", return_value=fake_ssh):
        result = stop_sap_system(StopSapRequest(sid="E4G"), config=config)

    assert result.success is False
