"""Loader for the JSON config file that holds per-deployment settings.

Three different kinds of configuration live in this project, deliberately
kept apart:

  - ``mcp_server/config.py`` - process settings read from environment
    variables (bind host/port, where this file lives). Small, flat,
    always present.
  - this file - structured, per-deployment data read from the JSON file
    at ``settings.config_path``: host inventories, ports, addresses,
    recipient lists. Too nested to be comfortable as env vars.
  - the environment - the actual secret *values*, which the JSON file
    only refers to by name (see below).

Structure and secrets want opposite treatment. Structure benefits from
being versioned, diffed and reviewed; secrets should never be written
down next to it. Mixing both into one file is what makes a config file
feel radioactive - you can't share it, commit it, or paste it into an
issue without leaking something.

So a string anywhere in the config file may contain ``${VAR}``, which is
replaced at load time with that environment variable's value::

    "password": "${SMTP_PASSWORD}"

That keeps ``config.json`` free of secrets - it names them instead of
holding them - while the values live wherever is appropriate for the
deployment: ``.env`` in development, or injected by the service manager,
container runtime, or a secrets manager in production. Swapping that
backend later means changing how the environment gets populated, not
this file's format and not any domain code.

Write ``$$`` for a literal ``$`` if a value genuinely needs to contain
``${...}`` text rather than have it substituted.

Deliberately fails loudly, at load time, with a message naming the file
and the exact key - rather than returning ``{}`` or an empty string and
letting a capability fail much later with a confusing error deep inside
domain logic. The rule for which exception: ``KeyError`` when something
required is absent (a config key, an environment variable), ``ValueError``
when it's present but unusable (malformed JSON, an empty secret).

Add a loader function per config section as capabilities need them,
following ``load_email_config`` below: read the section, validate what's
required, return a frozen dataclass. Domain code should take that
dataclass, never a raw dict - that way a typo in config.json is caught
here instead of at the call site.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ${NAME}, where NAME is a normal environment-variable identifier. A "$"
# not followed by "{" is left alone, so ordinary text and anything shell-
# flavored ("$HOME", "US$5") passes through untouched.
#
# "$$" is an escape for a literal "$", so "$${NAME}" survives as the text
# "${NAME}" instead of being looked up (same convention as
# docker-compose). Without it there'd be no way to store a string that
# genuinely contains ${...} - which is easy to hit by accident, e.g. a
# template or a comment describing this very syntax.
_ENV_PLACEHOLDER = re.compile(r"\$\$|\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


@dataclass(frozen=True)
class EmailConfig:
    smtp_server: str
    smtp_port: int
    from_address: str
    password: str
    to: list[str]
    # Who receives approval requests for gated capabilities. Kept separate
    # from `to` on purpose: general notifications and "press this button
    # to let something irreversible happen" are different audiences, and
    # the second one is a standing authorization list. Defaults to `to`
    # when unset, so the split is available without being mandatory.
    approver_emails: list[str] = field(default_factory=list)


def _resolve_placeholder(name: str, *, where: str, config_path: Path) -> str:
    value = os.environ.get(name)
    if value is None:
        raise KeyError(
            f"Config file {config_path} refers to ${{{name}}} at '{where}', but "
            f"{name} is not set in the environment. Add it to mcp_server/.env "
            f"(or however this deployment supplies secrets)."
        )
    if value == "":
        # Almost always "SMTP_PASSWORD=" left blank in .env rather than a
        # genuinely empty secret - and a blank password fails later at
        # SMTP login with a far less obvious message. Write "" directly in
        # config.json if an empty value is really what you want.
        raise ValueError(
            f"Config file {config_path} refers to ${{{name}}} at '{where}', but "
            f"{name} is set to an empty string. Give it a value, or put a "
            f"literal \"\" in the config file if empty is intended."
        )
    return value


def _resolve_env(value: Any, *, where: str, config_path: Path) -> Any:
    """Walk the parsed config and substitute ${VAR} inside every string.

    Recurses through dicts and lists so any section added later gets this
    for free. Only values are touched, never keys - a computed key name
    would make the config unreadable for no benefit. Non-string scalars
    (ints, bools, null) pass through untouched.
    """
    if isinstance(value, dict):
        return {
            key: _resolve_env(item, where=f"{where}.{key}" if where else str(key), config_path=config_path)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [
            _resolve_env(item, where=f"{where}[{index}]", config_path=config_path)
            for index, item in enumerate(value)
        ]
    if isinstance(value, str):
        def substitute(match: re.Match[str]) -> str:
            if match.group(0) == "$$":
                return "$"
            return _resolve_placeholder(match.group(1), where=where, config_path=config_path)

        return _ENV_PLACEHOLDER.sub(substitute, value)
    return value


def load_config(config_path: Path) -> dict[str, Any]:
    """Read, parse, and resolve ${VAR} references. Raises on anything unusable."""
    if not config_path.exists():
        raise FileNotFoundError(
            f"Config file not found: {config_path}. Copy config.json.example "
            f"and point CONFIG_PATH at it."
        )
    try:
        with config_path.open(encoding="utf-8") as handle:
            data = json.load(handle)
    except json.JSONDecodeError as error:
        raise ValueError(f"Config file {config_path} is not valid JSON: {error}") from error

    if not isinstance(data, dict):
        raise ValueError(f"Config file {config_path} must contain a JSON object at the top level")
    return _resolve_env(data, where="", config_path=config_path)


def _require(section: dict[str, Any], key: str, *, section_name: str, config_path: Path) -> Any:
    if key not in section:
        raise KeyError(f"Config file {config_path} is missing '{section_name}.{key}'")
    return section[key]


def load_email_config(config_path: Path) -> EmailConfig:
    """Parse the "email" section into an EmailConfig.

    ``from`` is a Python keyword, so it can't be a dataclass field name -
    it's read from the JSON as ``from`` and exposed as ``from_address``.
    """
    config = load_config(config_path)
    section = config.get("email")
    if not isinstance(section, dict):
        raise KeyError(f"Config file {config_path} is missing an 'email' section")

    def required(key: str) -> Any:
        return _require(section, key, section_name="email", config_path=config_path)

    def as_address_list(value: Any) -> list[str]:
        # A bare string is the obvious thing to write for one recipient,
        # and iterating it character-by-character would be a nasty way to
        # find out otherwise.
        if isinstance(value, str):
            value = [value]
        return [str(address) for address in value]

    recipients = as_address_list(required("to"))
    approvers = as_address_list(section.get("approver_emails", recipients))

    return EmailConfig(
        smtp_server=str(required("smtp_server")),
        smtp_port=int(required("smtp_port")),
        from_address=str(required("from")),
        password=str(required("password")),
        to=recipients,
        approver_emails=approvers,
    )
