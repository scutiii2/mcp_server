"""Shared fixtures. Later tasks add fixtures to this file."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from pathlib import Path

import pytest

from src.config import Settings
from src.errors import DownloaderError, ErrorCode
from src.extractor.models import DownloadedFile, DownloadProgress, FormatInfo, MediaInfo
from src.extractor.presets import Preset
from src.policy.url_policy import UrlPolicy

TEST_TOKEN = "test-token"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Settings that keep every file under tmp_path."""
    return Settings(
        store_dir=tmp_path / "store",
        log_dir=tmp_path / "logs",
        internal_api_token=TEST_TOKEN,
        signing_key=b"s" * 32,
    )


async def public_resolver(host: str) -> list[str]:
    return ["93.184.216.34"]


class FakeExtractor:
    """Stands in for yt-dlp: no network, configurable outcome."""

    def __init__(self) -> None:
        self.info = MediaInfo(
            title="Cat video",
            duration=60.0,
            thumbnail="https://img.example/t.jpg",
            uploader="Cats",
            webpage_url="https://example.com/v",
            formats=[
                FormatInfo("18", 360, 500.0, None, True, True),
                FormatInfo("22", 720, 1500.0, None, True, True),
                FormatInfo("140", None, 128.0, None, False, True),
            ],
        )
        self.content = b"video-bytes" * 100
        self.suffix = ".mp4"
        self.probe_error: DownloaderError | None = None
        self.download_error: DownloaderError | None = None
        self.hold: threading.Event | None = None  # download waits for this (or for cancel)
        self.calls: list[tuple[str, str]] = []
        self.max_durations: list[float | None] = []
        self.on_probe: Callable[[], None] | None = None  # runs after each probe (tests use it to cancel)

    def probe(self, url: str) -> MediaInfo:
        if self.probe_error:
            raise self.probe_error
        if self.on_probe is not None:
            self.on_probe()
        return self.info

    def download(
        self,
        url: str,
        preset: Preset,
        work_dir,
        *,
        max_bytes: int,
        max_duration_seconds: float | None,
        on_progress: Callable[[DownloadProgress], None],
        cancel: threading.Event,
    ) -> DownloadedFile:
        self.calls.append((url, preset.id))
        self.max_durations.append(max_duration_seconds)
        if self.download_error:
            raise self.download_error
        on_progress(DownloadProgress("downloading", 10.0, 1000.0, 5.0))
        if self.hold is not None:
            while not self.hold.is_set():
                if cancel.is_set():
                    raise DownloaderError(ErrorCode.CANCELLED, "The download was cancelled.")
                time.sleep(0.01)
        suffix = ".mp3" if preset.kind == "audio" else self.suffix
        path = work_dir / f"media{suffix}"
        path.write_bytes(self.content)
        on_progress(DownloadProgress("processing", 100.0, None, None))
        return DownloadedFile(path)


@pytest.fixture
def fake_extractor() -> FakeExtractor:
    return FakeExtractor()


@pytest.fixture
def service(settings, fake_extractor):
    from src.service import build_service

    return build_service(settings, extractor=fake_extractor, policy=UrlPolicy(public_resolver))
