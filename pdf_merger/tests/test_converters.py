from __future__ import annotations

from pathlib import Path

import pikepdf
import pytest

from src.converters.base import ImageOptions
from src.converters.image import ImageConverter
from src.converters.pdf import PdfPassthrough
from src.converters.registry import default_registry
from src.errors import ErrorCode, MergerError
from tests.conftest import make_image, make_pdf

A4 = (595.28, 841.89)


def mediabox(path: Path) -> tuple[float, float]:
    with pikepdf.open(path) as pdf:
        box = pdf.pages[0].mediabox
        return float(box[2]) - float(box[0]), float(box[3]) - float(box[1])


def only_image(pdf: pikepdf.Pdf) -> pikepdf.Object:
    [(_, xobject)] = list(pdf.pages[0].get_images(recursive=False).items())
    return xobject


# --- registry --------------------------------------------------------------


@pytest.mark.parametrize(("mime", "kind"), [("application/pdf", "pdf"), ("image/png", "image"), ("image/heic", "image")])
def test_registry_picks_by_mime(mime, kind):
    assert default_registry(10**8).for_mime(mime).kind == kind


@pytest.mark.parametrize("mime", [None, "application/zip", "text/plain"])
def test_registry_rejects_unknown(mime):
    with pytest.raises(MergerError) as caught:
        default_registry(10**8).for_mime(mime)
    assert caught.value.code == ErrorCode.UNSUPPORTED_TYPE


# --- pdf -------------------------------------------------------------------


async def test_pdf_inspect_counts_pages_and_to_pdf_is_identity(tmp_path: Path):
    src = make_pdf(tmp_path / "a.pdf", [100, 101, 102])
    converter = PdfPassthrough()

    assert await converter.inspect(src) == 3
    assert await converter.to_pdf(src, tmp_path, ImageOptions()) == src


async def test_encrypted_pdf_is_rejected(tmp_path: Path):
    path = tmp_path / "locked.pdf"
    pdf = pikepdf.new()
    pdf.add_blank_page()
    pdf.save(path, encryption=pikepdf.Encryption(owner="o", user="u"))

    with pytest.raises(MergerError) as caught:
        await PdfPassthrough().inspect(path)
    assert caught.value.code == ErrorCode.ENCRYPTED_PDF


async def test_corrupt_pdf_is_rejected(tmp_path: Path):
    path = tmp_path / "bad.pdf"
    path.write_bytes(b"%PDF-1.7\nthis is not a pdf")

    with pytest.raises(MergerError) as caught:
        await PdfPassthrough().inspect(path)
    assert caught.value.code == ErrorCode.CORRUPT_FILE


# --- images ----------------------------------------------------------------


async def test_jpeg_bytes_are_embedded_unchanged(tmp_path: Path):
    src = make_image(tmp_path / "photo.jpg")
    out = await ImageConverter(10**8).to_pdf(src, tmp_path, ImageOptions())

    with pikepdf.open(out) as pdf:
        assert only_image(pdf).read_raw_bytes() == src.read_bytes()


async def test_a4_page_size(tmp_path: Path):
    src = make_image(tmp_path / "photo.jpg")
    out = await ImageConverter(10**8).to_pdf(src, tmp_path, ImageOptions(page_size="A4"))

    width, height = mediabox(out)
    assert width == pytest.approx(A4[0], abs=0.5) and height == pytest.approx(A4[1], abs=0.5)


async def test_match_page_size_uses_image_size(tmp_path: Path):
    src = make_image(tmp_path / "photo.png", size=(300, 150), fmt="PNG")
    out = await ImageConverter(10**8).to_pdf(src, tmp_path, ImageOptions(page_size="match"))

    width, height = mediabox(out)
    assert width / height == pytest.approx(2.0, rel=0.01)


async def test_exif_orientation_becomes_page_rotation(tmp_path: Path):
    src = make_image(tmp_path / "phone.jpg", exif_orientation=6)
    out = await ImageConverter(10**8).to_pdf(src, tmp_path, ImageOptions(page_size="match"))

    with pikepdf.open(out) as pdf:
        assert int(pdf.pages[0].obj.get("/Rotate", 0)) == 90


async def test_png_alpha_is_flattened(tmp_path: Path):
    src = make_image(tmp_path / "logo.png", mode="RGBA", fmt="PNG")
    out = await ImageConverter(10**8).to_pdf(src, tmp_path, ImageOptions())

    with pikepdf.open(out) as pdf:
        assert "/SMask" not in only_image(pdf)


@pytest.mark.parametrize("fmt", ["WEBP", "TIFF", "GIF"])
async def test_other_formats_convert(tmp_path: Path, fmt):
    src = make_image(tmp_path / f"img.{fmt.lower()}", fmt=fmt)
    out = await ImageConverter(10**8).to_pdf(src, tmp_path, ImageOptions())

    with pikepdf.open(out) as pdf:
        assert len(pdf.pages) == 1


async def test_heic_converts(tmp_path: Path):
    from pillow_heif import register_heif_opener

    register_heif_opener()
    src = make_image(tmp_path / "img.heic", fmt="HEIF")
    out = await ImageConverter(10**8).to_pdf(src, tmp_path, ImageOptions())

    with pikepdf.open(out) as pdf:
        assert len(pdf.pages) == 1


async def test_image_over_pixel_limit_is_rejected(tmp_path: Path):
    src = make_image(tmp_path / "big.jpg", size=(40, 30))

    with pytest.raises(MergerError) as caught:
        await ImageConverter(max_pixels=1000).inspect(src)
    assert caught.value.code == ErrorCode.LIMIT_EXCEEDED


async def test_unreadable_image_is_corrupt(tmp_path: Path):
    path = tmp_path / "broken.png"
    path.write_bytes(b"\x89PNG\r\n\x1a\nnot really")

    with pytest.raises(MergerError) as caught:
        await ImageConverter(10**8).inspect(path)
    assert caught.value.code == ErrorCode.CORRUPT_FILE
