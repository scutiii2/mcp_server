# Video Downloader Web App Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `video_downloader_web`, a one-page Vue 3 + TypeScript app for `video_downloader`: paste a link, preview it, pick a quality, watch progress, download or delete files.

**Architecture:** Typed API client over `/api` (Vite proxy, same-origin cookie), three Pinia stores (`probe`, `jobs`, `files`), small presentational components. Job progress comes from SSE (`EventSource`). Mirrors PDFMerger's `pdf_merger_web` toolchain and conventions.

**Tech Stack:** Vue 3, TypeScript, Pinia, Vite, Vitest + jsdom + @vue/test-utils.

**Spec:** `docs/superpowers/specs/2026-10-06-video-downloader-design.md` (section "Web app"). Backend contract: `docs/superpowers/plans/2026-10-06-video-downloader-1-backend.md` (Tasks 7-8).

## Global Constraints

- Folder: `D:\User\Documents\Programming\Python\VideoDownloader\video_downloader_web\`. Run npm commands from there.
- Port 5175 (`VIDEO_DOWNLOADER_WEB_PORT`), `strictPort`, host `127.0.0.1`. `/api` proxied to `VIDEO_DOWNLOADER_API_URL` or `http://127.0.0.1:<VIDEO_DOWNLOADER_PORT>` (default 8050). Env comes from the repo-root `.env` via `loadEnv(mode, '..', 'VIDEO_DOWNLOADER_')`.
- All API paths relative (`/api/...`), `fetch` default credentials (same-origin cookie `vd_session`).
- Unit tests sit beside their source as `*.test.ts`; `npm test` = `vitest run`; `npm run build` = `vue-tsc -b && vite build` must pass.
- TypeScript strict via `@vue/tsconfig`; no `any`. Erasable syntax only (no enums, no constructor parameter properties).
- UI footer text: "Download only content you have the right to download."
- No end-to-end tests; the user tests manually.
- Commit messages end with the session's `Co-Authored-By` trailer.

## File Structure

```
video_downloader_web/
  package.json  index.html  vite.config.ts  tsconfig*.json  run.bat  README.md
  src/
    main.ts  style.css  App.vue
    api/{types.ts, client.ts, client.test.ts}
    lib/{format.ts, format.test.ts, messages.ts, messages.test.ts}
    stores/{probe.ts, probe.test.ts, jobs.ts, jobs.test.ts, files.ts, files.test.ts}
    components/{UrlBar.vue, ProbeCard.vue, ProbeCard.test.ts, JobCard.vue, JobCard.test.ts, FileRow.vue, FileRow.test.ts}
```

---

### Task 1: Scaffold, format helpers, error messages

**Files:**
- Create: `package.json`, `index.html`, `vite.config.ts`, `tsconfig.json`, `tsconfig.app.json`, `tsconfig.node.json`, `run.bat`, `README.md`
- Create: `src/main.ts`, `src/style.css`, `src/App.vue` (minimal shell, replaced in Task 4)
- Create: `src/lib/format.ts`, `src/lib/messages.ts`
- Test: `src/lib/format.test.ts`, `src/lib/messages.test.ts`

**Interfaces:**
- Produces:
  - `formatBytes(bytes: number): string`, `formatDuration(seconds: number | null): string`, `formatSpeed(bytesPerSecond: number | null): string`, `formatEta(seconds: number | null): string`, `formatExpiry(expiresAt: number, now: number): string` (both unix seconds), `plural(count, word)`.
  - `messageOf(error: unknown): string`; `friendlyError(code: string, message: string): string`.

- [ ] **Step 1: Write config files**

`package.json`:
```json
{
  "name": "video_downloader_web",
  "private": true,
  "version": "0.0.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "vue-tsc -b && vite build",
    "preview": "vite preview",
    "test": "vitest run"
  },
  "dependencies": {
    "pinia": "^4.0.3",
    "vue": "^3.5.42"
  },
  "devDependencies": {
    "@types/node": "^24.13.3",
    "@vitejs/plugin-vue": "^6.0.8",
    "@vue/test-utils": "^2.5.1",
    "@vue/tsconfig": "^0.9.1",
    "jsdom": "^29.1.1",
    "typescript": "~6.0.2",
    "vite": "^8.3.0",
    "vitest": "^5.0.2",
    "vue-tsc": "^3.3.11"
  }
}
```

`tsconfig.json`:
```json
{
  "files": [],
  "references": [{ "path": "./tsconfig.app.json" }, { "path": "./tsconfig.node.json" }]
}
```

`tsconfig.app.json`:
```json
{
  "extends": "@vue/tsconfig/tsconfig.dom.json",
  "compilerOptions": {
    "tsBuildInfoFile": "./node_modules/.tmp/tsconfig.app.tsbuildinfo",
    "types": ["vite/client"],
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "erasableSyntaxOnly": true,
    "noFallthroughCasesInSwitch": true
  },
  "include": ["src/**/*.ts", "src/**/*.vue"]
}
```

`tsconfig.node.json`:
```json
{
  "compilerOptions": {
    "tsBuildInfoFile": "./node_modules/.tmp/tsconfig.node.tsbuildinfo",
    "target": "es2023",
    "lib": ["ES2023"],
    "types": ["node"],
    "skipLibCheck": true,
    "module": "nodenext",
    "allowImportingTsExtensions": true,
    "verbatimModuleSyntax": true,
    "moduleDetection": "force",
    "noEmit": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "erasableSyntaxOnly": true,
    "noFallthroughCasesInSwitch": true
  },
  "include": ["vite.config.ts"]
}
```

`vite.config.ts`:
```ts
import vue from '@vitejs/plugin-vue'
import { loadEnv } from 'vite'
import { defineConfig } from 'vitest/config'

// Host, ports and URLs come from the repo-root .env (shared with video_downloader);
// real environment variables win over it.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '..', 'VIDEO_DOWNLOADER_')
  // Everything under /api goes to video_downloader, so the browser sees one origin:
  // the vd_session cookie works and no CORS is involved. SSE streams through.
  const apiProxy = {
    '/api': { target: env.VIDEO_DOWNLOADER_API_URL || `http://127.0.0.1:${env.VIDEO_DOWNLOADER_PORT || 8050}` },
  }
  return {
    plugins: [vue()],
    // `npm test`: unit tests sit beside their source as *.test.ts.
    test: {
      environment: 'jsdom',
      include: ['src/**/*.test.ts'],
      restoreMocks: true,
      unstubGlobals: true,
    },
    server: {
      // strictPort: fail instead of moving to another port, so server_launcher's port is the real one.
      port: Number(env.VIDEO_DOWNLOADER_WEB_PORT || 5175),
      strictPort: true,
      // Explicit IPv4: on Windows "localhost" can bind only [::1].
      host: '127.0.0.1',
      proxy: apiProxy,
    },
    preview: { proxy: apiProxy },
  }
})
```

`index.html`:
```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <meta name="robots" content="noindex, nofollow" />
    <title>Video downloader</title>
  </head>
  <body>
    <div id="app"></div>
    <script type="module" src="/src/main.ts"></script>
  </body>
</html>
```

`run.bat`:
```bat
@echo off
REM video_downloader_web dev launcher. Installs node_modules on first run, then starts
REM the Vite dev server. Extra args pass straight through to vite (e.g. --open).
REM
REM LABEL: Video Downloader Web
REM DESCRIPTION: Vue 3 + TypeScript web app for video_downloader: paste a link, pick a quality, download.
cd /d "%~dp0"

