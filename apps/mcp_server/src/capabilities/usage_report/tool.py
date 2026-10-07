"""MCP tool wrappers for the usage_report capability - thin on purpose."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from src.capabilities.usage_report import domain
from src.capabilities.usage_report.contract import UsageSummaryResult
from src.commands import command
from src.config import settings
from src.offload import offload
from src.server import mcp


@command(name="summary", description="Token usage per agent, model or day")
@mcp.tool(meta={"keywords": ["usage", "tokens", "cost", "spend", "agent", "model", "report", "consumption"], "display_label": "Adding up usage"})
@offload
def tool_usage_summary(
    days: Annotated[int, Field(description="How many days back, today included.", ge=1, le=90)] = 7,
    group_by: Annotated[Literal["agent", "model", "day"], Field(description="What each row adds up.")] = "agent",
) -> UsageSummaryResult:
    """Add up token usage from ai_agent's usage log, per agent, model or day.
    Counts every answer an agent gave, including work delegated to it. The
    log folder comes from config; do not ask the user for it. Report tokens
    only - there is no price data here."""
    return domain.summarize(settings.usage_dir, days, group_by)
