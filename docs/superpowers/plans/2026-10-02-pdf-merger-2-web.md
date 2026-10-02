# PDF merger web app (`pdf_merger_web`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `pdf_merger_web/`, a single-page Vite + Vue 3 + TypeScript app where people upload PDFs and images, choose page ranges, reorder pages with thumbnails, set output options, and merge.

**Architecture:** Typed API client (`src/api/`) over `pdf_merger`'s REST API, reached through Vite's `/api` proxy so the session cookie is same-origin. Two Pinia stores: `files` (uploaded sources and their per-file options) and `plan` (page order, output options, merge state). Pure functions in `src/lib/segments.ts` convert between the page strip and the server's `MergePlan` segments. Thumbnails render lazily in the browser with `pdfjs-dist`.

**Tech Stack:** Vue 3.5, Pinia, TypeScript (~6.0), Vite 8, Vitest 5 + jsdom + @vue/test-utils, vue-tsc, pdfjs-dist 5.

**Spec:** `docs/superpowers/specs/2026-10-02-pdf-merger-design.md`

This is plan 2 of 3. It needs plan 1 (`2026-10-02-pdf-merger-1-backend.md`) done for the manual check in Task 9; every automated test here mocks the API.

## Global Constraints

- Working directory for every command: `Python/MCPServer/pdf_merger_web` unless a step says otherwise. Git commands run in `Python/MCPServer`.
- Same toolchain versions as `ember_web/package.json` (Vue ^3.5.42, Pinia ^4.0.3, Vite ^8.3.0, Vitest ^5.0.2, TypeScript ~6.0.2, vue-tsc ^3.3.11). One new runtime dependency: `pdfjs-dist`.
- `tsconfig` has `erasableSyntaxOnly: true`, `noUnusedLocals`, `noUnusedParameters`. So: no `enum`, no constructor parameter properties, no unused variables, in app code and test code alike (`vue-tsc -b` type-checks tests too).
- Dev server: `127.0.0.1`, port `PDF_MERGER_WEB_PORT` (default 5174), `strictPort: true`. `/api` proxies to `PDF_MERGER_API_URL` (default `http://127.0.0.1:8040`).
- All requests are relative (`/api/...`). The merge result's absolute `download_url` is turned into a relative path before use, so downloads also go through the proxy.
- One screen, top to bottom: header, drop zone, source files, page strip, output panel, merge bar. No router.
- UI copy: sentence case, no "please", no exclamation marks, errors say what happened then what to do.
- Server API shape (from plan 1): `POST /api/files` raw body + `X-Filename` (URL-encoded) → `FileInfo`; `GET /api/files` → `FileInfo[]`; `DELETE /api/files/{id}` → 204; `GET /api/files/{id}/content`; `POST /api/merge` `MergePlan` → `{job_id}`; `GET /api/jobs/{id}/events` SSE with one JSON object per `data:` line and types `queued | progress | done | error`. Error bodies: `{"error": {"code", "message"}}`.

---

## File map

```
pdf_merger_web/
  package.json, vite.config.ts, tsconfig.json, tsconfig.app.json, tsconfig.node.json   Task 1
  index.html, .gitignore, run.bat, src/main.ts, src/App.vue (placeholder)              Task 1
  src/api/types.ts          Task 2   API types, ApiError
  src/api/client.ts         Task 2   listFiles, uploadFile, deleteFile, startMerge, contentUrl, watchJob
  src/lib/segments.ts       Task 3   PageItem, parseRange, formatRange, toSegments, reconcile, moveItem
  src/lib/format.ts         Task 3   formatBytes, plural
  src/lib/messages.ts       Task 3   messageOf
  src/stores/files.ts       Task 4   useFilesStore, SourceState
  src/stores/plan.ts        Task 5   usePlanStore
  src/components/DropZone.vue, SourceRow.vue, SourceList.vue                          Task 6
  src/lib/pdfThumbs.ts, src/components/PageThumb.vue, PageStrip.vue                   Task 7
  src/components/OutputPanel.vue, MergeBar.vue                                         Task 8
  src/App.vue (final), src/style.css, README.md                                        Task 9
  *.test.ts beside their source
```

---

### Task 1: Project scaffold

**Files:**
- Create: `pdf_merger_web/package.json`, `vite.config.ts`, `tsconfig.json`, `tsconfig.app.json`, `tsconfig.node.json`, `index.html`, `.gitignore`, `run.bat`, `src/main.ts`, `src/App.vue`, `src/style.css`

**Interfaces:**
- Produces: a building, runnable Vite app; `npm test` runs `src/**/*.test.ts` in jsdom.

- [ ] **Step 1: Create the files**

`pdf_merger_web/package.json`:

```json
{
  "name": "pdf_merger_web",
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
    "pdfjs-dist": "^5.4.0",
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

`pdf_merger_web/vite.config.ts`:

```ts
import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vitest/config'

// Everything under /api goes to pdf_merger, so the browser sees one origin:
// the pm_session cookie works and no CORS is involved. SSE streams through.
const apiProxy = {
  '/api': { target: process.env.PDF_MERGER_API_URL ?? 'http://127.0.0.1:8040' },
}

export default defineConfig({
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
    port: Number(process.env.PDF_MERGER_WEB_PORT ?? 5174),
    strictPort: true,
    // Explicit IPv4: on Windows "localhost" can bind only [::1].
    host: '127.0.0.1',
    proxy: apiProxy,
  },
  preview: { proxy: apiProxy },
})
```

`pdf_merger_web/tsconfig.json`:

```json
{
  "files": [],
  "references": [{ "path": "./tsconfig.app.json" }, { "path": "./tsconfig.node.json" }]
}
```

`pdf_merger_web/tsconfig.app.json`:

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

`pdf_merger_web/tsconfig.node.json`:

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

`pdf_merger_web/index.html`:

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <meta name="robots" content="noindex, nofollow" />
    <title>PDF merger</title>
  </head>
  <body>
    <div id="app"></div>
    <script type="module" src="/src/main.ts"></script>
  </body>
</html>
```

`pdf_merger_web/.gitignore`:

```
node_modules
dist
*.local
*.log
```

`pdf_merger_web/run.bat`:

```bat
@echo off
REM pdf_merger_web dev launcher. Installs node_modules on first run, then starts
REM the Vite dev server. Extra args pass straight through to vite (e.g. --open).
REM
REM LABEL: PDF Merger Web
REM DESCRIPTION: Vue 3 + TypeScript web app for pdf_merger: upload, reorder pages and merge.
cd /d "%~dp0"

if not defined PDF_MERGER_WEB_PORT set PDF_MERGER_WEB_PORT=5174
if not defined PDF_MERGER_API_URL set PDF_MERGER_API_URL=http://127.0.0.1:8040

if not exist "node_modules" (
    echo Installing pdf_merger_web dependencies ...
    call npm install
)

:run
call npm run dev -- %*

echo.
echo ----------------------------------------
echo  pdf_merger_web stopped.
choice /C RQ /N /M "Press [R] to restart, [Q] to quit: "
if errorlevel 2 goto :end
if errorlevel 1 goto :run

:end
```

`PDF_MERGER_WEB_PORT` is set first on purpose: `server_launcher` treats the first `set` variable containing `PORT` as the port variable. `PDF_MERGER_API_URL` has no `PORT` in its name, so it is passed through as an extra env var.

`pdf_merger_web/src/main.ts`:

```ts
import { createPinia } from 'pinia'
import { createApp } from 'vue'
import App from './App.vue'
import './style.css'

createApp(App).use(createPinia()).mount('#app')
```

`pdf_merger_web/src/App.vue` (placeholder; Task 9 replaces it):

```vue
<template>
  <main class="app"><h1>PDF merger</h1></main>
</template>
```

`pdf_merger_web/src/style.css` (empty for now; Task 9 fills it):

```css
/* Filled in Task 9. */
```

- [ ] **Step 2: Install and build**

Run: `npm install`
Run: `npm run build`
Expected: build succeeds, `dist/` created.

- [ ] **Step 3: Commit**

```bash
git add pdf_merger_web
git commit -m "feat(pdf_merger_web): scaffold Vite + Vue + TypeScript app"
```

---

### Task 2: API types and client

**Files:**
- Create: `pdf_merger_web/src/api/types.ts`, `pdf_merger_web/src/api/client.ts`
- Test: `pdf_merger_web/src/api/client.test.ts`

**Interfaces:**
- Produces (`types.ts`): `Rotation = 0 | 90 | 180 | 270`, `Fit = 'fit' | 'fill' | 'original'`, `PageSize = 'A4' | 'Letter' | 'match'`, `FileKind = 'pdf' | 'image'`, `FileInfo`, `Segment`, `OutputOptions`, `MergePlan`, `MergeResult`, `JobEvent`, `class ApiError extends Error { code: string; status: number }`.
- Produces (`client.ts`): `listFiles(): Promise<FileInfo[]>`, `uploadFile(file: File): Promise<FileInfo>`, `deleteFile(fileId: string): Promise<void>`, `startMerge(plan: MergePlan): Promise<{ job_id: string }>`, `contentUrl(fileId: string): string`, `watchJob(jobId: string, onEvent: (event: JobEvent) => void): () => void` (returns a stop function; emits a synthetic `connection_lost` error if the stream drops before `done`/`error`).

- [ ] **Step 1: Write the types**

`pdf_merger_web/src/api/types.ts`:

```ts
// Mirrors pdf_merger/src/models.py. Keep both in step.

export type Rotation = 0 | 90 | 180 | 270
export type Fit = 'fit' | 'fill' | 'original'
export type PageSize = 'A4' | 'Letter' | 'match'
export type FileKind = 'pdf' | 'image'

export interface FileInfo {
  file_id: string
  name: string
  kind: FileKind
  pages: number
  size: number
  expires_at: number
}

export interface Segment {
  file_id: string
  pages: string | null
  rotate: Rotation
  fit: Fit | null
}

export interface OutputOptions {
  filename: string
  title: string | null
  author: string | null
  bookmarks: boolean
  image_page_size: PageSize
  image_fit: Fit
  image_margin_mm: number
}

export interface MergePlan {
  segments: Segment[]
  output: OutputOptions
}

export interface MergeResult {
  file_id: string
  name: string
  pages: number
  size: number
  expires_at: number
  download_url: string
}

export type JobEvent =
  | { type: 'queued'; total: number }
  | { type: 'progress'; done: number; total: number }
  | ({ type: 'done' } & MergeResult)
  | { type: 'error'; code: string; message: string }

/** A failed request, with the server's error code and user-facing message. */
export class ApiError extends Error {
  readonly code: string
  readonly status: number

  constructor(code: string, message: string, status: number) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.status = status
  }
}
```

- [ ] **Step 2: Write the failing test**

`pdf_merger_web/src/api/client.test.ts`:

```ts
import { describe, expect, it, vi } from 'vitest'
import { contentUrl, deleteFile, listFiles, startMerge, uploadFile, watchJob } from './client'
import type { JobEvent, MergePlan } from './types'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

class FakeEventSource {
  static last: FakeEventSource | null = null
  readonly url: string
  closed = false
  onmessage: ((event: MessageEvent<string>) => void) | null = null
  onerror: (() => void) | null = null

  constructor(url: string) {
    this.url = url
    FakeEventSource.last = this
  }

  close(): void {
    this.closed = true
  }

  emit(data: unknown): void {
    this.onmessage?.(new MessageEvent('message', { data: JSON.stringify(data) }))
  }
}

describe('client', () => {
  it('uploads the raw file with a URL-encoded name', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ file_id: 'f_1' }, 201))
    vi.stubGlobal('fetch', fetchMock)
    const file = new File(['%PDF-'], 'résumé 1.pdf')

    await uploadFile(file)

    const [url, init] = fetchMock.mock.calls[0]!
    expect(url).toBe('/api/files')
    expect(init.method).toBe('POST')
    expect(init.body).toBe(file)
    expect(init.headers['X-Filename']).toBe(encodeURIComponent('résumé 1.pdf'))
  })

  it('turns an error body into an ApiError', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(jsonResponse({ error: { code: 'unsupported_type', message: 'Nope.' } }, 415)),
    )

    await expect(listFiles()).rejects.toMatchObject({ name: 'ApiError', code: 'unsupported_type', message: 'Nope.', status: 415 })
  })

  it('falls back to a generic error when the body is not JSON', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('bad gateway', { status: 502 })))

    await expect(listFiles()).rejects.toMatchObject({ code: 'http_error', status: 502 })
  })

  it('resolves delete on 204', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 204 }))
    vi.stubGlobal('fetch', fetchMock)

    await expect(deleteFile('f_1')).resolves.toBeUndefined()
    expect(fetchMock.mock.calls[0]![0]).toBe('/api/files/f_1')
    expect(fetchMock.mock.calls[0]![1].method).toBe('DELETE')
  })

  it('posts the plan as JSON', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ job_id: 'j_1' }, 202))
    vi.stubGlobal('fetch', fetchMock)
    const plan: MergePlan = {
      segments: [{ file_id: 'f_1', pages: '1-2', rotate: 0, fit: null }],
      output: {
        filename: 'm.pdf',
        title: null,
        author: null,
        bookmarks: true,
        image_page_size: 'A4',
        image_fit: 'fit',
        image_margin_mm: 10,
      },
    }

    await expect(startMerge(plan)).resolves.toEqual({ job_id: 'j_1' })
    expect(JSON.parse(fetchMock.mock.calls[0]![1].body)).toEqual(plan)
  })

  it('builds content URLs', () => {
    expect(contentUrl('f_1')).toBe('/api/files/f_1/content')
  })

  it('streams job events and closes after done', () => {
    vi.stubGlobal('EventSource', FakeEventSource)
    const events: JobEvent[] = []

    watchJob('j_1', (event) => events.push(event))
    const source = FakeEventSource.last!
    source.emit({ type: 'progress', done: 1, total: 2 })
    source.emit({ type: 'done', file_id: 'f_r', name: 'm.pdf', pages: 2, size: 9, expires_at: 0, download_url: 'x' })
    source.onerror?.()

    expect(source.url).toBe('/api/jobs/j_1/events')
    expect(events.map((e) => e.type)).toEqual(['progress', 'done'])
    expect(source.closed).toBe(true)
  })

  it('reports a dropped connection once', () => {
    vi.stubGlobal('EventSource', FakeEventSource)
    const events: JobEvent[] = []

    watchJob('j_1', (event) => events.push(event))
    FakeEventSource.last!.onerror?.()
    FakeEventSource.last!.onerror?.()

    expect(events).toEqual([
      { type: 'error', code: 'connection_lost', message: 'Lost the connection to the server. Try the merge again.' },
    ])
  })
})
```

- [ ] **Step 3: Run test to verify it fails**

Run: `npx vitest run src/api/client.test.ts`
Expected: FAIL with `Failed to resolve import "./client"`.

- [ ] **Step 4: Write the implementation**

`pdf_merger_web/src/api/client.ts`:

```ts
// Thin typed wrapper over pdf_merger's REST API. Every path is relative
// (/api/...) so requests go through the Vite proxy with the session cookie.
import { ApiError, type FileInfo, type JobEvent, type MergePlan } from './types'

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

function fileUrl(fileId: string, suffix = ''): string {
  return `${BASE}/files/${encodeURIComponent(fileId)}${suffix}`
}

export function listFiles(): Promise<FileInfo[]> {
  return fetch(`${BASE}/files`).then((r) => parse<FileInfo[]>(r))
}

/** Streams the file as the raw request body; the server sniffs its real type. */
export function uploadFile(file: File): Promise<FileInfo> {
  return fetch(`${BASE}/files`, {
    method: 'POST',
    body: file,
    headers: { 'X-Filename': encodeURIComponent(file.name), 'Content-Type': 'application/octet-stream' },
  }).then((r) => parse<FileInfo>(r))
}

export function deleteFile(fileId: string): Promise<void> {
  return fetch(fileUrl(fileId), { method: 'DELETE' }).then((r) => parse<void>(r))
}

export function startMerge(plan: MergePlan): Promise<{ job_id: string }> {
  return fetch(`${BASE}/merge`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(plan),
  }).then((r) => parse<{ job_id: string }>(r))
}

export function contentUrl(fileId: string): string {
  return fileUrl(fileId, '/content')
}

/** Follow a merge job over SSE. Returns a function that stops listening. */
export function watchJob(jobId: string, onEvent: (event: JobEvent) => void): () => void {
  const source = new EventSource(`${BASE}/jobs/${encodeURIComponent(jobId)}/events`)
  let finished = false
  const finish = (): void => {
    finished = true
    source.close()
  }
  source.onmessage = (message: MessageEvent<string>) => {
    const event = JSON.parse(message.data) as JobEvent
    onEvent(event)
    if (event.type === 'done' || event.type === 'error') finish()
  }
  source.onerror = () => {
    if (finished) return
    finish()
    onEvent({ type: 'error', code: 'connection_lost', message: 'Lost the connection to the server. Try the merge again.' })
  }
  return finish
}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `npx vitest run src/api/client.test.ts`
Expected: PASS (8 tests).

- [ ] **Step 6: Commit**

```bash
git add pdf_merger_web/src/api
git commit -m "feat(pdf_merger_web): add typed API client with SSE job watching"
```

---

### Task 3: Segment logic and small helpers

**Files:**
- Create: `pdf_merger_web/src/lib/segments.ts`, `src/lib/format.ts`, `src/lib/messages.ts`
- Test: `pdf_merger_web/src/lib/segments.test.ts`, `src/lib/format.test.ts`

**Interfaces:**
- Consumes: `Fit`, `FileKind`, `Rotation`, `Segment` (Task 2).
- Produces:
  - `PageItem { key: string; fileId: string; page: number /* 0-based */; rotate: Rotation }`, `pageKey(fileId, page): string` (`"<fileId>:<page>"`).
  - `parseRange(spec: string, count: number): number[] | string` (string = error message; mirrors the server parser plus duplicate check).
  - `formatRange(pages: readonly number[]): string` (0-based in, 1-based ranges out; compresses ascending runs only).
  - `toSegments(items, fitByFile: ReadonlyMap<string, Fit | null>, kindByFile: ReadonlyMap<string, FileKind>): Segment[]` (consecutive items with the same file and rotation become one segment).
  - `reconcile(current: readonly PageItem[], fresh: readonly PageItem[]): PageItem[]` (keeps the current order for pages still present, takes rotation from `fresh`, inserts new pages before the next already-placed page of the same file, else after its last placed page, else at the end).
  - `moveItem<T>(list: readonly T[], from: number, to: number): T[]`.
  - `formatBytes(bytes: number): string`, `plural(count: number, word: string): string`.
  - `messageOf(error: unknown): string`.

- [ ] **Step 1: Write the failing tests**

`pdf_merger_web/src/lib/segments.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import type { FileKind, Fit, Rotation } from '../api/types'
import { formatRange, moveItem, pageKey, parseRange, reconcile, toSegments, type PageItem } from './segments'

function item(fileId: string, page: number, rotate: Rotation = 0): PageItem {
  return { key: pageKey(fileId, page), fileId, page, rotate }
}

const keys = (items: PageItem[]) => items.map((i) => i.key)

describe('parseRange', () => {
  it('selects every page for empty or all', () => {
    expect(parseRange('', 3)).toEqual([0, 1, 2])
    expect(parseRange(' ALL ', 2)).toEqual([0, 1])
  })

  it('parses ranges in written order', () => {
    expect(parseRange('1-3,7', 10)).toEqual([0, 1, 2, 6])
    expect(parseRange('5, 2', 10)).toEqual([4, 1])
  })

  it('returns a message for bad input', () => {
    expect(parseRange('0', 5)).toBe('Pages go from 1 to 5')
    expect(parseRange('6', 5)).toBe('Pages go from 1 to 5')
    expect(parseRange('3-1', 5)).toBe('"3-1" runs backwards')
    expect(parseRange('a', 5)).toBe('"a" isn\'t a page or range')
    expect(parseRange('1,1', 5)).toBe('A page is listed twice')
  })
})

