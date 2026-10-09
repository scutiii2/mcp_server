# VideoDownloader

Download videos or audio from YouTube, TikTok and other sites supported by yt-dlp.

- `video_downloader/` — backend service (port 8050), see its README
- `video_downloader_web/` — web app (port 5175), see its README

Requirements: Python 3.11+, FFmpeg on PATH. Setup and run steps are in each folder's README.

## Run order
1. `video_downloader/run.bat`
2. `video_downloader_web/run.bat`
3. Optionally `mcp_server` (MCPServer repo), so agents get the `video_downloader__tool_video_*` tools. Start `video_downloader` before it.

Design: `docs/superpowers/specs/2026-10-06-video-downloader-design.md`. Deferred features: `_TODO.md`.
