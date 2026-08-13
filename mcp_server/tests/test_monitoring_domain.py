"""Domain-layer tests for monitoring - run_command mocked, no real SSH.

Fake ABAPGetWPTable rows use two DIFFERENT status vocabularies on
purpose, matching a real distinction in the ported logic:
check_work_process_errors checks for the literal strings ERROR/STOPPED/
HOLD/RESTART in the raw status field, while get_work_process_breakdown's
parser maps RUN->GREEN, WAIT/HOLD/RESTART->YELLOW, STOPPED->GRAY. Same
raw field, two different interpretations depending on which tool reads
it - both ported faithfully, not unified into one.
"""

from __future__ import annotations

from unittest.mock import patch

from mcp_server.capabilities.monitoring.contract import DiskUsageRequest, FindLargestFilesRequest, SidRequest
from mcp_server.capabilities.monitoring.domain import (
    check_cpu_usage,
    check_disk_usage,
    check_memory_usage,
    check_work_process_errors,
    debug_raw_process_list,
    find_largest_files,
    get_hana_status,
    get_kernel_version,
    get_sap_process_list,
    get_sap_process_status,
    get_sap_system_health,
    get_work_process_breakdown,
    list_sap_systems,
)
from mcp_server.infra.sap_config import AppConfig, SapServerConfig


def _server(sid: str = "E4G") -> SapServerConfig:
    return SapServerConfig(sid=sid, host="e4g-host", pashost="e4g-pas", sapadm="e4gadm", pas_nr="00", password="x")


def _full_server(sid: str = "E4G") -> SapServerConfig:
    return SapServerConfig(
        sid=sid, host="e4g-host", password="x",
        pashost="e4g-pas", ascshost="e4g-ascs", dbhost="e4g-db",
        sapadm="e4gadm", hanaadm="hdcadm",
        pas_nr="00", ascs_nr="01", db_nr="02",
    )


# ── list_sap_systems ──────────────────────────────────────────────────

def test_list_sap_systems_no_servers():
    assert list_sap_systems(AppConfig(sap_server=[])) == "No SAP systems configured."


def test_list_sap_systems_lists_configured():
    config = AppConfig(sap_server=[_server("E4G"), _server("S4E")])

    result = list_sap_systems(config)

    assert "SID=E4G" in result
    assert "SID=S4E" in result
    assert "PAS=e4g-pas" in result


# ── check_work_process_errors ────────────────────────────────────────

def test_check_work_process_errors_no_server_configured():
    config = AppConfig(sap_server=[])

    result = check_work_process_errors(SidRequest(sid="E4G"), config=config)

    assert "not found in config" in result


def test_check_work_process_errors_healthy_when_all_running():
    config = AppConfig(sap_server=[_server()])
    csv_output = (
        "No, Typ, Pid, Status, Reason\n"
        "0, DIA, 1001, RUN, \n"
        "1, BTC, 1002, RUN, \n"
    )

    with patch(
        "mcp_server.capabilities.monitoring.domain.run_command",
        return_value=(True, csv_output, ""),
    ):
        result = check_work_process_errors(SidRequest(sid="E4G"), config=config)

    assert "✅ HEALTHY" in result
    assert "PROBLEMS DETECTED" not in result


def test_check_work_process_errors_detects_error_process():
    config = AppConfig(sap_server=[_server()])
    csv_output = (
        "No, Typ, Pid, Status, Reason\n"
        "0, DIA, 1001, RUN, \n"
        "1, BTC, 1002, ERROR, crashed\n"
    )

    with patch(
        "mcp_server.capabilities.monitoring.domain.run_command",
        return_value=(True, csv_output, ""),
    ):
        result = check_work_process_errors(SidRequest(sid="E4G"), config=config)

    assert "PROBLEMS DETECTED — 1" in result
    assert "ERROR PROCESSES (1)" in result
    assert "WP# 1" in result


def test_check_work_process_errors_no_output_returned():
    config = AppConfig(sap_server=[_server()])

    with patch("mcp_server.capabilities.monitoring.domain.run_command", return_value=(False, "", "connection lost")):
        result = check_work_process_errors(SidRequest(sid="E4G"), config=config)

    assert "No work process table returned" in result


# ── get_work_process_breakdown ───────────────────────────────────────

