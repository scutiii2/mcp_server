# Video Downloader Wiring and Docs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Connect `video_downloader` to the rest of the workspace (mcp_server extension entry, server_launcher group), write its README and vault notes, and verify the whole stack end to end.

**Architecture:** No code in the new projects changes here. mcp_server reaches video_downloader as an HTTP extension (same as pdf_merger); server_launcher discovers it through `extra_roots.json`; docs follow the PDFMerger pattern.

**Tech Stack:** JSON config files, Markdown (Obsidian vault rules in `Brain/AGENTS.md`).

**Spec:** `docs/superpowers/specs/2026-10-06-video-downloader-design.md` (section "Integration"). Depends on plans 1 (backend) and 2 (web) being done.

## Global Constraints

- Never read or print real `.env` or `config_*.json` files; only `.example` twins. Changes to a real config file are made by the user (or with their explicit yes), never by reading it back.
- `INTERNAL_API_TOKEN` must be identical in `VideoDownloader/.env` and `MCPServer/apps/mcp_server/.env`. The user sets it; no agent prints or copies it.
- Edits outside `Brain/` need approval first (workspace rule): ask before step 3 of Task 1 and before Task 2. Do not touch `_ClaudeSkills/`.
- Vault notes: frontmatter `type`, `status`, `tags`, `created`; `[[wikilinks]]`; at least 2 links per project note; never invent facts, mark guesses with `(?)`; vault git repo is `Brain/.git`.
- Never run git commands at `D:\User\Documents\Programming` root. MCPServer, VideoDownloader and Brain are separate repos.
- Commit messages end with the session's `Co-Authored-By` trailer.

---

### Task 1: mcp_server extension entry

**Files:**
- Modify: `D:\User\Documents\Programming\Python\MCPServer\apps\mcp_server\configs\config_extensions.json.example`
- User step: the real `apps/mcp_server/configs/config_extensions.json` (gitignored) and the two `.env` files.

**Interfaces:**
- Consumes: video_downloader `/mcp` (plan 1, Task 9) and web port 5175 (plan 2).
- Produces: extension id `video_downloader`; its tools reach agents as `video_downloader__tool_video_probe`, `..._download`, `..._status`, `..._listFiles`.

- [ ] **Step 1: Add the example entry**

Add after the `pdf_merger` entry in `config_extensions.json.example` (keep valid JSON, add a comma after the previous entry):
```json
  "video_downloader": {
    "_comment": "video_downloader's MCP endpoint (Python/VideoDownloader/video_downloader). It requires the shared internal token, sent here as a header. Start video_downloader before mcp_server so the connection succeeds at startup. forward_requester gives each asking user their own file session. web_url is video_downloader_web, linked from ember's Extensions page: it must be an address the user's browser can reach (use this machine's LAN address, not 127.0.0.1, when others open ember from elsewhere). Downloads are started and polled, never awaited: the tools return a job_id and tool_video_status reports progress.",
    "label": "Video Downloader",
    "description": "Download a video or its audio from YouTube, TikTok and other sites; returns a download link. Start a job, then poll its status.",
    "url": "http://127.0.0.1:8050/mcp",
    "headers": { "X-Internal-Token": "${INTERNAL_API_TOKEN}" },
    "forward_requester": true,
    "web_url": "http://127.0.0.1:5175"
  }
```

- [ ] **Step 2: Run mcp_server tests**

Run (from `apps/mcp_server`): `.venv_mcp/Scripts/python -m pytest tests/test_extensions.py tests/test_app_config.py -q`
Expected: pass. If a test counts the example entries or checks the exact key list, update that test to include `video_downloader`.

- [ ] **Step 3: Ask the user, then enable it live**

Ask: "Add `video_downloader` to your real `config_extensions.json`, or use Ember's Extensions page (Add extension) with the same URL, header and web_url?" Do what they choose. For the file edit, add the same entry as Step 1 without reading other entries' secrets.

Tell the user to set the same `INTERNAL_API_TOKEN` in `VideoDownloader/.env` as in `apps/mcp_server/.env` themselves (do not read either file), and a random `VIDEO_DOWNLOADER_SIGNING_KEY` (`py -c "import secrets; print(secrets.token_hex(32))"`).

- [ ] **Step 4: Commit (MCPServer repo)**

```bash
cd D:\User\Documents\Programming\Python\MCPServer && git add apps/mcp_server/configs/config_extensions.json.example && git commit -m "feat(mcp_server): example extension entry for video_downloader"
```

---

### Task 2: server_launcher

**Files:**
- Modify: `apps/server_launcher/data/extra_roots.json`, `apps/server_launcher/data/groups.json`

**Interfaces:**
- Consumes: `video_downloader/run.bat` and `video_downloader_web/run.bat` headers `REM LABEL:` / `REM DESCRIPTION:` (plans 1 and 2).
- Produces: template keys `video_downloader` (port 8050) and `video_downloader_web` (port 5175); group "Video Downloader".

