# PDF merger design

Date: 2026-10-02
Status: approved design, not implemented

## Goal

A tool that merges PDFs and images into one PDF. People use it through a dedicated web app (Vite + Vue 3 + TypeScript). LLM agents use it through MCP, reached via `mcp_server`, so it shows up in Ember and chat_app with no change on their side.

## Scope

In v1:

- Inputs: PDF, JPEG, PNG, WebP, TIFF, GIF (first frame), HEIC.
- Ordered merge of files.
- Page ranges per PDF (`1-3,7`).
- Rotation per segment.
- Image placement: page size (A4, Letter, match image), fit mode (fit, fill, original), margin.
- Page thumbnails and drag reorder at page level in the web app.
- Output metadata (title, author) and one bookmark per source segment.
- MCP tools to inspect, merge and list files.

Out of v1 (logged in `_TODO.md`):

- Word and office documents. Planned path: a `DocxConverter` using LibreOffice headless (`soffice --headless --convert-to pdf`). The converter interface below exists so this needs no change to other units.
- Unlocking encrypted PDFs with a user password.
- Output compression or optimization, page delete or duplicate in the strip, a split tool.
- An Ember upload proxy so users can drop files in Ember chat and have them land in pdf_merger.

## Decisions

| Decision | Choice | Why |
|---|---|---|
| Where the engine lives | Standalone service `pdf_merger/` | Repo rule: projects are self-contained, no cross-imports. The web app does not depend on `mcp_server` being up. |
| How `mcp_server` reaches it | HTTP extension in `mcp_server/configs/config_extensions.json` | Extensions already re-expose upstream tools under their own names. No new capability code in `mcp_server`. |
| File transport for MCP | File IDs plus a TTL store | Tool payloads stay small. Base64 would flood the LLM context. Server paths do not work for remote users. |
| PDF library | pikepdf + img2pdf + Pillow (+ pillow-heif) | qpdf-backed speed, lossless JPEG embedding, permissive licenses. PyMuPDF was rejected for its AGPL-3.0 license. pypdf was rejected for speed and image re-encoding. |
| Thumbnails | Rendered in the browser with `pdfjs-dist` | Keeps the server light. No server-side rasterizer needed. |
| Access control | LAN use, no login | Same trust model as the other dev servers. `/mcp` and token uploads still require `INTERNAL_API_TOKEN`. |

## Architecture

```
browser --> pdf_merger_web (5174) --/api--> pdf_merger (8040)
ember / chat_app --> ai_agent --> mcp_server (8010) --extension /mcp--> pdf_merger (8040)
```

Two new projects in `Python/MCPServer/`:

- `pdf_merger/` — FastAPI service on port 8040 (`PDF_MERGER_PORT`). Owns the engine, the file store, the REST API under `/api`, and a FastMCP endpoint mounted at `/mcp` (streamable HTTP).
- `pdf_merger_web/` — Vite + Vue 3 + TS on port 5174. Talks only to the `pdf_merger` REST API. The Vite dev server proxies `/api` to `http://127.0.0.1:8040`.

Both REST routers and MCP tools call one `MergeService`. Routers and tools hold no logic.

### Engine units (`pdf_merger/src/`)

Each unit has one job and is testable alone.

- `converters/base.py` — `SourceConverter` protocol: `kind: str`, `can_handle(mime: str) -> bool`, `async to_pdf(src: Path, opts: ImageOptions) -> Path`. Blocking work runs in `asyncio.to_thread`.
- `converters/pdf.py` — `PdfPassthrough`. Opens with pikepdf to validate. Rejects encrypted files with `encrypted_pdf`.
- `converters/image.py` — `ImageConverter`. Applies EXIF orientation. Embeds JPEG bytes unchanged through img2pdf when no transform is needed; otherwise normalizes through Pillow (alpha flattened onto white). Applies page size, fit mode and margin. Enforces the max pixel count.
- `converters/registry.py` — picks a converter by sniffed MIME type. New converters register here; nothing else changes.
- `engine/page_ranges.py` — parses `1-3,7`, `all` or null into 0-based indices. Rejects out-of-bounds, reversed and malformed ranges with `invalid_range`.
- `engine/planner.py` — validates a `MergePlan` against file metadata and expands it into an ordered list of page references (file, page index, rotation).
- `engine/assembler.py` — builds the output with pikepdf: copies pages in order, adds rotation to each page's own `/Rotate`, writes outlines and document info.
- `store/file_store.py` — `FileStore`. Session-scoped directories, file IDs, size and quota checks, metadata sidecar (`<file_id>.json`).
- `store/sniff.py` — detects type from magic bytes. File extensions are ignored.
- `store/sweeper.py` — background task that deletes expired files.
- `store/signing.py` — HMAC-SHA256 signed download links.
- `jobs/job_queue.py` — runs merges under a global `asyncio.Semaphore`, publishes progress events, enforces the job timeout.
- `service.py` — `MergeService`: the one facade used by `api/` and `mcp/`.