if not exist "node_modules" (
    echo Installing video_downloader_web dependencies ...
    call npm install
)

:run
call npm run dev -- %*

echo.
echo ----------------------------------------
echo  video_downloader_web stopped.
choice /C RQ /N /M "Press [R] to restart, [Q] to quit: "
if errorlevel 2 goto :end
if errorlevel 1 goto :run

:end
```

`README.md`:
```markdown
# video_downloader_web

Web app for `video_downloader`: paste a video link, preview it, pick a quality (or audio only), watch progress and download the file.

Design: `../docs/superpowers/specs/2026-10-06-video-downloader-design.md`.

## Run

Start `video_downloader` first (port 8050), then:

```
run.bat
```

Opens on http://127.0.0.1:5175 (`VIDEO_DOWNLOADER_WEB_PORT`). `/api` is proxied to `VIDEO_DOWNLOADER_API_URL` (default `http://127.0.0.1:<VIDEO_DOWNLOADER_PORT>`). Both come from the repo-root `VideoDownloader/.env`, shared with `video_downloader`; real environment variables win, so the session cookie stays same-origin.

Download only content you have the right to download. DRM-protected and login-only videos are refused.

## Tests

```
npm test
npm run build
```
```

`src/main.ts`:
```ts
import { createPinia } from 'pinia'
import { createApp } from 'vue'
import App from './App.vue'
import './style.css'

createApp(App).use(createPinia()).mount('#app')
```

`src/App.vue` (shell; Task 4 replaces it):
```vue
<template>
  <main class="app"><h1>Video downloader</h1></main>
