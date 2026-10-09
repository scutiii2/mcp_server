import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cancelJob, deleteFile, getJobStatus, listFiles, probe, startDownload, watchJob } from './client'
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

  it('getJobStatus fetches the job snapshot', async () => {
    fetchMock.mockResolvedValue(json({ job_id: 'j_1', state: 'queued', percent: null, speed: null, eta: null, file: null, error: null }))
    expect((await getJobStatus('j_1')).state).toBe('queued')
    expect(fetchMock.mock.calls[0][0]).toBe('/api/jobs/j_1')
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
  url: string
  constructor(url: string) {
    this.url = url
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

  it('returns a stop function', () => {
    const stop = watchJob('j_1', () => {})
    stop()
    expect(FakeEventSource.last.closed).toBe(true)
  })
})

describe('watchJob after the stream drops', () => {
  const fetchMock = vi.fn()
  const FILE = { file_id: 'f_1', name: 'a.mp4', kind: 'video' as const, mime: 'video/mp4', size: 1, duration: null, expires_at: 9, download_url: 'http://10.0.0.5:8050/api/files/f_1/download?exp=1&sig=s' }
  const status = (over: Record<string, unknown>) => json({ job_id: 'j_1', state: 'downloading', percent: 40, speed: null, eta: null, file: null, error: null, ...over })

  beforeEach(() => {
    vi.useFakeTimers()
    vi.stubGlobal('EventSource', FakeEventSource)
    vi.stubGlobal('fetch', fetchMock)
  })
  afterEach(() => {
    vi.useRealTimers()
    fetchMock.mockReset()
  })

  it('polls the job instead of failing, and delivers done', async () => {
    fetchMock.mockResolvedValueOnce(status({})).mockResolvedValueOnce(status({ state: 'done', percent: 100, file: FILE }))
    const seen: JobEvent[] = []
    watchJob('j_1', (e) => seen.push(e))
    FakeEventSource.last.onerror?.()
    FakeEventSource.last.onerror?.() // a second error event changes nothing
    expect(FakeEventSource.last.closed).toBe(true)
    expect(seen).toEqual([])
    await vi.advanceTimersByTimeAsync(2000)
    expect(fetchMock.mock.calls[0][0]).toBe('/api/jobs/j_1')
    expect(seen).toEqual([{ type: 'progress', percent: 40, speed: null, eta: null }])
    await vi.advanceTimersByTimeAsync(2000)
    expect(seen[1]).toMatchObject({ type: 'done', file_id: 'f_1', file: { download_url: '/api/files/f_1/download?exp=1&sig=s' } })
    await vi.advanceTimersByTimeAsync(10_000)
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('delivers an error the job ended with', async () => {
    fetchMock.mockResolvedValue(status({ state: 'error', error: { code: 'too_large', message: 'Big.' } }))
    const seen: JobEvent[] = []
    watchJob('j_1', (e) => seen.push(e))
    FakeEventSource.last.onerror?.()
    await vi.advanceTimersByTimeAsync(2000)
    expect(seen).toEqual([{ type: 'error', code: 'too_large', message: 'Big.' }])
  })

  it('reports connection_lost once if the job is still running after the retries', async () => {
    fetchMock.mockImplementation(() => Promise.resolve(status({ state: 'queued' })))
    const seen: JobEvent[] = []
    watchJob('j_1', (e) => seen.push(e))
    FakeEventSource.last.onerror?.()
    await vi.advanceTimersByTimeAsync(60_000)
    expect(fetchMock).toHaveBeenCalledTimes(10)
    expect(seen).toEqual([{ type: 'error', code: 'connection_lost', message: expect.any(String) }])
  })

  it('keeps retrying through network errors, then reports connection_lost', async () => {
    fetchMock.mockImplementation(() => Promise.reject(new TypeError('offline')))
    const seen: JobEvent[] = []
    watchJob('j_1', (e) => seen.push(e))
    FakeEventSource.last.onerror?.()
    await vi.advanceTimersByTimeAsync(60_000)
    expect(fetchMock).toHaveBeenCalledTimes(10)
    expect(seen.map((e) => (e.type === 'error' ? e.code : e.type))).toEqual(['connection_lost'])
  })

  it('reports connection_lost at once when the server no longer knows the job', async () => {
    fetchMock.mockResolvedValue(json({ error: { code: 'job_not_found', message: 'Gone.' } }, 404))
    const seen: JobEvent[] = []
    watchJob('j_1', (e) => seen.push(e))
    FakeEventSource.last.onerror?.()
    await vi.advanceTimersByTimeAsync(2000)
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(seen).toEqual([{ type: 'error', code: 'connection_lost', message: expect.any(String) }])
  })

  it('stop() ends the polling', async () => {
    fetchMock.mockImplementation(() => Promise.resolve(status({})))
    const seen: JobEvent[] = []
    const stop = watchJob('j_1', (e) => seen.push(e))
    FakeEventSource.last.onerror?.()
    stop()
    await vi.advanceTimersByTimeAsync(60_000)
    expect(fetchMock).not.toHaveBeenCalled()
    expect(seen).toEqual([])
  })
})
