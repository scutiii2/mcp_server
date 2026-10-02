from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from src.errors import ErrorCode, MergerError
from src.models import MergePlan
from src.service import Caller
from tests.conftest import chunks, make_image, make_pdf, page_widths

WEB = Caller("web:1")
OTHER = Caller("web:2")
BOT = Caller("mcp:alice", privileged=True)


async def upload(service, caller, path: Path):
    return await service.upload(caller, path.name, chunks(path.read_bytes()))


async def test_upload_sniffs_and_counts_pages(service, tmp_path: Path):
    stored = await upload(service, WEB, make_pdf(tmp_path / "a.pdf", [100, 101]))

    assert (stored.kind, stored.pages, stored.mime, stored.name) == ("pdf", 2, "application/pdf", "a.pdf")


async def test_upload_ignores_misleading_extension(service, tmp_path: Path):
    png = make_image(tmp_path / "x.png", fmt="PNG")
    disguised = tmp_path / "x.pdf"
    disguised.write_bytes(png.read_bytes())

    stored = await upload(service, WEB, disguised)

    assert stored.kind == "image" and stored.mime == "image/png"


async def test_unsupported_upload_leaves_nothing_behind(service, tmp_path: Path, settings):
    text = tmp_path / "notes.txt"
    text.write_text("hello")

    with pytest.raises(MergerError) as caught:
        await upload(service, WEB, text)

    assert caught.value.code == ErrorCode.UNSUPPORTED_TYPE
    assert [p for p in settings.store_dir.rglob("*") if p.is_file()] == []


async def test_merge_pdf_and_image_end_to_end(service, tmp_path: Path):
    pdf = await upload(service, WEB, make_pdf(tmp_path / "a.pdf", [100, 101, 102]))
    img = await upload(service, WEB, make_image(tmp_path / "b.jpg"))
    plan = MergePlan.model_validate(
        {
            "segments": [
                {"file_id": pdf.file_id, "pages": "3"},
                {"file_id": img.file_id},
                {"file_id": pdf.file_id, "pages": "1"},
            ],
            "output": {"filename": "out", "title": "T"},
        }
    )

    result = await service.merge_and_wait(WEB, plan)

    assert result.name == "out.pdf" and result.pages == 3
    merged = service.get_file(WEB, result.file_id)
    widths = page_widths(service.file_path(merged))
    assert widths[0] == 102 and widths[2] == 100
    assert widths[1] == 595  # A4 image page


async def test_plan_errors_raise_before_queueing(service, tmp_path: Path):
    pdf = await upload(service, WEB, make_pdf(tmp_path / "a.pdf", [100]))
    plan = MergePlan.model_validate({"segments": [{"file_id": pdf.file_id, "pages": "2"}]})

    with pytest.raises(MergerError) as caught:
        service.start_merge(WEB, plan)
    assert caught.value.code == ErrorCode.INVALID_RANGE


async def test_sessions_are_isolated_but_privileged_callers_use_ids(service, tmp_path: Path):
    pdf = await upload(service, WEB, make_pdf(tmp_path / "a.pdf", [100]))
    plan = MergePlan.model_validate({"segments": [{"file_id": pdf.file_id}]})

    with pytest.raises(MergerError):
        service.start_merge(OTHER, plan)
    result = await service.merge_and_wait(BOT, plan)

    assert [f.file_id for f in service.list_files(BOT)] == [result.file_id]
    assert service.list_files(OTHER) == []


async def test_download_url_round_trip(service, tmp_path: Path):
    pdf = await upload(service, WEB, make_pdf(tmp_path / "a.pdf", [100]))

    url = urlsplit(service.download_url(pdf))
    query = parse_qs(url.query)

    assert url.path == f"/api/files/{pdf.file_id}/download"
    assert service.file_for_download(pdf.file_id, int(query["exp"][0]), query["sig"][0]) == pdf
    with pytest.raises(MergerError):
        service.file_for_download(pdf.file_id, int(query["exp"][0]), "0" * 64)


async def test_inspect_reports_failures_without_aborting(service, tmp_path: Path):
    pdf = await upload(service, WEB, make_pdf(tmp_path / "a.pdf", [100]))

    files, failed = service.inspect(BOT, [pdf.file_id, "f_" + "0" * 32])

    assert [f.file_id for f in files] == [pdf.file_id]
    assert [(file_id, error.code) for file_id, error in failed] == [("f_" + "0" * 32, ErrorCode.FILE_NOT_FOUND)]
