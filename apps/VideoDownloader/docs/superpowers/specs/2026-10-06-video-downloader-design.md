# Video downloader: design

Date: 2026-10-06. Status: implemented (plans 1-3 in docs/superpowers/plans/).

## Goal

A standalone service that downloads videos (or audio only) from YouTube, TikTok and other sites supported by `yt-dlp`, plus a web UI. Built the way pdf_merger is built: a FastAPI service and a separate Vite + Vue web app, with MCP tools reached through mcp_server as an HTTP extension.

Not an mcp_server capability. Not part of ember_web.

## Decisions

| Decision | Choice | Why |
|---|---|---|
| Where files end up | Session-scoped TTL store, signed download links (like pdf_merger) | Works for LAN and remote users, nothing piles up on the host |
| v1 scope | Paste URL, metadata preview, video presets or audio-only, SSE progress, download link, MCP tools | Smallest useful slice. Preview is needed anyway to show formats and block huge files |
| URL policy | Public sites only, hard caps | An LLM agent can call the MCP tool; yt-dlp would fetch LAN addresses otherwise (SSRF) |
| Code reuse | Copy the pdf_merger pattern, own code | Repo rule: each project self-contained, no cross-project imports |
| Playlists | Off (`noplaylist=True`) | A playlist link downloads the single video only |

## Layout

`Python/VideoDownloader/` is its own git repo with `AGENTS.md`, `CLAUDE.md` (imports `@AGENTS.md`), `README.md`, `_TODO.md`, `docs/` and a repo-root `.env` plus `.env.example` for host, ports and URLs.

- `video_downloader/`: FastAPI service, port 8050 (`VIDEO_DOWNLOADER_PORT`). REST under `/api`, MCP at `/mcp`. Own venv, `run.bat`.
- `video_downloader_web/`: Vite + Vue 3 + TypeScript + Pinia + Vitest, port 5175. Vite proxies `/api` so the session cookie is same-origin.

Vault note: `Brain/Projects/VideoDownloader.md`, plus component notes `video_downloader.md` and `video_downloader_web.md`.

## Service units (`video_downloader/src/`)

- `service.py`: one facade, `DownloadService`. REST routers and MCP tools call only it.
- `policy/`: URL check and caps.
  - Scheme must be http or https.
  - Host is resolved; reject private, loopback and link-local addresses (IPv4 and IPv6), including when a hostname resolves to one.
  - Caps from config: 500 MB per file, 2 h duration, 2 concurrent downloads, 2 GB per session.
- `extractor/`: thin wrapper over `yt-dlp`.
  - `probe(url)`: title, duration, thumbnail, uploader, size estimate, format choices. Metadata only.
  - `download(url, preset, progress_cb)`: runs in a thread. Progress hook aborts when bytes exceed the cap and deletes partial files.
  - Maps yt-dlp exceptions to stable error codes.
- `store/`: session-scoped TTL file store with JSON sidecars and signed links. 6 h TTL, 2 GB per session, link TTL 1 h. Sweep on startup and periodically.
- `jobs/`: job queue, 2-slot semaphore, SSE progress events, cancel. A cancelled job keeps its slot until its thread really ends.
- `api/`, `mcp_tools/`: transport only.

FFmpeg is a system dependency. It is checked at startup; if missing the service refuses to start with a clear error (`ffmpeg_missing`).

Sessions and auth match pdf_merger: browsers get a session cookie; callers with `X-Internal-Token` act as `mcp:<username>`, may read any file by ID, and delete only their own. An unset token refuses all MCP calls.

## Flow and REST API

1. `POST /api/probe {url}`: policy check, then metadata. Returns `{title, duration, thumbnail, uploader, options[]}`. Presets: `best`, `1080p`, `720p`, `480p`, `audio-mp3`, `audio-m4a`. Presets the site lacks are omitted. A preset over the duration or size cap is marked `blocked` with a reason.
2. `POST /api/downloads {url, preset}`: re-checks policy and caps (never trusts probe), creates a job, returns `{job_id}`.
3. `GET /api/jobs/{id}/events` (SSE): `queued`, `progress {percent, speed, eta}`, `processing` (ffmpeg merge or extract), `done {file_id, name, size}`, `error {code, message}`.
4. `POST /api/jobs/{id}/cancel`.
5. `GET /api/files`, `GET /api/files/{id}/link`, `DELETE /api/files/{id}`, signed `GET /download?token=` (streams the file).
6. `GET /api/health`: includes the yt-dlp and ffmpeg versions.

