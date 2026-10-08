"""Private extensions: the MCP servers an account added for itself.

Every query filters by account. Header values are secrets: they are validated
here, encrypted with the SecretBox before they reach the database, and only
this service decrypts them. `ai_agent` validates again (it is the one that
connects), so the limits below are duplicated there on purpose.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db import utcnow
from src.models import UserExtension
from src.services.secret_box import SecretBox, SecretBoxError

MAX_EXTENSIONS = 20
MAX_HEADERS = 20
MAX_VALUE = 2000
MAX_URL = 1000
MAX_LABEL = 60
MAX_DESCRIPTION = 300
MAX_SLUG = 40
SLUG_PATTERN = r"^[a-z0-9]+(_[a-z0-9]+)*$"
UNREADABLE_MESSAGE = "Its headers can't be read (the secrets key changed). Edit it to set them again."

_HEADER_NAME = re.compile(r"[A-Za-z0-9-]{1,64}")
_FORBIDDEN_HEADERS = frozenset(
    {"host", "content-length", "transfer-encoding", "connection", "upgrade", "te", "trailer", "proxy-authorization", "cookie"}
)
_NOT_SLUG = re.compile(r"[^a-z0-9]+")


class InvalidExtension(ValueError):
    """Input that cannot be saved. The message is safe to show the user."""


class ExtensionNotFound(Exception):
    """No such extension for this account."""


class ExtensionLimit(Exception):
    """The account already has MAX_EXTENSIONS extensions."""


def slugify(label: str) -> str:
    slug = _NOT_SLUG.sub("_", label.strip().lower()).strip("_")[:MAX_SLUG].strip("_")
    return slug or "extension"


def clean_label(label: str) -> str:
    cleaned = " ".join(label.split())
    if not cleaned:
        raise InvalidExtension("Enter a name")
    if len(cleaned) > MAX_LABEL:
        raise InvalidExtension(f"The name can be at most {MAX_LABEL} characters")
    return cleaned


def clean_description(description: str) -> str:
    cleaned = description.strip()
    if len(cleaned) > MAX_DESCRIPTION:
        raise InvalidExtension(f"The description can be at most {MAX_DESCRIPTION} characters")
    return cleaned


def clean_url(url: str) -> str:
    cleaned = url.strip()
    parts = urlsplit(cleaned)
    if not cleaned or len(cleaned) > MAX_URL or parts.scheme not in ("http", "https") or not parts.hostname:
        raise InvalidExtension("Enter an http or https address")
    if parts.username is not None or parts.password is not None:
        raise InvalidExtension("Put credentials in a header, not in the address")
    return cleaned


def clean_headers(headers: Mapping[str, str] | None) -> dict[str, str]:
    if not headers:
        return {}
    if len(headers) > MAX_HEADERS:
        raise InvalidExtension(f"At most {MAX_HEADERS} headers are allowed")
    cleaned: dict[str, str] = {}
    for name, value in headers.items():
        if not _HEADER_NAME.fullmatch(name):
            raise InvalidExtension("A header name may only use letters, digits and hyphens (64 at most)")
        if name.lower() in _FORBIDDEN_HEADERS:
            raise InvalidExtension(f"The header {name} can't be set")
        if not 1 <= len(value) <= MAX_VALUE:
            raise InvalidExtension(f"The value of {name} must be 1 to {MAX_VALUE} characters")
        if any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
            raise InvalidExtension(f"The value of {name} has a control character")
        cleaned[name] = value
    return cleaned


@dataclass(frozen=True)
class StoredExtension:
    row: UserExtension
    # None: the stored headers could not be decrypted (the key changed).
    headers: dict[str, str] | None

    @property
    def readable(self) -> bool:
        return self.headers is not None

    @property
    def header_names(self) -> list[str]:
        return sorted(self.headers or {})

    def __repr__(self) -> str:  # never show header values
        return f"StoredExtension(slug={self.row.slug!r}, readable={self.readable})"


@dataclass(frozen=True)
class TurnExtensions:
    # What ai_agent gets: {"id", "label", "url", "headers"}.
    items: tuple[dict[str, Any], ...]
    # Enabled extensions left out of the turn: {"id", "label", "error"}.
    skipped: tuple[dict[str, str], ...]


class UserExtensionService:
    def __init__(self, session: AsyncSession, account_id: int, box: SecretBox) -> None:
        self._session = session
        self._account_id = account_id
        self._box = box

    def _stored(self, row: UserExtension) -> StoredExtension:
        if row.headers_encrypted is None:
            return StoredExtension(row, {})
        try:
            return StoredExtension(row, self._box.decrypt_map(row.headers_encrypted))
        except SecretBoxError:
            return StoredExtension(row, None)

    async def _rows(self) -> list[UserExtension]:
        result = await self._session.scalars(
            select(UserExtension)
            .where(UserExtension.account_id == self._account_id)
            .order_by(UserExtension.created_at, UserExtension.id)
        )
        return list(result)

    async def _row(self, slug: str) -> UserExtension:
        row = await self._session.scalar(
            select(UserExtension).where(UserExtension.account_id == self._account_id, UserExtension.slug == slug)
        )
        if row is None:
            raise ExtensionNotFound(slug)
        return row

    async def list(self) -> list[StoredExtension]:
        return [self._stored(row) for row in await self._rows()]

    async def get(self, slug: str) -> StoredExtension:
        return self._stored(await self._row(slug))

    async def create(
        self, *, label: str, url: str, description: str = "", headers: Mapping[str, str] | None = None
    ) -> StoredExtension:
        label = clean_label(label)
        url = clean_url(url)
        description = clean_description(description)
        values = clean_headers(headers)
        rows = await self._rows()
        if len(rows) >= MAX_EXTENSIONS:
            raise ExtensionLimit
        taken = {row.slug for row in rows}
        base = slugify(label)
        slug, number = base, 2
        while slug in taken:
            suffix = f"_{number}"
            slug = f"{base[: MAX_SLUG - len(suffix)].rstrip('_')}{suffix}"
            number += 1
        row = UserExtension(
            account_id=self._account_id,
            slug=slug,
            label=label,
            description=description,
            url=url,
            headers_encrypted=self._box.encrypt_map(values) if values else None,
            enabled=True,
        )
        self._session.add(row)
        await self._session.commit()
        return StoredExtension(row, values)

    async def update(
        self,
        slug: str,
        *,
        label: str | None = None,
        description: str | None = None,
        url: str | None = None,
        headers: Mapping[str, str] | None = None,
        enabled: bool | None = None,
    ) -> StoredExtension:
        """`headers`, when given (even empty), replaces the whole set. A new host
        without new headers clears the saved ones: a token is never silently
        sent to another host."""
        row = await self._row(slug)
        if label is not None:
            row.label = clean_label(label)
        if description is not None:
            row.description = clean_description(description)
        host_changed = False
        if url is not None:
            new_url = clean_url(url)
            host_changed = urlsplit(new_url).hostname != urlsplit(row.url).hostname
            row.url = new_url
        if headers is not None:
            values = clean_headers(headers)
            row.headers_encrypted = self._box.encrypt_map(values) if values else None
        elif host_changed:
            row.headers_encrypted = None
        if enabled is not None:
            row.enabled = enabled
        row.updated_at = utcnow()
        await self._session.commit()
        return self._stored(row)

    async def delete(self, slug: str) -> None:
        await self._session.delete(await self._row(slug))
        await self._session.commit()

    async def enabled_for_turn(self) -> TurnExtensions:
        items: list[dict[str, Any]] = []
        skipped: list[dict[str, str]] = []
        for row in await self._rows():
            if not row.enabled:
                continue
            stored = self._stored(row)
            if stored.headers is None:
                skipped.append({"id": row.slug, "label": row.label, "error": UNREADABLE_MESSAGE})
            else:
                items.append({"id": row.slug, "label": row.label, "url": row.url, "headers": dict(stored.headers)})
        return TurnExtensions(tuple(items), tuple(skipped))
