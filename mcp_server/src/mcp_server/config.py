"""Server-wide settings.

Deliberately plain (no external settings library required) - swap for
pydantic-settings later if the number of tunables grows.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    config_path: Path = Path(os.getenv("SAP_CONFIG_PATH", "config.json"))
    # Relative to CWD by default, matching config_path's same deliberate
    # fragility (see infra/sap_config.py's load_config docstring) - kept
    # consistent rather than fixed only here. Configurable so tests don't
    # need to write real files into the sandbox's CWD.
    maintenance_path: Path = Path(os.getenv("SAP_MAINTENANCE_PATH", "maintenance.json"))
    host: str = os.getenv("MCP_HOST", "0.0.0.0")
    port: int = int(os.getenv("MCP_PORT", "8010"))


settings = Settings()
