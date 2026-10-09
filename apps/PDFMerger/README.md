# PDFMerger

Merge PDFs and images (JPG, PNG, WebP, TIFF, GIF, HEIC) into one PDF.

| Folder | What | Port |
|---|---|---|
| `pdf_merger/` | FastAPI service: REST API for the web app, MCP tools for agents | 8040 |
| `pdf_merger_web/` | Vue 3 + TypeScript web app | 5174 |

Start `pdf_merger/run.bat`, then `pdf_merger_web/run.bat`, and open http://127.0.0.1:5174. Each folder's README has the details.

Agents use it through `mcp_server` in `Python/MCPServer`, which proxies pdf_merger's `/mcp` as an HTTP extension. Design: `docs/superpowers/specs/2026-10-02-pdf-merger-design.md`.
