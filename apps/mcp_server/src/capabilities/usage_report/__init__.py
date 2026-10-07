"""Usage report: token usage per agent, model or day, read from ai_agent's usage log."""

from src.services import capability_meta

META = capability_meta.register(folder="usage_report", id="usage", label="Usage Report")
