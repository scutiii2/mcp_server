"""MCP tool result models. Each ends with a human-readable ``message``."""

from __future__ import annotations

from pydantic import BaseModel

from src.models import FileInfo, JobStatus, ProbeResult


class ProbeToolResult(ProbeResult):
    message: str


class DownloadStarted(BaseModel):
    job_id: str
    message: str


class StatusToolResult(JobStatus):
    message: str


class ListFilesResult(BaseModel):
    files: list[FileInfo]
    message: str
