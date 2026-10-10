"""Pure rules for tickets: vocabulary, fingerprints, tags and priority elevation."""

from __future__ import annotations

import hashlib
import re
from typing import Iterable

TYPES = ("bug", "feature", "other")
STATUSES = ("open", "in_progress", "resolved", "closed")
PRIORITIES = ("low", "normal", "high", "urgent")
SOURCES = ("user", "ai_user_request", "ai_auto")
CLOSED_STATUSES = ("resolved", "closed")
MAX_TAGS_PER_TICKET = 5

_PATH = re.compile(r"(?:[a-z]:\\|/)[^\s'\"]+")
_HEX = re.compile(r"\b[0-9a-f]{8,}\b")
_NUMBER = re.compile(r"\d+")


def priority_rank(priority: str) -> int:
    return PRIORITIES.index(priority)


def higher_priority(a: str, b: str) -> str:
    return a if priority_rank(a) >= priority_rank(b) else b


def fingerprint(tool_name: str | None, error_text: str | None) -> str:
    """Stable id for "the same error from the same tool": numbers, paths and ids are blanked out."""
    text = (error_text or "").lower()
    text = _PATH.sub("<path>", text)
    text = _HEX.sub("<id>", text)
    text = _NUMBER.sub("#", text)
    text = " ".join(text.split())
    digest = hashlib.sha256(f"{(tool_name or '').strip().lower()}\n{text}".encode("utf-8")).hexdigest()
    return digest[:16]


def clean_tags(tags: Iterable[str] | None, vocabulary: Iterable[str], *, allow_custom: bool = False) -> list[str]:
    """Normalize unique tags, at most five; manual tickets may add custom names."""
    allowed = set(vocabulary)
    result: list[str] = []
    for tag in tags or []:
        name = str(tag).strip().lower()
        if allow_custom and name not in allowed:
            name = re.sub(r"\s+", "-", name)
            if name and (len(name) > 64 or not re.fullmatch(r"[\w-]+", name)):
                raise ValueError("Custom tags must use letters, numbers, hyphens or underscores, up to 64 characters.")
        if name and (name in allowed or allow_custom) and name not in result:
            result.append(name)
        if len(result) == MAX_TAGS_PER_TICKET:
            break
    return result


def elevated_priority(current: str, total: int, recent: int, elevation: dict[str, dict[str, int]]) -> str:
    """`current` raised to the highest level whose ticket-count or recent-rate threshold is met. Never lowers."""
    level = current
    for name in ("high", "urgent"):
        rule = elevation.get(name)
        if rule and (total >= rule["tickets"] or recent >= rule["recent"]):
            level = higher_priority(level, name)
    return level
