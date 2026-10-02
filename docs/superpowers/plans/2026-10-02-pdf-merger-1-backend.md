# PDF merger backend (`pdf_merger`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `pdf_merger/`, a FastAPI service that merges PDFs and images into one PDF, with a REST API for the web app and an MCP endpoint for `mcp_server`.

**Architecture:** Small single-purpose units (page-range parser, type sniffer, file store, converters, planner, assembler, job queue) composed by one `MergeService`. REST routers and MCP tools are thin and call only `MergeService`. Blocking PDF and image work runs in `asyncio.to_thread`; merges run through a semaphore-limited job queue that publishes progress events.

**Tech Stack:** Python 3.11+, FastAPI, uvicorn, mcp (FastMCP), pikepdf, img2pdf, Pillow, pillow-heif, python-dotenv; pytest, pytest-asyncio, httpx2 (for `starlette.testclient`).

**Spec:** `docs/superpowers/specs/2026-10-02-pdf-merger-design.md`

This is plan 1 of 3. Plan 2 (`2026-10-02-pdf-merger-2-web.md`) builds `pdf_merger_web`. Plan 3 (`2026-10-02-pdf-merger-3-mcp-wiring.md`) changes `mcp_server` and wires everything together.

## Global Constraints

- Working directory for every command: `Python/MCPServer/pdf_merger` unless a step says otherwise. Git commands run in `Python/MCPServer` (the repo root), never in `Python/` or above.
- Repo rule: no imports from `mcp_server`, `chat_app`, `ai_agent` or `ember_api`. Copy small helpers instead.
- Project shape follows `.claude/skills/root-project-scaffold/SKILL.md`, dotted variant: `configs/` tracked, `.secrets/`, `.data/`, `.logs/` untracked (only `.example` twins tracked).
- Default port 8040 (`PDF_MERGER_PORT`). Web origin default `http://127.0.0.1:5174`.
- Limits (defaults): 100 MB per file, 500 MB per session, 50 segments, 2000 output pages, 80 megapixels per image, 2 concurrent merges, 120 s job timeout, 6 h file TTL, sweep every 10 min, download links valid 60 min.
- Error body is always `{"error": {"code": "...", "message": "..."}}`. Codes: `unsupported_type`, `file_too_large`, `encrypted_pdf`, `corrupt_file`, `invalid_range`, `invalid_request`, `file_not_found`, `job_not_found`, `limit_exceeded`, `merge_timeout`, `internal_error`. Raw exception text is never returned.
- MCP tool names: `tool_pdf_inspect`, `tool_pdf_merge`, `tool_pdf_listFiles`. Every tool has `meta.display_label` and `meta.keywords`. Tools never call an AI.
- `/mcp` rejects any call without a valid `X-Internal-Token`. An unset token never validates.
- File IDs: `f_` + 32 lowercase hex chars. Job IDs: `j_` + 24 hex chars.
- User-facing messages: sentence case, say what happened then what to do, no "please", no exclamation marks.
- Code comments and docstrings follow the global coding rules: async I/O, docstrings on classes and public functions.

### Deviations from the spec (decided while planning)

- Upload is a raw request body with the filename in an `X-Filename` header (URL-encoded), not multipart. This streams straight to disk and drops the `python-multipart` dependency.
- The MCP package folder is `src/mcp_tools/`, not `src/mcp/`, so it can never shadow the `mcp` SDK package.
- Two extra error codes: `invalid_request` (malformed JSON body) and `job_not_found`.
- A page may appear only once per output (the planner rejects duplicates with `invalid_range`). Duplicating pages is already deferred in the spec.
- SSE events have no `event:` name; the type lives in the JSON `type` field. A named `error` event would collide with `EventSource`'s own connection `error` event.
- TIFF and GIF inputs use the first frame only.

---

## File map

```
pdf_merger/
  README.md                       Task 10
  pyproject.toml                  Task 1
  run.bat                         Task 1
  configs/config_pdf_merger.json.example   Task 1
  .secrets/secret_internal_api.env.example Task 1
  .secrets/secret_signing.env.example      Task 1
  src/__init__.py                 Task 1
  src/config.py                   Task 1   Settings, Limits, load_settings()
  src/errors.py                   Task 1   ErrorCode, MergerError
  src/logging_setup.py            Task 1   configure_logging()
  src/run.py                      Task 1   entry point
  src/app.py                      Task 1 (health only), Task 8 (full), Task 9 (MCP mount)
  src/engine/__init__.py          Task 2
  src/engine/page_ranges.py       Task 2   parse_page_ranges()
  src/store/__init__.py           Task 3
  src/store/sniff.py              Task 3   sniff_mime()
  src/store/names.py              Task 3   safe_filename(), ensure_pdf_suffix(), file_stem(), content_disposition()
  src/store/file_store.py         Task 4   StoredFile, PendingFile, FileStore
  src/store/signing.py            Task 4   LinkSigner
  src/converters/__init__.py      Task 5
  src/converters/base.py          Task 5   ImageOptions, SourceConverter
  src/converters/pdf.py           Task 5   PdfPassthrough
  src/converters/image.py         Task 5   ImageConverter
  src/converters/registry.py      Task 5   ConverterRegistry, default_registry()
  src/models.py                   Task 6   pydantic API models (MergePlan etc.)
  src/engine/planner.py           Task 6   PlannedSegment, ExpandedPlan, expand_plan()
  src/engine/assembler.py         Task 6   AssemblyPart, Assembler
  src/jobs/__init__.py            Task 7
  src/jobs/job_queue.py           Task 7   Job, JobQueue
  src/service.py                  Task 7   Caller, MergeService, build_service()
  src/store/sweeper.py            Task 8   run_sweeper()
  src/api/__init__.py             Task 8
  src/api/deps.py                 Task 8   get_service(), get_caller()
  src/api/files.py                Task 8   /api/files routes
  src/api/merge.py                Task 8   /api/merge, /api/jobs routes
  src/internal_token.py           Task 9   InternalTokenMiddleware
  src/mcp_tools/__init__.py       Task 9
  src/mcp_tools/contract.py       Task 9   tool result models
  src/mcp_tools/tools.py          Task 9   build_mcp(), caller_from_context()
  tests/conftest.py               Task 1 (settings), Task 5 (fixtures), Task 7 (service)
  tests/test_*.py                 per task
Python/MCPServer/.gitignore       Task 1
Python/MCPServer/_TODO.md         Task 10
```

---

### Task 1: Project scaffold, settings, errors, health route

**Files:**
- Create: `pdf_merger/pyproject.toml`, `pdf_merger/run.bat`, `pdf_merger/configs/config_pdf_merger.json.example`, `pdf_merger/.secrets/secret_internal_api.env.example`, `pdf_merger/.secrets/secret_signing.env.example`
- Create: `pdf_merger/src/__init__.py`, `src/config.py`, `src/errors.py`, `src/logging_setup.py`, `src/app.py`, `src/run.py`
- Create: `pdf_merger/tests/__init__.py`, `tests/conftest.py`, `tests/test_config.py`, `tests/test_errors.py`, `tests/test_health.py`
- Modify: `Python/MCPServer/.gitignore` (append)

**Interfaces:**
- Produces: `Settings` (frozen dataclass, fields listed below), `Limits`, `load_settings(configs_dir, secrets_dir, env) -> Settings`, `ErrorCode` (StrEnum), `MergerError(code, message)` with `.code`, `.message`, `.http_status`, `.to_body()`, `configure_logging(log_dir: Path) -> None`, `create_app(settings: Settings) -> FastAPI`, fixture `settings` in `tests/conftest.py`.

- [ ] **Step 1: Create packaging, launcher and config files**

`pdf_merger/pyproject.toml`:

```toml
[project]
name = "pdf_merger"
description = "Merges PDFs and images into one PDF. REST API for pdf_merger_web, MCP endpoint for mcp_server."
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.115,<1.0",
    "uvicorn>=0.30,<1.0",
    "mcp>=1.28.0,<2.0.0",
    # qpdf-backed PDF reading/writing: page copy, rotation, outlines.
    "pikepdf>=9.0",
    # Embeds JPEG bytes unchanged (lossless) and lays images out on a page.
    "img2pdf>=0.5",
    "pillow>=10.0",
    # HEIC/HEIF support for Pillow.
    "pillow-heif>=0.18",
    "python-dotenv>=1.0",
]

[project.optional-dependencies]
# httpx2: what starlette.testclient wants now (same as ember_api).
dev = ["pytest>=8.0", "pytest-asyncio>=0.24", "httpx2"]

[tool.setuptools.packages.find]
include = ["src*"]

[tool.pytest.ini_options]
pythonpath = ["."]
testpaths = ["tests"]
asyncio_mode = "auto"
```

`pdf_merger/run.bat`:

```bat
@echo off
REM pdf_merger dev launcher. Creates .venv_pdf_merger on first run and installs
REM this project into it in editable mode.
REM
REM LABEL: PDF Merger
REM DESCRIPTION: Merges PDFs and images into one PDF. REST API for pdf_merger_web, MCP endpoint for mcp_server.
cd /d "%~dp0"

if not defined PDF_MERGER_PORT set PDF_MERGER_PORT=8040

if not exist ".venv_pdf_merger\Scripts\python.exe" (
    echo Creating virtual environment .venv_pdf_merger ...
    py -m venv .venv_pdf_merger
    call .venv_pdf_merger\Scripts\activate
    echo Installing pdf_merger in editable mode ...
    pip install -e ".[dev]"
) else (
    call .venv_pdf_merger\Scripts\activate
)

:run
py -m src.run

echo.
echo ----------------------------------------
echo  pdf_merger stopped.
choice /C RQ /N /M "Press [R] to restart, [Q] to quit: "
if errorlevel 2 goto :end
if errorlevel 1 goto :run

:end
```

`pdf_merger/configs/config_pdf_merger.json.example`:

```json
{
  "host": "127.0.0.1",
  "port": 8040,
  "public_base_url": "",
  "web_origin": "http://127.0.0.1:5174",
  "file_ttl_hours": 6,
  "sweep_interval_minutes": 10,
  "download_link_minutes": 60,
  "limits": {
    "max_file_mb": 100,
    "max_session_mb": 500,
    "max_segments": 50,
    "max_output_pages": 2000,
    "max_image_megapixels": 80,
    "max_concurrent_merges": 2,
    "job_timeout_seconds": 120
  }
}
```

`public_base_url` empty means `http://127.0.0.1:<port>`. Set it to a LAN address when other machines must open download links.

`pdf_merger/.secrets/secret_internal_api.env.example`:

```
# Same value as INTERNAL_API_TOKEN in mcp_server/.secrets/secret_internal_api.env.
# /mcp and token uploads are refused until this is set.
INTERNAL_API_TOKEN=
```

`pdf_merger/.secrets/secret_signing.env.example`:

```
# Random secret for signed download links, e.g. py -c "import secrets; print(secrets.token_hex(32))".
# Unset: a random key per process, so links stop working after a restart.
PDF_MERGER_SIGNING_KEY=
```

Append to `Python/MCPServer/.gitignore`:

```
# pdf_merger's real secrets and runtime state (uploaded files, logs).
/pdf_merger/.secrets/*
!/pdf_merger/.secrets/*.example
/pdf_merger/.data/
/pdf_merger/.logs/
```

`configs/config_pdf_merger.json` (the real file) is already ignored by the repo-wide `config_*.json` rule.

- [ ] **Step 2: Write the failing tests**

`pdf_merger/tests/__init__.py`: empty file.

`pdf_merger/tests/conftest.py`:

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

`pdf_merger/tests/test_config.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

from src.config import MB, Limits, load_settings

EXAMPLE = Path(__file__).resolve().parent.parent / "configs" / "config_pdf_merger.json.example"


def _dirs(tmp_path: Path) -> tuple[Path, Path]:
    configs, secrets_dir = tmp_path / "configs", tmp_path / ".secrets"
    configs.mkdir()
    secrets_dir.mkdir()
    (configs / "config_pdf_merger.json.example").write_text(EXAMPLE.read_text("utf-8"), "utf-8")
    return configs, secrets_dir


def test_missing_config_is_copied_from_example(tmp_path: Path):
    configs, secrets_dir = _dirs(tmp_path)

    settings = load_settings(configs, secrets_dir, env={})

    assert (configs / "config_pdf_merger.json").exists()
    assert settings.port == 8040
    assert settings.public_base_url == "http://127.0.0.1:8040"
    assert settings.limits == Limits()
    assert settings.file_ttl_seconds == 6 * 3600


def test_env_overrides_port_and_public_url_follows(tmp_path: Path):
    configs, secrets_dir = _dirs(tmp_path)

    settings = load_settings(configs, secrets_dir, env={"PDF_MERGER_PORT": "9999"})

    assert settings.port == 9999
    assert settings.public_base_url == "http://127.0.0.1:9999"


def test_limits_are_read_in_friendly_units(tmp_path: Path):
    configs, secrets_dir = _dirs(tmp_path)
    raw = json.loads(EXAMPLE.read_text("utf-8"))
    raw["limits"]["max_file_mb"] = 5
    raw["limits"]["max_image_megapixels"] = 1.5
    (configs / "config_pdf_merger.json").write_text(json.dumps(raw), "utf-8")

    settings = load_settings(configs, secrets_dir, env={})

    assert settings.limits.max_file_bytes == 5 * MB
    assert settings.limits.max_image_pixels == 1_500_000


def test_secrets_are_read_from_env_files(tmp_path: Path):
    configs, secrets_dir = _dirs(tmp_path)
    (secrets_dir / "secret_internal_api.env").write_text("INTERNAL_API_TOKEN=abc\n", "utf-8")
    (secrets_dir / "secret_signing.env").write_text("PDF_MERGER_SIGNING_KEY=key\n", "utf-8")

    settings = load_settings(configs, secrets_dir, env={})

    assert settings.internal_api_token == "abc"
    assert settings.signing_key == b"key"


def test_missing_signing_key_gets_a_random_one(tmp_path: Path):
    configs, secrets_dir = _dirs(tmp_path)

    first = load_settings(configs, secrets_dir, env={})
    second = load_settings(configs, secrets_dir, env={})

    assert len(first.signing_key) == 64
    assert first.signing_key != second.signing_key
```

`pdf_merger/tests/test_errors.py`:

```python
from __future__ import annotations

from src.errors import ErrorCode, MergerError


def test_error_body_and_status():
    error = MergerError(ErrorCode.INVALID_RANGE, "Pages go from 1 to 3.")

    assert error.http_status == 422
    assert error.to_body() == {"error": {"code": "invalid_range", "message": "Pages go from 1 to 3."}}


def test_every_code_has_a_status():
    for code in ErrorCode:
        assert 400 <= MergerError(code, "x").http_status < 600
```

`pdf_merger/tests/test_health.py`:

```python
from __future__ import annotations

from fastapi.testclient import TestClient

from src.app import create_app


def test_health(settings):
    with TestClient(create_app(settings)) as client:
        response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

- [ ] **Step 3: Create the venv and run the tests to verify they fail**

Run: `py -m venv .venv_pdf_merger && .venv_pdf_merger\Scripts\python -m pip install -e ".[dev]"` (after Step 1 files exist).
Run: `.venv_pdf_merger\Scripts\python -m pytest -q`
Expected: FAIL / errors with `ModuleNotFoundError: No module named 'src.config'`.

- [ ] **Step 4: Write the implementation**

`pdf_merger/src/__init__.py`: empty file.

`pdf_merger/src/errors.py`:

```python
"""Every failure a caller can see, as a code plus a plain-language message.

Routers turn MergerError into an HTTP error body; MCP tools turn it into a
ToolError. Anything else that escapes is logged and reported as
internal_error, so raw exception text never reaches a caller.
"""

from __future__ import annotations

from enum import StrEnum


class ErrorCode(StrEnum):
    UNSUPPORTED_TYPE = "unsupported_type"
    FILE_TOO_LARGE = "file_too_large"
    ENCRYPTED_PDF = "encrypted_pdf"
    CORRUPT_FILE = "corrupt_file"
    INVALID_RANGE = "invalid_range"
    INVALID_REQUEST = "invalid_request"
    FILE_NOT_FOUND = "file_not_found"
    JOB_NOT_FOUND = "job_not_found"
    LIMIT_EXCEEDED = "limit_exceeded"
    MERGE_TIMEOUT = "merge_timeout"
    INTERNAL = "internal_error"


