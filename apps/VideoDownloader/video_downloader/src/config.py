"""video_downloader settings: configs/config_video_downloader.json (caps, TTLs) plus
the repo-root .env (host, ports, URLs, secrets). Real environment variables win over .env.
video_downloader_web reads the same .env, so each port is written once.

A missing real config or .env file is copied from its committed .example twin on first use.
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
CONFIG_FILE = "config_video_downloader.json"
MB = 1024 * 1024

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Limits:
    """Hard caps that keep one caller from exhausting disk, bandwidth or CPU."""

    max_file_bytes: int = 500 * MB
    max_duration_seconds: float = 2 * 3600
    max_session_bytes: int = 2048 * MB
    max_concurrent_downloads: int = 2
    max_queued_downloads: int = 8
    job_timeout_seconds: float = 30 * 60

    @classmethod
    def from_config(cls, raw: Mapping) -> Limits:
        default = cls()
        return cls(
            max_file_bytes=int(float(raw.get("max_file_mb", default.max_file_bytes / MB)) * MB),
            max_duration_seconds=float(raw.get("max_duration_minutes", default.max_duration_seconds / 60)) * 60,
            max_session_bytes=int(float(raw.get("max_session_mb", default.max_session_bytes / MB)) * MB),
            max_concurrent_downloads=int(raw.get("max_concurrent_downloads", default.max_concurrent_downloads)),
            max_queued_downloads=int(raw.get("max_queued_downloads", default.max_queued_downloads)),
            job_timeout_seconds=float(raw.get("job_timeout_minutes", default.job_timeout_seconds / 60)) * 60,
        )


@dataclass(frozen=True)
class Settings:
    """Everything the service needs at startup. Built once by load_settings()."""

    host: str = "127.0.0.1"
    port: int = 8050
    public_base_url: str = "http://127.0.0.1:8050"
    web_origin: str = "http://127.0.0.1:5175"
    store_dir: Path = PROJECT_DIR / ".data" / "store"
    log_dir: Path = PROJECT_DIR / ".logs"
    file_ttl_seconds: int = 6 * 3600
    sweep_interval_seconds: int = 600
    download_link_seconds: int = 3600
    internal_api_token: str = ""
    signing_key: bytes = b""
    limits: Limits = field(default_factory=Limits)


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

    port = int(env.get("VIDEO_DOWNLOADER_PORT") or 8050)
    web_port = int(env.get("VIDEO_DOWNLOADER_WEB_PORT") or 5175)
    signing_key = env.get("VIDEO_DOWNLOADER_SIGNING_KEY", "")
    if not signing_key:
        logger.warning("VIDEO_DOWNLOADER_SIGNING_KEY is not set; download links stop working after a restart.")
        signing_key = secrets.token_hex(32)

    return Settings(
        host=env.get("VIDEO_DOWNLOADER_HOST") or "127.0.0.1",
        port=port,
        public_base_url=(env.get("VIDEO_DOWNLOADER_PUBLIC_BASE_URL") or f"http://127.0.0.1:{port}").rstrip("/"),
        web_origin=env.get("VIDEO_DOWNLOADER_WEB_ORIGIN") or f"http://127.0.0.1:{web_port}",
        file_ttl_seconds=int(float(raw.get("file_ttl_hours", 6)) * 3600),
        sweep_interval_seconds=int(float(raw.get("sweep_interval_minutes", 10)) * 60),
        download_link_seconds=int(float(raw.get("download_link_minutes", 60)) * 60),
        internal_api_token=env.get("INTERNAL_API_TOKEN", ""),
        signing_key=signing_key.encode("utf-8"),
        limits=Limits.from_config(raw.get("limits", {})),
    )
