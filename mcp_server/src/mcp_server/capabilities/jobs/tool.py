"""SAP background job tools - failures, logs, reschedule, long-running,
completed, longest-completed, trend analysis. RFC-based, same [rfc]
optional dependency group as dumps.

Each function loads config, opens an RFC connection via infra/rfc.py,
calls the domain function(s), formats the result, closes the connection.
``@mcp.tool()`` appears here and nowhere else.
"""

from __future__ import annotations

from mcp_server.capabilities.jobs.contract import (
    CompletedJobsRequest,
    LongestCompletedJobsRequest,
    LongRunningJobsRequest,
)
from mcp_server.capabilities.jobs.domain import (
    format_completed_jobs_report,
    format_failed_jobs_report,
    format_job_log_report,
    format_job_trend_report,
    format_long_running_jobs_report,
    format_longest_completed_jobs_report,
    get_completed_jobs,
    get_failed_jobs,
    get_job_log_entries,
    get_job_trend_analysis,
    get_long_running_jobs,
    get_longest_completed_jobs,
    reschedule_job,
)
from mcp_server.config import settings
from mcp_server.infra.rfc import open_rfc_connection
from mcp_server.infra.sap_config import find_rfc_server, load_config
from mcp_server.server import mcp


@mcp.tool(description="Get background job failures for a SAP system in the last N hours using RFC.")
def get_job_failures_tool(sid: str, hours: int = 24) -> str:
    config = load_config(settings.config_path)
    server = find_rfc_server(sid, config)
    if not server:
        return f"❌ RFC config not found for SID '{sid}'."
    try:
        conn = open_rfc_connection(server)
        try:
            jobs = get_failed_jobs(conn, server.user)
        finally:
            conn.close()
        return format_failed_jobs_report(sid, hours, jobs)
    except Exception as error:
        return f"❌ Error fetching job failures: {error}"


@mcp.tool(description=(
    "Get the execution log for a specific failed SAP background job. "
    "Looks up the job's most recent run automatically - just provide the job name and SID."
))
def get_job_log_tool(sid: str, jobname: str) -> str:
    config = load_config(settings.config_path)
    server = find_rfc_server(sid, config)
    if not server:
        return f"❌ RFC config not found for SID '{sid}'."
    try:
        conn = open_rfc_connection(server)
        try:
            jobs = get_failed_jobs(conn, server.user)
            match = next((j for j in jobs if j.jobname.upper() == jobname.upper()), None)
            if not match:
                return f"❌ Job '{jobname}' not found among recent failures for {sid}."
            logs = get_job_log_entries(conn, match.jobname, match.jobcount, server.user)
        finally:
            conn.close()
        return format_job_log_report(sid, jobname, match.jobcount, logs)
    except Exception as error:
        return f"❌ Error fetching job log: {error}"


@mcp.tool(description=(
    "Reschedule and immediately restart a failed SAP background job. "
    "Looks up the job's most recent failed run automatically. "
    "Optionally run it under a different step user. "
    "ALWAYS confirm with the user before calling this - it starts a real job."
))
def reschedule_job_tool(sid: str, jobname: str, step_user: str = "") -> str:
    config = load_config(settings.config_path)
    server = find_rfc_server(sid, config)
    if not server:
        return f"❌ RFC config not found for SID '{sid}'."
    try:
        conn = open_rfc_connection(server)
        try:
            jobs = get_failed_jobs(conn, server.user)
            match = next((j for j in jobs if j.jobname.upper() == jobname.upper()), None)
            if not match:
                return f"❌ Job '{jobname}' not found among recent failures for {sid}."
            ok, msg = reschedule_job(conn, match.jobname, match.jobcount, server.user, step_user=step_user or None)
        finally:
            conn.close()
        return f"✅ {msg}" if ok else f"❌ {msg}"
    except Exception as error:
        return f"❌ Error rescheduling job: {error}"


