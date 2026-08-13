"""Typed contracts for SAP background job tools.

FailedJob/JobLogLine/JobRun/TrendResult mirror the plain dicts the legacy
sap_utils.py functions returned - kept as real structured shapes here
since (like Dumps) the legacy code already separates data-fetching from
display formatting.
"""

from __future__ import annotations

from pydantic import BaseModel


class FailedJob(BaseModel):
    jobname: str
    jobcount: str


class JobLogRequest(BaseModel):
    sid: str
    jobname: str


class JobLogLine(BaseModel):
    date: str
    time: str
    text: str


class RescheduleJobRequest(BaseModel):
    sid: str
    jobname: str
    step_user: str = ""


class LongRunningJobsRequest(BaseModel):
    sid: str
    threshold_minutes: int = 60


class CompletedJobsRequest(BaseModel):
    sid: str
    hours: int = 24
    top_n: int = 100
    from_date: str = ""
    to_date: str = ""
    from_time: str = "000000"
    to_time: str = "235959"


class LongestCompletedJobsRequest(BaseModel):
    sid: str
    hours: int = 24
    top_n: int = 20
    threshold_minutes: int = 60


class JobRun(BaseModel):
    jobname: str
    jobcount: str
    username: str
    status: str
    duration: str
    duration_seconds: int
    duration_minutes: float = 0.0
    start: str
    end: str = ""
    start_date: str
    start_time: str
    end_date: str = ""
    end_time: str = ""


class JobTrendRequest(BaseModel):
    sid: str
    jobname: str
    days: int = 30


class WeekStats(BaseModel):
    avg: float
    min: float
    max: float
    count: int


class TrendResult(BaseModel):
    status: str
    jobname: str = ""
    message: str = ""
    period_days: int = 0
    weeks: dict[str, WeekStats] = {}
    overall_change_percent: float = 0.0
    weeks_analyzed: int = 0
    total_runs: int = 0
    recommendation: str = ""
