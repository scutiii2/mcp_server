"""pdf_merger settings: configs/config_pdf_merger.json (tuning) plus the repo-root
.env (host, ports, URLs, secrets). Real environment variables win over .env.
pdf_merger_web reads the same .env, so each port is written once.

A missing real config or .env file is copied from its committed
.example twin on first use (same behavior as ember_api's config_loader).
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import shutil
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import dotenv_values

PROJECT_DIR = Path(__file__).resolve().parent.parent
CONFIGS_DIR = PROJECT_DIR / "configs"
ENV_FILE = PROJECT_DIR.parent / ".env"
CONFIG_FILE = "config_pdf_merger.json"
MB = 1024 * 1024

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Limits:
    """Hard caps that keep one caller from exhausting disk, memory or CPU."""

    max_file_bytes: int = 100 * MB
    max_session_bytes: int = 500 * MB
    max_segments: int = 50
    max_output_pages: int = 2000
    max_image_pixels: int = 80_000_000
    max_concurrent_merges: int = 2
    job_timeout_seconds: float = 120.0

    @classmethod
    def from_config(cls, raw: Mapping) -> Limits:
        default = cls()
        return cls(
            max_file_bytes=int(float(raw.get("max_file_mb", default.max_file_bytes / MB)) * MB),
            max_session_bytes=int(float(raw.get("max_session_mb", default.max_session_bytes / MB)) * MB),
            max_segments=int(raw.get("max_segments", default.max_segments)),
            max_output_pages=int(raw.get("max_output_pages", default.max_output_pages)),
            max_image_pixels=int(float(raw.get("max_image_megapixels", default.max_image_pixels / 1e6)) * 1_000_000),
            max_concurrent_merges=int(raw.get("max_concurrent_merges", default.max_concurrent_merges)),
            job_timeout_seconds=float(raw.get("job_timeout_seconds", default.job_timeout_seconds)),
        )


@dataclass(frozen=True)
class Settings:
    """Everything the service needs at startup. Built once by load_settings()."""

    host: str = "127.0.0.1"
    port: int = 8040
    public_base_url: str = "http://127.0.0.1:8040"
    web_origin: str = "http://127.0.0.1:5174"
    store_dir: Path = PROJECT_DIR / ".data" / "store"
    log_dir: Path = PROJECT_DIR / ".logs"
    file_ttl_seconds: int = 6 * 3600
    sweep_interval_seconds: int = 600
    download_link_seconds: int = 3600
    internal_api_token: str = ""
    signing_key: bytes = b""
    limits: Limits = field(default_factory=Limits)
    mcp_wait_seconds: float = 100.0


def _ensure_from_example(path: Path) -> bool:
    """Copy ``<path>.example`` to ``path`` if needed; False if neither exists."""
    if path.exists():
        return True
    example = path.with_name(path.name + ".example")
    if not example.exists():
        return False
    shutil.copyfile(example, path)
    return True


def _read_json(path: Path) -> dict:
    if not _ensure_from_example(path):
        raise FileNotFoundError(f"Config file not found: {path}")
    return json.loads(path.read_text("utf-8"))


def _read_env_file(env_file: Path) -> dict[str, str]:
    """All KEY=value pairs from the .env file, copied from .env.example first."""
    if not _ensure_from_example(env_file):
        return {}
    return {k: v for k, v in dotenv_values(env_file).items() if v is not None}


def load_settings(
    configs_dir: Path = CONFIGS_DIR,
    env_file: Path = ENV_FILE,
    env: Mapping[str, str] | None = None,
) -> Settings:
    """Read config + .env; real environment variables win over .env."""
    env = {**_read_env_file(env_file), **(os.environ if env is None else env)}
    raw = _read_json(configs_dir / CONFIG_FILE)

    port = int(env.get("PDF_MERGER_PORT") or 8040)
    web_port = int(env.get("PDF_MERGER_WEB_PORT") or 5174)
    signing_key = env.get("PDF_MERGER_SIGNING_KEY", "")
    if not signing_key:
        logger.warning("PDF_MERGER_SIGNING_KEY is not set; download links stop working after a restart.")
        signing_key = secrets.token_hex(32)

    return Settings(
        host=env.get("PDF_MERGER_HOST") or "127.0.0.1",
        port=port,
        public_base_url=(env.get("PDF_MERGER_PUBLIC_BASE_URL") or f"http://127.0.0.1:{port}").rstrip("/"),
        web_origin=env.get("PDF_MERGER_WEB_ORIGIN") or f"http://127.0.0.1:{web_port}",
        file_ttl_seconds=int(float(raw.get("file_ttl_hours", 6)) * 3600),
        sweep_interval_seconds=int(float(raw.get("sweep_interval_minutes", 10)) * 60),
        download_link_seconds=int(float(raw.get("download_link_minutes", 60)) * 60),
        internal_api_token=env.get("INTERNAL_API_TOKEN", ""),
        signing_key=signing_key.encode("utf-8"),
        limits=Limits.from_config(raw.get("limits", {})),
        mcp_wait_seconds=float(raw.get("mcp_wait_seconds", 100)),
    )
