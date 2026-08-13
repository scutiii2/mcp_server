"""Domain tests for health tools.

get_system_health tests use run_command mocked (matching monitoring's
pattern). get_maintenance_status/set_maintenance_mode tests use pytest's
real tmp_path fixture for actual file I/O rather than mocking open() -
these functions ARE the file I/O, so testing the real thing is both
simpler and more meaningful than mocking it.
"""

from __future__ import annotations

from unittest.mock import patch

from mcp_server.capabilities.health.contract import MaintenanceModeRequest, SidRequest
from mcp_server.capabilities.health.domain import (
    _health_icon,
    _health_score,
    _overall_status,
    _parse_cpu_health,
    _parse_disk_health,
    _parse_memory_health,
    _parse_sap_process_health,
    get_maintenance_status,
    get_system_health,
    set_maintenance_mode,
)
from mcp_server.infra.sap_config import AppConfig, SapServerConfig


def _full_server(sid: str = "E4G") -> SapServerConfig:
    return SapServerConfig(
        sid=sid, host="e4g-host", password="x",
        pashost="e4g-pas", ascshost="e4g-ascs", dbhost="e4g-db",
        sapadm="e4gadm", hanaadm="hdcadm",
        pas_nr="00", ascs_nr="01", db_nr="02",
    )


# ── pure helper functions ────────────────────────────────────────────

def test_health_icon_maps_known_statuses():
    assert _health_icon("HEALTHY") == "✅"
    assert _health_icon("WARNING") == "⚠️"
    assert _health_icon("CRITICAL") == "❌"
    assert _health_icon("UNKNOWN") == "ℹ️"
    assert _health_icon(None) == "ℹ️"


def test_parse_disk_health_flags_over_threshold():
    df_output = "Filesystem Size Used Avail Use% Mounted\n/dev/sda1 100G 85G 15G 85% /\n"
    overall, filesystems = _parse_disk_health(df_output)
    assert overall == "WARNING"
    assert filesystems[0]["use_pct"] == 85
    assert filesystems[0]["status"] == "WARNING"


def test_parse_disk_health_critical_overrides_warning():
    df_output = "/dev/sda1 100G 50G 50G 50% /\n/dev/sdb1 100G 95G 5G 95% /data\n"
    overall, filesystems = _parse_disk_health(df_output)
    assert overall == "CRITICAL"
    assert len(filesystems) == 2


def test_parse_disk_health_all_healthy():
    overall, filesystems = _parse_disk_health("/dev/sda1 100G 10G 90G 10% /\n")
    assert overall == "HEALTHY"


def test_parse_memory_health_computes_percentages():
    free_output = "              total  used  free  shared  buff/cache  available\nMem:          32000 16000  8000     100        8000      16000\nSwap:          4000     0  4000\n"
    result = _parse_memory_health(free_output)
    assert result["total_mb"] == 32000
    assert result["used_pct"] == 50.0
    assert result["status"] == "HEALTHY"


def test_parse_memory_health_critical_on_high_swap():
    free_output = "Mem: 32000 16000 8000 100 8000 16000\nSwap: 4000 3000 1000\n"
    result = _parse_memory_health(free_output)
    assert result["swap_used_pct"] == 75.0
    assert result["status"] == "CRITICAL"  # swap >= 50%


def test_parse_cpu_health_parses_expected_format():
    cpu_output = "CPU_USED=45.5\nLOAD_AVG=0.5 0.4 0.3\nCPU_CORES=8\n"
    result = _parse_cpu_health(cpu_output)
    assert result["cpu_used_pct"] == 45.5
    assert result["load_avg"] == "0.5 0.4 0.3"
    assert result["status"] == "HEALTHY"


def test_parse_cpu_health_critical_above_threshold():
    result = _parse_cpu_health("CPU_USED=95.0\nLOAD_AVG=5 5 5\nCPU_CORES=4\n")
    assert result["status"] == "CRITICAL"


def test_parse_sap_process_health_all_green():
    result = _parse_sap_process_health("msg_server GREEN\ndisp+work GREEN\n")
    assert result["green"] == 2
    assert result["status"] == "HEALTHY"


def test_parse_sap_process_health_gray_is_critical():
    result = _parse_sap_process_health("msg_server GREEN\ndisp+work GRAY\n")
    assert result["status"] == "CRITICAL"


def test_overall_status_critical_wins():
    assert _overall_status(["HEALTHY", "WARNING", "CRITICAL"]) == "CRITICAL"


def test_overall_status_all_healthy():
    assert _overall_status(["HEALTHY", "HEALTHY"]) == "HEALTHY"


