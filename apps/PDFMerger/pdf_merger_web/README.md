# pdf_merger_web

Web app for `pdf_merger`: upload PDFs and images, pick page ranges, reorder pages with thumbnails, set output options, merge and download.

Design: `../docs/superpowers/specs/2026-10-02-pdf-merger-design.md`.

## Run

Start `pdf_merger` first (port 8040), then:

```
run.bat
```

Opens on http://127.0.0.1:5174 (`PDF_MERGER_WEB_PORT`). `/api` is proxied to `PDF_MERGER_API_URL` (default `http://127.0.0.1:<PDF_MERGER_PORT>`). Both come from the repo-root `PDFMerger/.env`, shared with `pdf_merger`; real environment variables win, so the session cookie stays same-origin.

## Using a file in chat

Each file row and the merge result have a "Copy ID" button. Paste the ID into an Ember chat and ask the agent to merge it; the agent uses the `tool_pdf_*` tools through `mcp_server`.

## Tests

```
npm test
npm run build
```
