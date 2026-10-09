# PDFMerger

Project note: `Brain/Projects/PDFMerger.md` in the Obsidian vault (`../../Brain/` from this folder; component notes beside it: `pdf_merger.md`, `pdf_merger_web.md`).

## Agent instructions
This file is the one instruction file for every coding agent. Codex reads it directly; `CLAUDE.md` only imports it (`@AGENTS.md`) for Claude Code. Edit this file, never `CLAUDE.md`.

## Layout
- `pdf_merger/` — FastAPI service (port 8040): merge engine, REST API under `/api`, MCP tools at `/mcp`.
- `pdf_merger_web/` — Vite + Vue 3 + TypeScript web app (port 5174) for pdf_merger.
- `docs/superpowers/` — design spec and implementation plans. They were written while the code lived in `Python/MCPServer/`, so paths in them say `MCPServer`.

## Rules
- Each folder is its own project with its own README, venv or node_modules. No imports from `Python/MCPServer` projects.
- `mcp_server` (in `Python/MCPServer`) reaches pdf_merger as an HTTP extension: `mcp_server/configs/config_extensions.json` entry `pdf_merger` with the internal token header and `forward_requester: true`. Start pdf_merger before mcp_server.
- `server_launcher` (in `Python/MCPServer`) finds these projects through its `data/extra_roots.json` (`../PDFMerger`).
- Host, ports and URLs live once in the repo-root `.env` (`.env.example` is the twin); both projects read it. `pdf_merger/configs/config_pdf_merger.json` holds tuning only.
- Never read or print real files `.env`, `.secrets/` or `config_*.json`; only `.example` twins.
