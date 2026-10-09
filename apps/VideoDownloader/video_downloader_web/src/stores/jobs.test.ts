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
