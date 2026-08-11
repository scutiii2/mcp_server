"""Typed request/result contracts for SAP control tools (stop/start).

Defining these once, as Pydantic models, means:
  - FastMCP derives a real JSON schema for the tool automatically (no
    hand-written description strings to keep in sync).
  - The Flask capabilities browser can render a proper input form per
    tool instead of a free-text blob.
  - The domain layer, tool wrapper, and any tests all import the exact
    same shape - no drift between what a tool "returns" in three places.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class StopSapRequest(BaseModel):
    sid: str = Field(..., description="SAP system ID to stop, e.g. E4G")


class StopSapResult(BaseModel):
    sid: str
    success: bool
    message: str
