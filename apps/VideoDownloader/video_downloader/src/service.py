"""DownloadService: the one facade the REST routers and MCP tools call.

It composes the URL policy, extractor, file store, job queue and link signer.
Routers and tools hold no logic of their own.
"""

from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from src.config import Limits, Settings
from src.errors import LIVE_STREAM_MESSAGE, DownloaderError, ErrorCode
from src.extractor.base import Extractor
from src.extractor.models import DownloadProgress, MediaInfo
from src.extractor.options import available_presets, build_options, estimate_size
from src.extractor.presets import Preset, get_preset
from src.jobs.job_queue import Emit, Job, JobQueue
from src.models import ErrorInfo, FileInfo, JobStatus, ProbeResult
from src.policy.url_policy import UrlPolicy
from src.store.file_store import FileStore, StoredFile
from src.store.names import mime_for, safe_filename
from src.store.signing import LinkSigner

_STATE_BY_EVENT = {"queued": "queued", "progress": "downloading", "processing": "processing", "done": "done", "error": "error"}


@dataclass(frozen=True)
class Caller:
    """Who is asking. ``privileged`` callers (internal token) may open any file by ID."""

    session: str
    privileged: bool = False

    @property
    def scope(self) -> str | None:
        return None if self.privileged else self.session


class DownloadService:
    """Facade over probing, downloading, files, jobs and signed download links."""

    def __init__(
        self,
        *,
        store: FileStore,
        extractor: Extractor,
        policy: UrlPolicy,
        jobs: JobQueue,
        signer: LinkSigner,
        limits: Limits,
        public_base_url: str,
        file_ttl_seconds: int,
    ) -> None:
        self._store = store
        self._extractor = extractor
        self._policy = policy
        self._jobs = jobs
        self._signer = signer
        self._limits = limits
        self._public_base_url = public_base_url.rstrip("/")
        self._file_ttl = file_ttl_seconds

    @property
    def store(self) -> FileStore:
        return self._store

    # --- probing -----------------------------------------------------------

    async def probe(self, url: str) -> ProbeResult:
        clean = await self._policy.check(url)
        info = await asyncio.to_thread(self._extractor.probe, clean)
        return ProbeResult(
            url=clean,
            title=info.title,
            duration=info.duration,
            thumbnail=info.thumbnail,
            uploader=info.uploader,
            options=build_options(info, self._limits),
        )

    # --- downloading -------------------------------------------------------

    async def start_download(self, caller: Caller, url: str, preset_id: str) -> Job:
        """Validate cheaply, then queue the job. Probe-based caps are checked again inside the job."""
        preset = get_preset(preset_id)
        clean = await self._policy.check(url)

        async def work(emit: Emit, cancel: threading.Event) -> dict:
            return await self._run_download(caller.session, clean, preset, emit, cancel)

        return self._jobs.submit(caller.session, work)

    def _enforce_caps(self, info: MediaInfo, preset: Preset, session: str) -> None:
        """Re-check everything the probe showed; never trust what the client saw earlier."""
        if info.is_live:
            raise DownloaderError(ErrorCode.LIVE_STREAM, LIVE_STREAM_MESSAGE)
        if preset.id not in {p.id for p in available_presets(info)}:
            raise DownloaderError(ErrorCode.INVALID_REQUEST, "This video isn't available in that quality. Probe it again and pick another.")
        if info.duration is not None and info.duration > self._limits.max_duration_seconds:
            raise DownloaderError(
                ErrorCode.TOO_LONG, f"Videos longer than {int(self._limits.max_duration_seconds // 60)} minutes are not allowed."
            )
        estimate = estimate_size(info, preset)
        if estimate is None:
            return
        if estimate > self._limits.max_file_bytes:
            raise DownloaderError(
                ErrorCode.TOO_LARGE,
                f"This would be about {estimate // (1024 * 1024)} MB; the limit is {self._limits.max_file_bytes // (1024 * 1024)} MB. Pick a lower quality.",
            )
        if self._store.session_usage(session) + estimate > self._limits.max_session_bytes:
            raise DownloaderError(
                ErrorCode.LIMIT_EXCEEDED, "Your files would use more space than allowed. Delete some files or wait for them to expire."
            )

    async def _run_download(self, session: str, url: str, preset: Preset, emit: Emit, cancel: threading.Event) -> dict:
        info = await asyncio.to_thread(self._extractor.probe, url)
        if cancel.is_set():  # cancelled while probing: don't start the download
            raise DownloaderError(ErrorCode.CANCELLED, "The download was cancelled.")
        self._enforce_caps(info, preset, session)

        def on_progress(progress: DownloadProgress) -> None:
            if progress.stage == "processing":
                emit({"type": "processing"})
            else:
                emit({"type": "progress", "percent": progress.percent, "speed": progress.speed, "eta": progress.eta})

        work_dir = await self._store.make_work_dir()
        try:
            downloaded = await asyncio.to_thread(
                self._extractor.download,
                url,
                preset,
                work_dir,
                max_bytes=self._limits.max_file_bytes,
                # The download extracts again; duration and live status are re-checked on that extraction.
                max_duration_seconds=self._limits.max_duration_seconds,
                on_progress=on_progress,
                cancel=cancel,
            )
            suffix = downloaded.path.suffix
            stored = await self._store.commit_file(
                session,
                downloaded.path,
                name=safe_filename(info.title, "video") + suffix,
                mime=mime_for(suffix),
                kind=preset.kind,
                duration=info.duration,
            )
        finally:
            await self._store.remove_work_dir(work_dir)
        file = self.file_info(stored)
        return {"file_id": stored.file_id, "file": file.model_dump(mode="json")}

    # --- jobs --------------------------------------------------------------

    def get_job(self, caller: Caller, job_id: str) -> Job:
        return self._jobs.get(job_id, caller.scope)

    def cancel_job(self, caller: Caller, job_id: str) -> None:
        self._jobs.cancel(self.get_job(caller, job_id))

    def cancel_all_jobs(self) -> int:
        """Stop every running or queued download (shutdown)."""
        return self._jobs.cancel_all()

    async def wait(self, job: Job) -> dict:
        return await self._jobs.wait(job)

    def job_status(self, caller: Caller, job_id: str) -> JobStatus:
        job = self.get_job(caller, job_id)
        last = job.events[-1] if job.events else {"type": "queued"}
        status = JobStatus(job_id=job.id, state=_STATE_BY_EVENT.get(last["type"], "queued"))
        progress = next((e for e in reversed(job.events) if e["type"] == "progress"), None)
        if progress:
            status.percent, status.speed, status.eta = progress.get("percent"), progress.get("speed"), progress.get("eta")
        if last["type"] == "done":
            status.percent = 100.0
            try:
                status.file = self.file_info(self._store.get(last["file_id"], None))  # fresh signed link
            except DownloaderError as error:
                if error.code != ErrorCode.FILE_NOT_FOUND:
                    raise
                status.file = None  # deleted or expired since; the job itself still finished
        elif last["type"] == "error":
            status.error = ErrorInfo(code=last["code"], message=last["message"])
        return status

    # --- files -------------------------------------------------------------

    def file_info(self, stored: StoredFile) -> FileInfo:
        exp, sig = self._signer.sign(stored.file_id)
        url = f"{self._public_base_url}/api/files/{stored.file_id}/download?exp={exp}&sig={sig}"
        return FileInfo.of(stored, url)

    def list_files(self, caller: Caller) -> list[StoredFile]:
        return self._store.list(caller.session)

    def get_file(self, caller: Caller, file_id: str) -> StoredFile:
        return self._store.get(file_id, caller.scope)

    def file_path(self, file: StoredFile) -> Path:
        return self._store.path(file)

    async def delete_file(self, caller: Caller, file_id: str) -> None:
        """Callers delete only their own files, even privileged ones."""
        await self._store.delete(file_id, caller.session)

    def file_for_download(self, file_id: str, exp: int, sig: str) -> StoredFile:
        if not self._signer.verify(file_id, exp, sig):
            raise DownloaderError(ErrorCode.FILE_NOT_FOUND, "This download link is invalid or has expired.")
        return self._store.get(file_id, None)

    async def sweep(self) -> int:
        """Delete expired files and forget old finished jobs."""
        self._jobs.prune(older_than=time.time() - self._file_ttl)
        return await self._store.sweep()


def build_service(settings: Settings, *, extractor: Extractor | None = None, policy: UrlPolicy | None = None) -> DownloadService:
    """Wire the real collaborators; tests pass a fake extractor and policy."""
    if extractor is None:
        from src.extractor.ytdlp import YtDlpExtractor

        extractor = YtDlpExtractor()
    limits = settings.limits
    return DownloadService(
        store=FileStore(
            settings.store_dir,
            ttl_seconds=settings.file_ttl_seconds,
            max_file_bytes=limits.max_file_bytes,
            max_session_bytes=limits.max_session_bytes,
        ),
        extractor=extractor,
        policy=policy or UrlPolicy(),
        jobs=JobQueue(limits.max_concurrent_downloads, limits.max_queued_downloads, limits.job_timeout_seconds),
        signer=LinkSigner(settings.signing_key, settings.download_link_seconds),
        limits=limits,
        public_base_url=settings.public_base_url,
        file_ttl_seconds=settings.file_ttl_seconds,
    )
