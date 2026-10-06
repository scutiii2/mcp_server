"""Per-capability GUI pages: `capabilities/<folder>/gui/page.json`.

A page is declarative data that ember_web draws with a fixed set of
widgets; the capability's own code never runs in the browser. This module
holds the page models and the loader. `load_page` returns None for every
case that means "no page to show" - no file, capability off, unknown
capability, or an invalid file (logged, so one bad page never breaks the
server or another capability).

Mounted as an HTTP route by `capability_routes.py`, not a tool: a page is
for people, not for a model.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Discriminator, Field, Tag, field_validator, model_validator

from src.services import capability_meta, capability_registry

logger = logging.getLogger(__name__)

_CAPABILITIES_DIR = Path(__file__).resolve().parent / "capabilities"
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}")
_SECTION_ID = r"^[A-Za-z0-9_-]{1,64}$"


def _identifier(value: str | None) -> str | None:
    if value is not None and not _IDENTIFIER.fullmatch(value):
        raise ValueError(f"{value!r} is not a result field name")
    return value


class GuiField(BaseModel):
    """Overrides for one of the tool's own parameters; the form itself is built from the tool's schema."""

    model_config = ConfigDict(extra="ignore")
    param: str = Field(min_length=1)
    label: str | None = None
    order: int | None = None
    hidden: bool = False


class GuiResult(BaseModel):
    """How a tool's structured result is shown. `field` names the value to show.
    `strength` names a numeric result field (bits of entropy) that draws a
    strength bar; `group` spaces a secret for reading (copying still copies it
    whole). Both only apply to a `secret`."""

    model_config = ConfigDict(extra="ignore")
    kind: Literal["secret", "message", "table", "fields"] = "fields"
    field: str | None = None
    detail: str | None = None
    refresh_after: str | None = None
    strength: str | None = None
    group: int | None = Field(default=None, ge=2, le=8)

    _check_names = field_validator("field", "detail", "refresh_after", "strength")(lambda cls, value: _identifier(value))

    @model_validator(mode="after")
    def _needs_a_field(self) -> "GuiResult":
        if self.kind in ("secret", "table") and self.field is None:
            raise ValueError(f"result kind {self.kind!r} needs a 'field'")
        if self.kind != "secret" and (self.strength is not None or self.group is not None):
            raise ValueError("'strength' and 'group' only apply to a result of kind 'secret'")
        return self


class GuiFormSection(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(pattern=_SECTION_ID)
    title: str = Field(min_length=1)
    tool: str = Field(min_length=1)
    submit: str = Field(default="Run", min_length=1)
    fields: list[GuiField] = Field(default_factory=list)
    result: GuiResult = Field(default_factory=GuiResult)
    # Runs when it opens and whenever a control changes (ember_web debounces).
    live: bool = False


class GuiTextSection(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(pattern=_SECTION_ID)
    title: str | None = Field(default=None, min_length=1)
    text: str = Field(min_length=1)


MAX_TABS = 8


class GuiTabsSection(BaseModel):
    """Several forms shown one at a time, each tab keeping its own settings."""

    model_config = ConfigDict(extra="ignore")
    id: str = Field(pattern=_SECTION_ID)
    tabs: list[GuiFormSection] = Field(min_length=2, max_length=MAX_TABS)


def _section_kind(value: Any) -> str:
    if isinstance(value, dict):
        if "tabs" in value:
            return "tabs"
        return "text" if "text" in value else "form"
    if isinstance(value, GuiTabsSection):
        return "tabs"
    return "text" if isinstance(value, GuiTextSection) else "form"


GuiSection = Annotated[
    Union[
        Annotated[GuiFormSection, Tag("form")],
        Annotated[GuiTextSection, Tag("text")],
        Annotated[GuiTabsSection, Tag("tabs")],
    ],
    Discriminator(_section_kind),
]


class GuiPage(BaseModel):
    model_config = ConfigDict(extra="ignore")
    version: Literal[1]
    title: str = Field(min_length=1)
    description: str = ""
    sections: list[GuiSection] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_section_ids(self) -> "GuiPage":
        ids: list[str] = []
        for section in self.sections:
            ids.append(section.id)
            if isinstance(section, GuiTabsSection):
                ids.extend(tab.id for tab in section.tabs)
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        if duplicates:
            raise ValueError(f"duplicate section ids: {', '.join(duplicates)}")
        return self


def form_sections(page: GuiPage) -> Iterator[GuiFormSection]:
    """Every form of the page, those inside tabs included, in page order."""
    for section in page.sections:
        if isinstance(section, GuiFormSection):
            yield section
        elif isinstance(section, GuiTabsSection):
            yield from section.tabs


def parse_page(raw: str, own_tools: set[str] | None) -> GuiPage:
    """Validate `raw`. With `own_tools`, every form's tool must be one of them."""
    page = GuiPage.model_validate_json(raw)
    if own_tools is not None:
        named = {form.tool for form in form_sections(page)}
        foreign = sorted(named - own_tools)
        if foreign:
            raise ValueError(f"page names tools this capability does not own: {', '.join(foreign)}")
    return page


def _page_path(capability_id: str) -> Path | None:
    folder = capability_meta.folder_for_id(capability_id)
    return None if folder is None else _CAPABILITIES_DIR / folder / "gui" / "page.json"


def load_page(capability_id: str) -> GuiPage | None:
    """The capability's page, or None when there is nothing to show (see module docstring)."""
    path = _page_path(capability_id)
    if path is None or not path.is_file():
        return None
    try:
        if not capability_registry.is_enabled(capability_id):
            return None
        return parse_page(path.read_text(encoding="utf-8"), set(capability_registry.tool_names(capability_id)))
    except (KeyError, OSError, ValueError) as error:  # pydantic's ValidationError is a ValueError
        logger.warning("Ignoring the GUI page of capability %r (%s): %s", capability_id, path, error)
        return None