@mcp.tool(description=(
    "🚨 Find LONG-RUNNING jobs that are still executing right now (not failed). "
    "Queries SM37 background job log for jobs with STATUS='ACTIVE' AND duration > threshold. "
    "Useful for spotting jobs that should have finished but are hung, waiting for resources, or in infinite loops. "
    "Use this INSTEAD of get_job_failures_tool() to proactively find slow jobs."
))
def get_long_running_jobs_tool(sid: str, threshold_minutes: int = 60) -> str:
    config = load_config(settings.config_path)
    server = find_rfc_server(sid, config)
    if not server:
        return f"❌ RFC config not found for SID '{sid}'. Add SAP RFC credentials to config.json 'sap' section."
    try:
        conn = open_rfc_connection(server)
        try:
            jobs = get_long_running_jobs(conn, LongRunningJobsRequest(sid=sid, threshold_minutes=threshold_minutes))
        finally:
            conn.close()
        return format_long_running_jobs_report(sid, threshold_minutes, jobs)
    except Exception as error:
        return f"❌ Error querying long-running jobs for {sid}: {error}"


@mcp.tool(description=(
    "✅ Show completed SAP background jobs for a given time frame. Uses TBTCO via PyRFC. "
    "Returns jobs with STATUS='F' within the specified time period. Use this for: completed jobs, "
    "finished jobs, completed jobs last 24 hours, jobs yesterday, completed jobs this week. "
    "This tool does NOT apply a duration threshold. For completed jobs longer than 60 minutes "
    "or slow completed jobs, use get_longest_completed_jobs_tool instead."
))
def get_completed_jobs_tool(
    sid: str, hours: int = 24, top_n: int = 100,
    from_date: str = "", to_date: str = "", from_time: str = "000000", to_time: str = "235959",
) -> str:
    config = load_config(settings.config_path)
    server = find_rfc_server(sid, config)
    if not server:
        return f"❌ RFC config not found for SID '{sid}'. Add SAP RFC credentials to config.json 'sap' section."
    request = CompletedJobsRequest(sid=sid, hours=hours, top_n=top_n, from_date=from_date, to_date=to_date, from_time=from_time, to_time=to_time)
    try:
        conn = open_rfc_connection(server)
        try:
            jobs = get_completed_jobs(conn, request)
        finally:
            conn.close()
        return format_completed_jobs_report(sid, request, jobs)
    except Exception as error:
        return f"❌ Error querying completed jobs for {sid}: {error}"


@mcp.tool(description=(
    "📊 Find completed SAP background jobs with the longest execution duration. Uses TBTCO via PyRFC. "
    "Returns jobs with STATUS='F' ordered by actual runtime descending using ENDDATE/ENDTIME minus "
    "STRTDATE/STRTTIME. Use this for questions like: completed jobs, finished jobs, jobs which took "
    "longer duration, longest completed jobs, slow completed jobs."
))
def get_longest_completed_jobs_tool(sid: str, hours: int = 24, top_n: int = 20, threshold_minutes: int = 60) -> str:
    config = load_config(settings.config_path)
    server = find_rfc_server(sid, config)
    if not server:
        return f"❌ RFC config not found for SID '{sid}'. Add SAP RFC credentials to config.json 'sap' section."
    request = LongestCompletedJobsRequest(sid=sid, hours=hours, top_n=top_n, threshold_minutes=threshold_minutes)
    try:
        conn = open_rfc_connection(server)
        try:
            jobs = get_longest_completed_jobs(conn, request)
        finally:
            conn.close()
        return format_longest_completed_jobs_report(sid, request, jobs)
    except Exception as error:
        return f"❌ Error querying completed jobs for {sid}: {error}"


@mcp.tool(description=(
    "📈 Analyze execution time TRENDS for a specific SAP background job. Queries SM37 for the last N "
    "days of runs, calculates average/min/max duration per week, detects degradation (linear increase "
    "over time), and flags anomalies. Use this AFTER identifying a slow job with "
    "get_long_running_jobs_tool() to understand if it's a NEW problem or an ongoing DEGRADATION."
))
def get_job_trend_analysis_tool(sid: str, jobname: str, days: int = 30) -> str:
    config = load_config(settings.config_path)
    server = find_rfc_server(sid, config)
    if not server:
        return f"❌ RFC config not found for SID '{sid}'. Add SAP RFC credentials to config.json 'sap' section."
    try:
        conn = open_rfc_connection(server)
        try:
            trend = get_job_trend_analysis(conn, jobname.upper(), days)
        finally:
            conn.close()
        return format_job_trend_report(sid, jobname, days, trend)
    except Exception as error:
        return f"❌ Error analyzing trend for {jobname} on {sid}: {error}"
