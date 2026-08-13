"""Domain-layer tests - no SSH connection, no MCP server, no network at all.

Faithful multi-tier orchestration means the polling loops (_wait_for_down/
_wait_for_green) are exercised for real here, not skipped - but without
any real 5-second sleeps. That works because both loops check state
*before* sleeping: if the mocked SSHClient's run_login_shell already
returns the target state by the second call, the loop returns on its
first internal check and never reaches time.sleep() at all. Tests are
built around that: sequence SSHClient.run_login_shell's return values so
the "already there" state appears exactly when the loop would check it.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from mcp_server.capabilities.control.contract import SapControlRequest
from mcp_server.capabilities.control.domain import get_available_sids, start_sap_system, stop_sap_system
from mcp_server.infra.sap_config import AdditionalAppServer, AppConfig, SapServerConfig
from mcp_server.infra.ssh import SSHCommandResult


def _process_list(state: str) -> SSHCommandResult:
    """Minimal fake sapcontrol GetProcessList output - only what
    _parse_process_state actually reads (comma-separated, 3rd field)."""
    return SSHCommandResult(stdout=f"msg_server, MessageServer, {state}, running\n", stderr="", exit_status=0)


def _mock_ssh(*stdout_sequence: SSHCommandResult):
    """SSHClient(...) always returns the same fake instance regardless of
    args (matching how the domain opens a fresh connection per call), with
    run_login_shell returning each result in order across every call."""
    fake_ssh = MagicMock()
    fake_ssh.__enter__.return_value = fake_ssh
    fake_ssh.run_login_shell.side_effect = list(stdout_sequence)
    return fake_ssh


def _full_server(sid: str = "E4G") -> SapServerConfig:
    return SapServerConfig(
        sid=sid,
        host="e4g-host",
        password="x",
        dbhost="e4g-db",
        ascshost="e4g-ascs",
        pashost="e4g-pas",
        sapadm="e4gadm",
        hanaadm="hdcadm",
        db_nr="02",
        ascs_nr="01",
        pas_nr="00",
        additional_app_servers=[],
    )


def test_get_available_sids_lists_all_configured_systems():
    config = AppConfig(sap_server=[_full_server("E4G"), _full_server("S4E")])

    result = get_available_sids(config)

    assert [s.sid for s in result.systems] == ["E4G", "S4E"]


def test_get_available_sids_prefers_pashost_over_host():
    config = AppConfig(sap_server=[SapServerConfig(sid="E4G", host="fallback-host", pashost="real-pas-host")])

    result = get_available_sids(config)

    assert result.systems[0].host == "real-pas-host"


def test_get_available_sids_falls_back_to_host_when_no_pashost():
    config = AppConfig(sap_server=[SapServerConfig(sid="E4G", host="only-host")])

    result = get_available_sids(config)

    assert result.systems[0].host == "only-host"


def test_stop_sap_system_no_server_configured():
    config = AppConfig(sap_server=[])

    result = stop_sap_system(SapControlRequest(sid="E4G"), config=config)

    assert len(result.results) == 1
    assert result.results[0].success is False
    assert "E4G" in result.results[0].message


def test_stop_sap_system_supports_comma_separated_multi_sid():
    config = AppConfig(sap_server=[])  # neither configured - just proving both get processed

    result = stop_sap_system(SapControlRequest(sid="E4G,S4E"), config=config)

    assert [r.sid for r in result.results] == ["E4G", "S4E"]
    assert all(r.success is False for r in result.results)


def test_stop_sap_system_already_fully_down_is_idempotent_no_op():
    """Every tier already DOWN - each tier gets exactly one GetProcessList
    check and no Stop action, no wait loop entered at all."""
    config = AppConfig(sap_server=[_full_server()])
    fake_ssh = _mock_ssh(
        _process_list("GRAY"),  # PAS check
        _process_list("GRAY"),  # ASCS check
        _process_list("GRAY"),  # DB check
    )

    with patch("mcp_server.capabilities.control.domain.SSHClient", return_value=fake_ssh):
        result = stop_sap_system(SapControlRequest(sid="E4G"), config=config)

    assert result.results[0].success is True
    assert "already stopped" in result.results[0].message
    assert fake_ssh.run_login_shell.call_count == 3  # one check per tier, no actions


def test_stop_sap_system_stops_a_running_tier_and_waits_for_down():
    """PAS is GREEN (needs stopping); ASCS/DB already down. The wait loop
    resolves on its first internal check (mocked as already GRAY), so no
    real sleep happens."""
    config = AppConfig(sap_server=[_full_server()])
    fake_ssh = _mock_ssh(
        _process_list("GREEN"),  # PAS initial check - running
        SSHCommandResult(stdout="", stderr="", exit_status=0),  # PAS Stop action (output unused)
        _process_list("GRAY"),  # PAS wait-loop check - now down, loop exits immediately
        _process_list("GRAY"),  # ASCS check - already down
        _process_list("GRAY"),  # DB check - already down
    )

    with patch("mcp_server.capabilities.control.domain.SSHClient", return_value=fake_ssh):
        result = stop_sap_system(SapControlRequest(sid="E4G"), config=config)

    assert result.results[0].success is True
    assert "Stopping PAS" in result.results[0].message
    assert "PAS fully stopped" in result.results[0].message


def test_start_sap_system_no_server_configured():
    config = AppConfig(sap_server=[])

    result = start_sap_system(SapControlRequest(sid="E4G"), config=config)

    assert result.results[0].success is False
    assert "E4G" in result.results[0].message


def test_start_sap_system_already_fully_green_is_idempotent_no_op():
    config = AppConfig(sap_server=[_full_server()])
    fake_ssh = _mock_ssh(
        _process_list("GREEN"),  # DB check
        _process_list("GREEN"),  # ASCS check
        _process_list("GREEN"),  # PAS check
    )

    with patch("mcp_server.capabilities.control.domain.SSHClient", return_value=fake_ssh):
        result = start_sap_system(SapControlRequest(sid="E4G"), config=config)

    assert result.results[0].success is True
    assert "SAP fully started" in result.results[0].message
    assert fake_ssh.run_login_shell.call_count == 3


def test_start_sap_system_starts_a_down_tier_and_waits_for_green():
    """DB is down (needs starting); ASCS/PAS already green. The wait loop
    resolves on its first internal check (mocked as already GREEN)."""
    config = AppConfig(sap_server=[_full_server()])
    fake_ssh = _mock_ssh(
        _process_list("GRAY"),  # DB initial check - down
        SSHCommandResult(stdout="", stderr="", exit_status=0),  # DB Start action
        _process_list("GREEN"),  # DB wait-loop check - now green, loop exits immediately
        _process_list("GREEN"),  # ASCS check - already green
        _process_list("GREEN"),  # PAS check - already green
    )

    with patch("mcp_server.capabilities.control.domain.SSHClient", return_value=fake_ssh):
        result = start_sap_system(SapControlRequest(sid="E4G"), config=config)

    assert result.results[0].success is True
    assert "Starting DB" in result.results[0].message


def test_start_sap_system_includes_additional_app_servers():
    config = AppConfig(
        sap_server=[
            SapServerConfig(
                sid="E4G", host="e4g-host", password="x",
                dbhost="e4g-db", ascshost="e4g-ascs", pashost="e4g-pas",
                sapadm="e4gadm", hanaadm="hdcadm",
                db_nr="02", ascs_nr="01", pas_nr="00",
                additional_app_servers=[AdditionalAppServer(host="e4g-aas1", instance="02")],
            )
        ]
    )
    fake_ssh = _mock_ssh(
        _process_list("GREEN"),  # DB
        _process_list("GREEN"),  # ASCS
        _process_list("GREEN"),  # PAS
        _process_list("GREEN"),  # AAS
    )

    with patch("mcp_server.capabilities.control.domain.SSHClient", return_value=fake_ssh):
        result = start_sap_system(SapControlRequest(sid="E4G"), config=config)

    assert result.results[0].success is True
    assert fake_ssh.run_login_shell.call_count == 4