def test_get_work_process_breakdown_no_server_configured():
    config = AppConfig(sap_server=[])

    result = get_work_process_breakdown(SidRequest(sid="E4G"), config=config)

    assert "not found in config" in result


def test_get_work_process_breakdown_parses_comma_delimited_and_maps_status():
    config = AppConfig(sap_server=[_server()])
    csv_output = (
        "No, Typ, Pid, Status, Reason\n"
        "0, DIA, 1001, RUN, \n"      # -> dialog, GREEN
        "1, DIA, 1002, WAIT, \n"     # -> dialog, YELLOW
        "2, BTC, 1003, STOPPED, \n"  # -> batch, GRAY
    )

    with patch(
        "mcp_server.capabilities.monitoring.domain.run_command",
        return_value=(True, csv_output, ""),
    ):
        result = get_work_process_breakdown(SidRequest(sid="E4G"), config=config)

    assert "Work Process Breakdown for E4G" in result
    assert "Dialog processes:    2" in result
    assert "Batch processes:     1" in result
    assert "TOTAL:               3" in result
    # one GREEN + one YELLOW dialog process
    assert "DIALOG: 1✅ 1🟡 0⚫" in result
    assert "BATCH: 0✅ 0🟡 1⚫" in result


def test_get_work_process_breakdown_falls_back_to_profile_when_wp_table_unparseable():
    """No recognizable WP rows in the first output -> falls through to
    the DEFAULT.pfl profile-based last resort, a SEPARATE SSH call."""
    config = AppConfig(sap_server=[_server()])
    unparseable_wp_output = "some garbage that has a comma, but no valid rows\n"
    profile_output = "wp_no_dw = 4\nwp_no_btc = 2\nwp_no_spo = 1\nwp_no_upd = 1\nwp_no_en = 1\nwp_no_gw = 1\n"

    with patch(
        "mcp_server.capabilities.monitoring.domain.run_command",
        side_effect=[(True, unparseable_wp_output, ""), (True, profile_output, "")],
    ):
        result = get_work_process_breakdown(SidRequest(sid="E4G"), config=config)

    assert "Work Process Config for E4G" in result
    assert "Dialog: 4" in result
    assert "Gateway: 1" in result


def test_get_work_process_breakdown_no_output_returned():
    config = AppConfig(sap_server=[_server()])

    with patch("mcp_server.capabilities.monitoring.domain.run_command", return_value=(False, "", "timeout")):
        result = get_work_process_breakdown(SidRequest(sid="E4G"), config=config)

    assert "No work process table returned" in result


# ── debug_raw_process_list ───────────────────────────────────────────

def test_debug_raw_process_list_no_server_configured():
    config = AppConfig(sap_server=[])

    result = debug_raw_process_list(SidRequest(sid="E4G"), config=config)

    assert "not found in config" in result


def test_debug_raw_process_list_shows_line_numbers_and_detects_comma_delimiter():
    config = AppConfig(sap_server=[_server()])
    raw_output = "name, dispstatus, textstatus\nmsg_server, GREEN, Running\n"

    with patch(
        "mcp_server.capabilities.monitoring.domain.run_command",
        return_value=(True, raw_output, ""),
    ):
        result = debug_raw_process_list(SidRequest(sid="E4G"), config=config)

    assert "RAW PROCESS LIST for E4G" in result
    assert "Total lines: 2" in result
    assert "1: " in result
    assert "Delimiter: COMMA" in result
    assert "Number of fields in header: 3" in result


# ── get_sap_process_list ─────────────────────────────────────────────

def test_get_sap_process_list_no_server_configured():
    result = get_sap_process_list(SidRequest(sid="E4G"), config=AppConfig(sap_server=[]))
    assert "not found in config" in result


def test_get_sap_process_list_success():
    config = AppConfig(sap_server=[_server()])
    with patch("mcp_server.capabilities.monitoring.domain.run_command", return_value=(True, "msg_server, GREEN\n", "")):
        result = get_sap_process_list(SidRequest(sid="E4G"), config=config)
    assert "SAP Process List [E4G]:" in result
    assert "GREEN" in result


