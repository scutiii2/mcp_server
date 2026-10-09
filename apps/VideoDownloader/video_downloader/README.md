# video_downloader

FastAPI service that downloads videos or audio from public sites with yt-dlp. REST API for `video_downloader_web`, MCP tools for `mcp_server`.

Design: `../docs/superpowers/specs/2026-10-06-video-downloader-design.md`.

## Requirements
- Python 3.11+ (runs on 3.14)
- FFmpeg on PATH (the service refuses to start without it)

## Setup
1. Copy `../.env.example` to `../.env` (the service also does this on first start) and set:
   - `INTERNAL_API_TOKEN`: same value as in `apps/mcp_server/.env` (`/mcp` is refused until it is set).
   - `VIDEO_DOWNLOADER_SIGNING_KEY`: a random secret (`py -c "import secrets; print(secrets.token_hex(32))"`), or download links stop working after a restart.
2. `run.bat` creates `.venv_video_downloader`, installs the project and starts the service on port 8050.
3. Start it before `mcp_server`, which reaches `/mcp` as an HTTP extension.

For LAN use set `VIDEO_DOWNLOADER_HOST=0.0.0.0` and `VIDEO_DOWNLOADER_PUBLIC_BASE_URL` to the address other machines use.

## Limits (configs/config_video_downloader.json)
500 MB per file, 2 hours per video, 2 downloads at once (8 waiting), 2 GB per session, files kept 6 hours, download links valid 1 hour. Playlist links download the single video only.

## URL policy
Only public http(s) sites (ports 80 and 443). Private, loopback and link-local addresses (including IPv4 hidden in NAT64 or IPv4-compatible IPv6) are refused, and so are redirect targets and DNS answers seen while downloading. yt-dlp's connections go direct (any `*_PROXY` environment variable is ignored), so the checks see the real targets.

Some sites (TikTok) need browser impersonation, which yt-dlp does with curl_cffi (installed through the `curl-cffi` extra). libcurl resolves names and follows redirects on its own, so `src/policy/curl_guard.py` checks each impersonated request individually: the host is resolved and checked with the same rule before anything is sent, libcurl is pinned to the checked IPs (`CURLOPT_RESOLVE`, so DNS rebinding can't swap the target), and libcurl never follows redirects: the service follows `Location` itself (at most 5 hops, http/https only), checking and pinning every hop.

Live streams (live, upcoming or still processing) are refused with `live_stream`: yt-dlp would fetch them with FFmpeg, whose own connections can't be checked, and they never finish. Any other stream yt-dlp would hand to FFmpeg or another external downloader (for example an HLS stream its native downloader can't handle) fails closed with `blocked_host`. FFmpeg still runs on local files to merge video and audio and to convert audio. Duration and live status are checked again on the download's own extraction, not just on the probe.

## API
`POST /api/probe`, `POST /api/downloads`, `GET /api/jobs/{id}`, `GET /api/jobs/{id}/events` (SSE), `POST /api/jobs/{id}/cancel`, `GET /api/files`, `DELETE /api/files/{id}`, `GET /api/files/{id}/download?exp=&sig=`, `GET /api/health`. MCP at `/mcp`: `tool_video_probe`, `tool_video_download`, `tool_video_status`, `tool_video_listFiles`.

## Updating yt-dlp
Sites change often. Run `update.bat`, test, then update the pin in `pyproject.toml`.

## Tests
`.venv_video_downloader\Scripts\python -m pytest -q`

Tests marked `live` reach real websites and are skipped by default; run them with `-m live`.

Download only content you have the right to download. DRM-protected and login-only videos are refused.