_HTTP_STATUS: dict[ErrorCode, int] = {
    ErrorCode.UNSUPPORTED_TYPE: 415,
    ErrorCode.FILE_TOO_LARGE: 413,
    ErrorCode.ENCRYPTED_PDF: 422,
    ErrorCode.CORRUPT_FILE: 422,
    ErrorCode.INVALID_RANGE: 422,
    ErrorCode.INVALID_REQUEST: 422,
    ErrorCode.FILE_NOT_FOUND: 404,
    ErrorCode.JOB_NOT_FOUND: 404,
    ErrorCode.LIMIT_EXCEEDED: 413,
    ErrorCode.MERGE_TIMEOUT: 504,
    ErrorCode.INTERNAL: 500,
}


class MergerError(Exception):
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

`pdf_merger/src/config.py`:

```python
"""pdf_merger settings: configs/config_pdf_merger.json plus .secrets/*.env,
with PDF_MERGER_HOST / PDF_MERGER_PORT / INTERNAL_API_TOKEN /
PDF_MERGER_SIGNING_KEY environment overrides.

A missing real config or secret file is copied from its committed
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
SECRETS_DIR = PROJECT_DIR / ".secrets"
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


def _read_secrets(secrets_dir: Path) -> dict[str, str]:
    """All KEY=value pairs from every secret_*.env, examples copied first."""
    values: dict[str, str] = {}
    if not secrets_dir.is_dir():
        return values
    for example in sorted(secrets_dir.glob("*.env.example")):
        _ensure_from_example(example.with_suffix(""))
    for env_file in sorted(secrets_dir.glob("*.env")):
        values.update({k: v for k, v in dotenv_values(env_file).items() if v is not None})
    return values


def load_settings(
    configs_dir: Path = CONFIGS_DIR,
    secrets_dir: Path = SECRETS_DIR,
    env: Mapping[str, str] | None = None,
) -> Settings:
    """Read config + secrets; environment variables win over both."""
    env = os.environ if env is None else env
    raw = _read_json(configs_dir / CONFIG_FILE)
    secret = _read_secrets(secrets_dir)

    port = int(env.get("PDF_MERGER_PORT") or raw.get("port", 8040))
    signing_key = env.get("PDF_MERGER_SIGNING_KEY") or secret.get("PDF_MERGER_SIGNING_KEY", "")
    if not signing_key:
        logger.warning("PDF_MERGER_SIGNING_KEY is not set; download links stop working after a restart.")
        signing_key = secrets.token_hex(32)

    return Settings(
        host=env.get("PDF_MERGER_HOST") or raw.get("host", "127.0.0.1"),
        port=port,
        public_base_url=(raw.get("public_base_url") or f"http://127.0.0.1:{port}").rstrip("/"),
        web_origin=raw.get("web_origin", "http://127.0.0.1:5174"),
        file_ttl_seconds=int(float(raw.get("file_ttl_hours", 6)) * 3600),
        sweep_interval_seconds=int(float(raw.get("sweep_interval_minutes", 10)) * 60),
        download_link_seconds=int(float(raw.get("download_link_minutes", 60)) * 60),
        internal_api_token=env.get("INTERNAL_API_TOKEN") or secret.get("INTERNAL_API_TOKEN", ""),
        signing_key=signing_key.encode("utf-8"),
        limits=Limits.from_config(raw.get("limits", {})),
    )
```

`pdf_merger/src/logging_setup.py`:

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

`pdf_merger/src/app.py` (health only; Task 8 replaces this file):

```python
"""FastAPI application factory."""

from __future__ import annotations

from fastapi import FastAPI

from src.config import Settings


def create_app(settings: Settings) -> FastAPI:
    app = FastAPI(title="pdf_merger")
    app.state.settings = settings

    @app.get("/api/health")
    async def health() -> dict:
        return {"status": "ok"}

    return app
```

`pdf_merger/src/run.py`:

```python
"""pdf_merger entry point: ``py -m src.run`` (see run.bat)."""

from __future__ import annotations

import uvicorn

from src.app import create_app
from src.config import load_settings
from src.logging_setup import configure_logging


def main() -> None:
    settings = load_settings()
    configure_logging(settings.log_dir)
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv_pdf_merger\Scripts\python -m pytest -q`
Expected: PASS (8 tests).

- [ ] **Step 6: Commit**

```bash
git add .gitignore pdf_merger/pyproject.toml pdf_merger/run.bat pdf_merger/configs pdf_merger/.secrets/*.example pdf_merger/src pdf_merger/tests
git commit -m "feat(pdf_merger): scaffold project with settings, errors and health route"
```

---

### Task 2: Page range parser

**Files:**
- Create: `pdf_merger/src/engine/__init__.py` (empty), `pdf_merger/src/engine/page_ranges.py`
- Test: `pdf_merger/tests/test_page_ranges.py`

**Interfaces:**
- Consumes: `ErrorCode`, `MergerError` (Task 1).
- Produces: `parse_page_ranges(spec: str | None, page_count: int) -> list[int]` returning 0-based indices in the order written; raises `MergerError(INVALID_RANGE, ...)`.

- [ ] **Step 1: Write the failing test**

`pdf_merger/tests/test_page_ranges.py`:

```python
from __future__ import annotations

import pytest

from src.engine.page_ranges import parse_page_ranges
from src.errors import ErrorCode, MergerError


@pytest.mark.parametrize("spec", [None, "", "  ", "all", "ALL"])
def test_empty_or_all_means_every_page(spec):
    assert parse_page_ranges(spec, 3) == [0, 1, 2]


@pytest.mark.parametrize(
    ("spec", "expected"),
    [
        ("1", [0]),
        ("1-3,7", [0, 1, 2, 6]),
        (" 2 - 3 , 5 ", [1, 2, 4]),
        ("7,1", [6, 0]),
    ],
)
def test_ranges_are_one_based_and_keep_written_order(spec, expected):
    assert parse_page_ranges(spec, 10) == expected


@pytest.mark.parametrize(
    ("spec", "fragment"),
    [
        ("0", "1 to 5"),
        ("4-6", "1 to 5"),
        ("3-1", "backwards"),
        ("a", "isn't a page"),
        ("1,,2", "isn't a page"),
        ("1-", "isn't a page"),
    ],
)
def test_bad_ranges_raise_invalid_range(spec, fragment):
    with pytest.raises(MergerError) as caught:
        parse_page_ranges(spec, 5)

    assert caught.value.code == ErrorCode.INVALID_RANGE
    assert fragment in caught.value.message
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv_pdf_merger\Scripts\python -m pytest tests/test_page_ranges.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.engine'`.

- [ ] **Step 3: Write the implementation**

`pdf_merger/src/engine/page_ranges.py`:

```python
"""Parse a human page selection like "1-3,7" into 0-based page indices.

Order is kept as written ("7,1" gives [6, 0]) so a caller can reorder
pages inside one segment. Duplicate detection is the planner's job, since
it must also catch the same page used by two different segments.
"""

from __future__ import annotations

import re

from src.errors import ErrorCode, MergerError

_PART = re.compile(r"(\d+)(?:\s*-\s*(\d+))?")


def parse_page_ranges(spec: str | None, page_count: int) -> list[int]:
    """Return 0-based indices. None, "", or "all" select every page. O(n) in pages selected."""
    text = (spec or "").strip()
    if text == "" or text.lower() == "all":
        return list(range(page_count))

    pages: list[int] = []
    for raw in text.split(","):
        part = raw.strip()
        match = _PART.fullmatch(part)
        if match is None:
            raise MergerError(ErrorCode.INVALID_RANGE, f'"{part}" isn\'t a page or range. Use a form like 1-3,7.')
        start = int(match.group(1))
        end = int(match.group(2) or start)
        if start > end:
            raise MergerError(ErrorCode.INVALID_RANGE, f'"{part}" runs backwards. Write the lower page first.')
        if start < 1 or end > page_count:
            raise MergerError(ErrorCode.INVALID_RANGE, f'"{part}" is outside the document. Pages go from 1 to {page_count}.')
        pages.extend(range(start - 1, end))
    return pages
```

Note: `"3-1"` is checked for "backwards" before bounds, so the test's `fragment` matches. `"0"` has start 0 < 1, so it hits the bounds message.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv_pdf_merger\Scripts\python -m pytest tests/test_page_ranges.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pdf_merger/src/engine pdf_merger/tests/test_page_ranges.py
git commit -m "feat(pdf_merger): parse page ranges"
```

---

### Task 3: File type sniffing and safe file names

**Files:**
- Create: `pdf_merger/src/store/__init__.py` (empty), `pdf_merger/src/store/sniff.py`, `pdf_merger/src/store/names.py`
- Test: `pdf_merger/tests/test_sniff.py`, `pdf_merger/tests/test_names.py`

**Interfaces:**
- Produces: `SNIFF_BYTES: int = 1024`, `sniff_mime(head: bytes) -> str | None`; `safe_filename(name: str | None, default: str) -> str`, `ensure_pdf_suffix(name: str) -> str`, `file_stem(name: str) -> str`, `content_disposition(name: str, *, inline: bool = False) -> str`.

- [ ] **Step 1: Write the failing tests**

`pdf_merger/tests/test_sniff.py`:

```python
from __future__ import annotations

import pytest

from src.store.sniff import sniff_mime


@pytest.mark.parametrize(
    ("head", "mime"),
    [
        (b"%PDF-1.7\n...", "application/pdf"),
        (b"\xef\xbb\xbfjunk%PDF-1.4", "application/pdf"),
        (b"\xff\xd8\xff\xe0\x00\x10JFIF", "image/jpeg"),
        (b"\x89PNG\r\n\x1a\n\x00\x00", "image/png"),
        (b"GIF89a\x01\x00", "image/gif"),
        (b"II*\x00\x08\x00", "image/tiff"),
        (b"MM\x00*\x00\x00", "image/tiff"),
        (b"RIFF\x24\x00\x00\x00WEBPVP8 ", "image/webp"),
        (b"\x00\x00\x00\x18ftypheic\x00\x00", "image/heic"),
        (b"\x00\x00\x00\x18ftypmif1\x00\x00", "image/heic"),
    ],
)
def test_known_signatures(head, mime):
    assert sniff_mime(head) == mime


@pytest.mark.parametrize("head", [b"", b"hello world", b"PK\x03\x04docx", b"\x00\x00\x00\x18ftypmp42"])
def test_unknown_content_is_none(head):
    assert sniff_mime(head) is None
```

`pdf_merger/tests/test_names.py`:

```python
from __future__ import annotations

from src.store.names import content_disposition, ensure_pdf_suffix, file_stem, safe_filename


def test_safe_filename_strips_paths_and_odd_characters():
    assert safe_filename("../../etc/passwd", "x") == "passwd"
    assert safe_filename("C:\\Users\\me\\scan 01.jpg", "x") == "scan 01.jpg"
    assert safe_filename('bad<>:"|?*name.pdf', "x") == "bad_name.pdf"
    assert safe_filename("résumé.pdf", "x") == "résumé.pdf"


def test_safe_filename_falls_back_to_default():
    assert safe_filename(None, "upload") == "upload"
    assert safe_filename("  ...  ", "upload") == "upload"


def test_ensure_pdf_suffix():
    assert ensure_pdf_suffix("merged") == "merged.pdf"
    assert ensure_pdf_suffix("merged.PDF") == "merged.PDF"


def test_file_stem():
    assert file_stem("contract_2026.pdf") == "contract_2026"
    assert file_stem("noext") == "noext"


def test_content_disposition_has_ascii_and_utf8_forms():
    header = content_disposition("résumé.pdf")
    assert header.startswith('attachment; filename="rsum.pdf"')
    assert "filename*=UTF-8''r%C3%A9sum%C3%A9.pdf" in header
    assert content_disposition("a.pdf", inline=True).startswith("inline;")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv_pdf_merger\Scripts\python -m pytest tests/test_sniff.py tests/test_names.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.store'`.

- [ ] **Step 3: Write the implementation**

`pdf_merger/src/store/sniff.py`:

```python
"""Detect a file's real type from its first bytes. File extensions are never trusted."""

from __future__ import annotations

SNIFF_BYTES = 1024

_PREFIXES: tuple[tuple[bytes, str], ...] = (
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"II*\x00", "image/tiff"),
    (b"MM\x00*", "image/tiff"),
)
_HEIF_BRANDS = frozenset({b"heic", b"heix", b"heim", b"heis", b"hevc", b"hevx", b"mif1", b"msf1"})


def sniff_mime(head: bytes) -> str | None:
    """MIME type for the first SNIFF_BYTES of a file, or None if unsupported."""
    for prefix, mime in _PREFIXES:
        if head.startswith(prefix):
            return mime
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    if head[4:8] == b"ftyp" and head[8:12] in _HEIF_BRANDS:
        return "image/heic"
    # The PDF spec allows junk before the header; readers accept it within the first 1 KB.
    if b"%PDF-" in head[:SNIFF_BYTES]:
        return "application/pdf"
    return None
```

`pdf_merger/src/store/names.py`:

```python
"""User-supplied file names are metadata only. These helpers make them safe to store and to send back in headers."""

from __future__ import annotations

import re
from urllib.parse import quote

_UNSAFE = re.compile(r"[^\w.\- ()]+")
_MAX_LENGTH = 150


def safe_filename(name: str | None, default: str) -> str:
    """Last path component with unsafe characters collapsed to "_"; ``default`` if nothing is left."""
    base = (name or "").replace("\\", "/").rsplit("/", 1)[-1]
    base = _UNSAFE.sub("_", base).strip(" .")[:_MAX_LENGTH]
    return base or default


def ensure_pdf_suffix(name: str) -> str:
    return name if name.lower().endswith(".pdf") else f"{name}.pdf"


def file_stem(name: str) -> str:
    """Name without its last extension, used as a bookmark title."""
    stem, dot, _ = name.rpartition(".")
    return stem if dot and stem else name


def content_disposition(name: str, *, inline: bool = False) -> str:
    """RFC 6266 header with an ASCII fallback and the exact UTF-8 name."""
    ascii_name = name.encode("ascii", "ignore").decode("ascii").replace('"', "") or "file"
    kind = "inline" if inline else "attachment"
    return f"{kind}; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(name)}"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv_pdf_merger\Scripts\python -m pytest tests/test_sniff.py tests/test_names.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pdf_merger/src/store pdf_merger/tests/test_sniff.py pdf_merger/tests/test_names.py
git commit -m "feat(pdf_merger): sniff file types and sanitize file names"
```

---

### Task 4: File store and signed links

**Files:**
- Create: `pdf_merger/src/store/file_store.py`, `pdf_merger/src/store/signing.py`
- Test: `pdf_merger/tests/test_file_store.py`, `pdf_merger/tests/test_signing.py`

**Interfaces:**
- Consumes: `ErrorCode`, `MergerError`, `MB` (Task 1).
- Produces:
  - `StoredFile` frozen dataclass: `file_id: str, session: str, name: str, mime: str, kind: str, pages: int, size: int, created_at: float, expires_at: float`.
  - `PendingFile` frozen dataclass: `file_id: str, session: str, path: Path`.
  - `FileStore(root: Path, *, ttl_seconds: int, max_file_bytes: int, max_session_bytes: int, clock: Callable[[], float] = time.time)` with:
    `async load_index() -> int`, `new_pending(session: str) -> PendingFile`, `async write_stream(session: str, chunks: AsyncIterable[bytes]) -> PendingFile`, `discard(pending: PendingFile) -> None`, `async commit(pending, *, name: str, mime: str, kind: str, pages: int) -> StoredFile`, `get(file_id: str, session: str | None) -> StoredFile`, `path(file: StoredFile) -> Path`, `list(session: str) -> list[StoredFile]`, `session_usage(session: str) -> int`, `async delete(file_id: str, session: str | None) -> None`, `async sweep() -> int`, `async make_work_dir() -> Path`, `async remove_work_dir(path: Path) -> None`.
  - `LinkSigner(key: bytes, ttl_seconds: int, clock=time.time)` with `sign(file_id: str) -> tuple[int, str]` and `verify(file_id: str, exp: int, sig: str) -> bool`.

