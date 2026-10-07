"""Request/result models for the usage_report tools. Every result ends
with a `message` meant to be relayed to a person verbatim."""

from __future__ import annotations

from pydantic import BaseModel, Field


class UsageRow(BaseModel):
    key: str = Field(description="The agent id, model or date this row adds up.")
    requests: int = Field(description="Answers counted, delegated ones included.")
    input_tokens: int = Field(description="Prompt tokens.")
    output_tokens: int = Field(description="Reply tokens.")
    total_tokens: int = Field(description="Input plus output tokens.")


class UsageSummaryResult(BaseModel):
    days: int = Field(description="How many days back the report covers, today included.")
    group_by: str = Field(description="What each row adds up: agent, model or day.")
    rows: list[UsageRow] = Field(description="One row per group, largest total first (by date for day).")
    requests: int = Field(description="Answers in the whole period.")
    total_tokens: int = Field(description="Tokens in the whole period.")
    skipped_lines: int = Field(description="Log lines that could not be read and were left out.")
    message: str = Field(description="One-line summary of the report.")
