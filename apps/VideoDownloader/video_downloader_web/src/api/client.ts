// Thin typed wrapper over video_downloader's REST API. Every path is relative
// (/api/...) so requests go through the Vite proxy with the session cookie.
import { ApiError, type FileInfo, type JobEvent, type JobStatus, type ProbeResult } from './types'

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

export function getJobStatus(jobId: string): Promise<JobStatus> {
  return fetch(`${BASE}/jobs/${encodeURIComponent(jobId)}`).then((r) => parse<JobStatus>(r))
}

const POLL_INTERVAL_MS = 2000
const POLL_ATTEMPTS = 10

/** The event a status snapshot stands for; null while it is only queued. */
function eventOf(status: JobStatus): JobEvent | null {
  switch (status.state) {
    case 'done':
      return status.file
        ? { type: 'done', file_id: status.file.file_id, file: relative(status.file) }
        : { type: 'error', code: 'file_not_found', message: 'The download finished, but the file is no longer available.' }
    case 'error':
      return { type: 'error', code: status.error?.code ?? 'http_error', message: status.error?.message ?? 'The download failed.' }
    case 'downloading':
      return { type: 'progress', percent: status.percent, speed: status.speed, eta: status.eta }
    case 'processing':
      return { type: 'processing' }
    default:
      return null
  }
}

/**
 * Follow a download job over SSE. Returns a function that stops listening.
 *
 * If the stream drops, the job is polled (GET /api/jobs/{id}) every 2 s, up to 10 times,
 * and connection_lost is reported only if the server no longer knows the job or it is
 * still running after the last try.
 */
export function watchJob(jobId: string, onEvent: (event: JobEvent) => void): () => void {
  const source = new EventSource(`${BASE}/jobs/${encodeURIComponent(jobId)}/events`)
  let finished = false
  let polling = false
  let timer: ReturnType<typeof setTimeout> | undefined
  const finish = (): void => {
    finished = true
    source.close()
    if (timer !== undefined) clearTimeout(timer)
  }
  const lost = (): void => {
    finish()
    onEvent({ type: 'error', code: 'connection_lost', message: 'Lost the connection to the server. Check your downloads list, then try again.' })
  }
  const poll = (attempt: number): void => {
    timer = setTimeout(async () => {
      timer = undefined
      let status: JobStatus
      try {
        status = await getJobStatus(jobId)
      } catch (error) {
        if (finished) return
        const definite = error instanceof ApiError && error.status < 500 // e.g. 404: the job is gone
        if (definite || attempt + 1 >= POLL_ATTEMPTS) lost()
        else poll(attempt + 1)
        return
      }
      if (finished) return
      const event = eventOf(status)
      if (event) onEvent(event)
      if (event?.type === 'done' || event?.type === 'error') finish()
      else if (attempt + 1 >= POLL_ATTEMPTS) lost()
      else poll(attempt + 1)
    }, POLL_INTERVAL_MS)
  }
  source.onmessage = (message: MessageEvent<string>) => {
    let event = JSON.parse(message.data) as JobEvent
    if (event.type === 'done') event = { ...event, file: relative(event.file) }
    onEvent(event)
    if (event.type === 'done' || event.type === 'error') finish()
  }
  source.onerror = () => {
    if (finished || polling) return
    polling = true
    source.close() // EventSource would reconnect and replay every event; a status poll is enough
    poll(0)
  }
  return finish
}
