"""Session-scoped files on disk with an in-memory index.

Layout: <root>/<sha256(session)[:32]>/<file_id> plus a <file_id>.json
sidecar holding the StoredFile record, so the index can be rebuilt after a
restart. Session strings are hashed so "mcp:alice" or anything a caller
sends can never become a raw path. The user's file name is metadata only.

One instance per process. Index mutations happen on the event loop thread;
disk I/O goes through asyncio.to_thread so the loop never blocks.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import secrets
import shutil
import tempfile
import time
from collections.abc import AsyncIterable, Callable
from dataclasses import asdict, dataclass
from pathlib import Path

from src.config import MB
from src.errors import ErrorCode, MergerError

logger = logging.getLogger(__name__)

_WORK_DIR_NAME = "_work"


@dataclass(frozen=True)
class StoredFile:
    """One committed file. ``kind`` is "pdf" or "image"."""

    file_id: str
    session: str
    name: str
    mime: str
    kind: str
    pages: int
    size: int
    created_at: float
    expires_at: float


@dataclass(frozen=True)
class PendingFile:
    """Content being written; becomes a StoredFile on commit()."""

    file_id: str
    session: str
    path: Path


def new_file_id() -> str:
    return "f_" + secrets.token_hex(16)


class FileStore:
    def __init__(
        self,
        root: Path,
        *,
        ttl_seconds: int,
        max_file_bytes: int,
        max_session_bytes: int,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._root = root
        self._ttl = ttl_seconds
        self._max_file_bytes = max_file_bytes
        self._max_session_bytes = max_session_bytes
        self._clock = clock
        self._index: dict[str, StoredFile] = {}
        self._reserved: dict[str, int] = {}

    # --- paths -------------------------------------------------------------

    def _session_dir(self, session: str) -> Path:
        return self._root / hashlib.sha256(session.encode("utf-8")).hexdigest()[:32]

    def path(self, file: StoredFile) -> Path:
        return self._session_dir(file.session) / file.file_id

    def _meta_path(self, file: StoredFile) -> Path:
        return self._session_dir(file.session) / f"{file.file_id}.json"

    # --- startup -----------------------------------------------------------

    async def load_index(self) -> int:
        """Rebuild the index from sidecars. Returns the number of files loaded."""

        def scan() -> list[StoredFile]:
            found: list[StoredFile] = []
            for meta in self._root.glob("*/f_*.json"):
                try:
                    found.append(StoredFile(**json.loads(meta.read_text("utf-8"))))
                except (OSError, ValueError, TypeError):
                    logger.warning("Skipping unreadable sidecar %s", meta)
            return found

        for file in await asyncio.to_thread(scan):
            self._index[file.file_id] = file
        return len(self._index)

    # --- writing -----------------------------------------------------------

    def new_pending(self, session: str) -> PendingFile:
        directory = self._session_dir(session)
        directory.mkdir(parents=True, exist_ok=True)
        file_id = new_file_id()
        return PendingFile(file_id=file_id, session=session, path=directory / f"{file_id}.part")

    async def write_stream(self, session: str, chunks: AsyncIterable[bytes]) -> PendingFile:
        """Stream chunks to disk, stopping as soon as the per-file limit is passed."""
        pending = self.new_pending(session)
        size = 0
        handle = await asyncio.to_thread(open, pending.path, "wb")
        try:
            async for chunk in chunks:
                size += len(chunk)
                if size > self._max_file_bytes:
                    raise MergerError(
                        ErrorCode.FILE_TOO_LARGE,
                        f"This file is larger than {self._max_file_bytes // MB} MB. Split or compress it, then upload it again.",
                    )
                await asyncio.to_thread(handle.write, chunk)
        except BaseException:
            await asyncio.to_thread(handle.close)
            self.discard(pending)
            raise
        await asyncio.to_thread(handle.close)
        return pending

    def discard(self, pending: PendingFile) -> None:
        pending.path.unlink(missing_ok=True)

    async def commit(self, pending: PendingFile, *, name: str, mime: str, kind: str, pages: int) -> StoredFile:
        """Register written content. Enforces the session quota."""
        size = (await asyncio.to_thread(pending.path.stat)).st_size
        reserved = self._reserved.get(pending.session, 0)
        if self.session_usage(pending.session) + reserved + size > self._max_session_bytes:
            self.discard(pending)
            raise MergerError(
                ErrorCode.LIMIT_EXCEEDED,
                f"Your files would use more than {self._max_session_bytes // MB} MB. Delete some files or wait for them to expire.",
            )
        # Synchronously reserve space before any further awaits
        self._reserved[pending.session] = reserved + size
        try:
            now = self._clock()
            stored = StoredFile(
                file_id=pending.file_id,
                session=pending.session,
                name=name,
                mime=mime,
                kind=kind,
                pages=pages,
                size=size,
                created_at=now,
                expires_at=now + self._ttl,
            )

            def finish() -> None:
                os.replace(pending.path, self.path(stored))
                self._meta_path(stored).write_text(json.dumps(asdict(stored)), "utf-8")

            await asyncio.to_thread(finish)
            self._index[stored.file_id] = stored
            return stored
        finally:
            # Release the reservation after index insert (or on failure)
            reserved = self._reserved.get(pending.session, 0)
            new_reserved = reserved - size
            if new_reserved <= 0:
                self._reserved.pop(pending.session, None)
            else:
                self._reserved[pending.session] = new_reserved

    # --- reading -----------------------------------------------------------

    def get(self, file_id: str, session: str | None) -> StoredFile:
        """The file, if it exists, has not expired, and ``session`` may see it (None = any)."""
        file = self._index.get(file_id)
        if file is None or file.expires_at <= self._clock() or (session is not None and file.session != session):
            raise MergerError(ErrorCode.FILE_NOT_FOUND, f"File {file_id} wasn't found. It may have expired; upload it again.")
        return file

    def list(self, session: str) -> list[StoredFile]:
        now = self._clock()
        files = [f for f in self._index.values() if f.session == session and f.expires_at > now]
        return sorted(files, key=lambda f: f.created_at)

    def session_usage(self, session: str) -> int:
        return sum(f.size for f in self.list(session))

    # --- removal -----------------------------------------------------------

    async def _remove(self, file: StoredFile) -> bool:
        """Remove a file from disk and index. Returns True if successful, False if it failed."""
        def unlink() -> None:
            self.path(file).unlink(missing_ok=True)
            self._meta_path(file).unlink(missing_ok=True)

        try:
            await asyncio.to_thread(unlink)
            self._index.pop(file.file_id, None)
            return True
        except OSError:
            logger.warning("Could not remove file %s", file.file_id)
            return False

    async def delete(self, file_id: str, session: str | None) -> None:
        if not await self._remove(self.get(file_id, session)):
            raise MergerError(
                ErrorCode.INTERNAL_ERROR,
                "This file couldn't be deleted right now. Try again in a moment.",
            )

    async def sweep(self) -> int:
        """Delete every expired file. Returns how many were removed."""
        now = self._clock()
        expired = [f for f in self._index.values() if f.expires_at <= now]
        removed = 0
        for file in expired:
            if await self._remove(file):
                removed += 1
        return removed

    # --- scratch space -----------------------------------------------------

    async def make_work_dir(self) -> Path:
        """A fresh scratch directory for one merge (converted images)."""
        base = self._root / _WORK_DIR_NAME
        await asyncio.to_thread(base.mkdir, parents=True, exist_ok=True)
        return Path(await asyncio.to_thread(tempfile.mkdtemp, dir=base))

    async def remove_work_dir(self, path: Path) -> None:
        await asyncio.to_thread(shutil.rmtree, path, True)
