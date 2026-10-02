"""The converter contract. Every input type becomes a PDF before assembly.

Adding a type (for example Word documents via LibreOffice) means one new
class implementing SourceConverter plus one line in registry.py. Nothing
else changes.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

PageSize = Literal["A4", "Letter", "match"]
FitMode = Literal["fit", "fill", "original"]


@dataclass(frozen=True)
class ImageOptions:
    """How an image is placed on its page. Ignored by non-image converters."""

    page_size: PageSize = "A4"
    fit: FitMode = "fit"
    margin_mm: float = 10.0


class SourceConverter(Protocol):
    kind: str

    def can_handle(self, mime: str) -> bool: ...

    async def inspect(self, path: Path) -> int:
        """Validate the file and return its page count. Raises MergerError."""
        ...

    async def to_pdf(self, path: Path, work_dir: Path, opts: ImageOptions) -> Path:
        """A PDF version of ``path``. May return ``path`` itself when it is already a PDF."""
        ...