</template>
```

`src/style.css`:
```css
:root {
  color-scheme: light dark;
  --bg: light-dark(#f6f5f1, #1c1c1a);
  --surface: light-dark(#ffffff, #262624);
  --text: light-dark(#1f1e1d, #ecebe7);
  --muted: light-dark(#6b6a65, #a3a29c);
  --border: light-dark(#e2e0d8, #3a3936);
  --accent: light-dark(#2f6fd1, #6ea2ef);
  --on-accent: #ffffff;
  --danger: light-dark(#b42323, #f08585);
  --ok: light-dark(#1f7a3d, #6fcf8e);
  --radius: 8px;
  font-family: system-ui, -apple-system, 'Segoe UI', sans-serif;
  background: var(--bg);
  color: var(--text);
}

body { margin: 0; }
h1 { font-size: 20px; font-weight: 600; margin: 0; }
h2 { font-size: 14px; font-weight: 600; margin: 0 0 8px; }
.muted { color: var(--muted); }
.small { font-size: 12px; }
.error { color: var(--danger); }

.app { max-width: 820px; margin: 0 auto; padding: 24px 16px 64px; display: grid; gap: 16px; }
.app-head { display: flex; justify-content: space-between; align-items: baseline; }
.panel { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 12px; }
.footer { text-align: center; }

button { font: inherit; color: inherit; background: transparent; border: 1px solid var(--border); border-radius: var(--radius); padding: 6px 10px; cursor: pointer; text-decoration: none; }
button:hover:not(:disabled) { border-color: var(--muted); }
button:disabled { opacity: 0.5; cursor: not-allowed; }
button.primary, a.primary { background: var(--accent); color: var(--on-accent); border: 1px solid var(--accent); padding: 8px 18px; border-radius: var(--radius); text-decoration: none; display: inline-block; }
input, select { font: inherit; color: inherit; background: var(--bg); border: 1px solid var(--border); border-radius: var(--radius); padding: 6px 8px; }

.url-bar { display: flex; gap: 8px; }
.url-bar input { flex: 1; min-width: 0; }

.probe { display: grid; grid-template-columns: 160px 1fr; gap: 12px; }
.probe img { width: 160px; border-radius: var(--radius); background: var(--border); aspect-ratio: 16 / 9; object-fit: cover; }
.probe .title { font-weight: 600; overflow-wrap: anywhere; }
.presets { list-style: none; margin: 8px 0; padding: 0; display: flex; flex-wrap: wrap; gap: 8px; }
.preset { display: block; border: 1px solid var(--border); border-radius: var(--radius); padding: 6px 10px; cursor: pointer; }
.preset.selected { border-color: var(--accent); outline: 1px solid var(--accent); }
.preset.blocked { opacity: 0.5; cursor: not-allowed; }
.preset input { margin-right: 6px; }

.list { list-style: none; margin: 0; padding: 0; display: grid; gap: 8px; }
.row { display: flex; align-items: center; gap: 10px; padding: 6px 0; }
.row + .row { border-top: 1px solid var(--border); }
.row .grow { flex: 1; min-width: 0; }
.row .name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.kind { font-size: 11px; font-weight: 600; padding: 2px 6px; border-radius: 4px; border: 1px solid var(--accent); color: var(--accent); }
.kind.audio { border-color: var(--ok); color: var(--ok); }
progress { width: 100%; height: 8px; accent-color: var(--accent); }

@media (max-width: 560px) {
  .probe { grid-template-columns: 1fr; }
  .probe img { width: 100%; }
}
```

- [ ] **Step 2: Write failing helper tests**

`src/lib/format.test.ts`:
```ts
import { describe, expect, it } from 'vitest'
import { formatBytes, formatDuration, formatEta, formatExpiry, formatSpeed, plural } from './format'

describe('format', () => {
  it('formats bytes', () => {
    expect(formatBytes(512)).toBe('512 B')
    expect(formatBytes(2048)).toBe('2 KB')
    expect(formatBytes(5 * 1024 * 1024)).toBe('5.0 MB')
    expect(formatBytes(3 * 1024 ** 3)).toBe('3.00 GB')
  })

  it('formats durations', () => {
    expect(formatDuration(null)).toBe('')
    expect(formatDuration(65)).toBe('1:05')
    expect(formatDuration(3725)).toBe('1:02:05')
  })

  it('formats speed and eta', () => {
    expect(formatSpeed(null)).toBe('')
    expect(formatSpeed(1_500_000)).toBe('1.4 MB/s')
    expect(formatEta(null)).toBe('')
    expect(formatEta(12)).toBe('12 s')
    expect(formatEta(75)).toBe('1 min 15 s')
    expect(formatEta(3700)).toBe('1 h 2 min')
  })

  it('formats time left until expiry', () => {
    expect(formatExpiry(1000, 1000)).toBe('expired')
    expect(formatExpiry(1000 + 90, 1000)).toBe('1 min')
    expect(formatExpiry(1000 + 5 * 3600 + 12 * 60, 1000)).toBe('5 h 12 min')
  })

  it('pluralizes', () => {
    expect(plural(1, 'file')).toBe('1 file')
    expect(plural(2, 'file')).toBe('2 files')
  })
})
```

`src/lib/messages.test.ts`:
```ts
import { describe, expect, it } from 'vitest'
import { friendlyError, messageOf } from './messages'

describe('messages', () => {
  it('messageOf reads Error messages and stringifies the rest', () => {
    expect(messageOf(new Error('boom'))).toBe('boom')
    expect(messageOf('plain')).toBe('plain')
  })

  it('friendlyError prefers the table, else the server message', () => {
    expect(friendlyError('cancelled', 'x')).toBe('The download was cancelled.')
    expect(friendlyError('connection_lost', 'x')).toContain('connection')
    expect(friendlyError('something_new', 'Server says hi.')).toBe('Server says hi.')
  })
})
```

- [ ] **Step 3: Install and run tests to verify failure**

Run:
```bash
npm install && npx vitest run
```
Expected: install succeeds; tests FAIL (`Failed to resolve import './format'`).

- [ ] **Step 4: Implement**

`src/lib/format.ts`:
```ts
const KB = 1024
const MB = KB * 1024
const GB = MB * 1024

export function formatBytes(bytes: number): string {
  if (bytes < KB) return `${bytes} B`
  if (bytes < MB) return `${Math.round(bytes / KB)} KB`
  if (bytes < GB) return `${(bytes / MB).toFixed(1)} MB`
  return `${(bytes / GB).toFixed(2)} GB`
}

export function plural(count: number, word: string): string {
  return `${count} ${word}${count === 1 ? '' : 's'}`
}

/** m:ss, or h:mm:ss from one hour up. Empty when unknown. */
export function formatDuration(seconds: number | null): string {
  if (seconds === null) return ''
  const total = Math.round(seconds)
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  const s = total % 60
  const pad = (n: number): string => String(n).padStart(2, '0')
  return h > 0 ? `${h}:${pad(m)}:${pad(s)}` : `${m}:${pad(s)}`
}

export function formatSpeed(bytesPerSecond: number | null): string {
  return bytesPerSecond === null ? '' : `${(bytesPerSecond / MB).toFixed(1)} MB/s`
}

export function formatEta(seconds: number | null): string {
  if (seconds === null) return ''
  const total = Math.round(seconds)
  if (total < 60) return `${total} s`
  if (total < 3600) return `${Math.floor(total / 60)} min ${total % 60} s`
  return `${Math.floor(total / 3600)} h ${Math.floor((total % 3600) / 60)} min`
}

/** Time left until a unix-seconds expiry, e.g. "5 h 12 min". Both arguments are unix seconds. */
export function formatExpiry(expiresAt: number, now: number): string {
  const left = Math.floor(expiresAt - now)
  if (left <= 0) return 'expired'
  const hours = Math.floor(left / 3600)
  const minutes = Math.max(1, Math.floor((left % 3600) / 60))
  return hours > 0 ? `${hours} h ${Math.floor((left % 3600) / 60)} min` : `${minutes} min`
}
```

`src/lib/messages.ts`:
```ts
/** The user-facing text of anything thrown. ApiError messages come from the server. */
export function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}

// Codes whose wording is better decided here than by the server (client-side codes and a few overrides).
const FRIENDLY: Record<string, string> = {
  cancelled: 'The download was cancelled.',
  connection_lost: 'Lost the connection to the server. Check your downloads list, then try again.',
  http_error: 'The server could not be reached. Try again.',
  drm_protected: 'This video is copy-protected (DRM), so it cannot be downloaded.',
  login_required: 'This video needs a login (private, members-only or age-restricted), so it cannot be downloaded here.',
}

/** One table of error text: known codes get fixed wording, anything else shows the server's message. */
export function friendlyError(code: string, message: string): string {
  return FRIENDLY[code] ?? message
}
```

- [ ] **Step 5: Run tests and build**

Run: `npm test && npm run build`
Expected: tests pass; build succeeds (shell `App.vue`).

- [ ] **Step 6: Commit** (the repo root `.gitignore` already excludes `node_modules/` and `dist/`)

```bash
cd .. && git add -A && git commit -m "feat(web): scaffold video_downloader_web with format and message helpers"
```

---

### Task 2: API types and client

**Files:**
- Create: `src/api/types.ts`, `src/api/client.ts`
- Test: `src/api/client.test.ts`

**Interfaces:**
- Produces (types): `ApiError` class (`code`, `message`, `status`), `FileInfo`, `PresetOption`, `ProbeResult`, `JobEvent`, `JobState`.
- Produces (client): `probe(url: string): Promise<ProbeResult>`, `startDownload(url: string, preset: string): Promise<{ job_id: string }>`, `cancelJob(jobId: string): Promise<void>`, `listFiles(): Promise<FileInfo[]>`, `deleteFile(fileId: string): Promise<void>`, `watchJob(jobId: string, onEvent: (event: JobEvent) => void): () => void`.

- [ ] **Step 1: Write failing tests**

`src/api/client.test.ts`:
```ts
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cancelJob, deleteFile, listFiles, probe, startDownload, watchJob } from './client'
import { ApiError, type JobEvent } from './types'

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

describe('client', () => {
  const fetchMock = vi.fn()
  beforeEach(() => vi.stubGlobal('fetch', fetchMock))
  afterEach(() => fetchMock.mockReset())

  it('probe posts the url and returns the result', async () => {
    fetchMock.mockResolvedValue(json({ url: 'https://x/v', title: 'T', duration: 5, thumbnail: null, uploader: null, options: [] }))
    const result = await probe('https://x/v')
    expect(result.title).toBe('T')
    const [path, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(path).toBe('/api/probe')
    expect(init.method).toBe('POST')
    expect(JSON.parse(init.body as string)).toEqual({ url: 'https://x/v' })
  })

  it('startDownload posts url and preset', async () => {
    fetchMock.mockResolvedValue(json({ job_id: 'j_1' }, 202))
    expect(await startDownload('https://x/v', '720p')).toEqual({ job_id: 'j_1' })
    const init = fetchMock.mock.calls[0][1] as RequestInit
    expect(JSON.parse(init.body as string)).toEqual({ url: 'https://x/v', preset: '720p' })
  })

  it('maps error bodies to ApiError', async () => {
    fetchMock.mockResolvedValue(json({ error: { code: 'blocked_host', message: 'Nope.' } }, 403))
    await expect(probe('http://127.0.0.1')).rejects.toMatchObject({ code: 'blocked_host', message: 'Nope.', status: 403 })
    await expect(probe('http://127.0.0.1')).rejects.toBeInstanceOf(ApiError)
  })

  it('falls back to a generic error for non-JSON failures', async () => {
    fetchMock.mockResolvedValue(new Response('<html>', { status: 502 }))
    await expect(listFiles()).rejects.toMatchObject({ code: 'http_error', status: 502 })
  })

  it('listFiles turns absolute download links into relative paths', async () => {
    const file = { file_id: 'f_1', name: 'a.mp4', kind: 'video', mime: 'video/mp4', size: 1, duration: null, expires_at: 9, download_url: 'http://127.0.0.1:8050/api/files/f_1/download?exp=1&sig=s' }
    fetchMock.mockResolvedValue(json([file]))
    const [got] = await listFiles()
    expect(got.download_url).toBe('/api/files/f_1/download?exp=1&sig=s')
  })

  it('cancelJob and deleteFile resolve on success', async () => {
    fetchMock.mockResolvedValueOnce(json({ job_id: 'j_1' }, 202)).mockResolvedValueOnce(new Response(null, { status: 204 }))
    await expect(cancelJob('j_1')).resolves.toBeUndefined()
    await expect(deleteFile('f_1')).resolves.toBeUndefined()
    expect(fetchMock.mock.calls[0][0]).toBe('/api/jobs/j_1/cancel')
    expect(fetchMock.mock.calls[1][0]).toBe('/api/files/f_1')
    expect((fetchMock.mock.calls[1][1] as RequestInit).method).toBe('DELETE')
  })
})

class FakeEventSource {
  static last: FakeEventSource
  onmessage: ((m: MessageEvent<string>) => void) | null = null
  onerror: (() => void) | null = null
  closed = false
  constructor(public url: string) {
    FakeEventSource.last = this
  }
  close(): void {
    this.closed = true
  }
  emit(event: JobEvent): void {
    this.onmessage?.({ data: JSON.stringify(event) } as MessageEvent<string>)
  }
}

describe('watchJob', () => {
  beforeEach(() => vi.stubGlobal('EventSource', FakeEventSource))

  it('delivers events and closes after done', () => {
    const seen: JobEvent[] = []
    watchJob('j_1', (e) => seen.push(e))
    const source = FakeEventSource.last
    expect(source.url).toBe('/api/jobs/j_1/events')
    source.emit({ type: 'queued' })
    expect(source.closed).toBe(false)
    source.emit({ type: 'error', code: 'cancelled', message: 'x' })
    expect(source.closed).toBe(true)
    expect(seen.map((e) => e.type)).toEqual(['queued', 'error'])
  })

  it('makes the done event link relative', () => {
    const seen: JobEvent[] = []
    watchJob('j_1', (e) => seen.push(e))
    const file = { file_id: 'f_1', name: 'a.mp4', kind: 'video' as const, mime: 'video/mp4', size: 1, duration: null, expires_at: 9, download_url: 'http://10.0.0.5:8050/api/files/f_1/download?exp=1&sig=s' }
    FakeEventSource.last.emit({ type: 'done', file_id: 'f_1', file })
    expect(seen[0]).toMatchObject({ type: 'done', file: { download_url: '/api/files/f_1/download?exp=1&sig=s' } })
  })

  it('reports connection_lost once when the stream drops early', () => {
    const seen: JobEvent[] = []
    watchJob('j_1', (e) => seen.push(e))
    FakeEventSource.last.onerror?.()
    FakeEventSource.last.onerror?.()
    expect(seen).toEqual([{ type: 'error', code: 'connection_lost', message: expect.any(String) }])
  })

  it('returns a stop function', () => {
    const stop = watchJob('j_1', () => {})
    stop()
    expect(FakeEventSource.last.closed).toBe(true)
  })
})
```

- [ ] **Step 2: Run to verify failure**

Run: `npx vitest run src/api/client.test.ts`
Expected: FAIL, cannot resolve `./client`.

- [ ] **Step 3: Implement**

`src/api/types.ts`:
```ts
// Mirrors video_downloader/src/models.py and the job events in src/service.py. Keep both in step.

export type FileKind = 'video' | 'audio'
export type JobState = 'queued' | 'downloading' | 'processing' | 'done' | 'error'

export interface FileInfo {
  file_id: string
  name: string
  kind: FileKind
  mime: string
  size: number
  duration: number | null
  expires_at: number
  download_url: string
}

export interface PresetOption {
  id: string
  label: string
  kind: FileKind
  estimated_bytes: number | null
  blocked: boolean
  code: string | null
  reason: string | null
}

export interface ProbeResult {
  url: string
  title: string
  duration: number | null
  thumbnail: string | null
  uploader: string | null
  options: PresetOption[]
}

export type JobEvent =
  | { type: 'queued' }
  | { type: 'progress'; percent: number | null; speed: number | null; eta: number | null }
  | { type: 'processing' }
  | { type: 'done'; file_id: string; file: FileInfo }
  | { type: 'error'; code: string; message: string }

export class ApiError extends Error {
  code: string
  status: number

  constructor(code: string, message: string, status: number) {
    super(message)
    this.code = code
    this.status = status
  }
}
```

`src/api/client.ts`:
```ts
// Thin typed wrapper over video_downloader's REST API. Every path is relative
// (/api/...) so requests go through the Vite proxy with the session cookie.
import { ApiError, type FileInfo, type JobEvent, type ProbeResult } from './types'

const BASE = '/api'

async function parse<T>(response: Response): Promise<T> {
  if (response.ok) {
    return (response.status === 204 ? undefined : await response.json()) as T
  }
  let code = 'http_error'
  let message = `The server answered ${response.status}. Try again.`
  try {
    const body = (await response.json()) as { error?: { code?: string; message?: string } }
    code = body.error?.code ?? code
    message = body.error?.message ?? message
  } catch {
    // Body was not JSON; keep the generic message.
  }
  throw new ApiError(code, message, response.status)
}

function postJson<T>(path: string, body: unknown): Promise<T> {
  return fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }).then((r) => parse<T>(r))
}

export function probe(url: string): Promise<ProbeResult> {
  return postJson<ProbeResult>('/probe', { url })
}

export function startDownload(url: string, preset: string): Promise<{ job_id: string }> {
  return postJson<{ job_id: string }>('/downloads', { url, preset })
}

export async function cancelJob(jobId: string): Promise<void> {
  await fetch(`${BASE}/jobs/${encodeURIComponent(jobId)}/cancel`, { method: 'POST' }).then((r) => parse<unknown>(r))
}

/** The server builds absolute links from its public base URL; a relative path always works through the Vite proxy (LAN, other hosts). */
function relative(file: FileInfo): FileInfo {
  try {
    const url = new URL(file.download_url)
    return { ...file, download_url: url.pathname + url.search }
  } catch {
    return file
  }
}

export function listFiles(): Promise<FileInfo[]> {
  return fetch(`${BASE}/files`)
    .then((r) => parse<FileInfo[]>(r))
    .then((files) => files.map(relative))
}

export function deleteFile(fileId: string): Promise<void> {
  return fetch(`${BASE}/files/${encodeURIComponent(fileId)}`, { method: 'DELETE' }).then((r) => parse<void>(r))
}

/** Follow a download job over SSE. Returns a function that stops listening. */
export function watchJob(jobId: string, onEvent: (event: JobEvent) => void): () => void {
  const source = new EventSource(`${BASE}/jobs/${encodeURIComponent(jobId)}/events`)
  let finished = false
  const finish = (): void => {
    finished = true
    source.close()
  }
  source.onmessage = (message: MessageEvent<string>) => {
    let event = JSON.parse(message.data) as JobEvent
    if (event.type === 'done') event = { ...event, file: relative(event.file) }
    onEvent(event)
    if (event.type === 'done' || event.type === 'error') finish()
  }
  source.onerror = () => {
    if (finished) return
    finish()
    onEvent({ type: 'error', code: 'connection_lost', message: 'Lost the connection to the server. Check your downloads list, then try again.' })
  }
  return finish
}
```

- [ ] **Step 4: Run tests and build**

Run: `npm test && npm run build`
Expected: pass.

- [ ] **Step 5: Commit**

```bash
cd .. && git add -A && git commit -m "feat(web): typed API client with SSE job watcher"
```

---

### Task 3: Stores (probe, jobs, files)

**Files:**
- Create: `src/stores/probe.ts`, `src/stores/jobs.ts`, `src/stores/files.ts`
- Test: `src/stores/probe.test.ts`, `src/stores/jobs.test.ts`, `src/stores/files.test.ts`

**Interfaces:**
- Consumes: Task 2 client and types, Task 1 `messageOf`/`friendlyError`.
- Produces:
  - `useProbeStore()`: `url: Ref<string>`, `result: Ref<ProbeResult | null>`, `selected: Ref<string | null>`, `loading: Ref<boolean>`, `error: Ref<string | null>`, `canCheck: ComputedRef<boolean>`, `selectedOption: ComputedRef<PresetOption | null>`, `check(): Promise<void>`, `select(id: string): void`, `reset(): void`.
  - `useFilesStore()`: `files: Ref<FileInfo[]>`, `loading`, `error`, `refresh(): Promise<void>`, `remove(fileId): Promise<void>`.
  - `useJobsStore()`: `jobs: Ref<JobView[]>`, `startError: Ref<string | null>`, `start(url: string, title: string, option: PresetOption): Promise<void>`, `cancel(id)`, `dismiss(id)`; `JobView = { id, title, presetLabel, state: JobState, percent: number | null, speed: number | null, eta: number | null, file: FileInfo | null, error: { code: string; message: string } | null }`.

- [ ] **Step 1: Write failing tests**

`src/stores/probe.test.ts`:
```ts
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '../api/client'
import { ApiError, type ProbeResult } from '../api/types'
import { useProbeStore } from './probe'

vi.mock('../api/client')

const RESULT: ProbeResult = {
  url: 'https://x/v',
  title: 'T',
  duration: 60,
  thumbnail: null,
  uploader: 'U',
  options: [
    { id: 'best', label: 'Best quality', kind: 'video', estimated_bytes: null, blocked: true, code: 'too_large', reason: 'Too big' },
    { id: '720p', label: '720p', kind: 'video', estimated_bytes: 1000, blocked: false, code: null, reason: null },
    { id: 'audio-mp3', label: 'Audio (MP3)', kind: 'audio', estimated_bytes: 500, blocked: false, code: null, reason: null },
  ],
}

describe('probe store', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('cannot check an empty url', () => {
    const store = useProbeStore()
    expect(store.canCheck).toBe(false)
    store.url = '  https://x/v '
    expect(store.canCheck).toBe(true)
  })

  it('check stores the result and selects the first unblocked preset', async () => {
    vi.mocked(api.probe).mockResolvedValue(RESULT)
    const store = useProbeStore()
    store.url = 'https://x/v'
    await store.check()
    expect(api.probe).toHaveBeenCalledWith('https://x/v')
    expect(store.result?.title).toBe('T')
    expect(store.selected).toBe('720p')
    expect(store.selectedOption?.label).toBe('720p')
    expect(store.loading).toBe(false)
  })

  it('select ignores blocked or unknown presets', async () => {
    vi.mocked(api.probe).mockResolvedValue(RESULT)
    const store = useProbeStore()
    store.url = 'https://x/v'
    await store.check()
    store.select('best')
    expect(store.selected).toBe('720p')
    store.select('audio-mp3')
    expect(store.selected).toBe('audio-mp3')
  })

  it('check failure sets a friendly error and clears the result', async () => {
    vi.mocked(api.probe).mockRejectedValue(new ApiError('drm_protected', 'raw', 422))
    const store = useProbeStore()
    store.url = 'https://x/v'
    await store.check()
    expect(store.result).toBeNull()
    expect(store.error).toContain('copy-protected')
    expect(store.loading).toBe(false)
  })

  it('reset clears everything', async () => {
    vi.mocked(api.probe).mockResolvedValue(RESULT)
    const store = useProbeStore()
    store.url = 'https://x/v'
    await store.check()
    store.reset()
    expect(store.url).toBe('')
    expect(store.result).toBeNull()
    expect(store.selected).toBeNull()
  })
})
```

`src/stores/files.test.ts`:
```ts
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '../api/client'
import { ApiError, type FileInfo } from '../api/types'
import { useFilesStore } from './files'

vi.mock('../api/client')

const FILE: FileInfo = { file_id: 'f_1', name: 'a.mp4', kind: 'video', mime: 'video/mp4', size: 10, duration: 5, expires_at: 99, download_url: '/d' }

describe('files store', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('refresh loads the list', async () => {
    vi.mocked(api.listFiles).mockResolvedValue([FILE])
    const store = useFilesStore()
    await store.refresh()
    expect(store.files).toEqual([FILE])
    expect(store.error).toBeNull()
  })

  it('refresh failure keeps the old list and sets an error', async () => {
    vi.mocked(api.listFiles).mockResolvedValueOnce([FILE]).mockRejectedValueOnce(new ApiError('http_error', 'down', 502))
    const store = useFilesStore()
    await store.refresh()
    await store.refresh()
    expect(store.files).toEqual([FILE])
    expect(store.error).toBeTruthy()
  })

  it('remove deletes on the server then drops the row', async () => {
    vi.mocked(api.listFiles).mockResolvedValue([FILE])
    vi.mocked(api.deleteFile).mockResolvedValue()
    const store = useFilesStore()
    await store.refresh()
    await store.remove('f_1')
    expect(api.deleteFile).toHaveBeenCalledWith('f_1')
    expect(store.files).toEqual([])
  })
})
```

`src/stores/jobs.test.ts`:
```ts
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '../api/client'
import { ApiError, type FileInfo, type JobEvent, type PresetOption } from '../api/types'
import { useFilesStore } from './files'
import { useJobsStore } from './jobs'

vi.mock('../api/client')

const OPTION: PresetOption = { id: '720p', label: '720p', kind: 'video', estimated_bytes: null, blocked: false, code: null, reason: null }
const FILE: FileInfo = { file_id: 'f_1', name: 'a.mp4', kind: 'video', mime: 'video/mp4', size: 10, duration: 5, expires_at: 99, download_url: '/d' }

let emit: (event: JobEvent) => void = () => {}
const stop = vi.fn()

describe('jobs store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.mocked(api.startDownload).mockResolvedValue({ job_id: 'j_1' })
    vi.mocked(api.listFiles).mockResolvedValue([FILE])
    vi.mocked(api.watchJob).mockImplementation((_id, onEvent) => {
      emit = onEvent
      return stop
    })
  })

  it('start adds a queued job and follows it', async () => {
    const store = useJobsStore()
    await store.start('https://x/v', 'Cat', OPTION)
    expect(api.startDownload).toHaveBeenCalledWith('https://x/v', '720p')
    expect(store.jobs).toHaveLength(1)
    expect(store.jobs[0]).toMatchObject({ id: 'j_1', title: 'Cat', presetLabel: '720p', state: 'queued', percent: null })
  })

  it('progress is monotonic and moves to processing then done, refreshing files', async () => {
    const store = useJobsStore()
    await store.start('https://x/v', 'Cat', OPTION)
    emit({ type: 'progress', percent: 40, speed: 1000, eta: 5 })
    emit({ type: 'progress', percent: 10, speed: 900, eta: 9 }) // second stream restarts at 10: never go back
    expect(store.jobs[0]).toMatchObject({ state: 'downloading', percent: 40, speed: 900, eta: 9 })
    emit({ type: 'processing' })
    expect(store.jobs[0].state).toBe('processing')
    emit({ type: 'done', file_id: 'f_1', file: FILE })
    expect(store.jobs[0]).toMatchObject({ state: 'done', percent: 100, file: FILE })
    await vi.waitFor(() => expect(useFilesStore().files).toEqual([FILE]))
  })

  it('error events keep code and message', async () => {
    const store = useJobsStore()
    await store.start('https://x/v', 'Cat', OPTION)
    emit({ type: 'error', code: 'too_large', message: 'Too big.' })
    expect(store.jobs[0]).toMatchObject({ state: 'error', error: { code: 'too_large', message: 'Too big.' } })
  })

  it('start failure sets startError and adds no job', async () => {
    vi.mocked(api.startDownload).mockRejectedValue(new ApiError('queue_full', 'Busy.', 429))
    const store = useJobsStore()
    await store.start('https://x/v', 'Cat', OPTION)
    expect(store.jobs).toEqual([])
    expect(store.startError).toBe('Busy.')
  })

  it('cancel asks the server; dismiss stops watching and removes the card', async () => {
    vi.mocked(api.cancelJob).mockResolvedValue()
    const store = useJobsStore()
    await store.start('https://x/v', 'Cat', OPTION)
    await store.cancel('j_1')
    expect(api.cancelJob).toHaveBeenCalledWith('j_1')
    store.dismiss('j_1')
    expect(stop).toHaveBeenCalled()
    expect(store.jobs).toEqual([])
  })
})
```

- [ ] **Step 2: Run to verify failure**

Run: `npx vitest run src/stores`
Expected: FAIL, cannot resolve `./probe`, `./jobs`, `./files`.

- [ ] **Step 3: Implement**

`src/stores/probe.ts`:
```ts
// The link the user pasted and what the server found out about it.
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import * as api from '../api/client'
import { ApiError, type PresetOption, type ProbeResult } from '../api/types'
import { friendlyError, messageOf } from '../lib/messages'

