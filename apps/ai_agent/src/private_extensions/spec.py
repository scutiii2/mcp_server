"""One private extension as ember_api sends it with a turn, validated.

ember_api validates too; this is the last check before the process connects
somewhere, so it does not trust the sender. Header values are secrets:
`describe_error` is the only way an error leaves this package, and it hides
them.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import httpx

from src.private_extensions.guard import BlockedAddress, RedirectRefused

SLUG = re.compile(r"[a-z0-9]+(?:_[a-z0-9]+)*")
MAX_SLUG = 40
MAX_LABEL = 60
MAX_URL = 1000
MAX_HEADERS = 20
MAX_VALUE = 2000
MAX_ERROR = 200
_HEADER_NAME = re.compile(r"[A-Za-z0-9-]{1,64}")
_FORBIDDEN_HEADERS = frozenset(
    {"host", "content-length", "transfer-encoding", "connection", "upgrade", "te", "trailer", "proxy-authorization", "cookie"}
)


class InvalidSpec(ValueError):
    """A private extension that cannot be used. The message is safe to show."""


def _headers(raw: Any) -> tuple[tuple[str, str], ...]:
    if raw is None:
        return ()
    if not isinstance(raw, Mapping):
        raise InvalidSpec("Headers must be a set of names and values")
    if len(raw) > MAX_HEADERS:
        raise InvalidSpec(f"At most {MAX_HEADERS} headers are allowed")
    pairs: list[tuple[str, str]] = []
    for name, value in raw.items():
        if not isinstance(name, str) or not _HEADER_NAME.fullmatch(name):
            raise InvalidSpec("A header name may only use letters, digits and hyphens (64 at most)")
        if name.lower() in _FORBIDDEN_HEADERS:
            raise InvalidSpec(f"The header {name} can't be set")
        if not isinstance(value, str) or not 1 <= len(value) <= MAX_VALUE:
            raise InvalidSpec(f"The value of {name} must be 1 to {MAX_VALUE} characters")
        if any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
            raise InvalidSpec(f"The value of {name} has a control character")
        pairs.append((name, value))
    return tuple(sorted(pairs))


def _url(raw: Any) -> str:
    if not isinstance(raw, str) or not raw or len(raw) > MAX_URL:
        raise InvalidSpec("Enter an http or https address")
    parts = urlsplit(raw)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise InvalidSpec("Enter an http or https address")
    if parts.username is not None or parts.password is not None:
        raise InvalidSpec("Put credentials in a header, not in the address")
    return raw


@dataclass(frozen=True)
class PrivateSpec:
    slug: str
    label: str
    url: str
    headers: tuple[tuple[str, str], ...] = ()

    @property
    def header_map(self) -> dict[str, str]:
        return dict(self.headers)

    @property
    def host(self) -> str:
        return urlsplit(self.url).hostname or ""

    @property
    def secrets(self) -> tuple[str, ...]:
        return tuple(value for _name, value in self.headers)

    def key(self) -> str:
        """Same url and headers, same key (header order does not matter)."""
        return hashlib.sha256(json.dumps([self.url, list(self.headers)]).encode("utf-8")).hexdigest()

    @classmethod
    def parse(cls, raw: Any) -> PrivateSpec:
        if not isinstance(raw, Mapping):
            raise InvalidSpec("A private extension must be an object")
        slug = raw.get("id")
        if not isinstance(slug, str) or len(slug) > MAX_SLUG or not SLUG.fullmatch(slug):
            raise InvalidSpec("The extension id is not valid")
        label = raw.get("label")
        label = label.strip()[:MAX_LABEL] if isinstance(label, str) and label.strip() else slug
        return cls(slug=slug, label=label, url=_url(raw.get("url")), headers=_headers(raw.get("headers")))

    @classmethod
    def from_probe(cls, url: str, headers: Mapping[str, str] | None) -> PrivateSpec:
        return cls(slug="probe", label="probe", url=_url(url), headers=_headers(headers))


def describe_error(error: BaseException, secrets: Iterable[str] = ()) -> str:
    """One short line about `error`, safe to show: the guard's own messages as
    they are, anything else cut to its first line, with every secret hidden."""
    while isinstance(error, BaseExceptionGroup) and error.exceptions:
        error = error.exceptions[0]
    if isinstance(error, (BlockedAddress, RedirectRefused)):
        return str(error)
    if isinstance(error, (TimeoutError, httpx.TimeoutException)):
        return "Timed out"
    text = (str(error).strip().splitlines() or [""])[0].strip() or type(error).__name__
    for secret in sorted((s for s in secrets if s), key=len, reverse=True):
        text = text.replace(secret, "***")
    return text[:MAX_ERROR]
