"""/api/templates: the logged-in account's saved prompts (chat.use)."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Path, Response, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from src.deps import get_db_session, require_permission
from src.models import Account, PromptTemplate
from src.services.permissions import CHAT_USE
from src.services.template_service import (
    BODY_MAX,
    NAME_MAX,
    TemplateLimitError,
    TemplateNameTaken,
    TemplateNotFound,
    TemplateService,
)

router = APIRouter(prefix="/api/templates", tags=["templates"])

require_chat = require_permission(CHAT_USE)

TemplateId = Path(ge=1, le=2**31 - 1)


def get_template_service(
    account: Account = Depends(require_chat),
    session: AsyncSession = Depends(get_db_session),
) -> TemplateService:
    return TemplateService(session, account.id)


class TemplateIn(BaseModel):
    name: str = Field(max_length=NAME_MAX * 4)  # trimmed below, then held to NAME_MAX
    body: str = Field(max_length=BODY_MAX)

    @field_validator("name")
    @classmethod
    def clean_name(cls, name: str) -> str:
        cleaned = " ".join(name.split())
        if not cleaned:
            raise ValueError("name must not be blank")
        if len(cleaned) > NAME_MAX:
            raise ValueError(f"name must be at most {NAME_MAX} characters")
        return cleaned

    @field_validator("body")
    @classmethod
    def body_not_blank(cls, body: str) -> str:
        if not body.strip():
            raise ValueError("body must not be blank")
        return body


class TemplateOut(BaseModel):
    id: int
    name: str
    body: str
    created_at: datetime
    updated_at: datetime

    @classmethod
    def of(cls, template: PromptTemplate) -> TemplateOut:
        return cls(
            id=template.id,
            name=template.name,
            body=template.body,
            created_at=template.created_at,
            updated_at=template.updated_at,
        )


def _not_found() -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, "Template not found")


def _name_taken(name: str) -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, f'You already have a template named "{name}"')


@router.get("")
async def list_templates(templates: TemplateService = Depends(get_template_service)) -> list[TemplateOut]:
    """Most recently edited first."""
    return [TemplateOut.of(t) for t in await templates.list()]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_template(
    body: TemplateIn, templates: TemplateService = Depends(get_template_service)
) -> TemplateOut:
    try:
        return TemplateOut.of(await templates.create(body.name, body.body))
    except TemplateNameTaken as error:
        raise _name_taken(body.name) from error
    except TemplateLimitError as error:
        raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error


@router.put("/{template_id}")
async def update_template(
    body: TemplateIn,
    template_id: int = TemplateId,
    templates: TemplateService = Depends(get_template_service),
) -> TemplateOut:
    try:
        return TemplateOut.of(await templates.update(template_id, body.name, body.body))
    except TemplateNotFound as error:
        raise _not_found() from error
    except TemplateNameTaken as error:
        raise _name_taken(body.name) from error


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_template(
    template_id: int = TemplateId, templates: TemplateService = Depends(get_template_service)
) -> Response:
    try:
        await templates.delete(template_id)
    except TemplateNotFound as error:
        raise _not_found() from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)
