"""Background job history: pure logic, no MCP or transport concerns.

Queries TBTCO - the standard SAP job-header table - directly over the
HANA SQL port. This is a legitimate, commonly used bypass of the RFC
layer for reporting/monitoring, but it means this reflects raw database
state, not SAP's own job-status semantics (release locks, authorization
checks, client handling). The column list below is representative of a
typical TBTCO schema, not guaranteed to match your exact SAP version -
verify against your system (e.g. ``SELECT * FROM TBTCO LIMIT 1`` in HANA
Studio or DBACOCKPIT) before relying on it.
"""

from __future__ import annotations

from mcp_server.infra.db import HanaClient
from mcp_server.infra.sap_config import AppConfig, find_sap_server
from mcp_server.resources.job_history.contract import JobHistoryRequest, JobHistoryResult, JobRecord


_QUERY = """
SELECT JOBNAME, JOBCOUNT, STATUS, SDLSTRTDT, SDLSTRTTM, ENDDATE, ENDTIME
FROM TBTCO
WHERE SDLSTRTDT >= ADD_DAYS(CURRENT_DATE, -7)
ORDER BY SDLSTRTDT DESC, SDLSTRTTM DESC
LIMIT 50
"""


def get_job_history(request: JobHistoryRequest, *, config: AppConfig) -> JobHistoryResult:
    server = find_sap_server(request.sid, config)
    if server is None or not server.hana_host:
        return JobHistoryResult(sid=request.sid, jobs=[])

    with HanaClient(
        server.hana_host,
        server.hana_port,
        server.hana_user or "",
        server.hana_password or "",
    ) as db:
        result = db.query(_QUERY)

    jobs = [
        JobRecord(
            jobname=str(row.get("JOBNAME", "")),
            jobcount=str(row.get("JOBCOUNT", "")),
            status=str(row.get("STATUS", "")),
            start_date=str(row.get("SDLSTRTDT", "")),
            start_time=str(row.get("SDLSTRTTM", "")),
            end_date=str(row.get("ENDDATE", "")),
            end_time=str(row.get("ENDTIME", "")),
        )
        for row in result.rows
    ]
    return JobHistoryResult(sid=request.sid, jobs=jobs)
