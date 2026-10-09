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