def test_overall_status_empty_list_defaults_warning():
    assert _overall_status([]) == "WARNING"


def test_health_score_averages_correctly():
    # HEALTHY=100, WARNING=60 -> average 80
    assert _health_score(["HEALTHY", "WARNING"]) == 80


def test_health_score_empty_list_is_zero():
    assert _health_score([]) == 0


# ── get_system_health ────────────────────────────────────────────────

def test_get_system_health_no_server_configured():
    result = get_system_health(SidRequest(sid="E4G"), config=AppConfig(sap_server=[]))
    assert "not found in config.json under sap_server" in result


def test_get_system_health_empty_sid():
    result = get_system_health(SidRequest(sid=""), config=AppConfig(sap_server=[]))
    assert "Please provide SID" in result


def test_get_system_health_includes_all_eight_sections_and_score():
    """This is the key regression test for the disclosed completion -
    every one of the 8 components must actually appear in the report,
    not just CPU/Memory like the legacy source's incomplete version did."""
    config = AppConfig(sap_server=[_full_server()])
    cpu_out = "CPU_USED=10.0\nLOAD_AVG=0.1 0.1 0.1\nCPU_CORES=8\n"
    mem_out = "Mem: 32000 8000 24000 100 8000 24000\nSwap: 4000 0 4000\n"
    disk_out = "/dev/sda1 100G 10G 90G 10% /\n"
    sap_out = "msg_server GREEN\n"
    net_out = "OK\n"
    kernel_out = "kernel release 789\n"

    with patch(
        "mcp_server.capabilities.health.domain.run_command",
        side_effect=[
            (True, cpu_out, ""),      # cpu
            (True, mem_out, ""),      # memory
            (True, disk_out, ""),     # disk
            (True, sap_out, ""),      # sap_pas
            (True, sap_out, ""),      # sap_ascs
            (True, sap_out, ""),      # database (hanaadm branch -> sapcontrol)
            (True, net_out, ""),      # connectivity
            (True, kernel_out, ""),   # kernel
        ],
    ):
        result = get_system_health(SidRequest(sid="E4G"), config=config)

    for expected_section in ("CPU Status", "Memory / Swap Status", "Disk Status", "SAP PAS Status",
                              "SAP ASCS Status", "Database Status", "App-to-DB Connectivity", "Kernel Version",
                              "Overall Health"):
        assert expected_section in result, f"missing section: {expected_section}"

    assert "Health Score     : 100/100" in result
    assert "Overall Status   : ✅ HEALTHY" in result


def test_get_system_health_reports_errors_section_on_failures():
    config = AppConfig(sap_server=[_full_server()])
    with patch("mcp_server.capabilities.health.domain.run_command", return_value=(False, "", "connection refused")):
        result = get_system_health(SidRequest(sid="E4G"), config=config)

    assert "Errors encountered during assessment" in result
    assert "connection refused" in result


# ── get_maintenance_status / set_maintenance_mode (real file I/O) ───

def test_get_maintenance_status_no_file(tmp_path):
    result = get_maintenance_status(maintenance_path=tmp_path / "maintenance.json")
    assert result == "✅ No systems in maintenance mode."


def test_set_then_get_maintenance_mode_round_trip(tmp_path):
    path = tmp_path / "maintenance.json"

    enable_result = set_maintenance_mode(MaintenanceModeRequest(sid="e4g", enable=True), maintenance_path=path)
    assert "ENABLED" in enable_result
    assert path.exists()

    status = get_maintenance_status(maintenance_path=path)
    assert "E4G" in status
    assert "since" in status.lower() or "🛠" in status


def test_disable_maintenance_mode_removes_entry(tmp_path):
    path = tmp_path / "maintenance.json"
    set_maintenance_mode(MaintenanceModeRequest(sid="E4G", enable=True), maintenance_path=path)

    disable_result = set_maintenance_mode(MaintenanceModeRequest(sid="E4G", enable=False), maintenance_path=path)

    assert "DISABLED" in disable_result
    status = get_maintenance_status(maintenance_path=path)
    assert status == "✅ No systems in maintenance mode."


def test_maintenance_mode_multiple_sids_independent(tmp_path):
    path = tmp_path / "maintenance.json"
    set_maintenance_mode(MaintenanceModeRequest(sid="E4G", enable=True), maintenance_path=path)
    set_maintenance_mode(MaintenanceModeRequest(sid="S4E", enable=True), maintenance_path=path)

    set_maintenance_mode(MaintenanceModeRequest(sid="E4G", enable=False), maintenance_path=path)

    status = get_maintenance_status(maintenance_path=path)
    assert "S4E" in status
    assert "E4G" not in status
