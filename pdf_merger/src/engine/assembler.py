"""Build the output PDF from converted parts with pikepdf (qpdf).

Each source PDF is opened once however many parts use it. The whole build
runs in one worker thread; ``on_page`` is called from that thread, so
callers must hand progress back to the event loop thread-safely.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

import pikepdf
from pikepdf import OutlineItem


@dataclass(frozen=True)
class AssemblyPart:
    pdf_path: Path
    pages: tuple[int, ...]
    rotate: int
    bookmark: str
    group_key: str  # parts in a row with the same key share one bookmark


def _assemble(
    parts: Sequence[AssemblyPart],
    out_path: Path,
    title: str | None,
    author: str | None,
    bookmarks: bool,
    on_page: Callable[[int], None] | None,
) -> int:
    output = pikepdf.new()
    sources: dict[Path, pikepdf.Pdf] = {}
    try:
        outline_items: list[OutlineItem] = []
        previous_key: str | None = None
        for part in parts:
            source = sources.get(part.pdf_path)
            if source is None:
                source = sources[part.pdf_path] = pikepdf.open(part.pdf_path)
            first_page = len(output.pages)
            for index in part.pages:
                output.pages.append(source.pages[index])
                if part.rotate:
                    output.pages[-1].rotate(part.rotate, relative=True)
                if on_page is not None:
                    on_page(len(output.pages))
            if bookmarks and part.group_key != previous_key:
                outline_items.append(OutlineItem(part.bookmark, first_page))
            previous_key = part.group_key

        if outline_items:
            with output.open_outline() as outline:
                outline.root.extend(outline_items)
        if title:
            output.docinfo["/Title"] = title
        if author:
            output.docinfo["/Author"] = author
        output.save(out_path)
        return len(output.pages)
    finally:
        for source in sources.values():
            source.close()
        output.close()


class Assembler:
    """Merges converted PDF parts into one output file."""

    async def assemble(
        self,
        parts: Sequence[AssemblyPart],
        out_path: Path,
        *,
        title: str | None,
        author: str | None,
        bookmarks: bool,
        on_page: Callable[[int], None] | None = None,
    ) -> int:
        """Write the merged PDF to ``out_path``; returns its page count."""
        return await asyncio.to_thread(_assemble, parts, out_path, title, author, bookmarks, on_page)