`session=None` in `get`/`delete` means a privileged (token) caller: any session's file by ID.

- [ ] **Step 1: Write the failing tests**

`pdf_merger/tests/test_file_store.py`:

```python
from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from src.errors import ErrorCode, MergerError
from src.store.file_store import FileStore


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


async def chunks(data: bytes, size: int = 4) -> AsyncIterator[bytes]:
    for start in range(0, len(data), size):
        yield data[start : start + size]


def make_store(tmp_path: Path, clock: FakeClock, **overrides) -> FileStore:
    options = dict(ttl_seconds=100, max_file_bytes=1000, max_session_bytes=2000, clock=clock)
    options.update(overrides)
    return FileStore(tmp_path / "store", **options)


async def add(store: FileStore, session: str, data: bytes = b"hello", name: str = "a.pdf"):
    pending = await store.write_stream(session, chunks(data))
    return await store.commit(pending, name=name, mime="application/pdf", kind="pdf", pages=1)


async def test_commit_then_get_and_read(tmp_path: Path):
    store = make_store(tmp_path, FakeClock())

    stored = await add(store, "web:1", b"content")

    assert stored.file_id.startswith("f_") and len(stored.file_id) == 34
    assert stored.size == 7 and stored.expires_at == 1100.0
    assert store.get(stored.file_id, "web:1") == stored
    assert store.path(stored).read_bytes() == b"content"


async def test_other_session_gets_not_found_but_privileged_caller_can_read(tmp_path: Path):
    store = make_store(tmp_path, FakeClock())
    stored = await add(store, "web:1")

    with pytest.raises(MergerError) as caught:
        store.get(stored.file_id, "web:2")
    assert caught.value.code == ErrorCode.FILE_NOT_FOUND
    assert store.get(stored.file_id, None) == stored


async def test_expired_file_is_not_found_and_swept(tmp_path: Path):
    clock = FakeClock()
    store = make_store(tmp_path, clock)
    stored = await add(store, "web:1")
    path = store.path(stored)

    clock.now += 101
    with pytest.raises(MergerError):
        store.get(stored.file_id, "web:1")
    assert await store.sweep() == 1
    assert not path.exists()


async def test_too_large_stream_is_rejected_and_cleaned_up(tmp_path: Path):
    store = make_store(tmp_path, FakeClock(), max_file_bytes=10)

    with pytest.raises(MergerError) as caught:
        await store.write_stream("web:1", chunks(b"x" * 11))

    assert caught.value.code == ErrorCode.FILE_TOO_LARGE
    assert list((tmp_path / "store").rglob("*.part")) == []


async def test_session_quota(tmp_path: Path):
    store = make_store(tmp_path, FakeClock(), max_session_bytes=10)
    await add(store, "web:1", b"x" * 6)

    with pytest.raises(MergerError) as caught:
        await add(store, "web:1", b"x" * 6)

    assert caught.value.code == ErrorCode.LIMIT_EXCEEDED
    assert store.session_usage("web:1") == 6
    await add(store, "web:2", b"x" * 6)  # other sessions have their own quota


async def test_list_is_per_session_oldest_first(tmp_path: Path):
    clock = FakeClock()
    store = make_store(tmp_path, clock)
    first = await add(store, "web:1", name="first.pdf")
    clock.now += 1
    second = await add(store, "web:1", name="second.pdf")
    await add(store, "web:2")

    assert store.list("web:1") == [first, second]


async def test_delete(tmp_path: Path):
    store = make_store(tmp_path, FakeClock())
    stored = await add(store, "web:1")

    await store.delete(stored.file_id, "web:1")

    with pytest.raises(MergerError):
        store.get(stored.file_id, None)
    assert not store.path(stored).exists()


async def test_index_survives_restart(tmp_path: Path):
    clock = FakeClock()
    stored = await add(make_store(tmp_path, clock), "mcp:alice")

    reopened = make_store(tmp_path, clock)
    assert await reopened.load_index() == 1
    assert reopened.get(stored.file_id, "mcp:alice") == stored


async def test_session_names_never_become_raw_paths(tmp_path: Path):
    store = make_store(tmp_path, FakeClock())
    stored = await add(store, "mcp:../../evil")

    assert store.path(stored).resolve().is_relative_to((tmp_path / "store").resolve())


async def test_work_dir_round_trip(tmp_path: Path):
    store = make_store(tmp_path, FakeClock())

    work = await store.make_work_dir()
    (work / "x.pdf").write_bytes(b"x")
    await store.remove_work_dir(work)

    assert not work.exists()
```

`pdf_merger/tests/test_signing.py`:

```python
from __future__ import annotations

from src.store.signing import LinkSigner


def test_sign_and_verify():
    clock = lambda: 1000.0  # noqa: E731
    signer = LinkSigner(b"k" * 32, ttl_seconds=60, clock=clock)

    exp, sig = signer.sign("f_" + "a" * 32)

    assert exp == 1060
    assert signer.verify("f_" + "a" * 32, exp, sig)
    assert not signer.verify("f_" + "b" * 32, exp, sig)
    assert not signer.verify("f_" + "a" * 32, exp + 1, sig)
    assert not signer.verify("f_" + "a" * 32, exp, "0" * 64)


def test_expired_link_fails():
    now = [1000.0]
    signer = LinkSigner(b"k" * 32, ttl_seconds=60, clock=lambda: now[0])
    exp, sig = signer.sign("f_" + "a" * 32)

    now[0] = 1061.0

    assert not signer.verify("f_" + "a" * 32, exp, sig)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv_pdf_merger\Scripts\python -m pytest tests/test_file_store.py tests/test_signing.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.store.file_store'`.

- [ ] **Step 3: Write the implementation**

`pdf_merger/src/store/file_store.py`:

```python
"""Session-scoped files on disk with an in-memory index.

Layout: <root>/<sha256(session)[:32]>/<file_id> plus a <file_id>.json
sidecar holding the StoredFile record, so the index can be rebuilt after a
restart. Session strings are hashed so "mcp:alice" or anything a caller
sends can never become a raw path. The user's file name is metadata only.

One instance per process. Index mutations happen on the event loop thread;
disk I/O goes through asyncio.to_thread so the loop never blocks.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import secrets
import shutil
import tempfile
import time
from collections.abc import AsyncIterable, Callable
from dataclasses import asdict, dataclass
from pathlib import Path

from src.config import MB
from src.errors import ErrorCode, MergerError

logger = logging.getLogger(__name__)

_WORK_DIR_NAME = "_work"


@dataclass(frozen=True)
class StoredFile:
    """One committed file. ``kind`` is "pdf" or "image"."""

    file_id: str
    session: str
    name: str
    mime: str
    kind: str
    pages: int
    size: int
    created_at: float
    expires_at: float


@dataclass(frozen=True)
class PendingFile:
    """Content being written; becomes a StoredFile on commit()."""

    file_id: str
    session: str
    path: Path


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

    # --- paths -------------------------------------------------------------

    def _session_dir(self, session: str) -> Path:
        return self._root / hashlib.sha256(session.encode("utf-8")).hexdigest()[:32]

    def path(self, file: StoredFile) -> Path:
        return self._session_dir(file.session) / file.file_id

    def _meta_path(self, file: StoredFile) -> Path:
        return self._session_dir(file.session) / f"{file.file_id}.json"

    # --- startup -----------------------------------------------------------

    async def load_index(self) -> int:
        """Rebuild the index from sidecars. Returns the number of files loaded."""

        def scan() -> list[StoredFile]:
            found: list[StoredFile] = []
            for meta in self._root.glob("*/f_*.json"):
                try:
                    found.append(StoredFile(**json.loads(meta.read_text("utf-8"))))
                except (OSError, ValueError, TypeError):
                    logger.warning("Skipping unreadable sidecar %s", meta)
            return found

        for file in await asyncio.to_thread(scan):
            self._index[file.file_id] = file
        return len(self._index)

    # --- writing -----------------------------------------------------------

    def new_pending(self, session: str) -> PendingFile:
        directory = self._session_dir(session)
        directory.mkdir(parents=True, exist_ok=True)
        file_id = new_file_id()
        return PendingFile(file_id=file_id, session=session, path=directory / f"{file_id}.part")

    async def write_stream(self, session: str, chunks: AsyncIterable[bytes]) -> PendingFile:
        """Stream chunks to disk, stopping as soon as the per-file limit is passed."""
        pending = self.new_pending(session)
        size = 0
        handle = await asyncio.to_thread(open, pending.path, "wb")
        try:
            async for chunk in chunks:
                size += len(chunk)
                if size > self._max_file_bytes:
                    raise MergerError(
                        ErrorCode.FILE_TOO_LARGE,
                        f"This file is larger than {self._max_file_bytes // MB} MB. Split or compress it, then upload it again.",
                    )
                await asyncio.to_thread(handle.write, chunk)
        except BaseException:
            await asyncio.to_thread(handle.close)
            self.discard(pending)
            raise
        await asyncio.to_thread(handle.close)
        return pending

    def discard(self, pending: PendingFile) -> None:
        pending.path.unlink(missing_ok=True)

    async def commit(self, pending: PendingFile, *, name: str, mime: str, kind: str, pages: int) -> StoredFile:
        """Register written content. Enforces the session quota."""
        size = (await asyncio.to_thread(pending.path.stat)).st_size
        if self.session_usage(pending.session) + size > self._max_session_bytes:
            self.discard(pending)
            raise MergerError(
                ErrorCode.LIMIT_EXCEEDED,
                f"Your files would use more than {self._max_session_bytes // MB} MB. Delete some files or wait for them to expire.",
            )
        now = self._clock()
        stored = StoredFile(
            file_id=pending.file_id,
            session=pending.session,
            name=name,
            mime=mime,
            kind=kind,
            pages=pages,
            size=size,
            created_at=now,
            expires_at=now + self._ttl,
        )

        def finish() -> None:
            os.replace(pending.path, self.path(stored))
            self._meta_path(stored).write_text(json.dumps(asdict(stored)), "utf-8")

        await asyncio.to_thread(finish)
        self._index[stored.file_id] = stored
        return stored

    # --- reading -----------------------------------------------------------

    def get(self, file_id: str, session: str | None) -> StoredFile:
        """The file, if it exists, has not expired, and ``session`` may see it (None = any)."""
        file = self._index.get(file_id)
        if file is None or file.expires_at <= self._clock() or (session is not None and file.session != session):
            raise MergerError(ErrorCode.FILE_NOT_FOUND, f"File {file_id} wasn't found. It may have expired; upload it again.")
        return file

    def list(self, session: str) -> list[StoredFile]:
        now = self._clock()
        files = [f for f in self._index.values() if f.session == session and f.expires_at > now]
        return sorted(files, key=lambda f: f.created_at)

    def session_usage(self, session: str) -> int:
        return sum(f.size for f in self.list(session))

    # --- removal -----------------------------------------------------------

    async def _remove(self, file: StoredFile) -> None:
        self._index.pop(file.file_id, None)

        def unlink() -> None:
            self.path(file).unlink(missing_ok=True)
            self._meta_path(file).unlink(missing_ok=True)

        await asyncio.to_thread(unlink)

    async def delete(self, file_id: str, session: str | None) -> None:
        await self._remove(self.get(file_id, session))

    async def sweep(self) -> int:
        """Delete every expired file. Returns how many were removed."""
        now = self._clock()
        expired = [f for f in self._index.values() if f.expires_at <= now]
        for file in expired:
            await self._remove(file)
        return len(expired)

    # --- scratch space -----------------------------------------------------

    async def make_work_dir(self) -> Path:
        """A fresh scratch directory for one merge (converted images)."""
        base = self._root / _WORK_DIR_NAME
        await asyncio.to_thread(base.mkdir, parents=True, exist_ok=True)
        return Path(await asyncio.to_thread(tempfile.mkdtemp, dir=base))

    async def remove_work_dir(self, path: Path) -> None:
        await asyncio.to_thread(shutil.rmtree, path, True)
```

`pdf_merger/src/store/signing.py`:

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
        return hmac.compare_digest(self._digest(file_id, exp), sig)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv_pdf_merger\Scripts\python -m pytest tests/test_file_store.py tests/test_signing.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pdf_merger/src/store pdf_merger/tests/test_file_store.py pdf_merger/tests/test_signing.py
git commit -m "feat(pdf_merger): add session-scoped file store and signed links"
```

---

### Task 5: Converters (PDF passthrough, images)

**Files:**
- Create: `pdf_merger/src/converters/__init__.py` (empty), `base.py`, `pdf.py`, `image.py`, `registry.py`
- Modify: `pdf_merger/tests/conftest.py` (append fixture helpers)
- Test: `pdf_merger/tests/test_converters.py`

**Interfaces:**
- Consumes: `ErrorCode`, `MergerError` (Task 1).
- Produces:
  - `PageSize = Literal["A4", "Letter", "match"]`, `FitMode = Literal["fit", "fill", "original"]`.
  - `ImageOptions(page_size: PageSize = "A4", fit: FitMode = "fit", margin_mm: float = 10.0)` frozen dataclass.
  - `SourceConverter` Protocol: `kind: str`, `can_handle(mime: str) -> bool`, `async inspect(path: Path) -> int` (page count), `async to_pdf(path: Path, work_dir: Path, opts: ImageOptions) -> Path`.
  - `PdfPassthrough()` (`kind="pdf"`), `ImageConverter(max_pixels: int)` (`kind="image"`), `IMAGE_MIMES: frozenset[str]`.
  - `ConverterRegistry(converters)` with `for_mime(mime: str | None) -> SourceConverter`; `default_registry(max_image_pixels: int) -> ConverterRegistry`.
  - Test helpers in conftest: `make_pdf(path, widths, height=200, rotate=0) -> Path`, `page_widths(path) -> list[int]`, `make_image(path, size=(40, 30), mode="RGB", fmt="JPEG", exif_orientation=None) -> Path`.

"original" fit means natural size, shrunk only when larger than the page (img2pdf `FitMode.shrink`). "match" page size makes the page the image's own size; margin and fit are ignored then.

- [ ] **Step 1: Add fixture helpers to conftest**

Append to `pdf_merger/tests/conftest.py`:

```python
from collections.abc import Sequence

import pikepdf
from PIL import Image


def make_pdf(path: Path, widths: Sequence[int], height: int = 200, rotate: int = 0) -> Path:
    """A PDF whose page i is widths[i] points wide, so tests can check page order by width."""
    pdf = pikepdf.new()
    for width in widths:
        pdf.add_blank_page(page_size=(width, height))
        if rotate:
            pdf.pages[-1].obj.Rotate = rotate
    pdf.save(path)
    return path


def page_widths(path: Path) -> list[int]:
    with pikepdf.open(path) as pdf:
        return [round(float(page.mediabox[2])) for page in pdf.pages]


def make_image(
    path: Path,
    size: tuple[int, int] = (40, 30),
    mode: str = "RGB",
    fmt: str = "JPEG",
    exif_orientation: int | None = None,
) -> Path:
    color = (200, 10, 10, 128) if mode == "RGBA" else (200, 10, 10)
    image = Image.new(mode, size, color)
    options = {}
    if exif_orientation is not None:
        exif = Image.Exif()
        exif[0x0112] = exif_orientation
        options["exif"] = exif
    image.save(path, format=fmt, **options)
    return path
```

- [ ] **Step 2: Write the failing tests**

`pdf_merger/tests/test_converters.py`:

```python
from __future__ import annotations

from pathlib import Path

import pikepdf
import pytest

from src.converters.base import ImageOptions
from src.converters.image import ImageConverter
from src.converters.pdf import PdfPassthrough
from src.converters.registry import default_registry
from src.errors import ErrorCode, MergerError
from tests.conftest import make_image, make_pdf

A4 = (595.28, 841.89)


def mediabox(path: Path) -> tuple[float, float]:
    with pikepdf.open(path) as pdf:
        box = pdf.pages[0].mediabox
        return float(box[2]) - float(box[0]), float(box[3]) - float(box[1])


def only_image(pdf: pikepdf.Pdf) -> pikepdf.Object:
    [(_, xobject)] = list(pdf.pages[0].images.items())
    return xobject


# --- registry --------------------------------------------------------------


