"""/api/traffic: the Analytics page's Traffic tab (counters from services/traffic.py)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.deps import get_db_session, require_permission
from src.models import Account
from src.services.log_analytics import Period
from src.services.permissions import TRAFFIC_VIEW
from src.services.traffic_analytics import TrafficAnalytics, TrafficReport

router = APIRouter(prefix="/api/traffic", tags=["traffic"])

require_traffic = require_permission(TRAFFIC_VIEW)


@router.get("/analytics")
async def traffic_analytics(
    period: Period = Query(default="7d", alias="range"),
    _account: Account = Depends(require_traffic),
    session: AsyncSession = Depends(get_db_session),
) -> TrafficReport:
    """Requests, latency and upstream calls over the last 24h / 7d / 30d / 90d,
    compared with the period before. Counts only; nothing identifies a person."""
    return await TrafficAnalytics(session).report(period)