## Merge plan

One schema serves the web app and MCP. A plan is an ordered list of segments. A page-level reorder in the web app becomes several segments of the same file (for example `contract 1-2`, `receipt`, `contract 3`). An LLM writes the same shape by hand.

```jsonc
{
  "segments": [
    {
      "file_id": "f_ab12...",
      "pages": "1-3,7",   // 1-based; null or "all" = every page; ignored for images
      "rotate": 0,        // 0 | 90 | 180 | 270, added to the page's existing rotation
      "fit": null         // images only: "fit" | "fill" | "original"; null = output default
    }
  ],
  "output": {
    "filename": "merged.pdf",
    "title": null,
    "author": null,
    "bookmarks": true,          // one per segment; neighbouring segments of the same file collapse into one
    "image_page_size": "A4",    // "A4" | "Letter" | "match"
    "image_fit": "fit",         // default for image segments
    "image_margin_mm": 10
  }
}
```

Bookmark titles are the source filename without extension.

## REST API (`/api`)

| Method | Path | Purpose |
|---|---|---|
| POST | `/files` | Multipart upload, streamed to disk in chunks. Returns `{file_id, name, kind, pages, size, expires_at}`. |
| GET | `/files` | Lists the caller's session files. |
| DELETE | `/files/{id}` | Deletes a file before it expires. |
| GET | `/files/{id}/content` | Returns the raw source (used by pdf.js for thumbnails). |
| POST | `/merge` | Body: `MergePlan`. Returns `{job_id}`. |
| GET | `/jobs/{id}/events` | Server-sent events: `progress {done, total}`, `done {file_id, pages, size, download_url}`, `error {code, message}`. |
| GET | `/files/{id}/download?exp=&sig=` | Signed link, valid 1 hour. No cookie needed, so Ember download cards can use it. |

## Sessions and access

- Web: a random `pm_session` cookie (HttpOnly, SameSite=Strict), set on first request. Cookie access to a file of another session returns 404, never 403.
- MCP and token callers (`X-Internal-Token` header): the session is `mcp:<requester username>` from `_meta.requester`, or `mcp:anonymous` when absent. Token callers may read any file by ID. File IDs are 128-bit random values, so an ID works as a capability. This is how a file uploaded in the web app reaches a chat: the web app has a "Copy ID" action on each file and on the merge result.
- `tool_pdf_listFiles` lists only the caller's MCP session files.
- `/mcp` rejects calls without a valid `X-Internal-Token` (constant-time compare; an unset token never validates).

## MCP tools

Repo naming (`tool_<alias>_<camelTask>`, alias `pdf`). Every tool has `meta.display_label` and `meta.keywords`. Tools never call an AI.

| Tool | Parameters | Result | Display label |
|---|---|---|---|
| `tool_pdf_inspect` | `file_ids: str` (comma-separated) | Per file: name, kind, pages, size, expires_at; plus a `failed` list; `message` | Inspecting files |
| `tool_pdf_merge` | `plan: MergePlan` | `file_id, pages, size, download_url, message` | Merging files |
| `tool_pdf_listFiles` | none | Session files with expiry; `message` | Listing files |

`tool_pdf_merge` waits for its job (timeout 120 s) and returns the result directly. Docstrings tell the model: take file IDs from the user, never invent IDs, call `tool_pdf_inspect` before choosing page ranges.

## Errors

Every error body is `{"error": {"code": "...", "message": "..."}}`. MCP results use the same codes. Raw exceptions are logged and never returned.

| Code | When |
|---|---|
| `unsupported_type` | Sniffed type has no converter. |
| `file_too_large` | Upload over the per-file limit. |
| `encrypted_pdf` | PDF needs a password. |
| `corrupt_file` | pikepdf or Pillow cannot open the file. |
| `invalid_range` | Bad page range. Message names the segment and the file's page count. |
| `file_not_found` | Unknown, expired, or other-session file. |
| `limit_exceeded` | Session quota, segment count, output page count, or image pixel limit. |
| `merge_timeout` | Job ran past its timeout. |

## Limits

All in `configs/config_pdf_merger.json`, with these defaults:

- 100 MB per file, 500 MB per session (results count toward it).
- 50 segments per plan, 2000 output pages.
- 80 megapixels per image (also set as Pillow's `MAX_IMAGE_PIXELS`).
- 2 concurrent merges; extra jobs queue.
- Job timeout 120 s.
- File TTL 6 hours; sweeper runs every 10 minutes.
- CORS allows only the configured web origin.

## Safety

- Files are stored as `.data/store/<session>/<file_id>`. The user's filename is metadata only and is sanitized before it goes into `Content-Disposition`.
- No path ever comes from the client.
- Type comes from magic bytes, not the extension.

## Project layout

### `pdf_merger/`

Follows the root-project-scaffold skill, dotted variant (it owns runtime state).

```
pdf_merger/
  README.md
  pyproject.toml
  run.bat                                  # LABEL: PDF Merger; PDF_MERGER_PORT=8040; .venv_pdf_merger
  configs/config_pdf_merger.json(.example)
  .secrets/secret_internal_api.env(.example)
  .secrets/secret_signing.env(.example)
  .data/store/                             # gitignored, swept by TTL
  .logs/server.log                         # rotating
  src/
    run.py  app.py  config.py  errors.py  logging_setup.py  service.py
    api/        files.py  merge.py  jobs.py  deps.py
    mcp/        tools.py  contract.py
    engine/     planner.py  assembler.py  page_ranges.py
    converters/ base.py  pdf.py  image.py  registry.py
    store/      file_store.py  sniff.py  sweeper.py  signing.py
    jobs/       job_queue.py
  tests/
```

Dependencies: fastapi, uvicorn, mcp, pikepdf, img2pdf, pillow, pillow-heif, python-multipart, pydantic. Dev: pytest, pytest-asyncio, httpx.

### `pdf_merger_web/`

Same stack as ember_web: Vue 3.5, Pinia, Vite 8, Vitest, vue-tsc. One page, so no router. One new dependency: `pdfjs-dist`.

```
pdf_merger_web/
  README.md  package.json  vite.config.ts  index.html  run.bat
  src/
    main.ts  App.vue
    api/client.ts  api/types.ts             # typed fetch, SSE wrapper
    stores/files.ts  stores/plan.ts         # plan store derives segments from the page strip
    components/
      DropZone.vue  SourceList.vue  SourceRow.vue
      PageStrip.vue  PageThumb.vue  OutputPanel.vue  MergeBar.vue
    lib/pdfThumbs.ts                        # lazy render, IntersectionObserver, pdf.js worker
    lib/segments.ts                         # page order <-> segments, pure functions
```

### UI

One screen, top to bottom:

1. Header with app name and the file retention note.
2. Drop zone listing accepted types and the size limit. Also opens a file picker.
3. Source files: one row per file with drag handle, type icon, name, page count and size. PDF rows have a page-range input; image rows have a fit dropdown. Each row has rotate, copy ID and remove actions.
4. Page strip: thumbnails of every selected page in output order, draggable. File order sets the default order; dragging overrides it.
5. Output panel: file name, title, author, image page size, image margin, bookmarks checkbox.
6. Merge bar: summary ("7 pages from 3 files"), live progress from SSE, then download link and copy ID for the result.

Changing a row's range or rotation rebuilds the strip, keeping any manual order for pages that remain.

## Integration

- `mcp_server/configs/config_extensions.json`: add a `pdf_merger` entry with `url: http://127.0.0.1:8040/mcp`.
- Required `mcp_server` change: today `services/extensions.py` calls `streamablehttp_client(config.url)` with no headers, and proxied calls do not forward the requester. Add an optional `headers` field to HTTP extension entries (values support `${ENV}` expansion, so `X-Internal-Token` comes from `secret_internal_api.env`), and forward the caller's requester as `_meta.requester` on proxied calls.
- `server_launcher`: new "PDF Merger" group with pdf_merger and pdf_merger_web.
- Ember download cards: `tool_pdf_merge` returns a signed `download_url` pointing straight at pdf_merger, so this tool does not depend on the pending `/download` route in `mcp_server`.
- Vault: after the build, run project-sync for `Brain/Projects/MCPServer.md` and add component notes `pdf_merger.md` and `pdf_merger_web.md`.

## Testing

Python (pytest, pytest-asyncio, httpx `AsyncClient`). Fixtures are generated in `conftest.py`; no binary test files are committed.

- `page_ranges`: `1-3,7`, `all`, null, reversed, out of bounds, malformed input.
- Converters: JPEG embedded with unchanged bytes, PNG with alpha, EXIF rotation, HEIC, an image over the pixel limit is rejected, encrypted PDF is rejected.
- Assembler: page order, rotation adds to existing rotation, bookmarks collapse for neighbouring same-file segments, metadata written.
- Store: session isolation returns 404, TTL sweep, quota, magic-byte sniff (a PNG named `.pdf`).
- API and MCP: end-to-end merge, SSE event sequence, signed URL expiry and tampering, `/mcp` rejects a missing or wrong token.

Web (Vitest + @vue/test-utils, pdf.js mocked):

- `segments.ts`: page order to segments and back.
- Plan store: range edit keeps manual order.
- `SourceRow`: inline range validation.
- `MergeBar`: idle, running, done and error states.

## Success criteria

- A user merges two PDFs (with a page range) and one photo in the web app and downloads a correct PDF with bookmarks.
- In Ember, an agent merges files by ID through `tool_pdf_merge` and the answer shows a working download link.
- A Word document upload returns `unsupported_type` with a clear message.
- All tests pass in both projects.
