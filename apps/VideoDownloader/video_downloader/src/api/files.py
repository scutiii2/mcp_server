"""File routes: list, delete and signed download."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from fastapi.responses import FileResponse

from src.api.deps import get_caller, get_service
from src.models import FileInfo
from src.service import Caller, DownloadService
from src.store.names import content_disposition

router = APIRouter(prefix="/api")
_NOSNIFF = {"X-Content-Type-Options": "nosniff"}


@router.get("/files")
async def list_files(caller: Caller = Depends(get_caller), service: DownloadService = Depends(get_service)) -> list[FileInfo]:
    return [service.file_info(f) for f in service.list_files(caller)]


@router.delete("/files/{file_id}", status_code=204)
async def delete_file(
    file_id: str, caller: Caller = Depends(get_caller), service: DownloadService = Depends(get_service)
) -> Response:
    await service.delete_file(caller, file_id)
    return Response(status_code=204)


@router.get("/files/{file_id}/download")
async def download(file_id: str, exp: int, sig: str, service: DownloadService = Depends(get_service)) -> FileResponse:
    """Signed link; no cookie needed. FileResponse honours Range requests, so players can seek."""
    file = service.file_for_download(file_id, exp, sig)
    return FileResponse(
        service.file_path(file),
        media_type=file.mime,
        headers={"Content-Disposition": content_disposition(file.name), "Cache-Control": "private, no-store", **_NOSNIFF},
    )
