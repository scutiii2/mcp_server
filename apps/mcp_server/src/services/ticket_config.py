"""Ticket settings from configs/config_tickets.json (every key optional)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_TAGS: dict[str, str] = {
    "config": "A setting, config file or environment variable is missing or wrong.",
    "tool-failure": "A tool or capability failed or returned an error.",
    "auth": "Login, permissions or access problems.",
    "ui": "Something looks or behaves wrong in the web interface.",
    "chat": "Chat answers, history, attachments or agents misbehave.",
    "performance": "Slowness, timeouts or high resource use.",
    "email": "Sending or receiving email, invitations or verification.",
    "feature-request": "A new feature or an improvement is being suggested.",
}
DEFAULT_ELEVATION: dict[str, dict[str, int]] = {
    "high": {"tickets": 3, "recent": 2},
    "urgent": {"tickets": 6, "recent": 4},
}
MIN_TAGS = 2
MAX_TAGS = 10  # Laya's `choice` question allows at most ten options.


@dataclass(frozen=True)
class TicketConfig:
    tags: dict[str, str]
    auto_hourly_cap: int
    recent_hours: int
    elevation: dict[str, dict[str, int]]
    laya_min_confidence: float
    laya_candidates: int
    laya_timeout_seconds: float


def _positive_int(raw: dict[str, Any], key: str, default: int) -> int:
    value = raw.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"config_tickets.json: {key} must be a whole number of at least 1.")
    return value


def _tags(raw: Any) -> dict[str, str]:
    if not isinstance(raw, dict) or not MIN_TAGS <= len(raw) <= MAX_TAGS:
        raise ValueError(f"config_tickets.json: tags must be an object of {MIN_TAGS} to {MAX_TAGS} tag: description pairs.")
    for tag, description in raw.items():
        if not isinstance(tag, str) or not tag.strip() or not isinstance(description, str) or not description.strip():
            raise ValueError("config_tickets.json: every tag needs a non-empty name and description.")
    return {tag.strip().lower(): description.strip() for tag, description in raw.items()}


def _elevation(raw: Any) -> dict[str, dict[str, int]]:
    if not isinstance(raw, dict) or not set(raw) <= set(DEFAULT_ELEVATION):
        raise ValueError("config_tickets.json: elevation may only define 'high' and 'urgent'.")
    result: dict[str, dict[str, int]] = {}
    for level, rule in raw.items():
        if not isinstance(rule, dict):
            raise ValueError(f"config_tickets.json: elevation.{level} must be an object.")
        result[level] = {key: _positive_int(rule, key, 0) for key in ("tickets", "recent")}
    return result


def load_ticket_config(path: Path) -> TicketConfig:
    raw: Any = {}
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError(f"{path.name} is not valid JSON: {error}") from error
    if not isinstance(raw, dict):
        raise ValueError(f"{path.name} must hold a JSON object.")
    laya = raw.get("laya", {})
    if not isinstance(laya, dict):
        raise ValueError("config_tickets.json: laya must be an object.")
    confidence = laya.get("min_confidence", 0.7)
    timeout = laya.get("timeout_seconds", 20.0)
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 < confidence <= 1:
        raise ValueError("config_tickets.json: laya.min_confidence must be above 0 and at most 1.")
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout <= 0:
        raise ValueError("config_tickets.json: laya.timeout_seconds must be above 0.")
    candidates = _positive_int(laya, "candidates", 5)
    if candidates > 10:
        raise ValueError("config_tickets.json: laya.candidates must be at most 10.")
    return TicketConfig(
        tags=_tags(raw.get("tags", DEFAULT_TAGS)),
        auto_hourly_cap=_positive_int(raw, "auto_hourly_cap", 5),
        recent_hours=_positive_int(raw, "recent_hours", 24),
        elevation=_elevation(raw["elevation"]) if "elevation" in raw else dict(DEFAULT_ELEVATION),
        laya_min_confidence=float(confidence),
        laya_candidates=candidates,
        laya_timeout_seconds=float(timeout),
    )