- [ ] **Step 1: Ask approval** (edits outside `Brain/`), then add the root

`extra_roots.json` becomes:
```json
[
  "../../PDFMerger",
  "../../VideoDownloader"
]
```

- [ ] **Step 2: Add the group**

Append to `groups.json` (after the `"PDF Merger"` group, add a comma first):
```json
  "Video Downloader": {
    "members": [
      {
        "template_key": "video_downloader",
        "port": 8050,
        "extra_env": {},
        "extra_args": "",
        "preset_name": null
      },
      {
        "template_key": "video_downloader_web",
        "port": 5175,
        "extra_env": {},
        "extra_args": "",
        "preset_name": null
      }
    ]
  }
```
Also add a `video_downloader` member (port 8050) to the "Ember" group, before `mcp_server`, mirroring `pdf_merger`.

- [ ] **Step 3: Run launcher tests**

Run (from `apps/server_launcher`): `.venv_launcher/Scripts/python -m pytest -q`
Expected: pass. If a test fixes the number of extra roots or groups, update it.

- [ ] **Step 4: Check discovery**

Run: `.venv_launcher/Scripts/python -c "from src.discovery import discover_templates; print(sorted(discover_templates()))"` (adjust to the module's real return type if it is a dict or list).
Expected: output contains `video_downloader` and `video_downloader_web`.

- [ ] **Step 5: Commit (MCPServer repo)**

```bash
cd D:\User\Documents\Programming\Python\MCPServer && git add apps/server_launcher/data && git commit -m "feat(server_launcher): discover VideoDownloader and add its group"
```

---

### Task 3: README, spec status, vault notes

**Files:**
- Create: `D:\User\Documents\Programming\Python\VideoDownloader\video_downloader\README.md`
- Modify: `VideoDownloader/README.md`, spec header (`Status: implemented`), `VideoDownloader/_TODO.md` if needed
- Create: `D:\User\Documents\Programming\Brain\Projects\VideoDownloader.md`, `video_downloader.md`, `video_downloader_web.md`
- Modify: `D:\User\Documents\Programming\Brain\Projects\MCPServer.md` (one link line), `D:\User\Documents\Programming\Python\MCPServer\_TODO.md` (video item)

- [ ] **Step 1: Write `video_downloader/README.md`**

```markdown
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
Only public http(s) sites (ports 80 and 443). Private, loopback and link-local addresses are refused, including redirect targets. Known gap: when yt-dlp hands a stream to FFmpeg to fetch directly, FFmpeg's own connections are not checked; native HLS is preferred to keep this rare.

## API
`POST /api/probe`, `POST /api/downloads`, `GET /api/jobs/{id}`, `GET /api/jobs/{id}/events` (SSE), `POST /api/jobs/{id}/cancel`, `GET /api/files`, `DELETE /api/files/{id}`, `GET /api/files/{id}/download?exp=&sig=`, `GET /api/health`. MCP at `/mcp`: `tool_video_probe`, `tool_video_download`, `tool_video_status`, `tool_video_listFiles`.

## Updating yt-dlp
Sites change often. Run `update.bat`, test, then update the pin in `pyproject.toml`.

## Tests
`.venv_video_downloader\Scripts\python -m pytest -q`

Download only content you have the right to download. DRM-protected and login-only videos are refused.
```

Replace the body of `VideoDownloader/README.md` with a short index plus a "Run order" list: video_downloader, then video_downloader_web, then (optionally) mcp_server.

- [ ] **Step 2: Update spec header**

Change the spec's `Status: draft, awaiting review.` to `Status: implemented (plans 1-3 in docs/superpowers/plans/).` and add a "Plan deviations" list (the five items at the top of plan 1) at the end of the spec.

- [ ] **Step 3: Write the vault notes**

`Brain/Projects/VideoDownloader.md`:
```markdown
---
type: project
status: active
tags: [project, python, typescript]
created: 2026-10-06
repo: Python/VideoDownloader
---

# VideoDownloader

Repo of two projects that download videos or audio from YouTube, TikTok and other sites. Built like [[PDFMerger]].

## Purpose
Download a video by hand in a web app, or let agents do it through MCP tools.

## Components
| Component | Role | Note |
|---|---|---|
| `video_downloader` | FastAPI service: yt-dlp wrapper, URL policy, TTL file store, jobs with SSE, REST API, MCP tools (port 8050) | [[video_downloader]] |
| `video_downloader_web` | Vue 3 + TypeScript web app (port 5175) | [[video_downloader_web]] |

## Architecture
```
browser --> video_downloader_web --/api--> video_downloader <--extension (HTTP, token)-- mcp_server (MCPServer repo)
```
- No imports from other projects. Links to the outside: the `video_downloader` entry in `mcp_server/configs/config_extensions.json` and `server_launcher/data/extra_roots.json` (`../../VideoDownloader`).
- Agent instructions live in `Python/VideoDownloader/AGENTS.md`; `CLAUDE.md` only imports it.

## Key decisions
| Date | Decision | Why |
|---|---|---|
| 2026-10-06 | Standalone service plus web app, not an mcp_server capability | Same shape as [[pdf_merger]]; self-contained repo rule |
| 2026-10-06 | Files in a TTL store with signed links | Works for LAN and remote users; nothing piles up |
| 2026-10-06 | Public sites only, hard caps, getaddrinfo guard | yt-dlp fetches any URL and agents can call the tool (SSRF) |
| 2026-10-06 | Copy the pdf_merger pattern, no shared library | Repo rule: no cross-project imports |

## How to run
`video_downloader/run.bat` (port 8050), then `video_downloader_web/run.bat` (port 5175). Needs FFmpeg on PATH. Start the service before mcp_server.

## Open questions
- Real Ember or LLM call to the download tools is untested (?).
- Deferred features in `Python/VideoDownloader/_TODO.md`.

## Related
- [[MCPServer]]
- [[PDFMerger]]
- [[video_downloader]]
- [[video_downloader_web]]
```

`Brain/Projects/video_downloader.md` (purpose, stack, architecture units, key decisions table, how to run, limits; `repo: Python/VideoDownloader/video_downloader`) and `Brain/Projects/video_downloader_web.md` (stack, one-page layout, stores, `repo: Python/VideoDownloader/video_downloader_web`) follow the same frontmatter. Each links `[[VideoDownloader]]`, `[[pdf_merger]]` or `[[ember_web]]`, and its sibling. Content comes from the README files and spec; do not paste code.

Add a line to `Brain/Projects/MCPServer.md` under its related/extensions section: `- [[VideoDownloader]]: HTTP extension, tools \`video_downloader__tool_video_*\``.

- [ ] **Step 4: Update the MCPServer `_TODO.md`**

Replace the "Video downloader app" section with a short note: built on 2026-10-06 as `Python/VideoDownloader`, see its README and `_TODO.md` for deferred features. (Ask first: outside `Brain/`.)

- [ ] **Step 5: Validate the vault**

Run (from `D:\User\Documents\Programming`): `py .claude/hooks/validate_vault.py --all`
Expected: no errors for the new notes.

- [ ] **Step 6: Commit** (three repos, separately)

```bash
cd D:\User\Documents\Programming\Python\VideoDownloader && git add -A && git commit -m "docs: video_downloader README and spec status"
cd D:\User\Documents\Programming\Brain && git add Projects && git commit -m "docs: VideoDownloader project notes"
cd D:\User\Documents\Programming\Python\MCPServer && git add _TODO.md && git commit -m "docs: video downloader built, point to its repo"
```

---

### Task 4: Final verification

**Files:** none (verification only).

- [ ] **Step 1: Test suites**

Run `.venv_video_downloader/Scripts/python -m pytest -q` in `video_downloader/` and `npm test && npm run build` in `video_downloader_web/`.
Expected: all green.

- [ ] **Step 2: Start the stack**

Start `video_downloader`, `video_downloader_web`, `mcp_server`, `ai_agent`, `ember_api`, `ember_web` (server_launcher "Ember" group). Check `http://127.0.0.1:8050/api/health` returns `ffmpeg: true`.

- [ ] **Step 3: Web flow**

In `http://127.0.0.1:5175`: paste a short public video link, Check, download 480p, then an audio-mp3, confirm both files play and the list shows expiry; cancel one download mid-way; try `http://127.0.0.1/x` (expect "not a public website") and a playlist-only URL (expect the single-video message).

- [ ] **Step 4: Ember flow**

In Ember's Extensions page confirm "Video Downloader" shows with an "Open app" link. In a chat with an agent that can use tools, ask it to download a short video: expect probe, download, polled status, then a download link. Report the exact outcome. If the agent's tool shortlist hides the new tools, note it (see memory "Laya tool shortlist").

- [ ] **Step 5: Report**

List what passed, what failed and any deviations. Do not claim success for steps not run.

---

## Self-Review

- **Spec coverage (Integration section):** mcp_server extension entry (Task 1), server_launcher (Task 2), README/vault/`_TODO` (Task 3), Ember persona deferred (stays in repo `_TODO.md`), extensions-proxy removal noted in vault note and spec. FFmpeg-gap and URL policy documented in the README.
- **Placeholder scan:** none. The two sub-notes in Task 3 Step 3 are described by required content and links because they are prose summarizing READMEs written in the same task.
- **Consistency:** ports 8050/5175, template keys `video_downloader` and `video_downloader_web`, tool names `tool_video_*` match plans 1 and 2.
