"""Which presets a video offers, how big each would be, and which the caps block."""

from __future__ import annotations

from src.config import MB, Limits
from src.errors import LIVE_STREAM_MESSAGE, ErrorCode
from src.extractor.models import FormatInfo, MediaInfo
from src.extractor.presets import PRESETS, Preset
from src.models import PresetOption

_KBIT_TO_BYTES_PER_SECOND = 125  # 1 kbit/s = 125 bytes/s


def available_presets(info: MediaInfo) -> list[Preset]:
    """Presets the site can serve. An unknown format list offers "best" plus audio."""
    has_video = any(f.has_video for f in info.formats) or not info.formats
    heights = [f.height for f in info.formats if f.has_video and f.height]
    offered: list[Preset] = []
    for preset in PRESETS.values():
        if preset.kind == "audio":
            offered.append(preset)
        elif not has_video:
            continue
        elif preset.height is None or (heights and max(heights) >= preset.height):
            offered.append(preset)
    return offered


def _format_bytes(fmt: FormatInfo, duration: float | None) -> int | None:
    if fmt.filesize:
        return int(fmt.filesize)
    if fmt.tbr and duration:
        return int(fmt.tbr * _KBIT_TO_BYTES_PER_SECOND * duration)
    return None


def estimate_size(info: MediaInfo, preset: Preset) -> int | None:
    """Expected size in bytes, or None when the site gives no usable numbers."""
    if preset.kind == "audio":
        return int(preset.audio_kbps * _KBIT_TO_BYTES_PER_SECOND * info.duration) if info.duration else None
    candidates = [f for f in info.formats if f.has_video and (preset.height is None or (f.height or 0) <= preset.height)]
    if not candidates:
        return None
    best = max(candidates, key=lambda f: (f.height or 0, f.tbr or 0))
    size = _format_bytes(best, info.duration)
    if size is None:
        return None
    if not best.has_audio:
        audio = [f for f in info.formats if f.has_audio and not f.has_video]
        if audio:
            best_audio = max(audio, key=lambda f: f.tbr or 0)
            size += _format_bytes(best_audio, info.duration) or 0
    return size


def build_options(info: MediaInfo, limits: Limits) -> list[PresetOption]:
    """One option per offered preset, with the caps applied."""
    too_long = info.duration is not None and info.duration > limits.max_duration_seconds
    options: list[PresetOption] = []
    for preset in available_presets(info):
        estimate = estimate_size(info, preset)
        blocked, code, reason = False, None, None
        if info.is_live:
            blocked, code, reason = True, str(ErrorCode.LIVE_STREAM), LIVE_STREAM_MESSAGE
        elif too_long:
            minutes = int(limits.max_duration_seconds // 60)
            blocked, code = True, str(ErrorCode.TOO_LONG)
            reason = f"Videos longer than {minutes} minutes are not allowed."
        elif estimate is not None and estimate > limits.max_file_bytes:
            blocked, code = True, str(ErrorCode.TOO_LARGE)
            reason = f"Would be about {estimate // MB} MB; the limit is {limits.max_file_bytes // MB} MB. Pick a lower quality."
        options.append(
            PresetOption(
                id=preset.id,
                label=preset.label,
                kind=preset.kind,
                estimated_bytes=estimate,
                blocked=blocked,
                code=code,
                reason=reason,
            )
        )
    return options
