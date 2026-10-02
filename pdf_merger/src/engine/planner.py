"""Validate a MergePlan against stored files and expand it into concrete pages.

Runs before a job is queued, so every plan error reaches the caller as an
immediate 4xx instead of a failed job.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from src.config import Limits
from src.converters.base import ImageOptions
from src.engine.page_ranges import parse_page_ranges
from src.errors import ErrorCode, MergerError
from src.models import MergePlan
from src.store.file_store import StoredFile


@dataclass(frozen=True)
class PlannedSegment:
    file: StoredFile
    pages: tuple[int, ...]
    rotate: int
    image_options: ImageOptions | None


@dataclass(frozen=True)
class ExpandedPlan:
    segments: tuple[PlannedSegment, ...]
    total_pages: int


def expand_plan(plan: MergePlan, lookup: Callable[[str], StoredFile], limits: Limits) -> ExpandedPlan:
    """O(total pages). ``lookup`` raises file_not_found for IDs the caller may not use."""
    if len(plan.segments) > limits.max_segments:
        raise MergerError(ErrorCode.LIMIT_EXCEEDED, f"A merge can have at most {limits.max_segments} segments.")

    output = plan.output
    seen: set[tuple[str, int]] = set()
    planned: list[PlannedSegment] = []
    total = 0
    for number, segment in enumerate(plan.segments, start=1):
        file = lookup(segment.file_id)
        if file.kind == "image":
            pages: tuple[int, ...] = (0,)
            options = ImageOptions(
                page_size=output.image_page_size, fit=segment.fit or output.image_fit, margin_mm=output.image_margin_mm
            )
        else:
            try:
                pages = tuple(parse_page_ranges(segment.pages, file.pages))
            except MergerError as error:
                raise MergerError(ErrorCode.INVALID_RANGE, f"Segment {number} ({file.name}): {error.message}") from error
            options = None

        for page in pages:
            key = (file.file_id, page)
            if key in seen:
                raise MergerError(
                    ErrorCode.INVALID_RANGE,
                    f"Segment {number} ({file.name}): page {page + 1} is already used. Each page can appear once.",
                )
            seen.add(key)

        total += len(pages)
        if total > limits.max_output_pages:
            raise MergerError(ErrorCode.LIMIT_EXCEEDED, f"The merged PDF would have more than {limits.max_output_pages} pages.")
        planned.append(PlannedSegment(file=file, pages=pages, rotate=segment.rotate, image_options=options))

    return ExpandedPlan(segments=tuple(planned), total_pages=total)
