"""Typed contracts for SAP health tools."""

from __future__ import annotations

from pydantic import BaseModel


class SidRequest(BaseModel):
    sid: str


class MaintenanceModeRequest(BaseModel):
    sid: str
    enable: bool
