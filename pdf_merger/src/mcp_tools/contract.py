"""MCP tool result models. Each ends with a human-readable ``message``."""

from __future__ import annotations

from pydantic import BaseModel

from src.models import FileInfo, MergeResult


class FailedItem(BaseModel):
    file_id: str
    code: str
    message: str


class InspectResult(BaseModel):
    files: list[FileInfo]
    failed: list[FailedItem]
    message: str


class ListFilesResult(BaseModel):
    files: list[FileInfo]
    message: str


class MergeToolResult(MergeResult):
    message: str
