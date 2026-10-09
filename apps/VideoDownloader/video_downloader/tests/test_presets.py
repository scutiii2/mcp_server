import pytest

from src.errors import DownloaderError, ErrorCode
from src.extractor.presets import PRESETS, get_preset


def test_preset_ids_and_order():
    assert list(PRESETS) == ["best", "1080p", "720p", "480p", "audio-mp3", "audio-m4a"]


def test_video_and_audio_presets():
    assert get_preset("720p").kind == "video" and get_preset("720p").height == 720
    assert get_preset("best").height is None
    assert get_preset("audio-mp3").kind == "audio" and get_preset("audio-mp3").codec == "mp3"
    assert get_preset("audio-m4a").codec == "m4a"


def test_unknown_preset_is_invalid_request():
    with pytest.raises(DownloaderError) as error:
        get_preset("8k")
    assert error.value.code == ErrorCode.INVALID_REQUEST
