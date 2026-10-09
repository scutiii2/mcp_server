from __future__ import annotations

import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from src.errors import DownloaderError, ErrorCode
from src.extractor.models import DownloadProgress
from src.extractor.presets import get_preset
from src.extractor.ytdlp import YtDlpExtractor, map_error, media_info_from_dict
from src.policy.socket_guard import SocketGuard


# --- pure mapping ------------------------------------------------------------

RAW = {
    "title": "Cat",
    "duration": 61.5,
    "thumbnail": "https://img/t.jpg",
    "uploader": "Cats",
    "webpage_url": "https://example.com/v",
    "formats": [
        {"format_id": "18", "height": 360, "tbr": 500.2, "filesize": None, "filesize_approx": 4000000, "vcodec": "avc1", "acodec": "mp4a"},
        {"format_id": "140", "height": None, "tbr": 128, "filesize": 1000, "vcodec": "none", "acodec": "mp4a"},
        {"format_id": "sb0", "height": 90, "tbr": None, "vcodec": "none", "acodec": "none"},
    ],
}


def test_media_info_from_dict():
    info = media_info_from_dict(RAW)
    assert (info.title, info.duration, info.uploader) == ("Cat", 61.5, "Cats")
    video, audio = info.formats[0], info.formats[1]
    assert video.has_video and video.has_audio and video.filesize == 4000000 and video.height == 360
    assert audio.has_audio and not audio.has_video and audio.filesize == 1000
    assert len(info.formats) == 2  # the storyboard (no audio, no video) is dropped


def test_media_info_defaults_when_fields_missing():
    info = media_info_from_dict({})
    assert info.title == "video" and info.formats == [] and info.duration is None
    assert info.live_status is None and not info.is_live


@pytest.mark.parametrize(
    "raw, live",
    [
        ({"live_status": "is_live"}, True),
        ({"live_status": "is_upcoming"}, True),
        ({"live_status": "post_live"}, True),
        ({"is_live": True}, True),
        ({"live_status": "was_live"}, False),
        ({"live_status": "not_live", "is_live": False}, False),
    ],
)
def test_media_info_live_status(raw, live):
    assert media_info_from_dict(raw).is_live is live


@pytest.mark.parametrize(
    "message, expected",
    [
        ("ERROR: Unsupported URL: https://x.example", ErrorCode.UNSUPPORTED_SITE),
        ("ERROR: [youtube] abc: Sign in to confirm you're not a bot", ErrorCode.LOGIN_REQUIRED),
        ("ERROR: Private video. Sign in if you've been granted access", ErrorCode.LOGIN_REQUIRED),
        ("ERROR: This video is DRM protected", ErrorCode.DRM_PROTECTED),
        ("ERROR: ffmpeg not found. Please install", ErrorCode.FFMPEG_MISSING),
        ("ERROR: something odd", ErrorCode.EXTRACTOR_FAILED),
    ],
)
def test_map_error(message, expected):
    assert map_error(RuntimeError(message), blocked=False).code == expected


def test_map_error_blocked_wins():
    assert map_error(RuntimeError("anything"), blocked=True).code == ErrorCode.BLOCKED_HOST


def test_map_error_passes_downloader_errors_through():
    original = DownloaderError(ErrorCode.TOO_LARGE, "big")
    assert map_error(original, blocked=False) is original


# --- against a local HTTP server (the generic extractor handles direct media links) ---


class MediaServer:
    """Serves one fake mp4 slowly enough to cancel mid-download."""

    def __init__(self, size: int, chunk: int = 8192, delay: float = 0.0) -> None:
        self.size = size

        class Handler(BaseHTTPRequestHandler):
            def _headers(self):
                self.send_response(200)
                self.send_header("Content-Type", "video/mp4")
                self.send_header("Content-Length", str(size))
                self.end_headers()

            def do_HEAD(self):
                self._headers()

            def do_GET(self):
                self._headers()
                sent = 0
                try:
                    while sent < size:
                        part = min(chunk, size - sent)
                        self.wfile.write(b"\0" * part)
                        sent += part
                        if delay:
                            time.sleep(delay)
                except ConnectionError:  # client hung up (BrokenPipe, Reset, and Windows' ConnectionAborted)
                    pass

            def log_message(self, *args):
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}/clip.mp4"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def open_guard():
    guard = SocketGuard(allow=lambda ip, port: True)  # loopback is fine for these tests
    yield guard
    guard.uninstall()