describe('formatRange', () => {
  it('compresses ascending runs only', () => {
    expect(formatRange([0, 1, 2, 6])).toBe('1-3,7')
    expect(formatRange([4, 1])).toBe('5,2')
    expect(formatRange([0])).toBe('1')
  })
})

describe('toSegments', () => {
  const kinds = new Map<string, FileKind>([
    ['a', 'pdf'],
    ['img', 'image'],
  ])
  const fits = new Map<string, Fit | null>([['img', 'fill']])

  it('groups neighbours of the same file and rotation', () => {
    const segments = toSegments([item('a', 0), item('a', 1), item('img', 0), item('a', 2, 90), item('a', 3, 90)], fits, kinds)

    expect(segments).toEqual([
      { file_id: 'a', pages: '1-2', rotate: 0, fit: null },
      { file_id: 'img', pages: null, rotate: 0, fit: 'fill' },
      { file_id: 'a', pages: '3-4', rotate: 90, fit: null },
    ])
  })

  it('returns nothing for no pages', () => {
    expect(toSegments([], fits, kinds)).toEqual([])
  })
})

describe('reconcile', () => {
  it('keeps manual order and drops removed pages', () => {
    const current = [item('b', 0), item('a', 1), item('a', 0)]
    const fresh = [item('a', 0), item('b', 0)]

    expect(keys(reconcile(current, fresh))).toEqual(['b:0', 'a:0'])
  })

  it('takes rotation from fresh', () => {
    expect(reconcile([item('a', 0)], [item('a', 0, 180)])[0]!.rotate).toBe(180)
  })

  it('inserts a new page before the next placed page of its file', () => {
    const current = [item('b', 0), item('a', 2)]
    const fresh = [item('a', 0), item('a', 2), item('b', 0)]

    expect(keys(reconcile(current, fresh))).toEqual(['b:0', 'a:0', 'a:2'])
  })

  it('appends pages of a new file at the end, in order', () => {
    const current = [item('a', 0)]
    const fresh = [item('a', 0), item('c', 0), item('c', 1)]

    expect(keys(reconcile(current, fresh))).toEqual(['a:0', 'c:0', 'c:1'])
  })
})

describe('moveItem', () => {
  it('moves without mutating', () => {
    const list = ['a', 'b', 'c']

    expect(moveItem(list, 2, 0)).toEqual(['c', 'a', 'b'])
    expect(list).toEqual(['a', 'b', 'c'])
  })
})
```

`pdf_merger_web/src/lib/format.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { formatBytes, plural } from './format'
import { messageOf } from './messages'

describe('format helpers', () => {
  it('formats bytes', () => {
    expect(formatBytes(512)).toBe('512 B')
    expect(formatBytes(2048)).toBe('2 KB')
    expect(formatBytes(3.25 * 1024 * 1024)).toBe('3.3 MB')
  })

  it('pluralizes', () => {
    expect(plural(1, 'page')).toBe('1 page')
    expect(plural(2, 'page')).toBe('2 pages')
  })

  it('reads error messages', () => {
    expect(messageOf(new Error('Broken.'))).toBe('Broken.')
    expect(messageOf('plain')).toBe('plain')
  })
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `npx vitest run src/lib`
Expected: FAIL with `Failed to resolve import "./segments"`.

- [ ] **Step 3: Write the implementation**

`pdf_merger_web/src/lib/segments.ts`:

```ts
// Pure conversions between the page strip (one PageItem per output page)
// and the server's MergePlan segments. No Vue, no I/O: easy to test.
import type { FileKind, Fit, Rotation, Segment } from '../api/types'

export interface PageItem {
  key: string
  fileId: string
  /** 0-based page index in the source file. */
  page: number
  rotate: Rotation
}

export function pageKey(fileId: string, page: number): string {
  return `${fileId}:${page}`
}

const PART = /^(\d+)(?:\s*-\s*(\d+))?$/

/** 0-based pages for a "1-3,7" spec, or an error message. Same rules as the server. */
export function parseRange(spec: string, count: number): number[] | string {
  const text = spec.trim().toLowerCase()
  if (text === '' || text === 'all') return Array.from({ length: count }, (_, i) => i)
  const pages: number[] = []
  for (const raw of text.split(',')) {
    const part = raw.trim()
    const match = PART.exec(part)
    if (!match) return `"${part}" isn't a page or range`
    const start = Number(match[1])
    const end = Number(match[2] ?? match[1])
    if (start > end) return `"${part}" runs backwards`
    if (start < 1 || end > count) return `Pages go from 1 to ${count}`
    for (let page = start; page <= end; page++) pages.push(page - 1)
  }
  if (new Set(pages).size !== pages.length) return 'A page is listed twice'
  return pages
}

/** 0-based pages to a 1-based spec. Only ascending runs collapse, so order is kept. */
export function formatRange(pages: readonly number[]): string {
  const parts: string[] = []
  let start = 0
  while (start < pages.length) {
    let end = start
    while (end + 1 < pages.length && pages[end + 1] === pages[end]! + 1) end++
    parts.push(start === end ? `${pages[start]! + 1}` : `${pages[start]! + 1}-${pages[end]! + 1}`)
    start = end + 1
  }
  return parts.join(',')
}

/** Group neighbouring pages of one file with one rotation into segments. O(n). */
export function toSegments(
  items: readonly PageItem[],
  fitByFile: ReadonlyMap<string, Fit | null>,
  kindByFile: ReadonlyMap<string, FileKind>,
): Segment[] {
  const segments: Segment[] = []
  let run: PageItem[] = []
  const flush = (): void => {
    const first = run[0]
    if (!first) return
    const isImage = kindByFile.get(first.fileId) === 'image'
    segments.push({
      file_id: first.fileId,
      pages: isImage ? null : formatRange(run.map((r) => r.page)),
      rotate: first.rotate,
      fit: isImage ? (fitByFile.get(first.fileId) ?? null) : null,
    })
    run = []
  }
  for (const item of items) {
    const last = run[run.length - 1]
    if (last && (last.fileId !== item.fileId || last.rotate !== item.rotate)) flush()
    run.push(item)
  }
  flush()
  return segments
}

function lastIndexOfFile(items: readonly PageItem[], fileId: string): number {
  for (let i = items.length - 1; i >= 0; i--) if (items[i]!.fileId === fileId) return i
  return -1
}

/**
 * Apply a new page set to a hand-ordered strip. Pages still present keep
 * their place (with fresh rotation); new pages slot in near their file.
 * O(n^2) worst case; n is capped at 2000 pages by the server.
 */
export function reconcile(current: readonly PageItem[], fresh: readonly PageItem[]): PageItem[] {
  const freshByKey = new Map(fresh.map((item) => [item.key, item]))
  const result: PageItem[] = []
  for (const item of current) {
    const updated = freshByKey.get(item.key)
    if (updated) result.push(updated)
  }
  const placed = new Set(result.map((item) => item.key))
  fresh.forEach((item, index) => {
    if (placed.has(item.key)) return
    const next = fresh.slice(index + 1).find((other) => other.fileId === item.fileId && placed.has(other.key))
    let at: number
    if (next) {
      at = result.findIndex((r) => r.key === next.key)
    } else {
      const last = lastIndexOfFile(result, item.fileId)
      at = last === -1 ? result.length : last + 1
    }
    result.splice(at, 0, item)
    placed.add(item.key)
  })
  return result
}

export function moveItem<T>(list: readonly T[], from: number, to: number): T[] {
  const copy = [...list]
  const [moved] = copy.splice(from, 1)
  if (moved !== undefined) copy.splice(to, 0, moved)
  return copy
}
```

`pdf_merger_web/src/lib/format.ts`:

```ts
export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

export function plural(count: number, word: string): string {
  return `${count} ${word}${count === 1 ? '' : 's'}`
}
```

`pdf_merger_web/src/lib/messages.ts`:

```ts
/** The user-facing text of anything thrown. ApiError messages come from the server. */
export function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `npx vitest run src/lib`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pdf_merger_web/src/lib
git commit -m "feat(pdf_merger_web): add page-strip to segment conversion"
```

---

### Task 4: Files store

**Files:**
- Create: `pdf_merger_web/src/stores/files.ts`
- Test: `pdf_merger_web/src/stores/files.test.ts`

**Interfaces:**
- Consumes: `api/client` functions (Task 2), `parseRange`, `moveItem` (Task 3), `messageOf` (Task 3).
- Produces: `SourceState { info: FileInfo; range: string; pages: number[]; rangeError: string | null; rotate: Rotation; fit: Fit | null }`; `useFilesStore()` with state `sources`, `uploading`, `errors` and actions `add(info)`, `upload(files)`, `restore()`, `remove(fileId)`, `setRange(fileId, text)`, `rotate(fileId)`, `setFit(fileId, fit)`, `moveSource(from, to)`, `dismissError(index)`.

`pages` always holds the last valid selection, so an invalid range never empties the strip.

- [ ] **Step 1: Write the failing test**

`pdf_merger_web/src/stores/files.test.ts`:

```ts
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '../api/client'
import type { FileInfo } from '../api/types'
import { useFilesStore } from './files'

vi.mock('../api/client')

function pdf(id: string, pages = 3): FileInfo {
  return { file_id: id, name: `${id}.pdf`, kind: 'pdf', pages, size: 1000, expires_at: 0 }
}

