# Video Downloader Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `video_downloader`, a FastAPI service that probes and downloads videos or audio with yt-dlp into a session-scoped TTL store, with REST + SSE for the web app and MCP tools for mcp_server.

**Architecture:** One facade, `DownloadService`, composes a URL policy (SSRF guard), an extractor (yt-dlp wrapper behind a small protocol), a session-scoped file store with signed links, and a job queue with SSE events. REST routers and MCP tools only call the facade. The layout copies PDFMerger's `pdf_merger` pattern (no cross-project imports).

**Tech Stack:** Python 3.11+ (runs on 3.14), FastAPI, uvicorn, `mcp` (FastMCP), `yt-dlp[default]` (pinned), python-dotenv. Tests: pytest, pytest-asyncio, httpx2. System dependency: FFmpeg on PATH.

**Spec:** `docs/superpowers/specs/2026-10-06-video-downloader-design.md`. Plans 2 (web app) and 3 (mcp_server wiring, docs, vault) follow this one.

## Global Constraints

- Repo root: `D:\User\Documents\Programming\Python\VideoDownloader` (own git repo). Service folder: `video_downloader/`, Python package name `src` (as in pdf_merger). Run all service commands from `video_downloader/`.
- Venv: `.venv_video_downloader`. Test command: `.venv_video_downloader/Scripts/python -m pytest -q` (bash) .
- Port 8050 (`VIDEO_DOWNLOADER_PORT`), web origin port 5175 (`VIDEO_DOWNLOADER_WEB_PORT`). Settings come from repo-root `.env` (real env vars win) plus `video_downloader/configs/config_video_downloader.json`; missing real files are copied from their `.example` twins.
- Caps (defaults, spec): 500 MB per file, 2 h duration, 2 concurrent downloads, 2 GB per session, store TTL 6 h, signed link TTL 1 h.
- Never read or print real `.env` or `config_*.json` files; only `.example` twins.
- URL policy: http/https only; resolved addresses must all be public (reject private, loopback, link-local, CGNAT, reserved, multicast; IPv4-mapped IPv6 unwrapped).
- `noplaylist=True` always. No network access in tests except local 127.0.0.1 servers.
- MCP tools never block on a download. `/mcp` requires `X-Internal-Token`; an unset token refuses everything.
- Error codes (stable): `invalid_url`, `blocked_host`, `too_long`, `too_large`, `unsupported_site`, `login_required`, `drm_protected`, `ffmpeg_missing`, `queue_full`, `cancelled`, `timeout`, `extractor_failed`, plus `limit_exceeded`, `file_not_found`, `job_not_found`, `invalid_request`, `internal_error`. Raw yt-dlp text goes to logs only.
- Code style: type hints, short docstrings, `from __future__ import annotations`, async for I/O, blocking work through `asyncio.to_thread`.
- Commit messages end with the session's `Co-Authored-By` trailer.

## Spec deviations (intentional, update the spec in Task 1)

- The preset table lives in code (`src/extractor/presets.py`), not config (YAGNI; caps and TTLs stay in config).
- No separate `GET /api/files/{id}/link`: every `FileInfo` carries a fresh signed `download_url`.
- Signed download route is `GET /api/files/{id}/download?exp=&sig=` (same as pdf_merger).
- Extra error code `timeout` for jobs that exceed `job_timeout_minutes`.
- Redirect SSRF is handled by a `getaddrinfo` guard (Task 2), not only by the first-URL check.

## File Structure

```
VideoDownloader/
  .gitignore  .env.example  AGENTS.md  CLAUDE.md  README.md  _TODO.md
  video_downloader/
    pyproject.toml  run.bat  update.bat
    configs/config_video_downloader.json.example
    src/
      errors.py  config.py  logging_setup.py  system_info.py  run.py  app.py
      internal_token.py  models.py  service.py
      policy/{url_policy.py, socket_guard.py}
      store/{names.py, signing.py, file_store.py, sweeper.py}
      extractor/{models.py, presets.py, options.py, base.py, ytdlp.py}
      jobs/job_queue.py
      api/{deps.py, probe.py, downloads.py, files.py}
      mcp_tools/{contract.py, tools.py}
    tests/ (one test file per module + conftest.py)
```

---

### Task 1: Scaffold, config, errors

**Files:**
- Create: `.gitignore`, `.env.example`, `AGENTS.md`, `CLAUDE.md`, `README.md`, `_TODO.md`
- Create: `video_downloader/pyproject.toml`, `video_downloader/run.bat`, `video_downloader/update.bat`
- Create: `video_downloader/configs/config_video_downloader.json.example`
- Create: `video_downloader/src/__init__.py`, `src/errors.py`, `src/config.py`, `src/logging_setup.py`
- Create: `video_downloader/tests/__init__.py`, `tests/conftest.py`, `tests/test_errors.py`, `tests/test_config.py`
- Modify: `docs/superpowers/specs/2026-10-06-video-downloader-design.md` (deviation note)

**Interfaces:**
- Produces: `ErrorCode` (StrEnum), `DownloaderError(code, message)` with `.http_status`, `.to_body()`; `Limits`, `Settings`, `load_settings(configs_dir, env_file, env)`, `MB`, `PROJECT_DIR`; `configure_logging(log_dir)`; fixture `settings` in conftest.

- [ ] **Step 1: Write repo files**

`.gitignore`:
```
__pycache__/
*.pyc
.venv/
.venv_*/
*.egg-info/
.pytest_cache/
.vscode
*.zip
node_modules/
dist/

# Real config/secrets and runtime state. Only the .example twins are tracked.
config_*.json
/.env
/video_downloader/.data/
/video_downloader/.logs/

# Claude Code scratch.
.claude/*
!.claude/skills/
.worktrees/
.superpowers/
```

`.env.example`:
```
# Shared by video_downloader and video_downloader_web. Real environment variables win over this file.

# --- Network (written once; web_origin and the web proxy target derive from these) ---
VIDEO_DOWNLOADER_HOST=127.0.0.1
VIDEO_DOWNLOADER_PORT=8050
VIDEO_DOWNLOADER_WEB_PORT=5175
# Optional. LAN use: the address other machines reach this one at (also set VIDEO_DOWNLOADER_HOST to 0.0.0.0).
# Default http://127.0.0.1:<VIDEO_DOWNLOADER_PORT>.
# VIDEO_DOWNLOADER_PUBLIC_BASE_URL=
# Optional. Browser origin allowed by CORS. Default http://127.0.0.1:<VIDEO_DOWNLOADER_WEB_PORT>.
# VIDEO_DOWNLOADER_WEB_ORIGIN=
# Optional. Where video_downloader_web proxies /api. Default http://127.0.0.1:<VIDEO_DOWNLOADER_PORT>.
# VIDEO_DOWNLOADER_API_URL=

# --- Secrets ---
# Same value as INTERNAL_API_TOKEN in apps/mcp_server/.env.
# /mcp and token calls are refused until this is set.
INTERNAL_API_TOKEN=
# Random secret for signed download links, e.g. py -c "import secrets; print(secrets.token_hex(32))".
# Unset: a random key per process, so links stop working after a restart.
VIDEO_DOWNLOADER_SIGNING_KEY=
```

`AGENTS.md`:
```markdown
# VideoDownloader

Project note: `Brain/Projects/VideoDownloader.md` in the Obsidian vault (`../../Brain/` from this folder; component notes beside it: `video_downloader.md`, `video_downloader_web.md`).

## Agent instructions
This file is the one instruction file for every coding agent. Codex reads it directly; `CLAUDE.md` only imports it (`@AGENTS.md`) for Claude Code. Edit this file, never `CLAUDE.md`.

## Layout
- `video_downloader/` — FastAPI service (port 8050): yt-dlp wrapper, URL policy, TTL file store, jobs with SSE, REST API under `/api`, MCP tools at `/mcp`.
- `video_downloader_web/` — Vite + Vue 3 + TypeScript web app (port 5175) for video_downloader.
- `docs/superpowers/` — design spec and implementation plans.

## Rules
- Each folder is its own project with its own README, venv or node_modules. No imports from `Python/MCPServer` or `Python/PDFMerger` projects.
- `mcp_server` (in `Python/MCPServer`) reaches video_downloader as an HTTP extension: `mcp_server/configs/config_extensions.json` entry `video_downloader` with the internal token header and `forward_requester: true`. Start video_downloader before mcp_server.
- `server_launcher` finds these projects through its `data/extra_roots.json` (`../VideoDownloader`).
- Host, ports and URLs live once in the repo-root `.env` (`.env.example` is the twin); both projects read it. `video_downloader/configs/config_video_downloader.json` holds caps and TTLs only.
- FFmpeg must be on PATH; the service refuses to start without it.
- Never read or print real files `.env` or `config_*.json`; only `.example` twins.
- Download only content you have the right to download. DRM and login-only content are refused.
```

`CLAUDE.md`:
```
@AGENTS.md
```

`README.md`:
```markdown
# VideoDownloader

Download videos or audio from YouTube, TikTok and other sites supported by yt-dlp.

- `video_downloader/` — backend service (port 8050)
- `video_downloader_web/` — web app (port 5175)

Requirements: Python 3.11+, FFmpeg on PATH. Setup and run steps are in each folder's README.
```

`_TODO.md`:
```markdown
# _TODO.md

Deferred items — not scheduled, revisit when the trigger condition below is met.

## Video downloader: deferred features (added 2026-10-06)

- Playlists (many files per job), subtitles, cookies for login-only sites, download history.
- Ember persona in `Python/MCPServer/apps/ai_agent/agents/` (like pdf-assistant).
- Clip trimming.

**Revisit when**: the user asks for any of these.
```

`video_downloader/pyproject.toml`:
```toml
[project]
name = "video_downloader"
description = "Downloads videos and audio from public sites with yt-dlp. REST API for video_downloader_web, MCP endpoint for mcp_server."
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.115,<1.0",
    "uvicorn>=0.30,<1.0",
    "mcp>=1.28.0,<2.0.0",
    # Pinned: site extractors break often; update deliberately with update.bat.
    "yt-dlp[default]==2026.8.19",
    "python-dotenv>=1.0",
]

[project.optional-dependencies]
dev = ["pytest>=8.0", "pytest-asyncio>=0.24", "httpx2"]

[tool.setuptools.packages.find]
include = ["src*"]

[tool.pytest.ini_options]
pythonpath = ["."]
testpaths = ["tests"]
asyncio_mode = "auto"
asyncio_default_fixture_loop_scope = "function"
```

`video_downloader/run.bat`:
```bat
@echo off
REM video_downloader dev launcher. Creates .venv_video_downloader on first run and
REM installs this project into it in editable mode.
REM
REM LABEL: Video Downloader
REM DESCRIPTION: Downloads videos and audio with yt-dlp. REST API for video_downloader_web, MCP endpoint for mcp_server.
cd /d "%~dp0"

if not exist ".venv_video_downloader\Scripts\python.exe" (
    echo Creating virtual environment .venv_video_downloader ...
    py -m venv .venv_video_downloader
    call .venv_video_downloader\Scripts\activate
    echo Installing video_downloader in editable mode ...
    pip install -e ".[dev]"
) else (
    call .venv_video_downloader\Scripts\activate
)

:run
py -m src.run

echo.
echo ----------------------------------------
echo  video_downloader stopped.
choice /C RQ /N /M "Press [R] to restart, [Q] to quit: "
if errorlevel 2 goto :end
if errorlevel 1 goto :run

:end
```

`video_downloader/update.bat`:
```bat
@echo off
REM Upgrade yt-dlp inside the project venv (sites change often, old versions break).
cd /d "%~dp0"
if not exist ".venv_video_downloader\Scripts\python.exe" (
    echo Run run.bat once first to create the virtual environment.
    exit /b 1
)
call .venv_video_downloader\Scripts\activate
pip install -U "yt-dlp[default]"
pip show yt-dlp | findstr /B "Version"
echo Update the pin in pyproject.toml if you want this version to stick.
```

`video_downloader/configs/config_video_downloader.json.example`:
```json
{
  "file_ttl_hours": 6,
  "sweep_interval_minutes": 10,
  "download_link_minutes": 60,
  "limits": {
    "max_file_mb": 500,
    "max_duration_minutes": 120,
    "max_session_mb": 2048,
    "max_concurrent_downloads": 2,
    "max_queued_downloads": 8,
    "job_timeout_minutes": 30
  }
}
```

- [ ] **Step 2: Create the venv and install**

Run (from `video_downloader/`):
```bash
py -m venv .venv_video_downloader && .venv_video_downloader/Scripts/python -m pip install -e ".[dev]"
```
Expected: install succeeds (yt-dlp 2026.8.19). If a dependency has no wheel for the host Python, stop and report it.

- [ ] **Step 3: Write failing tests**

`tests/test_errors.py`:
```python
from __future__ import annotations

from src.errors import DownloaderError, ErrorCode


def test_to_body_has_code_and_message():
    error = DownloaderError(ErrorCode.TOO_LONG, "Too long.")
    assert error.to_body() == {"error": {"code": "too_long", "message": "Too long."}}


def test_http_status_for_every_code():
    for code in ErrorCode:
        assert 400 <= DownloaderError(code, "x").http_status <= 599


def test_specific_statuses():
    assert DownloaderError(ErrorCode.FILE_NOT_FOUND, "x").http_status == 404
    assert DownloaderError(ErrorCode.QUEUE_FULL, "x").http_status == 429
    assert DownloaderError(ErrorCode.BLOCKED_HOST, "x").http_status == 403
```

`tests/test_config.py`:
```python
from __future__ import annotations

import json
from pathlib import Path

from src.config import MB, load_settings


def _dirs(tmp_path: Path, raw: dict | None = None) -> tuple[Path, Path]:
    configs = tmp_path / "configs"
    configs.mkdir()
    (configs / "config_video_downloader.json").write_text(json.dumps(raw or {}), "utf-8")
    env_file = tmp_path / ".env"
    env_file.write_text("", "utf-8")
    return configs, env_file


def test_defaults(tmp_path):
    configs, env_file = _dirs(tmp_path)
    settings = load_settings(configs, env_file, env={})
    assert settings.port == 8050
    assert settings.public_base_url == "http://127.0.0.1:8050"
    assert settings.web_origin == "http://127.0.0.1:5175"
    assert settings.limits.max_file_bytes == 500 * MB
    assert settings.limits.max_duration_seconds == 7200
    assert settings.limits.max_session_bytes == 2048 * MB
    assert settings.limits.max_concurrent_downloads == 2
    assert settings.file_ttl_seconds == 6 * 3600
    assert settings.download_link_seconds == 3600
    assert settings.internal_api_token == ""
    assert len(settings.signing_key) > 0  # random per process when unset


def test_env_overrides(tmp_path):
    configs, env_file = _dirs(tmp_path)
    env = {
        "VIDEO_DOWNLOADER_PORT": "9000",
        "VIDEO_DOWNLOADER_WEB_PORT": "9001",
        "INTERNAL_API_TOKEN": "tok",
        "VIDEO_DOWNLOADER_SIGNING_KEY": "key",
        "VIDEO_DOWNLOADER_PUBLIC_BASE_URL": "http://10.0.0.5:9000/",
    }
    settings = load_settings(configs, env_file, env=env)
    assert settings.port == 9000
    assert settings.web_origin == "http://127.0.0.1:9001"
    assert settings.public_base_url == "http://10.0.0.5:9000"
    assert settings.internal_api_token == "tok"
    assert settings.signing_key == b"key"


def test_config_file_overrides_limits(tmp_path):
    configs, env_file = _dirs(tmp_path, {"file_ttl_hours": 1, "limits": {"max_file_mb": 10, "max_duration_minutes": 5, "job_timeout_minutes": 2}})
    settings = load_settings(configs, env_file, env={})
    assert settings.file_ttl_seconds == 3600
    assert settings.limits.max_file_bytes == 10 * MB
    assert settings.limits.max_duration_seconds == 300
    assert settings.limits.job_timeout_seconds == 120


def test_missing_config_is_copied_from_example(tmp_path):
    configs = tmp_path / "configs"
    configs.mkdir()
    (configs / "config_video_downloader.json.example").write_text("{}", "utf-8")
    env_file = tmp_path / ".env"
    (tmp_path / ".env.example").write_text("VIDEO_DOWNLOADER_PORT=8123\n", "utf-8")
    settings = load_settings(configs, env_file, env=None)
    assert (configs / "config_video_downloader.json").exists()
    assert env_file.exists()
    assert settings.port in (8123, 8050)  # real os.environ may override
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `.venv_video_downloader/Scripts/python -m pytest -q`
Expected: collection ERROR (`No module named 'src.errors'` / `src.config`).

- [ ] **Step 5: Implement**

`src/__init__.py`, `tests/__init__.py`: empty files.

`src/errors.py`:
```python
"""Every failure a caller can see, as a code plus a plain-language message.

Routers turn DownloaderError into an HTTP error body; MCP tools turn it into a
ToolError. Anything else that escapes is logged and reported as
internal_error, so raw exception text never reaches a caller.
"""

from __future__ import annotations

from enum import StrEnum


class ErrorCode(StrEnum):
    INVALID_URL = "invalid_url"
    BLOCKED_HOST = "blocked_host"
    TOO_LONG = "too_long"
    TOO_LARGE = "too_large"
    UNSUPPORTED_SITE = "unsupported_site"
    LOGIN_REQUIRED = "login_required"
    DRM_PROTECTED = "drm_protected"
    FFMPEG_MISSING = "ffmpeg_missing"
    QUEUE_FULL = "queue_full"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"
    EXTRACTOR_FAILED = "extractor_failed"
    LIMIT_EXCEEDED = "limit_exceeded"
    FILE_NOT_FOUND = "file_not_found"
    JOB_NOT_FOUND = "job_not_found"
    INVALID_REQUEST = "invalid_request"
    INTERNAL = "internal_error"