@pytest.fixture
def extractor(open_guard):
    return YtDlpExtractor(guard=open_guard)


def test_probe_local_media_link(extractor):
    server = MediaServer(2000)
    try:
        info = extractor.probe(server.url)
    finally:
        server.close()
    assert info.title  # generic extractor derives a title from the file name


def test_download_returns_file_and_reports_progress(extractor, tmp_path: Path):
    server = MediaServer(200_000, chunk=20_000)
    seen: list[DownloadProgress] = []
    try:
        result = extractor.download(
            server.url, get_preset("best"), tmp_path, max_bytes=10_000_000, max_duration_seconds=None, on_progress=seen.append, cancel=threading.Event()
        )
    finally:
        server.close()
    assert result.path.exists() and result.path.stat().st_size == 200_000
    assert any(p.stage == "downloading" for p in seen)


def test_download_stops_when_over_byte_cap(extractor, tmp_path: Path):
    server = MediaServer(400_000, chunk=20_000, delay=0.01)
    try:
        with pytest.raises(DownloaderError) as error:
            extractor.download(
                server.url, get_preset("best"), tmp_path, max_bytes=50_000, max_duration_seconds=None, on_progress=lambda p: None, cancel=threading.Event()
            )
    finally:
        server.close()
    assert error.value.code == ErrorCode.TOO_LARGE


def test_download_stops_when_cancelled(extractor, tmp_path: Path):
    server = MediaServer(2_000_000, chunk=20_000, delay=0.02)
    cancel = threading.Event()
    threading.Timer(0.2, cancel.set).start()
    try:
        with pytest.raises(DownloaderError) as error:
            extractor.download(server.url, get_preset("best"), tmp_path, max_bytes=10**9, max_duration_seconds=None, on_progress=lambda p: None, cancel=cancel)
    finally:
        server.close()
    assert error.value.code == ErrorCode.CANCELLED


def _patch_generic(monkeypatch, **extra):
    """Make the generic extractor report extra fields (is_live, duration) for the local test file."""
    from yt_dlp.extractor.generic import GenericIE

    original = GenericIE._real_extract

    def patched(self, url):
        result = original(self, url)
        result.update(extra)
        return result

    monkeypatch.setattr(GenericIE, "_real_extract", patched)


def _download(extractor, url, work_dir, **overrides):
    kwargs = {
        "max_bytes": 10_000_000,
        "max_duration_seconds": None,
        "on_progress": lambda p: None,
        "cancel": threading.Event(),
        **overrides,
    }
    return extractor.download(url, get_preset("best"), work_dir, **kwargs)


def test_download_refuses_a_live_stream(extractor, tmp_path: Path, monkeypatch):
    _patch_generic(monkeypatch, is_live=True, live_status="is_live")
    server = MediaServer(200_000, chunk=20_000)
    try:
        with pytest.raises(DownloaderError) as error:
            _download(extractor, server.url, tmp_path)
    finally:
        server.close()
    assert error.value.code == ErrorCode.LIVE_STREAM
    assert not any(tmp_path.iterdir())  # nothing was fetched


def test_download_rechecks_duration(extractor, tmp_path: Path, monkeypatch):
    _patch_generic(monkeypatch, duration=7200.0)
    server = MediaServer(200_000, chunk=20_000)
    try:
        with pytest.raises(DownloaderError) as error:
            _download(extractor, server.url, tmp_path, max_duration_seconds=3600)
    finally:
        server.close()
    assert error.value.code == ErrorCode.TOO_LONG


