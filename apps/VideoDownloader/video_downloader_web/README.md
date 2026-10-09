# video_downloader_web

Web app for `video_downloader`: paste a video link, preview it, pick a quality (or audio only), watch progress and download the file.

Design: `../docs/superpowers/specs/2026-10-06-video-downloader-design.md`.

## Run

Start `video_downloader` first (port 8050), then:

```
run.bat
```

Opens on http://127.0.0.1:5175 (`VIDEO_DOWNLOADER_WEB_PORT`). `/api` is proxied to `VIDEO_DOWNLOADER_API_URL` (default `http://127.0.0.1:<VIDEO_DOWNLOADER_PORT>`). Both come from the repo-root `VideoDownloader/.env`, shared with `video_downloader`; real environment variables win, so the session cookie stays same-origin.

The dev server listens on 127.0.0.1 only. For access from other machines on your LAN, run `run.bat --host 0.0.0.0` (the flag passes through to Vite) and open `http://<this-pc's-ip>:5175`.

Download only content you have the right to download. DRM-protected and login-only videos are refused.

## Tests

```
npm test
npm run build
```
