from __future__ import annotations

import pytest

from src.config import Limits
from src.converters.base import ImageOptions
from src.engine.planner import expand_plan
from src.errors import ErrorCode, MergerError
from src.models import MergePlan
from src.store.file_store import StoredFile


def stored(file_id: str, kind: str = "pdf", pages: int = 5, name: str = "doc.pdf") -> StoredFile:
    return StoredFile(file_id, "web:1", name, "application/pdf" if kind == "pdf" else "image/jpeg", kind, pages, 10, 0.0, 9e9)


FILES = {"f_pdf": stored("f_pdf"), "f_img": stored("f_img", kind="image", pages=1, name="photo.jpg")}


def lookup(file_id: str) -> StoredFile:
    if file_id not in FILES:
        raise MergerError(ErrorCode.FILE_NOT_FOUND, "missing")
    return FILES[file_id]


def plan(*segments: dict, **output) -> MergePlan:
    return MergePlan.model_validate({"segments": list(segments), "output": output})


def test_segments_expand_in_order():
    expanded = expand_plan(
        plan({"file_id": "f_pdf", "pages": "1-2"}, {"file_id": "f_img"}, {"file_id": "f_pdf", "pages": "5", "rotate": 90}),
        lookup,
        Limits(),
    )

    assert [(s.file.file_id, s.pages, s.rotate) for s in expanded.segments] == [
        ("f_pdf", (0, 1), 0),
        ("f_img", (0,), 0),
        ("f_pdf", (4,), 90),
    ]
    assert expanded.total_pages == 4


def test_image_options_come_from_output_with_segment_fit_override():
    expanded = expand_plan(
        plan({"file_id": "f_img", "fit": "fill"}, image_page_size="Letter", image_fit="fit", image_margin_mm=5),
        lookup,
        Limits(),
    )

    assert expanded.segments[0].image_options == ImageOptions(page_size="Letter", fit="fill", margin_mm=5)


def test_pdf_segments_have_no_image_options():
    assert expand_plan(plan({"file_id": "f_pdf"}), lookup, Limits()).segments[0].image_options is None


def test_bad_range_names_the_segment():
    with pytest.raises(MergerError) as caught:
        expand_plan(plan({"file_id": "f_pdf"}, {"file_id": "f_pdf", "pages": "9"}), lookup, Limits())

    assert caught.value.code == ErrorCode.INVALID_RANGE
    assert caught.value.message.startswith("Segment 2 (doc.pdf):")


def test_duplicate_page_is_rejected():
    with pytest.raises(MergerError) as caught:
        expand_plan(plan({"file_id": "f_pdf", "pages": "1-2"}, {"file_id": "f_pdf", "pages": "2"}), lookup, Limits())

    assert caught.value.code == ErrorCode.INVALID_RANGE
    assert "page 2" in caught.value.message


def test_unknown_file_propagates_not_found():
    with pytest.raises(MergerError) as caught:
        expand_plan(plan({"file_id": "f_nope"}), lookup, Limits())
    assert caught.value.code == ErrorCode.FILE_NOT_FOUND


def test_segment_and_page_limits():
    with pytest.raises(MergerError) as caught:
        expand_plan(plan({"file_id": "f_pdf", "pages": "1"}, {"file_id": "f_img"}), lookup, Limits(max_segments=1))
    assert caught.value.code == ErrorCode.LIMIT_EXCEEDED

    with pytest.raises(MergerError) as caught:
        expand_plan(plan({"file_id": "f_pdf"}), lookup, Limits(max_output_pages=4))
    assert caught.value.code == ErrorCode.LIMIT_EXCEEDED


def test_plan_model_rejects_bad_rotation():
    with pytest.raises(ValueError):
        MergePlan.model_validate({"segments": [{"file_id": "f_pdf", "rotate": 45}]})
