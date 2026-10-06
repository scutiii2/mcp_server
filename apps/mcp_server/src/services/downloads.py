"""Files a tool offers to its caller for download.

A tool hands the bytes to `registry.offer(...)` and puts the returned
`[[DOWNLOAD ...]]` marker in its result (`download_markers`). The chat page
turns the marker into a download card, which reaches this server's
`GET /download?path=<id>` (see `download_routes.py`) through ember_api.

Nothing here names a file on disk. The id is random and opaque, the bytes
are held in memory, and the entry is bound to the account that asked: any
other account, an expired id and an unknown id are indistinguishable (all
`get()` -> None), so ids cannot be probed. A restart drops every entry; the
person just runs the command again.

Plain threads call this (tools run in `@offload` worker threads, the route
on the event loop), so every change to the store takes the lock.
"""

from __future__ import annotations

import hmac
import re
import secrets
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass

TTL_SECONDS = 600
MAX_ENTRIES = 50
MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_TOTAL_BYTES = 50 * 1024 * 1024

_FILENAME_MAX = 100
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")
_LABEL = re.compile(r"[A-Za-z0-9 _-]{1,30}")


class DownloadRefused(ValueError):
    """The file cannot be offered; the message is safe to show to the caller."""


@dataclass(frozen=True)
class Download:
    id: str
    owner: str
    filename: str
    data: bytes
    expires_at: float

    @property
    def size(self) -> int:
        return len(self.data)


def safe_filename(name: str) -> str:
    """A name that can sit inside a marker's quotes and a Content-Disposition header."""
    cleaned = _UNSAFE.sub("_", name.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]).strip("._")
    return (cleaned or "download")[:_FILENAME_MAX]


class DownloadRegistry:
    def __init__(
        self,
        ttl_seconds: float = TTL_SECONDS,
        max_entries: int = MAX_ENTRIES,
        max_file_bytes: int = MAX_FILE_BYTES,
        max_total_bytes: int = MAX_TOTAL_BYTES,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ttl = ttl_seconds
        self._max_entries = max_entries
        self._max_file = max_file_bytes
        self._max_total = max_total_bytes
        self._clock = clock
        self._entries: OrderedDict[str, Download] = OrderedDict()
        self._total = 0
        self._lock = threading.Lock()

    def offer(self, owner: str, filename: str, data: bytes) -> Download:
        """Holds `data` for `owner` and returns the entry (its `id` goes in the marker)."""
        if not owner:
            raise DownloadRefused("The caller is not identified, so the file cannot be offered.")
        if len(data) > self._max_file:
            raise DownloadRefused(f"The file is larger than {self._max_file // (1024 * 1024)} MB.")
        entry = Download(
            id=secrets.token_urlsafe(16),
            owner=owner,
            filename=safe_filename(filename),
            data=data,
            expires_at=self._clock() + self._ttl,
        )
        with self._lock:
            self._drop_expired()
            while self._entries and (
                len(self._entries) >= self._max_entries or self._total + len(data) > self._max_total
            ):
                self._drop(next(iter(self._entries)))
            self._entries[entry.id] = entry
            self._total += len(data)
        return entry

    def get(self, download_id: str, owner: str) -> Download | None:
        """The entry, only for the account it was offered to and before it expires."""
        with self._lock:
            self._drop_expired()
            entry = self._entries.get(download_id)
        if entry is None:
            return None
        if not hmac.compare_digest(entry.owner.encode("utf-8"), owner.encode("utf-8")):
            return None
        return entry

    def __len__(self) -> int:
        with self._lock:
            self._drop_expired()
            return len(self._entries)

    def _drop_expired(self) -> None:
        now = self._clock()
        for key in [k for k, e in self._entries.items() if e.expires_at <= now]:
            self._drop(key)

    def _drop(self, key: str) -> None:
        self._total -= len(self._entries.pop(key).data)


def marker(download: Download, label: str = "DOWNLOAD") -> str:
    """The text a result carries so the chat shows a download card. The page
    accepts only a `/server/download?...` link (ember_web's utils/downloads.ts)."""
    if not _LABEL.fullmatch(label):
        raise ValueError(f"not a label: {label!r}")
    return (
        f'[[DOWNLOAD filename="{download.filename}" bytes="{download.size}" '
        f'url="/server/download?path={download.id}" label="{label}"]]'
    )


# The one store this server uses; tests swap it.
registry = DownloadRegistry()
