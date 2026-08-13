"""SAP background job monitoring: RFC-based (BAPI_XBP_* + TBTCO), not SSH.

Faithful port of get_failed_jobs, get_job_log, reschedule_failed_job,
get_long_running_jobs, get_completed_jobs, get_longest_completed_jobs,
get_job_trend_analysis, and _get_trend_recommendation from sap_utils.py,
plus the display formatting from mcp_server.py's seven job tools.

Two disclosed notes, neither a crash-causing bug like the ones found in
Dumps/Health, so neither was "fixed" - both preserved as-is, flagged here
for visibility:

1. get_long_running_jobs's actual RFC filter is ``STATUS <> 'A'``
   (not-aborted) against the last 7 days of TBTCO - broader than its name
   and tool description suggest ("jobs with STATUS='ACTIVE'"). It
   actually returns any non-aborted job (completed or still running)
   whose duration - real if finished, elapsed-so-far if not - exceeds the
   threshold. Functionally reasonable (surfaces both stuck-and-still-
   running AND recently-slow-but-finished jobs), just not what the name
   implies.
2. get_job_trend_analysis's legacy mcp_server.py tool wrapper only checks
   for `status in ("NO_DATA", "INSUFFICIENT_DATA")` before formatting -
   it never checks for `status == "ERROR"` (the shape returned by
   get_job_trend_analysis's own except block). An RFC failure there would
   fall through to the success-path formatting code and likely produce a
   confusing "0 total runs" report instead of showing the actual error.
   This one WAS worth fixing (matches the "clean error message" standard
   every other tool in this port follows) - see format_job_trend_report.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta

from mcp_server.capabilities.jobs.contract import (
    CompletedJobsRequest,
    FailedJob,
    JobLogLine,
    JobRun,
    LongestCompletedJobsRequest,
    LongRunningJobsRequest,
    TrendResult,
    WeekStats,
)
from mcp_server.infra.rfc import RfcConnection


_XMI_LOGON_KWARGS = dict(EXTCOMPANY="DXC", EXTPRODUCT="AIMONITOR", INTERFACE="XBP", VERSION="3.0")


def _parse_pipe_row(wa: str, min_parts: int) -> list[str] | None:
    if not wa:
        return None
    parts = wa.split("|")
    if len(parts) < min_parts:
        return None
    return [p.strip() for p in parts]


def _format_duration(total_seconds: int) -> str:
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours}:{minutes:02d}:{seconds:02d}"


# ── get_failed_jobs ───────────────────────────────────────────────────

def get_failed_jobs(conn: RfcConnection, rfc_user: str) -> list[FailedJob]:
    conn.call("BAPI_XMI_LOGON", **_XMI_LOGON_KWARGS)

    today = datetime.now().strftime("%Y%m%d")
    result = conn.call(
        "BAPI_XBP_JOB_SELECT",
        EXTERNAL_USER_NAME=rfc_user,
        JOB_SELECT_PARAM={"JOBNAME": "*", "USERNAME": "*", "FROM_DATE": today, "TO_DATE": today, "ABORTED": "X"},
        SELECTION="AL",
    )

    jobs = [FailedJob(jobname=row["JOBNAME"], jobcount=row["JOBCOUNT"]) for row in result.get("SELECTED_JOBS", [])]

    # Keep only latest failed occurrence per job name
    latest: dict[str, FailedJob] = {}
    for j in jobs:
        if j.jobname not in latest or j.jobcount > latest[j.jobname].jobcount:
            latest[j.jobname] = j

    conn.call("BAPI_XMI_LOGOFF")
    return list(latest.values())


# ── get_job_log ───────────────────────────────────────────────────────

def get_job_log_entries(conn: RfcConnection, jobname: str, jobcount: str, rfc_user: str) -> list[JobLogLine]:
    conn.call("BAPI_XMI_LOGON", **_XMI_LOGON_KWARGS)

    result = conn.call(
        "BAPI_XBP_JOB_JOBLOG_READ",
        JOBNAME=jobname, JOBCOUNT=jobcount, EXTERNAL_USER_NAME=rfc_user, LINES=0,
    )

    logs = []
    for row in result.get("JOB_PROTOCOL", []):
        enterdate = row.get("ENTERDATE", "")
        entertime = row.get("ENTERTIME", "")
        text = row.get("TEXT", "")

        if len(enterdate) == 8:
            enterdate = f"{enterdate[6:8]}.{enterdate[4:6]}.{enterdate[0:4]}"
        if len(entertime) == 6:
            entertime = f"{entertime[0:2]}:{entertime[2:4]}:{entertime[4:6]}"

        logs.append(JobLogLine(date=enterdate, time=entertime, text=text))

    conn.call("BAPI_XMI_LOGOFF")
    return logs


# ── reschedule_job ────────────────────────────────────────────────────

def reschedule_job(
    conn: RfcConnection, jobname: str, jobcount: str, rfc_user: str, step_user: str | None = None
) -> tuple[bool, str]:
    effective_user = step_user.upper() if step_user else None

    conn.call("BAPI_XMI_LOGON", **_XMI_LOGON_KWARGS)

    job_detail = conn.call("BAPI_XBP_JOB_DEFINITION_GET", JOBNAME=jobname, JOBCOUNT=jobcount, EXTERNAL_USER_NAME=rfc_user)
    abap_steps = job_detail.get("ABAP_STEP_LIST") or job_detail.get("STEP_LIST_ABP") or []
    step_tbl = job_detail.get("STEP_TBL", [])

    open_result = conn.call("BAPI_XBP_JOB_OPEN", JOBNAME=jobname, EXTERNAL_USER_NAME=rfc_user)
    ret_open = open_result.get("RETURN", {})
    if ret_open.get("TYPE") == "E":
        conn.call("BAPI_XMI_LOGOFF")
        return False, ret_open.get("MESSAGE", "Job open failed")

    new_jobcount = open_result.get("JOBCOUNT")
    if not new_jobcount:
        conn.call("BAPI_XMI_LOGOFF")
        return False, "No jobcount returned from BAPI_XBP_JOB_OPEN"

    steps_to_add = []
    if step_tbl:
        for s in step_tbl:
            if s.get("TYP", "A") != "A":
                continue
            program = s.get("PROGRAM", "").strip()
            if program:
                steps_to_add.append({
                    "program": program,
                    "variant": s.get("PARAMETER", "").strip(),
                    "original_user": s.get("AUTHCKNAM", "").strip().upper(),
                })
    elif abap_steps:
        for s in abap_steps:
            program = (s.get("ABAP_PROGRAM_NAME") or s.get("PROGRAMM") or s.get("PROGRAM") or "").strip()
            if program:
                steps_to_add.append({
                    "program": program,
                    "variant": (s.get("ABAP_VARIANT_NAME") or s.get("VARIANT") or "").strip(),
                    "original_user": s.get("AUTHCKNAM", "").strip().upper(),
                })

    added = False
    for step in steps_to_add:
        step_user_to_use = effective_user or step.get("original_user") or rfc_user
        step_result = conn.call(
            "BAPI_XBP_JOB_ADD_ABAP_STEP",
            JOBNAME=jobname, JOBCOUNT=new_jobcount, EXTERNAL_USER_NAME=rfc_user,
            ABAP_PROGRAM_NAME=step["program"], ABAP_VARIANT_NAME=step["variant"],
            SAP_USER_NAME=step_user_to_use, LANGUAGE="EN",
        )
        ret_step = step_result.get("RETURN", {})
        if ret_step.get("TYPE") == "E":
            conn.call("BAPI_XMI_LOGOFF")
            return False, ret_step.get("MESSAGE", "Step add failed")
        added = True

    if not added:
        conn.call("BAPI_XMI_LOGOFF")
        return False, f"Could not extract ABAP step from job {jobname}/{jobcount}."

    close_result = conn.call("BAPI_XBP_JOB_CLOSE", JOBNAME=jobname, JOBCOUNT=new_jobcount, EXTERNAL_USER_NAME=rfc_user)
    ret_close = close_result.get("RETURN", {})
    if ret_close.get("TYPE") == "E":
        conn.call("BAPI_XMI_LOGOFF")
        return False, ret_close.get("MESSAGE", "Job close failed")

    start_result = conn.call(
        "BAPI_XBP_JOB_START_IMMEDIATELY",
        JOBNAME=jobname, JOBCOUNT=new_jobcount, EXTERNAL_USER_NAME=rfc_user,
        TARGET_SERVER="", TARGET_GROUP="",
    )
    conn.call("BAPI_XMI_LOGOFF")

    ret_start = start_result.get("RETURN", {})
    if ret_start.get("TYPE") == "E":
        return False, ret_start.get("MESSAGE", "Job start failed")

    action_desc = f"step user changed to {effective_user}" if effective_user else "original step user kept"
    return True, f"{jobname} rescheduled as jobcount {new_jobcount} ({action_desc})"


# ── get_long_running_jobs ────────────────────────────────────────────

def get_long_running_jobs(conn: RfcConnection, request: LongRunningJobsRequest) -> list[JobRun]:
    now = datetime.now()
    threshold = timedelta(minutes=request.threshold_minutes)
    from_date = (now - timedelta(days=7)).strftime("%Y%m%d")

    result = conn.call(
        "RFC_READ_TABLE", QUERY_TABLE="TBTCO", DELIMITER="|",
        OPTIONS=[{"TEXT": "STATUS <> 'A'"}, {"TEXT": f"AND STRTDATE >= '{from_date}'"}],
        FIELDS=[{"FIELDNAME": f} for f in ("JOBNAME", "JOBCOUNT", "SDLUNAME", "STRTDATE", "STRTTIME", "ENDDATE", "ENDTIME", "STATUS")],
    )

    long_running = []
    for row in result.get("DATA", []):
        parts = _parse_pipe_row(row.get("WA", ""), 8)
        if parts is None:
            continue
        jobname, jobcount, sdluname, strtdate, strttime, enddate, endtime, status = parts[:8]

        if status == "A":
            continue

        try:
            start_dt = datetime.strptime(f"{strtdate} {strttime.zfill(6)}", "%Y%m%d %H%M%S")
            if enddate.strip() and endtime.strip():
                end_dt = datetime.strptime(f"{enddate} {endtime.zfill(6)}", "%Y%m%d %H%M%S")
                duration = end_dt - start_dt
            else:
                duration = now - start_dt
        except ValueError:
            continue

        if duration > threshold:
            total_seconds = int(duration.total_seconds())
            long_running.append(JobRun(
                jobname=jobname, jobcount=jobcount, username=sdluname, status=status,
                duration=_format_duration(total_seconds), duration_seconds=total_seconds,
                start=f"{strtdate} {strttime}", start_date=strtdate, start_time=strttime,
                end_date=enddate, end_time=endtime,
            ))

    long_running.sort(key=lambda j: j.duration_seconds, reverse=True)
    return long_running


# ── get_completed_jobs ───────────────────────────────────────────────

def get_completed_jobs(conn: RfcConnection, request: CompletedJobsRequest) -> list[JobRun]:
    now = datetime.now()
    explicit_range = bool(request.from_date and request.to_date)

    if explicit_range:
        from_time = (request.from_time or "000000").strip().zfill(6)
        to_time = (request.to_time or "235959").strip().zfill(6)
        range_start_dt = datetime.strptime(f"{request.from_date} {from_time}", "%Y%m%d %H%M%S")
        range_end_dt = datetime.strptime(f"{request.to_date} {to_time}", "%Y%m%d %H%M%S")
        query_from_date = request.from_date
    else:
        range_start_dt = now - timedelta(hours=request.hours)
        range_end_dt = now
        query_from_date = range_start_dt.strftime("%Y%m%d")

    result = conn.call(
        "RFC_READ_TABLE", QUERY_TABLE="TBTCO", DELIMITER="|",
        OPTIONS=[{"TEXT": "STATUS = 'F'"}, {"TEXT": f"AND STRTDATE >= '{query_from_date}'"}],
        FIELDS=[{"FIELDNAME": f} for f in ("JOBNAME", "JOBCOUNT", "SDLUNAME", "STRTDATE", "STRTTIME", "ENDDATE", "ENDTIME", "STATUS")],
        ROWCOUNT=10000,
    )

    completed = []
    for row in result.get("DATA", []):
        parts = _parse_pipe_row(row.get("WA", ""), 8)
        if parts is None:
            continue
        jobname, jobcount, username, strtdate, strttime_raw, enddate, endtime_raw, status = parts[:8]
        strttime, endtime = strttime_raw.zfill(6), endtime_raw.zfill(6)

        if status != "F" or not strtdate or not enddate or enddate == "00000000" or endtime == "000000":
            continue

        try:
            start_dt = datetime.strptime(f"{strtdate} {strttime}", "%Y%m%d %H%M%S")
            end_dt = datetime.strptime(f"{enddate} {endtime}", "%Y%m%d %H%M%S")
        except ValueError:
            continue

        if start_dt < range_start_dt or start_dt > range_end_dt:
            continue

        total_seconds = int((end_dt - start_dt).total_seconds())
        if total_seconds < 0:
            continue

        completed.append(JobRun(
            jobname=jobname, jobcount=jobcount, username=username, status=status,
            duration=_format_duration(total_seconds), duration_seconds=total_seconds,
            duration_minutes=round(total_seconds / 60, 1),
            start=f"{strtdate} {strttime}", end=f"{enddate} {endtime}",
            start_date=strtdate, start_time=strttime, end_date=enddate, end_time=endtime,
        ))

    completed.sort(key=lambda j: f"{j.end_date}{j.end_time}", reverse=True)
    return completed[: request.top_n]


# ── get_longest_completed_jobs ───────────────────────────────────────

def get_longest_completed_jobs(conn: RfcConnection, request: LongestCompletedJobsRequest) -> list[JobRun]:
    cutoff_dt = datetime.now() - timedelta(hours=request.hours)
    cutoff_date = cutoff_dt.strftime("%Y%m%d")

    result = conn.call(
        "RFC_READ_TABLE", QUERY_TABLE="TBTCO", DELIMITER="|",
        OPTIONS=[{"TEXT": "STATUS = 'F'"}, {"TEXT": f"AND STRTDATE >= '{cutoff_date}'"}],
        FIELDS=[{"FIELDNAME": f} for f in ("JOBNAME", "JOBCOUNT", "SDLUNAME", "STRTDATE", "STRTTIME", "ENDDATE", "ENDTIME", "STATUS")],
        ROWCOUNT=10000,
    )

    completed = []
    for row in result.get("DATA", []):
        parts = _parse_pipe_row(row.get("WA", ""), 8)
        if parts is None:
            continue
        jobname, jobcount, username, strtdate, strttime, enddate, endtime, status = parts[:8]

        if status != "F" or not strtdate or not strttime or not enddate or not endtime:
            continue
        if enddate == "00000000" or endtime == "000000":
            continue

        strttime, endtime = strttime.zfill(6), endtime.zfill(6)
        try:
            start_dt = datetime.strptime(f"{strtdate} {strttime}", "%Y%m%d %H%M%S")
            end_dt = datetime.strptime(f"{enddate} {endtime}", "%Y%m%d %H%M%S")
        except ValueError:
            continue

        if start_dt < cutoff_dt:
            continue

        total_seconds = int((end_dt - start_dt).total_seconds())
        if total_seconds <= 0:
            continue

        duration_minutes = total_seconds / 60
        if duration_minutes < request.threshold_minutes:
            continue

        completed.append(JobRun(
            jobname=jobname, jobcount=jobcount, username=username, status=status,
            duration=_format_duration(total_seconds), duration_seconds=total_seconds,
            duration_minutes=round(duration_minutes, 1),
            start=f"{strtdate} {strttime}", end=f"{enddate} {endtime}",
            start_date=strtdate, start_time=strttime, end_date=enddate, end_time=endtime,
        ))

    completed.sort(key=lambda j: j.duration_seconds, reverse=True)
    return completed[: request.top_n]


# ── get_job_trend_analysis ───────────────────────────────────────────

def _get_trend_recommendation(status: str, jobname: str) -> str:
    if status == "DEGRADING":
        return f"Job {jobname} is getting SLOWER. Investigate: table fragmentation, missing indexes, lock contention, data growth"
    if status == "IMPROVING":
        return f"Job {jobname} is getting FASTER — normal behavior"
    if status == "STABLE":
        return f"Job {jobname} performance is STABLE — no action needed"
    return "Insufficient data to determine trend"


def get_job_trend_analysis(conn: RfcConnection, jobname: str, days: int) -> TrendResult:
    conn.call("BAPI_XMI_LOGON", **_XMI_LOGON_KWARGS)

    safe_jobname = jobname.upper().replace("'", "''")
    cutoff_date = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")

    result = conn.call(
        "RFC_READ_TABLE", QUERY_TABLE="TBTCO", DELIMITER="|",
        OPTIONS=[{"TEXT": f"JOBNAME = '{safe_jobname}'"}, {"TEXT": f"AND STRTDATE >= '{cutoff_date}'"}],
        FIELDS=[{"FIELDNAME": f} for f in ("JOBNAME", "JOBCOUNT", "STRTDATE", "STRTTIME", "ENDDATE", "ENDTIME", "STATUS")],
    )

    data_rows = result.get("DATA", [])
    if not data_rows:
        conn.call("BAPI_XMI_LOGOFF")
        return TrendResult(status="NO_DATA", jobname=jobname, message=f"No job history found for {jobname} in last {days} days")

    runs_by_date: dict[str, list[int]] = defaultdict(list)
    for row in data_rows:
        parts = _parse_pipe_row(row.get("WA", ""), 7)
        if parts is None:
            continue
        _job_name, _job_count, strtdate, strttime, enddate, endtime, status = parts[:7]

        if not all([strtdate, strttime, enddate, endtime]) or status not in ("F", "A"):
            continue

        try:
            start_dt = datetime.strptime(f"{strtdate} {strttime}", "%Y%m%d %H%M%S")
            end_dt = datetime.strptime(f"{enddate} {endtime}", "%Y%m%d %H%M%S")
        except ValueError:
            continue

        duration_secs = int((end_dt - start_dt).total_seconds())
        if duration_secs <= 0:
            continue

        runs_by_date[strtdate].append(duration_secs)

    if not runs_by_date:
        conn.call("BAPI_XMI_LOGOFF")
        return TrendResult(status="NO_DATA", jobname=jobname, message=f"Could not parse job history for {jobname}")

    weeks: dict[int, list[int]] = defaultdict(list)
    for date_str, durations in runs_by_date.items():
        date_obj = datetime.strptime(date_str, "%Y%m%d")
        week_offset = int((date_obj - datetime.now()).days // 7)
        weeks[week_offset].extend(durations)

    week_stats: dict[str, WeekStats] = {}
    for week, durations in sorted(weeks.items()):
        if durations:
            week_stats[str(week)] = WeekStats(
                avg=sum(durations) / len(durations), min=min(durations), max=max(durations), count=len(durations),
            )

    weeks_sorted = sorted(int(w) for w in week_stats.keys())
    if len(weeks_sorted) < 2:
        trend_status, change_percent = "INSUFFICIENT_DATA", 0.0
    else:
        first_avg = week_stats[str(weeks_sorted[0])].avg
        last_avg = week_stats[str(weeks_sorted[-1])].avg
        change_percent = ((last_avg - first_avg) / first_avg) * 100 if first_avg else 0.0
        if change_percent > 10:
            trend_status = "DEGRADING"
        elif change_percent < -10:
            trend_status = "IMPROVING"
        else:
            trend_status = "STABLE"

    conn.call("BAPI_XMI_LOGOFF")

    return TrendResult(
        status=trend_status, jobname=jobname, period_days=days, weeks=week_stats,
        overall_change_percent=round(change_percent, 1), weeks_analyzed=len(week_stats),
        total_runs=sum(s.count for s in week_stats.values()),
        recommendation=_get_trend_recommendation(trend_status, jobname),
    )


# ── Tool-level report formatting ─────────────────────────────────────

def format_failed_jobs_report(sid: str, hours: int, jobs: list[FailedJob]) -> str:
    if not jobs:
        return f"✅ No failed jobs in last {hours}h for {sid}"
    lines = [f"Failed jobs [{sid}] last {hours}h:\n"]
    for j in jobs[:20]:
        lines.append(f"  ❌ {j.jobname} (jobcount: {j.jobcount})")
    return "\n".join(lines)


def format_job_log_report(sid: str, jobname: str, jobcount: str, logs: list[JobLogLine]) -> str:
    if not logs:
        return f"📭 No log entries found for {jobname} (jobcount {jobcount})."
    lines = [f"📋 Job log for {jobname} (jobcount {jobcount}) [{sid}]:\n"]
    for entry in logs[-50:]:
        lines.append(f"  {entry.date} {entry.time}  {entry.text}")
    return "\n".join(lines)


def format_long_running_jobs_report(sid: str, threshold_minutes: int, jobs: list[JobRun]) -> str:
    if not jobs:
        return f"✅ No jobs running longer than {threshold_minutes}m on {sid}"

    lines = [f"\n🚨 LONG-RUNNING JOBS [{sid}] (>{threshold_minutes}m)", "=" * 70 + "\n"]
    for job in jobs:
        lines.append(f"  {job.jobname:<20}  {job.duration:<10}  Started: {job.start}")
        lines.append(f"    Jobcount: {job.jobcount}  User: {job.username}")
        lines.append("")

    lines.append("=" * 70)
    lines.append(f"\nTotal: {len(jobs)} job(s) over threshold\n")
    lines.append("💡 Next steps:")
    lines.append(f"  1. Use get_job_log(sid='{sid}', jobname='...') to check current step")
    lines.append(f"  2. Check for locks: check_work_process_errors('{sid}')")
    lines.append("  3. Monitor: SM50 (work processes) or SM37 (job details)")
    lines.append(f"  4. Get trends: get_job_trend_analysis('{sid}', jobname='...')")
    return "\n".join(lines)


def format_completed_jobs_report(sid: str, request: CompletedJobsRequest, jobs: list[JobRun]) -> str:
    if request.from_date and request.to_date:
        frame_label = f"{request.from_date} {request.from_time or '000000'} to {request.to_date} {request.to_time or '235959'}"
    else:
        frame_label = f"Last {request.hours} hour(s)"

    if not jobs:
        return f"✅ No completed jobs found on {sid.upper()} for time frame: {frame_label}."

    lines = [f"\n✅ COMPLETED JOBS [{sid.upper()}]", "=" * 70, f"Time frame : {frame_label}", f"Returned   : {len(jobs)} job(s)", "=" * 70, ""]
    for idx, job in enumerate(jobs, 1):
        lines.append(f"{idx:>3}. {job.jobname}")
        lines.append(f"     Jobcount : {job.jobcount}")
        lines.append(f"     User     : {job.username}")
        lines.append("     Status   : F (Finished)")
        lines.append(f"     Started  : {job.start}")
        lines.append(f"     Ended    : {job.end}")
        lines.append(f"     Duration : {job.duration} ({job.duration_minutes} min)")
        lines.append("")

    lines.append("=" * 70)
    lines.append("💡 Notes:")
    lines.append("  • This report shows all completed jobs in the selected time frame.")
    lines.append("  • Cancelled jobs are not included.")
    lines.append("  • No duration threshold is applied.")
    lines.append("  • For completed jobs longer than 60 minutes, use get_longest_completed_jobs.")
    return "\n".join(lines)


def format_longest_completed_jobs_report(sid: str, request: LongestCompletedJobsRequest, jobs: list[JobRun]) -> str:
    if not jobs:
        if request.threshold_minutes and request.threshold_minutes > 0:
            return f"✅ No completed jobs found on {sid.upper()} longer than {request.threshold_minutes} minutes in the last {request.hours} hours."
        return f"✅ No completed jobs found on {sid.upper()} in the last {request.hours} hours."

    lines = [f"\n📊 LONGEST COMPLETED JOBS [{sid.upper()}]", "=" * 70, f"Lookback period : Last {request.hours} hour(s)", f"Returned        : Top {len(jobs)} job(s)"]
    if request.threshold_minutes and request.threshold_minutes > 0:
        lines.append(f"Threshold       : >= {request.threshold_minutes} minute(s)")
    lines.append("=" * 70)
    lines.append("")

    for idx, job in enumerate(jobs, 1):
        lines.append(f"{idx:>2}. {job.jobname}")
        lines.append(f"    Duration : {job.duration} ({job.duration_minutes} min)")
        lines.append(f"    Started  : {job.start}")
        lines.append(f"    Ended    : {job.end}")
        lines.append(f"    Jobcount : {job.jobcount}")
        lines.append(f"    User     : {job.username}")
        lines.append(f"    Status   : {job.status} (Finished)")
        lines.append("")

    lines.append("=" * 70)
    lines.append("")
    lines.append("💡 Notes:")
    lines.append("  • This report uses actual completed runtime:")
    lines.append("    ENDDATE/ENDTIME - STRTDATE/STRTTIME")
    lines.append("  • Cancelled jobs are excluded.")
    lines.append("  • Currently running jobs are not included here.")
    lines.append("  • For active long-running jobs, use get_long_running_jobs().")
    return "\n".join(lines)


def format_job_trend_report(sid: str, jobname: str, days: int, trend: TrendResult) -> str:
    if trend.status == "NO_DATA":
        return f"⚠️  {trend.message}"
    if trend.status == "INSUFFICIENT_DATA":
        return "⚠️  Insufficient data for trend analysis (need >= 2 weeks)"
    # Disclosed fix vs legacy (see module docstring): the legacy tool
    # wrapper never checked for this status and would have fallen through
    # to format an empty/misleading report instead of showing the error.
    if trend.status == "ERROR":
        return f"❌ Error analyzing trend for {jobname} on {sid}: {trend.message}"

    lines = [
        f"\n📈 Job Trend Analysis [{sid}] {jobname}", "=" * 70,
        f"Analysis period: Last {days} days",
        f"Total runs analyzed: {trend.total_runs}",
        f"Weeks with data: {trend.weeks_analyzed}\n",
    ]

    status_emoji = {
        "DEGRADING": "⚠️  DEGRADING ⬆️", "IMPROVING": "✅ IMPROVING ⬇️", "STABLE": "✔️  STABLE",
    }.get(trend.status, "❓ UNKNOWN")
    lines.append(f"Trend: {status_emoji}")
    lines.append(f"Overall change: {trend.overall_change_percent:+.1f}%\n")

    lines.append("Weekly breakdown (avg duration in minutes):")
    lines.append("-" * 70)
    week_keys = sorted(int(w) for w in trend.weeks.keys())
    for week_num in week_keys:
        stats = trend.weeks[str(week_num)]
        avg_min, min_min, max_min = stats.avg / 60, stats.min / 60, stats.max / 60
        if week_num == min(week_keys):
            week_label = f"Week {abs(week_num)} (oldest)"
        elif week_num == max(week_keys):
            week_label = f"Week {abs(week_num)} (latest)"
        else:
            week_label = f"Week {abs(week_num)}"
        lines.append(f"  {week_label:20} avg: {avg_min:7.1f}m (min: {min_min:6.1f}m, max: {max_min:6.1f}m) × {stats.count} runs")

    lines.append("=" * 70)
    lines.append("\n💡 Recommendation:")
    lines.append(f"  {trend.recommendation}")

    if trend.status == "DEGRADING":
        lines.append("\n⚠️  This job is getting SLOWER. Investigate:")
        lines.append("  • Table fragmentation: DBCC SHOWCONTIG (ASE) or similar")
        lines.append("  • Missing indexes: Check query plans in work process list")
        lines.append("  • Lock contention: Use SM50 to monitor during job run")
        lines.append("  • Data growth: Check table row counts")
        lines.append("  • Resource pressure: Monitor CPU/memory during execution")

    return "\n".join(lines)