@pytest.mark.parametrize(("mime", "kind"), [("application/pdf", "pdf"), ("image/png", "image"), ("image/heic", "image")])
def test_registry_picks_by_mime(mime, kind):
    assert default_registry(10**8).for_mime(mime).kind == kind


@pytest.mark.parametrize("mime", [None, "application/zip", "text/plain"])
def test_registry_rejects_unknown(mime):
    with pytest.raises(MergerError) as caught:
        default_registry(10**8).for_mime(mime)
    assert caught.value.code == ErrorCode.UNSUPPORTED_TYPE


# --- pdf -------------------------------------------------------------------


async def test_pdf_inspect_counts_pages_and_to_pdf_is_identity(tmp_path: Path):
    src = make_pdf(tmp_path / "a.pdf", [100, 101, 102])
    converter = PdfPassthrough()

    assert await converter.inspect(src) == 3
    assert await converter.to_pdf(src, tmp_path, ImageOptions()) == src


async def test_encrypted_pdf_is_rejected(tmp_path: Path):
    path = tmp_path / "locked.pdf"
    pdf = pikepdf.new()
    pdf.add_blank_page()
    pdf.save(path, encryption=pikepdf.Encryption(owner="o", user="u"))

    with pytest.raises(MergerError) as caught:
        await PdfPassthrough().inspect(path)
    assert caught.value.code == ErrorCode.ENCRYPTED_PDF


async def test_corrupt_pdf_is_rejected(tmp_path: Path):
    path = tmp_path / "bad.pdf"
    path.write_bytes(b"%PDF-1.7\nthis is not a pdf")

    with pytest.raises(MergerError) as caught:
        await PdfPassthrough().inspect(path)
    assert caught.value.code == ErrorCode.CORRUPT_FILE


# --- images ----------------------------------------------------------------


async def test_jpeg_bytes_are_embedded_unchanged(tmp_path: Path):
    src = make_image(tmp_path / "photo.jpg")
    out = await ImageConverter(10**8).to_pdf(src, tmp_path, ImageOptions())

    with pikepdf.open(out) as pdf:
        assert only_image(pdf).read_raw_bytes() == src.read_bytes()


async def test_a4_page_size(tmp_path: Path):
    src = make_image(tmp_path / "photo.jpg")
    out = await ImageConverter(10**8).to_pdf(src, tmp_path, ImageOptions(page_size="A4"))

    width, height = mediabox(out)
    assert width == pytest.approx(A4[0], abs=0.5) and height == pytest.approx(A4[1], abs=0.5)


async def test_match_page_size_uses_image_size(tmp_path: Path):
    src = make_image(tmp_path / "photo.png", size=(300, 150), fmt="PNG")
    out = await ImageConverter(10**8).to_pdf(src, tmp_path, ImageOptions(page_size="match"))

    width, height = mediabox(out)
    assert width / height == pytest.approx(2.0, rel=0.01)


async def test_exif_orientation_becomes_page_rotation(tmp_path: Path):
    src = make_image(tmp_path / "phone.jpg", exif_orientation=6)
    out = await ImageConverter(10**8).to_pdf(src, tmp_path, ImageOptions(page_size="match"))

    with pikepdf.open(out) as pdf:
        assert int(pdf.pages[0].obj.get("/Rotate", 0)) == 90


async def test_png_alpha_is_flattened(tmp_path: Path):
    src = make_image(tmp_path / "logo.png", mode="RGBA", fmt="PNG")
    out = await ImageConverter(10**8).to_pdf(src, tmp_path, ImageOptions())

    with pikepdf.open(out) as pdf:
        assert "/SMask" not in only_image(pdf)


@pytest.mark.parametrize("fmt", ["WEBP", "TIFF", "GIF"])
async def test_other_formats_convert(tmp_path: Path, fmt):
    src = make_image(tmp_path / f"img.{fmt.lower()}", fmt=fmt)
    out = await ImageConverter(10**8).to_pdf(src, tmp_path, ImageOptions())

    with pikepdf.open(out) as pdf:
        assert len(pdf.pages) == 1


async def test_heic_converts(tmp_path: Path):
    from pillow_heif import register_heif_opener

    register_heif_opener()
    src = make_image(tmp_path / "img.heic", fmt="HEIF")
    out = await ImageConverter(10**8).to_pdf(src, tmp_path, ImageOptions())

    with pikepdf.open(out) as pdf:
        assert len(pdf.pages) == 1


async def test_image_over_pixel_limit_is_rejected(tmp_path: Path):
    src = make_image(tmp_path / "big.jpg", size=(40, 30))

    with pytest.raises(MergerError) as caught:
        await ImageConverter(max_pixels=1000).inspect(src)
    assert caught.value.code == ErrorCode.LIMIT_EXCEEDED


async def test_unreadable_image_is_corrupt(tmp_path: Path):
    path = tmp_path / "broken.png"
    path.write_bytes(b"\x89PNG\r\n\x1a\nnot really")

    with pytest.raises(MergerError) as caught:
        await ImageConverter(10**8).inspect(path)
    assert caught.value.code == ErrorCode.CORRUPT_FILE
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv_pdf_merger\Scripts\python -m pytest tests/test_converters.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.converters'`.

- [ ] **Step 4: Write the implementation**

`pdf_merger/src/converters/base.py`:

```python
"""The converter contract. Every input type becomes a PDF before assembly.

Adding a type (for example Word documents via LibreOffice) means one new
class implementing SourceConverter plus one line in registry.py. Nothing
else changes.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

PageSize = Literal["A4", "Letter", "match"]
FitMode = Literal["fit", "fill", "original"]


@dataclass(frozen=True)
class ImageOptions:
    """How an image is placed on its page. Ignored by non-image converters."""

    page_size: PageSize = "A4"
    fit: FitMode = "fit"
    margin_mm: float = 10.0


class SourceConverter(Protocol):
    kind: str

    def can_handle(self, mime: str) -> bool: ...

    async def inspect(self, path: Path) -> int:
        """Validate the file and return its page count. Raises MergerError."""
        ...

    async def to_pdf(self, path: Path, work_dir: Path, opts: ImageOptions) -> Path:
        """A PDF version of ``path``. May return ``path`` itself when it is already a PDF."""
        ...
```

`pdf_merger/src/converters/pdf.py`:

```python
"""PDFs need no conversion; this converter only validates them."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pikepdf

from src.converters.base import ImageOptions
from src.errors import ErrorCode, MergerError


def _count_pages(path: Path) -> int:
    try:
        with pikepdf.open(path) as pdf:
            count = len(pdf.pages)
    except pikepdf.PasswordError as error:
        raise MergerError(
            ErrorCode.ENCRYPTED_PDF, "This PDF is password-protected. Remove the password, then upload it again."
        ) from error
    except pikepdf.PdfError as error:
        raise MergerError(ErrorCode.CORRUPT_FILE, "This PDF is damaged and can't be read.") from error
    if count == 0:
        raise MergerError(ErrorCode.CORRUPT_FILE, "This PDF has no pages.")
    return count


class PdfPassthrough:
    kind = "pdf"

    def can_handle(self, mime: str) -> bool:
        return mime == "application/pdf"

    async def inspect(self, path: Path) -> int:
        return await asyncio.to_thread(_count_pages, path)

    async def to_pdf(self, path: Path, work_dir: Path, opts: ImageOptions) -> Path:
        return path
```

`pdf_merger/src/converters/image.py`:

```python
"""Images become one-page PDFs through img2pdf.

JPEGs are embedded byte for byte (lossless); their EXIF orientation is
applied as the page's /Rotate, not by re-encoding. Every other format is
flattened to RGB (alpha onto white) and handed over as PNG, which img2pdf
also embeds without loss. Multi-frame GIF/TIFF use the first frame.
"""

from __future__ import annotations

import asyncio
import io
from pathlib import Path
from uuid import uuid4

import img2pdf
from PIL import Image, ImageOps, UnidentifiedImageError
from pillow_heif import register_heif_opener

from src.converters.base import FitMode, ImageOptions, PageSize
from src.errors import ErrorCode, MergerError

register_heif_opener()
# Our own pixel limit (with a clear message) replaces Pillow's DecompressionBombError.
Image.MAX_IMAGE_PIXELS = None

IMAGE_MIMES = frozenset({"image/jpeg", "image/png", "image/webp", "image/tiff", "image/gif", "image/heic"})

_PAGE_SIZES: dict[PageSize, tuple[float, float]] = {
    "A4": (img2pdf.mm_to_pt(210), img2pdf.mm_to_pt(297)),
    "Letter": (img2pdf.in_to_pt(8.5), img2pdf.in_to_pt(11)),
}
_FIT: dict[FitMode, img2pdf.FitMode] = {
    "fit": img2pdf.FitMode.into,
    "fill": img2pdf.FitMode.fill,
    "original": img2pdf.FitMode.shrink,
}


def _layout(opts: ImageOptions):
    if opts.page_size == "match":
        return img2pdf.default_layout_fun
    border = None
    if opts.margin_mm > 0:
        margin = img2pdf.mm_to_pt(opts.margin_mm)
        border = (margin, margin)
    return img2pdf.get_layout_fun(pagesize=_PAGE_SIZES[opts.page_size], border=border, fit=_FIT[opts.fit])


def _flatten(image: Image.Image) -> Image.Image:
    has_alpha = image.mode in ("RGBA", "LA") or (image.mode == "P" and "transparency" in image.info)
    if has_alpha:
        rgba = image.convert("RGBA")
        background = Image.new("RGB", rgba.size, (255, 255, 255))
        background.paste(rgba, mask=rgba.getchannel("A"))
        return background
    return image if image.mode in ("RGB", "L") else image.convert("RGB")


def _image_bytes(path: Path) -> bytes:
    with Image.open(path) as image:
        if image.format == "JPEG" and image.mode in ("RGB", "L", "CMYK"):
            return path.read_bytes()
        image.seek(0)
        upright = ImageOps.exif_transpose(image)
        buffer = io.BytesIO()
        _flatten(upright).save(buffer, format="PNG")
        return buffer.getvalue()


class ImageConverter:
    kind = "image"

    def __init__(self, max_pixels: int) -> None:
        self._max_pixels = max_pixels

    def can_handle(self, mime: str) -> bool:
        return mime in IMAGE_MIMES

    def _check(self, path: Path) -> None:
        try:
            with Image.open(path) as image:
                width, height = image.size
                image.verify()
        except (UnidentifiedImageError, OSError, SyntaxError) as error:
            raise MergerError(ErrorCode.CORRUPT_FILE, "This image is damaged and can't be read.") from error
        if width * height > self._max_pixels:
            raise MergerError(
                ErrorCode.LIMIT_EXCEEDED,
                f"This image is {width * height / 1e6:.1f} megapixels; the limit is {self._max_pixels / 1e6:g}. Resize it, then upload it again.",
            )

    def _convert(self, path: Path, out: Path, opts: ImageOptions) -> None:
        self._check(path)
        try:
            data = _image_bytes(path)
            out.write_bytes(img2pdf.convert(data, layout_fun=_layout(opts), rotation=img2pdf.Rotation.ifvalid))
        except (img2pdf.ImageOpenError, ValueError, OSError) as error:
            raise MergerError(ErrorCode.CORRUPT_FILE, "This image couldn't be converted to a PDF page.") from error

    async def inspect(self, path: Path) -> int:
        await asyncio.to_thread(self._check, path)
        return 1

    async def to_pdf(self, path: Path, work_dir: Path, opts: ImageOptions) -> Path:
        out = work_dir / f"{path.name}-{uuid4().hex}.pdf"
        await asyncio.to_thread(self._convert, path, out, opts)
        return out
```

`pdf_merger/src/converters/registry.py`:

```python
"""Pick the converter for a sniffed MIME type."""

from __future__ import annotations

from collections.abc import Sequence

from src.converters.base import SourceConverter
from src.converters.image import ImageConverter
from src.converters.pdf import PdfPassthrough
from src.errors import ErrorCode, MergerError


class ConverterRegistry:
    def __init__(self, converters: Sequence[SourceConverter]) -> None:
        self._converters = tuple(converters)

    def for_mime(self, mime: str | None) -> SourceConverter:
        for converter in self._converters:
            if mime and converter.can_handle(mime):
                return converter
        raise MergerError(
            ErrorCode.UNSUPPORTED_TYPE,
            "This file type isn't supported. Upload a PDF or an image (JPG, PNG, WebP, TIFF, GIF or HEIC).",
        )


def default_registry(max_image_pixels: int) -> ConverterRegistry:
    return ConverterRegistry([PdfPassthrough(), ImageConverter(max_image_pixels)])
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv_pdf_merger\Scripts\python -m pytest tests/test_converters.py -q`
Expected: PASS. If `test_heic_converts` fails with an encoder error on this machine, check `python -c "import pillow_heif; print(pillow_heif.libheif_info())"` shows an HEVC encoder; the installed wheel normally ships one.

- [ ] **Step 6: Commit**

```bash
git add pdf_merger/src/converters pdf_merger/tests/conftest.py pdf_merger/tests/test_converters.py
git commit -m "feat(pdf_merger): convert PDFs and images through a converter registry"
```

---

### Task 6: Plan models, planner and assembler

**Files:**
- Create: `pdf_merger/src/models.py`, `pdf_merger/src/engine/planner.py`, `pdf_merger/src/engine/assembler.py`
- Test: `pdf_merger/tests/test_planner.py`, `pdf_merger/tests/test_assembler.py`

**Interfaces:**
- Consumes: `parse_page_ranges` (Task 2), `StoredFile` (Task 4), `ImageOptions` (Task 5), `Limits` (Task 1).
- Produces:
  - `src/models.py` (pydantic): `Rotation = Literal[0, 90, 180, 270]`; `Segment(file_id: str, pages: str | None = None, rotate: Rotation = 0, fit: FitMode | None = None)`; `OutputOptions(filename: str = "merged.pdf", title: str | None = None, author: str | None = None, bookmarks: bool = True, image_page_size: PageSize = "A4", image_fit: FitMode = "fit", image_margin_mm: float = 10 (0..50))`; `MergePlan(segments: list[Segment] (min 1), output: OutputOptions = OutputOptions())`; `FileInfo(file_id, name, kind, pages, size, expires_at)` with `FileInfo.of(stored: StoredFile)`; `MergeResult(file_id, name, pages, size, expires_at, download_url)`.
  - `PlannedSegment(file: StoredFile, pages: tuple[int, ...], rotate: int, image_options: ImageOptions | None)`, `ExpandedPlan(segments: tuple[PlannedSegment, ...], total_pages: int)`, `expand_plan(plan: MergePlan, lookup: Callable[[str], StoredFile], limits: Limits) -> ExpandedPlan`.
  - `AssemblyPart(pdf_path: Path, pages: tuple[int, ...], rotate: int, bookmark: str, group_key: str)`, `Assembler()` with `async assemble(parts: Sequence[AssemblyPart], out_path: Path, *, title: str | None, author: str | None, bookmarks: bool, on_page: Callable[[int], None] | None = None) -> int` (returns page count; `on_page` gets the running page count, called from a worker thread).

- [ ] **Step 1: Write the failing tests**

`pdf_merger/tests/test_planner.py`:

