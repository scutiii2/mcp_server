"""Shared fixtures. Later tasks add fixtures to this file."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.config import Settings

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


from collections.abc import Sequence

import pikepdf
from PIL import Image


def make_pdf(path: Path, widths: Sequence[int], height: int = 200, rotate: int = 0) -> Path:
    """A PDF whose page i is widths[i] points wide, so tests can check page order by width."""
    pdf = pikepdf.new()
    for width in widths:
        pdf.add_blank_page(page_size=(width, height))
        if rotate:
            pdf.pages[-1].obj.Rotate = rotate
    pdf.save(path)
    return path


def page_widths(path: Path) -> list[int]:
    with pikepdf.open(path) as pdf:
        return [round(float(page.mediabox[2])) for page in pdf.pages]


def make_image(
    path: Path,
    size: tuple[int, int] = (40, 30),
    mode: str = "RGB",
    fmt: str = "JPEG",
    exif_orientation: int | None = None,
) -> Path:
    color = (200, 10, 10, 128) if mode == "RGBA" else (200, 10, 10)
    image = Image.new(mode, size, color)
    options = {}
    if exif_orientation is not None:
        exif = Image.Exif()
        exif[0x0112] = exif_orientation
        options["exif"] = exif
    image.save(path, format=fmt, **options)
    return path


from collections.abc import AsyncIterator


async def chunks(data: bytes, size: int = 65536) -> AsyncIterator[bytes]:
    for start in range(0, len(data), size):
        yield data[start : start + size]


@pytest.fixture
def service(settings):
    from src.service import build_service

    return build_service(settings)