Size is checked twice: estimate before the job starts, and bytes during the download.

## MCP tools (`/mcp`, token required)

- `tool_video_probe(url)`: metadata and presets.
- `tool_video_download(url, preset)`: starts a job, returns `job_id` immediately.
- `tool_video_status(job_id)`: state and progress; when done, `file_id`, name, size and signed link.
- `tool_video_listFiles()`.

No tool blocks on a download. The agent polls `status`, which stays under the ~120 s client limit.

## Error codes

`invalid_url`, `blocked_host`, `too_long`, `too_large`, `unsupported_site`, `login_required`, `drm_protected`, `live_stream`, `ffmpeg_missing`, `queue_full`, `cancelled`, `extractor_failed`. Raw yt-dlp text goes to logs only, not to clients.

## Web app (`video_downloader_web/`)

One page, three areas:

- **URL bar**: paste, Check. Shows thumbnail, title, duration, uploader and a preset picker (blocked presets greyed with the reason). Download button.
- **Active jobs**: card per job with progress bar, speed, ETA, Cancel. Driven by SSE.
- **My files**: name, size, time to expiry; Download (signed link) and Delete.

Pinia stores: `probe`, `jobs`, `files`. API clients in `src/api/`. One table maps error codes to friendly messages. Footer notes: download only content you have rights to.

## Config

- Repo-root `.env`: host, ports, `INTERNAL_API_TOKEN` (must match mcp_server), `VIDEO_DOWNLOADER_SIGNING_KEY`, `PUBLIC_BASE_URL`.
- `video_downloader/configs/config_video_downloader.json` plus `.example`: caps, TTLs, link TTL (the preset table lives in code).
- Runtime files in `.data/store/`, gitignored.

## Integration

- mcp_server: entry in `apps/mcp_server/configs/config_extensions.json` with the internal token header and `forward_requester: true`. Start the downloader before mcp_server.
- `server_launcher`: add `../VideoDownloader` to `data/extra_roots.json`.
- Ember persona in `ai_agent/agents/`: deferred.
- The extensions proxy is scheduled for removal in `MCPServer/_TODO.md` ("Treat mcp_server as a normal MCP"). That migration will need a direct MCP entry for this service too.

## Testing

pytest, pytest-asyncio, httpx. No network in tests.

- `policy`: URL cases, private and loopback addresses, hostnames resolving to private IPs (resolver mocked).
- `extractor`: yt-dlp mocked; error mapping; progress-hook cap abort.
- `store`: TTL, quotas, sidecars, signed link expiry and tampering.
- `jobs`: slot limit, cancel, SSE event order.
- `api` and `mcp_tools`: through the facade with a fake extractor.
- One opt-in live test (`-m live`) against a short public video, skipped by default.

Web: Vitest for stores, error mapping and preset picker logic. No e2e.

## Risks and open items

- **yt-dlp breaks when sites change.** Pin the version; ship `update.bat` (`pip install -U yt-dlp`); expose the version in `/api/health`.
- **Redirect SSRF.** yt-dlp follows redirects, and the policy checks only the first URL. The implementation plan must start with a spike: register a custom request handler in yt-dlp's networking layer that runs the policy on every outgoing request and redirect target. If that proves impossible, v1 ships with the gap documented in the README and the resolved `webpage_url` from probe re-checked before download.
- **Legal and ToS.** DRM and login-only content are refused with clear codes. README and UI footer state the rights notice.
- **Disk use.** Quotas, TTL sweep and startup sweep.
- **Python 3.14.** Check that yt-dlp and its dependencies install on the host Python at scaffold time.

## Deferred (to `_TODO.md` in the new repo)

Playlists, subtitles, cookies for login-only sites, download history, Ember persona, clip trimming.

## Plan deviations

Plan deviations: (1) the preset table lives in code (`src/extractor/presets.py`), not config; (2) no separate `GET /api/files/{id}/link`, every file carries a fresh signed `download_url`; (3) the signed download route is `GET /api/files/{id}/download?exp=&sig=`; (4) extra error code `timeout` for jobs exceeding `job_timeout_minutes`; (5) redirect SSRF is handled by a `getaddrinfo` guard, not only by the first-URL check.
