"""Domain tests for S/4HANA conversion pre-checks.

Most of this domain is pure string/regex parsing and SQL-building
(_escape_table_name through _isql_failed) - tested exhaustively here with
no mocking needed at all. The orchestration function
(check_case_sensitivity_duplicates) is tested at its early-exit paths
(no server, missing ASE fields, no tables found) plus one full mocked
happy-path scan, using run_command mocked - matching monitoring's
pattern, not a fake RFC connection, since this uses plain SSH/isql.
"""

from __future__ import annotations

from unittest.mock import patch

from mcp_server.capabilities.conversion.contract import SidRequest
from mcp_server.capabilities.conversion.domain import (
    _build_index_dup_check_sql,
    _build_sp_helpindex_batch,
    _escape_table_name,
    _isql_failed,
    _parse_dup_output,
    _parse_sp_helpindex_batch,
    _parse_table_list,
    check_case_sensitivity_duplicates,
    get_scan_progress,
)
from mcp_server.infra.sap_config import AppConfig, SapServerConfig


def _ase_server(sid: str = "E4G") -> SapServerConfig:
    return SapServerConfig(
        sid=sid, host="e4g-host", password="x",
        ase_host="e4g-ase", ase_servername="E4G", ase_dbname="E4G",
        ase_user="sapsa", ase_password="asepass", ase_os_user="sybe4g",
    )


# ── _escape_table_name ───────────────────────────────────────────────

def test_escape_table_name_simple():
    assert _escape_table_name("MARA") == "[MARA]"


def test_escape_table_name_already_bracketed():
    assert _escape_table_name("[MARA]") == "[MARA]"


def test_escape_table_name_schema_qualified():
    assert _escape_table_name("dbo.MARA") == "[dbo].[MARA]"


def test_escape_table_name_empty_or_invalid():
    assert _escape_table_name("") == "[unknown]"
    assert _escape_table_name(None) == "[unknown]"


# ── _build_sp_helpindex_batch ────────────────────────────────────────

def test_build_sp_helpindex_batch_skips_suspicious_names():
    sql = _build_sp_helpindex_batch(["MARA", "DROP TABLE X; --evil"])
    assert "sp_helpindex [MARA]" in sql
    assert "evil" not in sql


def test_build_sp_helpindex_batch_empty_list():
    assert _build_sp_helpindex_batch([]) == ""


# ── _parse_table_list ────────────────────────────────────────────────

def test_parse_table_list_filters_headers_and_footers():
    raw = "name\n----\nMARA\nMARC\n(2 rows affected)\n"
    assert _parse_table_list(raw) == ["MARA", "MARC"]


def test_parse_table_list_rejects_sql_injection_attempts():
    raw = "MARA\nDROP;TABLE\n"
    result = _parse_table_list(raw)
    assert "MARA" in result
    assert "DROP;TABLE" not in result


def test_parse_table_list_empty():
    assert _parse_table_list("") == []


# ── _parse_sp_helpindex_batch ────────────────────────────────────────

def test_parse_sp_helpindex_batch_extracts_unique_indexes_only():
    raw = (
        "### TABLE: MARA ###\n"
        "index_name          index_description                index_keys\n"
        "PK__MARA            clustered, unique, primary key   MATNR\n"
        "IDX_MARA_2          nonclustered                     ERSDA\n"
    )
    result = _parse_sp_helpindex_batch(raw)
    assert result == {"MARA.PK__MARA": ["MATNR"]}


def test_parse_sp_helpindex_batch_no_table_marker_yields_nothing():
    assert _parse_sp_helpindex_batch("PK__MARA  unique  MATNR\n") == {}


# ── _build_index_dup_check_sql ───────────────────────────────────────

def test_build_index_dup_check_sql_generates_valid_structure():
    sql = _build_index_dup_check_sql({"MARA.PK__MARA": ["MATNR"]})
    assert "### INDEX: MARA.PK__MARA ###" in sql
    assert "FROM [MARA].[PK__MARA]" in sql
    assert "GROUP BY [MATNR]" in sql


def test_build_index_dup_check_sql_skips_malformed_index_names():
    sql = _build_index_dup_check_sql({"no_dot_here": ["COL"]})
    assert sql == ""


# ── _parse_dup_output ─────────────────────────────────────────────────

def test_parse_dup_output_only_keeps_actual_duplicates():
    raw = (
        "### INDEX: MARA.PK__MARA ###\n"
        "key_value            key_count\n"
        "--------------------------------\n"
        "ABC123                    3\n"
        "XYZ999                    1\n"
        "(2 rows affected)\n"
    )
    result = _parse_dup_output(raw)
    assert result == {"MARA.PK__MARA": [("ABC123", 3)]}


def test_parse_dup_output_no_duplicates_found():
    raw = "### INDEX: MARA.PK__MARA ###\n(0 rows affected)\n"
    assert _parse_dup_output(raw) == {}


# ── _isql_failed ──────────────────────────────────────────────────────

def test_isql_failed_detects_msg_error():
    raw = "Msg 208, Level 16, State 1:\nSome context\nInvalid object name 'FOO'.\n"
    result = _isql_failed(raw)
    assert result is not None
    assert "Sybase error" in result


def test_isql_failed_detects_login_failure():
    assert _isql_failed("Login failed for user sapsa") == "Login failed"


def test_isql_failed_clean_output_returns_none():
    assert _isql_failed("MARA\nMARC\n(2 rows affected)\n") is None


# ── get_scan_progress ────────────────────────────────────────────────

def test_get_scan_progress_no_scan_running():
    with patch("mcp_server.capabilities.conversion.domain.os.path.exists", return_value=False):
        result = get_scan_progress("E4G")
    assert "No scan in progress" in result


def test_get_scan_progress_complete():
    fake_progress = '{"status": "complete"}'
    with patch("mcp_server.capabilities.conversion.domain.os.path.exists", return_value=True), \
         patch("builtins.open", return_value=__import__("io").StringIO(fake_progress)):
        result = get_scan_progress("E4G")
    assert "COMPLETE" in result


# ── check_case_sensitivity_duplicates ────────────────────────────────

def test_check_case_sensitivity_duplicates_no_server_configured():
    result = check_case_sensitivity_duplicates(SidRequest(sid="E4G"), config=AppConfig(sap_server=[]))
    assert "not found in config" in result


def test_check_case_sensitivity_duplicates_missing_ase_fields():
    config = AppConfig(sap_server=[SapServerConfig(sid="E4G", host="e4g-host")])  # no ASE fields
    result = check_case_sensitivity_duplicates(SidRequest(sid="E4G"), config=config)
    assert "Missing ASE config field" in result


def test_check_case_sensitivity_duplicates_no_tables_found():
    config = AppConfig(sap_server=[_ase_server()])
    with patch("mcp_server.capabilities.conversion.domain.sftp_write_file"), \
         patch("mcp_server.capabilities.conversion.domain.run_command", return_value=(True, "(0 rows affected)", "")):
        result = check_case_sensitivity_duplicates(SidRequest(sid="E4G"), config=config)
    assert "No tables with unique indexes found" in result


def test_check_case_sensitivity_duplicates_full_scan_finds_duplicate():
    config = AppConfig(sap_server=[_ase_server()])
    table_discovery_output = "MARA\n(1 row affected)\n"
    helpindex_output = (
        "### TABLE: MARA ###\n"
        "index_name    index_description               index_keys\n"
        "PK__MARA      clustered, unique, primary key  MATNR\n"
    )
    dup_output = (
        "### INDEX: MARA.PK__MARA ###\n"
        "ABC123    2\n"
    )

    with patch("mcp_server.capabilities.conversion.domain.sftp_write_file"), \
         patch(
             "mcp_server.capabilities.conversion.domain.run_command",
             side_effect=[(True, table_discovery_output, ""), (True, helpindex_output, ""), (True, dup_output, "")],
         ), \
         patch("mcp_server.capabilities.conversion.domain.DUP_CHECK_USE_PARALLEL", False):
        result = check_case_sensitivity_duplicates(SidRequest(sid="E4G"), config=config)

    assert "Duplicate key values found" in result
    assert "MARA.PK__MARA" in result
    assert "ABC123" in result
