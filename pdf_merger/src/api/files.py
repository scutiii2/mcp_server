"""File routes: upload, list, delete, raw content and signed download."""

from __future__ import annotations

from urllib.parse import unquote

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import FileResponse

from src.api.deps import get_caller, get_service
from src.errors import ErrorCode, MergerError
from src.models import FileInfo
from src.service import Caller, MergeService
from src.store.names import content_disposition

router = APIRouter(prefix="/api")


@router.post("/files", status_code=201)
async def upload_file(
    request: Request, caller: Caller = Depends(get_caller), service: MergeService = Depends(get_service)
) -> FileInfo:
    """Raw request body is the file; X-Filename carries its URL-encoded name."""
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > request.app.state.settings.limits.max_file_bytes:
        raise MergerError(ErrorCode.FILE_TOO_LARGE, "This file is over the size limit. Split or compress it, then upload it again.")
    name = unquote(request.headers.get("X-Filename", ""))
    stored = await service.upload(caller, name, request.stream())
    return FileInfo.of(stored)


@router.get("/files")
async def list_files(caller: Caller = Depends(get_caller), service: MergeService = Depends(get_service)) -> list[FileInfo]:
    return [FileInfo.of(f) for f in service.list_files(caller)]


@router.delete("/files/{file_id}", status_code=204)
async def delete_file(
    file_id: str, caller: Caller = Depends(get_caller), service: MergeService = Depends(get_service)
) -> Response:
    await service.delete_file(caller, file_id)
    return Response(status_code=204)


@router.get("/files/{file_id}/content")
async def file_content(
    file_id: str, caller: Caller = Depends(get_caller), service: MergeService = Depends(get_service)
) -> FileResponse:
    file = service.get_file(caller, file_id)
    return FileResponse(
        service.file_path(file),
        media_type=file.mime,
        headers={"Content-Disposition": content_disposition(file.name, inline=True), "Cache-Control": "private, max-age=3600"},
    )


@router.get("/files/{file_id}/download")
async def download(file_id: str, exp: int, sig: str, service: MergeService = Depends(get_service)) -> FileResponse:
    """Signed link; no cookie needed."""
    file = service.file_for_download(file_id, exp, sig)
    return FileResponse(
        service.file_path(file),
        media_type=file.mime,
        headers={"Content-Disposition": content_disposition(file.name), "Cache-Control": "private, no-store"},
    )