export const useProbeStore = defineStore('probe', () => {
  const url = ref('')
  const result = ref<ProbeResult | null>(null)
  const selected = ref<string | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)

  const canCheck = computed(() => url.value.trim() !== '' && !loading.value)
  const selectedOption = computed<PresetOption | null>(
    () => result.value?.options.find((o) => o.id === selected.value) ?? null,
  )

  async function check(): Promise<void> {
    if (!canCheck.value) return
    loading.value = true
    error.value = null
    result.value = null
    selected.value = null
    try {
      result.value = await api.probe(url.value.trim())
      selected.value = result.value.options.find((o) => !o.blocked)?.id ?? null
    } catch (e) {
      error.value = e instanceof ApiError ? friendlyError(e.code, e.message) : messageOf(e)
    } finally {
      loading.value = false
    }
  }

  /** Blocked or unknown presets cannot be selected. */
  function select(id: string): void {
    const option = result.value?.options.find((o) => o.id === id)
    if (option && !option.blocked) selected.value = id
  }

  function reset(): void {
    url.value = ''
    result.value = null
    selected.value = null
    error.value = null
  }

  return { url, result, selected, loading, error, canCheck, selectedOption, check, select, reset }
})
```

`src/stores/files.ts`:
```ts
// The files this browser session has downloaded (kept by the server until they expire).
import { defineStore } from 'pinia'
import { ref } from 'vue'
import * as api from '../api/client'
import type { FileInfo } from '../api/types'
import { messageOf } from '../lib/messages'

