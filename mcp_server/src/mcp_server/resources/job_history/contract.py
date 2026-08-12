"""Typed request/result contracts for the background-job-history resource."""

from __future__ import annotations

from pydantic import BaseModel


class JobHistoryRequest(BaseModel):
    sid: str


class JobRecord(BaseModel):
    jobname: str
    jobcount: str
    status: str
    start_date: str
    start_time: str
    end_date: str
    end_time: str


class JobHistoryResult(BaseModel):
    sid: str
    jobs: list[JobRecord]