def test_get_sap_process_list_failure_shows_error():
    config = AppConfig(sap_server=[_server()])
    with patch("mcp_server.capabilities.monitoring.domain.run_command", return_value=(False, "", "auth failed")):
        result = get_sap_process_list(SidRequest(sid="E4G"), config=config)
    assert result == "❌ auth failed"


# ── get_sap_process_status ───────────────────────────────────────────

def test_get_sap_process_status_no_server_configured():
    result = get_sap_process_status(SidRequest(sid="E4G"), config=AppConfig(sap_server=[]))
    assert "not found" in result


def test_get_sap_process_status_queries_all_three_components():
    config = AppConfig(sap_server=[_full_server()])
    with patch(
        "mcp_server.capabilities.monitoring.domain.run_command",
        return_value=(True, "GREEN", ""),
    ) as mock_run:
        result = get_sap_process_status(SidRequest(sid="E4G"), config=config)

    assert "[PAS]" in result
    assert "[ASCS]" in result
    assert "[DB]" in result
    assert mock_run.call_count == 3
    # DB tier must use hanaadm, not sapadm
    db_call = mock_run.call_args_list[2]
    assert db_call.args[1] == "hdcadm"


# ── get_sap_system_health ────────────────────────────────────────────

def test_get_sap_system_health_no_server_configured_returns_clean_error():
    """Disclosed fix vs legacy: original indexed sap_srv["pashost"] with
    no None-check here and would have raised TypeError for an unknown
    SID; this returns a clean error message like every other tool."""
    result = get_sap_system_health(SidRequest(sid="UNKNOWN"), config=AppConfig(sap_server=[]))
    assert result == "❌ SID 'UNKNOWN' not found in config."


def test_get_sap_system_health_all_green():
    config = AppConfig(sap_server=[_full_server()])
    with patch("mcp_server.capabilities.monitoring.domain.run_command", return_value=(True, "state GREEN", "")):
        result = get_sap_system_health(SidRequest(sid="E4G"), config=config)
    assert result == "PAS: ✅ GREEN\nASCS: ✅ GREEN\nDB: ✅ GREEN"


def test_get_sap_system_health_unreachable_component():
    config = AppConfig(sap_server=[_full_server()])
    with patch("mcp_server.capabilities.monitoring.domain.run_command", return_value=(False, "", "timeout")):
        result = get_sap_system_health(SidRequest(sid="E4G"), config=config)
    assert "PAS: ❌ UNREACHABLE" in result


# ── get_kernel_version ───────────────────────────────────────────────

def test_get_kernel_version_no_server_configured():
    result = get_kernel_version(SidRequest(sid="E4G"), config=AppConfig(sap_server=[]))
    assert "not found" in result


def test_get_kernel_version_primary_sapcontrol_success():
    config = AppConfig(sap_server=[_server()])
    with patch(
        "mcp_server.capabilities.monitoring.domain.run_command",
        return_value=(True, "kernel release 789, patch 200", ""),
    ):
        result = get_kernel_version(SidRequest(sid="E4G"), config=config)
    assert "via sapcontrol" in result
    assert "kernel release 789" in result


def test_get_kernel_version_falls_back_to_disp_plus_work():
    config = AppConfig(sap_server=[_server()])
    with patch(
        "mcp_server.capabilities.monitoring.domain.run_command",
        side_effect=[(True, "", ""), (True, "disp+work information\nkernel 789", "")],
    ):
        result = get_kernel_version(SidRequest(sid="E4G"), config=config)
    assert "via disp+work fallback" in result
    assert "kernel 789" in result


def test_get_kernel_version_both_methods_empty():
    config = AppConfig(sap_server=[_server()])
    with patch("mcp_server.capabilities.monitoring.domain.run_command", return_value=(True, "", "")):
        result = get_kernel_version(SidRequest(sid="E4G"), config=config)
    assert "Both sapcontrol and disp+work checks returned empty output" in result


# ── check_disk_usage ─────────────────────────────────────────────────

def test_check_disk_usage_no_server_configured():
    result = check_disk_usage(DiskUsageRequest(sid="E4G"), config=AppConfig(sap_server=[]))
    assert "not found" in result


