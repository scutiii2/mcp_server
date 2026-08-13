"""Typed contracts for S/4HANA conversion pre-check tools."""

from __future__ import annotations

from pydantic import BaseModel


class SidRequest(BaseModel):
    sid: str
