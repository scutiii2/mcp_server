"""The quality choices offered to users. Kept in code: they map straight to yt-dlp format selectors."""

from __future__ import annotations

from dataclasses import dataclass

from src.errors import DownloaderError, ErrorCode


@dataclass(frozen=True)
class Preset:
    id: str
    label: str
    kind: str  # "video" or "audio"
    height: int | None = None  # video: cap on frame height (None = best available)
    audio_kbps: int = 192  # audio: target bitrate of the converted file
    codec: str | None = None  # audio: "mp3" or "m4a"


PRESETS: dict[str, Preset] = {
    p.id: p
    for p in (
        Preset("best", "Best quality", "video"),
        Preset("1080p", "1080p", "video", height=1080),
        Preset("720p", "720p", "video", height=720),
        Preset("480p", "480p", "video", height=480),
        Preset("audio-mp3", "Audio (MP3)", "audio", codec="mp3"),
        Preset("audio-m4a", "Audio (M4A)", "audio", codec="m4a"),
    )
}


def get_preset(preset_id: str) -> Preset:
    preset = PRESETS.get(preset_id)
    if preset is None:
        raise DownloaderError(ErrorCode.INVALID_REQUEST, f"Unknown quality '{preset_id}'. Choose one of: {', '.join(PRESETS)}.")
    return preset
