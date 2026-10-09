"""Request and response models shared by the REST routers and MCP tools."""

from __future__ import annotations

from pydantic import BaseModel


class PresetOption(BaseModel):
    id: str
    label: str
    kind: str
    estimated_bytes: int | None = None
    blocked: bool = False
    code: str | None = None  # error code when blocked
    reason: str | None = None  # plain-language reason when blocked


class ProbeResult(BaseModel):
    url: str
    title: str
    duration: float | None = None
    thumbnail: str | None = None
    uploader: str | None = None
    options: list[PresetOption]


from src.store.file_store import StoredFile  # noqa: E402  (kept at the bottom to keep the top of the file model-only)


class FileInfo(BaseModel):
    file_id: str
    name: str
    kind: str  # "video" or "audio"
    mime: str
    size: int
    duration: float | None = None
    expires_at: float
    download_url: str

    @classmethod
    def of(cls, stored: StoredFile, download_url: str) -> FileInfo:
        return cls(
            file_id=stored.file_id,
            name=stored.name,
            kind=stored.kind,
            mime=stored.mime,
            size=stored.size,
            duration=stored.duration,
            expires_at=stored.expires_at,
            download_url=download_url,
        )


class ErrorInfo(BaseModel):
    code: str
    message: str


class JobStatus(BaseModel):
    job_id: str
    state: str  # queued | downloading | processing | done | error
    percent: float | None = None
    speed: float | None = None
    eta: float | None = None
    file: FileInfo | None = None
    error: ErrorInfo | None = None


class ProbeRequest(BaseModel):
    url: str


class DownloadRequest(BaseModel):
    url: str
    preset: str
