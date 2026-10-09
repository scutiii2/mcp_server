"""Facts about the host the service depends on: FFmpeg and the yt-dlp version."""

from __future__ import annotations

import shutil

from src.errors import DownloaderError, ErrorCode


def find_ffmpeg() -> str | None:
    return shutil.which("ffmpeg")


def ytdlp_version() -> str:
    from yt_dlp.version import __version__

    return __version__


def require_ffmpeg() -> None:
    """Raise ffmpeg_missing unless both ffmpeg and ffprobe are on PATH (called at startup)."""
    if find_ffmpeg() is None or shutil.which("ffprobe") is None:
        raise DownloaderError(
            ErrorCode.FFMPEG_MISSING,
            "FFmpeg and ffprobe must both be on PATH. Install FFmpeg (it includes ffprobe), then start the service again.",
        )