export const useFilesStore = defineStore('files', () => {
  const files = ref<FileInfo[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)

  async function refresh(): Promise<void> {
    loading.value = true
    try {
      files.value = await api.listFiles()
      error.value = null
    } catch (e) {
      error.value = messageOf(e)
    } finally {
      loading.value = false
    }
  }

  async function remove(fileId: string): Promise<void> {
    try {
      await api.deleteFile(fileId)
      files.value = files.value.filter((f) => f.file_id !== fileId)
      error.value = null
    } catch (e) {
      error.value = messageOf(e)
    }
  }

  return { files, loading, error, refresh, remove }
})
```

`src/stores/jobs.ts`:
```ts
// Downloads in progress or just finished, each followed over SSE.
import { defineStore } from 'pinia'
import { ref } from 'vue'
import * as api from '../api/client'
import { ApiError, type FileInfo, type JobEvent, type JobState, type PresetOption } from '../api/types'
import { friendlyError, messageOf } from '../lib/messages'
import { useFilesStore } from './files'

export interface JobView {
  id: string
  title: string
  presetLabel: string
  state: JobState
  /** Never goes backwards: video and audio download as two streams that each count 0-100. */
  percent: number | null
  speed: number | null
  eta: number | null
  file: FileInfo | null
  error: { code: string; message: string } | null
}

