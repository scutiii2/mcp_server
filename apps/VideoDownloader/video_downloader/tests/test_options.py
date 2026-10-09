from src.config import MB, Limits
from src.extractor.models import FormatInfo, MediaInfo
from src.extractor.options import available_presets, build_options, estimate_size
from src.extractor.presets import get_preset


def video(height, tbr=1000.0, filesize=None, audio=True, fid=None):
    return FormatInfo(fid or f"v{height}", height, tbr, filesize, True, audio)


def audio_only(tbr=128.0, filesize=None):
    return FormatInfo("a1", None, tbr, filesize, False, True)


def info(formats, duration=100.0):
    return MediaInfo("T", duration, None, None, None, formats)


def ids(presets):
    return [p.id for p in presets]


def test_presets_limited_by_max_height():
    got = available_presets(info([video(480), video(720), audio_only()]))
    assert ids(got) == ["best", "720p", "480p", "audio-mp3", "audio-m4a"]


def test_audio_only_site_offers_audio_presets_only():
    assert ids(available_presets(info([audio_only()]))) == ["audio-mp3", "audio-m4a"]


def test_unknown_formats_offer_best_and_audio():
    assert ids(available_presets(info([]))) == ["best", "audio-mp3", "audio-m4a"]


def test_estimate_uses_filesize_when_known():
    i = info([video(720, filesize=5_000_000, audio=False), audio_only(filesize=1_000_000)])
    assert estimate_size(i, get_preset("720p")) == 6_000_000


def test_estimate_falls_back_to_bitrate_times_duration():
    i = info([video(720, tbr=800.0)], duration=100.0)  # 800 kbit/s * 100 s = 10_000_000 bytes
    assert estimate_size(i, get_preset("720p")) == 10_000_000


def test_estimate_picks_highest_format_within_height():
    i = info([video(480, tbr=500.0), video(1080, tbr=4000.0)], duration=10.0)
    assert estimate_size(i, get_preset("480p")) == 625_000
    assert estimate_size(i, get_preset("best")) == 5_000_000


def test_estimate_unknown_is_none():
    assert estimate_size(info([video(720, tbr=None)], duration=None), get_preset("720p")) is None


def test_audio_estimate_uses_target_bitrate():
    assert estimate_size(info([audio_only()], duration=100.0), get_preset("audio-mp3")) == 192 * 125 * 100


def test_build_options_blocks_too_long():
    limits = Limits(max_duration_seconds=60)
    options = build_options(info([video(720), audio_only()], duration=120.0), limits)
    assert options and all(o.blocked and o.code == "too_long" for o in options)


def test_build_options_blocks_live_streams():
    live = MediaInfo("T", None, None, None, None, [video(720), audio_only()], live_status="is_live")
    options = build_options(live, Limits())
    assert options and all(o.blocked and o.code == "live_stream" for o in options)


def test_was_live_is_not_blocked():
    ended = MediaInfo("T", 100.0, None, None, None, [video(720), audio_only()], live_status="was_live")
    assert not any(o.blocked for o in build_options(ended, Limits()))


def test_build_options_blocks_too_large_per_preset():
    limits = Limits(max_file_bytes=2 * MB)
    i = info([video(480, tbr=100.0), video(1080, tbr=8000.0)], duration=100.0)
    by_id = {o.id: o for o in build_options(i, limits)}
    assert not by_id["480p"].blocked
    assert by_id["1080p"].blocked and by_id["1080p"].code == "too_large"
    assert by_id["best"].blocked
    assert by_id["480p"].estimated_bytes == 1_250_000
