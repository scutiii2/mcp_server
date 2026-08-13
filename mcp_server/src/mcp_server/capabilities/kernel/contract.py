"""Typed contract for the kernel update tool."""

from __future__ import annotations

from pydantic import BaseModel


class KernelUpdateRequest(BaseModel):
    sid: str
