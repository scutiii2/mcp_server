"""Shapes for the host-health tool.

The models are **re-exported from the resource**, not redefined. Both
primitives describe the same facts about the same machine, so a second
copy would only be a second thing to forget when a field changes - and
the two would drift silently, since nothing compares them.

What the tool adds is a result wrapper. The resource returns bare text
because a resource read *is* its content; a tool answers a model that has
to decide what to do next, so it gets the rendered report alongside the
name it was asked about and the structured figures behind it.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

# Re-exported so callers of this capability never need to reach into
# resources/ for a type. The definitions live there because that is where
# the domain logic lives.
from mcp_server.resources.host_health.contract import DiskUsage, HostHealth

__all__ = ["DiskUsage", "HostHealth", "HostHealthResult"]


class HostHealthResult(BaseModel):
    name: str = Field(description="The configured host name that was checked.")
    report: str = Field(
        description="Human-readable summary, safe to relay verbatim to whoever asked."
    )
    health: HostHealth = Field(
        description=(
            "The same figures in structured form - use these to compare, "
            "threshold or chart, rather than parsing the report text."
        )
    )