export const useJobsStore = defineStore('jobs', () => {
  const jobs = ref<JobView[]>([])
  const startError = ref<string | null>(null)
  const stops = new Map<string, () => void>()

  function apply(job: JobView, event: JobEvent): void {
    switch (event.type) {
      case 'queued':
        job.state = 'queued'
        break
      case 'progress':
        job.state = 'downloading'
        if (event.percent !== null) job.percent = Math.max(job.percent ?? 0, event.percent)
        job.speed = event.speed
        job.eta = event.eta
        break
      case 'processing':
        job.state = 'processing'
        job.speed = null
        job.eta = null
        break
      case 'done':
        job.state = 'done'
        job.percent = 100
        job.file = event.file
        void useFilesStore().refresh()
        break
      case 'error':
        job.state = 'error'
        job.error = { code: event.code, message: friendlyError(event.code, event.message) }
        break
    }
  }

  async function start(url: string, title: string, option: PresetOption): Promise<void> {
    startError.value = null
    try {
      const { job_id } = await api.startDownload(url, option.id)
      const job: JobView = {
        id: job_id,
        title,
        presetLabel: option.label,
        state: 'queued',
        percent: null,
        speed: null,
        eta: null,
        file: null,
        error: null,
      }
      jobs.value.unshift(job)
      // Mutate through the reactive proxy that lives in the array.
      stops.set(job_id, api.watchJob(job_id, (event) => apply(jobs.value.find((j) => j.id === job_id) ?? job, event)))
    } catch (e) {
      startError.value = e instanceof ApiError ? friendlyError(e.code, e.message) : messageOf(e)
    }
  }

  async function cancel(id: string): Promise<void> {
    try {
      await api.cancelJob(id)
    } catch (e) {
      startError.value = messageOf(e)
    }
  }

  function dismiss(id: string): void {
    stops.get(id)?.()
    stops.delete(id)
    jobs.value = jobs.value.filter((j) => j.id !== id)
  }

  return { jobs, startError, start, cancel, dismiss }
})
```

- [ ] **Step 4: Run tests and build**

Run: `npm test && npm run build`
Expected: pass.

- [ ] **Step 5: Commit**

```bash
cd .. && git add -A && git commit -m "feat(web): probe, jobs and files stores"
```

---

### Task 4: Components and App

**Files:**
- Create: `src/components/UrlBar.vue`, `src/components/ProbeCard.vue`, `src/components/JobCard.vue`, `src/components/FileRow.vue`
- Modify: `src/App.vue`
- Test: `src/components/ProbeCard.test.ts`, `src/components/JobCard.test.ts`, `src/components/FileRow.test.ts`

**Interfaces:**
- Consumes: stores from Task 3, helpers from Task 1.
- Produces: components `UrlBar` (props: `modelValue: string`, `loading: boolean`, `canCheck: boolean`; emits `update:modelValue`, `check`), `ProbeCard` (props: `result: ProbeResult`, `selected: string | null`; emits `select(id)`, `download`), `JobCard` (props: `job: JobView`; emits `cancel`, `dismiss`), `FileRow` (props: `file: FileInfo`, `now: number`; emits `remove`).

- [ ] **Step 1: Write failing tests**

`src/components/ProbeCard.test.ts`:
```ts
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import type { ProbeResult } from '../api/types'
import ProbeCard from './ProbeCard.vue'

