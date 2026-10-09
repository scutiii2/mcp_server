"""Session-scoped files on disk with an in-memory index.

Layout: <root>/<sha256(session)[:32]>/<file_id> plus a <file_id>.json sidecar
holding the StoredFile record, so the index can be rebuilt after a restart.
Session strings are hashed so "mcp:alice" or anything a caller sends can never
become a raw path. The video title is metadata only.

Downloads happen in scratch directories under <root>/_work (same volume as the
store, so commit_file can move a finished file with an atomic rename).

One instance per process. Index mutations happen on the event loop thread; disk
I/O goes through asyncio.to_thread so the loop never blocks.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import secrets
import shutil
import tempfile
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

from src.config import MB
from src.errors import DownloaderError, ErrorCode

logger = logging.getLogger(__name__)

_WORK_DIR_NAME = "_work"
_DATA_NAME_RE = re.compile(r"f_[0-9a-f]{32}")


@dataclass(frozen=True)
class StoredFile:
    """One committed file. ``kind`` is "video" or "audio"."""

    file_id: str
    session: str
    name: str
    mime: str
    kind: str
    size: int
    duration: float | None
    created_at: float
    expires_at: float


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
        """Rebuild the index from sidecars and clean crash leftovers. Returns the number of files loaded."""

        def scan() -> list[StoredFile]:
            self._root.mkdir(parents=True, exist_ok=True)
            found: list[StoredFile] = []
            for meta in self._root.glob("*/f_*.json"):
                try:
                    file = StoredFile(**json.loads(meta.read_text("utf-8")))
                except (OSError, ValueError, TypeError):
                    logger.warning("Skipping unreadable sidecar %s", meta)
                    continue
                if not self.path(file).is_file():
                    logger.warning("Dropping sidecar %s: its data file is missing", meta)
                    meta.unlink(missing_ok=True)
                    continue
                found.append(file)
            self._clean_stale(found)
            return found

        for file in await asyncio.to_thread(scan):
            self._index[file.file_id] = file
        return len(self._index)

    def _clean_stale(self, found: list[StoredFile]) -> None:
        """Delete data files without a sidecar and every scratch directory (no job survives a restart)."""
        known = {file.file_id for file in found}
        for path in self._root.glob("*/f_*"):
            if path.name.endswith(".json") or path.parent.name == _WORK_DIR_NAME:
                continue
            if _DATA_NAME_RE.fullmatch(path.name) and path.name not in known:
                try:
                    path.unlink()
                except OSError:
                    logger.warning("Could not remove stale file %s", path)
        shutil.rmtree(self._root / _WORK_DIR_NAME, ignore_errors=True)

    # --- writing -----------------------------------------------------------

    async def make_work_dir(self) -> Path:
        """A fresh scratch directory for one download."""
        base = self._root / _WORK_DIR_NAME
        await asyncio.to_thread(base.mkdir, parents=True, exist_ok=True)
        return Path(await asyncio.to_thread(tempfile.mkdtemp, dir=base))

    async def remove_work_dir(self, path: Path) -> None:
        await asyncio.to_thread(shutil.rmtree, path, True)

    async def commit_file(
        self, session: str, source: Path, *, name: str, mime: str, kind: str, duration: float | None
    ) -> StoredFile:
        """Move a finished download into the store. Enforces the file cap and the session quota.

        On a refusal the source file is deleted, so nothing is left behind.
        """
        size = (await asyncio.to_thread(source.stat)).st_size
        if size > self._max_file_bytes:
            await asyncio.to_thread(source.unlink, True)
            raise DownloaderError(
                ErrorCode.TOO_LARGE, f"The file is larger than {self._max_file_bytes // MB} MB, so it was not kept."
            )
        reserved = self._reserved.get(session, 0)
        if self.session_usage(session) + reserved + size > self._max_session_bytes:
            await asyncio.to_thread(source.unlink, True)
            raise DownloaderError(
                ErrorCode.LIMIT_EXCEEDED,
                f"Your files would use more than {self._max_session_bytes // MB} MB. Delete some files or wait for them to expire.",
            )
        # Reserve space synchronously, before any further await.
        self._reserved[session] = reserved + size
        try:
            now = self._clock()
            stored = StoredFile(
                file_id=new_file_id(),
                session=session,
                name=name,
                mime=mime,
                kind=kind,
                size=size,
                duration=duration,
                created_at=now,
                expires_at=now + self._ttl,
            )

            def finish() -> None:
                self._session_dir(session).mkdir(parents=True, exist_ok=True)
                os.replace(source, self.path(stored))
                self._meta_path(stored).write_text(json.dumps(asdict(stored)), "utf-8")

            await asyncio.to_thread(finish)
            self._index[stored.file_id] = stored
            return stored
        finally:
            left = self._reserved.get(session, 0) - size
            if left <= 0:
                self._reserved.pop(session, None)
            else:
                self._reserved[session] = left

    # --- reading -----------------------------------------------------------

    def get(self, file_id: str, session: str | None) -> StoredFile:
        """The file, if it exists, has not expired, and ``session`` may see it (None = any)."""
        file = self._index.get(file_id)
        if file is None or file.expires_at <= self._clock() or (session is not None and file.session != session):
            raise DownloaderError(ErrorCode.FILE_NOT_FOUND, f"File {file_id} wasn't found. It may have expired; download it again.")
        return file

    def list(self, session: str) -> list[StoredFile]:
        now = self._clock()
        files = [f for f in self._index.values() if f.session == session and f.expires_at > now]
        return sorted(files, key=lambda f: f.created_at)

    def session_usage(self, session: str) -> int:
        return sum(f.size for f in self.list(session))

    # --- removal -----------------------------------------------------------

    async def _remove(self, file: StoredFile) -> bool:
        def unlink() -> None:
            self.path(file).unlink(missing_ok=True)
            self._meta_path(file).unlink(missing_ok=True)

        try:
            await asyncio.to_thread(unlink)
        except OSError:
            logger.warning("Could not remove file %s", file.file_id)
            return False
        self._index.pop(file.file_id, None)
        return True

    async def delete(self, file_id: str, session: str | None) -> None:
        if not await self._remove(self.get(file_id, session)):
            raise DownloaderError(ErrorCode.INTERNAL, "This file couldn't be deleted right now. Try again in a moment.")

    async def sweep(self) -> int:
        """Delete every expired file. Returns how many were removed."""
        now = self._clock()
        removed = 0
        for file in [f for f in self._index.values() if f.expires_at <= now]:
            if await self._remove(file):
                removed += 1
        return removed
