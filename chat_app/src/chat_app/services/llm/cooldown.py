"""Process-wide rate-limit cooldown tracking.

This is intentionally a plain module-level dict, not per-session state -
and that's a deliberate distinction from the CACHED_DUMPS anti-pattern
this project avoided elsewhere. A user's dump-query cache is personal data
that has no business being global; a provider's rate-limit status is the
opposite - it's a genuine process-wide fact. If OpenAI 429s this process
once, it's 429ing every user of this process, not just whoever triggered
it. Sharing that state is correct here.

Caveat worth knowing: this resets on process restart, and isn't shared
across multiple worker processes if this ever runs behind something like
gunicorn with >1 worker - a real cache (Redis, etc.) would fix that. Not
needed for a single-process setup.
"""

from __future__ import annotations

import time

DEFAULT_COOLDOWN_SECONDS = 60.0

_cooldown_until: dict[str, float] = {}


def start_cooldown(provider_id: str, seconds: float = DEFAULT_COOLDOWN_SECONDS) -> None:
    _cooldown_until[provider_id] = time.monotonic() + max(seconds, 1.0)


def seconds_remaining(provider_id: str) -> float:
    until = _cooldown_until.get(provider_id)
    if until is None:
        return 0.0
    return max(0.0, until - time.monotonic())


def is_in_cooldown(provider_id: str) -> bool:
    return seconds_remaining(provider_id) > 0


def reset(provider_id: str | None = None) -> None:
    """Clear cooldown state - used by tests, and available for an admin
    'force retry now' action later if that turns out to be useful."""
    if provider_id is None:
        _cooldown_until.clear()
    else:
        _cooldown_until.pop(provider_id, None)


def extract_retry_after_seconds(error: Exception) -> float | None:
    """Both openai and anthropic's rate-limit errors carry the original
    httpx response, which may include a Retry-After header - prefer the
    server's own answer over guessing a fixed cooldown length."""
    response = getattr(error, "response", None)
    if response is None:
        return None
    header = response.headers.get("retry-after")
    if header is None:
        return None
    try:
        return float(header)
    except ValueError:
        return None