def test_check_disk_usage_reports_filesystems_over_threshold():
    config = AppConfig(sap_server=[_server()])
    with patch(
        "mcp_server.capabilities.monitoring.domain.run_command",
        return_value=(True, "Filesystem Size Use% Mounted\n/dev/sda1 100G 85% /\n", ""),
    ):
        result = check_disk_usage(DiskUsageRequest(sid="E4G", threshold=80), config=config)
    assert "Disk Usage [E4G] (≥80%)" in result
    assert "85%" in result


def test_check_disk_usage_all_healthy_when_empty_output():
    config = AppConfig(sap_server=[_server()])
    with patch("mcp_server.capabilities.monitoring.domain.run_command", return_value=(True, "", "")):
        result = check_disk_usage(DiskUsageRequest(sid="E4G", threshold=80), config=config)
    assert "✅ All filesystems below 80%" in result


# ── find_largest_files ───────────────────────────────────────────────

def test_find_largest_files_no_server_configured():
    result = find_largest_files(FindLargestFilesRequest(sid="E4G", mount_path="/hana/data"), config=AppConfig(sap_server=[]))
    assert "not found" in result


def test_find_largest_files_converts_bytes_to_mb():
    config = AppConfig(sap_server=[_server()])
    # 10 MiB file
    fake_output = f"{10 * 1024 * 1024} /hana/data/bigfile.dat\n"
    with patch("mcp_server.capabilities.monitoring.domain.run_command", return_value=(True, fake_output, "")):
        result = find_largest_files(FindLargestFilesRequest(sid="E4G", mount_path="/hana/data", top_n=10), config=config)
    assert "10.00 MB" in result
    assert "/hana/data/bigfile.dat" in result


def test_find_largest_files_empty_result():
    config = AppConfig(sap_server=[_server()])
    with patch("mcp_server.capabilities.monitoring.domain.run_command", return_value=(True, "", "")):
        result = find_largest_files(FindLargestFilesRequest(sid="E4G", mount_path="/nonexistent"), config=config)
    assert "No files found" in result


# ── check_cpu_usage / check_memory_usage ─────────────────────────────

def test_check_cpu_usage_no_server_configured():
    result = check_cpu_usage(SidRequest(sid="E4G"), config=AppConfig(sap_server=[]))
    assert "not found" in result


def test_check_cpu_usage_combines_three_calls():
    config = AppConfig(sap_server=[_server()])
    with patch(
        "mcp_server.capabilities.monitoring.domain.run_command",
        side_effect=[(True, "top output", ""), (True, "0.50 0.40 0.30", ""), (True, "mpstat output", "")],
    ) as mock_run:
        result = check_cpu_usage(SidRequest(sid="E4G"), config=config)

    assert "CPU Usage [E4G]" in result
    assert "top output" in result
    assert "0.50 0.40 0.30" in result
    assert "mpstat output" in result
    assert mock_run.call_count == 3


def test_check_memory_usage_no_server_configured():
    result = check_memory_usage(SidRequest(sid="E4G"), config=AppConfig(sap_server=[]))
    assert "not found" in result


def test_check_memory_usage_combines_two_calls():
    config = AppConfig(sap_server=[_server()])
    with patch(
        "mcp_server.capabilities.monitoring.domain.run_command",
        side_effect=[(True, "Mem: 32G used 10G", ""), (True, "USER PID %MEM COMMAND\nhdbadm 1 20 hdb", "")],
    ):
        result = check_memory_usage(SidRequest(sid="E4G"), config=config)

    assert "Memory Usage [E4G]" in result
    assert "Mem: 32G used 10G" in result
    assert "Top Memory-Consuming Processes" in result


# ── get_hana_status ──────────────────────────────────────────────────

def test_get_hana_status_no_server_configured():
    result = get_hana_status(SidRequest(sid="E4G"), config=AppConfig(sap_server=[]))
    assert "not found" in result


def test_get_hana_status_uses_hanaadm_and_dbhost():
    config = AppConfig(sap_server=[_full_server()])
    with patch(
        "mcp_server.capabilities.monitoring.domain.run_command",
        return_value=(True, "GREEN", ""),
    ) as mock_run:
        result = get_hana_status(SidRequest(sid="E4G"), config=config)

    assert "HANA Status [E4G]" in result
    assert mock_run.call_count == 2
    first_call = mock_run.call_args_list[0]
    assert first_call.args[0] == "e4g-db"
    assert first_call.args[1] == "hdcadm"
