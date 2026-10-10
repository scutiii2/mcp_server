"""Mask secrets and personal data in log text before a model reads it."""

from __future__ import annotations

import re

MASK = "[REDACTED]"

# (pattern, replacement). Order matters: URL credentials and header values go
# first so the generic key=value rule does not see half-masked text.
_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?i)(://[^/\s:@]+:)[^@\s/]+(@)"), rf"\1{MASK}\2"),
    (re.compile(r"(?i)\b(authorization|proxy-authorization|cookie|set-cookie)(\s*[:=]\s*)[^\r\n]+"), rf"\1\2{MASK}"),
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}"), f"Bearer {MASK}"),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"), MASK),
    (re.compile(r"\b(?:sk|pk|rk)-[A-Za-z0-9_-]{16,}\b"), MASK),
    (re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"), MASK),
    (
        re.compile(
            r"(?i)\b([\w.-]*(?:password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key|private[_-]?key)[\w.-]*)"
            r"(\s*[=:]\s*)(?:\"[^\"\r\n]*\"|'[^'\r\n]*'|[^\s,;&\"']+)"
        ),
        rf"\1\2{MASK}",
    ),
    (re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b"), MASK),
)


def redact(text: str) -> tuple[str, int]:
    """The text with secrets masked, and how many masks were applied."""
    total = 0
    for pattern, replacement in _RULES:
        text, count = pattern.subn(replacement, text)
        total += count
    return text, total
