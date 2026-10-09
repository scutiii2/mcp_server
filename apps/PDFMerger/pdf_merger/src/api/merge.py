"""Merge routes: start a job, then follow it over server-sent events."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from src.api.deps import get_caller, get_service
from src.models import MergePlan
from src.service import Caller, MergeService

router = APIRouter(prefix="/api")


@router.post("/merge", status_code=202)
async def start_merge(
    plan: MergePlan, caller: Caller = Depends(get_caller), service: MergeService = Depends(get_service)
) -> dict:
    job = service.start_merge(caller, plan)
    return {"job_id": job.id}


@router.get("/jobs/{job_id}/events")
async def job_events(
    job_id: str, caller: Caller = Depends(get_caller), service: MergeService = Depends(get_service)
) -> StreamingResponse:
    job = service.get_job(caller, job_id)

    async def body() -> AsyncIterator[str]:
        async for event in job.stream():
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(
        body(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )
