"""yt-dlp behind the Extractor protocol.

Every network call runs inside ``guard.active()`` so redirects and DNS answers
to private addresses are refused. yt-dlp's exceptions are mapped to stable
error codes; their raw text goes to the log only.

External downloaders (ffmpeg, rtmpdump, aria2c, curl, ...) open their own
sockets, which the guard can't see, and report no byte progress, so the byte
cap and cancel would not apply either. yt-dlp uses ffmpeg to fetch live
streams and HLS manifests its native downloader can't handle. Live streams are
refused up front (``live_stream``); anything else that would reach an external
downloader fails closed (``blocked_host``). Merging and audio conversion run
ffmpeg on local files as post-processors and are unaffected.
"""

from __future__ import annotations

import functools
import logging
import re
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

from yt_dlp import YoutubeDL
from yt_dlp.downloader.external import ExternalFD
from yt_dlp.downloader.rtmp import RtmpFD
from yt_dlp.utils import DownloadCancelled

from src.errors import LIVE_STREAM_MESSAGE, DownloaderError, ErrorCode
from src.extractor.models import LIVE_STATUSES, DownloadedFile, DownloadProgress, FormatInfo, MediaInfo
from src.extractor.presets import Preset
from src.policy.socket_guard import GUARD, SocketGuard

logger = logging.getLogger(__name__)

SOCKET_TIMEOUT_SECONDS = 20
PROGRESS_INTERVAL_SECONDS = 0.5  # at most ~2 progress events per second per job
_LOGIN = re.compile(r"sign in|log in|login|private video|members[- ]only|age[- ]restricted|cookies|confirm you.re not a bot", re.I)


class _CancelledByCaller(DownloadCancelled):
    """Raised from a progress hook when the job's cancel event is set."""


class _OverByteCap(DownloadCancelled):
    """Raised from a progress hook when the download passes the byte cap."""


# --- external downloaders fail closed ------------------------------------------

_external_refused = threading.local()


@contextmanager
def refuse_external_downloaders() -> Iterator[None]:
    """While this thread is inside the block, any external downloader raises blocked_host."""
    depth = getattr(_external_refused, "depth", 0)
    _external_refused.depth = depth + 1
    try:
        yield
    finally:
        _external_refused.depth = depth


def _refusing(original: Callable) -> Callable:
    @functools.wraps(original)
    def real_download(self, filename, info_dict):
        if getattr(_external_refused, "depth", 0) > 0:
            logger.warning("Refused %s: external downloaders bypass the socket guard", type(self).__name__)
            raise DownloaderError(ErrorCode.BLOCKED_HOST, "This stream would have to be fetched outside the address checks, so it can't be downloaded.")
        return original(self, filename, info_dict)

    real_download._vd_refusing = True  # type: ignore[attr-defined]
    return real_download


def _install_external_refusal() -> None:
    """Wrap real_download of every downloader that runs its own network client (idempotent).

    ExternalFD covers FFmpegFD and its subclasses plus aria2c/curl/wget/httpie; RtmpFD runs rtmpdump.
    Threads outside ``refuse_external_downloaders()`` are unaffected.
    """
    for cls in (ExternalFD, RtmpFD):
        current = cls.__dict__["real_download"]
        if not getattr(current, "_vd_refusing", False):
            cls.real_download = _refusing(current)


_install_external_refusal()


def _match_filter(max_duration_seconds: float | None) -> Callable:
    """yt-dlp match_filter: refuse live streams and over-long media on the download's own extraction.

    Raising (instead of returning a skip reason) aborts extract_info with a clear error; a skip
    would return an info dict with no file and surface as extractor_failed.
    """

    def check(info: dict, incomplete: bool = False) -> None:
        if info.get("is_live") or info.get("live_status") in LIVE_STATUSES:
            raise DownloaderError(ErrorCode.LIVE_STREAM, LIVE_STREAM_MESSAGE)
        duration = info.get("duration")
        if max_duration_seconds is not None and duration and float(duration) > max_duration_seconds:
            raise DownloaderError(
                ErrorCode.TOO_LONG, f"Videos longer than {int(max_duration_seconds // 60)} minutes are not allowed."
            )
        return None

    return check


def media_info_from_dict(raw: dict) -> MediaInfo:
    """Convert yt-dlp's info dict into MediaInfo. Formats with neither audio nor video (storyboards) are dropped."""
    formats: list[FormatInfo] = []
    for fmt in raw.get("formats") or []:
        has_video = (fmt.get("vcodec") or "none") != "none"
        has_audio = (fmt.get("acodec") or "none") != "none"
        if not has_video and not has_audio:
            continue
        formats.append(
            FormatInfo(
                format_id=str(fmt.get("format_id", "")),
                height=fmt.get("height") or None,
                tbr=float(fmt["tbr"]) if fmt.get("tbr") else None,
                filesize=int(fmt.get("filesize") or fmt.get("filesize_approx") or 0) or None,
                has_video=has_video,
                has_audio=has_audio,
            )
        )
    duration = raw.get("duration")
    live_status = raw.get("live_status") or None
    if raw.get("is_live") and live_status not in LIVE_STATUSES:
        live_status = "is_live"
    return MediaInfo(
        title=str(raw.get("title") or "video"),
        duration=float(duration) if duration else None,
        thumbnail=raw.get("thumbnail") or None,
        uploader=raw.get("uploader") or raw.get("channel") or None,
        webpage_url=raw.get("webpage_url") or None,
        formats=formats,
        live_status=live_status,
    )


def map_error(exc: Exception, *, blocked: bool) -> DownloaderError:
    """Turn any extractor failure into a DownloaderError. Raw text is logged, never returned."""
    if isinstance(exc, DownloaderError):
        return exc
    if blocked:
        return DownloaderError(ErrorCode.BLOCKED_HOST, "That address is not a public website, so it can't be downloaded.")
    text = str(exc)
    logger.warning("yt-dlp failed: %s", text)
    lowered = text.lower()
    if "unsupported url" in lowered:
        return DownloaderError(ErrorCode.UNSUPPORTED_SITE, "This site or link isn't supported.")
    if "drm" in lowered:
        return DownloaderError(ErrorCode.DRM_PROTECTED, "This video is copy-protected (DRM) and can't be downloaded.")
    if "ffmpeg" in lowered or "ffprobe" in lowered:
        return DownloaderError(ErrorCode.FFMPEG_MISSING, "FFmpeg is missing or failed, so the video can't be processed.")
    if _LOGIN.search(text):
        return DownloaderError(ErrorCode.LOGIN_REQUIRED, "This video needs a login (private, members-only or age-restricted).")
    return DownloaderError(ErrorCode.EXTRACTOR_FAILED, "The video couldn't be fetched. The site may have changed or the video is unavailable.")


def _final_path(info: dict, work_dir: Path) -> Path:
    """The finished file: yt-dlp reports it, else the single non-temporary file in work_dir.

    A reported path is used only if it resolves inside work_dir.
    """
    root = work_dir.resolve()
    for item in info.get("requested_downloads") or []:
        path = item.get("filepath")
        if not path:
            continue
        resolved = Path(path).resolve()
        if not resolved.is_relative_to(root):
            logger.warning("Ignoring reported download path outside the work directory")
        elif resolved.is_file():
            return resolved
    candidates = [p for p in work_dir.iterdir() if p.is_file() and p.suffix not in (".part", ".ytdl", ".temp")]
    if len(candidates) != 1:
        raise DownloaderError(ErrorCode.EXTRACTOR_FAILED, "The download finished but the file could not be found.")
    return candidates[0]


class YtDlpExtractor:
    def __init__(
        self,
        guard: SocketGuard = GUARD,
        ffmpeg_location: str | None = None,
        *,
        progress_interval: float = PROGRESS_INTERVAL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._guard = guard
        self._ffmpeg_location = ffmpeg_location
        self._progress_interval = progress_interval
        self._clock = clock
        guard.install()

    def _base_options(self) -> dict:
        options: dict = {
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "playlist_items": "1",
            "socket_timeout": SOCKET_TIMEOUT_SECONDS,
            "retries": 3,
            "cachedir": False,
            "proxy": "",  # direct connection, ignoring *_PROXY env vars, so the guard sees the real targets
            "hls_prefer_native": True,
            "concurrent_fragment_downloads": 1,  # one thread, so the thread-local guard covers every request
        }
        if self._ffmpeg_location:
            options["ffmpeg_location"] = self._ffmpeg_location
        return options

    @contextmanager
    def _guarded(self) -> Iterator[None]:
        with self._guard.active(), refuse_external_downloaders():
            yield

    def probe(self, url: str) -> MediaInfo:
        options = {**self._base_options(), "skip_download": True}
        with self._guarded():
            try:
                with YoutubeDL(options) as ydl:
                    raw = ydl.extract_info(url, download=False)
            except Exception as exc:
                raise map_error(exc, blocked=self._guard.blocked) from exc
        if not raw:
            raise DownloaderError(ErrorCode.EXTRACTOR_FAILED, "The video couldn't be fetched.")
        if raw.get("_type") in ("playlist", "multi_video"):
            raise DownloaderError(ErrorCode.INVALID_URL, "That link is a playlist. Paste the link of a single video.")
        return media_info_from_dict(raw)

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
        finished_bytes = 0  # bytes of streams already completed (video, then audio, for merged formats)
        last_emit: float | None = None

        def hook(status: dict) -> None:
            nonlocal finished_bytes, last_emit
            if cancel.is_set():
                raise _CancelledByCaller()
            if status.get("status") == "downloading":
                done = status.get("downloaded_bytes") or 0
                exact_total = status.get("total_bytes")
                if finished_bytes + done > max_bytes or (exact_total and finished_bytes + exact_total > max_bytes):
                    raise _OverByteCap()
                now = self._clock()
                if last_emit is not None and now - last_emit < self._progress_interval:
                    return  # throttled; the caps above still ran
                last_emit = now
                total = exact_total or status.get("total_bytes_estimate")
                percent = round(done * 100 / total, 1) if total else None
                on_progress(DownloadProgress("downloading", percent, status.get("speed"), status.get("eta")))
            elif status.get("status") == "finished":
                finished_bytes += status.get("downloaded_bytes") or status.get("total_bytes") or 0
                on_progress(DownloadProgress("processing", 100.0, None, None))

        def postprocessor_hook(status: dict) -> None:
            # Called when each post-processor (merge, audio conversion) starts and finishes.
            # A running ffmpeg can't be interrupted from here, but the next step won't start.
            if cancel.is_set():
                raise _CancelledByCaller()

        options = {
            **self._base_options(),
            "paths": {"home": str(work_dir), "temp": str(work_dir)},
            "outtmpl": "%(id)s.%(ext)s",
            "restrictfilenames": True,
            "progress_hooks": [hook],
            "postprocessor_hooks": [postprocessor_hook],
            "match_filter": _match_filter(max_duration_seconds),
            "noprogress": True,
            # No "max_filesize": yt-dlp's HTTP downloader then quietly skips an oversized file
            # (returns False, no exception), which would surface as extractor_failed. The hook
            # above enforces the cap instead and raises a clear too_large.
            **_format_options(preset),
        }
        with self._guarded():
            try:
                with YoutubeDL(options) as ydl:
                    info = ydl.extract_info(url, download=True)
            except _CancelledByCaller:
                raise DownloaderError(ErrorCode.CANCELLED, "The download was cancelled.") from None
            except _OverByteCap:
                raise DownloaderError(
                    ErrorCode.TOO_LARGE, f"The file is larger than {max_bytes // (1024 * 1024)} MB, so the download was stopped."
                ) from None
            except Exception as exc:
                raise map_error(exc, blocked=self._guard.blocked) from exc
        if info and info.get("_type") in ("playlist", "multi_video"):
            raise DownloaderError(ErrorCode.INVALID_URL, "That link is a playlist. Paste the link of a single video.")
        if info and (info.get("is_live") or info.get("live_status") in LIVE_STATUSES):
            raise DownloaderError(ErrorCode.LIVE_STREAM, LIVE_STREAM_MESSAGE)  # backstop if the filter was bypassed
        return DownloadedFile(_final_path(info or {}, work_dir))


def _format_options(preset: Preset) -> dict:
    """yt-dlp format selector (and audio conversion) for one preset."""
    if preset.kind == "audio":
        return {
            "format": "bestaudio/best",
            "postprocessors": [
                {"key": "FFmpegExtractAudio", "preferredcodec": preset.codec, "preferredquality": str(preset.audio_kbps)}
            ],
        }
    if preset.height is None:
        selector = "bestvideo*+bestaudio/best"
    else:
        selector = f"bestvideo*[height<={preset.height}]+bestaudio/best[height<={preset.height}]"
    return {"format": selector, "merge_output_format": "mp4", "format_sort": ["res", "ext:mp4:m4a"]}