describe('files store', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('uploads in drop order and reports failures per file', async () => {
    vi.mocked(api.uploadFile)
      .mockResolvedValueOnce(pdf('f_a'))
      .mockRejectedValueOnce(new Error('Too big.'))
      .mockResolvedValueOnce(pdf('f_c'))
    const files = useFilesStore()

    await files.upload([new File([''], 'a.pdf'), new File([''], 'b.pdf'), new File([''], 'c.pdf')])

    expect(files.sources.map((s) => s.info.file_id)).toEqual(['f_a', 'f_c'])
    expect(files.errors).toEqual(['b.pdf: Too big.'])
    expect(files.uploading).toBe(0)
  })

  it('starts with every page selected', () => {
    const files = useFilesStore()
    files.add(pdf('f_a', 3))

    expect(files.sources[0]).toMatchObject({ range: 'all', pages: [0, 1, 2], rangeError: null, rotate: 0, fit: null })
  })

  it('keeps the last valid pages while a range is invalid', () => {
    const files = useFilesStore()
    files.add(pdf('f_a', 5))

    files.setRange('f_a', '2-3')
    files.setRange('f_a', '9')

    expect(files.sources[0]).toMatchObject({ range: '9', pages: [1, 2], rangeError: 'Pages go from 1 to 5' })
    files.setRange('f_a', '4')
    expect(files.sources[0]).toMatchObject({ pages: [3], rangeError: null })
  })

  it('rotates in 90 degree steps', () => {
    const files = useFilesStore()
    files.add(pdf('f_a'))

    for (let i = 0; i < 4; i++) files.rotate('f_a')

    expect(files.sources[0]!.rotate).toBe(0)
    files.rotate('f_a')
    expect(files.sources[0]!.rotate).toBe(90)
  })

  it('restore adds server files once', async () => {
    vi.mocked(api.listFiles).mockResolvedValue([pdf('f_a'), pdf('f_b')])
    const files = useFilesStore()
    files.add(pdf('f_a'))

    await files.restore()

    expect(files.sources.map((s) => s.info.file_id)).toEqual(['f_a', 'f_b'])
  })

  it('removes locally even when the server delete fails', async () => {
    vi.mocked(api.deleteFile).mockRejectedValue(new Error('gone'))
    const files = useFilesStore()
    files.add(pdf('f_a'))

    await files.remove('f_a')

    expect(files.sources).toEqual([])
  })

  it('moves sources', () => {
    const files = useFilesStore()
    files.add(pdf('f_a'))
    files.add(pdf('f_b'))

    files.moveSource(1, 0)

    expect(files.sources.map((s) => s.info.file_id)).toEqual(['f_b', 'f_a'])
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run src/stores/files.test.ts`
Expected: FAIL with `Failed to resolve import "./files"`.

- [ ] **Step 3: Write the implementation**

`pdf_merger_web/src/stores/files.ts`:

```ts
// Uploaded source files and their per-file options (range, rotation, fit).
import { defineStore } from 'pinia'
import { ref } from 'vue'
import * as api from '../api/client'
import type { FileInfo, Fit, Rotation } from '../api/types'
import { messageOf } from '../lib/messages'
import { moveItem, parseRange } from '../lib/segments'

export interface SourceState {
  info: FileInfo
  /** What the user typed. */
  range: string
  /** Last valid selection, 0-based. */
  pages: number[]
  rangeError: string | null
  rotate: Rotation
  /** Images only; null = use the output default. */
  fit: Fit | null
}

function allPages(info: FileInfo): number[] {
  return Array.from({ length: info.pages }, (_, i) => i)
}

export const useFilesStore = defineStore('files', () => {
  const sources = ref<SourceState[]>([])
  const uploading = ref(0)
  const errors = ref<string[]>([])

  function find(fileId: string): SourceState | undefined {
    return sources.value.find((s) => s.info.file_id === fileId)
  }

  function add(info: FileInfo): void {
    if (find(info.file_id)) return
    sources.value.push({ info, range: 'all', pages: allPages(info), rangeError: null, rotate: 0, fit: null })
  }

  /** One at a time, so sources appear in drop order. */
  async function upload(files: readonly File[]): Promise<void> {
    uploading.value += files.length
    for (const file of files) {
      try {
        add(await api.uploadFile(file))
      } catch (error) {
        errors.value.push(`${file.name}: ${messageOf(error)}`)
      } finally {
        uploading.value -= 1
      }
    }
  }

  /** Bring back this browser's files after a reload. Also makes the server set the session cookie. */
  async function restore(): Promise<void> {
    try {
      for (const info of await api.listFiles()) add(info)
    } catch (error) {
      errors.value.push(`Couldn't load your files: ${messageOf(error)}`)
    }
  }

  async function remove(fileId: string): Promise<void> {
    sources.value = sources.value.filter((s) => s.info.file_id !== fileId)
    try {
      await api.deleteFile(fileId)
    } catch {
      // Already expired or deleted; nothing left to do.
    }
  }

  function setRange(fileId: string, text: string): void {
    const source = find(fileId)
    if (!source) return
    source.range = text
    const parsed = parseRange(text, source.info.pages)
    if (typeof parsed === 'string') {
      source.rangeError = parsed
    } else {
      source.rangeError = null
      source.pages = parsed
    }
  }

  function rotate(fileId: string): void {
    const source = find(fileId)
    if (source) source.rotate = ((source.rotate + 90) % 360) as Rotation
  }

  function setFit(fileId: string, fit: Fit | null): void {
    const source = find(fileId)
    if (source) source.fit = fit
  }

  function moveSource(from: number, to: number): void {
    sources.value = moveItem(sources.value, from, to)
  }

  function dismissError(index: number): void {
    errors.value.splice(index, 1)
  }

  return { sources, uploading, errors, add, upload, restore, remove, setRange, rotate, setFit, moveSource, dismissError }
})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx vitest run src/stores/files.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pdf_merger_web/src/stores/files.ts pdf_merger_web/src/stores/files.test.ts
git commit -m "feat(pdf_merger_web): add files store"
```

---

### Task 5: Plan store

**Files:**
- Create: `pdf_merger_web/src/stores/plan.ts`
- Test: `pdf_merger_web/src/stores/plan.test.ts`

**Interfaces:**
- Consumes: `useFilesStore` (Task 4), `startMerge`, `watchJob` (Task 2), `PageItem`, `pageKey`, `reconcile`, `toSegments`, `moveItem` (Task 3), `messageOf`.
- Produces: `MergeStatus = 'idle' | 'running' | 'done' | 'error'`; `usePlanStore()` with state `pages: PageItem[]`, `manualOrder: boolean`, `output: OutputOptions`, `status`, `progress: { done; total }`, `result: MergeResult | null`, `error: string | null`; getters `segments`, `hasRangeErrors`, `canMerge`; actions `movePage(from, to)`, `resetOrder()`, `buildPlan(): MergePlan`, `merge()`.

Page order rule: until the user drags a page, `pages` follows source order. After a drag (`manualOrder = true`), changes to sources are merged in with `reconcile`. `resetOrder()` goes back to source order.

- [ ] **Step 1: Write the failing test**

`pdf_merger_web/src/stores/plan.test.ts`:

```ts
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { nextTick } from 'vue'
import * as api from '../api/client'
import { ApiError, type FileInfo, type JobEvent } from '../api/types'
import type { PageItem } from '../lib/segments'
import { useFilesStore } from './files'
import { usePlanStore } from './plan'

vi.mock('../api/client')

function info(id: string, pages: number, kind: 'pdf' | 'image' = 'pdf'): FileInfo {
  return { file_id: id, name: `${id}.${kind === 'pdf' ? 'pdf' : 'jpg'}`, kind, pages, size: 10, expires_at: 0 }
}

const keys = (items: PageItem[]) => items.map((i) => i.key)

describe('plan store', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('follows source order until a page is moved by hand', async () => {
    const files = useFilesStore()
    const plan = usePlanStore()
    files.add(info('f_a', 2))
    files.add(info('f_b', 1))
    await nextTick()
    expect(keys(plan.pages)).toEqual(['f_a:0', 'f_a:1', 'f_b:0'])

    files.moveSource(1, 0)
    await nextTick()
    expect(keys(plan.pages)).toEqual(['f_b:0', 'f_a:0', 'f_a:1'])

    plan.movePage(2, 0)
    expect(plan.manualOrder).toBe(true)
    files.setRange('f_a', '1')
    await nextTick()
    expect(keys(plan.pages)).toEqual(['f_b:0', 'f_a:0'])

    plan.resetOrder()
    expect(plan.manualOrder).toBe(false)
    expect(keys(plan.pages)).toEqual(['f_b:0', 'f_a:0'])
  })

  it('builds segments with image fit and rotation', async () => {
    const files = useFilesStore()
    const plan = usePlanStore()
    files.add(info('f_a', 3))
    files.add(info('f_img', 1, 'image'))
    files.setFit('f_img', 'fill')
    files.rotate('f_a')
    await nextTick()

    expect(plan.segments).toEqual([
      { file_id: 'f_a', pages: '1-3', rotate: 90, fit: null },
      { file_id: 'f_img', pages: null, rotate: 0, fit: 'fill' },
    ])
  })

  it('cannot merge with no pages or with a range error', async () => {
    const files = useFilesStore()
    const plan = usePlanStore()
    expect(plan.canMerge).toBe(false)

    files.add(info('f_a', 2))
    await nextTick()
    expect(plan.canMerge).toBe(true)

    files.setRange('f_a', 'x')
    expect(plan.canMerge).toBe(false)
  })

  it('cleans up output options in the plan', () => {
    const plan = usePlanStore()
    plan.output.filename = '  '
    plan.output.title = '  Package '
    plan.output.author = ''

    expect(plan.buildPlan().output).toMatchObject({ filename: 'merged.pdf', title: 'Package', author: null })
  })

  it('merges and records progress and the result', async () => {
    vi.mocked(api.startMerge).mockResolvedValue({ job_id: 'j_1' })
    vi.mocked(api.watchJob).mockImplementation((_jobId: string, onEvent: (event: JobEvent) => void) => {
      onEvent({ type: 'progress', done: 1, total: 2 })
      onEvent({ type: 'done', file_id: 'f_r', name: 'merged.pdf', pages: 2, size: 99, expires_at: 0, download_url: 'u' })
      return () => {}
    })
    const files = useFilesStore()
    const plan = usePlanStore()
    files.add(info('f_a', 2))
    await nextTick()

    await plan.merge()

    expect(api.watchJob).toHaveBeenCalledWith('j_1', expect.any(Function))
    expect(plan.status).toBe('done')
    expect(plan.progress).toEqual({ done: 1, total: 2 })
    expect(plan.result).toEqual({ file_id: 'f_r', name: 'merged.pdf', pages: 2, size: 99, expires_at: 0, download_url: 'u' })
  })

  it('shows the server message when the merge is refused', async () => {
    vi.mocked(api.startMerge).mockRejectedValue(new ApiError('invalid_range', 'Segment 1 (a.pdf): bad.', 422))
    const files = useFilesStore()
    const plan = usePlanStore()
    files.add(info('f_a', 2))
    await nextTick()

    await plan.merge()

    expect(plan.status).toBe('error')
    expect(plan.error).toBe('Segment 1 (a.pdf): bad.')
  })

  it('shows job errors', async () => {
    vi.mocked(api.startMerge).mockResolvedValue({ job_id: 'j_1' })
    vi.mocked(api.watchJob).mockImplementation((_jobId: string, onEvent: (event: JobEvent) => void) => {
      onEvent({ type: 'error', code: 'merge_timeout', message: 'Too slow.' })
      return () => {}
    })
    const files = useFilesStore()
    const plan = usePlanStore()
    files.add(info('f_a', 2))
    await nextTick()

    await plan.merge()

    expect(plan.status).toBe('error')
    expect(plan.error).toBe('Too slow.')
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run src/stores/plan.test.ts`
Expected: FAIL with `Failed to resolve import "./plan"`.

- [ ] **Step 3: Write the implementation**

`pdf_merger_web/src/stores/plan.ts`:

```ts
// Output page order, output options and the merge job's state.
import { defineStore } from 'pinia'
import { computed, reactive, ref, watch } from 'vue'
import * as api from '../api/client'
import type { FileKind, Fit, JobEvent, MergePlan, MergeResult, OutputOptions } from '../api/types'
import { messageOf } from '../lib/messages'
import { moveItem, pageKey, reconcile, toSegments, type PageItem } from '../lib/segments'
import { useFilesStore } from './files'

export type MergeStatus = 'idle' | 'running' | 'done' | 'error'

export const usePlanStore = defineStore('plan', () => {
  const files = useFilesStore()

  const pages = ref<PageItem[]>([])
  const manualOrder = ref(false)
  const output = reactive<OutputOptions>({
    filename: 'merged.pdf',
    title: null,
    author: null,
    bookmarks: true,
    image_page_size: 'A4',
    image_fit: 'fit',
    image_margin_mm: 10,
  })
  const status = ref<MergeStatus>('idle')
  const progress = ref({ done: 0, total: 0 })
  const result = ref<MergeResult | null>(null)
  const error = ref<string | null>(null)
  let stopWatching: (() => void) | null = null

  /** Pages in source order, from each source's current selection and rotation. */
  function freshPages(): PageItem[] {
    return files.sources.flatMap((source) =>
      source.pages.map((page) => ({
        key: pageKey(source.info.file_id, page),
        fileId: source.info.file_id,
        page,
        rotate: source.rotate,
      })),
    )
  }

  watch(
    freshPages,
    (fresh) => {
      pages.value = manualOrder.value ? reconcile(pages.value, fresh) : fresh
    },
    { immediate: true },
  )

  const segments = computed(() =>
    toSegments(
      pages.value,
      new Map<string, Fit | null>(files.sources.map((s) => [s.info.file_id, s.fit])),
      new Map<string, FileKind>(files.sources.map((s) => [s.info.file_id, s.info.kind])),
    ),
  )
  const hasRangeErrors = computed(() => files.sources.some((s) => s.rangeError !== null))
  const canMerge = computed(() => pages.value.length > 0 && status.value !== 'running' && !hasRangeErrors.value)

  function movePage(from: number, to: number): void {
    if (from === to) return
    pages.value = moveItem(pages.value, from, to)
    manualOrder.value = true
  }

  function resetOrder(): void {
    manualOrder.value = false
    pages.value = freshPages()
  }

  function buildPlan(): MergePlan {
    return {
      segments: segments.value,
      output: {
        ...output,
        filename: output.filename.trim() || 'merged.pdf',
        title: output.title?.trim() || null,
        author: output.author?.trim() || null,
      },
    }
  }

  function onEvent(event: JobEvent): void {
    if (event.type === 'progress') {
      progress.value = { done: event.done, total: event.total }
    } else if (event.type === 'done') {
      result.value = {
        file_id: event.file_id,
        name: event.name,
        pages: event.pages,
        size: event.size,
        expires_at: event.expires_at,
        download_url: event.download_url,
      }
      status.value = 'done'
      stopWatching = null
    } else if (event.type === 'error') {
      error.value = event.message
      status.value = 'error'
      stopWatching = null
    }
  }

  async function merge(): Promise<void> {
    if (!canMerge.value) return
    stopWatching?.()
    status.value = 'running'
    error.value = null
    result.value = null
    progress.value = { done: 0, total: pages.value.length }
    try {
      const { job_id } = await api.startMerge(buildPlan())
      stopWatching = api.watchJob(job_id, onEvent)
    } catch (caught) {
      error.value = messageOf(caught)
      status.value = 'error'
    }
  }

  return {
    pages,
    manualOrder,
    output,
    status,
    progress,
    result,
    error,
    segments,
    hasRangeErrors,
    canMerge,
    movePage,
    resetOrder,
    buildPlan,
    merge,
  }
})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx vitest run src/stores/plan.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pdf_merger_web/src/stores/plan.ts pdf_merger_web/src/stores/plan.test.ts
git commit -m "feat(pdf_merger_web): add plan store with page order and merge state"
```

---

### Task 6: Drop zone and source list

**Files:**
- Create: `pdf_merger_web/src/components/DropZone.vue`, `SourceRow.vue`, `SourceList.vue`
- Test: `pdf_merger_web/src/components/SourceRow.test.ts`

**Interfaces:**
- Consumes: `useFilesStore`, `SourceState` (Task 4), `formatBytes`, `plural` (Task 3), `Fit` (Task 2).
- Produces: `<DropZone @files="(files: File[]) => …">`, `<SourceRow :source @range(text) @rotate @fit(Fit|null) @remove>`, `<SourceList>` (reads and writes the files store directly).

- [ ] **Step 1: Write the failing test**

`pdf_merger_web/src/components/SourceRow.test.ts`:

```ts
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import type { SourceState } from '../stores/files'
import SourceRow from './SourceRow.vue'

function source(overrides: Partial<SourceState> = {}, kind: 'pdf' | 'image' = 'pdf'): SourceState {
  return {
    info: { file_id: 'f_a', name: 'contract.pdf', kind, pages: 12, size: 2_400_000, expires_at: 0 },
    range: 'all',
    pages: [],
    rangeError: null,
    rotate: 0,
    fit: null,
    ...overrides,
  }
}

describe('SourceRow', () => {
  it('shows name, pages and size', () => {
    const wrapper = mount(SourceRow, { props: { source: source() } })

    expect(wrapper.text()).toContain('contract.pdf')
    expect(wrapper.text()).toContain('12 pages · 2.3 MB')
  })

  it('emits typed ranges', async () => {
    const wrapper = mount(SourceRow, { props: { source: source() } })

    await wrapper.get('input[aria-label="Pages"]').setValue('1-3,7')

    expect(wrapper.emitted('range')).toEqual([['1-3,7']])
  })

  it('shows a range error next to the input', () => {
    const wrapper = mount(SourceRow, { props: { source: source({ range: '99', rangeError: 'Pages go from 1 to 12' }) } })

    expect(wrapper.get('[role="alert"]').text()).toBe('Pages go from 1 to 12')
    expect(wrapper.get('input[aria-label="Pages"]').classes()).toContain('invalid')
  })

  it('shows a fit menu for images and emits null for the default', async () => {
    const wrapper = mount(SourceRow, { props: { source: source({}, 'image') } })
    const select = wrapper.get('select[aria-label="Image fit"]')

    await select.setValue('fill')
    await select.setValue('')

    expect(wrapper.find('input[aria-label="Pages"]').exists()).toBe(false)
    expect(wrapper.emitted('fit')).toEqual([['fill'], [null]])
  })

  it('emits rotate and remove', async () => {
    const wrapper = mount(SourceRow, { props: { source: source({ rotate: 90 }) } })

    await wrapper.get('button[aria-label="Rotate"]').trigger('click')
    await wrapper.get('button[aria-label="Remove"]').trigger('click')

    expect(wrapper.text()).toContain('rotated 90°')
    expect(wrapper.emitted('rotate')).toHaveLength(1)
    expect(wrapper.emitted('remove')).toHaveLength(1)
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run src/components/SourceRow.test.ts`
Expected: FAIL with `Failed to resolve import "./SourceRow.vue"`.

- [ ] **Step 3: Write the components**

`pdf_merger_web/src/components/DropZone.vue`:

```vue
<script setup lang="ts">
// Drop target and file picker. Type checks happen on the server (magic bytes),
// so `accept` here only narrows the picker.
import { ref } from 'vue'

const emit = defineEmits<{ files: [File[]] }>()
const over = ref(false)
const input = ref<HTMLInputElement | null>(null)

function onDrop(event: DragEvent): void {
  over.value = false
  const list = Array.from(event.dataTransfer?.files ?? [])
  if (list.length) emit('files', list)
}

function onPick(event: Event): void {
  const element = event.target as HTMLInputElement
  const list = Array.from(element.files ?? [])
  element.value = ''
  if (list.length) emit('files', list)
}
</script>

<template>
  <div
    class="dropzone"
    :class="{ over }"
    role="button"
    tabindex="0"
    aria-label="Add files"
    @click="input?.click()"
    @keydown.enter.prevent="input?.click()"
    @keydown.space.prevent="input?.click()"
    @dragover.prevent="over = true"
    @dragleave="over = false"
    @drop.prevent="onDrop"
  >
    <p class="dropzone-title">Drop PDFs or images here</p>
    <p class="muted small">PDF, JPG, PNG, WebP, TIFF, GIF or HEIC · up to 100 MB each · or click to choose</p>
    <input ref="input" type="file" multiple hidden accept=".pdf,image/*,.heic,.heif" @change="onPick" />
  </div>
</template>
```

`pdf_merger_web/src/components/SourceRow.vue`:

```vue
<script setup lang="ts">
// One uploaded file: page range (PDF) or fit (image), rotate, copy ID, remove.
import { ref } from 'vue'
import type { Fit } from '../api/types'
import { formatBytes, plural } from '../lib/format'
import type { SourceState } from '../stores/files'

const props = defineProps<{ source: SourceState }>()
const emit = defineEmits<{ range: [string]; rotate: []; fit: [Fit | null]; remove: [] }>()
const copied = ref(false)

async function copyId(): Promise<void> {
  try {
    await navigator.clipboard.writeText(props.source.info.file_id)
    copied.value = true
    setTimeout(() => (copied.value = false), 1500)
  } catch {
    // Clipboard blocked (non-secure context); the ID is still in the button title.
  }
}

function onRange(event: Event): void {
  emit('range', (event.target as HTMLInputElement).value)
}

function onFit(event: Event): void {
  const value = (event.target as HTMLSelectElement).value
  emit('fit', value === '' ? null : (value as Fit))
}
</script>

<template>
  <div class="source-row">
    <span class="handle" aria-hidden="true">⋮⋮</span>
    <span class="kind" :class="source.info.kind">{{ source.info.kind === 'pdf' ? 'PDF' : 'IMG' }}</span>
    <div class="meta">
      <div class="name" :title="source.info.name">{{ source.info.name }}</div>
      <div class="muted small">
        {{ plural(source.info.pages, 'page') }} · {{ formatBytes(source.info.size)
        }}<template v-if="source.rotate"> · rotated {{ source.rotate }}°</template>
      </div>
    </div>
    <div class="control">
      <template v-if="source.info.kind === 'pdf'">
        <input
          class="range"
          :class="{ invalid: source.rangeError }"
          :value="source.range"
          aria-label="Pages"
          placeholder="all"
          @input="onRange"
        />
        <div v-if="source.rangeError" class="error small" role="alert">{{ source.rangeError }}</div>
      </template>
      <select v-else aria-label="Image fit" :value="source.fit ?? ''" @change="onFit">
        <option value="">Default fit</option>
        <option value="fit">Fit page</option>
        <option value="fill">Fill page</option>
        <option value="original">Original size</option>
      </select>
    </div>
    <button type="button" class="icon" aria-label="Rotate" title="Rotate 90°" @click="emit('rotate')">⟳</button>
    <button
      type="button"
      class="icon"
      :aria-label="copied ? 'Copied' : 'Copy file ID'"
      :title="`Copy ID for chat: ${source.info.file_id}`"
      @click="copyId"
    >
      {{ copied ? '✓' : 'ID' }}
    </button>
    <button type="button" class="icon" aria-label="Remove" @click="emit('remove')">✕</button>
  </div>
</template>
```

Check: `formatBytes(2_400_000)` is `2.3 MB` (2.29 rounded to one decimal), matching the test.

`pdf_merger_web/src/components/SourceList.vue`:

```vue
<script setup lang="ts">
// Source files in default order; drag a row to reorder.
import { ref } from 'vue'
import { useFilesStore } from '../stores/files'
import SourceRow from './SourceRow.vue'

const files = useFilesStore()
const dragFrom = ref<number | null>(null)

function onDrop(index: number): void {
  if (dragFrom.value !== null) files.moveSource(dragFrom.value, index)
  dragFrom.value = null
}
</script>

<template>
  <section v-if="files.sources.length" class="panel">
    <h2>Source files</h2>
    <ol class="source-list">
      <li
        v-for="(source, index) in files.sources"
        :key="source.info.file_id"
        draggable="true"
        :class="{ dragging: dragFrom === index }"
        @dragstart="dragFrom = index"
        @dragend="dragFrom = null"
        @dragover.prevent
        @drop.prevent="onDrop(index)"
      >
        <SourceRow
          :source="source"
          @range="files.setRange(source.info.file_id, $event)"
          @rotate="files.rotate(source.info.file_id)"
          @fit="files.setFit(source.info.file_id, $event)"
          @remove="files.remove(source.info.file_id)"
        />
      </li>
    </ol>
  </section>
</template>
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx vitest run src/components/SourceRow.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pdf_merger_web/src/components/DropZone.vue pdf_merger_web/src/components/SourceRow.vue pdf_merger_web/src/components/SourceRow.test.ts pdf_merger_web/src/components/SourceList.vue
git commit -m "feat(pdf_merger_web): add drop zone and source list"
```

---

### Task 7: Thumbnails and page strip

**Files:**
- Create: `pdf_merger_web/src/lib/pdfThumbs.ts`, `src/components/PageThumb.vue`, `src/components/PageStrip.vue`
- Test: `pdf_merger_web/src/components/PageStrip.test.ts`

**Interfaces:**
- Consumes: `contentUrl` (Task 2), `PageItem` (Task 3), `useFilesStore` (Task 4), `usePlanStore` (Task 5).
- Produces: `renderPage(url: string, pageIndex: number, canvas: HTMLCanvasElement, cssWidth: number): Promise<void>`, `forgetDocument(url: string): void`; `<PageThumb :item :kind :label>`; `<PageStrip>`.

pdf.js loads lazily on the first thumbnail. Each document is fetched once and cached; at most 2 pages render at a time. A thumbnail renders only when it scrolls within 200 px of view.

- [ ] **Step 1: Write the failing test**

`pdf_merger_web/src/components/PageStrip.test.ts`:

```ts
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { describe, expect, it, vi } from 'vitest'
import { nextTick } from 'vue'
import { useFilesStore } from '../stores/files'
import { usePlanStore } from '../stores/plan'
import PageStrip from './PageStrip.vue'

vi.mock('../api/client')
vi.mock('../lib/pdfThumbs', () => ({ renderPage: vi.fn().mockResolvedValue(undefined), forgetDocument: vi.fn() }))

describe('PageStrip', () => {
  it('labels pages and reorders by drag and drop', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const files = useFilesStore()
    const plan = usePlanStore()
    files.add({ file_id: 'f_a', name: 'contract.pdf', kind: 'pdf', pages: 2, size: 1, expires_at: 0 })
    files.add({ file_id: 'f_b', name: 'receipt.jpg', kind: 'image', pages: 1, size: 1, expires_at: 0 })
    await nextTick()

    const wrapper = mount(PageStrip, { global: { plugins: [pinia] } })
    const items = wrapper.findAll('li')
    expect(items.map((li) => li.text())).toEqual(['contract p1', 'contract p2', 'receipt'])

    await items[2]!.trigger('dragstart')
    await items[0]!.trigger('drop')

    expect(plan.pages.map((p) => p.key)).toEqual(['f_b:0', 'f_a:0', 'f_a:1'])
    expect(wrapper.text()).toContain('Reset order')
  })

  it('renders nothing without pages', () => {
    const pinia = createPinia()
    setActivePinia(pinia)

    const wrapper = mount(PageStrip, { global: { plugins: [pinia] } })

    expect(wrapper.find('section').exists()).toBe(false)
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run src/components/PageStrip.test.ts`
Expected: FAIL with `Failed to resolve import "./PageStrip.vue"`.

- [ ] **Step 3: Write the implementation**

`pdf_merger_web/src/lib/pdfThumbs.ts`:

```ts
// Lazy pdf.js thumbnails. The library and its worker load on first use; each
// document is fetched once; at most MAX_ACTIVE pages render at the same time.
import type { PDFDocumentProxy } from 'pdfjs-dist'

type PdfJs = typeof import('pdfjs-dist')

const MAX_ACTIVE = 2
let library: Promise<PdfJs> | null = null
const documents = new Map<string, Promise<PDFDocumentProxy>>()
let active = 0
const waiting: Array<() => void> = []

function loadLibrary(): Promise<PdfJs> {
  library ??= Promise.all([import('pdfjs-dist'), import('pdfjs-dist/build/pdf.worker.min.mjs?url')]).then(
    ([pdfjs, worker]) => {
      pdfjs.GlobalWorkerOptions.workerSrc = worker.default
      return pdfjs
    },
  )
  return library
}

function loadDocument(url: string): Promise<PDFDocumentProxy> {
  let document = documents.get(url)
  if (!document) {
    document = loadLibrary().then((pdfjs) => pdfjs.getDocument({ url }).promise)
    documents.set(url, document)
    document.catch(() => documents.delete(url))
  }
  return document
}

async function withSlot<T>(work: () => Promise<T>): Promise<T> {
  if (active >= MAX_ACTIVE) await new Promise<void>((resolve) => waiting.push(resolve))
  active++
  try {
    return await work()
  } finally {
    active--
    waiting.shift()?.()
  }
}

/** Draw one page (0-based) into `canvas`, `cssWidth` CSS pixels wide, sharp on HiDPI screens. */
export function renderPage(url: string, pageIndex: number, canvas: HTMLCanvasElement, cssWidth: number): Promise<void> {
  return withSlot(async () => {
    const document = await loadDocument(url)
    const page = await document.getPage(pageIndex + 1)
    const base = page.getViewport({ scale: 1 })
    const viewport = page.getViewport({ scale: (cssWidth * window.devicePixelRatio) / base.width })
    canvas.width = Math.round(viewport.width)
    canvas.height = Math.round(viewport.height)
    await page.render({ canvas, viewport }).promise
    page.cleanup()
  })
}

/** Drop a cached document, e.g. after its file is removed. */
export function forgetDocument(url: string): void {
  void documents.get(url)?.then((document) => document.destroy())
  documents.delete(url)
}
```

If `vue-tsc` rejects `page.render({ canvas, viewport })` because the installed pdfjs-dist types still require `canvasContext`, use `page.render({ canvas, canvasContext: canvas.getContext('2d')!, viewport })`.

`pdf_merger_web/src/components/PageThumb.vue`:

```vue
<script setup lang="ts">
// One page preview. PDFs render to a canvas through pdf.js, images use <img>.
// Nothing loads until the thumbnail is near the viewport.
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { contentUrl } from '../api/client'
import type { FileKind } from '../api/types'
import { renderPage } from '../lib/pdfThumbs'
import type { PageItem } from '../lib/segments'

const props = defineProps<{ item: PageItem; kind: FileKind; label: string }>()
const THUMB_WIDTH = 96
const root = ref<HTMLElement | null>(null)
const canvas = ref<HTMLCanvasElement | null>(null)
const visible = ref(false)
const failed = ref(false)
let observer: IntersectionObserver | null = null

async function show(): Promise<void> {
  visible.value = true
  if (props.kind !== 'pdf' || !canvas.value) return
  try {
    await renderPage(contentUrl(props.item.fileId), props.item.page, canvas.value, THUMB_WIDTH)
  } catch {
    failed.value = true
  }
}

onMounted(() => {
  if (!root.value) return
  if (typeof IntersectionObserver === 'undefined') {
    void show()
    return
  }
  observer = new IntersectionObserver(
    (entries) => {
      if (entries.some((entry) => entry.isIntersecting)) {
        observer?.disconnect()
        void show()
      }
    },
    { rootMargin: '200px' },
  )
  observer.observe(root.value)
})

onBeforeUnmount(() => observer?.disconnect())
</script>

<template>
  <figure ref="root" class="thumb">
    <div class="paper" :style="{ transform: `rotate(${item.rotate}deg)` }">
      <canvas v-if="kind === 'pdf' && !failed" ref="canvas" />
      <img v-else-if="kind === 'image' && visible" :src="contentUrl(item.fileId)" alt="" />
      <span v-else-if="failed" class="muted small">No preview</span>
    </div>
    <figcaption class="small">{{ label }}</figcaption>
  </figure>
</template>
```

`pdf_merger_web/src/components/PageStrip.vue`:

```vue
<script setup lang="ts">
// Every output page in order. Dragging a page switches the plan to manual order.
import { computed, ref } from 'vue'
import { plural } from '../lib/format'
import { useFilesStore } from '../stores/files'
import { usePlanStore } from '../stores/plan'
import PageThumb from './PageThumb.vue'

const files = useFilesStore()
const plan = usePlanStore()
const dragFrom = ref<number | null>(null)
const infoById = computed(() => new Map(files.sources.map((s) => [s.info.file_id, s.info])))

function label(fileId: string, page: number): string {
  const info = infoById.value.get(fileId)
  if (!info) return ''
  const name = info.name.replace(/\.[^.]+$/, '')
  return info.kind === 'image' ? name : `${name} p${page + 1}`
}

function onDrop(index: number): void {
  if (dragFrom.value !== null) plan.movePage(dragFrom.value, index)
  dragFrom.value = null
}
</script>

<template>
  <section v-if="plan.pages.length" class="panel">
    <div class="panel-head">
      <h2>Pages <span class="muted small">drag to reorder</span></h2>
      <span class="muted small">{{ plural(plan.pages.length, 'page') }}</span>
      <button v-if="plan.manualOrder" type="button" class="link" @click="plan.resetOrder()">Reset order</button>
    </div>
    <ol class="strip">
      <li
        v-for="(item, index) in plan.pages"
        :key="item.key"
        draggable="true"
        :class="{ dragging: dragFrom === index }"
        @dragstart="dragFrom = index"
        @dragend="dragFrom = null"
        @dragover.prevent
        @drop.prevent="onDrop(index)"
      >
        <PageThumb :item="item" :kind="infoById.get(item.fileId)?.kind ?? 'pdf'" :label="label(item.fileId, item.page)" />
      </li>
    </ol>
  </section>
</template>
```

In the test, `trigger('dragstart')` then `trigger('drop')` drives the same handlers a real drag does. The `<li>` text equals the label because the thumbnail body has no text in jsdom (canvas renders nothing).

- [ ] **Step 4: Run tests and type-check**

Run: `npx vitest run src/components/PageStrip.test.ts`
Expected: PASS.
Run: `npm run build`
Expected: build succeeds (this is where pdf.js types are checked).

- [ ] **Step 5: Commit**

```bash
git add pdf_merger_web/src/lib/pdfThumbs.ts pdf_merger_web/src/components/PageThumb.vue pdf_merger_web/src/components/PageStrip.vue pdf_merger_web/src/components/PageStrip.test.ts
git commit -m "feat(pdf_merger_web): add lazy pdf.js thumbnails and draggable page strip"
```

---

### Task 8: Output panel and merge bar

**Files:**
- Create: `pdf_merger_web/src/components/OutputPanel.vue`, `src/components/MergeBar.vue`
- Test: `pdf_merger_web/src/components/MergeBar.test.ts`

**Interfaces:**
- Consumes: `usePlanStore` (Task 5), `formatBytes`, `plural` (Task 3).
- Produces: `<OutputPanel>` (binds `plan.output`), `<MergeBar>` (summary, progress, result link with a same-origin `href`, copy ID, errors, merge button).

- [ ] **Step 1: Write the failing test**

`pdf_merger_web/src/components/MergeBar.test.ts`:

```ts
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { nextTick } from 'vue'
import * as api from '../api/client'
import { ApiError, type JobEvent } from '../api/types'
import { useFilesStore } from '../stores/files'
import MergeBar from './MergeBar.vue'

vi.mock('../api/client')

async function setup() {
  const pinia = createPinia()
  setActivePinia(pinia)
  const files = useFilesStore()
  files.add({ file_id: 'f_a', name: 'a.pdf', kind: 'pdf', pages: 2, size: 1, expires_at: 0 })
  await nextTick()
  return { files, wrapper: mount(MergeBar, { global: { plugins: [pinia] } }) }
}

describe('MergeBar', () => {
  beforeEach(() => vi.mocked(api.startMerge).mockResolvedValue({ job_id: 'j_1' }))

  it('summarizes the plan', async () => {
    const { wrapper } = await setup()

    expect(wrapper.text()).toContain('Ready to merge 2 pages from 1 file')
  })

  it('shows a same-origin download link when done', async () => {
    vi.mocked(api.watchJob).mockImplementation((_jobId: string, onEvent: (event: JobEvent) => void) => {
      onEvent({
        type: 'done',
        file_id: 'f_r',
        name: 'merged.pdf',
        pages: 2,
        size: 2048,
        expires_at: 0,
        download_url: 'http://127.0.0.1:8040/api/files/f_r/download?exp=1&sig=ab',
      })
      return () => {}
    })
    const { wrapper } = await setup()

    await wrapper.get('button.primary').trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('Done · merged.pdf (2 KB)')
    expect(wrapper.get('a').attributes('href')).toBe('/api/files/f_r/download?exp=1&sig=ab')
  })

  it('shows server errors', async () => {
    vi.mocked(api.startMerge).mockRejectedValue(new ApiError('limit_exceeded', 'Too many pages.', 413))
    const { wrapper } = await setup()

    await wrapper.get('button.primary').trigger('click')
    await flushPromises()

    expect(wrapper.get('[role="alert"]').text()).toBe('Too many pages.')
  })

  it('explains why merge is blocked by a bad range', async () => {
    const { files, wrapper } = await setup()

    files.setRange('f_a', '9')
    await nextTick()

    expect(wrapper.text()).toContain('Fix the page ranges marked in red')
    expect(wrapper.get('button.primary').attributes('disabled')).toBeDefined()
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run src/components/MergeBar.test.ts`
Expected: FAIL with `Failed to resolve import "./MergeBar.vue"`.

- [ ] **Step 3: Write the components**

`pdf_merger_web/src/components/OutputPanel.vue`:

```vue
<script setup lang="ts">
// Output file name, metadata and image defaults.
import { usePlanStore } from '../stores/plan'

const plan = usePlanStore()
</script>

<template>
  <section class="panel">
    <h2>Output</h2>
    <div class="grid">
      <label>File name<input v-model="plan.output.filename" placeholder="merged.pdf" /></label>
      <label>Title<input v-model="plan.output.title" placeholder="Contract package" /></label>
      <label>Author<input v-model="plan.output.author" placeholder="Jane Cruz" /></label>
      <label
        >Image page size
        <select v-model="plan.output.image_page_size">
          <option value="A4">A4</option>
          <option value="Letter">Letter</option>
          <option value="match">Match image</option>
        </select>
      </label>
      <label
        >Image fit
        <select v-model="plan.output.image_fit">
          <option value="fit">Fit page</option>
          <option value="fill">Fill page</option>
          <option value="original">Original size</option>
        </select>
      </label>
      <label
        >Image margin (mm)
        <input v-model.number="plan.output.image_margin_mm" type="number" min="0" max="50" step="1" />
      </label>
      <label class="check"><input v-model="plan.output.bookmarks" type="checkbox" /> Bookmark each source</label>
    </div>
  </section>
</template>
```

`pdf_merger_web/src/components/MergeBar.vue`:

```vue
<script setup lang="ts">
// Merge summary, progress, result and the merge button.
import { computed, ref } from 'vue'
import { formatBytes, plural } from '../lib/format'
import { usePlanStore } from '../stores/plan'

const plan = usePlanStore()
const copied = ref(false)

const summary = computed(() => {
  const fileCount = new Set(plan.pages.map((p) => p.fileId)).size
  return `${plural(plan.pages.length, 'page')} from ${plural(fileCount, 'file')}`
})
const percent = computed(() =>
  plan.progress.total ? Math.round((plan.progress.done / plan.progress.total) * 100) : 0,
)
// The server's link is absolute (public_base_url); keep only path + query so it
// goes through this app's /api proxy, whatever host the browser used.
const downloadHref = computed(() => {
  if (!plan.result) return ''
  const url = new URL(plan.result.download_url, window.location.href)
  return `${url.pathname}${url.search}`
})

async function copyId(): Promise<void> {
  if (!plan.result) return
  try {
    await navigator.clipboard.writeText(plan.result.file_id)
    copied.value = true
    setTimeout(() => (copied.value = false), 1500)
  } catch {
    // Clipboard blocked; the ID is shown in the button title.
  }
}
</script>

<template>
  <div class="merge-bar">
    <div class="status" aria-live="polite">
      <template v-if="plan.status === 'running'">
        Merging… {{ plan.progress.done }} of {{ plan.progress.total }} pages
        <progress :value="percent" max="100" />
      </template>
      <template v-else-if="plan.status === 'done' && plan.result">
        Done · {{ plan.result.name }} ({{ formatBytes(plan.result.size) }})
        <a :href="downloadHref" download>Download</a>
        <button type="button" class="link" :title="plan.result.file_id" @click="copyId">
          {{ copied ? 'Copied' : 'Copy ID' }}
        </button>
      </template>
      <span v-else-if="plan.status === 'error'" class="error" role="alert">{{ plan.error }}</span>
      <span v-else-if="plan.hasRangeErrors" class="error">Fix the page ranges marked in red, then merge.</span>
      <template v-else-if="plan.pages.length">Ready to merge {{ summary }}</template>
      <template v-else>Add files to start</template>
    </div>
    <button type="button" class="primary" :disabled="!plan.canMerge" @click="plan.merge()">
      {{ plan.status === 'running' ? 'Merging…' : 'Merge' }}
    </button>
  </div>
</template>
```

Note: after an error, `plan.status` stays `error` until the next merge; the range-error hint shows only when there is no merge error on screen.

- [ ] **Step 4: Run test to verify it passes**

Run: `npx vitest run src/components/MergeBar.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pdf_merger_web/src/components/OutputPanel.vue pdf_merger_web/src/components/MergeBar.vue pdf_merger_web/src/components/MergeBar.test.ts
git commit -m "feat(pdf_merger_web): add output panel and merge bar"
```

---

### Task 9: App shell, styles, README and a browser check

**Files:**
- Replace: `pdf_merger_web/src/App.vue`, `pdf_merger_web/src/style.css`
- Create: `pdf_merger_web/README.md`

**Interfaces:**
- Consumes: every component and store above.

- [ ] **Step 1: Write the app shell**

`pdf_merger_web/src/App.vue`:

```vue
<script setup lang="ts">
import { onMounted } from 'vue'
import DropZone from './components/DropZone.vue'
import MergeBar from './components/MergeBar.vue'
import OutputPanel from './components/OutputPanel.vue'
import PageStrip from './components/PageStrip.vue'
import SourceList from './components/SourceList.vue'
import { useFilesStore } from './stores/files'
import { usePlanStore } from './stores/plan'

const files = useFilesStore()
usePlanStore() // created here so its page watcher runs from the start

onMounted(() => {
  void files.restore()
})
</script>

<template>
  <main class="app">
    <header class="app-head">
      <h1>PDF merger</h1>
      <span class="muted small">Files are kept for 6 hours</span>
    </header>
    <DropZone @files="files.upload($event)" />
    <p v-if="files.uploading" class="muted small" aria-live="polite">Uploading {{ files.uploading }} file(s)…</p>
    <ul v-if="files.errors.length" class="errors">
      <li v-for="(message, index) in files.errors" :key="index" role="alert">
        {{ message }}
        <button type="button" class="link" @click="files.dismissError(index)">Dismiss</button>
      </li>
    </ul>
    <SourceList />
    <PageStrip />
    <OutputPanel />
    <MergeBar />
  </main>
</template>
```

- [ ] **Step 2: Write the styles**

`pdf_merger_web/src/style.css`:

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

.app { max-width: 920px; margin: 0 auto; padding: 24px 16px 96px; display: grid; gap: 16px; }
.app-head { display: flex; justify-content: space-between; align-items: baseline; }

.panel { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 12px; }
.panel-head { display: flex; align-items: baseline; gap: 12px; }
.panel-head h2 { flex: 1; }

button { font: inherit; color: inherit; background: transparent; border: 1px solid var(--border); border-radius: var(--radius); padding: 6px 10px; cursor: pointer; }
button:hover:not(:disabled) { border-color: var(--muted); }
button:disabled { opacity: 0.5; cursor: not-allowed; }
button.primary { background: var(--accent); color: var(--on-accent); border-color: var(--accent); padding: 8px 18px; }
button.link { border: none; padding: 0 4px; color: var(--accent); }
button.icon { min-width: 34px; }
input, select { font: inherit; color: inherit; background: var(--bg); border: 1px solid var(--border); border-radius: var(--radius); padding: 6px 8px; }
input.invalid { border-color: var(--danger); }

.dropzone { border: 1.5px dashed var(--muted); border-radius: 12px; background: var(--surface); padding: 24px; text-align: center; cursor: pointer; }
.dropzone.over { border-color: var(--accent); }
.dropzone-title { margin: 0 0 4px; font-size: 15px; }
.dropzone p:last-of-type { margin: 0; }

.source-list, .strip, .errors { list-style: none; margin: 0; padding: 0; }
.source-list li + li { border-top: 1px solid var(--border); }
.source-list li.dragging, .strip li.dragging { opacity: 0.4; }
.source-row { display: flex; align-items: center; gap: 10px; padding: 8px 4px; }
.handle { color: var(--muted); cursor: grab; }
.kind { font-size: 11px; font-weight: 600; padding: 2px 6px; border-radius: 4px; }
.kind.pdf { color: var(--danger); border: 1px solid var(--danger); }
.kind.image { color: var(--accent); border: 1px solid var(--accent); }
.meta { flex: 1; min-width: 0; }
.name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.control { width: 130px; }
.control input, .control select { width: 100%; box-sizing: border-box; }

.strip { display: flex; flex-wrap: wrap; gap: 10px; }
.strip li { cursor: grab; }
.thumb { margin: 0; width: 96px; text-align: center; }
.paper { width: 96px; height: 128px; display: flex; align-items: center; justify-content: center; background: #ffffff; border: 1px solid var(--border); border-radius: 4px; overflow: hidden; transition: transform 0.15s; }
.paper canvas, .paper img { max-width: 100%; max-height: 100%; }
.thumb figcaption { margin-top: 4px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; }
.grid label { display: grid; gap: 4px; font-size: 12px; color: var(--muted); }
.grid label.check { display: flex; align-items: center; gap: 8px; color: var(--text); font-size: 13px; }

.merge-bar { position: sticky; bottom: 0; display: flex; align-items: center; gap: 12px; padding: 12px; background: var(--surface); border: 1px solid var(--border); border-radius: 12px; }
.merge-bar .status { flex: 1; font-size: 13px; display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.merge-bar a { color: var(--accent); }

@media (max-width: 600px) {
  .source-row { flex-wrap: wrap; }
  .control { width: 100%; order: 5; }
}
```

- [ ] **Step 3: Write the README**

`pdf_merger_web/README.md`:

````markdown
# pdf_merger_web

Web app for `pdf_merger`: upload PDFs and images, pick page ranges, reorder pages with thumbnails, set output options, merge and download.

Design: `../docs/superpowers/specs/2026-10-02-pdf-merger-design.md`.

## Run

Start `pdf_merger` first (port 8040), then:

```
run.bat
```

Opens on http://127.0.0.1:5174 (`PDF_MERGER_WEB_PORT`). `/api` is proxied to `PDF_MERGER_API_URL` (default `http://127.0.0.1:8040`), so the session cookie stays same-origin.

## Using a file in chat

Each file row and the merge result have a "Copy ID" button. Paste the ID into an Ember chat and ask the agent to merge it; the agent uses the `tool_pdf_*` tools through `mcp_server`.

## Tests

```
npm test
npm run build
```
````

- [ ] **Step 4: Run all tests and build**

Run: `npm test`
Expected: PASS (all test files).
Run: `npm run build`
Expected: build succeeds.

- [ ] **Step 5: Browser check (needs plan 1 running)**

1. Start `pdf_merger/run.bat`, then `pdf_merger_web/run.bat`.
2. Open http://127.0.0.1:5174.
3. Drop two PDFs and one JPG. Expected: three rows in drop order; thumbnails appear in the page strip.
4. Type `1-2` in the first PDF's range. Expected: the strip drops its other pages. Type `99`. Expected: red border, message under the input, Merge disabled with "Fix the page ranges marked in red".
5. Fix the range, drag the image thumbnail to the front. Expected: "Reset order" appears.
6. Rotate the second PDF. Expected: its thumbnails turn 90°.
7. Set title "Test", press Merge. Expected: progress, then "Done · merged.pdf" with a Download link that downloads a PDF with the image first, the rotation applied and bookmarks per source.
8. Reload the page. Expected: uploaded files and the result come back (restored from the session).
9. Drop a `.txt` file. Expected: an error line "notes.txt: This file type isn't supported…" with Dismiss.

Record anything that does not match in the commit message or as a follow-up.

- [ ] **Step 6: Commit**

```bash
git add pdf_merger_web/src/App.vue pdf_merger_web/src/style.css pdf_merger_web/README.md
git commit -m "feat(pdf_merger_web): assemble the merge screen with styles and README"
```

---

## Self-review notes

- Spec coverage: drop zone and accepted types (Task 6), source rows with range, fit, rotate, copy ID, remove (6), page strip with lazy thumbnails and drag reorder (7), output panel (8), merge bar with SSE progress, download and copy ID (8), "range edit keeps manual order" (3, 5), tests listed in the spec (`segments.ts`, plan store, `SourceRow`, `MergeBar`) plus client, files store and page strip.
- Types used across tasks: `SourceState`, `PageItem`, `JobEvent`, `MergeResult`, `OutputOptions` are defined once (Tasks 2–4) and imported everywhere else.