const RESULT: ProbeResult = {
  url: 'https://x/v',
  title: 'Cat video',
  duration: 125,
  thumbnail: 'https://img/t.jpg',
  uploader: 'Cats',
  options: [
    { id: 'best', label: 'Best quality', kind: 'video', estimated_bytes: 50_000_000, blocked: true, code: 'too_large', reason: 'Too big for the limit.' },
    { id: '720p', label: '720p', kind: 'video', estimated_bytes: 11_000_000, blocked: false, code: null, reason: null },
  ],
}

describe('ProbeCard', () => {
  it('shows title, uploader, duration and thumbnail', () => {
    const wrapper = mount(ProbeCard, { props: { result: RESULT, selected: '720p' } })
    expect(wrapper.text()).toContain('Cat video')
    expect(wrapper.text()).toContain('Cats')
    expect(wrapper.text()).toContain('2:05')
    expect(wrapper.get('img').attributes('src')).toBe('https://img/t.jpg')
  })

  it('disables blocked presets and shows the reason', () => {
    const wrapper = mount(ProbeCard, { props: { result: RESULT, selected: '720p' } })
    const radios = wrapper.findAll('input[type="radio"]')
    expect((radios[0].element as HTMLInputElement).disabled).toBe(true)
    expect((radios[1].element as HTMLInputElement).disabled).toBe(false)
    expect(wrapper.text()).toContain('Too big for the limit.')
  })

  it('emits select and download', async () => {
    const wrapper = mount(ProbeCard, { props: { result: RESULT, selected: null } })
    expect(wrapper.get('button.primary').attributes('disabled')).toBeDefined()
    await wrapper.setProps({ selected: '720p' })
    await wrapper.findAll('input[type="radio"]')[1].setValue(true)
    expect(wrapper.emitted('select')?.[0]).toEqual(['720p'])
    await wrapper.get('button.primary').trigger('click')
    expect(wrapper.emitted('download')).toHaveLength(1)
  })
})
```

`src/components/JobCard.test.ts`:
```ts
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import type { JobView } from '../stores/jobs'
import JobCard from './JobCard.vue'

function job(partial: Partial<JobView>): JobView {
  return { id: 'j_1', title: 'Cat', presetLabel: '720p', state: 'downloading', percent: 40, speed: 1_500_000, eta: 12, file: null, error: null, ...partial }
}

describe('JobCard', () => {
  it('shows progress, speed and eta while downloading, with Cancel', async () => {
    const wrapper = mount(JobCard, { props: { job: job({}) } })
    expect(wrapper.text()).toContain('Cat')
    expect(wrapper.text()).toContain('40%')
    expect(wrapper.text()).toContain('1.4 MB/s')
    expect(wrapper.text()).toContain('12 s')
    expect((wrapper.get('progress').element as HTMLProgressElement).value).toBe(40)
    await wrapper.get('button.cancel').trigger('click')
    expect(wrapper.emitted('cancel')).toHaveLength(1)
  })

  it('shows a processing state without cancel', () => {
    const wrapper = mount(JobCard, { props: { job: job({ state: 'processing' }) } })
    expect(wrapper.text()).toContain('Processing')
  })

  it('offers the file when done and Dismiss', async () => {
    const file = { file_id: 'f_1', name: 'Cat.mp4', kind: 'video' as const, mime: 'video/mp4', size: 1, duration: 5, expires_at: 9, download_url: '/api/files/f_1/download?exp=1&sig=s' }
    const wrapper = mount(JobCard, { props: { job: job({ state: 'done', percent: 100, file }) } })
    expect(wrapper.get('a.primary').attributes('href')).toBe(file.download_url)
    await wrapper.get('button.dismiss').trigger('click')
    expect(wrapper.emitted('dismiss')).toHaveLength(1)
  })

  it('shows the error message', () => {
    const wrapper = mount(JobCard, { props: { job: job({ state: 'error', error: { code: 'too_large', message: 'Too big.' } }) } })
    expect(wrapper.get('.error').text()).toBe('Too big.')
  })
})
```

`src/components/FileRow.test.ts`:
```ts
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import type { FileInfo } from '../api/types'
import FileRow from './FileRow.vue'

const FILE: FileInfo = {
  file_id: 'f_1',
  name: 'Cat.mp4',
  kind: 'video',
  mime: 'video/mp4',
  size: 5 * 1024 * 1024,
  duration: 65,
  expires_at: 1000 + 5 * 3600,
  download_url: '/api/files/f_1/download?exp=1&sig=s',
}

describe('FileRow', () => {
  it('shows name, size, duration and time left', () => {
    const wrapper = mount(FileRow, { props: { file: FILE, now: 1000 } })
    expect(wrapper.text()).toContain('Cat.mp4')
    expect(wrapper.text()).toContain('5.0 MB')
    expect(wrapper.text()).toContain('1:05')
    expect(wrapper.text()).toContain('5 h 0 min')
  })

  it('links to the signed download and emits remove', async () => {
    const wrapper = mount(FileRow, { props: { file: FILE, now: 1000 } })
    expect(wrapper.get('a').attributes('href')).toBe(FILE.download_url)
    await wrapper.get('button.remove').trigger('click')
    expect(wrapper.emitted('remove')).toHaveLength(1)
  })
})
```

- [ ] **Step 2: Run to verify failure**

Run: `npx vitest run src/components`
Expected: FAIL, cannot resolve the `.vue` files.

- [ ] **Step 3: Implement components**

`src/components/UrlBar.vue`:
```vue
<script setup lang="ts">
defineProps<{ modelValue: string; loading: boolean; canCheck: boolean }>()
defineEmits<{ 'update:modelValue': [value: string]; check: [] }>()
</script>

<template>
  <form class="url-bar" @submit.prevent="$emit('check')">
    <input
      type="url"
      :value="modelValue"
      placeholder="Paste a video link (YouTube, TikTok, ...)"
      aria-label="Video link"
      autofocus
      @input="$emit('update:modelValue', ($event.target as HTMLInputElement).value)"
    />
    <button class="primary" type="submit" :disabled="!canCheck">{{ loading ? 'Checking...' : 'Check' }}</button>
  </form>
</template>
```

`src/components/ProbeCard.vue`:
```vue
<script setup lang="ts">
import type { ProbeResult } from '../api/types'
import { formatBytes, formatDuration } from '../lib/format'

defineProps<{ result: ProbeResult; selected: string | null }>()
defineEmits<{ select: [id: string]; download: [] }>()
</script>

<template>
  <section class="panel probe">
    <img v-if="result.thumbnail" :src="result.thumbnail" alt="" />
    <div v-else class="muted small">No preview</div>
    <div>
      <div class="title">{{ result.title }}</div>
      <div class="muted small">
        <span v-if="result.uploader">{{ result.uploader }}</span>
        <span v-if="result.uploader && result.duration !== null"> &middot; </span>
        <span v-if="result.duration !== null">{{ formatDuration(result.duration) }}</span>
      </div>
      <ul class="presets">
        <li v-for="option in result.options" :key="option.id">
          <label class="preset" :class="{ selected: option.id === selected, blocked: option.blocked }">
            <input
              type="radio"
              name="preset"
              :value="option.id"
              :checked="option.id === selected"
              :disabled="option.blocked"
              @change="$emit('select', option.id)"
            />
            {{ option.label }}
            <span v-if="option.estimated_bytes !== null" class="muted small">~{{ formatBytes(option.estimated_bytes) }}</span>
            <span v-if="option.blocked && option.reason" class="error small">{{ option.reason }}</span>
          </label>
        </li>
      </ul>
      <button class="primary" type="button" :disabled="selected === null" @click="$emit('download')">Download</button>
    </div>
  </section>
