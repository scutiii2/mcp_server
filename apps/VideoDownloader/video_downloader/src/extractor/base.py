"""What the service needs from an extractor. yt-dlp is one implementation; tests use a fake."""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from src.extractor.models import DownloadedFile, DownloadProgress, MediaInfo
from src.extractor.presets import Preset


class Extractor(Protocol):
    def probe(self, url: str) -> MediaInfo:
        """Metadata only, no download. Blocking: call through asyncio.to_thread."""

    def download(
        self,
        url: str,
        preset: Preset,
        work_dir: Path,
        *,
        max_bytes: int,
        max_duration_seconds: float | None,
        on_progress: Callable[[DownloadProgress], None],
        cancel: threading.Event,
    ) -> DownloadedFile:
        """Download into ``work_dir`` and return the finished file. Blocking: call through asyncio.to_thread.

        The download extracts the page again, so live streams and media longer than
        ``max_duration_seconds`` (None = no limit) are refused on that extraction too.
        Raises DownloaderError (cancelled, too_large, too_long, live_stream, ...). Stops soon after ``cancel`` is set.
        """
