"""PDFs need no conversion; this converter only validates them."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pikepdf

from src.converters.base import ImageOptions
from src.errors import ErrorCode, MergerError


def _count_pages(path: Path) -> int:
    try:
        with pikepdf.open(path) as pdf:
            count = len(pdf.pages)
    except pikepdf.PasswordError as error:
        raise MergerError(
            ErrorCode.ENCRYPTED_PDF, "This PDF is password-protected. Remove the password, then upload it again."
        ) from error
    except pikepdf.PdfError as error:
        raise MergerError(ErrorCode.CORRUPT_FILE, "This PDF is damaged and can't be read.") from error
    if count == 0:
        raise MergerError(ErrorCode.CORRUPT_FILE, "This PDF has no pages.")
    return count


class PdfPassthrough:
    kind = "pdf"

    def can_handle(self, mime: str) -> bool:
        return mime == "application/pdf"

    async def inspect(self, path: Path) -> int:
        return await asyncio.to_thread(_count_pages, path)

    async def to_pdf(self, path: Path, work_dir: Path, opts: ImageOptions) -> Path:
        return path