_HTTP_STATUS: dict[ErrorCode, int] = {
    ErrorCode.INVALID_URL: 422,
    ErrorCode.BLOCKED_HOST: 403,
    ErrorCode.TOO_LONG: 413,
    ErrorCode.TOO_LARGE: 413,
    ErrorCode.UNSUPPORTED_SITE: 422,
    ErrorCode.LOGIN_REQUIRED: 422,
    ErrorCode.DRM_PROTECTED: 422,
    ErrorCode.FFMPEG_MISSING: 503,
    ErrorCode.QUEUE_FULL: 429,
    ErrorCode.CANCELLED: 409,
    ErrorCode.TIMEOUT: 504,
    ErrorCode.EXTRACTOR_FAILED: 502,
    ErrorCode.LIMIT_EXCEEDED: 413,
    ErrorCode.FILE_NOT_FOUND: 404,
    ErrorCode.JOB_NOT_FOUND: 404,
    ErrorCode.INVALID_REQUEST: 422,
    ErrorCode.INTERNAL: 500,
}


class DownloaderError(Exception):
    """An expected failure with a stable code and a message safe to show users."""

    def __init__(self, code: ErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    @property
    def http_status(self) -> int:
        return _HTTP_STATUS[self.code]

    def to_body(self) -> dict:
        return {"error": {"code": str(self.code), "message": self.message}}
```

`src/logging_setup.py`:
```python
"""One-time logging wiring: rotating .logs/server.log (5 MB x 3) plus stderr."""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def configure_logging(log_dir: Path) -> None:
    """Attach handlers to the root logger. Call once, from run.py only."""
    log_dir.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    file_handler = RotatingFileHandler(log_dir / "server.log", maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
    stream_handler = logging.StreamHandler(sys.stderr)
    for handler in (file_handler, stream_handler):
        handler.setFormatter(logging.Formatter(_FORMAT))
        root.addHandler(handler)
```

`src/config.py`:
```python
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
```

`tests/conftest.py`:
```python
"""Shared fixtures. Later tasks add fixtures to this file."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.config import Settings

TEST_TOKEN = "test-token"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Settings that keep every file under tmp_path."""
    return Settings(
        store_dir=tmp_path / "store",
        log_dir=tmp_path / "logs",
        internal_api_token=TEST_TOKEN,
        signing_key=b"s" * 32,
    )
```

Edit the spec: in the "Config" section replace the "caps, preset table, link TTL" wording with "caps, TTLs, link TTL (the preset table lives in code)", and add a "Plan deviations" line listing the five deviations above.

- [ ] **Step 6: Run tests**

Run: `.venv_video_downloader/Scripts/python -m pytest -q`
Expected: all pass (about 7 tests).

- [ ] **Step 7: Commit**

```bash
git add -A && git commit -m "feat: scaffold video_downloader with config and error codes"
```

---

### Task 2: URL policy and socket guard (redirect SSRF spike)

**Files:**
- Create: `video_downloader/src/policy/__init__.py` (empty), `src/policy/url_policy.py`, `src/policy/socket_guard.py`
- Test: `video_downloader/tests/test_url_policy.py`, `tests/test_socket_guard.py`

**Interfaces:**
- Consumes: `DownloaderError`, `ErrorCode` (Task 1).
- Produces:
  - `is_public_ip(ip: str) -> bool`
  - `Resolver = Callable[[str], Awaitable[list[str]]]`
  - `UrlPolicy(resolver: Resolver | None = None)` with `async check(url: str) -> str` (returns trimmed URL or raises `DownloaderError`).
  - `BlockedAddressError(OSError)`; `SocketGuard(allow: Callable[[str, int | None], bool] = default)` with `install()`, `uninstall()`, `active()` context manager, `blocked` property; module singleton `GUARD`.

- [ ] **Step 1: Write failing policy tests**

`tests/test_url_policy.py`:
```python
from __future__ import annotations

import socket

import pytest

from src.errors import DownloaderError, ErrorCode
from src.policy.url_policy import UrlPolicy, is_public_ip


@pytest.mark.parametrize("ip", ["8.8.8.8", "93.184.216.34", "2606:4700:4700::1111"])
def test_public_addresses(ip):
    assert is_public_ip(ip)


@pytest.mark.parametrize(
    "ip",
    ["127.0.0.1", "10.0.0.1", "172.16.5.4", "192.168.1.1", "169.254.169.254", "100.64.0.1", "0.0.0.0",
     "224.0.0.1", "::1", "fe80::1", "fc00::1", "::ffff:127.0.0.1", "::ffff:10.0.0.1"],
)
def test_non_public_addresses(ip):
    assert not is_public_ip(ip)


def resolver_for(mapping: dict[str, list[str]]):
    async def resolve(host: str) -> list[str]:
        if host not in mapping:
            raise socket.gaierror("not found")
        return mapping[host]

    return resolve


@pytest.fixture
def policy():
    return UrlPolicy(resolver_for({
        "example.com": ["93.184.216.34"],
        "evil.example": ["10.0.0.5"],
        "mixed.example": ["93.184.216.34", "127.0.0.1"],
    }))


async def test_accepts_public_https_and_trims(policy):
    assert await policy.check("  https://example.com/watch?v=1  ") == "https://example.com/watch?v=1"


@pytest.mark.parametrize("url", ["", "not a url", "ftp://example.com/x", "file:///etc/passwd", "javascript:alert(1)",
                                 "https://", "https://user:pw@example.com/", "https://" + "a" * 3000 + ".com"])
async def test_rejects_bad_shapes(policy, url):
    with pytest.raises(DownloaderError) as error:
        await policy.check(url)
    assert error.value.code == ErrorCode.INVALID_URL


@pytest.mark.parametrize("url", [
    "http://127.0.0.1/x", "http://[::1]/x", "http://192.168.1.10/x", "http://evil.example/x",
    "http://mixed.example/x", "https://example.com:8080/x", "http://169.254.169.254/latest/meta-data",
])
async def test_blocks_private_hosts_and_odd_ports(policy, url):
    with pytest.raises(DownloaderError) as error:
        await policy.check(url)
    assert error.value.code == ErrorCode.BLOCKED_HOST


async def test_unknown_host_is_invalid_url(policy):
    with pytest.raises(DownloaderError) as error:
        await policy.check("https://nope.example/x")
    assert error.value.code == ErrorCode.INVALID_URL


async def test_allows_port_443_and_80(policy):
    assert await policy.check("https://example.com:443/x")
    assert await policy.check("http://example.com:80/x")
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv_video_downloader/Scripts/python -m pytest tests/test_url_policy.py -q`
Expected: ERROR `No module named 'src.policy'`.

- [ ] **Step 3: Implement `src/policy/url_policy.py`**

```python
"""Which URLs the service may fetch: public http(s) hosts only.

yt-dlp fetches whatever it is given, and an LLM agent can call the MCP tool,
so private and loopback targets must be refused (SSRF). The host is resolved
here and every resulting address must be public. Redirects and DNS answers
that change later are covered by socket_guard.py.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import Awaitable, Callable
from urllib.parse import urlsplit

from src.errors import DownloaderError, ErrorCode

Resolver = Callable[[str], Awaitable[list[str]]]

MAX_URL_LENGTH = 2048
ALLOWED_PORTS = (None, 80, 443)


def is_public_ip(ip: str) -> bool:
    """True only for globally routable unicast addresses (IPv4-mapped IPv6 is unwrapped)."""
    try:
        address = ipaddress.ip_address(ip.split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    return address.is_global and not address.is_multicast


async def system_resolver(host: str) -> list[str]:
    """Resolve through the event loop's executor, without blocking it."""
    infos = await asyncio.get_running_loop().getaddrinfo(host, None, type=socket.SOCK_STREAM)
    return [str(info[4][0]) for info in infos]


class UrlPolicy:
    """Validates a user-supplied URL before any network fetch."""

    def __init__(self, resolver: Resolver | None = None) -> None:
        self._resolver = resolver or system_resolver

    async def check(self, url: str) -> str:
        """Return the trimmed URL, or raise DownloaderError (invalid_url / blocked_host)."""
        url = (url or "").strip()
        if not url or len(url) > MAX_URL_LENGTH:
            raise DownloaderError(ErrorCode.INVALID_URL, "That doesn't look like a valid link.")
        try:
            parts = urlsplit(url)
            port = parts.port
        except ValueError:
            raise DownloaderError(ErrorCode.INVALID_URL, "That doesn't look like a valid link.") from None
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise DownloaderError(ErrorCode.INVALID_URL, "Paste a full link that starts with http:// or https://.")
        if parts.username or parts.password:
            raise DownloaderError(ErrorCode.INVALID_URL, "Links with a user name or password are not supported.")
        if port not in ALLOWED_PORTS:
            raise DownloaderError(ErrorCode.BLOCKED_HOST, "Only standard web ports (80 and 443) are allowed.")

        host = parts.hostname
        try:
            ipaddress.ip_address(host)
            addresses = [host]
        except ValueError:
            try:
                addresses = await self._resolver(host)
            except OSError:
                raise DownloaderError(ErrorCode.INVALID_URL, "That web address could not be found.") from None
        if not addresses or not all(is_public_ip(a) for a in addresses):
            raise DownloaderError(ErrorCode.BLOCKED_HOST, "That address is not a public website, so it can't be downloaded.")
        return url
```

- [ ] **Step 4: Run policy tests**

Run: `.venv_video_downloader/Scripts/python -m pytest tests/test_url_policy.py -q`
Expected: PASS.

- [ ] **Step 5: Write failing socket guard tests**

`tests/test_socket_guard.py`:
```python
from __future__ import annotations

import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from yt_dlp import YoutubeDL

from src.policy.socket_guard import BlockedAddressError, SocketGuard


class _Server:
    """A tiny local HTTP server that records requests; optionally redirects."""

    def __init__(self, redirect_to: str | None = None) -> None:
        self.hits: list[str] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                outer.hits.append(self.path)
                if redirect_to:
                    self.send_response(302)
                    self.send_header("Location", redirect_to)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                else:
                    body = b"ok"
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)

            def log_message(self, *args):
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def guard():
    created: list[SocketGuard] = []

    def make(allow):
        g = SocketGuard(allow=allow)
        g.install()
        created.append(g)
        return g

    yield make
    for g in reversed(created):
        g.uninstall()


def test_install_and_uninstall_restore_getaddrinfo(guard):
    original = socket.getaddrinfo
    g = guard(lambda ip, port: True)
    assert socket.getaddrinfo is not original
    g.uninstall()
    assert socket.getaddrinfo is original


def test_inactive_guard_lets_everything_through(guard):
    guard(lambda ip, port: False)
    assert socket.getaddrinfo("127.0.0.1", 80)  # not inside active(): untouched


def test_active_guard_blocks_disallowed_address(guard):
    g = guard(lambda ip, port: False)
    with g.active():
        with pytest.raises(BlockedAddressError):
            socket.getaddrinfo("127.0.0.1", 80)
        assert g.blocked
    with g.active():
        assert not g.blocked  # flag resets on a fresh outermost entry


def test_yt_dlp_redirect_to_blocked_target_is_stopped(guard):
    """The first hop is allowed, the redirect target is not: its server must never be hit."""
    target = _Server()
    first = _Server(redirect_to=f"http://127.0.0.1:{target.port}/secret")
    try:
        g = guard(lambda ip, port: port == first.port)
        with YoutubeDL({"quiet": True, "no_warnings": True}) as ydl, g.active():
            with pytest.raises(Exception):
                ydl.urlopen(f"http://127.0.0.1:{first.port}/start").read()
            assert g.blocked
        assert first.hits == ["/start"]
        assert target.hits == []
    finally:
        first.close()
        target.close()
```

- [ ] **Step 6: Run to verify failure**

Run: `.venv_video_downloader/Scripts/python -m pytest tests/test_socket_guard.py -q`
Expected: ERROR `No module named 'src.policy.socket_guard'`.

- [ ] **Step 7: Implement `src/policy/socket_guard.py`**

```python
"""Block connections to non-public addresses, including redirect targets.

yt-dlp follows HTTP redirects inside its own HTTP handler, so a URL that passed
UrlPolicy could still redirect to http://127.0.0.1/... The guard wraps
socket.getaddrinfo, which every outgoing connection goes through (urllib,
urllib3, http.client), and refuses disallowed answers while a thread is inside
``active()``. It also closes DNS-rebinding gaps, because the checked answer is
the one the connection uses. Threads outside ``active()`` (uvicorn, the event
loop's resolver) are untouched.

Known gap: when yt-dlp hands a stream to ffmpeg to fetch directly, ffmpeg's own
sockets are not guarded. Native HLS is preferred in ytdlp.py to keep this rare.
"""

from __future__ import annotations

import socket
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager

from src.policy.url_policy import is_public_ip

AllowFn = Callable[[str, int | None], bool]


class BlockedAddressError(OSError):
    """Raised instead of connecting to a non-public address."""


def _allow_public(ip: str, port: int | None) -> bool:
    return is_public_ip(ip)


def _as_port(port: object) -> int | None:
    try:
        return int(port)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


class SocketGuard:
    def __init__(self, allow: AllowFn = _allow_public) -> None:
        self._allow = allow
        self._local = threading.local()
        self._original: Callable | None = None

    def install(self) -> None:
        """Replace socket.getaddrinfo with the guarded wrapper (idempotent)."""
        if self._original is None:
            self._original = socket.getaddrinfo
            socket.getaddrinfo = self._getaddrinfo

    def uninstall(self) -> None:
        if self._original is not None:
            socket.getaddrinfo = self._original
            self._original = None

    @contextmanager
    def active(self) -> Iterator[None]:
        """Guard every lookup made by this thread inside the block."""
        depth = getattr(self._local, "depth", 0)
        if depth == 0:
            self._local.blocked = False
        self._local.depth = depth + 1
        try:
            yield
        finally:
            self._local.depth -= 1

    @property
    def blocked(self) -> bool:
        """True if this thread's current ``active()`` block hit a blocked address."""
        return bool(getattr(self._local, "blocked", False))

    def _getaddrinfo(self, host, port, *args, **kwargs):
        assert self._original is not None
        results = self._original(host, port, *args, **kwargs)
        if getattr(self._local, "depth", 0) > 0:
            number = _as_port(port)
            for _family, _type, _proto, _canon, sockaddr in results:
                if not self._allow(str(sockaddr[0]), number):
                    self._local.blocked = True
                    raise BlockedAddressError("Connection to a non-public address was blocked.")
        return results


GUARD = SocketGuard()
```

- [ ] **Step 8: Run guard tests**

Run: `.venv_video_downloader/Scripts/python -m pytest tests/test_socket_guard.py -q`
Expected: PASS. If `test_yt_dlp_redirect_to_blocked_target_is_stopped` fails because yt-dlp resolves hosts in a way the wrapper misses (for example a handler that calls `_socket.getaddrinfo` directly), STOP and report; the spec's fallback is documenting the gap and re-checking the resolved `webpage_url`.

- [ ] **Step 9: Commit**

```bash
git add -A && git commit -m "feat(policy): URL policy and getaddrinfo guard against private targets and redirects"
```

---

### Task 3: File store, signing, sweeper

**Files:**
- Create: `src/store/__init__.py` (empty), `src/store/names.py`, `src/store/signing.py`, `src/store/file_store.py`, `src/store/sweeper.py`
- Test: `tests/test_names.py`, `tests/test_signing.py`, `tests/test_file_store.py`, `tests/test_sweeper.py`

**Interfaces:**
- Consumes: `DownloaderError`, `ErrorCode`, `MB` (config).
- Produces:
  - `safe_filename(name: str | None, default: str) -> str`, `content_disposition(name: str, *, inline: bool = False) -> str`, `mime_for(suffix: str) -> str`
  - `LinkSigner(key: bytes, ttl_seconds: int, clock=time.time)` with `sign(file_id) -> tuple[int, str]`, `verify(file_id, exp, sig) -> bool`
  - `StoredFile` dataclass: `file_id, session, name, mime, kind, size, duration, created_at, expires_at`
  - `FileStore(root: Path, *, ttl_seconds, max_file_bytes, max_session_bytes, clock=time.time)` with `async load_index() -> int`, `async make_work_dir() -> Path`, `async remove_work_dir(path)`, `async commit_file(session, source: Path, *, name, mime, kind, duration) -> StoredFile`, `get(file_id, session|None) -> StoredFile`, `list(session) -> list[StoredFile]`, `session_usage(session) -> int`, `path(file) -> Path`, `async delete(file_id, session|None)`, `async sweep() -> int`
  - `run_sweeper(service, interval_seconds, stop: asyncio.Event)`

- [ ] **Step 1: Write failing tests**

`tests/test_names.py`:
```python
from src.store.names import content_disposition, mime_for, safe_filename


def test_safe_filename_strips_paths_and_unsafe_chars():
    assert safe_filename("../../etc/pa:ss*wd.mp4", "video") == "pa_ss_wd.mp4"
    assert safe_filename("", "video") == "video"
    assert safe_filename(None, "video") == "video"
    assert safe_filename("a" * 400 + ".mp4", "video") == "a" * 150


def test_content_disposition_has_ascii_fallback_and_utf8_name():
    header = content_disposition("café.mp4")
    assert header.startswith("attachment;")
    assert 'filename="caf.mp4"' in header
    assert "filename*=UTF-8''caf%C3%A9.mp4" in header
    assert content_disposition("a.mp4", inline=True).startswith("inline;")


def test_mime_for():
    assert mime_for(".mp4") == "video/mp4"
    assert mime_for(".MP3") == "audio/mpeg"
    assert mime_for(".m4a") == "audio/mp4"
    assert mime_for(".webm") == "video/webm"
    assert mime_for(".xyz") == "application/octet-stream"
```

`tests/test_signing.py`:
```python
from src.store.signing import LinkSigner


def test_sign_and_verify_roundtrip():
    now = [1000.0]
    signer = LinkSigner(b"k" * 32, 3600, clock=lambda: now[0])
    exp, sig = signer.sign("f_1")
    assert exp == 4600
    assert signer.verify("f_1", exp, sig)


def test_rejects_other_file_tampered_sig_and_expiry():
    now = [1000.0]
    signer = LinkSigner(b"k" * 32, 60, clock=lambda: now[0])
    exp, sig = signer.sign("f_1")
    assert not signer.verify("f_2", exp, sig)
    assert not signer.verify("f_1", exp, sig[:-1] + ("0" if sig[-1] != "0" else "1"))
    assert not signer.verify("f_1", exp + 1, sig)
    now[0] = exp + 1
    assert not signer.verify("f_1", exp, sig)
```

`tests/test_file_store.py`:
```python
from __future__ import annotations

from pathlib import Path

import pytest

from src.errors import DownloaderError, ErrorCode
from src.store.file_store import FileStore

MB = 1024 * 1024


def make_store(tmp_path: Path, clock, *, max_file=10 * MB, max_session=20 * MB, ttl=3600) -> FileStore:
    return FileStore(tmp_path / "store", ttl_seconds=ttl, max_file_bytes=max_file, max_session_bytes=max_session, clock=clock)


async def make_source(store: FileStore, size: int = 100, name: str = "v.mp4") -> Path:
    work = await store.make_work_dir()
    source = work / name
    source.write_bytes(b"x" * size)
    return source


async def test_commit_then_get_and_list(tmp_path):
    now = [1000.0]
    store = make_store(tmp_path, lambda: now[0])
    stored = await store.commit_file("web:a", await make_source(store), name="Cat.mp4", mime="video/mp4", kind="video", duration=12.5)

    assert stored.size == 100 and stored.expires_at == 4600
    assert store.path(stored).read_bytes() == b"x" * 100
    assert store.get(stored.file_id, "web:a") == stored
    assert [f.file_id for f in store.list("web:a")] == [stored.file_id]
    assert store.list("web:b") == []


async def test_other_session_cannot_get_but_privileged_can(tmp_path):
    store = make_store(tmp_path, lambda: 1000.0)
    stored = await store.commit_file("web:a", await make_source(store), name="a.mp4", mime="video/mp4", kind="video", duration=None)
    with pytest.raises(DownloaderError) as error:
        store.get(stored.file_id, "web:b")
    assert error.value.code == ErrorCode.FILE_NOT_FOUND
    assert store.get(stored.file_id, None).file_id == stored.file_id


async def test_expired_file_is_hidden_and_swept(tmp_path):
    now = [1000.0]
    store = make_store(tmp_path, lambda: now[0], ttl=60)
    stored = await store.commit_file("web:a", await make_source(store), name="a.mp4", mime="video/mp4", kind="video", duration=None)
    now[0] = 2000.0
    with pytest.raises(DownloaderError):
        store.get(stored.file_id, "web:a")
    assert store.list("web:a") == []
    assert await store.sweep() == 1
    assert not store.path(stored).exists()


async def test_session_quota_enforced_and_source_removed(tmp_path):
    store = make_store(tmp_path, lambda: 1000.0, max_session=150)
    await store.commit_file("web:a", await make_source(store, 100), name="a.mp4", mime="video/mp4", kind="video", duration=None)
    source = await make_source(store, 100, "b.mp4")
    with pytest.raises(DownloaderError) as error:
        await store.commit_file("web:a", source, name="b.mp4", mime="video/mp4", kind="video", duration=None)
    assert error.value.code == ErrorCode.LIMIT_EXCEEDED
    assert not source.exists()


async def test_file_cap_enforced(tmp_path):
    store = make_store(tmp_path, lambda: 1000.0, max_file=50)
    source = await make_source(store, 100)
    with pytest.raises(DownloaderError) as error:
        await store.commit_file("web:a", source, name="a.mp4", mime="video/mp4", kind="video", duration=None)
    assert error.value.code == ErrorCode.TOO_LARGE
    assert not source.exists()


async def test_delete_removes_file_and_sidecar(tmp_path):
    store = make_store(tmp_path, lambda: 1000.0)
    stored = await store.commit_file("web:a", await make_source(store), name="a.mp4", mime="video/mp4", kind="video", duration=None)
    await store.delete(stored.file_id, "web:a")
    assert not store.path(stored).exists()
    with pytest.raises(DownloaderError):
        store.get(stored.file_id, "web:a")


async def test_index_rebuilt_after_restart_and_stale_files_cleaned(tmp_path):
    clock = lambda: 1000.0
    store = make_store(tmp_path, clock)
    stored = await store.commit_file("web:a", await make_source(store), name="a.mp4", mime="video/mp4", kind="video", duration=3.0)
    orphan = store.path(stored).parent / ("f_" + "0" * 32)
    orphan.write_bytes(b"orphan")  # data file without a sidecar
    leftover = await store.make_work_dir()
    (leftover / "half.part").write_bytes(b"half")

    fresh = make_store(tmp_path, clock)
    assert await fresh.load_index() == 1
    assert fresh.get(stored.file_id, "web:a").duration == 3.0
    assert not orphan.exists()
    assert not leftover.exists()


async def test_session_names_never_become_paths(tmp_path):
    store = make_store(tmp_path, lambda: 1000.0)
    stored = await store.commit_file("mcp:../../evil", await make_source(store), name="a.mp4", mime="video/mp4", kind="video", duration=None)
    assert (tmp_path / "store") in store.path(stored).parents
```

`tests/test_sweeper.py`:
```python
import asyncio

from src.store.sweeper import run_sweeper


class FakeService:
    def __init__(self):
        self.calls = 0

    async def sweep(self) -> int:
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("boom")  # must not stop the loop
        return 0


async def test_sweeper_runs_repeatedly_and_survives_errors():
    service = FakeService()
    stop = asyncio.Event()
    task = asyncio.create_task(run_sweeper(service, 0.01, stop))
    await asyncio.sleep(0.1)
    stop.set()
    await task
    assert service.calls >= 2
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv_video_downloader/Scripts/python -m pytest tests/test_names.py tests/test_signing.py tests/test_file_store.py tests/test_sweeper.py -q`
Expected: ERROR `No module named 'src.store'`.

- [ ] **Step 3: Implement**

`src/store/names.py`:
```python
"""Titles from websites are metadata only. These helpers make them safe to store and to send back in headers."""

from __future__ import annotations

import re
from urllib.parse import quote

_UNSAFE = re.compile(r"[^\w.\- ()]+")
_MAX_LENGTH = 150
_MIME = {
    ".mp4": "video/mp4",
    ".webm": "video/webm",
    ".mkv": "video/x-matroska",
    ".mov": "video/quicktime",
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".opus": "audio/ogg",
    ".ogg": "audio/ogg",
}


def safe_filename(name: str | None, default: str) -> str:
    """Last path component with unsafe characters collapsed to "_"; ``default`` if nothing is left."""
    base = (name or "").replace("\\", "/").rsplit("/", 1)[-1]
    base = _UNSAFE.sub("_", base).strip(" .")[:_MAX_LENGTH]
    return base or default


def mime_for(suffix: str) -> str:
    return _MIME.get(suffix.lower(), "application/octet-stream")


def content_disposition(name: str, *, inline: bool = False) -> str:
    """RFC 6266 header with an ASCII fallback and the exact UTF-8 name."""
    ascii_name = name.encode("ascii", "ignore").decode("ascii").replace('"', "") or "file"
    kind = "inline" if inline else "attachment"
    return f"{kind}; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(name)}"
```

`src/store/signing.py`:
```python
"""HMAC-signed, expiring download links. A link works without a cookie, so
Ember's download cards and other machines can open it, but only until it expires."""

from __future__ import annotations

import hashlib
import hmac
import time
from collections.abc import Callable


class LinkSigner:
    def __init__(self, key: bytes, ttl_seconds: int, clock: Callable[[], float] = time.time) -> None:
        self._key = key
        self._ttl = ttl_seconds
        self._clock = clock

    def _digest(self, file_id: str, exp: int) -> str:
        return hmac.new(self._key, f"{file_id}.{exp}".encode("utf-8"), hashlib.sha256).hexdigest()

    def sign(self, file_id: str) -> tuple[int, str]:
        """(expiry as unix seconds, hex signature)."""
        exp = int(self._clock() + self._ttl)
        return exp, self._digest(file_id, exp)

    def verify(self, file_id: str, exp: int, sig: str) -> bool:
        if exp < self._clock():
            return False
        return hmac.compare_digest(
            self._digest(file_id, exp).encode("ascii"),
            sig.encode("utf-8", "replace"),
        )
```

`src/store/sweeper.py`:
```python
"""Background task that deletes expired files on a fixed interval."""

from __future__ import annotations

import asyncio
import logging
from typing import Protocol

logger = logging.getLogger(__name__)


class Sweepable(Protocol):
    async def sweep(self) -> int: ...


async def run_sweeper(service: Sweepable, interval_seconds: float, stop: asyncio.Event) -> None:
    """Sweep, then sleep until the interval passes or ``stop`` is set. Errors are logged, never fatal."""
    while not stop.is_set():
        try:
            removed = await service.sweep()
            if removed:
                logger.info("Swept %d expired file(s)", removed)
        except Exception:
            logger.exception("Sweep failed")
        try:
            await asyncio.wait_for(stop.wait(), interval_seconds)
        except TimeoutError:
            pass
```

`src/store/file_store.py`:
```python
"""Session-scoped files on disk with an in-memory index.

Layout: <root>/<sha256(session)[:32]>/<file_id> plus a <file_id>.json sidecar
holding the StoredFile record, so the index can be rebuilt after a restart.
Session strings are hashed so "mcp:alice" or anything a caller sends can never
become a raw path. The video title is metadata only.

Downloads happen in scratch directories under <root>/_work (same volume as the
store, so commit_file can move a finished file with an atomic rename).

One instance per process. Index mutations happen on the event loop thread; disk
I/O goes through asyncio.to_thread so the loop never blocks.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import secrets
import shutil
import tempfile
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

from src.config import MB
from src.errors import DownloaderError, ErrorCode

logger = logging.getLogger(__name__)

_WORK_DIR_NAME = "_work"
_DATA_NAME_RE = re.compile(r"f_[0-9a-f]{32}")


@dataclass(frozen=True)
class StoredFile:
    """One committed file. ``kind`` is "video" or "audio"."""

    file_id: str
    session: str
    name: str
    mime: str
    kind: str
    size: int
    duration: float | None
    created_at: float
    expires_at: float


def new_file_id() -> str:
    return "f_" + secrets.token_hex(16)


class FileStore:
    def __init__(
        self,
        root: Path,
        *,
        ttl_seconds: int,
        max_file_bytes: int,
        max_session_bytes: int,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._root = root
        self._ttl = ttl_seconds
        self._max_file_bytes = max_file_bytes
        self._max_session_bytes = max_session_bytes
        self._clock = clock
        self._index: dict[str, StoredFile] = {}
        self._reserved: dict[str, int] = {}

    # --- paths -------------------------------------------------------------

    def _session_dir(self, session: str) -> Path:
        return self._root / hashlib.sha256(session.encode("utf-8")).hexdigest()[:32]

    def path(self, file: StoredFile) -> Path:
        return self._session_dir(file.session) / file.file_id

    def _meta_path(self, file: StoredFile) -> Path:
        return self._session_dir(file.session) / f"{file.file_id}.json"

    # --- startup -----------------------------------------------------------

    async def load_index(self) -> int:
        """Rebuild the index from sidecars and clean crash leftovers. Returns the number of files loaded."""

        def scan() -> list[StoredFile]:
            self._root.mkdir(parents=True, exist_ok=True)
            found: list[StoredFile] = []
            for meta in self._root.glob("*/f_*.json"):
                try:
                    found.append(StoredFile(**json.loads(meta.read_text("utf-8"))))
                except (OSError, ValueError, TypeError):
                    logger.warning("Skipping unreadable sidecar %s", meta)
            self._clean_stale(found)
            return found

        for file in await asyncio.to_thread(scan):
            self._index[file.file_id] = file
        return len(self._index)

    def _clean_stale(self, found: list[StoredFile]) -> None:
        """Delete data files without a sidecar and every scratch directory (no job survives a restart)."""
        known = {file.file_id for file in found}
        for path in self._root.glob("*/f_*"):
            if path.name.endswith(".json") or path.parent.name == _WORK_DIR_NAME:
                continue
            if _DATA_NAME_RE.fullmatch(path.name) and path.name not in known:
                try:
                    path.unlink()
                except OSError:
                    logger.warning("Could not remove stale file %s", path)
        shutil.rmtree(self._root / _WORK_DIR_NAME, ignore_errors=True)

    # --- writing -----------------------------------------------------------

    async def make_work_dir(self) -> Path:
        """A fresh scratch directory for one download."""
        base = self._root / _WORK_DIR_NAME
        await asyncio.to_thread(base.mkdir, parents=True, exist_ok=True)
        return Path(await asyncio.to_thread(tempfile.mkdtemp, dir=base))

    async def remove_work_dir(self, path: Path) -> None:
        await asyncio.to_thread(shutil.rmtree, path, True)

    async def commit_file(
        self, session: str, source: Path, *, name: str, mime: str, kind: str, duration: float | None
    ) -> StoredFile:
        """Move a finished download into the store. Enforces the file cap and the session quota.

        On a refusal the source file is deleted, so nothing is left behind.
        """
        size = (await asyncio.to_thread(source.stat)).st_size
        if size > self._max_file_bytes:
            await asyncio.to_thread(source.unlink, True)
            raise DownloaderError(
                ErrorCode.TOO_LARGE, f"The file is larger than {self._max_file_bytes // MB} MB, so it was not kept."
            )
        reserved = self._reserved.get(session, 0)
        if self.session_usage(session) + reserved + size > self._max_session_bytes:
            await asyncio.to_thread(source.unlink, True)
            raise DownloaderError(
                ErrorCode.LIMIT_EXCEEDED,
                f"Your files would use more than {self._max_session_bytes // MB} MB. Delete some files or wait for them to expire.",
            )
        # Reserve space synchronously, before any further await.
        self._reserved[session] = reserved + size
        try:
            now = self._clock()
            stored = StoredFile(
                file_id=new_file_id(),
                session=session,
                name=name,
                mime=mime,
                kind=kind,
                size=size,
                duration=duration,
                created_at=now,
                expires_at=now + self._ttl,
            )

            def finish() -> None:
                self._session_dir(session).mkdir(parents=True, exist_ok=True)
                os.replace(source, self.path(stored))
                self._meta_path(stored).write_text(json.dumps(asdict(stored)), "utf-8")

            await asyncio.to_thread(finish)
            self._index[stored.file_id] = stored
            return stored
        finally:
            left = self._reserved.get(session, 0) - size
            if left <= 0:
                self._reserved.pop(session, None)
            else:
                self._reserved[session] = left

    # --- reading -----------------------------------------------------------

    def get(self, file_id: str, session: str | None) -> StoredFile:
        """The file, if it exists, has not expired, and ``session`` may see it (None = any)."""
        file = self._index.get(file_id)
        if file is None or file.expires_at <= self._clock() or (session is not None and file.session != session):
            raise DownloaderError(ErrorCode.FILE_NOT_FOUND, f"File {file_id} wasn't found. It may have expired; download it again.")
        return file

    def list(self, session: str) -> list[StoredFile]:
        now = self._clock()
        files = [f for f in self._index.values() if f.session == session and f.expires_at > now]
        return sorted(files, key=lambda f: f.created_at)

    def session_usage(self, session: str) -> int:
        return sum(f.size for f in self.list(session))

    # --- removal -----------------------------------------------------------

    async def _remove(self, file: StoredFile) -> bool:
        def unlink() -> None:
            self.path(file).unlink(missing_ok=True)
            self._meta_path(file).unlink(missing_ok=True)

        try:
            await asyncio.to_thread(unlink)
        except OSError:
            logger.warning("Could not remove file %s", file.file_id)
            return False
        self._index.pop(file.file_id, None)
        return True

    async def delete(self, file_id: str, session: str | None) -> None:
        if not await self._remove(self.get(file_id, session)):
            raise DownloaderError(ErrorCode.INTERNAL, "This file couldn't be deleted right now. Try again in a moment.")

    async def sweep(self) -> int:
        """Delete every expired file. Returns how many were removed."""
        now = self._clock()
        removed = 0
        for file in [f for f in self._index.values() if f.expires_at <= now]:
            if await self._remove(file):
                removed += 1
        return removed
```

- [ ] **Step 4: Run tests**

Run: `.venv_video_downloader/Scripts/python -m pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat(store): session-scoped TTL file store, signed links, sweeper"
```

---

### Task 4: Extractor domain: models, presets, options

**Files:**
- Create: `src/extractor/__init__.py` (empty), `src/extractor/models.py`, `src/extractor/presets.py`, `src/extractor/options.py`, `src/extractor/base.py`
- Create: `src/models.py` (pydantic API models, first part: `PresetOption`, `ProbeResult`)
- Test: `tests/test_presets.py`, `tests/test_options.py`

**Interfaces:**
- Consumes: `Limits` (config), `DownloaderError`/`ErrorCode`.
- Produces:
  - `FormatInfo(format_id: str, height: int | None, tbr: float | None, filesize: int | None, has_video: bool, has_audio: bool)` frozen dataclass.
  - `MediaInfo(title: str, duration: float | None, thumbnail: str | None, uploader: str | None, webpage_url: str | None, formats: list[FormatInfo])`.
  - `DownloadProgress(stage: str, percent: float | None, speed: float | None, eta: float | None)`; stage is `"downloading"` or `"processing"`.
  - `DownloadedFile(path: Path)`.
  - `Preset(id, label, kind, height, audio_kbps, codec)` plus `PRESETS: dict[str, Preset]`, `get_preset(preset_id) -> Preset`.
  - `available_presets(info) -> list[Preset]`, `estimate_size(info, preset) -> int | None`, `build_options(info, limits) -> list[PresetOption]`.
  - `Extractor` Protocol: `probe(url) -> MediaInfo`; `download(url, preset, work_dir, *, max_bytes, on_progress, cancel) -> DownloadedFile`.
  - Pydantic `PresetOption(id, label, kind, estimated_bytes: int | None, blocked: bool, code: str | None, reason: str | None)`, `ProbeResult(url, title, duration, thumbnail, uploader, options: list[PresetOption])`.

- [ ] **Step 1: Write failing tests**

`tests/test_presets.py`:
```python
import pytest

from src.errors import DownloaderError, ErrorCode
from src.extractor.presets import PRESETS, get_preset


def test_preset_ids_and_order():
    assert list(PRESETS) == ["best", "1080p", "720p", "480p", "audio-mp3", "audio-m4a"]


def test_video_and_audio_presets():
    assert get_preset("720p").kind == "video" and get_preset("720p").height == 720
    assert get_preset("best").height is None
    assert get_preset("audio-mp3").kind == "audio" and get_preset("audio-mp3").codec == "mp3"
    assert get_preset("audio-m4a").codec == "m4a"


def test_unknown_preset_is_invalid_request():
    with pytest.raises(DownloaderError) as error:
        get_preset("8k")
    assert error.value.code == ErrorCode.INVALID_REQUEST
```

`tests/test_options.py`:
```python
from src.config import MB, Limits
from src.extractor.models import FormatInfo, MediaInfo
from src.extractor.options import available_presets, build_options, estimate_size
from src.extractor.presets import get_preset


def video(height, tbr=1000.0, filesize=None, audio=True, fid=None):
    return FormatInfo(fid or f"v{height}", height, tbr, filesize, True, audio)


def audio_only(tbr=128.0, filesize=None):
    return FormatInfo("a1", None, tbr, filesize, False, True)


def info(formats, duration=100.0):
    return MediaInfo("T", duration, None, None, None, formats)


def ids(presets):
    return [p.id for p in presets]


def test_presets_limited_by_max_height():
    got = available_presets(info([video(480), video(720), audio_only()]))
    assert ids(got) == ["best", "720p", "480p", "audio-mp3", "audio-m4a"]


def test_audio_only_site_offers_audio_presets_only():
    assert ids(available_presets(info([audio_only()]))) == ["audio-mp3", "audio-m4a"]


def test_unknown_formats_offer_best_and_audio():
    assert ids(available_presets(info([]))) == ["best", "audio-mp3", "audio-m4a"]


def test_estimate_uses_filesize_when_known():
    i = info([video(720, filesize=5_000_000, audio=False), audio_only(filesize=1_000_000)])
    assert estimate_size(i, get_preset("720p")) == 6_000_000


def test_estimate_falls_back_to_bitrate_times_duration():
    i = info([video(720, tbr=800.0)], duration=100.0)  # 800 kbit/s * 100 s = 10_000_000 bytes
    assert estimate_size(i, get_preset("720p")) == 10_000_000


def test_estimate_picks_highest_format_within_height():
    i = info([video(480, tbr=500.0), video(1080, tbr=4000.0)], duration=10.0)
    assert estimate_size(i, get_preset("480p")) == 625_000
    assert estimate_size(i, get_preset("best")) == 5_000_000


def test_estimate_unknown_is_none():
    assert estimate_size(info([video(720, tbr=None)], duration=None), get_preset("720p")) is None


def test_audio_estimate_uses_target_bitrate():
    assert estimate_size(info([audio_only()], duration=100.0), get_preset("audio-mp3")) == 192 * 125 * 100


def test_build_options_blocks_too_long():
    limits = Limits(max_duration_seconds=60)
    options = build_options(info([video(720), audio_only()], duration=120.0), limits)
    assert options and all(o.blocked and o.code == "too_long" for o in options)


def test_build_options_blocks_too_large_per_preset():
    limits = Limits(max_file_bytes=2 * MB)
    i = info([video(480, tbr=100.0), video(1080, tbr=8000.0)], duration=100.0)
    by_id = {o.id: o for o in build_options(i, limits)}
    assert not by_id["480p"].blocked
    assert by_id["1080p"].blocked and by_id["1080p"].code == "too_large"
    assert by_id["best"].blocked
    assert by_id["480p"].estimated_bytes == 1_250_000
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv_video_downloader/Scripts/python -m pytest tests/test_presets.py tests/test_options.py -q`
Expected: ERROR `No module named 'src.extractor'`.

- [ ] **Step 3: Implement**

`src/extractor/models.py`:
```python
"""Plain data the extractor returns. Independent of yt-dlp's dict shapes."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class FormatInfo:
    format_id: str
    height: int | None
    tbr: float | None  # total bitrate, kbit/s
    filesize: int | None  # exact or approximate bytes
    has_video: bool
    has_audio: bool


@dataclass(frozen=True)
class MediaInfo:
    title: str
    duration: float | None
    thumbnail: str | None
    uploader: str | None
    webpage_url: str | None
    formats: list[FormatInfo] = field(default_factory=list)


@dataclass(frozen=True)
class DownloadProgress:
    stage: str  # "downloading" or "processing"
    percent: float | None
    speed: float | None  # bytes per second
    eta: float | None  # seconds


@dataclass(frozen=True)
class DownloadedFile:
    path: Path
```

`src/extractor/presets.py`:
```python
"""The quality choices offered to users. Kept in code: they map straight to yt-dlp format selectors."""

from __future__ import annotations

from dataclasses import dataclass

from src.errors import DownloaderError, ErrorCode


@dataclass(frozen=True)
class Preset:
    id: str
    label: str
    kind: str  # "video" or "audio"
    height: int | None = None  # video: cap on frame height (None = best available)
    audio_kbps: int = 192  # audio: target bitrate of the converted file
    codec: str | None = None  # audio: "mp3" or "m4a"


PRESETS: dict[str, Preset] = {
    p.id: p
    for p in (
        Preset("best", "Best quality", "video"),
        Preset("1080p", "1080p", "video", height=1080),
        Preset("720p", "720p", "video", height=720),
        Preset("480p", "480p", "video", height=480),
        Preset("audio-mp3", "Audio (MP3)", "audio", codec="mp3"),
        Preset("audio-m4a", "Audio (M4A)", "audio", codec="m4a"),
    )
}


def get_preset(preset_id: str) -> Preset:
    preset = PRESETS.get(preset_id)
    if preset is None:
        raise DownloaderError(ErrorCode.INVALID_REQUEST, f"Unknown quality '{preset_id}'. Choose one of: {', '.join(PRESETS)}.")
    return preset
```

`src/models.py` (first part; later tasks append):
```python
"""Request and response models shared by the REST routers and MCP tools."""

from __future__ import annotations

from pydantic import BaseModel


class PresetOption(BaseModel):
    id: str
    label: str
    kind: str
    estimated_bytes: int | None = None
    blocked: bool = False
    code: str | None = None  # error code when blocked
    reason: str | None = None  # plain-language reason when blocked


class ProbeResult(BaseModel):
    url: str
    title: str
    duration: float | None = None
    thumbnail: str | None = None
    uploader: str | None = None
    options: list[PresetOption]
```

`src/extractor/options.py`:
```python
"""Which presets a video offers, how big each would be, and which the caps block."""

from __future__ import annotations

from src.config import MB, Limits
from src.errors import ErrorCode
from src.extractor.models import FormatInfo, MediaInfo
from src.extractor.presets import PRESETS, Preset
from src.models import PresetOption

_KBIT_TO_BYTES_PER_SECOND = 125  # 1 kbit/s = 125 bytes/s


def available_presets(info: MediaInfo) -> list[Preset]:
    """Presets the site can serve. An unknown format list offers "best" plus audio."""
    has_video = any(f.has_video for f in info.formats) or not info.formats
    heights = [f.height for f in info.formats if f.has_video and f.height]
    offered: list[Preset] = []
    for preset in PRESETS.values():
        if preset.kind == "audio":
            offered.append(preset)
        elif not has_video:
            continue
        elif preset.height is None or (heights and max(heights) >= preset.height):
            offered.append(preset)
    return offered


def _format_bytes(fmt: FormatInfo, duration: float | None) -> int | None:
    if fmt.filesize:
        return int(fmt.filesize)
    if fmt.tbr and duration:
        return int(fmt.tbr * _KBIT_TO_BYTES_PER_SECOND * duration)
    return None


def estimate_size(info: MediaInfo, preset: Preset) -> int | None:
    """Expected size in bytes, or None when the site gives no usable numbers."""
    if preset.kind == "audio":
        return int(preset.audio_kbps * _KBIT_TO_BYTES_PER_SECOND * info.duration) if info.duration else None
    candidates = [f for f in info.formats if f.has_video and (preset.height is None or (f.height or 0) <= preset.height)]
    if not candidates:
        return None
    best = max(candidates, key=lambda f: (f.height or 0, f.tbr or 0))
    size = _format_bytes(best, info.duration)
    if size is None:
        return None
    if not best.has_audio:
        audio = [f for f in info.formats if f.has_audio and not f.has_video]
        if audio:
            best_audio = max(audio, key=lambda f: f.tbr or 0)
            size += _format_bytes(best_audio, info.duration) or 0
    return size


def build_options(info: MediaInfo, limits: Limits) -> list[PresetOption]:
    """One option per offered preset, with the caps applied."""
    too_long = info.duration is not None and info.duration > limits.max_duration_seconds
    options: list[PresetOption] = []
    for preset in available_presets(info):
        estimate = estimate_size(info, preset)
        blocked, code, reason = False, None, None
        if too_long:
            minutes = int(limits.max_duration_seconds // 60)
            blocked, code = True, str(ErrorCode.TOO_LONG)
            reason = f"Videos longer than {minutes} minutes are not allowed."
        elif estimate is not None and estimate > limits.max_file_bytes:
            blocked, code = True, str(ErrorCode.TOO_LARGE)
            reason = f"Would be about {estimate // MB} MB; the limit is {limits.max_file_bytes // MB} MB. Pick a lower quality."
        options.append(
            PresetOption(
                id=preset.id,
                label=preset.label,
                kind=preset.kind,
                estimated_bytes=estimate,
                blocked=blocked,
                code=code,
                reason=reason,
            )
        )
    return options
```

`src/extractor/base.py`:
```python
"""What the service needs from an extractor. yt-dlp is one implementation; tests use a fake."""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from src.extractor.models import DownloadedFile, DownloadProgress, MediaInfo
from src.extractor.presets import Preset


class Extractor(Protocol):
    def probe(self, url: str) -> MediaInfo:
        """Metadata only, no download. Blocking: call through asyncio.to_thread."""

    def download(
        self,
        url: str,
        preset: Preset,
        work_dir: Path,
        *,
        max_bytes: int,
        on_progress: Callable[[DownloadProgress], None],
        cancel: threading.Event,
    ) -> DownloadedFile:
        """Download into ``work_dir`` and return the finished file. Blocking: call through asyncio.to_thread.

        Raises DownloaderError (cancelled, too_large, ...). Stops soon after ``cancel`` is set.
        """
```

- [ ] **Step 4: Run tests**

Run: `.venv_video_downloader/Scripts/python -m pytest -q`
Expected: all pass. (Check `test_estimate_picks_highest_format_within_height`: 480p uses video480 tbr 500 → 500*125*10 = 625_000; best uses video1080 tbr 4000 → 5_000_000; both formats have audio so nothing added.)

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat(extractor): media models, quality presets, size estimates and caps"
```

---

### Task 5: yt-dlp extractor

**Files:**
- Create: `src/extractor/ytdlp.py`, `src/system_info.py`
- Test: `tests/test_ytdlp_extractor.py`, `tests/test_system_info.py`

**Interfaces:**
- Consumes: `GUARD`, `SocketGuard` (Task 2); `MediaInfo`, `FormatInfo`, `DownloadProgress`, `DownloadedFile`, `Preset` (Task 4); `DownloaderError`.
- Produces:
  - `media_info_from_dict(raw: dict) -> MediaInfo`
  - `map_error(exc: Exception, *, blocked: bool) -> DownloaderError`
  - `YtDlpExtractor(guard: SocketGuard = GUARD, ffmpeg_location: str | None = None)` implementing `Extractor`; `__init__` calls `guard.install()`.
  - `find_ffmpeg() -> str | None`, `ytdlp_version() -> str`, `require_ffmpeg() -> None` (raises `DownloaderError(FFMPEG_MISSING)`).

- [ ] **Step 1: Write failing tests**

`tests/test_system_info.py`:
```python
import pytest

from src import system_info
from src.errors import DownloaderError, ErrorCode


def test_require_ffmpeg_raises_when_missing(monkeypatch):
    monkeypatch.setattr(system_info.shutil, "which", lambda name: None)
    with pytest.raises(DownloaderError) as error:
        system_info.require_ffmpeg()
    assert error.value.code == ErrorCode.FFMPEG_MISSING


def test_require_ffmpeg_ok_when_found(monkeypatch):
    monkeypatch.setattr(system_info.shutil, "which", lambda name: "/usr/bin/ffmpeg")
    system_info.require_ffmpeg()


def test_ytdlp_version_is_a_string():
    assert system_info.ytdlp_version()
```

`tests/test_ytdlp_extractor.py`:
```python
from __future__ import annotations

import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from src.errors import DownloaderError, ErrorCode
from src.extractor.models import DownloadProgress
from src.extractor.presets import get_preset
from src.extractor.ytdlp import YtDlpExtractor, map_error, media_info_from_dict
from src.policy.socket_guard import SocketGuard


# --- pure mapping ------------------------------------------------------------

RAW = {
    "title": "Cat",
    "duration": 61.5,
    "thumbnail": "https://img/t.jpg",
    "uploader": "Cats",
    "webpage_url": "https://example.com/v",
    "formats": [
        {"format_id": "18", "height": 360, "tbr": 500.2, "filesize": None, "filesize_approx": 4000000, "vcodec": "avc1", "acodec": "mp4a"},
        {"format_id": "140", "height": None, "tbr": 128, "filesize": 1000, "vcodec": "none", "acodec": "mp4a"},
        {"format_id": "sb0", "height": 90, "tbr": None, "vcodec": "none", "acodec": "none"},
    ],
}


def test_media_info_from_dict():
    info = media_info_from_dict(RAW)
    assert (info.title, info.duration, info.uploader) == ("Cat", 61.5, "Cats")
    video, audio = info.formats[0], info.formats[1]
    assert video.has_video and video.has_audio and video.filesize == 4000000 and video.height == 360
    assert audio.has_audio and not audio.has_video and audio.filesize == 1000
    assert len(info.formats) == 2  # the storyboard (no audio, no video) is dropped


def test_media_info_defaults_when_fields_missing():
    info = media_info_from_dict({})
    assert info.title == "video" and info.formats == [] and info.duration is None


@pytest.mark.parametrize(
    "message, expected",
    [
        ("ERROR: Unsupported URL: https://x.example", ErrorCode.UNSUPPORTED_SITE),
        ("ERROR: [youtube] abc: Sign in to confirm you're not a bot", ErrorCode.LOGIN_REQUIRED),
        ("ERROR: Private video. Sign in if you've been granted access", ErrorCode.LOGIN_REQUIRED),
        ("ERROR: This video is DRM protected", ErrorCode.DRM_PROTECTED),
        ("ERROR: ffmpeg not found. Please install", ErrorCode.FFMPEG_MISSING),
        ("ERROR: something odd", ErrorCode.EXTRACTOR_FAILED),
    ],
)
def test_map_error(message, expected):
    assert map_error(RuntimeError(message), blocked=False).code == expected


def test_map_error_blocked_wins():
    assert map_error(RuntimeError("anything"), blocked=True).code == ErrorCode.BLOCKED_HOST


def test_map_error_passes_downloader_errors_through():
    original = DownloaderError(ErrorCode.TOO_LARGE, "big")
    assert map_error(original, blocked=False) is original


# --- against a local HTTP server (the generic extractor handles direct media links) ---


class MediaServer:
    """Serves one fake mp4 slowly enough to cancel mid-download."""

    def __init__(self, size: int, chunk: int = 8192, delay: float = 0.0) -> None:
        self.size = size

        class Handler(BaseHTTPRequestHandler):
            def _headers(self):
                self.send_response(200)
                self.send_header("Content-Type", "video/mp4")
                self.send_header("Content-Length", str(size))
                self.end_headers()

            def do_HEAD(self):
                self._headers()

            def do_GET(self):
                self._headers()
                sent = 0
                try:
                    while sent < size:
                        part = min(chunk, size - sent)
                        self.wfile.write(b"\0" * part)
                        sent += part
                        if delay:
                            time.sleep(delay)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def log_message(self, *args):
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}/clip.mp4"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def open_guard():
    guard = SocketGuard(allow=lambda ip, port: True)  # loopback is fine for these tests
    yield guard
    guard.uninstall()


@pytest.fixture
def extractor(open_guard):
    return YtDlpExtractor(guard=open_guard)


def test_probe_local_media_link(extractor):
    server = MediaServer(2000)
    try:
        info = extractor.probe(server.url)
    finally:
        server.close()
    assert info.title  # generic extractor derives a title from the file name


def test_download_returns_file_and_reports_progress(extractor, tmp_path: Path):
    server = MediaServer(200_000, chunk=20_000)
    seen: list[DownloadProgress] = []
    try:
        result = extractor.download(
            server.url, get_preset("best"), tmp_path, max_bytes=10_000_000, on_progress=seen.append, cancel=threading.Event()
        )
    finally:
        server.close()
    assert result.path.exists() and result.path.stat().st_size == 200_000
    assert any(p.stage == "downloading" for p in seen)


def test_download_stops_when_over_byte_cap(extractor, tmp_path: Path):
    server = MediaServer(400_000, chunk=20_000, delay=0.01)
    try:
        with pytest.raises(DownloaderError) as error:
            extractor.download(
                server.url, get_preset("best"), tmp_path, max_bytes=50_000, on_progress=lambda p: None, cancel=threading.Event()
            )
    finally:
        server.close()
    assert error.value.code == ErrorCode.TOO_LARGE


def test_download_stops_when_cancelled(extractor, tmp_path: Path):
    server = MediaServer(2_000_000, chunk=20_000, delay=0.02)
    cancel = threading.Event()
    threading.Timer(0.2, cancel.set).start()
    try:
        with pytest.raises(DownloaderError) as error:
            extractor.download(server.url, get_preset("best"), tmp_path, max_bytes=10**9, on_progress=lambda p: None, cancel=cancel)
    finally:
        server.close()
    assert error.value.code == ErrorCode.CANCELLED


def test_blocked_address_maps_to_blocked_host(tmp_path: Path):
    guard = SocketGuard(allow=lambda ip, port: False)
    try:
        extractor = YtDlpExtractor(guard=guard)
        server = MediaServer(2000)
        try:
            with pytest.raises(DownloaderError) as error:
                extractor.probe(server.url)
        finally:
            server.close()
    finally:
        guard.uninstall()
    assert error.value.code == ErrorCode.BLOCKED_HOST
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv_video_downloader/Scripts/python -m pytest tests/test_system_info.py tests/test_ytdlp_extractor.py -q`
Expected: ERROR `No module named 'src.system_info'`.

- [ ] **Step 3: Implement**

`src/system_info.py`:
```python
"""Facts about the host the service depends on: FFmpeg and the yt-dlp version."""

from __future__ import annotations

import shutil

from src.errors import DownloaderError, ErrorCode


def find_ffmpeg() -> str | None:
    return shutil.which("ffmpeg")


def ytdlp_version() -> str:
    from yt_dlp.version import __version__

    return __version__


def require_ffmpeg() -> None:
    """Raise ffmpeg_missing if FFmpeg is not on PATH (called at startup)."""
    if find_ffmpeg() is None:
        raise DownloaderError(ErrorCode.FFMPEG_MISSING, "FFmpeg was not found on PATH. Install FFmpeg, then start the service again.")
```

`src/extractor/ytdlp.py`:
```python
"""yt-dlp behind the Extractor protocol.

Every network call runs inside ``guard.active()`` so redirects and DNS answers
to private addresses are refused. yt-dlp's exceptions are mapped to stable
error codes; their raw text goes to the log only.
"""

from __future__ import annotations

import logging
import re
import threading
from collections.abc import Callable
from pathlib import Path

from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadCancelled

from src.errors import DownloaderError, ErrorCode
from src.extractor.models import DownloadedFile, DownloadProgress, FormatInfo, MediaInfo
from src.extractor.presets import Preset
from src.policy.socket_guard import GUARD, SocketGuard

logger = logging.getLogger(__name__)

SOCKET_TIMEOUT_SECONDS = 20
_LOGIN = re.compile(r"sign in|log in|login|private video|members[- ]only|age[- ]restricted|cookies|confirm you.re not a bot", re.I)


class _CancelledByCaller(DownloadCancelled):
    """Raised from a progress hook when the job's cancel event is set."""


class _OverByteCap(DownloadCancelled):
    """Raised from a progress hook when the download passes the byte cap."""


def media_info_from_dict(raw: dict) -> MediaInfo:
    """Convert yt-dlp's info dict into MediaInfo. Formats with neither audio nor video (storyboards) are dropped."""
    formats: list[FormatInfo] = []
    for fmt in raw.get("formats") or []:
        has_video = (fmt.get("vcodec") or "none") != "none"
        has_audio = (fmt.get("acodec") or "none") != "none"
        if not has_video and not has_audio:
            continue
        formats.append(
            FormatInfo(
                format_id=str(fmt.get("format_id", "")),
                height=fmt.get("height") or None,
                tbr=float(fmt["tbr"]) if fmt.get("tbr") else None,
                filesize=int(fmt.get("filesize") or fmt.get("filesize_approx") or 0) or None,
                has_video=has_video,
                has_audio=has_audio,
            )
        )
    duration = raw.get("duration")
    return MediaInfo(
        title=str(raw.get("title") or "video"),
        duration=float(duration) if duration else None,
        thumbnail=raw.get("thumbnail") or None,
        uploader=raw.get("uploader") or raw.get("channel") or None,
        webpage_url=raw.get("webpage_url") or None,
        formats=formats,
    )


def map_error(exc: Exception, *, blocked: bool) -> DownloaderError:
    """Turn any extractor failure into a DownloaderError. Raw text is logged, never returned."""
    if isinstance(exc, DownloaderError):
        return exc
    if blocked:
        return DownloaderError(ErrorCode.BLOCKED_HOST, "That address is not a public website, so it can't be downloaded.")
    text = str(exc)
    logger.warning("yt-dlp failed: %s", text)
    lowered = text.lower()
    if "unsupported url" in lowered:
        return DownloaderError(ErrorCode.UNSUPPORTED_SITE, "This site or link isn't supported.")
    if "drm" in lowered:
        return DownloaderError(ErrorCode.DRM_PROTECTED, "This video is copy-protected (DRM) and can't be downloaded.")
    if "ffmpeg" in lowered or "ffprobe" in lowered:
        return DownloaderError(ErrorCode.FFMPEG_MISSING, "FFmpeg is missing or failed, so the video can't be processed.")
    if _LOGIN.search(text):
        return DownloaderError(ErrorCode.LOGIN_REQUIRED, "This video needs a login (private, members-only or age-restricted).")
    return DownloaderError(ErrorCode.EXTRACTOR_FAILED, "The video couldn't be fetched. The site may have changed or the video is unavailable.")


def _final_path(info: dict, work_dir: Path) -> Path:
    """The finished file: yt-dlp reports it, else the single non-temporary file in work_dir."""
    for item in info.get("requested_downloads") or []:
        path = item.get("filepath")
        if path and Path(path).exists():
            return Path(path)
    candidates = [p for p in work_dir.iterdir() if p.is_file() and p.suffix not in (".part", ".ytdl", ".temp")]
    if len(candidates) != 1:
        raise DownloaderError(ErrorCode.EXTRACTOR_FAILED, "The download finished but the file could not be found.")
    return candidates[0]


class YtDlpExtractor:
    def __init__(self, guard: SocketGuard = GUARD, ffmpeg_location: str | None = None) -> None:
        self._guard = guard
        self._ffmpeg_location = ffmpeg_location
        guard.install()

    def _base_options(self) -> dict:
        options: dict = {
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "playlist_items": "1",
            "socket_timeout": SOCKET_TIMEOUT_SECONDS,
            "retries": 3,
            "cachedir": False,
            "hls_prefer_native": True,
            "concurrent_fragment_downloads": 1,  # one thread, so the thread-local guard covers every request
        }
        if self._ffmpeg_location:
            options["ffmpeg_location"] = self._ffmpeg_location
        return options

    def probe(self, url: str) -> MediaInfo:
        options = {**self._base_options(), "skip_download": True}
        with self._guard.active():
            try:
                with YoutubeDL(options) as ydl:
                    raw = ydl.extract_info(url, download=False)
            except Exception as exc:
                raise map_error(exc, blocked=self._guard.blocked) from exc
        if not raw:
            raise DownloaderError(ErrorCode.EXTRACTOR_FAILED, "The video couldn't be fetched.")
        if raw.get("_type") in ("playlist", "multi_video"):
            raise DownloaderError(ErrorCode.INVALID_URL, "That link is a playlist. Paste the link of a single video.")
        return media_info_from_dict(raw)

    def download(
        self,
        url: str,
        preset: Preset,
        work_dir: Path,
        *,
        max_bytes: int,
        on_progress: Callable[[DownloadProgress], None],
        cancel: threading.Event,
    ) -> DownloadedFile:
        def hook(status: dict) -> None:
            if cancel.is_set():
                raise _CancelledByCaller()
            if status.get("status") == "downloading":
                done = status.get("downloaded_bytes") or 0
                if done > max_bytes:
                    raise _OverByteCap()
                total = status.get("total_bytes") or status.get("total_bytes_estimate")
                percent = round(done * 100 / total, 1) if total else None
                on_progress(DownloadProgress("downloading", percent, status.get("speed"), status.get("eta")))
            elif status.get("status") == "finished":
                on_progress(DownloadProgress("processing", 100.0, None, None))

        options = {
            **self._base_options(),
            "paths": {"home": str(work_dir), "temp": str(work_dir)},
            "outtmpl": "%(id)s.%(ext)s",
            "restrictfilenames": True,
            "progress_hooks": [hook],
            "noprogress": True,
            "max_filesize": max_bytes,
            **_format_options(preset),
        }
        with self._guard.active():
            try:
                with YoutubeDL(options) as ydl:
                    info = ydl.extract_info(url, download=True)
            except _CancelledByCaller:
                raise DownloaderError(ErrorCode.CANCELLED, "The download was cancelled.") from None
            except _OverByteCap:
                raise DownloaderError(
                    ErrorCode.TOO_LARGE, f"The file is larger than {max_bytes // (1024 * 1024)} MB, so the download was stopped."
                ) from None
            except Exception as exc:
                raise map_error(exc, blocked=self._guard.blocked) from exc
        if info and info.get("_type") in ("playlist", "multi_video"):
            raise DownloaderError(ErrorCode.INVALID_URL, "That link is a playlist. Paste the link of a single video.")
        return DownloadedFile(_final_path(info or {}, work_dir))


def _format_options(preset: Preset) -> dict:
    """yt-dlp format selector (and audio conversion) for one preset."""
    if preset.kind == "audio":
        return {
            "format": "bestaudio/best",
            "postprocessors": [
                {"key": "FFmpegExtractAudio", "preferredcodec": preset.codec, "preferredquality": str(preset.audio_kbps)}
            ],
        }
    if preset.height is None:
        selector = "bestvideo*+bestaudio/best"
    else:
        selector = f"bestvideo*[height<={preset.height}]+bestaudio/best[height<={preset.height}]"
    return {"format": selector, "merge_output_format": "mp4", "format_sort": ["res", "ext:mp4:m4a"]}
```

- [ ] **Step 4: Run tests**

Run: `.venv_video_downloader/Scripts/python -m pytest tests/test_system_info.py tests/test_ytdlp_extractor.py -q`
Expected: PASS. If the local-server tests fail because yt-dlp's generic extractor will not accept the fake bytes or needs a different header, adjust only the test server (for example add `Accept-Ranges`) and note it; do not weaken the assertions. If cancel or cap tests fail because yt-dlp swallows the hook exception, report it rather than catching broadly.

- [ ] **Step 5: Run the whole suite**

Run: `.venv_video_downloader/Scripts/python -m pytest -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "feat(extractor): yt-dlp wrapper with guard, caps, cancel and error mapping"
```

---

### Task 6: Job queue

**Files:**
- Create: `src/jobs/__init__.py` (empty), `src/jobs/job_queue.py`
- Test: `tests/test_job_queue.py`

**Interfaces:**
- Consumes: `DownloaderError`, `ErrorCode`.
- Produces:
  - `Emit = Callable[[dict], None]` (thread-safe), `Work = Callable[[Emit, threading.Event], Awaitable[dict]]`
  - `Job` dataclass: `id`, `session`, `created_at`, `events: list[dict]`, `finished: bool`, `cancel_event`; methods `cancel()`, `publish(event, *, final=False)`, `async stream()`.
  - `JobQueue(max_concurrent, max_queued, timeout_seconds, clock=time.time)` with `submit(session, work) -> Job` (raises `queue_full`), `cancel(job)`, `get(job_id, session|None) -> Job`, `async wait(job) -> dict` (final event), `prune(older_than) -> int`.
  - Event shapes: `{"type":"queued"}`, `{"type":"progress"|"processing", ...}` (whatever `emit` receives), final `{"type":"done", **result}` or `{"type":"error","code","message"}`.

- [ ] **Step 1: Write failing tests**

`tests/test_job_queue.py`:
```python
from __future__ import annotations

import asyncio
import threading

import pytest

from src.errors import DownloaderError, ErrorCode
from src.jobs.job_queue import JobQueue


async def ok_work(emit, cancel):
    emit({"type": "progress", "percent": 50.0})
    return {"file_id": "f_1"}


async def test_job_publishes_queued_progress_done():
    queue = JobQueue(2, 4, 5.0)
    job = queue.submit("s", ok_work)
    final = await queue.wait(job)
    assert [e["type"] for e in job.events] == ["queued", "progress", "done"]
    assert final == {"type": "done", "file_id": "f_1"}


async def test_late_subscriber_replays_all_events():
    queue = JobQueue(2, 4, 5.0)
    job = queue.submit("s", ok_work)
    await queue.wait(job)
    seen = [e async for e in job.stream()]
    assert len(seen) == 3


async def test_downloader_error_becomes_error_event():
    async def work(emit, cancel):
        raise DownloaderError(ErrorCode.UNSUPPORTED_SITE, "nope")

    queue = JobQueue(2, 4, 5.0)
    final = await queue.wait(queue.submit("s", work))
    assert final == {"type": "error", "code": "unsupported_site", "message": "nope"}


async def test_unexpected_error_is_internal_and_hides_details():
    async def work(emit, cancel):
        raise RuntimeError("secret path C:\\x")

    queue = JobQueue(2, 4, 5.0)
    final = await queue.wait(queue.submit("s", work))
    assert final["code"] == "internal_error"
    assert "secret" not in final["message"]


async def test_concurrency_limit_and_queue_full():
    gate = asyncio.Event()
    running = 0
    peak = 0

    async def work(emit, cancel):
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await gate.wait()
        running -= 1
        return {}

    queue = JobQueue(max_concurrent=1, max_queued=1, timeout_seconds=5.0)
    first = queue.submit("s", work)
    second = queue.submit("s", work)
    with pytest.raises(DownloaderError) as error:
        queue.submit("s", work)
    assert error.value.code == ErrorCode.QUEUE_FULL
    await asyncio.sleep(0.05)
    assert peak == 1
    gate.set()
    await queue.wait(first)
    await queue.wait(second)
    assert peak == 1


async def test_cancel_running_job_ends_with_cancelled():
    started = asyncio.Event()

    async def work(emit, cancel):
        started.set()
        while not cancel.is_set():
            await asyncio.sleep(0.01)
        raise DownloaderError(ErrorCode.CANCELLED, "The download was cancelled.")

    queue = JobQueue(1, 1, 5.0)
    job = queue.submit("s", work)
    await started.wait()
    queue.cancel(job)
    final = await queue.wait(job)
    assert final["code"] == "cancelled"


async def test_cancel_while_queued_never_starts_work():
    gate = asyncio.Event()
    started: list[str] = []

    async def blocker(emit, cancel):
        await gate.wait()
        return {}

    async def work(emit, cancel):
        started.append("ran")
        return {}

    queue = JobQueue(1, 2, 5.0)
    first = queue.submit("s", blocker)
    second = queue.submit("s", work)
    await asyncio.sleep(0.02)
    queue.cancel(second)
    gate.set()
    await queue.wait(first)
    final = await queue.wait(second)
    assert final["code"] == "cancelled" and started == []


async def test_timeout_sets_cancel_and_reports_timeout():
    async def work(emit, cancel):
        while not cancel.is_set():
            await asyncio.sleep(0.01)
        raise DownloaderError(ErrorCode.CANCELLED, "x")

    queue = JobQueue(1, 1, 0.05)
    final = await queue.wait(queue.submit("s", work))
    assert final["code"] == "timeout"


async def test_emit_works_from_a_worker_thread():
    async def work(emit, cancel):
        await asyncio.to_thread(emit, {"type": "progress", "percent": 10.0})
        return {}

    queue = JobQueue(1, 1, 5.0)
    job = queue.submit("s", work)
    await queue.wait(job)
    assert {"type": "progress", "percent": 10.0} in job.events


async def test_get_is_scoped_to_session_and_prune_forgets_old_jobs():
    now = [100.0]
    queue = JobQueue(1, 1, 5.0, clock=lambda: now[0])
    job = queue.submit("alice", ok_work)
    await queue.wait(job)
    assert queue.get(job.id, "alice") is job
    assert queue.get(job.id, None) is job
    with pytest.raises(DownloaderError) as error:
        queue.get(job.id, "bob")
    assert error.value.code == ErrorCode.JOB_NOT_FOUND
    assert queue.prune(older_than=200.0) == 1
    with pytest.raises(DownloaderError):
        queue.get(job.id, "alice")
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv_video_downloader/Scripts/python -m pytest tests/test_job_queue.py -q`
Expected: ERROR `No module named 'src.jobs'`.

- [ ] **Step 3: Implement `src/jobs/job_queue.py`**

```python
"""Download jobs: a concurrency limit, a bounded wait queue, a timeout, replayable events.

A job's events are kept in a list so a late subscriber (the browser opening the
SSE stream after POST /downloads returned) still sees everything. publish() runs
on the event loop thread; worker threads report through ``emit``, which hops to
the loop with call_soon_threadsafe.

Timeouts and cancels are cooperative: the job's ``cancel`` event is set and the
work is awaited until it really stops (Python cannot kill threads). The
semaphore slot is held until then, so stopped downloads never exceed the
concurrency limit and always clean up after themselves.
"""

from __future__ import annotations

import asyncio
import logging
import secrets
import threading
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field

from src.errors import DownloaderError, ErrorCode

logger = logging.getLogger(__name__)

Emit = Callable[[dict], None]
Work = Callable[[Emit, threading.Event], Awaitable[dict]]


@dataclass
class Job:
    id: str
    session: str
    created_at: float
    events: list[dict] = field(default_factory=list)
    finished: bool = False
    cancel_event: threading.Event = field(default_factory=threading.Event, repr=False)
    _changed: asyncio.Event = field(default_factory=asyncio.Event, repr=False)

    def cancel(self) -> None:
        """Ask the job to stop: a queued job never starts, a running one stops cooperatively."""
        self.cancel_event.set()

    def publish(self, event: dict, *, final: bool = False) -> None:
        """Append an event. Events after the final one are dropped."""
        if self.finished:
            return
        self.events.append(event)
        self.finished = final
        self._changed.set()

    async def stream(self) -> AsyncIterator[dict]:
        """Every event so far, then new ones as they arrive, ending after the final event."""
        index = 0
        while True:
            while index < len(self.events):
                yield self.events[index]
                index += 1
            if self.finished:
                return
            self._changed.clear()
            await self._changed.wait()


def _error(code: ErrorCode, message: str) -> dict:
    return {"type": "error", "code": str(code), "message": message}


class JobQueue:
    """Runs submitted downloads under a concurrency limit, a queue bound and a timeout."""

    def __init__(
        self, max_concurrent: int, max_queued: int, timeout_seconds: float, clock: Callable[[], float] = time.time
    ) -> None:
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._capacity = max_concurrent + max_queued
        self._timeout = timeout_seconds
        self._clock = clock
        self._jobs: dict[str, Job] = {}
        self._tasks: set[asyncio.Task] = set()

    def submit(self, session: str, work: Work) -> Job:
        if sum(1 for job in self._jobs.values() if not job.finished) >= self._capacity:
            raise DownloaderError(ErrorCode.QUEUE_FULL, "Too many downloads are running. Try again in a minute.")
        job = Job(id="j_" + secrets.token_hex(12), session=session, created_at=self._clock())
        self._jobs[job.id] = job
        task = asyncio.create_task(self._run(job, work))
        self._tasks.add(task)  # keep a reference so the task is not garbage-collected
        task.add_done_callback(self._tasks.discard)
        return job

    async def _run(self, job: Job, work: Work) -> None:
        loop = asyncio.get_running_loop()
        cancel = job.cancel_event

        def emit(event: dict) -> None:
            try:
                loop.call_soon_threadsafe(job.publish, event)
            except RuntimeError:  # the loop closed while a worker thread was still running
                pass

        cancelled = _error(ErrorCode.CANCELLED, "The download was cancelled.")
        timed_out = _error(
            ErrorCode.TIMEOUT, f"The download took longer than {self._timeout / 60:g} minutes and was stopped."
        )
        job.publish({"type": "queued"})
        timeout_hit = False
        async with self._semaphore:
            if cancel.is_set():  # cancelled while queued: never start the work
                job.publish(cancelled, final=True)
                return
            task = asyncio.ensure_future(work(emit, cancel))
            await asyncio.wait({task}, timeout=self._timeout)
            if not task.done():
                timeout_hit = True
                cancel.set()
                await asyncio.wait({task})  # hold the slot until the work has really stopped
        try:
            result = task.result()
        except DownloaderError as error:
            job.publish(timed_out if timeout_hit else _error(error.code, error.message), final=True)
        except Exception:
            if timeout_hit:
                job.publish(timed_out, final=True)
            elif cancel.is_set():
                job.publish(cancelled, final=True)
            else:
                logger.exception("Download job %s failed", job.id)
                job.publish(_error(ErrorCode.INTERNAL, "The download failed unexpectedly. Try again."), final=True)
        else:
            job.publish({"type": "done", **result}, final=True)

    def cancel(self, job: Job) -> None:
        job.cancel()

    def get(self, job_id: str, session: str | None) -> Job:
        job = self._jobs.get(job_id)
        if job is None or (session is not None and job.session != session):
            raise DownloaderError(ErrorCode.JOB_NOT_FOUND, f"Job {job_id} wasn't found.")
        return job

    async def wait(self, job: Job) -> dict:
        """The job's final event."""
        final: dict = {}
        async for event in job.stream():
            final = event
        return final

    def prune(self, older_than: float) -> int:
        """Forget finished jobs created before ``older_than``."""
        stale = [job_id for job_id, job in self._jobs.items() if job.finished and job.created_at < older_than]
        for job_id in stale:
            del self._jobs[job_id]
        return len(stale)
```

- [ ] **Step 4: Run tests**

Run: `.venv_video_downloader/Scripts/python -m pytest tests/test_job_queue.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat(jobs): download job queue with SSE events, cancel and timeout"
```

---

### Task 7: API models and DownloadService facade

**Files:**
- Modify: `src/models.py` (append `FileInfo`, `ErrorInfo`, `JobStatus`, request models)
- Create: `src/service.py`
- Modify: `tests/conftest.py` (add `FakeExtractor`, `public_resolver`, `service` fixture)
- Test: `tests/test_service.py`

**Interfaces:**
- Consumes: everything from Tasks 1-6.
- Produces:
  - Models: `FileInfo(file_id, name, kind, mime, size, duration, expires_at, download_url)` with `FileInfo.of(stored, download_url)`; `ErrorInfo(code, message)`; `JobStatus(job_id, state, percent, speed, eta, file, error)`; `ProbeRequest(url)`; `DownloadRequest(url, preset)`.
  - `Caller(session: str, privileged: bool = False)` with `.scope`.
  - `DownloadService` methods: `store` property; `async probe(url) -> ProbeResult`; `async start_download(caller, url, preset_id) -> Job`; `get_job(caller, job_id) -> Job`; `cancel_job(caller, job_id) -> None`; `job_status(caller, job_id) -> JobStatus`; `async wait(job) -> dict`; `file_info(stored) -> FileInfo`; `list_files(caller) -> list[StoredFile]`; `get_file(caller, file_id) -> StoredFile`; `file_path(file) -> Path`; `async delete_file(caller, file_id)`; `file_for_download(file_id, exp, sig) -> StoredFile`; `async sweep() -> int`.
  - `build_service(settings, *, extractor=None, policy=None) -> DownloadService`.
  - Test helpers: `FakeExtractor` (attributes `info`, `content`, `suffix`, `probe_error`, `download_error`, `hold`, `calls`), `public_resolver`.

- [ ] **Step 1: Extend conftest**

Append to `tests/conftest.py`:
```python
import threading
import time
from collections.abc import Callable
from dataclasses import replace

from src.errors import DownloaderError, ErrorCode
from src.extractor.models import DownloadedFile, DownloadProgress, FormatInfo, MediaInfo
from src.extractor.presets import Preset
from src.policy.url_policy import UrlPolicy


async def public_resolver(host: str) -> list[str]:
    return ["93.184.216.34"]


class FakeExtractor:
    """Stands in for yt-dlp: no network, configurable outcome."""

    def __init__(self) -> None:
        self.info = MediaInfo(
            title="Cat video",
            duration=60.0,
            thumbnail="https://img.example/t.jpg",
            uploader="Cats",
            webpage_url="https://example.com/v",
            formats=[
                FormatInfo("18", 360, 500.0, None, True, True),
                FormatInfo("22", 720, 1500.0, None, True, True),
                FormatInfo("140", None, 128.0, None, False, True),
            ],
        )
        self.content = b"video-bytes" * 100
        self.suffix = ".mp4"
        self.probe_error: DownloaderError | None = None
        self.download_error: DownloaderError | None = None
        self.hold: threading.Event | None = None  # download waits for this (or for cancel)
        self.calls: list[tuple[str, str]] = []

    def probe(self, url: str) -> MediaInfo:
        if self.probe_error:
            raise self.probe_error
        return self.info

    def download(
        self,
        url: str,
        preset: Preset,
        work_dir,
        *,
        max_bytes: int,
        on_progress: Callable[[DownloadProgress], None],
        cancel: threading.Event,
    ) -> DownloadedFile:
        self.calls.append((url, preset.id))
        if self.download_error:
            raise self.download_error
        on_progress(DownloadProgress("downloading", 10.0, 1000.0, 5.0))
        if self.hold is not None:
            while not self.hold.is_set():
                if cancel.is_set():
                    raise DownloaderError(ErrorCode.CANCELLED, "The download was cancelled.")
                time.sleep(0.01)
        suffix = ".mp3" if preset.kind == "audio" else self.suffix
        path = work_dir / f"media{suffix}"
        path.write_bytes(self.content)
        on_progress(DownloadProgress("processing", 100.0, None, None))
        return DownloadedFile(path)


@pytest.fixture
def fake_extractor() -> FakeExtractor:
    return FakeExtractor()


@pytest.fixture
def service(settings, fake_extractor):
    from src.service import build_service

    return build_service(settings, extractor=fake_extractor, policy=UrlPolicy(public_resolver))
```
(Imports go at the top of the file in the final version; `pytest` is already imported.)

- [ ] **Step 2: Write failing tests**

`tests/test_service.py`:
```python
from __future__ import annotations

import asyncio
import threading
from dataclasses import replace

import pytest

from src.config import Limits
from src.errors import DownloaderError, ErrorCode
from src.policy.url_policy import UrlPolicy
from src.service import Caller, build_service
from tests.conftest import public_resolver

WEB = Caller("web:1")
URL = "https://example.com/watch?v=1"


async def run_download(service, caller=WEB, preset="720p"):
    job = await service.start_download(caller, URL, preset)
    return job, await service.wait(job)


async def test_probe_returns_options(service):
    result = await service.probe(URL)
    assert result.title == "Cat video"
    assert [o.id for o in result.options] == ["best", "720p", "480p", "audio-mp3", "audio-m4a"]
    assert not any(o.blocked for o in result.options)


async def test_probe_rejects_private_url(service):
    with pytest.raises(DownloaderError) as error:
        await service.probe("http://127.0.0.1/x")
    assert error.value.code == ErrorCode.BLOCKED_HOST


async def test_download_stores_file_and_reports_done(service, fake_extractor):
    job, final = await run_download(service)

    assert final["type"] == "done"
    assert final["file"]["name"] == "Cat video.mp4"
    assert final["file"]["kind"] == "video"
    assert "/api/files/" in final["file"]["download_url"] and "sig=" in final["file"]["download_url"]
    stored = service.get_file(WEB, final["file_id"])
    assert service.file_path(stored).read_bytes() == fake_extractor.content
    types = [e["type"] for e in job.events]
    assert types[0] == "queued" and "progress" in types and "processing" in types and types[-1] == "done"
    assert fake_extractor.calls == [(URL, "720p")]


async def test_audio_preset_makes_audio_file(service):
    _, final = await run_download(service, preset="audio-mp3")
    assert final["file"]["kind"] == "audio" and final["file"]["name"].endswith(".mp3")
    assert final["file"]["mime"] == "audio/mpeg"


async def test_scratch_dir_is_removed(service, settings):
    await run_download(service)
    work = settings.store_dir / "_work"
    assert not work.exists() or not any(work.iterdir())


async def test_unknown_preset_rejected_before_job(service):
    with pytest.raises(DownloaderError) as error:
        await service.start_download(WEB, URL, "8k")
    assert error.value.code == ErrorCode.INVALID_REQUEST


async def test_preset_not_offered_by_site_is_an_error_event(service, fake_extractor):
    fake_extractor.info = replace(fake_extractor.info, formats=fake_extractor.info.formats[:1] + fake_extractor.info.formats[2:])
    _, final = await run_download(service, preset="720p")  # only 360p exists
    assert final["code"] == "invalid_request"


async def test_too_long_video_is_refused(settings, fake_extractor):
    limits = replace(settings.limits, max_duration_seconds=30)
    service = build_service(replace(settings, limits=limits), extractor=fake_extractor, policy=UrlPolicy(public_resolver))
    _, final = await run_download(service)
    assert final["code"] == "too_long" and fake_extractor.calls == []


async def test_too_large_estimate_is_refused(settings, fake_extractor):
    limits = replace(settings.limits, max_file_bytes=1_000_000)
    service = build_service(replace(settings, limits=limits), extractor=fake_extractor, policy=UrlPolicy(public_resolver))
    _, final = await run_download(service)  # 720p estimate is about 12 MB
    assert final["code"] == "too_large" and fake_extractor.calls == []


async def test_session_quota_refused_before_download(settings, fake_extractor):
    limits = replace(settings.limits, max_session_bytes=2_000_000)
    service = build_service(replace(settings, limits=limits), extractor=fake_extractor, policy=UrlPolicy(public_resolver))
    _, final = await run_download(service)
    assert final["code"] == "limit_exceeded" and fake_extractor.calls == []


async def test_extractor_error_becomes_error_event(service, fake_extractor):
    fake_extractor.download_error = DownloaderError(ErrorCode.LOGIN_REQUIRED, "Needs login.")
    _, final = await run_download(service)
    assert final == {"type": "error", "code": "login_required", "message": "Needs login."}


async def test_probe_error_inside_job_is_reported(service, fake_extractor):
    fake_extractor.probe_error = DownloaderError(ErrorCode.UNSUPPORTED_SITE, "No.")
    _, final = await run_download(service)
    assert final["code"] == "unsupported_site"


async def test_cancel_running_download(service, fake_extractor):
    fake_extractor.hold = threading.Event()
    job = await service.start_download(WEB, URL, "720p")
    for _ in range(200):
        if fake_extractor.calls:
            break
        await asyncio.sleep(0.01)
    service.cancel_job(WEB, job.id)
    final = await service.wait(job)
    assert final["code"] == "cancelled"


async def test_job_status_progress_done_and_error(service, fake_extractor):
    job, _ = await run_download(service)
    status = service.job_status(WEB, job.id)
    assert status.state == "done" and status.file is not None and status.file.name == "Cat video.mp4"

    fake_extractor.download_error = DownloaderError(ErrorCode.EXTRACTOR_FAILED, "Broken.")
    job2, _ = await run_download(service)
    status2 = service.job_status(WEB, job2.id)
    assert status2.state == "error" and status2.error.code == "extractor_failed"


async def test_files_are_session_scoped_privileged_sees_any(service):
    _, final = await run_download(service)
    other = Caller("web:2")
    assert service.list_files(other) == []
    with pytest.raises(DownloaderError):
        service.get_file(other, final["file_id"])
    assert service.get_file(Caller("mcp:x", privileged=True), final["file_id"]).file_id == final["file_id"]


async def test_other_session_cannot_see_job(service):
    job, _ = await run_download(service)
    with pytest.raises(DownloaderError) as error:
        service.get_job(Caller("web:2"), job.id)
    assert error.value.code == ErrorCode.JOB_NOT_FOUND


async def test_signed_download_checks_signature(service):
    _, final = await run_download(service)
    url = final["file"]["download_url"]
    query = dict(p.split("=") for p in url.split("?", 1)[1].split("&"))
    assert service.file_for_download(final["file_id"], int(query["exp"]), query["sig"]).file_id == final["file_id"]
    with pytest.raises(DownloaderError) as error:
        service.file_for_download(final["file_id"], int(query["exp"]), "bad")
    assert error.value.code == ErrorCode.FILE_NOT_FOUND


async def test_delete_file(service):
    _, final = await run_download(service)
    await service.delete_file(WEB, final["file_id"])
    assert service.list_files(WEB) == []
```

- [ ] **Step 3: Run to verify failure**

Run: `.venv_video_downloader/Scripts/python -m pytest tests/test_service.py -q`
Expected: ERROR `No module named 'src.service'` (or missing `build_service`).

- [ ] **Step 4: Implement models and service**

Append to `src/models.py`:
```python
from src.store.file_store import StoredFile  # noqa: E402  (kept at the bottom to keep the top of the file model-only)


class FileInfo(BaseModel):
    file_id: str
    name: str
    kind: str  # "video" or "audio"
    mime: str
    size: int
    duration: float | None = None
    expires_at: float
    download_url: str

    @classmethod
    def of(cls, stored: StoredFile, download_url: str) -> FileInfo:
        return cls(
            file_id=stored.file_id,
            name=stored.name,
            kind=stored.kind,
            mime=stored.mime,
            size=stored.size,
            duration=stored.duration,
            expires_at=stored.expires_at,
            download_url=download_url,
        )


class ErrorInfo(BaseModel):
    code: str
    message: str


class JobStatus(BaseModel):
    job_id: str
    state: str  # queued | downloading | processing | done | error
    percent: float | None = None
    speed: float | None = None
    eta: float | None = None
    file: FileInfo | None = None
    error: ErrorInfo | None = None


class ProbeRequest(BaseModel):
    url: str


class DownloadRequest(BaseModel):
    url: str
    preset: str
```

`src/service.py`:
```python
"""DownloadService: the one facade the REST routers and MCP tools call.

It composes the URL policy, extractor, file store, job queue and link signer.
Routers and tools hold no logic of their own.
"""

from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from src.config import Limits, Settings
from src.errors import DownloaderError, ErrorCode
from src.extractor.base import Extractor
from src.extractor.models import DownloadProgress, MediaInfo
from src.extractor.options import available_presets, build_options, estimate_size
from src.extractor.presets import Preset, get_preset
from src.jobs.job_queue import Emit, Job, JobQueue
from src.models import ErrorInfo, FileInfo, JobStatus, ProbeResult
from src.policy.url_policy import UrlPolicy
from src.store.file_store import FileStore, StoredFile
from src.store.names import mime_for, safe_filename
from src.store.signing import LinkSigner

_STATE_BY_EVENT = {"queued": "queued", "progress": "downloading", "processing": "processing", "done": "done", "error": "error"}


@dataclass(frozen=True)
class Caller:
    """Who is asking. ``privileged`` callers (internal token) may open any file by ID."""

    session: str
    privileged: bool = False

    @property
    def scope(self) -> str | None:
        return None if self.privileged else self.session


class DownloadService:
    """Facade over probing, downloading, files, jobs and signed download links."""

    def __init__(
        self,
        *,
        store: FileStore,
        extractor: Extractor,
        policy: UrlPolicy,
        jobs: JobQueue,
        signer: LinkSigner,
        limits: Limits,
        public_base_url: str,
        file_ttl_seconds: int,
    ) -> None:
        self._store = store
        self._extractor = extractor
        self._policy = policy
        self._jobs = jobs
        self._signer = signer
        self._limits = limits
        self._public_base_url = public_base_url.rstrip("/")
        self._file_ttl = file_ttl_seconds

    @property
    def store(self) -> FileStore:
        return self._store

    # --- probing -----------------------------------------------------------

    async def probe(self, url: str) -> ProbeResult:
        clean = await self._policy.check(url)
        info = await asyncio.to_thread(self._extractor.probe, clean)
        return ProbeResult(
            url=clean,
            title=info.title,
            duration=info.duration,
            thumbnail=info.thumbnail,
            uploader=info.uploader,
            options=build_options(info, self._limits),
        )

    # --- downloading -------------------------------------------------------

    async def start_download(self, caller: Caller, url: str, preset_id: str) -> Job:
        """Validate cheaply, then queue the job. Probe-based caps are checked again inside the job."""
        preset = get_preset(preset_id)
        clean = await self._policy.check(url)

        async def work(emit: Emit, cancel: threading.Event) -> dict:
            return await self._run_download(caller.session, clean, preset, emit, cancel)

        return self._jobs.submit(caller.session, work)

    def _enforce_caps(self, info: MediaInfo, preset: Preset, session: str) -> None:
        """Re-check everything the probe showed; never trust what the client saw earlier."""
        if preset.id not in {p.id for p in available_presets(info)}:
            raise DownloaderError(ErrorCode.INVALID_REQUEST, "This video isn't available in that quality. Probe it again and pick another.")
        if info.duration is not None and info.duration > self._limits.max_duration_seconds:
            raise DownloaderError(
                ErrorCode.TOO_LONG, f"Videos longer than {int(self._limits.max_duration_seconds // 60)} minutes are not allowed."
            )
        estimate = estimate_size(info, preset)
        if estimate is None:
            return
        if estimate > self._limits.max_file_bytes:
            raise DownloaderError(
                ErrorCode.TOO_LARGE,
                f"This would be about {estimate // (1024 * 1024)} MB; the limit is {self._limits.max_file_bytes // (1024 * 1024)} MB. Pick a lower quality.",
            )
        if self._store.session_usage(session) + estimate > self._limits.max_session_bytes:
            raise DownloaderError(
                ErrorCode.LIMIT_EXCEEDED, "Your files would use more space than allowed. Delete some files or wait for them to expire."
            )

    async def _run_download(self, session: str, url: str, preset: Preset, emit: Emit, cancel: threading.Event) -> dict:
        info = await asyncio.to_thread(self._extractor.probe, url)
        self._enforce_caps(info, preset, session)

        def on_progress(progress: DownloadProgress) -> None:
            if progress.stage == "processing":
                emit({"type": "processing"})
            else:
                emit({"type": "progress", "percent": progress.percent, "speed": progress.speed, "eta": progress.eta})

        work_dir = await self._store.make_work_dir()
        try:
            downloaded = await asyncio.to_thread(
                self._extractor.download,
                url,
                preset,
                work_dir,
                max_bytes=self._limits.max_file_bytes,
                on_progress=on_progress,
                cancel=cancel,
            )
            suffix = downloaded.path.suffix
            stored = await self._store.commit_file(
                session,
                downloaded.path,
                name=safe_filename(info.title, "video") + suffix,
                mime=mime_for(suffix),
                kind=preset.kind,
                duration=info.duration,
            )
        finally:
            await self._store.remove_work_dir(work_dir)
        file = self.file_info(stored)
        return {"file_id": stored.file_id, "file": file.model_dump(mode="json")}

    # --- jobs --------------------------------------------------------------

    def get_job(self, caller: Caller, job_id: str) -> Job:
        return self._jobs.get(job_id, caller.scope)

    def cancel_job(self, caller: Caller, job_id: str) -> None:
        self._jobs.cancel(self.get_job(caller, job_id))

    async def wait(self, job: Job) -> dict:
        return await self._jobs.wait(job)

    def job_status(self, caller: Caller, job_id: str) -> JobStatus:
        job = self.get_job(caller, job_id)
        last = job.events[-1] if job.events else {"type": "queued"}
        status = JobStatus(job_id=job.id, state=_STATE_BY_EVENT.get(last["type"], "queued"))
        progress = next((e for e in reversed(job.events) if e["type"] == "progress"), None)
        if progress:
            status.percent, status.speed, status.eta = progress.get("percent"), progress.get("speed"), progress.get("eta")
        if last["type"] == "done":
            status.percent = 100.0
            status.file = self.file_info(self._store.get(last["file_id"], None))  # fresh signed link
        elif last["type"] == "error":
            status.error = ErrorInfo(code=last["code"], message=last["message"])
        return status

    # --- files -------------------------------------------------------------

    def file_info(self, stored: StoredFile) -> FileInfo:
        exp, sig = self._signer.sign(stored.file_id)
        url = f"{self._public_base_url}/api/files/{stored.file_id}/download?exp={exp}&sig={sig}"
        return FileInfo.of(stored, url)

    def list_files(self, caller: Caller) -> list[StoredFile]:
        return self._store.list(caller.session)

    def get_file(self, caller: Caller, file_id: str) -> StoredFile:
        return self._store.get(file_id, caller.scope)

    def file_path(self, file: StoredFile) -> Path:
        return self._store.path(file)

    async def delete_file(self, caller: Caller, file_id: str) -> None:
        """Callers delete only their own files, even privileged ones."""
        await self._store.delete(file_id, caller.session)

    def file_for_download(self, file_id: str, exp: int, sig: str) -> StoredFile:
        if not self._signer.verify(file_id, exp, sig):
            raise DownloaderError(ErrorCode.FILE_NOT_FOUND, "This download link is invalid or has expired.")
        return self._store.get(file_id, None)

    async def sweep(self) -> int:
        """Delete expired files and forget old finished jobs."""
        self._jobs.prune(older_than=time.time() - self._file_ttl)
        return await self._store.sweep()


def build_service(settings: Settings, *, extractor: Extractor | None = None, policy: UrlPolicy | None = None) -> DownloadService:
    """Wire the real collaborators; tests pass a fake extractor and policy."""
    if extractor is None:
        from src.extractor.ytdlp import YtDlpExtractor

        extractor = YtDlpExtractor()
    limits = settings.limits
    return DownloadService(
        store=FileStore(
            settings.store_dir,
            ttl_seconds=settings.file_ttl_seconds,
            max_file_bytes=limits.max_file_bytes,
            max_session_bytes=limits.max_session_bytes,
        ),
        extractor=extractor,
        policy=policy or UrlPolicy(),
        jobs=JobQueue(limits.max_concurrent_downloads, limits.max_queued_downloads, limits.job_timeout_seconds),
        signer=LinkSigner(settings.signing_key, settings.download_link_seconds),
        limits=limits,
        public_base_url=settings.public_base_url,
        file_ttl_seconds=settings.file_ttl_seconds,
    )
```

Note: the `models.py` import of `StoredFile` must not create a cycle: `file_store.py` imports only `config` and `errors`, so it is safe.

- [ ] **Step 5: Run tests**

Run: `.venv_video_downloader/Scripts/python -m pytest -q`
Expected: all pass. Notes for the executor: `test_too_large_estimate_is_refused` relies on the 720p estimate being 60 s x 1500 kbit/s = 11.25 MB (video format has audio) and `test_session_quota_refused_before_download` on the same estimate exceeding 2 MB; adjust numbers in the test only if the fake formats change.

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "feat(service): DownloadService facade with caps, jobs and signed links"
```

---

### Task 8: REST API, app factory, run entry

**Files:**
- Create: `src/internal_token.py`, `src/api/__init__.py` (empty), `src/api/deps.py`, `src/api/probe.py`, `src/api/downloads.py`, `src/api/files.py`, `src/app.py`, `src/run.py`
- Test: `tests/test_internal_token.py`, `tests/test_api.py`, `tests/test_health.py`

**Interfaces:**
- Consumes: `DownloadService`, `Caller`, `build_service`, models, `run_sweeper`, `require_ffmpeg`, `find_ffmpeg`, `ytdlp_version`.
- Produces: `create_app(settings, service=None) -> FastAPI`. Routes: `POST /api/probe`, `POST /api/downloads` (202 `{job_id}`), `GET /api/jobs/{id}`, `GET /api/jobs/{id}/events` (SSE), `POST /api/jobs/{id}/cancel` (202), `GET /api/files`, `DELETE /api/files/{id}`, `GET /api/files/{id}/download?exp=&sig=`, `GET /api/health`. Cookie `vd_session`. `InternalTokenMiddleware(app, token)`. `build_mcp` is wired in Task 9 (this task mounts nothing at `/`).

- [ ] **Step 1: Write failing tests**

`tests/test_internal_token.py`:
```python
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.internal_token import InternalTokenMiddleware


def make_client(token: str) -> TestClient:
    app = FastAPI()

    @app.get("/mcp")
    async def mcp():
        return {"ok": True}

    @app.get("/api/x")
    async def other():
        return {"ok": True}

    app.add_middleware(InternalTokenMiddleware, token=token)
    return TestClient(app)


def test_mcp_requires_the_token():
    client = make_client("secret")
    assert client.get("/mcp").status_code == 401
    assert client.get("/mcp", headers={"X-Internal-Token": "wrong"}).status_code == 401
    assert client.get("/mcp", headers={"X-Internal-Token": "secret"}).status_code == 200


def test_unset_token_refuses_everything_on_mcp():
    client = make_client("")
    assert client.get("/mcp", headers={"X-Internal-Token": ""}).status_code == 401


def test_other_paths_are_open():
    assert make_client("secret").get("/api/x").status_code == 200
```

`tests/test_health.py`:
```python
from fastapi.testclient import TestClient

from src.app import create_app


def test_health_reports_versions(settings, service):
    with TestClient(create_app(settings, service)) as client:
        body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["yt_dlp"]
    assert isinstance(body["ffmpeg"], bool)
```

`tests/test_api.py`:
```python
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from src.app import create_app
from src.errors import DownloaderError, ErrorCode
from tests.conftest import TEST_TOKEN

URL = "https://example.com/watch?v=1"


@pytest.fixture
def app(settings, service):
    return create_app(settings, service)


@pytest.fixture
def client(app):
    with TestClient(app) as test_client:
        yield test_client


def events(client: TestClient, job_id: str) -> list[dict]:
    with client.stream("GET", f"/api/jobs/{job_id}/events") as response:
        assert response.headers["content-type"].startswith("text/event-stream")
        body = "".join(response.iter_text())
    return [json.loads(line[len("data: "):]) for line in body.splitlines() if line.startswith("data: ")]


def download(client: TestClient, preset: str = "720p", headers: dict | None = None) -> dict:
    response = client.post("/api/downloads", json={"url": URL, "preset": preset}, headers=headers or {})
    assert response.status_code == 202
    return response.json()


def test_probe_returns_title_and_options(client):
    response = client.post("/api/probe", json={"url": URL})
    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "Cat video"
    assert [o["id"] for o in body["options"]][:2] == ["best", "720p"]


def test_probe_private_url_is_403_blocked_host(client):
    response = client.post("/api/probe", json={"url": "http://127.0.0.1/x"})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "blocked_host"


def test_probe_extractor_error_keeps_its_code(client, fake_extractor):
    fake_extractor.probe_error = DownloaderError(ErrorCode.UNSUPPORTED_SITE, "No.")
    response = client.post("/api/probe", json={"url": URL})
    assert response.status_code == 422 and response.json()["error"]["code"] == "unsupported_site"


def test_validation_error_uses_error_body(client):
    response = client.post("/api/probe", json={})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"


def test_download_flow_over_sse_then_download_the_file(client, fake_extractor):
    job = download(client)
    got = events(client, job["job_id"])
    assert got[0]["type"] == "queued" and got[-1]["type"] == "done"
    file = got[-1]["file"]
    assert "vd_session" in client.cookies

    assert [f["file_id"] for f in client.get("/api/files").json()] == [file["file_id"]]
    path = file["download_url"].split("/api/", 1)[1]
    response = client.get("/api/" + path)
    assert response.status_code == 200
    assert response.content == fake_extractor.content
    assert response.headers["content-disposition"].startswith("attachment;")
    assert response.headers["x-content-type-options"] == "nosniff"


def test_job_status_endpoint(client):
    job = download(client)
    events(client, job["job_id"])
    body = client.get(f"/api/jobs/{job['job_id']}").json()
    assert body["state"] == "done" and body["file"]["name"] == "Cat video.mp4"


def test_other_browser_cannot_see_job_or_file(app, client):
    job = download(client)
    final = events(client, job["job_id"])[-1]
    stranger = TestClient(app)
    assert stranger.get("/api/files").json() == []
    assert stranger.get(f"/api/jobs/{job['job_id']}").status_code == 404
    assert stranger.delete(f"/api/files/{final['file_id']}").status_code == 404


def test_download_with_bad_signature_is_404(client):
    job = download(client)
    file = events(client, job["job_id"])[-1]["file"]
    bad = f"/api/files/{file['file_id']}/download?exp=9999999999&sig=nope"
    assert client.get(bad).status_code == 404


def test_delete_file(client):
    job = download(client)
    file_id = events(client, job["job_id"])[-1]["file_id"]
    assert client.delete(f"/api/files/{file_id}").status_code == 204
    assert client.get("/api/files").json() == []


def test_cancel_endpoint(client, fake_extractor):
    import threading

    fake_extractor.hold = threading.Event()
    job = download(client)
    assert client.post(f"/api/jobs/{job['job_id']}/cancel").status_code == 202
    assert events(client, job["job_id"])[-1]["code"] == "cancelled"


def test_token_caller_acts_as_mcp_user_and_sees_any_file(client):
    job = download(client)
    file_id = events(client, job["job_id"])[-1]["file_id"]
    privileged = {"X-Internal-Token": TEST_TOKEN, "X-Requester-Username": "alice"}
    assert client.get("/api/files", headers=privileged).json() == []  # own mcp session is empty
    assert client.get(f"/api/jobs/{job['job_id']}", headers=privileged).status_code == 200  # privileged callers see any job
    assert client.delete(f"/api/files/{file_id}", headers=privileged).status_code == 404  # delete only your own
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv_video_downloader/Scripts/python -m pytest tests/test_internal_token.py tests/test_health.py tests/test_api.py -q`
Expected: ERROR `No module named 'src.internal_token'` / `src.app`.

- [ ] **Step 3: Implement**

`src/internal_token.py`:
```python
"""Require X-Internal-Token on /mcp (copied from pdf_merger's internal_token.py;
the repo forbids cross-project imports).

An unset token rejects every /mcp call, so a fresh install never exposes tools by accident.
"""

from __future__ import annotations

import hmac
import json

INTERNAL_TOKEN_HEADER = b"x-internal-token"
PROTECTED_PATH = "/mcp"


class InternalTokenMiddleware:
    """Plain ASGI middleware: 401 JSON for /mcp without the right token. Other paths pass through."""

    def __init__(self, app, token: str) -> None:
        self.app = app
        self._token = token.encode("utf-8")

    def _protects(self, scope) -> bool:
        if scope["type"] != "http":
            return False
        path = scope.get("path", "")
        return path == PROTECTED_PATH or path.startswith(PROTECTED_PATH + "/")

    async def __call__(self, scope, receive, send):
        if self._protects(scope):
            provided = dict(scope.get("headers") or []).get(INTERNAL_TOKEN_HEADER, b"")
            if not self._token or not hmac.compare_digest(self._token, provided):
                body = json.dumps({"error": {"code": "unauthorized", "message": "Invalid or missing internal API token."}}).encode()
                await send(
                    {
                        "type": "http.response.start",
                        "status": 401,
                        "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())],
                    }
                )
                await send({"type": "http.response.body", "body": body})
                return
        await self.app(scope, receive, send)
```

`src/api/deps.py`:
```python
"""Request-scoped dependencies: the service and who is calling."""

from __future__ import annotations

import hmac
import re
import secrets

from fastapi import Request, Response

from src.service import Caller, DownloadService

COOKIE_NAME = "vd_session"
TOKEN_HEADER = "X-Internal-Token"
REQUESTER_HEADER = "X-Requester-Username"
_SESSION_RE = re.compile(r"[A-Za-z0-9_-]{32}")


def get_service(request: Request) -> DownloadService:
    return request.app.state.service


def _token_valid(request: Request) -> bool:
    """Constant-time compare. An unset expected token never validates."""
    expected = request.app.state.settings.internal_api_token
    provided = request.headers.get(TOKEN_HEADER, "")
    return bool(expected) and hmac.compare_digest(expected.encode("utf-8"), provided.encode("utf-8", "replace"))


def get_caller(request: Request, response: Response) -> Caller:
    if _token_valid(request):
        username = request.headers.get(REQUESTER_HEADER, "").strip() or "anonymous"
        return Caller(session=f"mcp:{username}", privileged=True)

    session_id = request.cookies.get(COOKIE_NAME, "")
    if not _SESSION_RE.fullmatch(session_id):
        session_id = secrets.token_urlsafe(24)  # 32 URL-safe characters
    # Sliding session: re-set the cookie on every request so it lives as long as the files do.
    response.set_cookie(
        COOKIE_NAME,
        session_id,
        max_age=request.app.state.settings.file_ttl_seconds,
        httponly=True,
        samesite="strict",
    )
    return Caller(session=f"web:{session_id}")
```

`src/api/probe.py`:
```python
"""POST /api/probe: look a link up before downloading."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from src.api.deps import get_service
from src.models import ProbeRequest, ProbeResult
from src.service import DownloadService

router = APIRouter(prefix="/api")


@router.post("/probe")
async def probe(body: ProbeRequest, service: DownloadService = Depends(get_service)) -> ProbeResult:
    return await service.probe(body.url)
```

`src/api/downloads.py`:
```python
"""Download routes: start a job, then follow it over server-sent events."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from src.api.deps import get_caller, get_service
from src.models import DownloadRequest, JobStatus
from src.service import Caller, DownloadService

router = APIRouter(prefix="/api")


@router.post("/downloads", status_code=202)
async def start_download(
    body: DownloadRequest, caller: Caller = Depends(get_caller), service: DownloadService = Depends(get_service)
) -> dict:
    job = await service.start_download(caller, body.url, body.preset)
    return {"job_id": job.id}


@router.get("/jobs/{job_id}")
async def job_status(
    job_id: str, caller: Caller = Depends(get_caller), service: DownloadService = Depends(get_service)
) -> JobStatus:
    return service.job_status(caller, job_id)


@router.post("/jobs/{job_id}/cancel", status_code=202)
async def cancel_job(
    job_id: str, caller: Caller = Depends(get_caller), service: DownloadService = Depends(get_service)
) -> dict:
    service.cancel_job(caller, job_id)
    return {"job_id": job_id}


@router.get("/jobs/{job_id}/events")
async def job_events(
    job_id: str, caller: Caller = Depends(get_caller), service: DownloadService = Depends(get_service)
) -> StreamingResponse:
    job = service.get_job(caller, job_id)

    async def body() -> AsyncIterator[str]:
        async for event in job.stream():
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(
        body(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )
```

`src/api/files.py`:
```python
"""File routes: list, delete and signed download."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from fastapi.responses import FileResponse

from src.api.deps import get_caller, get_service
from src.models import FileInfo
from src.service import Caller, DownloadService
from src.store.names import content_disposition

router = APIRouter(prefix="/api")
_NOSNIFF = {"X-Content-Type-Options": "nosniff"}


@router.get("/files")
async def list_files(caller: Caller = Depends(get_caller), service: DownloadService = Depends(get_service)) -> list[FileInfo]:
    return [service.file_info(f) for f in service.list_files(caller)]


@router.delete("/files/{file_id}", status_code=204)
async def delete_file(
    file_id: str, caller: Caller = Depends(get_caller), service: DownloadService = Depends(get_service)
) -> Response:
    await service.delete_file(caller, file_id)
    return Response(status_code=204)


@router.get("/files/{file_id}/download")
async def download(file_id: str, exp: int, sig: str, service: DownloadService = Depends(get_service)) -> FileResponse:
    """Signed link; no cookie needed. FileResponse honours Range requests, so players can seek."""
    file = service.file_for_download(file_id, exp, sig)
    return FileResponse(
        service.file_path(file),
        media_type=file.mime,
        headers={"Content-Disposition": content_disposition(file.name), "Cache-Control": "private, no-store", **_NOSNIFF},
    )
```

`src/app.py`:
```python
"""FastAPI application factory: routers, error handlers, CORS and the sweeper."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.api import downloads, files, probe
from src.config import Settings
from src.errors import DownloaderError, ErrorCode
from src.internal_token import InternalTokenMiddleware
from src.service import DownloadService, build_service
from src.store.sweeper import run_sweeper
from src.system_info import find_ffmpeg, ytdlp_version

logger = logging.getLogger(__name__)


def create_app(settings: Settings, service: DownloadService | None = None) -> FastAPI:
    service = service or build_service(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await service.store.load_index()
        stop = asyncio.Event()
        sweeper = asyncio.create_task(run_sweeper(service, settings.sweep_interval_seconds, stop))
        try:
            yield
        finally:
            stop.set()
            await sweeper

    app = FastAPI(title="video_downloader", lifespan=lifespan)
    app.state.settings = settings
    app.state.service = service

    @app.exception_handler(DownloaderError)
    async def downloader_error(_: Request, error: DownloaderError) -> JSONResponse:
        return JSONResponse(error.to_body(), status_code=error.http_status)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, error: RequestValidationError) -> JSONResponse:
        first = error.errors()[0] if error.errors() else {}
        where = ".".join(str(part) for part in first.get("loc", ()) if part != "body")
        message = f"{where}: {first.get('msg', 'invalid value')}" if where else str(first.get("msg", "Invalid request."))
        return JSONResponse(DownloaderError(ErrorCode.INVALID_REQUEST, message).to_body(), status_code=422)

    @app.exception_handler(Exception)
    async def unexpected_error(_: Request, error: Exception) -> JSONResponse:
        logger.error("Unhandled error", exc_info=error)
        body = DownloaderError(ErrorCode.INTERNAL, "Something went wrong on the server. Try again.").to_body()
        return JSONResponse(body, status_code=500)

    @app.get("/api/health")
    async def health() -> dict:
        return {"status": "ok", "yt_dlp": ytdlp_version(), "ffmpeg": find_ffmpeg() is not None}

    app.include_router(probe.router)
    app.include_router(downloads.router)
    app.include_router(files.router)
    app.add_middleware(InternalTokenMiddleware, token=settings.internal_api_token)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.web_origin],
        allow_credentials=True,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Content-Type"],
    )
    return app
```

`src/run.py`:
```python
"""video_downloader entry point: ``py -m src.run`` (see run.bat)."""

from __future__ import annotations

import sys

import uvicorn

from src.app import create_app
from src.config import load_settings
from src.errors import DownloaderError
from src.logging_setup import configure_logging
from src.system_info import require_ffmpeg


def main() -> None:
    try:
        require_ffmpeg()
    except DownloaderError as error:
        print(f"video_downloader cannot start: {error.message}", file=sys.stderr)
        raise SystemExit(1) from None
    settings = load_settings()
    configure_logging(settings.log_dir)
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests**

Run: `.venv_video_downloader/Scripts/python -m pytest -q`
Expected: all pass.

- [ ] **Step 5: Smoke-start the real service**

Run (background, from `video_downloader/`): `.venv_video_downloader/Scripts/python -m src.run`, then `curl -s http://127.0.0.1:8050/api/health`.
Expected: `{"status":"ok","yt_dlp":"2026.08.19","ffmpeg":true}`. Stop the server afterwards. This creates `video_downloader/configs/config_video_downloader.json` and the repo-root `.env` from their `.example` twins (both gitignored).

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "feat(api): REST routes, SSE job events, signed downloads, app factory"
```

---

### Task 9: MCP tools

**Files:**
- Create: `src/mcp_tools/__init__.py` (empty), `src/mcp_tools/contract.py`, `src/mcp_tools/tools.py`
- Modify: `src/app.py` (mount MCP, run its session manager)
- Test: `tests/test_mcp_tools.py`; extend `tests/test_api.py` with an `/mcp` auth test

**Interfaces:**
- Consumes: `DownloadService`, `Caller`, models.
- Produces: `build_mcp(service) -> FastMCP`; `caller_from_context(ctx) -> Caller`; tools `tool_video_probe(url)`, `tool_video_download(url, preset)`, `tool_video_status(job_id)`, `tool_video_listFiles()`; result models `ProbeToolResult`, `DownloadStarted`, `StatusToolResult`, `ListFilesResult`, each with `message`.

- [ ] **Step 1: Write failing tests**

`tests/test_mcp_tools.py`:
```python
from __future__ import annotations

from types import SimpleNamespace

import pytest
from mcp.server.fastmcp.exceptions import ToolError

from src.mcp_tools.tools import build_mcp, caller_from_context
from src.service import Caller

URL = "https://example.com/watch?v=1"


async def test_tools_are_listed_with_labels_and_keywords(service):
    tools = {tool.name: tool for tool in await build_mcp(service).list_tools()}
    assert set(tools) == {"tool_video_probe", "tool_video_download", "tool_video_status", "tool_video_listFiles"}
    for tool in tools.values():
        assert tool.meta["display_label"]
        assert tool.meta["keywords"]


async def test_probe_lists_presets(service):
    _, result = await build_mcp(service).call_tool("tool_video_probe", {"url": URL})
    assert result["title"] == "Cat video"
    assert "720p" in [o["id"] for o in result["options"]]
    assert "Cat video" in result["message"]


async def test_download_returns_job_id_immediately_then_status_reaches_done(service):
    mcp = build_mcp(service)
    _, started = await mcp.call_tool("tool_video_download", {"url": URL, "preset": "720p"})
    job_id = started["job_id"]
    assert job_id.startswith("j_")

    caller = Caller("mcp:anonymous", privileged=True)
    await service.wait(service.get_job(caller, job_id))
    _, status = await mcp.call_tool("tool_video_status", {"job_id": job_id})
    assert status["state"] == "done"
    assert "/api/files/" in status["file"]["download_url"]
    assert "download_url" in status["message"]


async def test_status_of_unknown_job_is_a_tool_error_with_code(service):
    with pytest.raises(ToolError) as error:
        await build_mcp(service).call_tool("tool_video_status", {"job_id": "j_nope"})
    assert "job_not_found" in str(error.value)


async def test_download_of_private_url_is_a_tool_error(service):
    with pytest.raises(ToolError) as error:
        await build_mcp(service).call_tool("tool_video_download", {"url": "http://127.0.0.1/x", "preset": "best"})
    assert "blocked_host" in str(error.value)


async def test_list_files_without_request_context_is_anonymous(service):
    _, result = await build_mcp(service).call_tool("tool_video_listFiles", {})
    assert result["files"] == []
    assert result["message"] == "0 file(s)."


def test_caller_from_meta_then_header_then_anonymous():
    def ctx(meta_extra=None, headers=None):
        meta = SimpleNamespace(model_extra=meta_extra) if meta_extra is not None else None
        request = SimpleNamespace(headers=headers or {}) if headers is not None else None
        return SimpleNamespace(request_context=SimpleNamespace(meta=meta, request=request))

    assert caller_from_context(ctx({"requester": {"username": "alice"}}, {"x-requester-username": "bob"})) == Caller("mcp:alice", True)
    assert caller_from_context(ctx(None, {"x-requester-username": "bob"})) == Caller("mcp:bob", True)
    assert caller_from_context(ctx(None, {})) == Caller("mcp:anonymous", True)
```

Append to `tests/test_api.py`:
```python
def test_mcp_endpoint_requires_internal_token(client):
    assert client.post("/mcp", json={}).status_code == 401
    assert client.post("/mcp", json={}, headers={"X-Internal-Token": "wrong"}).status_code == 401
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv_video_downloader/Scripts/python -m pytest tests/test_mcp_tools.py -q`
Expected: ERROR `No module named 'src.mcp_tools'`.

- [ ] **Step 3: Implement**

`src/mcp_tools/contract.py`:
```python
"""MCP tool result models. Each ends with a human-readable ``message``."""

from __future__ import annotations

from pydantic import BaseModel

from src.models import FileInfo, JobStatus, ProbeResult


class ProbeToolResult(ProbeResult):
    message: str


class DownloadStarted(BaseModel):
    job_id: str
    message: str


class StatusToolResult(JobStatus):
    message: str


class ListFilesResult(BaseModel):
    files: list[FileInfo]
    message: str
```

`src/mcp_tools/tools.py`:
```python
"""MCP tools: thin glue over DownloadService. No logic and no AI calls here.

Who is asking comes from the request's _meta.requester (set by ai_agent and
forwarded by mcp_server), else the X-Requester-Username header, else
"anonymous". It is never a tool parameter, so a model cannot pick it.

No tool waits for a download: start_download returns a job ID at once and the
agent polls tool_video_status, staying under the ~120 s client limit.
"""

from __future__ import annotations

from typing import Annotated, Any

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import Field

from src.errors import DownloaderError
from src.mcp_tools.contract import DownloadStarted, ListFilesResult, ProbeToolResult, StatusToolResult
from src.service import Caller, DownloadService

REQUESTER_META_KEY = "requester"


def caller_from_context(ctx: Any) -> Caller:
    username = ""
    try:
        request_context = ctx.request_context
    except (ValueError, LookupError):
        request_context = None  # called outside an MCP request (tests, direct calls)
    if request_context is not None:
        meta = getattr(request_context, "meta", None)
        requester = (getattr(meta, "model_extra", None) or {}).get(REQUESTER_META_KEY) if meta is not None else None
        if isinstance(requester, dict) and isinstance(requester.get("username"), str):
            username = requester["username"]
        request = getattr(request_context, "request", None)
        if not username and request is not None:
            username = request.headers.get("x-requester-username", "")
    return Caller(session=f"mcp:{username.strip() or 'anonymous'}", privileged=True)


def _tool_error(error: DownloaderError) -> ToolError:
    return ToolError(f"{error.code}: {error.message}")


def build_mcp(service: DownloadService) -> FastMCP:
    # The internal token protects /mcp, so DNS-rebinding host checks would only
    # block legitimate LAN callers that reach this server by IP.
    mcp = FastMCP(
        "video_downloader",
        stateless_http=True,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )

    @mcp.tool(meta={"keywords": ["video", "youtube", "tiktok", "download", "link", "info"], "display_label": "Checking video link"})
    async def tool_video_probe(url: Annotated[str, Field(description="Link to a single video page (http or https).")]) -> ProbeToolResult:
        """Look up a video link: title, duration, uploader and the quality presets it offers.

        Each option has an id (best, 1080p, 720p, 480p, audio-mp3, audio-m4a), an
        estimated size and, when blocked, a reason (too long, too large). Call this
        before tool_video_download so you only request a preset that is not blocked.
        Playlist links are refused; give the link of one video.
        """
        try:
            result = await service.probe(url)
        except DownloaderError as error:
            raise _tool_error(error) from error
        return ProbeToolResult(**result.model_dump(), message=f"{result.title}: {len(result.options)} quality option(s).")

    @mcp.tool(meta={"keywords": ["video", "audio", "download", "mp3", "mp4", "youtube", "tiktok"], "display_label": "Starting download"})
    async def tool_video_download(
        url: Annotated[str, Field(description="Link to a single video page (http or https).")],
        preset: Annotated[str, Field(description="Quality id from tool_video_probe, e.g. best, 720p, audio-mp3.")],
        ctx: Context,
    ) -> DownloadStarted:
        """Start downloading a video or its audio. Returns a job_id at once; it does not wait.

        Then call tool_video_status with the job_id every few seconds until its state is
        "done" (or "error"). Only download content the user has the right to download.
        """
        try:
            job = await service.start_download(caller_from_context(ctx), url, preset)
        except DownloaderError as error:
            raise _tool_error(error) from error
        return DownloadStarted(job_id=job.id, message=f"Download started. Check tool_video_status with job_id {job.id}.")

    @mcp.tool(meta={"keywords": ["video", "download", "status", "progress", "job"], "display_label": "Checking download"})
    async def tool_video_status(job_id: Annotated[str, Field(description="The job_id from tool_video_download.")], ctx: Context) -> StatusToolResult:
        """Progress of a download job. State is queued, downloading, processing, done or error.

        When done, `file.download_url` is a link valid for about an hour: give it to the
        user. When error, `error.code` and `error.message` say what went wrong.
        """
        try:
            status = service.job_status(caller_from_context(ctx), job_id)
        except DownloaderError as error:
            raise _tool_error(error) from error
        if status.state == "done" and status.file:
            message = f"Done: {status.file.name}. Give the user this download_url: {status.file.download_url}"
        elif status.state == "error" and status.error:
            message = f"Failed ({status.error.code}): {status.error.message}"
        else:
            percent = f" {status.percent:.0f}%" if status.percent is not None else ""
            message = f"State: {status.state}{percent}."
        return StatusToolResult(**status.model_dump(), message=message)

    @mcp.tool(meta={"keywords": ["video", "files", "list", "downloads"], "display_label": "Listing downloads"})
    async def tool_video_listFiles(ctx: Context) -> ListFilesResult:
        """List files this assistant session has downloaded, with fresh download links and expiry.

        Files downloaded in the web app belong to the browser and are not listed here.
        """
        caller = caller_from_context(ctx)
        files = [service.file_info(f) for f in service.list_files(caller)]
        return ListFilesResult(files=files, message=f"{len(files)} file(s).")

    return mcp
```

Modify `src/app.py`:
- add `from src.mcp_tools.tools import build_mcp`
- after `service = service or build_service(settings)` add `mcp = build_mcp(service)` and `mcp_app = mcp.streamable_http_app()  # serves /mcp`
- in `lifespan`, wrap the `yield` in `async with mcp.session_manager.run():`
- after the routers: `app.mount("/", mcp_app)  # after the routers, so /api/* matches first`

(Identical to pdf_merger's `create_app`.)

- [ ] **Step 4: Run tests**

Run: `.venv_video_downloader/Scripts/python -m pytest -q`
Expected: all pass.

- [ ] **Step 5: End-to-end MCP smoke test against the real service**

Start the service (`.venv_video_downloader/Scripts/python -m src.run`) with `INTERNAL_API_TOKEN` set to a throwaway value in the environment (do not print real secrets), then:
```bash
curl -s -X POST http://127.0.0.1:8050/mcp -H "X-Internal-Token: $TOKEN" -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```
Expected: JSON listing the four `tool_video_*` tools. Then `POST /api/probe` with a real public video URL and confirm presets come back. Stop the server.

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "feat(mcp): video probe, download, status and list tools at /mcp"
```

---

## Self-Review

**Spec coverage**
- Layout, units (`policy/`, `extractor/`, `store/`, `jobs/`, `api/`, `mcp_tools/`, facade): Tasks 1-9.
- URL policy + redirect SSRF: Task 2 (guard, redirect test).
- Caps (500 MB, 2 h, 2 concurrent, 2 GB, TTL, link TTL): Task 1 config; enforced Tasks 3, 4, 5 (byte cap), 6 (slots), 7 (caps before download).
- `noplaylist`, playlist link refused: Task 5.
- FFmpeg startup check, health versions: Tasks 5, 8.
- REST endpoints, SSE events, cancel, signed downloads: Task 8. `GET /api/files/{id}/link` replaced by `download_url` (listed deviation).
- MCP tools, no blocking: Task 9.
- Error codes: Task 1, mapped in Task 5, 7.
- yt-dlp pin and `update.bat`: Task 1.
- Web app, mcp_server extension entry, server_launcher, README, vault notes, `_TODO.md` update: plans 2 and 3.

**Placeholder scan:** none found; every step has complete code or exact commands.

**Type consistency:** `Extractor.download(url, preset, work_dir, *, max_bytes, on_progress, cancel)` matches `FakeExtractor`, `YtDlpExtractor` and the service call. `JobQueue(max_concurrent, max_queued, timeout_seconds)` matches `build_service`. `Emit`/`Work` match service `work`. `FileInfo.of(stored, download_url)` matches `service.file_info`. `StoredFile.duration` is used by store, service and tests. Event keys (`file_id`, `file`, `percent`, `speed`, `eta`, `code`, `message`) match between queue, service `job_status`, API tests and MCP tests.
