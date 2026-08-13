"""Domain tests for kernel update.

Deliberately scoped: the pure helpers (_get_sap_state,
_looks_like_remote_error, _parse_kernel_output, _run_sap_ssh's fallback
contract) and the four-stage validation phase (kernel_dir missing,
directory missing, no SAR files, missing config fields) are tested
thoroughly here. The full _trigger_kernel_update orchestration - the
246-line generator doing SSH connectivity check, SAR extraction via a
local subprocess call, AAS/PAS/ASCS stop+wait, backup, SFTP upload,
chown/chmod, DB/ASCS/PAS/AAS start+wait, kernel version comparison, and
two email sends - is NOT end-to-end tested here. Faithfully mocking that
many sequential, order-dependent SSH calls (each returning different
canned output depending on which step is calling) would need a mock
sequencing scheme complex enough to become its own source of bugs, for
a function this scaffold's README already flags as the least portable/
most architecturally unusual tool in the whole project (Windows-local
subprocess dependency). What IS tested: the pre-flight SSH connectivity
check aborting immediately on failure, which is the one path cheap to
verify without a long mock chain and covers the most likely real failure
mode (bad credentials/unreachable host) before anything destructive
happens.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from mcp_server.capabilities.kernel.contract import KernelUpdateRequest
from mcp_server.capabilities.kernel.domain import (
    _get_sap_state,
    _looks_like_remote_error,
    _parse_kernel_output,
    _process_rows,
    _run_sap_ssh,
    apply_kernel_update,
)
from mcp_server.infra.sap_config import AppConfig, SapServerConfig
from mcp_server.infra.ssh import SSHCommandResult


def _full_server(sid: str = "E4G", kernel_dir: str | None = "/kernel") -> SapServerConfig:
    return SapServerConfig(
        sid=sid, host="e4g-host", password="x",
        pashost="e4g-pas", ascshost="e4g-ascs", dbhost="e4g-db",
        sapadm="e4gadm", hanaadm="hdcadm",
        pas_nr="00", ascs_nr="01", db_nr="02",
        kernel_dir=kernel_dir,
    )


# ── _get_sap_state ────────────────────────────────────────────────────

def test_get_sap_state_empty_output_is_down():
    assert _get_sap_state("") == "DOWN"


def test_get_sap_state_all_green():
    assert _get_sap_state("msg_server, MessageServer, GREEN, running\ndisp+work, Dispatcher, GREEN, running\n") == "GREEN"


def test_get_sap_state_any_yellow_is_yellow():
    assert _get_sap_state("msg_server, MessageServer, GREEN, running\ndisp+work, Dispatcher, YELLOW, warn\n") == "YELLOW"


def test_get_sap_state_gray_is_down():
    assert _get_sap_state("msg_server, MessageServer, GRAY, stopped\n") == "DOWN"


def test_get_sap_state_no_parseable_lines_is_unknown():
    assert _get_sap_state("some unparseable garbage\n") == "UNKNOWN"


# ── _looks_like_remote_error ─────────────────────────────────────────

def test_looks_like_remote_error_detects_auth_failure():
    assert _looks_like_remote_error("Error: Authentication failed.") is True


def test_looks_like_remote_error_empty_is_false():
    assert _looks_like_remote_error("") is False


def test_looks_like_remote_error_normal_output_is_false():
    assert _looks_like_remote_error("BACKUP_OK") is False


# ── _parse_kernel_output ─────────────────────────────────────────────

def test_parse_kernel_output_extracts_kernel_and_patch():
    assert _parse_kernel_output("kernel release 789 | patch number 200") == "789.200"


def test_parse_kernel_output_pads_short_patch_numbers():
    assert _parse_kernel_output("789 | patch number 5") == "789.05"


def test_parse_kernel_output_fallback_to_first_three_digits():
    assert _parse_kernel_output("some other format 793 build") == "793"


def test_parse_kernel_output_none_input():
    assert _parse_kernel_output(None) is None


def test_parse_kernel_output_no_digits_returns_none():
    assert _parse_kernel_output("no version info here") is None


# ── _process_rows ─────────────────────────────────────────────────────

def test_process_rows_skips_header_and_short_lines():
    output = "name, dispstatus, textstatus\nmsg_server, GREEN, Running, extra\ngarbage\n"
    rows = _process_rows(output)
    assert len(rows) == 1
    assert rows[0][0] == "msg_server"


# ── _run_sap_ssh ──────────────────────────────────────────────────────

def test_run_sap_ssh_prefers_stdout():
    fake_ssh = MagicMock()
    fake_ssh.__enter__.return_value = fake_ssh
    fake_ssh.run_login_shell.return_value = SSHCommandResult(stdout="real output", stderr="", exit_status=0)

    with patch("mcp_server.capabilities.kernel.domain.SSHClient", return_value=fake_ssh):
        result = _run_sap_ssh("host", "user", "pass", "echo hi")

    assert result == "real output"


def test_run_sap_ssh_falls_back_to_cleaned_stderr_when_stdout_empty():
    fake_ssh = MagicMock()
    fake_ssh.__enter__.return_value = fake_ssh
    fake_ssh.run_login_shell.return_value = SSHCommandResult(
        stdout="", stderr="[sudo] password for user:\nreal error\n", exit_status=1
    )

    with patch("mcp_server.capabilities.kernel.domain.SSHClient", return_value=fake_ssh):
        result = _run_sap_ssh("host", "user", "pass", "sudo something")

    assert result == "real error"
    assert "sudo" not in result.lower() or "password" not in result.lower()


def test_run_sap_ssh_connection_exception_becomes_error_string():
    with patch("mcp_server.capabilities.kernel.domain.SSHClient", side_effect=ConnectionError("refused")):
        result = _run_sap_ssh("badhost", "user", "pass", "echo hi")

    assert "❌ SAP SSH Error (badhost)" in result
    assert "refused" in result


# ── apply_kernel_update validation phase ─────────────────────────────

def test_apply_kernel_update_no_server_configured():
    result = apply_kernel_update(KernelUpdateRequest(sid="E4G"), config=AppConfig(sap_server=[]))
    assert "not found in config.json" in result


def test_apply_kernel_update_no_kernel_dir_configured():
    config = AppConfig(sap_server=[_full_server(kernel_dir=None)])
    result = apply_kernel_update(KernelUpdateRequest(sid="E4G"), config=config)
    assert "Missing 'kernel_dir'" in result


def test_apply_kernel_update_kernel_dir_does_not_exist(tmp_path):
    missing_dir = str(tmp_path / "does-not-exist")
    config = AppConfig(sap_server=[_full_server(kernel_dir=missing_dir)])
    result = apply_kernel_update(KernelUpdateRequest(sid="E4G"), config=config)
    assert "does not exist" in result


def test_apply_kernel_update_no_sar_files_found(tmp_path):
    config = AppConfig(sap_server=[_full_server(kernel_dir=str(tmp_path))])
    result = apply_kernel_update(KernelUpdateRequest(sid="E4G"), config=config)
    assert "No .SAR kernel files found" in result


def test_apply_kernel_update_missing_required_fields(tmp_path):
    (tmp_path / "SAPEXE.SAR").write_text("fake sar content")
    config = AppConfig(sap_server=[
        SapServerConfig(sid="E4G", host="e4g-host", kernel_dir=str(tmp_path))  # missing pashost/sapadm/etc
    ])
    result = apply_kernel_update(KernelUpdateRequest(sid="E4G"), config=config)
    assert "Missing required config fields" in result
    assert "pashost" in result


def test_apply_kernel_update_all_validation_passed_reaches_connectivity_check(tmp_path):
    """Confirms validation passes and the function proceeds into the real
    orchestration (aborting there is expected and tested separately, in
    the module docstring's documented scope) - not a full success test."""
    (tmp_path / "SAPEXE.SAR").write_text("fake sar content")
    config = AppConfig(sap_server=[_full_server(kernel_dir=str(tmp_path))])

    with patch("mcp_server.capabilities.kernel.domain.SSHClient", side_effect=ConnectionError("unreachable")):
        result = apply_kernel_update(KernelUpdateRequest(sid="E4G"), config=config)

    assert "PRE-FLIGHT VALIDATION PASSED" in result
    assert "Cannot reach" in result  # connectivity check correctly aborted before anything destructive