def test_external_downloaders_are_refused_inside_the_guard(extractor):
    from yt_dlp import YoutubeDL
    from yt_dlp.downloader.external import FFmpegFD

    from src.extractor import ytdlp

    with YoutubeDL({"quiet": True}) as ydl:
        fd = FFmpegFD(ydl, {})
        with ytdlp.refuse_external_downloaders():
            with pytest.raises(DownloaderError) as error:
                fd.real_download("out.mp4", {"url": "https://example.com/live.m3u8", "protocol": "m3u8"})
    assert error.value.code == ErrorCode.BLOCKED_HOST


def test_hls_delegated_to_ffmpeg_is_refused(extractor, tmp_path: Path):
    """An HLS stream the native downloader can't handle is handed to ffmpeg; that must fail closed."""
    playlist = (
        "#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-TARGETDURATION:2\n#EXT-X-MEDIA-SEQUENCE:0\n"
        '#EXT-X-KEY:METHOD=SAMPLE-AES,URI="https://example.com/key"\n'
        "#EXTINF:2.0,\nseg0.ts\n#EXT-X-ENDLIST\n"
    ).encode()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = playlist if self.path.endswith(".m3u8") else b"\0" * 1000
            self.send_response(200)
            self.send_header("Content-Type", "application/vnd.apple.mpegurl" if self.path.endswith(".m3u8") else "video/mp2t")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        with pytest.raises(DownloaderError) as error:
            _download(extractor, f"http://127.0.0.1:{httpd.server_address[1]}/stream.m3u8", tmp_path)
    finally:
        httpd.shutdown()
        httpd.server_close()
    assert error.value.code == ErrorCode.BLOCKED_HOST


def test_progress_events_are_throttled(open_guard, tmp_path: Path):
    extractor = YtDlpExtractor(guard=open_guard, progress_interval=0.5, clock=lambda: 100.0)  # time never moves
    server = MediaServer(200_000, chunk=10_000)
    seen: list[DownloadProgress] = []
    try:
        _download(extractor, server.url, tmp_path, on_progress=seen.append)
    finally:
        server.close()
    assert [p.stage for p in seen].count("downloading") == 1
    assert seen[-1].stage == "processing"


def test_cancel_during_postprocessing_stops(extractor, tmp_path: Path):
    import shutil

    if shutil.which("ffmpeg") is None:
        pytest.skip("needs ffmpeg for the audio post-processor")
    server = MediaServer(50_000, chunk=10_000)
    cancel = threading.Event()

    def on_progress(progress: DownloadProgress) -> None:
        if progress.stage == "processing":
            cancel.set()

    try:
        with pytest.raises(DownloaderError) as error:
            extractor.download(
                server.url,
                get_preset("audio-mp3"),
                tmp_path,
                max_bytes=10_000_000,
                max_duration_seconds=None,
                on_progress=on_progress,
                cancel=cancel,
            )
    finally:
        server.close()
    assert error.value.code == ErrorCode.CANCELLED


def test_final_path_ignores_a_reported_path_outside_work_dir(tmp_path: Path):
    from src.extractor.ytdlp import _final_path

    work = tmp_path / "work"
    work.mkdir()
    outside = tmp_path / "elsewhere.mp4"
    outside.write_bytes(b"x")
    inside = work / "clip.mp4"
    inside.write_bytes(b"y")
    assert _final_path({"requested_downloads": [{"filepath": str(outside)}]}, work) == inside


def test_base_options_force_a_direct_connection(extractor):
    assert extractor._base_options()["proxy"] == ""


def test_blocked_address_maps_to_blocked_host(tmp_path: Path):
    guard = SocketGuard(allow=lambda ip, port: False)
    try:
        extractor = YtDlpExtractor(guard=guard)
        server = MediaServer(2000)
        try:
            with pytest.raises(DownloaderError) as error:
                extractor.probe(server.url)
        finally:
            server.close()
    finally:
        guard.uninstall()
    assert error.value.code == ErrorCode.BLOCKED_HOST
