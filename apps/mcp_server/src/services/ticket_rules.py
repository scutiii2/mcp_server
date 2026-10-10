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


def clean_tags(tags: Iterable[str] | None, vocabulary: Iterable[str]) -> list[str]:
    """The tags that are in the vocabulary, lower-cased, unique, in order, at most five."""
    allowed = set(vocabulary)
    result: list[str] = []
    for tag in tags or []:
        name = str(tag).strip().lower()
        if name in allowed and name not in result:
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