```python
from __future__ import annotations

import pytest

from src.config import Limits
from src.converters.base import ImageOptions
from src.engine.planner import expand_plan
from src.errors import ErrorCode, MergerError
from src.models import MergePlan
from src.store.file_store import StoredFile


def stored(file_id: str, kind: str = "pdf", pages: int = 5, name: str = "doc.pdf") -> StoredFile:
    return StoredFile(file_id, "web:1", name, "application/pdf" if kind == "pdf" else "image/jpeg", kind, pages, 10, 0.0, 9e9)


FILES = {"f_pdf": stored("f_pdf"), "f_img": stored("f_img", kind="image", pages=1, name="photo.jpg")}


def lookup(file_id: str) -> StoredFile:
    if file_id not in FILES:
        raise MergerError(ErrorCode.FILE_NOT_FOUND, "missing")
    return FILES[file_id]


def plan(*segments: dict, **output) -> MergePlan:
    return MergePlan.model_validate({"segments": list(segments), "output": output})


def test_segments_expand_in_order():
    expanded = expand_plan(
        plan({"file_id": "f_pdf", "pages": "1-2"}, {"file_id": "f_img"}, {"file_id": "f_pdf", "pages": "5", "rotate": 90}),
        lookup,
        Limits(),
    )

    assert [(s.file.file_id, s.pages, s.rotate) for s in expanded.segments] == [
        ("f_pdf", (0, 1), 0),
        ("f_img", (0,), 0),
        ("f_pdf", (4,), 90),
    ]
    assert expanded.total_pages == 4


def test_image_options_come_from_output_with_segment_fit_override():
    expanded = expand_plan(
        plan({"file_id": "f_img", "fit": "fill"}, image_page_size="Letter", image_fit="fit", image_margin_mm=5),
        lookup,
        Limits(),
    )

    assert expanded.segments[0].image_options == ImageOptions(page_size="Letter", fit="fill", margin_mm=5)


def test_pdf_segments_have_no_image_options():
    assert expand_plan(plan({"file_id": "f_pdf"}), lookup, Limits()).segments[0].image_options is None


def test_bad_range_names_the_segment():
    with pytest.raises(MergerError) as caught:
        expand_plan(plan({"file_id": "f_pdf"}, {"file_id": "f_pdf", "pages": "9"}), lookup, Limits())

    assert caught.value.code == ErrorCode.INVALID_RANGE
    assert caught.value.message.startswith("Segment 2 (doc.pdf):")


def test_duplicate_page_is_rejected():
    with pytest.raises(MergerError) as caught:
        expand_plan(plan({"file_id": "f_pdf", "pages": "1-2"}, {"file_id": "f_pdf", "pages": "2"}), lookup, Limits())

    assert caught.value.code == ErrorCode.INVALID_RANGE
    assert "page 2" in caught.value.message


def test_unknown_file_propagates_not_found():
    with pytest.raises(MergerError) as caught:
        expand_plan(plan({"file_id": "f_nope"}), lookup, Limits())
    assert caught.value.code == ErrorCode.FILE_NOT_FOUND


def test_segment_and_page_limits():
    with pytest.raises(MergerError) as caught:
        expand_plan(plan({"file_id": "f_pdf", "pages": "1"}, {"file_id": "f_img"}), lookup, Limits(max_segments=1))
    assert caught.value.code == ErrorCode.LIMIT_EXCEEDED

    with pytest.raises(MergerError) as caught:
        expand_plan(plan({"file_id": "f_pdf"}), lookup, Limits(max_output_pages=4))
    assert caught.value.code == ErrorCode.LIMIT_EXCEEDED


def test_plan_model_rejects_bad_rotation():
    with pytest.raises(ValueError):
        MergePlan.model_validate({"segments": [{"file_id": "f_pdf", "rotate": 45}]})
```

`pdf_merger/tests/test_assembler.py`:

```python
from __future__ import annotations

from pathlib import Path

import pikepdf

from src.engine.assembler import AssemblyPart, Assembler
from tests.conftest import make_pdf, page_widths


async def test_pages_are_copied_in_plan_order(tmp_path: Path):
    a = make_pdf(tmp_path / "a.pdf", [100, 101, 102])
    b = make_pdf(tmp_path / "b.pdf", [200])
    out = tmp_path / "out.pdf"
    seen: list[int] = []

    count = await Assembler().assemble(
        [
            AssemblyPart(a, (2, 0), 0, "a", "fa"),
            AssemblyPart(b, (0,), 0, "b", "fb"),
            AssemblyPart(a, (1,), 0, "a", "fa"),
        ],
        out,
        title=None,
        author=None,
        bookmarks=False,
        on_page=seen.append,
    )

    assert count == 4
    assert page_widths(out) == [102, 100, 200, 101]
    assert seen == [1, 2, 3, 4]


async def test_rotation_adds_to_existing_rotation(tmp_path: Path):
    a = make_pdf(tmp_path / "a.pdf", [100], rotate=90)
    out = tmp_path / "out.pdf"

    await Assembler().assemble([AssemblyPart(a, (0,), 90, "a", "fa")], out, title=None, author=None, bookmarks=False)

    with pikepdf.open(out) as pdf:
        assert int(pdf.pages[0].obj.get("/Rotate", 0)) == 180


async def test_bookmarks_collapse_neighbouring_parts_of_one_file(tmp_path: Path):
    a = make_pdf(tmp_path / "a.pdf", [100, 101, 102])
    b = make_pdf(tmp_path / "b.pdf", [200])
    out = tmp_path / "out.pdf"

    await Assembler().assemble(
        [
            AssemblyPart(a, (0,), 0, "contract", "fa"),
            AssemblyPart(a, (1,), 90, "contract", "fa"),
            AssemblyPart(b, (0,), 0, "receipt", "fb"),
            AssemblyPart(a, (2,), 0, "contract", "fa"),
        ],
        out,
        title=None,
        author=None,
        bookmarks=True,
    )

    with pikepdf.open(out) as pdf, pdf.open_outline() as outline:
        assert [item.title for item in outline.root] == ["contract", "receipt", "contract"]


async def test_no_outline_when_bookmarks_off(tmp_path: Path):
    a = make_pdf(tmp_path / "a.pdf", [100])
    out = tmp_path / "out.pdf"

    await Assembler().assemble([AssemblyPart(a, (0,), 0, "a", "fa")], out, title=None, author=None, bookmarks=False)

    with pikepdf.open(out) as pdf, pdf.open_outline() as outline:
        assert list(outline.root) == []


async def test_metadata(tmp_path: Path):
    a = make_pdf(tmp_path / "a.pdf", [100])
    out = tmp_path / "out.pdf"

    await Assembler().assemble([AssemblyPart(a, (0,), 0, "a", "fa")], out, title="Package", author="Jane", bookmarks=False)

    with pikepdf.open(out) as pdf:
        assert str(pdf.docinfo["/Title"]) == "Package"
        assert str(pdf.docinfo["/Author"]) == "Jane"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv_pdf_merger\Scripts\python -m pytest tests/test_planner.py tests/test_assembler.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.models'`.

- [ ] **Step 3: Write the implementation**

`pdf_merger/src/models.py`:

```python
"""Request and response shapes shared by the REST API and the MCP tools."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from src.converters.base import FitMode, PageSize
from src.store.file_store import StoredFile

Rotation = Literal[0, 90, 180, 270]


class Segment(BaseModel):
    """A run of pages from one file. Several segments of one file express any page order."""

    file_id: str = Field(description="ID of an uploaded file, e.g. f_0123... Never invent one.")
    pages: str | None = Field(
        default=None, description='1-based pages like "1-3,7". Null or "all" means every page. Ignored for images.'
    )
    rotate: Rotation = Field(default=0, description="Clockwise degrees added to each page's own rotation.")
    fit: FitMode | None = Field(default=None, description="Images only. Null uses output.image_fit.")


class OutputOptions(BaseModel):
    filename: str = Field(default="merged.pdf", description="File name of the merged PDF.")
    title: str | None = Field(default=None, description="PDF title metadata.")
    author: str | None = Field(default=None, description="PDF author metadata.")
    bookmarks: bool = Field(default=True, description="Add one bookmark per source; neighbouring segments of one file share it.")
    image_page_size: PageSize = Field(default="A4", description='Page size for images; "match" uses the image size.')
    image_fit: FitMode = Field(default="fit", description="Default image fit: fit inside, fill the page, or original size.")
    image_margin_mm: float = Field(default=10, ge=0, le=50, description="Margin around images in millimetres.")


class MergePlan(BaseModel):
    segments: list[Segment] = Field(min_length=1, description="Output order, first to last.")
    output: OutputOptions = Field(default_factory=OutputOptions)


class FileInfo(BaseModel):
    file_id: str
    name: str
    kind: str
    pages: int
    size: int
    expires_at: float

    @classmethod
    def of(cls, file: StoredFile) -> FileInfo:
        return cls(
            file_id=file.file_id, name=file.name, kind=file.kind, pages=file.pages, size=file.size, expires_at=file.expires_at
        )


class MergeResult(BaseModel):
    file_id: str
    name: str
    pages: int
    size: int
    expires_at: float
    download_url: str
```

`pdf_merger/src/engine/planner.py`:

```python
"""Validate a MergePlan against stored files and expand it into concrete pages.

Runs before a job is queued, so every plan error reaches the caller as an
immediate 4xx instead of a failed job.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from src.config import Limits
from src.converters.base import ImageOptions
from src.engine.page_ranges import parse_page_ranges
from src.errors import ErrorCode, MergerError
from src.models import MergePlan
from src.store.file_store import StoredFile


@dataclass(frozen=True)
class PlannedSegment:
    file: StoredFile
    pages: tuple[int, ...]
    rotate: int
    image_options: ImageOptions | None


@dataclass(frozen=True)
class ExpandedPlan:
    segments: tuple[PlannedSegment, ...]
    total_pages: int


def expand_plan(plan: MergePlan, lookup: Callable[[str], StoredFile], limits: Limits) -> ExpandedPlan:
    """O(total pages). ``lookup`` raises file_not_found for IDs the caller may not use."""
    if len(plan.segments) > limits.max_segments:
        raise MergerError(ErrorCode.LIMIT_EXCEEDED, f"A merge can have at most {limits.max_segments} segments.")

    output = plan.output
    seen: set[tuple[str, int]] = set()
    planned: list[PlannedSegment] = []
    total = 0
    for number, segment in enumerate(plan.segments, start=1):
        file = lookup(segment.file_id)
        if file.kind == "image":
            pages: tuple[int, ...] = (0,)
            options = ImageOptions(
                page_size=output.image_page_size, fit=segment.fit or output.image_fit, margin_mm=output.image_margin_mm
            )
        else:
            try:
                pages = tuple(parse_page_ranges(segment.pages, file.pages))
            except MergerError as error:
                raise MergerError(ErrorCode.INVALID_RANGE, f"Segment {number} ({file.name}): {error.message}") from error
            options = None

        for page in pages:
            key = (file.file_id, page)
            if key in seen:
                raise MergerError(
                    ErrorCode.INVALID_RANGE,
                    f"Segment {number} ({file.name}): page {page + 1} is already used. Each page can appear once.",
                )
            seen.add(key)

        total += len(pages)
        if total > limits.max_output_pages:
            raise MergerError(ErrorCode.LIMIT_EXCEEDED, f"The merged PDF would have more than {limits.max_output_pages} pages.")
        planned.append(PlannedSegment(file=file, pages=pages, rotate=segment.rotate, image_options=options))

    return ExpandedPlan(segments=tuple(planned), total_pages=total)
```

`pdf_merger/src/engine/assembler.py`:

```python
"""Build the output PDF from converted parts with pikepdf (qpdf).

Each source PDF is opened once however many parts use it. The whole build
runs in one worker thread; ``on_page`` is called from that thread, so
callers must hand progress back to the event loop thread-safely.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

import pikepdf
from pikepdf import OutlineItem


@dataclass(frozen=True)
class AssemblyPart:
    pdf_path: Path
    pages: tuple[int, ...]
    rotate: int
    bookmark: str
    group_key: str  # parts in a row with the same key share one bookmark


def _assemble(
    parts: Sequence[AssemblyPart],
    out_path: Path,
    title: str | None,
    author: str | None,
    bookmarks: bool,
    on_page: Callable[[int], None] | None,
) -> int:
    output = pikepdf.new()
    sources: dict[Path, pikepdf.Pdf] = {}
    try:
        outline_items: list[OutlineItem] = []
        previous_key: str | None = None
        for part in parts:
            source = sources.get(part.pdf_path)
            if source is None:
                source = sources[part.pdf_path] = pikepdf.open(part.pdf_path)
            first_page = len(output.pages)
            for index in part.pages:
                output.pages.append(source.pages[index])
                if part.rotate:
                    output.pages[-1].rotate(part.rotate, relative=True)
                if on_page is not None:
                    on_page(len(output.pages))
            if bookmarks and part.group_key != previous_key:
                outline_items.append(OutlineItem(part.bookmark, first_page))
            previous_key = part.group_key

        if outline_items:
            with output.open_outline() as outline:
                outline.root.extend(outline_items)
        if title:
            output.docinfo["/Title"] = title
        if author:
            output.docinfo["/Author"] = author
        output.save(out_path)
        return len(output.pages)
    finally:
        for source in sources.values():
            source.close()
        output.close()


class Assembler:
    async def assemble(
        self,
        parts: Sequence[AssemblyPart],
        out_path: Path,
        *,
        title: str | None,
        author: str | None,
        bookmarks: bool,
        on_page: Callable[[int], None] | None = None,
    ) -> int:
        """Write the merged PDF to ``out_path``; returns its page count."""
        return await asyncio.to_thread(_assemble, parts, out_path, title, author, bookmarks, on_page)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv_pdf_merger\Scripts\python -m pytest tests/test_planner.py tests/test_assembler.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pdf_merger/src/models.py pdf_merger/src/engine pdf_merger/tests/test_planner.py pdf_merger/tests/test_assembler.py
git commit -m "feat(pdf_merger): plan merges and assemble output with bookmarks and metadata"
```

---

### Task 7: Job queue and MergeService

**Files:**
- Create: `pdf_merger/src/jobs/__init__.py` (empty), `pdf_merger/src/jobs/job_queue.py`, `pdf_merger/src/service.py`
- Modify: `pdf_merger/tests/conftest.py` (append `service` fixture and `chunks` helper)
- Test: `pdf_merger/tests/test_job_queue.py`, `pdf_merger/tests/test_service.py`

**Interfaces:**
- Consumes: everything from Tasks 1–6.
- Produces:
  - `Job` with `id: str`, `session: str`, `created_at: float`, `events: list[dict]`, `finished: bool`, `publish(event: dict, *, final: bool = False) -> None`, `async stream() -> AsyncIterator[dict]` (replays past events, then live ones, ends after the final event).
  - `JobQueue(max_concurrent: int, timeout_seconds: float, clock=time.time)` with `submit(session: str, total_pages: int, work: Callable[[Callable[[int], None]], Awaitable[dict]]) -> Job`, `get(job_id: str, session: str | None) -> Job`, `async wait(job: Job) -> dict` (final event), `prune(older_than: float) -> int`.
  - Event shapes: `{"type": "queued", "total": n}`, `{"type": "progress", "done": k, "total": n}`, `{"type": "done", **MergeResult fields}`, `{"type": "error", "code": str, "message": str}`.
  - `Caller(session: str, privileged: bool = False)` with property `scope -> str | None` (None when privileged).
  - `MergeService` with: `store` (property), `async upload(caller, name: str | None, chunks: AsyncIterable[bytes]) -> StoredFile`, `list_files(caller) -> list[StoredFile]`, `get_file(caller, file_id) -> StoredFile`, `file_path(file) -> Path`, `async delete_file(caller, file_id) -> None`, `inspect(caller, file_ids: Sequence[str]) -> tuple[list[StoredFile], list[tuple[str, MergerError]]]`, `start_merge(caller, plan: MergePlan) -> Job`, `async merge_and_wait(caller, plan) -> MergeResult`, `get_job(caller, job_id) -> Job`, `download_url(file) -> str`, `file_for_download(file_id, exp: int, sig: str) -> StoredFile`, `async sweep() -> int`.
  - `build_service(settings: Settings) -> MergeService`.
  - conftest: `service` fixture, `async chunks(data, size=65536)` helper.

- [ ] **Step 1: Add fixtures to conftest**

Append to `pdf_merger/tests/conftest.py`:

```python
from collections.abc import AsyncIterator


async def chunks(data: bytes, size: int = 65536) -> AsyncIterator[bytes]:
    for start in range(0, len(data), size):
        yield data[start : start + size]


@pytest.fixture
def service(settings):
    from src.service import build_service

    return build_service(settings)
```

- [ ] **Step 2: Write the failing tests**

`pdf_merger/tests/test_job_queue.py`:

