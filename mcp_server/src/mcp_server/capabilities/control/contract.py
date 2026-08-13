"""Typed request/result contracts for SAP control tools (list/stop/start).

Defining these once, as Pydantic models, means:
  - FastMCP derives a real JSON schema for the tool automatically (no
    hand-written description strings to keep in sync).
  - The Flask capabilities browser can render a proper input form per
    tool instead of a free-text blob.
  - The domain layer, tool wrapper, and any tests all import the exact
    same shape - no drift between what a tool "returns" in three places.

Stop and start share one request/result shape - they're symmetric
operations over the same multi-tier landscape, just in opposite order.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class SapSystemInfo(BaseModel):
    sid: str
    host: str


class AvailableSidsResult(BaseModel):
    systems: list[SapSystemInfo]


class SapControlRequest(BaseModel):
    sid: str = Field(
        ...,
        description="One SID, or comma-separated SIDs to act on together, e.g. 'S4E' or 'S4E,E4G'",
    )


class SapControlResult(BaseModel):
    sid: str
    success: bool
    message: str


class MultiSapControlResult(BaseModel):
    results: list[SapControlResult]
