import { beforeEach, describe, expect, it, vi } from 'vitest'

let current = 0
let peak = 0
let releases: Array<() => void> = []

vi.mock('pdfjs-dist/build/pdf.worker.min.mjs?url', () => ({ default: 'worker.js' }))
vi.mock('pdfjs-dist', () => {
  const page = {
    getViewport: () => ({ width: 100, height: 140 }),
    render: () => {
      current++
      peak = Math.max(peak, current)
      return {
        promise: new Promise<void>((resolve) => {
          releases.push(() => {
            current--
            resolve()
          })
        }),
      }
    },
    cleanup: vi.fn(),
  }
  const doc = { getPage: () => Promise.resolve(page), destroy: vi.fn() }
  return { GlobalWorkerOptions: {}, getDocument: () => ({ promise: Promise.resolve(doc) }) }
})

import { renderPage } from './pdfThumbs'

async function ticks(count: number, each?: () => void): Promise<void> {
  for (let i = 0; i < count; i++) {
    await Promise.resolve()
    each?.()
  }
}

describe('renderPage', () => {
  beforeEach(() => {
    current = 0
    peak = 0
    releases = []
  })

  it('never runs more than two renders at once', async () => {
    const canvas = document.createElement('canvas')
    const all: Array<Promise<void>> = []
    for (let i = 0; i < 5; i++) all.push(renderPage('/doc', i, canvas, 96))

    // Release in interleaved order; fire extra calls on every microtask tick
    // so a caller lands between a slot being freed and the waiter taking it.
    let guard = 0
    while (all.length > 0 && guard++ < 200) {
      await vi.waitFor(() => expect(releases.length).toBeGreaterThan(0))
      releases.pop()!()
      await ticks(8, () => all.push(renderPage('/doc', 9, canvas, 96)))
      if (guard > 6) break
    }
    while (releases.length || current > 0) {
      releases.pop()?.()
      await ticks(8)
    }
    await Promise.all(all)

    expect(peak).toBeLessThanOrEqual(2)
  })
})