```python
from __future__ import annotations

import asyncio

import pytest

from src.errors import ErrorCode, MergerError
from src.jobs.job_queue import JobQueue


async def collect(job) -> list[dict]:
    return [event async for event in job.stream()]


async def test_successful_job_streams_queued_progress_done():
    queue = JobQueue(max_concurrent=1, timeout_seconds=5)

    async def work(progress):
        progress(1)
        progress(2)
        await asyncio.sleep(0)
        return {"file_id": "f_x"}

    job = queue.submit("web:1", 2, work)
    events = await collect(job)

    assert events[0] == {"type": "queued", "total": 2}
    assert {"type": "progress", "done": 2, "total": 2} in events
    assert events[-1] == {"type": "done", "file_id": "f_x"}
    assert job.finished


async def test_merger_error_becomes_error_event():
    queue = JobQueue(max_concurrent=1, timeout_seconds=5)

    async def work(progress):
        raise MergerError(ErrorCode.CORRUPT_FILE, "Broken.")

    final = await queue.wait(queue.submit("web:1", 1, work))

    assert final == {"type": "error", "code": "corrupt_file", "message": "Broken."}


async def test_unexpected_error_hides_details():
    queue = JobQueue(max_concurrent=1, timeout_seconds=5)

    async def work(progress):
        raise RuntimeError("secret internals")

    final = await queue.wait(queue.submit("web:1", 1, work))

    assert final["code"] == "internal_error"
    assert "secret" not in final["message"]


async def test_timeout():
    queue = JobQueue(max_concurrent=1, timeout_seconds=0.05)

    async def work(progress):
        await asyncio.sleep(1)
        return {}

    final = await queue.wait(queue.submit("web:1", 1, work))

    assert final["code"] == "merge_timeout"


async def test_concurrency_limit():
    queue = JobQueue(max_concurrent=1, timeout_seconds=5)
    release = asyncio.Event()
    running = 0
    peak = 0

    async def work(progress):
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await release.wait()
        running -= 1
        return {}

    first = queue.submit("web:1", 1, work)
    second = queue.submit("web:1", 1, work)
    await asyncio.sleep(0.01)
    release.set()
    await queue.wait(first)
    await queue.wait(second)

    assert peak == 1


async def test_get_respects_session():
    queue = JobQueue(max_concurrent=1, timeout_seconds=5)

    async def work(progress):
        return {}

    job = queue.submit("web:1", 1, work)

    assert queue.get(job.id, "web:1") is job
    assert queue.get(job.id, None) is job
    with pytest.raises(MergerError) as caught:
        queue.get(job.id, "web:2")
    assert caught.value.code == ErrorCode.JOB_NOT_FOUND
    await queue.wait(job)


async def test_prune_drops_old_finished_jobs():
    now = [100.0]
    queue = JobQueue(max_concurrent=1, timeout_seconds=5, clock=lambda: now[0])

    async def work(progress):
        return {}

    job = queue.submit("web:1", 1, work)
    await queue.wait(job)

    assert queue.prune(older_than=50.0) == 0
    assert queue.prune(older_than=101.0) == 1
```

`pdf_merger/tests/test_service.py`:

```python
from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from src.errors import ErrorCode, MergerError
from src.models import MergePlan
from src.service import Caller
from tests.conftest import chunks, make_image, make_pdf, page_widths

WEB = Caller("web:1")
OTHER = Caller("web:2")
BOT = Caller("mcp:alice", privileged=True)


async def upload(service, caller, path: Path):
    return await service.upload(caller, path.name, chunks(path.read_bytes()))


async def test_upload_sniffs_and_counts_pages(service, tmp_path: Path):
    stored = await upload(service, WEB, make_pdf(tmp_path / "a.pdf", [100, 101]))

    assert (stored.kind, stored.pages, stored.mime, stored.name) == ("pdf", 2, "application/pdf", "a.pdf")


async def test_upload_ignores_misleading_extension(service, tmp_path: Path):
    png = make_image(tmp_path / "x.png", fmt="PNG")
    disguised = tmp_path / "x.pdf"
    disguised.write_bytes(png.read_bytes())

    stored = await upload(service, WEB, disguised)

    assert stored.kind == "image" and stored.mime == "image/png"


async def test_unsupported_upload_leaves_nothing_behind(service, tmp_path: Path, settings):
    text = tmp_path / "notes.txt"
    text.write_text("hello")

    with pytest.raises(MergerError) as caught:
        await upload(service, WEB, text)

    assert caught.value.code == ErrorCode.UNSUPPORTED_TYPE
    assert [p for p in settings.store_dir.rglob("*") if p.is_file()] == []


async def test_merge_pdf_and_image_end_to_end(service, tmp_path: Path):
    pdf = await upload(service, WEB, make_pdf(tmp_path / "a.pdf", [100, 101, 102]))
    img = await upload(service, WEB, make_image(tmp_path / "b.jpg"))
    plan = MergePlan.model_validate(
        {
            "segments": [
                {"file_id": pdf.file_id, "pages": "3"},
                {"file_id": img.file_id},
                {"file_id": pdf.file_id, "pages": "1"},
            ],
            "output": {"filename": "out", "title": "T"},
        }
    )

    result = await service.merge_and_wait(WEB, plan)

    assert result.name == "out.pdf" and result.pages == 3
    merged = service.get_file(WEB, result.file_id)
    widths = page_widths(service.file_path(merged))
    assert widths[0] == 102 and widths[2] == 100
    assert widths[1] == 595  # A4 image page


async def test_plan_errors_raise_before_queueing(service, tmp_path: Path):
    pdf = await upload(service, WEB, make_pdf(tmp_path / "a.pdf", [100]))
    plan = MergePlan.model_validate({"segments": [{"file_id": pdf.file_id, "pages": "2"}]})

    with pytest.raises(MergerError) as caught:
        service.start_merge(WEB, plan)
    assert caught.value.code == ErrorCode.INVALID_RANGE


async def test_sessions_are_isolated_but_privileged_callers_use_ids(service, tmp_path: Path):
    pdf = await upload(service, WEB, make_pdf(tmp_path / "a.pdf", [100]))
    plan = MergePlan.model_validate({"segments": [{"file_id": pdf.file_id}]})

    with pytest.raises(MergerError):
        service.start_merge(OTHER, plan)
    result = await service.merge_and_wait(BOT, plan)

    assert [f.file_id for f in service.list_files(BOT)] == [result.file_id]
    assert service.list_files(OTHER) == []


async def test_download_url_round_trip(service, tmp_path: Path):
    pdf = await upload(service, WEB, make_pdf(tmp_path / "a.pdf", [100]))

    url = urlsplit(service.download_url(pdf))
    query = parse_qs(url.query)

    assert url.path == f"/api/files/{pdf.file_id}/download"
    assert service.file_for_download(pdf.file_id, int(query["exp"][0]), query["sig"][0]) == pdf
    with pytest.raises(MergerError):
        service.file_for_download(pdf.file_id, int(query["exp"][0]), "0" * 64)


async def test_inspect_reports_failures_without_aborting(service, tmp_path: Path):
    pdf = await upload(service, WEB, make_pdf(tmp_path / "a.pdf", [100]))

    files, failed = service.inspect(BOT, [pdf.file_id, "f_" + "0" * 32])

    assert [f.file_id for f in files] == [pdf.file_id]
    assert [(file_id, error.code) for file_id, error in failed] == [("f_" + "0" * 32, ErrorCode.FILE_NOT_FOUND)]
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv_pdf_merger\Scripts\python -m pytest tests/test_job_queue.py tests/test_service.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.jobs'`.

- [ ] **Step 4: Write the implementation**

`pdf_merger/src/jobs/job_queue.py`:

