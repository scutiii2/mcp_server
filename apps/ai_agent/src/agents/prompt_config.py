"""The prompt text every agent shares, editable without touching code.

`configs/config_prompts.json` holds only the pieces an admin changed; any
missing or empty piece falls back to DEFAULTS below, so an absent file means
today's behaviour. agent_roles.py builds each agent's system prompt from
these values once at start-up, so a change takes effect when the agent
restarts (the supervisor restarts all agents when this file changes).

Pure stdlib on purpose: agent_roles and agent_store both import it.
"""

from __future__ import annotations

import json
import os
import string
import tempfile
from pathlib import Path

PATH = Path(__file__).resolve().parent.parent.parent / "configs" / "config_prompts.json"

DEFAULTS: dict[str, str] = {
    "app_name": "Ember",
    "app_description": "Support tool that reads real system state through tools instead of manual lookups.",
    "identity_template": (
        "Your name is {app_name}: {role}, an AI Assistant. {app_description} "
        "When asked who you are or what your name is, answer with your name and this role."
    ),
    "default_instructions": (
        "You are a helpful assistant with access to tools. Use them to get real data rather than guessing, "
        "and say so plainly when no tool can answer the question. Confirm with the user before any "
        "destructive or hard-to-reverse action."
    ),
    "roster_intro": (
        "You coordinate these specialist agents. When a part of the request fits one of them "
        "better than you, hand that part to it with delegate_to_agent, then combine the answers:"
    ),
    "caveman_instructions": (
        "Respond terse, like a smart caveman. Keep all technical substance; cut "
        "only fluff. Drop articles (a/an/the), filler (just/really/basically), "
        "pleasantries and hedging. Fragments are fine. Use short synonyms. Keep "
        "code blocks, commands, file paths, error messages, identifiers and "
        "numbers exactly as they are. Never drop not/no/never/only/except: they "
        "flip meaning. Use full, plain sentences for warnings and for anything "
        "irreversible or destructive. Write in the language the user writes in."
    ),
}

MAX_LENGTH = 8000
# The identity template may use exactly these placeholders.
_TEMPLATE_FIELDS = {"app_name", "app_description", "role"}


class PromptConfigError(Exception):
    """A rejected prompt change; the message is safe to show."""


def _read(path: Path) -> dict[str, str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {k: v for k, v in data.items() if k in DEFAULTS and isinstance(v, str) and v.strip()}


def load(path: Path = PATH) -> dict[str, str]:
    """Every prompt text: the file's value where set, else the default."""
    return {**DEFAULTS, **_read(path)}


def overrides(path: Path = PATH) -> dict[str, str]:
    """Only what the file sets (what differs from the defaults)."""
    return {k: v for k, v in _read(path).items() if v != DEFAULTS[k]}


def _validate(key: str, value: str) -> None:
    if key not in DEFAULTS:
        raise PromptConfigError(f"unknown prompt {key!r}; use one of: {', '.join(DEFAULTS)}")
    if len(value) > MAX_LENGTH:
        raise PromptConfigError(f"{key} is longer than {MAX_LENGTH} characters")
    if key == "identity_template":
        try:
            fields = {name for _, name, _, _ in string.Formatter().parse(value) if name is not None}
        except ValueError as error:
            raise PromptConfigError(f"identity_template is not valid: {error}") from error
        unknown = fields - _TEMPLATE_FIELDS
        if unknown:
            raise PromptConfigError(
                f"identity_template can only use {{app_name}}, {{app_description}} and {{role}}, not {{{sorted(unknown)[0]}}}"
            )


def save(changes: dict[str, str | None], path: Path = PATH) -> dict[str, str]:
    """Apply `changes` (key -> new text; None or blank = back to the default)
    and write the file atomically. Returns the effective values."""
    current = overrides(path)
    for key, value in changes.items():
        if key not in DEFAULTS:
            raise PromptConfigError(f"unknown prompt {key!r}; use one of: {', '.join(DEFAULTS)}")
        if value is None or not value.strip() or value == DEFAULTS[key]:
            current.pop(key, None)
        else:
            _validate(key, value)
            current[key] = value
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            file.write(json.dumps(current, indent=2, ensure_ascii=False) + "\n")
        os.replace(temp_name, path)
    except BaseException:
        Path(temp_name).unlink(missing_ok=True)
        raise
    return load(path)


def signature(path: Path = PATH) -> int | None:
    """Changes whenever the file is rewritten; None when it does not exist."""
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return None
