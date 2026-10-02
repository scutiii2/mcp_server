"""Detect a file's real type from its first bytes. File extensions are never trusted."""

from __future__ import annotations

SNIFF_BYTES = 1024

_PREFIXES: tuple[tuple[bytes, str], ...] = (
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"II*\x00", "image/tiff"),
    (b"MM\x00*", "image/tiff"),
)
_HEIF_BRANDS = frozenset({b"heic", b"heix", b"heim", b"heis", b"hevc", b"hevx", b"mif1", b"msf1"})


def sniff_mime(head: bytes) -> str | None:
    """MIME type for the first SNIFF_BYTES of a file, or None if unsupported."""
    for prefix, mime in _PREFIXES:
        if head.startswith(prefix):
            return mime
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    if head[4:8] == b"ftyp" and head[8:12] in _HEIF_BRANDS:
        return "image/heic"
    # The PDF spec allows junk before the header; readers accept it within the first 1 KB.
    if b"%PDF-" in head[:SNIFF_BYTES]:
        return "application/pdf"
    return None