```python
"""Merge jobs: a global concurrency limit, a timeout, and replayable progress events.

A job's events are kept in a list so a late subscriber (the browser opening
the SSE stream after POST /merge returned) still sees everything. All
publish() calls happen on the event loop thread; worker threads report
progress through loop.call_soon_threadsafe.

A timed-out merge stops being awaited, but its worker thread runs to
completion in the background (Python cannot kill threads). The semaphore
slot is released at the timeout, so a stuck merge cannot block the queue.
"""

from __future__ import annotations

import asyncio
import logging
import secrets
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field

from src.errors import ErrorCode, MergerError

logger = logging.getLogger(__name__)

ProgressFn = Callable[[int], None]
Work = Callable[[ProgressFn], Awaitable[dict]]


@dataclass
class Job:
    id: str
    session: str
    created_at: float
    events: list[dict] = field(default_factory=list)
    finished: bool = False
    _changed: asyncio.Event = field(default_factory=asyncio.Event, repr=False)

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


class JobQueue:
    def __init__(self, max_concurrent: int, timeout_seconds: float, clock: Callable[[], float] = time.time) -> None:
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._timeout = timeout_seconds
        self._clock = clock
        self._jobs: dict[str, Job] = {}
        self._tasks: set[asyncio.Task] = set()

    def submit(self, session: str, total_pages: int, work: Work) -> Job:
        job = Job(id="j_" + secrets.token_hex(12), session=session, created_at=self._clock())
        self._jobs[job.id] = job
        task = asyncio.create_task(self._run(job, total_pages, work))
        self._tasks.add(task)  # keep a reference so the task is not garbage-collected
        task.add_done_callback(self._tasks.discard)
        return job

    async def _run(self, job: Job, total: int, work: Work) -> None:
        loop = asyncio.get_running_loop()

        def progress(done: int) -> None:
            loop.call_soon_threadsafe(job.publish, {"type": "progress", "done": done, "total": total})

        job.publish({"type": "queued", "total": total})
        try:
            async with self._semaphore:
                job.publish({"type": "progress", "done": 0, "total": total})
                result = await asyncio.wait_for(work(progress), self._timeout)
        except MergerError as error:
            job.publish({"type": "error", "code": str(error.code), "message": error.message}, final=True)
        except TimeoutError:
            job.publish(
                {
                    "type": "error",
                    "code": str(ErrorCode.MERGE_TIMEOUT),
                    "message": f"The merge took longer than {self._timeout:g} seconds and was stopped. Try fewer pages.",
                },
                final=True,
            )
        except Exception:
            logger.exception("Merge job %s failed", job.id)
            job.publish(
                {"type": "error", "code": str(ErrorCode.INTERNAL), "message": "The merge failed unexpectedly. Try again."},
                final=True,
            )
        else:
            job.publish({"type": "done", **result}, final=True)

    def get(self, job_id: str, session: str | None) -> Job:
        job = self._jobs.get(job_id)
        if job is None or (session is not None and job.session != session):
            raise MergerError(ErrorCode.JOB_NOT_FOUND, f"Job {job_id} wasn't found.")
        return job

    async def wait(self, job: Job) -> dict:
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

`pdf_merger/src/service.py`:

```python
"""MergeService: the one facade the REST routers and MCP tools call.

It composes the store, converters, planner, assembler, job queue and link
signer. Routers and tools hold no logic of their own.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from src.config import Limits, Settings
from src.converters.base import ImageOptions
from src.converters.registry import ConverterRegistry, default_registry
from src.engine.assembler import AssemblyPart, Assembler
from src.engine.planner import ExpandedPlan, expand_plan
from src.errors import ErrorCode, MergerError
from src.jobs.job_queue import Job, JobQueue, ProgressFn
from src.models import MergePlan, MergeResult, OutputOptions
from src.store.file_store import FileStore, StoredFile
from src.store.names import ensure_pdf_suffix, file_stem, safe_filename
from src.store.signing import LinkSigner
from src.store.sniff import SNIFF_BYTES, sniff_mime


@dataclass(frozen=True)
class Caller:
    """Who is asking. ``privileged`` callers (internal token) may open any file by ID."""

    session: str
    privileged: bool = False

    @property
    def scope(self) -> str | None:
        return None if self.privileged else self.session


def _read_head(path: Path) -> bytes:
    with path.open("rb") as handle:
        return handle.read(SNIFF_BYTES)


class MergeService:
    def __init__(
        self,
        *,
        store: FileStore,
        registry: ConverterRegistry,
        assembler: Assembler,
        jobs: JobQueue,
        signer: LinkSigner,
        limits: Limits,
        public_base_url: str,
        file_ttl_seconds: int,
    ) -> None:
        self._store = store
        self._registry = registry
        self._assembler = assembler
        self._jobs = jobs
        self._signer = signer
        self._limits = limits
        self._public_base_url = public_base_url.rstrip("/")
        self._file_ttl = file_ttl_seconds

    @property
    def store(self) -> FileStore:
        return self._store

    # --- files -------------------------------------------------------------

    async def upload(self, caller: Caller, name: str | None, chunks: AsyncIterable[bytes]) -> StoredFile:
        """Stream to disk, sniff the real type, validate, then commit."""
        pending = await self._store.write_stream(caller.session, chunks)
        try:
            mime = sniff_mime(await asyncio.to_thread(_read_head, pending.path))
            converter = self._registry.for_mime(mime)
            pages = await converter.inspect(pending.path)
        except BaseException:
            self._store.discard(pending)
            raise
        return await self._store.commit(
            pending, name=safe_filename(name, "upload"), mime=mime or "", kind=converter.kind, pages=pages
        )

    def list_files(self, caller: Caller) -> list[StoredFile]:
        return self._store.list(caller.session)

    def get_file(self, caller: Caller, file_id: str) -> StoredFile:
        return self._store.get(file_id, caller.scope)

    def file_path(self, file: StoredFile) -> Path:
        return self._store.path(file)

    async def delete_file(self, caller: Caller, file_id: str) -> None:
        await self._store.delete(file_id, caller.scope)

    def inspect(self, caller: Caller, file_ids: Sequence[str]) -> tuple[list[StoredFile], list[tuple[str, MergerError]]]:
        """Look up each ID; one bad ID never aborts the rest."""
        files: list[StoredFile] = []
        failed: list[tuple[str, MergerError]] = []
        for file_id in file_ids:
            try:
                files.append(self._store.get(file_id, caller.scope))
            except MergerError as error:
                failed.append((file_id, error))
        return files, failed

    # --- links -------------------------------------------------------------

    def download_url(self, file: StoredFile) -> str:
        exp, sig = self._signer.sign(file.file_id)
        return f"{self._public_base_url}/api/files/{file.file_id}/download?exp={exp}&sig={sig}"

    def file_for_download(self, file_id: str, exp: int, sig: str) -> StoredFile:
        if not self._signer.verify(file_id, exp, sig):
            raise MergerError(ErrorCode.FILE_NOT_FOUND, "This download link is invalid or has expired.")
        return self._store.get(file_id, None)

    # --- merging -----------------------------------------------------------

    def start_merge(self, caller: Caller, plan: MergePlan) -> Job:
        """Validate now (errors raise immediately), then queue the work."""
        expanded = expand_plan(plan, lambda file_id: self._store.get(file_id, caller.scope), self._limits)
        return self._jobs.submit(
            caller.session,
            expanded.total_pages,
            lambda progress: self._run_merge(caller.session, expanded, plan.output, progress),
        )

    async def merge_and_wait(self, caller: Caller, plan: MergePlan) -> MergeResult:
        final = await self._jobs.wait(self.start_merge(caller, plan))
        if final.get("type") != "done":
            raise MergerError(ErrorCode(final.get("code", "internal_error")), final.get("message", "The merge failed."))
        return MergeResult.model_validate({k: v for k, v in final.items() if k != "type"})

    def get_job(self, caller: Caller, job_id: str) -> Job:
        return self._jobs.get(job_id, caller.scope)

    async def _run_merge(self, session: str, expanded: ExpandedPlan, output: OutputOptions, progress: ProgressFn) -> dict:
        work_dir = await self._store.make_work_dir()
        try:
            parts: list[AssemblyPart] = []
            for segment in expanded.segments:
                converter = self._registry.for_mime(segment.file.mime)
                pdf_path = await converter.to_pdf(
                    self._store.path(segment.file), work_dir, segment.image_options or ImageOptions()
                )
                parts.append(
                    AssemblyPart(
                        pdf_path=pdf_path,
                        pages=segment.pages,
                        rotate=segment.rotate,
                        bookmark=file_stem(segment.file.name),
                        group_key=segment.file.file_id,
                    )
                )
            pending = self._store.new_pending(session)
            try:
                pages = await self._assembler.assemble(
                    parts, pending.path, title=output.title, author=output.author, bookmarks=output.bookmarks, on_page=progress
                )
                stored = await self._store.commit(
                    pending,
                    name=ensure_pdf_suffix(safe_filename(output.filename, "merged.pdf")),
                    mime="application/pdf",
                    kind="pdf",
                    pages=pages,
                )
            except BaseException:
                self._store.discard(pending)
                raise
        finally:
            await self._store.remove_work_dir(work_dir)
        return MergeResult(
            file_id=stored.file_id,
            name=stored.name,
            pages=stored.pages,
            size=stored.size,
            expires_at=stored.expires_at,
            download_url=self.download_url(stored),
        ).model_dump()

    # --- housekeeping ------------------------------------------------------

    async def sweep(self) -> int:
        """Delete expired files and forget old jobs."""
        removed = await self._store.sweep()
        self._jobs.prune(older_than=time.time() - self._file_ttl)
        return removed


def build_service(settings: Settings) -> MergeService:
    limits = settings.limits
    return MergeService(
        store=FileStore(
            settings.store_dir,
            ttl_seconds=settings.file_ttl_seconds,
            max_file_bytes=limits.max_file_bytes,
            max_session_bytes=limits.max_session_bytes,
        ),
        registry=default_registry(limits.max_image_pixels),
        assembler=Assembler(),
        jobs=JobQueue(limits.max_concurrent_merges, limits.job_timeout_seconds),
        signer=LinkSigner(settings.signing_key, settings.download_link_seconds),
        limits=limits,
        public_base_url=settings.public_base_url,
        file_ttl_seconds=settings.file_ttl_seconds,
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv_pdf_merger\Scripts\python -m pytest tests/test_job_queue.py tests/test_service.py -q`
Expected: PASS.

- [ ] **Step 6: Run the whole suite**

Run: `.venv_pdf_merger\Scripts\python -m pytest -q`
Expected: PASS (all tests so far).

- [ ] **Step 7: Commit**

```bash
git add pdf_merger/src/jobs pdf_merger/src/service.py pdf_merger/tests/conftest.py pdf_merger/tests/test_job_queue.py pdf_merger/tests/test_service.py
git commit -m "feat(pdf_merger): add job queue and MergeService facade"
```

---

### Task 8: REST API, sweeper and full app factory

**Files:**
- Create: `pdf_merger/src/api/__init__.py` (empty), `src/api/deps.py`, `src/api/files.py`, `src/api/merge.py`, `src/store/sweeper.py`
- Replace: `pdf_merger/src/app.py`
- Test: `pdf_merger/tests/test_api.py`, `pdf_merger/tests/test_sweeper.py`

**Interfaces:**
- Consumes: `MergeService`, `Caller`, `build_service` (Task 7), models (Task 6), names (Task 3).
- Produces:
  - `COOKIE_NAME = "pm_session"`, `get_service(request) -> MergeService`, `get_caller(request, response) -> Caller`.
  - Routes: `GET /api/health`, `POST /api/files` (raw body, `X-Filename` URL-encoded header) → 201 `FileInfo`, `GET /api/files` → `list[FileInfo]`, `DELETE /api/files/{file_id}` → 204, `GET /api/files/{file_id}/content` → file, `GET /api/files/{file_id}/download?exp=&sig=` → attachment, `POST /api/merge` → 202 `{"job_id": str}`, `GET /api/jobs/{job_id}/events` → `text/event-stream` with `data: <json>\n\n` per event.
  - `run_sweeper(service: MergeService, interval_seconds: float, stop: asyncio.Event) -> None`.
  - `create_app(settings: Settings, service: MergeService | None = None) -> FastAPI`.

Session rules: a valid `X-Internal-Token` makes the caller `Caller("mcp:<X-Requester-Username or anonymous>", privileged=True)`. Otherwise the `pm_session` cookie (created if missing or malformed) makes `Caller("web:<cookie>")`.

- [ ] **Step 1: Write the failing tests**

`pdf_merger/tests/test_api.py`:

```python
from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from urllib.parse import quote, urlsplit

import pytest
from fastapi.testclient import TestClient

from src.app import create_app
from src.config import Limits
from tests.conftest import TEST_TOKEN, make_image, make_pdf, page_widths


@pytest.fixture
def app(settings):
    return create_app(settings)


@pytest.fixture
def client(app):
    with TestClient(app) as test_client:
        yield test_client


def upload(client: TestClient, path: Path, headers: dict | None = None):
    return client.post(
        "/api/files", content=path.read_bytes(), headers={"X-Filename": quote(path.name), **(headers or {})}
    )


def events(client: TestClient, job_id: str) -> list[dict]:
    with client.stream("GET", f"/api/jobs/{job_id}/events") as response:
        assert response.headers["content-type"].startswith("text/event-stream")
        body = "".join(response.iter_text())
    return [json.loads(line[len("data: ") :]) for line in body.splitlines() if line.startswith("data: ")]


def test_upload_sets_cookie_and_lists_file(client, tmp_path: Path):
    response = upload(client, make_pdf(tmp_path / "résumé.pdf", [100, 101]))

    assert response.status_code == 201
    info = response.json()
    assert (info["name"], info["kind"], info["pages"]) == ("résumé.pdf", "pdf", 2)
    assert "pm_session" in client.cookies
    assert [f["file_id"] for f in client.get("/api/files").json()] == [info["file_id"]]


def test_other_browser_cannot_see_the_file(app, client, tmp_path: Path):
    file_id = upload(client, make_pdf(tmp_path / "a.pdf", [100])).json()["file_id"]

    stranger = TestClient(app)  # no "with": the app's lifespan may run only once
    assert stranger.get("/api/files").json() == []
    response = stranger.get(f"/api/files/{file_id}/content")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "file_not_found"


def test_content_is_served_inline(client, tmp_path: Path):
    path = make_pdf(tmp_path / "a.pdf", [100])
    file_id = upload(client, path).json()["file_id"]

    response = client.get(f"/api/files/{file_id}/content")

    assert response.status_code == 200
    assert response.content == path.read_bytes()
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"].startswith("inline;")


def test_unsupported_type_body(client, tmp_path: Path):
    text = tmp_path / "notes.txt"
    text.write_text("hello")

    response = upload(client, text)

    assert response.status_code == 415
    assert response.json()["error"]["code"] == "unsupported_type"


def test_declared_size_over_limit_is_refused_early(settings):
    small = dataclasses.replace(settings, limits=Limits(max_file_bytes=10))

    with TestClient(create_app(small)) as client:
        response = client.post("/api/files", content=b"x" * 11, headers={"X-Filename": "a.pdf"})

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "file_too_large"


def test_merge_streams_events_and_download_works(client, tmp_path: Path):
    pdf = upload(client, make_pdf(tmp_path / "a.pdf", [100, 101])).json()
    img = upload(client, make_image(tmp_path / "b.jpg")).json()
    plan = {
        "segments": [{"file_id": pdf["file_id"], "pages": "2"}, {"file_id": img["file_id"]}],
        "output": {"filename": "out.pdf"},
    }

    started = client.post("/api/merge", json=plan)
    assert started.status_code == 202
    stream = events(client, started.json()["job_id"])

    assert stream[0]["type"] == "queued"
    done = stream[-1]
    assert done["type"] == "done" and done["pages"] == 2
    link = urlsplit(done["download_url"])
    download = client.get(f"{link.path}?{link.query}")
    assert download.status_code == 200
    assert download.headers["content-disposition"].startswith("attachment;")
    out = tmp_path / "downloaded.pdf"
    out.write_bytes(download.content)
    assert page_widths(out)[0] == 101


def test_tampered_download_link_is_not_found(client, tmp_path: Path):
    file_id = upload(client, make_pdf(tmp_path / "a.pdf", [100])).json()["file_id"]

    response = client.get(f"/api/files/{file_id}/download?exp=99999999999&sig={'0' * 64}")

    assert response.status_code == 404


def test_bad_plan_fails_immediately(client, tmp_path: Path):
    file_id = upload(client, make_pdf(tmp_path / "a.pdf", [100])).json()["file_id"]

    response = client.post("/api/merge", json={"segments": [{"file_id": file_id, "pages": "5"}]})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_range"


def test_malformed_body_is_invalid_request(client):
    response = client.post("/api/merge", json={"segments": []})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"


def test_delete(client, tmp_path: Path):
    file_id = upload(client, make_pdf(tmp_path / "a.pdf", [100])).json()["file_id"]

    assert client.delete(f"/api/files/{file_id}").status_code == 204
    assert client.get("/api/files").json() == []


def test_token_caller_can_use_a_web_file_by_id(app, client, tmp_path: Path):
    file_id = upload(client, make_pdf(tmp_path / "a.pdf", [100])).json()["file_id"]

    bot = TestClient(app)
    headers = {"X-Internal-Token": TEST_TOKEN, "X-Requester-Username": "alice"}
    assert bot.get(f"/api/files/{file_id}/content", headers=headers).status_code == 200
    assert bot.get("/api/files", headers=headers).json() == []


def test_wrong_token_is_treated_as_a_browser(app, client, tmp_path: Path):
    file_id = upload(client, make_pdf(tmp_path / "a.pdf", [100])).json()["file_id"]

    response = TestClient(app).get(f"/api/files/{file_id}/content", headers={"X-Internal-Token": "wrong"})
    assert response.status_code == 404
```

`pdf_merger/tests/test_sweeper.py`:

```python
from __future__ import annotations

import asyncio

from src.store.sweeper import run_sweeper


class FakeService:
    def __init__(self) -> None:
        self.calls = 0

    async def sweep(self) -> int:
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("disk hiccup")  # must not kill the loop
        return 0


async def test_sweeper_runs_until_stopped_and_survives_errors():
    service = FakeService()
    stop = asyncio.Event()

    task = asyncio.create_task(run_sweeper(service, 0.01, stop))
    await asyncio.sleep(0.05)
    stop.set()
    await asyncio.wait_for(task, 1)

    assert service.calls >= 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv_pdf_merger\Scripts\python -m pytest tests/test_api.py tests/test_sweeper.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.api'` / `src.store.sweeper`.

- [ ] **Step 3: Write the implementation**

`pdf_merger/src/store/sweeper.py`:

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

`pdf_merger/src/api/deps.py`:

```python
"""Request-scoped dependencies: the service and who is calling."""

from __future__ import annotations

import hmac
import re
import secrets

from fastapi import Request, Response

from src.service import Caller, MergeService

COOKIE_NAME = "pm_session"
TOKEN_HEADER = "X-Internal-Token"
REQUESTER_HEADER = "X-Requester-Username"
_SESSION_RE = re.compile(r"[A-Za-z0-9_-]{32}")


def get_service(request: Request) -> MergeService:
    return request.app.state.service


def _token_valid(request: Request) -> bool:
    """Constant-time compare. An unset expected token never validates."""
    expected = request.app.state.settings.internal_api_token
    provided = request.headers.get(TOKEN_HEADER, "")
    return bool(expected) and hmac.compare_digest(expected, provided)


def get_caller(request: Request, response: Response) -> Caller:
    if _token_valid(request):
        username = request.headers.get(REQUESTER_HEADER, "").strip() or "anonymous"
        return Caller(session=f"mcp:{username}", privileged=True)

    session_id = request.cookies.get(COOKIE_NAME, "")
    if not _SESSION_RE.fullmatch(session_id):
        session_id = secrets.token_urlsafe(24)  # 32 URL-safe characters
        response.set_cookie(
            COOKIE_NAME,
            session_id,
            max_age=request.app.state.settings.file_ttl_seconds,
            httponly=True,
            samesite="strict",
        )
    return Caller(session=f"web:{session_id}")
```

`pdf_merger/src/api/files.py`:

```python
"""File routes: upload, list, delete, raw content and signed download."""

from __future__ import annotations

from urllib.parse import unquote

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import FileResponse

from src.api.deps import get_caller, get_service
from src.errors import ErrorCode, MergerError
from src.models import FileInfo
from src.service import Caller, MergeService
from src.store.names import content_disposition

router = APIRouter(prefix="/api")


@router.post("/files", status_code=201)
async def upload_file(
    request: Request, caller: Caller = Depends(get_caller), service: MergeService = Depends(get_service)
) -> FileInfo:
    """Raw request body is the file; X-Filename carries its URL-encoded name."""
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > request.app.state.settings.limits.max_file_bytes:
        raise MergerError(ErrorCode.FILE_TOO_LARGE, "This file is over the size limit. Split or compress it, then upload it again.")
    name = unquote(request.headers.get("X-Filename", ""))
    stored = await service.upload(caller, name, request.stream())
    return FileInfo.of(stored)


@router.get("/files")
async def list_files(caller: Caller = Depends(get_caller), service: MergeService = Depends(get_service)) -> list[FileInfo]:
    return [FileInfo.of(f) for f in service.list_files(caller)]


@router.delete("/files/{file_id}", status_code=204)
async def delete_file(
    file_id: str, caller: Caller = Depends(get_caller), service: MergeService = Depends(get_service)
) -> Response:
    await service.delete_file(caller, file_id)
    return Response(status_code=204)


@router.get("/files/{file_id}/content")
async def file_content(
    file_id: str, caller: Caller = Depends(get_caller), service: MergeService = Depends(get_service)
) -> FileResponse:
    file = service.get_file(caller, file_id)
    return FileResponse(
        service.file_path(file),
        media_type=file.mime,
        headers={"Content-Disposition": content_disposition(file.name, inline=True), "Cache-Control": "private, max-age=3600"},
    )


@router.get("/files/{file_id}/download")
async def download(file_id: str, exp: int, sig: str, service: MergeService = Depends(get_service)) -> FileResponse:
    """Signed link; no cookie needed."""
    file = service.file_for_download(file_id, exp, sig)
    return FileResponse(
        service.file_path(file),
        media_type=file.mime,
        headers={"Content-Disposition": content_disposition(file.name), "Cache-Control": "private, no-store"},
    )
```

`pdf_merger/src/api/merge.py`:

```python
"""Merge routes: start a job, then follow it over server-sent events."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from src.api.deps import get_caller, get_service
from src.models import MergePlan
from src.service import Caller, MergeService

router = APIRouter(prefix="/api")


@router.post("/merge", status_code=202)
async def start_merge(
    plan: MergePlan, caller: Caller = Depends(get_caller), service: MergeService = Depends(get_service)
) -> dict:
    job = service.start_merge(caller, plan)
    return {"job_id": job.id}


