# _TODO.md

Deferred items — not scheduled, revisit when the trigger condition below is met.

## Video downloader: deferred features (added 2026-10-06)

- Playlists (many files per job), subtitles, cookies for login-only sites, download history.
- Ember persona in `Python/MCPServer/apps/ai_agent/agents/` (like pdf-assistant).
- Clip trimming.

**Revisit when**: the user asks for any of these.

## Known gaps from the final review (added 2026-10-06)

- **Web polling after an SSE drop** (`video_downloader_web/src/api/client.ts`, `POLL_ATTEMPTS = 10`): successful polls count toward the 10 attempts, so a download longer than about 20 s whose stream dropped is reported as `connection_lost` while still running. Fix: count only failed polls, or poll until a terminal state.
- **Refused external downloaders report `blocked_host`**: streams that need ffmpeg or another external downloader to fetch (SAMPLE-AES HLS, non-native m3u8) fail with an address-check message. Fix: a dedicated error code and message.
- **Per-session limits do not bound total disk or the queue**: a request without a cookie gets a fresh session, so the 2 GB per-session quota does not bound total disk use, and one client can fill all 10 queue slots. Fix: a global store byte cap and a per-session limit on running and queued jobs.
- **Non-standard CDN ports**: the guard allows only ports 80 and 443 for every connection, so a media CDN on another port fails with `blocked_host`. Relax only if seen in practice.
