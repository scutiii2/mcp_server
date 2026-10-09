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
