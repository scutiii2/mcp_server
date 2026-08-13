"""Domain tests for job monitoring tools - fake RFC connection objects
matching the RfcConnection Protocol's .call()/.close() interface, no
pyrfc import anywhere in this file.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from mcp_server.capabilities.jobs.contract import (
    CompletedJobsRequest,
    FailedJob,
    JobRun,
    LongestCompletedJobsRequest,
    LongRunningJobsRequest,
    TrendResult,
    WeekStats,
)
from mcp_server.capabilities.jobs.domain import (
    _get_trend_recommendation,
    _parse_pipe_row,
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


class FakeRfcConnection:
    """Records every .call() so tests can assert on RFC function names and
    arguments; returns canned results keyed by function name."""

    def __init__(self, results: dict[str, dict] | None = None, results_sequence: list[dict] | None = None):
        self.results = results or {}
        self.results_sequence = results_sequence
        self.calls: list[dict] = []
        self.closed = False

    def call(self, function_name: str, **kwargs) -> dict:
        self.calls.append({"function_name": function_name, **kwargs})
        if self.results_sequence is not None:
            return self.results_sequence[len([c for c in self.calls if c["function_name"] == function_name]) - 1]
        return self.results.get(function_name, {})

    def close(self) -> None:
        self.closed = True


# ── _parse_pipe_row ───────────────────────────────────────────────────

def test_parse_pipe_row_valid():
    assert _parse_pipe_row("a|b|c", 3) == ["a", "b", "c"]


def test_parse_pipe_row_too_short_returns_none():
    assert _parse_pipe_row("a|b", 3) is None


def test_parse_pipe_row_empty_returns_none():
    assert _parse_pipe_row("", 3) is None


def test_parse_pipe_row_strips_whitespace():
    assert _parse_pipe_row(" a | b |c ", 3) == ["a", "b", "c"]


# ── get_failed_jobs ───────────────────────────────────────────────────

def test_get_failed_jobs_groups_latest_occurrence_per_jobname():
    conn = FakeRfcConnection(results={
        "BAPI_XBP_JOB_SELECT": {"SELECTED_JOBS": [
            {"JOBNAME": "Z_JOB_A", "JOBCOUNT": "00000001"},
            {"JOBNAME": "Z_JOB_A", "JOBCOUNT": "00000005"},  # later occurrence, should win
            {"JOBNAME": "Z_JOB_B", "JOBCOUNT": "00000002"},
        ]}
    })

    jobs = get_failed_jobs(conn, "RFC_USER")

    by_name = {j.jobname: j.jobcount for j in jobs}
    assert by_name == {"Z_JOB_A": "00000005", "Z_JOB_B": "00000002"}


def test_get_failed_jobs_calls_xmi_logon_and_logoff():
    conn = FakeRfcConnection(results={"BAPI_XBP_JOB_SELECT": {"SELECTED_JOBS": []}})

    get_failed_jobs(conn, "RFC_USER")

    function_names = [c["function_name"] for c in conn.calls]
    assert function_names == ["BAPI_XMI_LOGON", "BAPI_XBP_JOB_SELECT", "BAPI_XMI_LOGOFF"]


def test_get_failed_jobs_empty():
    conn = FakeRfcConnection(results={"BAPI_XBP_JOB_SELECT": {"SELECTED_JOBS": []}})
    assert get_failed_jobs(conn, "RFC_USER") == []


# ── get_job_log_entries ──────────────────────────────────────────────

def test_get_job_log_entries_formats_date_and_time():
    conn = FakeRfcConnection(results={
        "BAPI_XBP_JOB_JOBLOG_READ": {"JOB_PROTOCOL": [
            {"ENTERDATE": "20260810", "ENTERTIME": "143000", "TEXT": "Job started"},
        ]}
    })

    logs = get_job_log_entries(conn, "Z_JOB", "00000001", "RFC_USER")

    assert logs[0].date == "10.08.2026"
    assert logs[0].time == "14:30:00"
    assert logs[0].text == "Job started"


# ── reschedule_job ────────────────────────────────────────────────────

def test_reschedule_job_open_failure_returns_clean_error():
    conn = FakeRfcConnection(results={
        "BAPI_XBP_JOB_DEFINITION_GET": {"STEP_TBL": []},
        "BAPI_XBP_JOB_OPEN": {"RETURN": {"TYPE": "E", "MESSAGE": "Job locked"}},
    })

    ok, msg = reschedule_job(conn, "Z_JOB", "00000001", "RFC_USER")

    assert ok is False
    assert msg == "Job locked"


def test_reschedule_job_no_jobcount_returned():
    conn = FakeRfcConnection(results={
        "BAPI_XBP_JOB_DEFINITION_GET": {"STEP_TBL": []},
        "BAPI_XBP_JOB_OPEN": {"RETURN": {"TYPE": "S"}},  # success but no JOBCOUNT key
    })

    ok, msg = reschedule_job(conn, "Z_JOB", "00000001", "RFC_USER")

    assert ok is False
    assert "No jobcount returned" in msg


def test_reschedule_job_full_success_via_step_tbl():
    conn = FakeRfcConnection(results={
        "BAPI_XBP_JOB_DEFINITION_GET": {"STEP_TBL": [
            {"TYP": "A", "PROGRAM": "ZPROG1", "PARAMETER": "VAR1", "AUTHCKNAM": "jdoe"},
        ]},
        "BAPI_XBP_JOB_OPEN": {"RETURN": {"TYPE": "S"}, "JOBCOUNT": "00000099"},
        "BAPI_XBP_JOB_ADD_ABAP_STEP": {"RETURN": {"TYPE": "S"}},
        "BAPI_XBP_JOB_CLOSE": {"RETURN": {"TYPE": "S"}},
        "BAPI_XBP_JOB_START_IMMEDIATELY": {"RETURN": {"TYPE": "S"}},
    })

    ok, msg = reschedule_job(conn, "Z_JOB", "00000001", "RFC_USER")

    assert ok is True
    assert "00000099" in msg
    assert "original step user kept" in msg


def test_reschedule_job_with_explicit_step_user():
    conn = FakeRfcConnection(results={
        "BAPI_XBP_JOB_DEFINITION_GET": {"STEP_TBL": [{"TYP": "A", "PROGRAM": "ZPROG1", "PARAMETER": "", "AUTHCKNAM": "jdoe"}]},
        "BAPI_XBP_JOB_OPEN": {"RETURN": {"TYPE": "S"}, "JOBCOUNT": "00000099"},
        "BAPI_XBP_JOB_ADD_ABAP_STEP": {"RETURN": {"TYPE": "S"}},
        "BAPI_XBP_JOB_CLOSE": {"RETURN": {"TYPE": "S"}},
        "BAPI_XBP_JOB_START_IMMEDIATELY": {"RETURN": {"TYPE": "S"}},
    })

    ok, msg = reschedule_job(conn, "Z_JOB", "00000001", "RFC_USER", step_user="newuser")

    assert ok is True
    assert "step user changed to NEWUSER" in msg
    add_step_call = next(c for c in conn.calls if c["function_name"] == "BAPI_XBP_JOB_ADD_ABAP_STEP")
    assert add_step_call["SAP_USER_NAME"] == "NEWUSER"


def test_reschedule_job_no_steps_extracted():
    conn = FakeRfcConnection(results={
        "BAPI_XBP_JOB_DEFINITION_GET": {"STEP_TBL": []},
        "BAPI_XBP_JOB_OPEN": {"RETURN": {"TYPE": "S"}, "JOBCOUNT": "00000099"},
    })

    ok, msg = reschedule_job(conn, "Z_JOB", "00000001", "RFC_USER")

    assert ok is False
    assert "Could not extract ABAP step" in msg


# ── get_long_running_jobs ────────────────────────────────────────────

def _tbtco_row(jobname, jobcount, user, strtdate, strttime, enddate, endtime, status):
    return {"WA": f"{jobname}|{jobcount}|{user}|{strtdate}|{strttime}|{enddate}|{endtime}|{status}"}


def test_get_long_running_jobs_still_running_uses_elapsed_time():
    now = datetime.now()
    start = now - timedelta(hours=2)
    conn = FakeRfcConnection(results={
        "RFC_READ_TABLE": {"DATA": [
            _tbtco_row("Z_LONG", "1", "jdoe", start.strftime("%Y%m%d"), start.strftime("%H%M%S"), "", "", "R"),
        ]}
    })

    jobs = get_long_running_jobs(conn, LongRunningJobsRequest(sid="E4G", threshold_minutes=60))

    assert len(jobs) == 1
    assert jobs[0].jobname == "Z_LONG"
    assert jobs[0].duration_seconds >= 7000  # ~2 hours


def test_get_long_running_jobs_excludes_aborted():
    conn = FakeRfcConnection(results={
        "RFC_READ_TABLE": {"DATA": [
            _tbtco_row("Z_ABORTED", "1", "jdoe", "20260810", "100000", "20260810", "100100", "A"),
        ]}
    })

    jobs = get_long_running_jobs(conn, LongRunningJobsRequest(sid="E4G", threshold_minutes=60))
    assert jobs == []


def test_get_long_running_jobs_below_threshold_excluded():
    now = datetime.now()
    start = now - timedelta(minutes=5)
    conn = FakeRfcConnection(results={
        "RFC_READ_TABLE": {"DATA": [
            _tbtco_row("Z_QUICK", "1", "jdoe", start.strftime("%Y%m%d"), start.strftime("%H%M%S"), "", "", "R"),
        ]}
    })

    jobs = get_long_running_jobs(conn, LongRunningJobsRequest(sid="E4G", threshold_minutes=60))
    assert jobs == []


# ── get_completed_jobs ───────────────────────────────────────────────

def test_get_completed_jobs_excludes_non_finished_status():
    conn = FakeRfcConnection(results={
        "RFC_READ_TABLE": {"DATA": [
            _tbtco_row("Z_RUNNING", "1", "jdoe", "20260810", "100000", "20260810", "110000", "R"),
        ]}
    })

    jobs = get_completed_jobs(conn, CompletedJobsRequest(sid="E4G", hours=24))
    assert jobs == []


def test_get_completed_jobs_computes_duration():
    conn = FakeRfcConnection(results={
        "RFC_READ_TABLE": {"DATA": [
            _tbtco_row("Z_DONE", "1", "jdoe", "20260810", "100000", "20260810", "103000", "F"),
        ]}
    })

    jobs = get_completed_jobs(conn, CompletedJobsRequest(sid="E4G", hours=24))

    assert len(jobs) == 1
    assert jobs[0].duration == "0:30:00"
    assert jobs[0].duration_minutes == 30.0


def test_get_completed_jobs_respects_explicit_date_range():
    conn = FakeRfcConnection(results={"RFC_READ_TABLE": {"DATA": [
        _tbtco_row("Z_IN_RANGE", "1", "jdoe", "20260810", "100000", "20260810", "103000", "F"),
        _tbtco_row("Z_OUT_OF_RANGE", "2", "jdoe", "20260801", "100000", "20260801", "103000", "F"),
    ]}})

    jobs = get_completed_jobs(conn, CompletedJobsRequest(sid="E4G", from_date="20260810", to_date="20260810"))

    assert [j.jobname for j in jobs] == ["Z_IN_RANGE"]


def test_get_completed_jobs_respects_top_n():
    rows = [_tbtco_row(f"Z_JOB_{i}", str(i), "jdoe", "20260810", "100000", "20260810", "100100", "F") for i in range(5)]
    conn = FakeRfcConnection(results={"RFC_READ_TABLE": {"DATA": rows}})

    jobs = get_completed_jobs(conn, CompletedJobsRequest(sid="E4G", hours=24, top_n=2))
    assert len(jobs) == 2


# ── get_longest_completed_jobs ───────────────────────────────────────

def test_get_longest_completed_jobs_applies_threshold():
    conn = FakeRfcConnection(results={"RFC_READ_TABLE": {"DATA": [
        _tbtco_row("Z_SHORT", "1", "jdoe", "20260810", "100000", "20260810", "100500", "F"),   # 5 min
        _tbtco_row("Z_LONG", "2", "jdoe", "20260810", "100000", "20260810", "110000", "F"),    # 60 min
    ]}})

    jobs = get_longest_completed_jobs(conn, LongestCompletedJobsRequest(sid="E4G", hours=24, threshold_minutes=30))

    assert [j.jobname for j in jobs] == ["Z_LONG"]


def test_get_longest_completed_jobs_sorted_descending():
    conn = FakeRfcConnection(results={"RFC_READ_TABLE": {"DATA": [
        _tbtco_row("Z_MEDIUM", "1", "jdoe", "20260810", "100000", "20260810", "103000", "F"),  # 30 min
        _tbtco_row("Z_LONGEST", "2", "jdoe", "20260810", "100000", "20260810", "120000", "F"), # 120 min
    ]}})

    jobs = get_longest_completed_jobs(conn, LongestCompletedJobsRequest(sid="E4G", hours=24, threshold_minutes=0))

    assert [j.jobname for j in jobs] == ["Z_LONGEST", "Z_MEDIUM"]


# ── get_job_trend_analysis ───────────────────────────────────────────

def test_get_job_trend_analysis_no_data():
    conn = FakeRfcConnection(results={"RFC_READ_TABLE": {"DATA": []}})

    trend = get_job_trend_analysis(conn, "Z_JOB", 30)

    assert trend.status == "NO_DATA"


def test_get_job_trend_analysis_insufficient_data_single_week():
    row = {"WA": "Z_JOB|1|20260810|100000|20260810|100500|F"}
    conn = FakeRfcConnection(results={"RFC_READ_TABLE": {"DATA": [row]}})

    trend = get_job_trend_analysis(conn, "Z_JOB", 30)

    assert trend.status == "INSUFFICIENT_DATA"


def test_get_job_trend_analysis_detects_degrading():
    old_date = (datetime.now() - timedelta(days=20)).strftime("%Y%m%d")
    recent_date = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")
    rows = [
        {"WA": f"Z_JOB|1|{old_date}|100000|{old_date}|100100|F"},   # 60s
        {"WA": f"Z_JOB|2|{recent_date}|100000|{recent_date}|100500|F"},  # 300s - 5x slower
    ]
    conn = FakeRfcConnection(results={"RFC_READ_TABLE": {"DATA": rows}})

    trend = get_job_trend_analysis(conn, "Z_JOB", 30)

    assert trend.status == "DEGRADING"
    assert trend.overall_change_percent > 10


def test_get_trend_recommendation_covers_all_statuses():
    assert "SLOWER" in _get_trend_recommendation("DEGRADING", "Z")
    assert "FASTER" in _get_trend_recommendation("IMPROVING", "Z")
    assert "STABLE" in _get_trend_recommendation("STABLE", "Z")
    assert "Insufficient" in _get_trend_recommendation("UNKNOWN", "Z")


# ── report formatting ─────────────────────────────────────────────────

def test_format_failed_jobs_report_empty():
    assert format_failed_jobs_report("E4G", 24, []) == "✅ No failed jobs in last 24h for E4G"


def test_format_failed_jobs_report_lists_jobs():
    jobs = [FailedJob(jobname="Z_JOB", jobcount="00000001")]
    result = format_failed_jobs_report("E4G", 24, jobs)
    assert "Z_JOB" in result
    assert "00000001" in result


def test_format_job_log_report_empty():
    assert format_job_log_report("E4G", "Z_JOB", "1", []) == "📭 No log entries found for Z_JOB (jobcount 1)."


def test_format_long_running_jobs_report_empty():
    assert format_long_running_jobs_report("E4G", 60, []) == "✅ No jobs running longer than 60m on E4G"


def test_format_job_trend_report_handles_error_status():
    """Disclosed fix vs legacy - the ERROR status was never checked in the
    original tool wrapper and would have fallen through to a misleading
    empty-report format instead."""
    trend = TrendResult(status="ERROR", message="RFC connection timed out")
    result = format_job_trend_report("E4G", "Z_JOB", 30, trend)
    assert "RFC connection timed out" in result
    assert "❌" in result


def test_format_job_trend_report_no_data():
    trend = TrendResult(status="NO_DATA", message="No job history found for Z_JOB in last 30 days")
    result = format_job_trend_report("E4G", "Z_JOB", 30, trend)
    assert "No job history found" in result


def test_format_job_trend_report_degrading_includes_investigation_tips():
    trend = TrendResult(
        status="DEGRADING", jobname="Z_JOB", total_runs=10, weeks_analyzed=3,
        overall_change_percent=25.0, recommendation="Job Z_JOB is getting SLOWER.",
        weeks={"-2": WeekStats(avg=60, min=50, max=70, count=3), "0": WeekStats(avg=90, min=80, max=100, count=3)},
    )
    result = format_job_trend_report("E4G", "Z_JOB", 30, trend)
    assert "DEGRADING" in result
    assert "Table fragmentation" in result
