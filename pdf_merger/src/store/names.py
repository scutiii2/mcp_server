"""User-supplied file names are metadata only. These helpers make them safe to store and to send back in headers."""

from __future__ import annotations

import re
from urllib.parse import quote

_UNSAFE = re.compile(r"[^\w.\- ()]+")
_MAX_LENGTH = 150


def safe_filename(name: str | None, default: str) -> str:
    """Last path component with unsafe characters collapsed to "_"; ``default`` if nothing is left."""
    base = (name or "").replace("\\", "/").rsplit("/", 1)[-1]
    base = _UNSAFE.sub("_", base).strip(" .")[:_MAX_LENGTH]
    return base or default


def ensure_pdf_suffix(name: str) -> str:
    return name if name.lower().endswith(".pdf") else f"{name}.pdf"


def file_stem(name: str) -> str:
    """Name without its last extension, used as a bookmark title."""
    stem, dot, _ = name.rpartition(".")
    return stem if dot and stem else name


def content_disposition(name: str, *, inline: bool = False) -> str:
    """RFC 6266 header with an ASCII fallback and the exact UTF-8 name."""
    ascii_name = name.encode("ascii", "ignore").decode("ascii").replace('"', "") or "file"
    kind = "inline" if inline else "attachment"
    return f"{kind}; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(name)}"
