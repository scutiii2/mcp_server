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
