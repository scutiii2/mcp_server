from __future__ import annotations

from datetime import datetime

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from src.db import Base


class TrafficBucket(Base):
    """Requests (and upstream calls) counted per hour, never one row each.

    kind: "http" (a request ember_api served; name "GET /api/chats/{chat_id}",
    status "2xx".."5xx") or "upstream" (a call ember_api made to ai_agent or
    mcp_server; name "ai_agent ask", status "ok" or "failed"). `band` is an
    index into services.traffic.LATENCY_BANDS_MS, so percentiles can be read
    back without storing every request. `total_ms` is the summed duration.
    Nothing here identifies a person: no account, IP, query string or body."""

    __tablename__ = "traffic_buckets"

    hour: Mapped[datetime] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(10), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), primary_key=True)
    status: Mapped[str] = mapped_column(String(8), primary_key=True)
    band: Mapped[int] = mapped_column(primary_key=True)
    count: Mapped[int]
    total_ms: Mapped[int]
