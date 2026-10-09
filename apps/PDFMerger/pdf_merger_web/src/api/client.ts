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
