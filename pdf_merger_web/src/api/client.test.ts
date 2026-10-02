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
