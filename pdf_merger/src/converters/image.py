"""Images become one-page PDFs through img2pdf.

JPEGs are embedded byte for byte (lossless); their EXIF orientation is
applied as the page's /Rotate, not by re-encoding. Every other format is
flattened to RGB (alpha onto white) and handed over as PNG, which img2pdf
also embeds without loss. Multi-frame GIF/TIFF use the first frame.
"""

from __future__ import annotations

import asyncio
import io
from pathlib import Path
from uuid import uuid4

import img2pdf
from PIL import Image, ImageOps, UnidentifiedImageError
from pillow_heif import register_heif_opener

from src.converters.base import FitMode, ImageOptions, PageSize
from src.errors import ErrorCode, MergerError

register_heif_opener()
# Our own pixel limit (with a clear message) replaces Pillow's DecompressionBombError.
Image.MAX_IMAGE_PIXELS = None

IMAGE_MIMES = frozenset({"image/jpeg", "image/png", "image/webp", "image/tiff", "image/gif", "image/heic"})

# img2pdf's exception classes share no common base, so list them all.
_IMG2PDF_ERRORS = (
    img2pdf.AlphaChannelError,
    img2pdf.ExifOrientationError,
    img2pdf.ImageOpenError,
    img2pdf.JpegColorspaceError,
    img2pdf.NegativeDimensionError,
    img2pdf.PdfTooLargeError,
    img2pdf.UnsupportedColorspaceError,
)
_PAGE_SIZES: dict[PageSize, tuple[float, float]] = {
    "A4": (img2pdf.mm_to_pt(210), img2pdf.mm_to_pt(297)),
    "Letter": (img2pdf.in_to_pt(8.5), img2pdf.in_to_pt(11)),
}
_FIT: dict[FitMode, img2pdf.FitMode] = {
    "fit": img2pdf.FitMode.into,
    "fill": img2pdf.FitMode.fill,
    "original": img2pdf.FitMode.shrink,
}


def _layout(opts: ImageOptions):
    if opts.page_size == "match":
        return img2pdf.default_layout_fun
    border = None
    if opts.margin_mm > 0:
        margin = img2pdf.mm_to_pt(opts.margin_mm)
        border = (margin, margin)
    return img2pdf.get_layout_fun(pagesize=_PAGE_SIZES[opts.page_size], border=border, fit=_FIT[opts.fit])


def _flatten(image: Image.Image) -> Image.Image:
    has_alpha = image.mode in ("RGBA", "LA") or "transparency" in image.info
    if has_alpha:
        rgba = image.convert("RGBA")
        background = Image.new("RGB", rgba.size, (255, 255, 255))
        background.paste(rgba, mask=rgba.getchannel("A"))
        return background
    return image if image.mode in ("RGB", "L") else image.convert("RGB")


def _image_bytes(path: Path) -> bytes:
    with Image.open(path) as image:
        if image.format == "JPEG" and image.mode in ("RGB", "L", "CMYK"):
            return path.read_bytes()
        image.seek(0)
        upright = ImageOps.exif_transpose(image)
        buffer = io.BytesIO()
        _flatten(upright).save(buffer, format="PNG")
        return buffer.getvalue()


class ImageConverter:
    kind = "image"

    def __init__(self, max_pixels: int) -> None:
        self._max_pixels = max_pixels

    def can_handle(self, mime: str) -> bool:
        return mime in IMAGE_MIMES

    def _check(self, path: Path) -> None:
        try:
            with Image.open(path) as image:
                width, height = image.size
                image.verify()
        except (UnidentifiedImageError, OSError, SyntaxError) as error:
            raise MergerError(ErrorCode.CORRUPT_FILE, "This image is damaged and can't be read.") from error
        if width * height > self._max_pixels:
            raise MergerError(
                ErrorCode.LIMIT_EXCEEDED,
                f"This image is {width * height / 1e6:.1f} megapixels; the limit is {self._max_pixels / 1e6:g}. Resize it, then upload it again.",
            )

    def _convert(self, path: Path, out: Path, opts: ImageOptions) -> None:
        self._check(path)
        try:
            data = _image_bytes(path)
            out.write_bytes(img2pdf.convert(data, layout_fun=_layout(opts), rotation=img2pdf.Rotation.ifvalid))
        except (*_IMG2PDF_ERRORS, ValueError, OSError) as error:
            raise MergerError(ErrorCode.CORRUPT_FILE, "This image couldn't be converted to a PDF page.") from error

    async def inspect(self, path: Path) -> int:
        await asyncio.to_thread(self._check, path)
        return 1

    async def to_pdf(self, path: Path, work_dir: Path, opts: ImageOptions) -> Path:
        out = work_dir / f"{path.name}-{uuid4().hex}.pdf"
        await asyncio.to_thread(self._convert, path, out, opts)
        return out
