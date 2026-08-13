"""Typed contracts for SAP monitoring tools.

Unlike control's results (real success/failure, multi-SID semantics),
most monitoring tools are pure "produce a formatted report string"
functions in the legacy code - so their contracts stay simple: one
shared request shape, and each domain function returns the report text
directly rather than a wrapping result model.
"""

from __future__ import annotations

from pydantic import BaseModel


class SidRequest(BaseModel):
    sid: str


class DiskUsageRequest(BaseModel):
    sid: str
    threshold: int = 80


class FindLargestFilesRequest(BaseModel):
    sid: str
    mount_path: str
    top_n: int = 10
