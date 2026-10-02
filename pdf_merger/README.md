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
Merges stop cooperatively after the job timeout (`merge_timeout`). Unexpected errors return a generic JSON 500 (`internal_error`).

## API

| Method | Path | Notes |
|---|---|---|
| POST | `/api/files` | Raw body; `X-Filename` header holds the URL-encoded name |
| GET | `/api/files` | Files of this session |
| DELETE | `/api/files/{id}` | |
| GET | `/api/files/{id}/content` | Raw source |
| POST | `/api/merge` | `MergePlan` body, returns `{job_id}` |
| GET | `/api/jobs/{id}/events` | SSE, one JSON object per `data:` line |
| GET | `/api/files/{id}/download?exp=&sig=` | Signed link; sent with `X-Content-Type-Options: nosniff` |

Browsers get a `pm_session` cookie. Callers with a valid `X-Internal-Token` act as `mcp:<X-Requester-Username>` and can open any file by ID.

## MCP tools

`tool_pdf_inspect`, `tool_pdf_merge`, `tool_pdf_listFiles`.

## Tests

```
.venv_pdf_merger\Scripts\python -m pytest -q
```
