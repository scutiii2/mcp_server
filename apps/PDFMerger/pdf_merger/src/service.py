"""MergeService: the one facade the REST routers and MCP tools call.

It composes the store, converters, planner, assembler, job queue and link
signer. Routers and tools hold no logic of their own.
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import AsyncIterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from src.config import Limits, Settings
from src.converters.base import ImageOptions
from src.converters.registry import ConverterRegistry, default_registry
from src.engine.assembler import AssemblyPart, Assembler
from src.engine.planner import ExpandedPlan, expand_plan
from src.errors import ErrorCode, MergerError
from src.jobs.job_queue import Job, JobQueue, ProgressFn
from src.models import MergePlan, MergeResult, OutputOptions
from src.store.file_store import FileStore, StoredFile
from src.store.names import ensure_pdf_suffix, file_stem, safe_filename
from src.store.signing import LinkSigner
from src.store.sniff import SNIFF_BYTES, sniff_mime


@dataclass(frozen=True)
class Caller:
    """Who is asking. ``privileged`` callers (internal token) may open any file by ID."""

    session: str
    privileged: bool = False

    @property
    def scope(self) -> str | None:
        return None if self.privileged else self.session


def _raise_if_cancelled(cancel: threading.Event) -> None:
    if cancel.is_set():
        raise MergerError(ErrorCode.MERGE_TIMEOUT, "The merge took too long and was stopped. Try fewer pages.")


def _read_head(path: Path) -> bytes:
    with path.open("rb") as handle:
        return handle.read(SNIFF_BYTES)


class MergeService:
    """Facade over files, merging, jobs and signed download links."""

    def __init__(
        self,
        *,
        store: FileStore,
        registry: ConverterRegistry,
        assembler: Assembler,
        jobs: JobQueue,
        signer: LinkSigner,
        limits: Limits,
        public_base_url: str,
        file_ttl_seconds: int,
        mcp_wait_seconds: float = 100.0,
    ) -> None:
        self._store = store
        self._registry = registry
        self._assembler = assembler
        self._jobs = jobs
        self._signer = signer
        self._limits = limits
        self._public_base_url = public_base_url.rstrip("/")
        self._file_ttl = file_ttl_seconds
        self._mcp_wait_seconds = mcp_wait_seconds

    @property
    def store(self) -> FileStore:
        return self._store

    # --- files -------------------------------------------------------------

    async def upload(self, caller: Caller, name: str | None, chunks: AsyncIterable[bytes]) -> StoredFile:
        """Stream to disk, sniff the real type, validate, then commit."""
        pending = await self._store.write_stream(caller.session, chunks)
        try:
            mime = sniff_mime(await asyncio.to_thread(_read_head, pending.path))
            converter = self._registry.for_mime(mime)
            pages = await converter.inspect(pending.path)
        except BaseException:
            self._store.discard(pending)
            raise
        return await self._store.commit(
            pending, name=safe_filename(name, "upload"), mime=mime or "", kind=converter.kind, pages=pages
        )

    def list_files(self, caller: Caller) -> list[StoredFile]:
        return self._store.list(caller.session)

    def get_file(self, caller: Caller, file_id: str) -> StoredFile:
        return self._store.get(file_id, caller.scope)

    def file_path(self, file: StoredFile) -> Path:
        return self._store.path(file)

    async def delete_file(self, caller: Caller, file_id: str) -> None:
        # Token callers may read any file by ID but only delete their own session's files.
        await self._store.delete(file_id, caller.session)

    def inspect(self, caller: Caller, file_ids: Sequence[str]) -> tuple[list[StoredFile], list[tuple[str, MergerError]]]:
        """Look up each ID; one bad ID never aborts the rest."""
        files: list[StoredFile] = []
        failed: list[tuple[str, MergerError]] = []
        for file_id in file_ids:
            try:
                files.append(self._store.get(file_id, caller.scope))
            except MergerError as error:
                failed.append((file_id, error))
        return files, failed

    # --- links -------------------------------------------------------------

    def download_url(self, file: StoredFile) -> str:
        exp, sig = self._signer.sign(file.file_id)
        return f"{self._public_base_url}/api/files/{file.file_id}/download?exp={exp}&sig={sig}"

    def file_for_download(self, file_id: str, exp: int, sig: str) -> StoredFile:
        if not self._signer.verify(file_id, exp, sig):
            raise MergerError(ErrorCode.FILE_NOT_FOUND, "This download link is invalid or has expired.")
        return self._store.get(file_id, None)

    # --- merging -----------------------------------------------------------

    def start_merge(self, caller: Caller, plan: MergePlan) -> Job:
        """Validate now (errors raise immediately), then queue the work."""
        expanded = expand_plan(plan, lambda file_id: self._store.get(file_id, caller.scope), self._limits)
        return self._jobs.submit(
            caller.session,
            expanded.total_pages,
            lambda progress, cancel: self._run_merge(caller.session, expanded, plan.output, progress, cancel),
        )

    async def merge_and_wait(self, caller: Caller, plan: MergePlan) -> MergeResult:
        job = self.start_merge(caller, plan)
        try:
            # wait_for cancels (and awaits) the inner wait on expiry, so nothing dangles
            final = await asyncio.wait_for(self._jobs.wait(job), self._mcp_wait_seconds)
        except asyncio.TimeoutError:
            self._jobs.cancel(job)
            raise MergerError(
                ErrorCode.MERGE_TIMEOUT,
                f"The merge took longer than {self._mcp_wait_seconds:g} seconds and was stopped. Try fewer pages.",
            ) from None
        if final.get("type") != "done":
            raise MergerError(ErrorCode(final.get("code", "internal_error")), final.get("message", "The merge failed."))
        return MergeResult.model_validate({k: v for k, v in final.items() if k != "type"})

    def get_job(self, caller: Caller, job_id: str) -> Job:
        return self._jobs.get(job_id, caller.scope)

    async def _run_merge(
        self, session: str, expanded: ExpandedPlan, output: OutputOptions, progress: ProgressFn, cancel: threading.Event
    ) -> dict:
        work_dir = await self._store.make_work_dir()
        try:
            parts: list[AssemblyPart] = []
            for segment in expanded.segments:
                _raise_if_cancelled(cancel)
                converter = self._registry.for_mime(segment.file.mime)
                pdf_path = await converter.to_pdf(
                    self._store.path(segment.file), work_dir, segment.image_options or ImageOptions()
                )
                parts.append(
                    AssemblyPart(
                        pdf_path=pdf_path,
                        pages=segment.pages,
                        rotate=segment.rotate,
                        bookmark=file_stem(segment.file.name),
                        group_key=segment.file.file_id,
                    )
                )
            pending = self._store.new_pending(session)
            try:
                pages = await self._assembler.assemble(
                    parts, pending.path, title=output.title, author=output.author, bookmarks=output.bookmarks, on_page=progress, cancel=cancel
                )
                stored = await self._store.commit(
                    pending,
                    name=ensure_pdf_suffix(safe_filename(output.filename, "merged.pdf")),
                    mime="application/pdf",
                    kind="pdf",
                    pages=pages,
                )
            except BaseException:
                self._store.discard(pending)
                raise
        finally:
            await self._store.remove_work_dir(work_dir)
        return MergeResult(
            file_id=stored.file_id,
            name=stored.name,
            pages=stored.pages,
            size=stored.size,
            expires_at=stored.expires_at,
            download_url=self.download_url(stored),
        ).model_dump()

    # --- housekeeping ------------------------------------------------------

    async def sweep(self) -> int:
        """Delete expired files and forget old jobs."""
        removed = await self._store.sweep()
        self._jobs.prune(older_than=time.time() - self._file_ttl)
        return removed


def build_service(settings: Settings) -> MergeService:
    """Wire a MergeService from settings."""
    limits = settings.limits
    return MergeService(
        store=FileStore(
            settings.store_dir,
            ttl_seconds=settings.file_ttl_seconds,
            max_file_bytes=limits.max_file_bytes,
            max_session_bytes=limits.max_session_bytes,
        ),
        registry=default_registry(limits.max_image_pixels),
        assembler=Assembler(),
        jobs=JobQueue(limits.max_concurrent_merges, limits.job_timeout_seconds),
        signer=LinkSigner(settings.signing_key, settings.download_link_seconds),
        limits=limits,
        public_base_url=settings.public_base_url,
        file_ttl_seconds=settings.file_ttl_seconds,
        mcp_wait_seconds=settings.mcp_wait_seconds,
    )
