"""Server-wide settings.

Deliberately plain (no external settings library) - same convention as
mcp_server/src/config.py.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path


def _env(name: str, default: str) -> str:
    value = os.getenv(name)
    return value if value else default


@dataclass(frozen=True)
class Settings:
    host: str = _env("CATALOG_HOST", "127.0.0.1")
    port: int = int(_env("CATALOG_PORT", "8020"))
    configs_dir: Path = Path(_env("CATALOG_CONFIGS_DIR", "configs"))
    cache_path: Path = Path(_env("CATALOG_CACHE_PATH", "data/catalog_cache.json"))

    @property
    def sources_config_path(self) -> Path:
        return self.configs_dir / "config_sources.json"

    def sources(self) -> list[tuple[str, Path]]:
        """Reads configs/config_sources.json: a JSON array of
        {"project": <name>, "path": <path to that project's src/ dir>}."""
        raw = json.loads(self.sources_config_path.read_text(encoding="utf-8"))
        return [(entry["project"], Path(entry["path"])) for entry in raw]


settings = Settings()
