"""Loader for the JSON config file that holds per-deployment settings.

Two different kinds of configuration live in this project, deliberately
kept apart:

  - ``mcp_server/config.py`` - process settings read from environment
    variables (bind host/port, where this file lives). Small, flat,
    always present.
  - this file - structured, per-deployment data read from the JSON file
    at ``settings.config_path``: credentials, host inventories, SMTP
    details. Too nested and too secret to be comfortable as env vars.

Deliberately fails loudly. A missing file, unparseable JSON, or a missing
required key raises here, at load time, with a message naming the file and
the key - rather than returning ``{}`` and letting a capability fail much
later with a confusing ``KeyError`` deep inside domain logic.

Add a loader function per config section as capabilities need them,
following ``load_email_config`` below: read the section, validate what's
required, return a frozen dataclass. Domain code should take that
dataclass, never a raw dict - that way a typo in config.json is caught
here instead of at the call site.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class EmailConfig:
    smtp_server: str
    smtp_port: int
    from_address: str
    password: str
    to: list[str]


def load_config(config_path: Path) -> dict[str, Any]:
    """Read and parse the whole config file. Raises on anything unusable."""
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
    return data


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

    recipients = required("to")
    if isinstance(recipients, str):
        recipients = [recipients]

    return EmailConfig(
        smtp_server=str(required("smtp_server")),
        smtp_port=int(required("smtp_port")),
        from_address=str(required("from")),
        password=str(required("password")),
        to=[str(address) for address in recipients],
    )
