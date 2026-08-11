"""Typed configuration for SAP server connection details.

The legacy ``_load_config()`` returned a plain ``dict`` (or ``{}`` on any
error), so a typo'd key surfaced as a confusing failure three calls deep
inside a tool. A Pydantic model fails fast, at load time, with a message
that names the actual missing/invalid field.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel


class SapServerConfig(BaseModel):
    sid: str
    host: str
    user: str = "root"
    key: str | None = None
    password: str | None = None


class AppConfig(BaseModel):
    sap_server: list[SapServerConfig] = []


def load_config(path: Path) -> AppConfig:
    with path.open(encoding="utf-8-sig") as config_file:
        raw = json.load(config_file)
    return AppConfig.model_validate(raw)


def find_sap_server(sid: str, config: AppConfig) -> SapServerConfig | None:
    sid_upper = sid.upper()
    return next((server for server in config.sap_server if server.sid.upper() == sid_upper), None)
