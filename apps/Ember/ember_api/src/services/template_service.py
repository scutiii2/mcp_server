"""Per-account prompt templates.

Like ChatService, every lookup filters by account, so another user's template
id behaves exactly like a nonexistent one.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.db import utcnow
from src.models import PromptTemplate

MAX_TEMPLATES_PER_ACCOUNT = 100
NAME_MAX = 60
BODY_MAX = 10_000


class TemplateNotFound(Exception):
    """Unknown id, or another account's (deliberately indistinguishable)."""


class TemplateNameTaken(Exception):
    """The account already has a template with this name (ignoring case)."""


class TemplateLimitError(Exception):
    """The account is at its template limit."""


def _key(name: str) -> str:
    return name.casefold()


class TemplateService:
    def __init__(self, session: AsyncSession, account_id: int) -> None:
        self._session = session
        self._account_id = account_id

    async def list(self) -> list[PromptTemplate]:
        """Most recently edited first."""
        return list(
            await self._session.scalars(
                select(PromptTemplate)
                .where(PromptTemplate.account_id == self._account_id)
                .order_by(PromptTemplate.updated_at.desc(), PromptTemplate.id.desc())
            )
        )

    async def create(self, name: str, body: str) -> PromptTemplate:
        count = await self._session.scalar(
            select(func.count()).select_from(PromptTemplate).where(PromptTemplate.account_id == self._account_id)
        )
        if (count or 0) >= MAX_TEMPLATES_PER_ACCOUNT:
            raise TemplateLimitError(f"At most {MAX_TEMPLATES_PER_ACCOUNT} templates per account - delete some first")
        now = utcnow()
        template = PromptTemplate(
            account_id=self._account_id, name=name, name_key=_key(name), body=body, created_at=now, updated_at=now
        )
        self._session.add(template)
        await self._commit(name)
        return template

    async def update(self, template_id: int, name: str, body: str) -> PromptTemplate:
        template = await self._get(template_id)
        template.name = name
        template.name_key = _key(name)
        template.body = body
        template.updated_at = utcnow()
        await self._commit(name)
        return template

    async def delete(self, template_id: int) -> None:
        await self._session.delete(await self._get(template_id))
        await self._session.commit()

    async def _get(self, template_id: int) -> PromptTemplate:
        template = await self._session.scalar(
            select(PromptTemplate).where(
                PromptTemplate.account_id == self._account_id, PromptTemplate.id == template_id
            )
        )
        if template is None:
            raise TemplateNotFound(template_id)
        return template

    async def _commit(self, name: str) -> None:
        """Commits; the unique constraint turns a duplicate name into an error
        even when two requests race past any earlier check."""
        try:
            await self._session.commit()
        except IntegrityError as error:
            await self._session.rollback()
            raise TemplateNameTaken(name) from error