@router.get("/jobs/{job_id}/events")
async def job_events(
    job_id: str, caller: Caller = Depends(get_caller), service: MergeService = Depends(get_service)
) -> StreamingResponse:
    job = service.get_job(caller, job_id)

    async def body() -> AsyncIterator[str]:
        async for event in job.stream():
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(
        body(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )
```

Replace `pdf_merger/src/app.py`:

```python
"""FastAPI application factory: routers, error handlers, CORS and the sweeper."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.api import files, merge
from src.config import Settings
from src.errors import ErrorCode, MergerError
from src.service import MergeService, build_service
from src.store.sweeper import run_sweeper


def create_app(settings: Settings, service: MergeService | None = None) -> FastAPI:
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

    app = FastAPI(title="pdf_merger", lifespan=lifespan)
    app.state.settings = settings
    app.state.service = service

    @app.exception_handler(MergerError)
    async def merger_error(_: Request, error: MergerError) -> JSONResponse:
        return JSONResponse(error.to_body(), status_code=error.http_status)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, error: RequestValidationError) -> JSONResponse:
        first = error.errors()[0] if error.errors() else {}
        where = ".".join(str(part) for part in first.get("loc", ()) if part != "body")
        message = f"{where}: {first.get('msg', 'invalid value')}" if where else str(first.get("msg", "Invalid request."))
        body = MergerError(ErrorCode.INVALID_REQUEST, message).to_body()
        return JSONResponse(body, status_code=422)

    @app.get("/api/health")
    async def health() -> dict:
        return {"status": "ok"}

    app.include_router(files.router)
    app.include_router(merge.router)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.web_origin],
        allow_credentials=True,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Content-Type", "X-Filename"],
    )
    return app
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv_pdf_merger\Scripts\python -m pytest -q`
Expected: PASS (whole suite, including `test_health.py`).

- [ ] **Step 5: Commit**

```bash
git add pdf_merger/src/api pdf_merger/src/app.py pdf_merger/src/store/sweeper.py pdf_merger/tests/test_api.py pdf_merger/tests/test_sweeper.py
git commit -m "feat(pdf_merger): add REST API with sessions, SSE progress and signed downloads"
```

---

### Task 9: MCP tools and token-protected `/mcp`

**Files:**
- Create: `pdf_merger/src/internal_token.py`, `pdf_merger/src/mcp_tools/__init__.py` (empty), `src/mcp_tools/contract.py`, `src/mcp_tools/tools.py`
- Modify: `pdf_merger/src/app.py`
- Test: `pdf_merger/tests/test_mcp_tools.py`, `pdf_merger/tests/test_internal_token.py`

**Interfaces:**
- Consumes: `MergeService`, `Caller` (Task 7), `MergePlan`, `FileInfo`, `MergeResult` (Task 6), `create_app` (Task 8).
- Produces:
  - `InternalTokenMiddleware(app, token: str)` (pure ASGI; protects `/mcp` and `/mcp/...`; empty token rejects everything).
  - `FailedItem(file_id, code, message)`, `InspectResult(files: list[FileInfo], failed: list[FailedItem], message: str)`, `ListFilesResult(files: list[FileInfo], message: str)`, `MergeToolResult(MergeResult fields + message: str)`.
  - `caller_from_context(ctx) -> Caller`, `build_mcp(service: MergeService) -> FastMCP` registering `tool_pdf_inspect`, `tool_pdf_merge`, `tool_pdf_listFiles`.

- [ ] **Step 1: Write the failing tests**

`pdf_merger/tests/test_mcp_tools.py`:

```python
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from mcp.server.fastmcp.exceptions import ToolError

from src.mcp_tools.tools import build_mcp, caller_from_context
from src.service import Caller
from tests.conftest import chunks, make_pdf

WEB = Caller("web:1")


async def upload_pdf(service, tmp_path: Path, widths=(100, 101)) -> str:
    path = make_pdf(tmp_path / "a.pdf", list(widths))
    return (await service.upload(WEB, path.name, chunks(path.read_bytes()))).file_id


async def test_tools_are_listed_with_labels_and_keywords(service):
    tools = {tool.name: tool for tool in await build_mcp(service).list_tools()}

    assert set(tools) == {"tool_pdf_inspect", "tool_pdf_merge", "tool_pdf_listFiles"}
    for tool in tools.values():
        assert tool.meta["display_label"]
        assert tool.meta["keywords"]


async def test_inspect_reports_found_and_failed(service, tmp_path: Path):
    file_id = await upload_pdf(service, tmp_path)

    _, result = await build_mcp(service).call_tool("tool_pdf_inspect", {"file_ids": f"{file_id}, f_nope"})

    assert [f["file_id"] for f in result["files"]] == [file_id]
    assert result["failed"][0]["file_id"] == "f_nope"
    assert result["failed"][0]["code"] == "file_not_found"
    assert "1 of 2" in result["message"]


async def test_merge_returns_download_url(service, tmp_path: Path):
    file_id = await upload_pdf(service, tmp_path)
    plan = {"segments": [{"file_id": file_id, "pages": "2,1"}], "output": {"filename": "x.pdf"}}

    _, result = await build_mcp(service).call_tool("tool_pdf_merge", {"plan": plan})

    assert result["pages"] == 2
    assert "/download?exp=" in result["download_url"]
    assert result["message"].startswith("Merged 2 pages")


async def test_merge_error_is_a_tool_error_with_code(service, tmp_path: Path):
    file_id = await upload_pdf(service, tmp_path)

    with pytest.raises(ToolError, match="invalid_range"):
        await build_mcp(service).call_tool("tool_pdf_merge", {"plan": {"segments": [{"file_id": file_id, "pages": "9"}]}})


async def test_list_files_without_request_context_is_anonymous(service, tmp_path: Path):
    _, result = await build_mcp(service).call_tool("tool_pdf_listFiles", {})

    assert result["files"] == []


def test_caller_from_meta_then_header_then_anonymous():
    def ctx(meta_extra=None, headers=None):
        meta = SimpleNamespace(model_extra=meta_extra) if meta_extra is not None else None
        request = SimpleNamespace(headers=headers) if headers is not None else None
        return SimpleNamespace(request_context=SimpleNamespace(meta=meta, request=request))

    assert caller_from_context(ctx({"requester": {"username": "alice"}})) == Caller("mcp:alice", privileged=True)
    assert caller_from_context(ctx(None, {"x-requester-username": "bob"})) == Caller("mcp:bob", privileged=True)
    assert caller_from_context(ctx({}, {})) == Caller("mcp:anonymous", privileged=True)
```

`pdf_merger/tests/test_internal_token.py`:

```python
from __future__ import annotations

import dataclasses

from fastapi.testclient import TestClient

from src.app import create_app
from tests.conftest import TEST_TOKEN

INIT = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
HEADERS = {"Accept": "application/json, text/event-stream"}


def test_mcp_without_token_is_401(settings):
    with TestClient(create_app(settings)) as client:
        response = client.post("/mcp", json=INIT, headers=HEADERS)

    assert response.status_code == 401


def test_mcp_with_token_passes_the_middleware(settings):
    with TestClient(create_app(settings)) as client:
        response = client.post("/mcp", json=INIT, headers={**HEADERS, "X-Internal-Token": TEST_TOKEN})

    assert response.status_code != 401


def test_unset_token_never_validates(settings):
    open_settings = dataclasses.replace(settings, internal_api_token="")

    with TestClient(create_app(open_settings)) as client:
        response = client.post("/mcp", json=INIT, headers={**HEADERS, "X-Internal-Token": ""})

    assert response.status_code == 401


def test_rest_api_is_not_affected(settings):
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/health").status_code == 200
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv_pdf_merger\Scripts\python -m pytest tests/test_mcp_tools.py tests/test_internal_token.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.mcp_tools'` and 404 (not 401) for `/mcp`.

- [ ] **Step 3: Write the implementation**

`pdf_merger/src/internal_token.py`:

```python
"""Require X-Internal-Token on /mcp (copied from mcp_server's internal_token.py;
the repo forbids cross-project imports).

Difference from mcp_server: an unset token rejects every /mcp call instead of
allowing them, so a fresh install never exposes tools by accident.
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

`pdf_merger/src/mcp_tools/contract.py`:

```python
"""MCP tool result models. Each ends with a human-readable ``message``."""

from __future__ import annotations

from pydantic import BaseModel

from src.models import FileInfo, MergeResult


class FailedItem(BaseModel):
    file_id: str
    code: str
    message: str


class InspectResult(BaseModel):
    files: list[FileInfo]
    failed: list[FailedItem]
    message: str


class ListFilesResult(BaseModel):
    files: list[FileInfo]
    message: str


class MergeToolResult(MergeResult):
    message: str
```

`pdf_merger/src/mcp_tools/tools.py`:

```python
"""MCP tools: thin glue over MergeService. No logic and no AI calls here.

Who is asking comes from the request's _meta.requester (set by ai_agent and
forwarded by mcp_server), else the X-Requester-Username header, else
"anonymous". It is never a tool parameter, so a model cannot pick it.
"""

from __future__ import annotations

from typing import Annotated, Any

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import Field

from src.errors import MergerError
from src.mcp_tools.contract import FailedItem, InspectResult, ListFilesResult, MergeToolResult
from src.models import FileInfo, MergePlan
from src.service import Caller, MergeService

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


def _tool_error(error: MergerError) -> ToolError:
    return ToolError(f"{error.code}: {error.message}")


def build_mcp(service: MergeService) -> FastMCP:
    # The internal token protects /mcp, so DNS-rebinding host checks would only
    # block legitimate LAN callers that reach this server by IP.
    mcp = FastMCP(
        "pdf_merger",
        stateless_http=True,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )

    @mcp.tool(meta={"keywords": ["pdf", "inspect", "pages", "file", "info"], "display_label": "Inspecting files"})
    async def tool_pdf_inspect(
        file_ids: Annotated[str, Field(description="Comma-separated file IDs (f_...) the user gave you.")],
        ctx: Context,
    ) -> InspectResult:
        """Look up uploaded files: name, kind (pdf or image), page count, size and expiry.

        Call this before tool_pdf_merge so you know each PDF's page count when
        choosing page ranges. File IDs come from the user (the PDF merger web
        app has a "Copy ID" button). Never invent an ID.
        """
        files, failed = service.inspect(caller_from_context(ctx), [i.strip() for i in file_ids.split(",") if i.strip()])
        return InspectResult(
            files=[FileInfo.of(f) for f in files],
            failed=[FailedItem(file_id=i, code=str(e.code), message=e.message) for i, e in failed],
            message=f"Found {len(files)} of {len(files) + len(failed)} file(s).",
        )

    @mcp.tool(meta={"keywords": ["pdf", "merge", "combine", "join", "images"], "display_label": "Merging files"})
    async def tool_pdf_merge(
        plan: Annotated[MergePlan, Field(description="Ordered segments plus output options.")],
        ctx: Context,
    ) -> MergeToolResult:
        """Merge PDFs and images into one PDF, in segment order.

        Each segment takes pages from one file ("1-3,7", 1-based; null = all).
        Use several segments of the same file to interleave pages. Each page may
        appear once. Images become one page each, laid out by output.image_*.
        Returns a download link valid for about an hour and the new file's ID,
        which can be merged again. Run tool_pdf_inspect first.
        """
        try:
            result = await service.merge_and_wait(caller_from_context(ctx), plan)
        except MergerError as error:
            raise _tool_error(error) from error
        return MergeToolResult(**result.model_dump(), message=f"Merged {result.pages} pages into {result.name}.")

    @mcp.tool(meta={"keywords": ["pdf", "files", "list", "uploads"], "display_label": "Listing files"})
    async def tool_pdf_listFiles(ctx: Context) -> ListFilesResult:
        """List files this assistant session has uploaded or produced, with expiry.

        Files uploaded in the web app belong to the browser and are not listed
        here; ask the user for their IDs instead.
        """
        files = service.list_files(caller_from_context(ctx))
        return ListFilesResult(files=[FileInfo.of(f) for f in files], message=f"{len(files)} file(s).")

    return mcp
```

Modify `pdf_merger/src/app.py`:

1. Add imports:

```python
from src.internal_token import InternalTokenMiddleware
from src.mcp_tools.tools import build_mcp
```

2. After `service = service or build_service(settings)`, add:

```python
    mcp = build_mcp(service)
    mcp_app = mcp.streamable_http_app()  # serves /mcp
```

3. In `lifespan`, wrap the `yield` so the MCP session manager runs (a mounted app's own lifespan is not run):

```python
        try:
            async with mcp.session_manager.run():
                yield
        finally:
            stop.set()
            await sweeper
```

4. After `app.include_router(merge.router)`, mount MCP and add the token middleware:

```python
    app.mount("/", mcp_app)  # after the routers, so /api/* matches first
    app.add_middleware(InternalTokenMiddleware, token=settings.internal_api_token)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv_pdf_merger\Scripts\python -m pytest -q`
Expected: PASS (whole suite). If `TransportSecuritySettings` fails to import, the installed `mcp` is older than this plan assumes: run `pip install -U "mcp>=1.28,<2"`.

- [ ] **Step 5: Commit**

```bash
git add pdf_merger/src/internal_token.py pdf_merger/src/mcp_tools pdf_merger/src/app.py pdf_merger/tests/test_mcp_tools.py pdf_merger/tests/test_internal_token.py
git commit -m "feat(pdf_merger): expose merge tools over token-protected MCP"
```

---

### Task 10: README, deferred items and a live smoke run

**Files:**
- Create: `pdf_merger/README.md`
- Modify: `Python/MCPServer/_TODO.md` (append)

- [ ] **Step 1: Write the README**

`pdf_merger/README.md`:

````markdown
# pdf_merger

Merges PDFs and images (JPG, PNG, WebP, TIFF, GIF, HEIC) into one PDF.

- REST API under `/api` for `pdf_merger_web`.
- MCP endpoint at `/mcp` for `mcp_server` (added there as an HTTP extension). Requires `X-Internal-Token`.

Design: `../docs/superpowers/specs/2026-10-02-pdf-merger-design.md`.

## Requirements

Python 3.11+. Dependencies install from `pyproject.toml` on first run.

## Setup

1. Run `run.bat` once. It creates `.venv_pdf_merger`, installs the project, and copies
   `configs/config_pdf_merger.json` and `.secrets/*.env` from their `.example` twins.
2. In `.secrets/secret_internal_api.env`, set `INTERNAL_API_TOKEN` to the same value as `mcp_server`.
3. In `.secrets/secret_signing.env`, set `PDF_MERGER_SIGNING_KEY` to a random value:
   `py -c "import secrets; print(secrets.token_hex(32))"`.
4. If other machines will open download links, set `public_base_url` in the config to this machine's LAN address.

## Run

```
run.bat
```

Default port 8040 (`PDF_MERGER_PORT`). Files live in `.data/store/` and are deleted after `file_ttl_hours`.

## API

| Method | Path | Notes |
|---|---|---|
| POST | `/api/files` | Raw body; `X-Filename` header holds the URL-encoded name |
| GET | `/api/files` | Files of this session |
| DELETE | `/api/files/{id}` | |
| GET | `/api/files/{id}/content` | Raw source |
| POST | `/api/merge` | `MergePlan` body, returns `{job_id}` |
| GET | `/api/jobs/{id}/events` | SSE, one JSON object per `data:` line |
| GET | `/api/files/{id}/download?exp=&sig=` | Signed link |

Browsers get a `pm_session` cookie. Callers with a valid `X-Internal-Token` act as `mcp:<X-Requester-Username>` and can open any file by ID.

## MCP tools

`tool_pdf_inspect`, `tool_pdf_merge`, `tool_pdf_listFiles`.

## Tests

```
.venv_pdf_merger\Scripts\python -m pytest -q
```
````

- [ ] **Step 2: Log deferred items**

Append to `Python/MCPServer/_TODO.md`:

```markdown
## PDF merger: deferred features (added 2026-10-02)

**Context**: `pdf_merger` v1 merges PDFs and images. These were left out on purpose (see `docs/superpowers/specs/2026-10-02-pdf-merger-design.md`).

- **Word and office documents**: add a `DocxConverter` in `pdf_merger/src/converters/` that runs LibreOffice headless (`soffice --headless --convert-to pdf`) in a subprocess, and register it in `registry.py`. Needs LibreOffice on the host (~350 MB). Run conversions with `asyncio.create_subprocess_exec` and a timeout.
- **Encrypted PDFs**: accept a password per file and open with `pikepdf.open(path, password=...)`.
- **Output options**: compression/optimization, page delete and duplicate in the web page strip, a split tool.
- **Ember upload proxy**: let users drop files in Ember chat and have ember_api forward them to `pdf_merger` `POST /api/files` with the internal token and `X-Requester-Username`, so they land in the user's MCP session.

**Revisit when**: the user asks for any of these.
```

- [ ] **Step 3: Live smoke run**

Run in one terminal: `run.bat` (from `pdf_merger/`).
Expected banner: uvicorn running on `http://127.0.0.1:8040`.

In another terminal, with any small PDF at `C:\temp\a.pdf`:

```bash
curl -s -X POST http://127.0.0.1:8040/api/files -H "X-Filename: a.pdf" --data-binary @C:/temp/a.pdf -c jar.txt
```

Expected: JSON with `"kind":"pdf"` and a `file_id`. Then:

```bash
curl -s -X POST http://127.0.0.1:8040/api/merge -b jar.txt -H "Content-Type: application/json" -d "{\"segments\":[{\"file_id\":\"<file_id>\"}]}"
```

Expected: `{"job_id":"j_..."}`. Then `curl -N -b jar.txt http://127.0.0.1:8040/api/jobs/<job_id>/events` ends with a `done` event whose `download_url` downloads the PDF. Stop the server; delete `jar.txt`.

- [ ] **Step 4: Commit**

```bash
git add pdf_merger/README.md _TODO.md
git commit -m "docs(pdf_merger): add README and log deferred features"
```

---

## Self-review notes

- Spec coverage: inputs and converters (Task 5), ranges (2), rotation and bookmarks and metadata (6), store, TTL, quotas, sessions (4, 8), signed links (4, 7, 8), REST routes (8), SSE (8), MCP tools and token (9), limits (1, 4, 6, 7), safety (3, 4), README and deferred items (10). Web UI is plan 2; `mcp_server` changes, launcher group and vault sync are plan 3.
