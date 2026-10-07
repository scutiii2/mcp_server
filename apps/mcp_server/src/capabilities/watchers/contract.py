"""Request/result models for the watch tools. Every result ends with a
`message` meant to be relayed to a person verbatim."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class CreateResult(BaseModel):
    key: str = Field(description="The watcher's id. Use it to cancel the watcher.")
    message: str = Field(description="What was set up: what is watched, how often, how long, and who gets the email.")


class WatcherRow(BaseModel):
    key: str = Field(description="The watcher's id.")
    phase: str = Field(description="running, completed, failed or timed_out.")
    started_at: str = Field(description="When the watcher started (ISO time).")
    last_polled_at: str = Field(description="When it last checked (ISO time).")
    detail: dict[str, Any] = Field(description="What is watched (kind, target, expect), the last check, the number of checks and the email outcome.")
    recipients: list[str] = Field(description="Who gets the email.")


class WatcherListResult(BaseModel):
    watchers: list[WatcherRow] = Field(description="The caller's own watchers, newest first.")
    message: str = Field(description="One-line summary of the listing.")


class CancelResult(BaseModel):
    key: str = Field(description="The watcher that was cancelled.")
    message: str = Field(description="One-line summary of what was done.")