</template>
```

`src/components/JobCard.vue`:
```vue
<script setup lang="ts">
import { computed } from 'vue'
import { formatEta, formatSpeed } from '../lib/format'
import type { JobView } from '../stores/jobs'

const props = defineProps<{ job: JobView }>()
defineEmits<{ cancel: []; dismiss: [] }>()

const running = computed(() => ['queued', 'downloading', 'processing'].includes(props.job.state))
const stateText = computed(() => {
  switch (props.job.state) {
    case 'queued':
      return 'Waiting in line...'
    case 'processing':
      return 'Processing (merging and converting)...'
    case 'downloading':
      return `${Math.round(props.job.percent ?? 0)}%`
    case 'done':
      return 'Done'
    default:
      return ''
  }
})
</script>

<template>
  <li class="panel">
    <div class="row">
      <div class="grow">
        <div class="name">{{ job.title }} <span class="muted small">{{ job.presetLabel }}</span></div>
        <div v-if="job.state !== 'error'" class="muted small">
          {{ stateText }}
          <template v-if="job.state === 'downloading'">
            <span v-if="job.speed !== null"> &middot; {{ formatSpeed(job.speed) }}</span>
            <span v-if="job.eta !== null"> &middot; {{ formatEta(job.eta) }} left</span>
          </template>
        </div>
        <div v-else class="error small">{{ job.error?.message }}</div>
      </div>
      <button v-if="running && job.state !== 'processing'" class="cancel" type="button" @click="$emit('cancel')">Cancel</button>
      <a v-if="job.state === 'done' && job.file" class="primary" :href="job.file.download_url" download>Download file</a>
      <button v-if="!running" class="dismiss" type="button" @click="$emit('dismiss')">Dismiss</button>
    </div>
    <progress v-if="running" max="100" :value="job.state === 'processing' ? 100 : (job.percent ?? 0)"></progress>
  </li>
</template>
```

`src/components/FileRow.vue`:
```vue
<script setup lang="ts">
import type { FileInfo } from '../api/types'
import { formatBytes, formatDuration, formatExpiry } from '../lib/format'

defineProps<{ file: FileInfo; now: number }>()
defineEmits<{ remove: [] }>()
</script>

<template>
  <li class="row">
    <span class="kind" :class="file.kind">{{ file.kind }}</span>
    <div class="grow">
      <div class="name" :title="file.name">{{ file.name }}</div>
      <div class="muted small">
        {{ formatBytes(file.size) }}
        <span v-if="file.duration !== null"> &middot; {{ formatDuration(file.duration) }}</span>
        &middot; expires in {{ formatExpiry(file.expires_at, now) }}
      </div>
    </div>
    <a :href="file.download_url" download>Download</a>
    <button class="remove" type="button" @click="$emit('remove')">Delete</button>
  </li>
</template>
```

`src/App.vue`:
```vue
<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import FileRow from './components/FileRow.vue'
import JobCard from './components/JobCard.vue'
import ProbeCard from './components/ProbeCard.vue'
import UrlBar from './components/UrlBar.vue'
import { plural } from './lib/format'
import { useFilesStore } from './stores/files'
import { useJobsStore } from './stores/jobs'
import { useProbeStore } from './stores/probe'

const probe = useProbeStore()
const jobs = useJobsStore()
const files = useFilesStore()

const now = ref(Date.now() / 1000)
let timer: ReturnType<typeof setInterval> | undefined

onMounted(() => {
  void files.refresh()
  timer = setInterval(() => (now.value = Date.now() / 1000), 30_000)
})
onBeforeUnmount(() => clearInterval(timer))

async function download(): Promise<void> {
  const result = probe.result
  const option = probe.selectedOption
  if (!result || !option) return
  await jobs.start(result.url, result.title, option)
  if (!jobs.startError) probe.reset()
}
</script>

<template>
  <main class="app">
    <header class="app-head">
      <h1>Video downloader</h1>
      <span class="muted small">{{ plural(files.files.length, 'file') }} kept for a few hours</span>
    </header>

    <UrlBar v-model="probe.url" :loading="probe.loading" :can-check="probe.canCheck" @check="probe.check()" />
    <p v-if="probe.error" class="error" role="alert">{{ probe.error }}</p>
    <p v-if="jobs.startError" class="error" role="alert">{{ jobs.startError }}</p>

    <ProbeCard v-if="probe.result" :result="probe.result" :selected="probe.selected" @select="probe.select($event)" @download="download" />

    <section v-if="jobs.jobs.length">
      <h2>Downloads</h2>
      <ul class="list">
        <JobCard v-for="job in jobs.jobs" :key="job.id" :job="job" @cancel="jobs.cancel(job.id)" @dismiss="jobs.dismiss(job.id)" />
      </ul>
    </section>

    <section class="panel">
      <h2>My files</h2>
      <p v-if="files.error" class="error" role="alert">{{ files.error }}</p>
      <p v-if="!files.files.length" class="muted small">Nothing here yet. Finished downloads show up here until they expire.</p>
      <ul v-else class="list">
        <FileRow v-for="file in files.files" :key="file.file_id" :file="file" :now="now" @remove="files.remove(file.file_id)" />
      </ul>
    </section>

    <p class="footer muted small">Download only content you have the right to download.</p>
  </main>
</template>
```

- [ ] **Step 4: Run tests and build**

Run: `npm test && npm run build`
Expected: all tests pass (FileRow expects "5 h 0 min": `formatExpiry(1000+18000, 1000)` gives hours=5, minutes part `Math.floor((18000 % 3600)/60)=0` → "5 h 0 min"); build passes with no type errors.

- [ ] **Step 5: Manual smoke test**

With `video_downloader` running (`run.bat` in `video_downloader/`), run `npm run dev`, open http://127.0.0.1:5175, paste a short public video link, press Check, pick a quality, Download, watch the progress bar, click "Download file", then delete the file from My files. Also paste `http://127.0.0.1/x` and confirm a "not a public website" error shows. Report what happened.

- [ ] **Step 6: Commit**

```bash
cd .. && git add -A && git commit -m "feat(web): URL bar, probe card, job cards, file list and app shell"
```

---

## Self-Review

- **Spec coverage:** URL bar + Check, probe card (thumbnail, title, duration, uploader, preset picker with blocked reasons, Download), active jobs (progress, speed, ETA, Cancel, Dismiss), My files (Download via signed link, Delete, expiry), error-code table (`messages.ts`), footer rights notice, Pinia stores `probe`/`jobs`/`files`, Vitest for stores, error mapping, preset picker. No e2e.
- **Placeholder scan:** none.
- **Type consistency:** `JobEvent` done carries `file_id` and `file` as the backend emits (`{"type":"done","file_id","file"}`); `ProbeResult`/`PresetOption`/`FileInfo` field names match `src/models.py`; `useJobsStore().start(url, title, option)` matches `App.vue`; `formatExpiry(expiresAt, now)` both unix seconds, `now` ref in seconds.
