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
  beforeEach(() => {
    vi.mocked(api.startMerge).mockResolvedValue({ job_id: 'j_1' })
  })

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
