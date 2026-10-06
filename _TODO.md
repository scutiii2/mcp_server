# _TODO.md

Deferred items — not scheduled, revisit when the trigger condition below is met.

## Catalog item descriptions (added 2026-09-14)

Give each item found by the catalog its own description (catalog_service currently lacks per-item descriptions).

## One .env per project, and merge the small configs (deferred 2026-09-21, rewritten 2026-10-05)

**Context**: Secrets and settings are split into many tiny files. ai_agent already uses a single `apps/ai_agent/.env` (with `.env.example`); mcp_server and ember_api still use several `secret_*.env` files. Not approved for implementation yet.

**Secrets: one `.env` per project, like ai_agent**
- **mcp_server** (done 2026-10-05): `.secrets/secret_*.env` merged into `apps/mcp_server/.env` (+ `.env.example`); `MCP_HOST` / `MCP_PORT` stay there. `run.py` builds `.env` from an old `.secrets/` folder on first start (`src/utils/env_file.py`). Delete the legacy `.secrets/` real files once `.env` is confirmed.
- **ember_api** (code done 2026-10-05): `secrets/secret_bootstrap_admin.env`, `secret_internal_api.env` and `secret_smtp.env` merged into `apps/ember_api/.env`; `src/utils/env_file.py` builds `.env` from an old `secrets/` folder on first start, else from `.env.example` (the example file still has to be created by hand: Claude's write to `.env*` is denied). Delete the legacy `secrets/` real files once `.env` is confirmed, and update `apps/ember_api/secrets/README.md`.
- `INTERNAL_API_TOKEN` stays in each project's own `.env` and must match across ember_api, ai_agent and mcp_server. Do not share one file across projects (each project stays self-contained).

**Configs: stay in `configs/`; which ones can merge**
- **mcp_server** (decided 2026-10-05: no merge): `config_capabilities.json` (42 B) and `config_extensions.json` stay separate. Merging needs wrapper keys and rewrites of the loaders and savers in `app_config.py` plus four test files, and `config_extensions.json` is deleted by the extensions-proxy item below, leaving `config_capabilities.json` alone. Both savers are synchronous read-modify-write, so one process cannot interleave them (no shared writer needed). `config_email.json` (example only, gitignored by path unlike the other two) looks dead: `Settings.email_config_path` has no caller in `src/`, `load_email_config` is used only by tests, and nothing loads the `EmailConfig` that `services/email.py` takes. Check `watcher` / `email` before removing it.
- **ai_agent**: `config_limits.json` and `config_tool_selection.json` are both small runtime tuning (token limits, tool shortlist) and can merge into one file (name to decide, for example `config_tuning.json`).
- **Keep separate**: `apps/ai_agent/configs/config_gateways.json` (3 KB, provider endpoints), `prompts.json` (persona text), `config_servers.json` (the MCP server list, reworked by the extensions item below), and `apps/ai_agent/data/agent_registry.json` (runtime registry, lives in `data/`, not a config).
- **Nothing to merge**: ember_api already has the single `configs/config_app.json`; `apps/chat_cli/configs/` has one file. `apps/catalog_service/configs/` not checked.

**Work involved**:
- Update every loader, the `.example` twins, `.gitignore` entries and any `run.bat` first-run copy step to match ai_agent's `.env` handling.
- Update `apps/ember_api/src/services/config_validation.py` per-file checkers (mcp_server has no equivalent file), tests, READMEs (including `apps/ember_api/secrets/README.md`) and the scaffold skills. Edit the skills under `.agents/skills/` (`aiagent-scaffold`, `mcp-capability-scaffold`, `root-project-scaffold`, `ember-feature-scaffold`), then sync to `.claude/skills/`; the pre-commit check enforces the match.
- Add a one-time migration that reads the old files when the new one is missing, so existing real secrets (for example the bootstrap admin password) are not lost.
- Fix stale comments in `apps/ai_agent/.env.example` (it still mentions `secret_llm.env`, `secret.env` and chat_app).

**Trade-off**: one typo in a merged file can break several settings at once.

**Why not built now**: user asked to log it instead of implementing.

**Revisit when**: user wants this built. mcp_server and ember_api secrets are done; configs are what is left.

## Treat mcp_server as a normal MCP, drop the "extensions" proxy (deferred 2026-09-21, rewritten 2026-10-05)

**Note**: chat_app was removed; ember_api now owns the MCP side the old text called "chat_app".

**Context**: Today mcp_server is a hub. External MCPs are added as "extensions" (`apps/mcp_server/configs/config_extensions.json`, `apps/mcp_server/src/extension_routes.py`, `/extensions` endpoint) and their tools arrive proxied as `{ext_id}__{tool}`. The file currently holds one live entry, `pdf_merger`. ember_api reaches mcp_server through one URL (`mcp_server_url` in `apps/ember_api/configs/config_app.json`, used by `apps/ember_api/src/services/mcp_proxy.py`) and passes extensions through (`apps/ember_api/src/routes/server_info.py`, `apps/ember_api/src/services/mcp_server_info.py`: list, add, remove). Each chat turn carries `enabled_extensions` from ember_api (`routes/chats.py`, `services/turns.py`, `services/agent_gateway.py`) to ai_agent (`apps/ai_agent/src/server.py`, `agents/agent_config.py`). `ai_agent` already has a multi-server registry (`configs/config_servers.json`, `McpClientRegistry`, tools namespaced `<server>__<tool>`), but it holds only the `main` entry (mcp_server). Goal: mcp_server is just one MCP entry among several, with no proxying.

**Target design**: ember_api and ai_agent connect to N MCP servers side by side (mcp_server, pdf_merger, github MCP, others). mcp_server exposes only its own capabilities.

**Plan (two steps, keeps the app working throughout)**:
1. Give ember_api a multi-server registry (reuse or share the ai_agent registry idea) and an MCP list config replacing the single `mcp_server_url`. Keep mcp_server's `/extensions` working meanwhile. ember_web gets add/remove MCP writing that list; the per-chat "extension" toggles become per-MCP toggles, and `enabled_extensions` becomes a list of server ids.
2. Migrate existing extensions (`pdf_merger`) to MCP entries, then delete the proxy in mcp_server: `extension_routes.py`, `config_extensions.json` and its `.example`, `extensions_config_path` in `src/config.py`, the `extensions` service, and extension mentions in `command_routes.py` / `capability_routes.py`. Keep `/commands`.

**Decision needed**: how ember_api and ai_agent share the MCP list. Options: one shared file (simple, breaks "each project self-contained") or ember_api as source of truth pushing it to ai_agent over the existing ask call (cleaner).

**Trade-offs**: less code in mcp_server, one concept instead of two, other MCPs stay available when mcp_server is down. External MCPs would skip whatever mcp_server adds on top: `capability_meta` registration, `ai_explain_result`, help entries. Check what ember_api's capability and tool listing (`server_info.py`, `mcp_server_info.py`) needs from mcp_server before deciding.

**Size**: medium to large. Touches:
- ember_api: `mcp_proxy.py`, `server_info.py`, `mcp_server_info.py`, `chats.py`, `turns.py`, `agent_gateway.py`, `config.py`, `config_validation.py`, the `ADMIN_MANAGE` permission text in `permissions.py`.
- ember_web: `api/ExtensionsClient.ts`, `api/ChatsClient.ts`, `components/AddExtensionModal.vue`, `components/ChatSettingsMenu.vue`, `stores/chat.ts`, `services/slashCommands.ts`, router pages.
- chat_cli: `src/api.py` (sends `enabled_extensions`).
- ai_agent: `config_servers.json` plumbing and `enabled_extensions` handling.
- mcp_server: routes and config above.
- Docs and the scaffold skills that mention extensions.

Overlaps with the config-consolidation item above: `config_extensions.json` would be deleted rather than merged.

**Why not built now**: user asked to log it instead of implementing.

**Revisit when**: user wants this built. Start with step 1.

## Chat folders: reordering and folder names in search (added 2026-10-06)

**Context**: Chat folders, pins and drag and drop are merged to `main` (spec: `docs/superpowers/specs/2026-10-05-chat-folders-pins-design.md`). Two parts were left out on purpose; each needs its own design.

- **Folder reordering UI**: the API already supports it (`PATCH /api/chat-folders/{id}` with `position`, and `foldersClient.reorder` / the folders store `reorder` exist). Missing: a way to reorder in the sidebar (drag a folder header, or Move up / Move down in the folder "..." menu).
- **Folder names in search hits**: search results are a flat list and do not say which folder a chat is in. Show the folder name on each hit (needs `folder_id` in the search hit rows from ember_api, or a lookup in the store).

**Revisit when**: user wants these built.

## More Ember ideas (added 2026-10-06)

Ideas from the "what more can we add" discussion; none designed yet.

- **Attachments with the pdf-assistant**: attach files to a chat message and let the pdf-assistant read them.
- **Per-user quotas**: limit usage per account (builds on the existing usage gauges).
- **Notifications when a long answer finishes**: for example a browser notification or a title badge when the tab is in the background.
- **Mobile and PWA support**: installable app, touch layout, offline shell.

**Revisit when**: user picks one; start with brainstorming a design.

## server_manager capability page (added 2026-10-06)

**Context**: Capability pages are built (spec: `docs/superpowers/specs/2026-10-06-capability-pages-design.md`); only `generator` has a `gui/page.json`. `server_manager` (start, stop, restart, list Docker apps on the host; fetch an app's log) is the other built-in capability. Skipped for now.

- **Simple page, no code change**: a `gui/page.json` with an app list `table` (`tool_srv_listApps`) and one form each for start, stop and restart (typed container name; a dropdown needs an `options_url` on the tool's `name` parameter).
- **Proper control panel, needs the page format extended**: row actions on a table (a Start/Stop/Restart button per app), download cards (so the log download works on the page), and several tools in one section (a list that refreshes after an action).
- Note: these tools are not approval-gated; anyone with `tools.use` could stop any app on the host (see the capability README).

**Revisit when**: user wants it built.

## Video downloader app (added 2026-10-06)

**Idea**: A Python app that downloads videos from YouTube, TikTok and other sites. Build it on `yt-dlp` (handles site extraction, formats, playlists, subtitles, metadata) with FFmpeg to merge separate audio and video streams. Not designed yet. Decided 2026-10-06: build it the way pdf_merger is built, as a standalone backend service plus a separate web UI (see Structure below), not as an mcp_server capability.

**Minimal example**:

```python
import yt_dlp

url = input("Enter video URL: ")

options = {
    "format": "bestvideo+bestaudio/best",
    "merge_output_format": "mp4",
    "outtmpl": "%(title)s.%(ext)s",
}

with yt_dlp.YoutubeDL(options) as downloader:
    downloader.download([url])
```

Install: `pip install yt-dlp`, plus FFmpeg on the system.

**Possible features**:
- Sites: YouTube, TikTok, Facebook, Instagram, X/Twitter, Vimeo, Reddit, Twitch, and the rest `yt-dlp` supports.
- MP4/WebM video, MP3/M4A audio extraction.
- Resolution choice: 360p, 720p, 1080p, 1440p, 4K.
- Playlists, subtitles, thumbnails, metadata.
- Download progress and several downloads at once.
- Clipboard URL auto-detection.
- Download history.
- Desktop GUI (PySide6, PyQt or Tkinter); PySide6 + yt-dlp + FFmpeg suggested for Windows.

**Architecture sketch**: GUI (URL input, format and resolution selectors, output folder, progress bar) -> downloader engine (`yt-dlp`) -> media processing (FFmpeg), plus a download history store.

**Limits**: Some sites need login cookies. DRM-protected content cannot be downloaded this way. Download only content you have permission for or that the service and copyright rules allow.

**Structure (copy the pdf_merger pattern)**:
- Backend: FastAPI service with one facade (a `DownloadService` wrapping `yt-dlp`). REST routers for the web UI and MCP tools at `/mcp` (token required) both call the facade only. Reached by mcp_server as an HTTP extension (entry in `apps/mcp_server/configs/config_extensions.json`, `X-Internal-Token` header, `forward_requester`). Likely a persona in `apps/ai_agent/agents/` like pdf-assistant.
- Web UI: separate Vite + Vue 3 + TypeScript app (Pinia, Vitest), Vite proxies `/api` to the backend so the session cookie is same-origin. Same toolchain as `pdf_merger_web` and ember_web.
- Own folder, own git repo, `AGENTS.md`, `run.bat`, and a note in `Brain/Projects/`. Use the `root-project-scaffold` skill for the top-level shape.

**Open design points**:
- Downloads are long, so use a job queue with SSE progress (like pdf_merger `jobs/`); the MCP tool is start, poll status, get result, not one blocking call (client limit ~120 s).
- Files go through MCP as IDs and signed download links with a TTL store, never as base64.
- FFmpeg is a system dependency; check it at startup.
- Output folder, size limits, concurrent download limit, and cookies for login-only sites need settings.

**Revisit when**: user wants this built; start with brainstorming a design.
