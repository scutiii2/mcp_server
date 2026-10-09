from __future__ import annotations

from pathlib import Path

import pikepdf
import pytest

from src.engine.assembler import AssemblyPart, Assembler
from tests.conftest import make_pdf, page_widths


async def test_pages_are_copied_in_plan_order(tmp_path: Path):
    a = make_pdf(tmp_path / "a.pdf", [100, 101, 102])
    b = make_pdf(tmp_path / "b.pdf", [200])
    out = tmp_path / "out.pdf"
    seen: list[int] = []

    count = await Assembler().assemble(
        [
            AssemblyPart(a, (2, 0), 0, "a", "fa"),
            AssemblyPart(b, (0,), 0, "b", "fb"),
            AssemblyPart(a, (1,), 0, "a", "fa"),
        ],
        out,
        title=None,
        author=None,
        bookmarks=False,
        on_page=seen.append,
    )

    assert count == 4
    assert page_widths(out) == [102, 100, 200, 101]
    assert seen == [1, 2, 3, 4]


async def test_rotation_adds_to_existing_rotation(tmp_path: Path):
    a = make_pdf(tmp_path / "a.pdf", [100], rotate=90)
    out = tmp_path / "out.pdf"

    await Assembler().assemble([AssemblyPart(a, (0,), 90, "a", "fa")], out, title=None, author=None, bookmarks=False)

    with pikepdf.open(out) as pdf:
        assert int(pdf.pages[0].obj.get("/Rotate", 0)) == 180


async def test_bookmarks_collapse_neighbouring_parts_of_one_file(tmp_path: Path):
    a = make_pdf(tmp_path / "a.pdf", [100, 101, 102])
    b = make_pdf(tmp_path / "b.pdf", [200])
    out = tmp_path / "out.pdf"

    await Assembler().assemble(
        [
            AssemblyPart(a, (0,), 0, "contract", "fa"),
            AssemblyPart(a, (1,), 90, "contract", "fa"),
            AssemblyPart(b, (0,), 0, "receipt", "fb"),
            AssemblyPart(a, (2,), 0, "contract", "fa"),
        ],
        out,
        title=None,
        author=None,
        bookmarks=True,
    )

    with pikepdf.open(out) as pdf, pdf.open_outline() as outline:
        assert [item.title for item in outline.root] == ["contract", "receipt", "contract"]


async def test_no_outline_when_bookmarks_off(tmp_path: Path):
    a = make_pdf(tmp_path / "a.pdf", [100])
    out = tmp_path / "out.pdf"

    await Assembler().assemble([AssemblyPart(a, (0,), 0, "a", "fa")], out, title=None, author=None, bookmarks=False)

    with pikepdf.open(out) as pdf, pdf.open_outline() as outline:
        assert list(outline.root) == []


async def test_metadata(tmp_path: Path):
    a = make_pdf(tmp_path / "a.pdf", [100])
    out = tmp_path / "out.pdf"

    await Assembler().assemble([AssemblyPart(a, (0,), 0, "a", "fa")], out, title="Package", author="Jane", bookmarks=False)

    with pikepdf.open(out) as pdf:
        assert str(pdf.docinfo["/Title"]) == "Package"
        assert str(pdf.docinfo["/Author"]) == "Jane"


async def test_preset_cancel_raises_and_writes_nothing(tmp_path: Path):
    import threading

    from src.errors import ErrorCode, MergerError

    a = make_pdf(tmp_path / "a.pdf", [100, 101])
    out = tmp_path / "out.pdf"
    cancel = threading.Event()
    cancel.set()

    with pytest.raises(MergerError) as caught:
        await Assembler().assemble(
            [AssemblyPart(a, (0, 1), 0, "a", "fa")], out, title=None, author=None, bookmarks=False, cancel=cancel
        )

    assert caught.value.code == ErrorCode.MERGE_TIMEOUT
    assert not out.exists()
