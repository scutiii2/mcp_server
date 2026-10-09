"""Request and response shapes shared by the REST API and the MCP tools."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from src.converters.base import FitMode, PageSize
from src.store.file_store import StoredFile

Rotation = Literal[0, 90, 180, 270]


class Segment(BaseModel):
    """A run of pages from one file. Several segments of one file express any page order."""

    file_id: str = Field(description="ID of an uploaded file, e.g. f_0123... Never invent one.")
    pages: str | None = Field(
        default=None, description='1-based pages like "1-3,7". Null or "all" means every page. Ignored for images.'
    )
    rotate: Rotation = Field(default=0, description="Clockwise degrees added to each page's own rotation.")
    fit: FitMode | None = Field(default=None, description="Images only. Null uses output.image_fit.")


class OutputOptions(BaseModel):
    filename: str = Field(default="merged.pdf", description="File name of the merged PDF.")
    title: str | None = Field(default=None, description="PDF title metadata.")
    author: str | None = Field(default=None, description="PDF author metadata.")
    bookmarks: bool = Field(default=True, description="Add one bookmark per source; neighbouring segments of one file share it.")
    image_page_size: PageSize = Field(default="A4", description='Page size for images; "match" uses the image size.')
    image_fit: FitMode = Field(default="fit", description="Default image fit: fit inside, fill the page, or original size.")
    image_margin_mm: float = Field(default=10, ge=0, le=50, description="Margin around images in millimetres.")


class MergePlan(BaseModel):
    segments: list[Segment] = Field(min_length=1, description="Output order, first to last.")
    output: OutputOptions = Field(default_factory=OutputOptions)


class FileInfo(BaseModel):
    file_id: str
    name: str
    kind: str
    pages: int
    size: int
    expires_at: float

    @classmethod
    def of(cls, file: StoredFile) -> FileInfo:
        return cls(
            file_id=file.file_id, name=file.name, kind=file.kind, pages=file.pages, size=file.size, expires_at=file.expires_at
        )


class MergeResult(BaseModel):
    file_id: str
    name: str
    pages: int
    size: int
    expires_at: float
    download_url: str
