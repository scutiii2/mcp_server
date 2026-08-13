"""Typed contracts for ABAP short-dump tools.

Unlike monitoring's tools (which return one pre-formatted string each),
the legacy dumps code genuinely separates data-fetching (sap_utils.py's
get_abap_dumps/get_dump_detail, which return structured dicts) from
display formatting (mcp_server.py's tool functions). This contract
mirrors that split: DumpSummary/DumpAnalysis are real structured shapes,
not just formatted strings.
"""

from __future__ import annotations

from pydantic import BaseModel


class AbapDumpsRequest(BaseModel):
    sid: str
    hours: int = 24
    dump_date: str = ""


class DumpSummary(BaseModel):
    user: str
    date: str
    time: str
    host: str
    mandt: str
    crash_key: str
    runtime_error: str
    program: str


class DumpAnalysis(BaseModel):
    runtime_error: str = ""
    program: str = ""
    include: str = ""
    method: str = ""
    missing_object: str = ""
    sql_code: str = ""
    source_line: str = ""
    failing_statement: str = ""
    root_cause: str = ""
    recommendation: str = ""
    text: str = ""
