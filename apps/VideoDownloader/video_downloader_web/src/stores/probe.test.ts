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
