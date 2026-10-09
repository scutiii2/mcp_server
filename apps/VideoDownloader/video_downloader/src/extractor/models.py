"""Plain data the extractor returns. Independent of yt-dlp's dict shapes."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class FormatInfo:
    format_id: str
    height: int | None
    tbr: float | None  # total bitrate, kbit/s
    filesize: int | None  # exact or approximate bytes
    has_video: bool
    has_audio: bool


# yt-dlp live_status values that mean "not a finished recording". Such streams are fetched by
# ffmpeg (outside the socket guard and the byte cap) and never end, so they are refused.
LIVE_STATUSES = frozenset({"is_live", "is_upcoming", "post_live"})


@dataclass(frozen=True)
class MediaInfo:
    title: str
    duration: float | None
    thumbnail: str | None
    uploader: str | None
    webpage_url: str | None
    formats: list[FormatInfo] = field(default_factory=list)
    live_status: str | None = None  # yt-dlp's live_status: is_live, is_upcoming, was_live, not_live, post_live

    @property
    def is_live(self) -> bool:
        return self.live_status in LIVE_STATUSES


@dataclass(frozen=True)
class DownloadProgress:
    stage: str  # "downloading" or "processing"
    percent: float | None
    speed: float | None  # bytes per second
    eta: float | None  # seconds


@dataclass(frozen=True)
class DownloadedFile:
    path: Path
