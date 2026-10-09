"""Pick the converter for a sniffed MIME type."""

from __future__ import annotations

from collections.abc import Sequence

from src.converters.base import SourceConverter
from src.converters.image import ImageConverter
from src.converters.pdf import PdfPassthrough
from src.errors import ErrorCode, MergerError


class ConverterRegistry:
    def __init__(self, converters: Sequence[SourceConverter]) -> None:
        self._converters = tuple(converters)

    def for_mime(self, mime: str | None) -> SourceConverter:
        for converter in self._converters:
            if mime and converter.can_handle(mime):
                return converter
        raise MergerError(
            ErrorCode.UNSUPPORTED_TYPE,
            "This file type isn't supported. Upload a PDF or an image (JPG, PNG, WebP, TIFF, GIF or HEIC).",
        )


def default_registry(max_image_pixels: int) -> ConverterRegistry:
    return ConverterRegistry([PdfPassthrough(), ImageConverter(max_image_pixels)])
