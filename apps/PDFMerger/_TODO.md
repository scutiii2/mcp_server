# _TODO.md

Deferred items — not scheduled, revisit when the trigger condition below is met.

## PDF merger: deferred features (added 2026-10-02)

**Context**: `pdf_merger` v1 merges PDFs and images. These were left out on purpose (see `docs/superpowers/specs/2026-10-02-pdf-merger-design.md`).

- **Word and office documents**: add a `DocxConverter` in `pdf_merger/src/converters/` that runs LibreOffice headless (`soffice --headless --convert-to pdf`) in a subprocess, and register it in `registry.py`. Needs LibreOffice on the host (~350 MB). Run conversions with `asyncio.create_subprocess_exec` and a timeout.
- **Encrypted PDFs**: accept a password per file and open with `pikepdf.open(path, password=...)`.
- **Output options**: compression/optimization, page delete and duplicate in the web page strip, a split tool.
- **Ember upload proxy**: let users drop files in Ember chat and have ember_api forward them to `pdf_merger` `POST /api/files` with the internal token and `X-Requester-Username`, so they land in the user's MCP session.

**Revisit when**: the user asks for any of these.
