"""Download routes: start a job, then follow it over server-sent events."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from src.api.deps import get_caller, get_service
from src.models import DownloadRequest, JobStatus
from src.service import Caller, DownloadService

router = APIRouter(prefix="/api")

KEEPALIVE_SECONDS = 15.0  # comment line on an idle SSE stream, so proxies and browsers keep it open


@router.post("/downloads", status_code=202)
async def start_download(
    body: DownloadRequest, caller: Caller = Depends(get_caller), service: DownloadService = Depends(get_service)
) -> dict:
    job = await service.start_download(caller, body.url, body.preset)
    return {"job_id": job.id}


@router.get("/jobs/{job_id}")
async def job_status(
    job_id: str, caller: Caller = Depends(get_caller), service: DownloadService = Depends(get_service)
) -> JobStatus:
    return service.job_status(caller, job_id)


@router.post("/jobs/{job_id}/cancel", status_code=202)
async def cancel_job(
    job_id: str, caller: Caller = Depends(get_caller), service: DownloadService = Depends(get_service)
) -> dict:
    service.cancel_job(caller, job_id)
    return {"job_id": job_id}


@router.get("/jobs/{job_id}/events")
async def job_events(
    job_id: str, caller: Caller = Depends(get_caller), service: DownloadService = Depends(get_service)
) -> StreamingResponse:
    job = service.get_job(caller, job_id)
    return StreamingResponse(
        _sse(job.stream()), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )


async def _sse(events: AsyncIterator[dict]) -> AsyncIterator[str]:
    """Events as SSE ``data:`` lines, with a ``: ping`` comment after KEEPALIVE_SECONDS of silence.

    The pending read is never cancelled by the timeout (that would close the job's
    stream); it stays in flight across pings and is cancelled only when the client leaves.
    """
    iterator = aiter(events)
    pending: asyncio.Future | None = None
    try:
        while True:
            if pending is None:
                pending = asyncio.ensure_future(anext(iterator))
            done, _ = await asyncio.wait({pending}, timeout=KEEPALIVE_SECONDS)
            if not done:
                yield ": ping\n\n"
                continue
            try:
                event = pending.result()
            except StopAsyncIteration:
                pending = None
                return
            pending = None
            yield f"data: {json.dumps(event)}\n\n"
    finally:
        if pending is not None and not pending.done():
            pending.cancel()
