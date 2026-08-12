"""Domain-layer tests for job history - no HANA connection, no MCP, no network."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from mcp_server.infra.db import DBQueryResult
from mcp_server.infra.sap_config import AppConfig, SapServerConfig
from mcp_server.resources.job_history.contract import JobHistoryRequest
from mcp_server.resources.job_history.domain import get_job_history


def test_get_job_history_no_server_configured():
    config = AppConfig(sap_server=[])

    result = get_job_history(JobHistoryRequest(sid="E4G"), config=config)

    assert result.sid == "E4G"
    assert result.jobs == []


def test_get_job_history_server_configured_but_no_hana_access():
    """SSH details exist for the SID, but no hana_host - a legitimate,
    common case (not every SID has direct DB access configured)."""
    config = AppConfig(sap_server=[SapServerConfig(sid="E4G", host="e4g-host")])

    result = get_job_history(JobHistoryRequest(sid="E4G"), config=config)

    assert result.jobs == []


def test_get_job_history_returns_parsed_rows():
    config = AppConfig(
        sap_server=[
            SapServerConfig(
                sid="E4G",
                host="e4g-host",
                hana_host="e4g-db.example.com",
                hana_user="SYSTEM",
                hana_password="x",
            )
        ]
    )
    fake_db = MagicMock()
    fake_db.__enter__.return_value = fake_db
    fake_db.query.return_value = DBQueryResult(
        columns=["JOBNAME", "JOBCOUNT", "STATUS", "SDLSTRTDT", "SDLSTRTTM", "ENDDATE", "ENDTIME"],
        rows=[
            {
                "JOBNAME": "Z_DAILY_CLEANUP",
                "JOBCOUNT": "12345678",
                "STATUS": "F",
                "SDLSTRTDT": "20260810",
                "SDLSTRTTM": "020000",
                "ENDDATE": "20260810",
                "ENDTIME": "020512",
            }
        ],
    )

    with patch("mcp_server.resources.job_history.domain.HanaClient", return_value=fake_db) as mock_client:
        result = get_job_history(JobHistoryRequest(sid="e4g"), config=config)

    assert result.sid == "e4g"
    assert len(result.jobs) == 1
    assert result.jobs[0].jobname == "Z_DAILY_CLEANUP"
    assert result.jobs[0].status == "F"
    assert result.jobs[0].start_date == "20260810"
    mock_client.assert_called_once_with("e4g-db.example.com", 30015, "SYSTEM", "x")


def test_get_job_history_handles_empty_result_set():
    config = AppConfig(
        sap_server=[SapServerConfig(sid="E4G", host="e4g-host", hana_host="e4g-db", hana_user="u", hana_password="p")]
    )
    fake_db = MagicMock()
    fake_db.__enter__.return_value = fake_db
    fake_db.query.return_value = DBQueryResult(columns=[], rows=[])

    with patch("mcp_server.resources.job_history.domain.HanaClient", return_value=fake_db):
        result = get_job_history(JobHistoryRequest(sid="E4G"), config=config)

    assert result.jobs == []
