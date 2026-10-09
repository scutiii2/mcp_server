import pytest

from src import system_info
from src.errors import DownloaderError, ErrorCode


def test_require_ffmpeg_raises_when_missing(monkeypatch):
    monkeypatch.setattr(system_info.shutil, "which", lambda name: None)
    with pytest.raises(DownloaderError) as error:
        system_info.require_ffmpeg()
    assert error.value.code == ErrorCode.FFMPEG_MISSING


def test_require_ffmpeg_raises_when_ffprobe_missing(monkeypatch):
    monkeypatch.setattr(system_info.shutil, "which", lambda name: "/usr/bin/ffmpeg" if name == "ffmpeg" else None)
    with pytest.raises(DownloaderError) as error:
        system_info.require_ffmpeg()
    assert error.value.code == ErrorCode.FFMPEG_MISSING
    assert "ffprobe" in error.value.message.lower()


def test_require_ffmpeg_ok_when_found(monkeypatch):
    monkeypatch.setattr(system_info.shutil, "which", lambda name: f"/usr/bin/{name}")
    system_info.require_ffmpeg()


def test_ytdlp_version_is_a_string():
    assert system_info.ytdlp_version()
