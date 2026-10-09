"""POST /api/probe: look a link up before downloading."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from src.api.deps import get_service
from src.models import ProbeRequest, ProbeResult
from src.service import DownloadService

router = APIRouter(prefix="/api")


@router.post("/probe")
async def probe(body: ProbeRequest, service: DownloadService = Depends(get_service)) -> ProbeResult:
    return await service.probe(body.url)
