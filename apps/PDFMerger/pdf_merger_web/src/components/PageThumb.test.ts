import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import type { PageItem } from '../lib/segments'
import PageThumb from './PageThumb.vue'

vi.mock('../api/client', () => ({ contentUrl: (id: string) => `/api/files/${id}/content` }))
vi.mock('../lib/pdfThumbs', () => ({ renderPage: vi.fn() }))

describe('PageThumb', () => {
  it('shows "No preview" when an image cannot be decoded by the browser', async () => {
    const item: PageItem = { key: 'f_a:0', fileId: 'f_a', page: 0, rotate: 0 }
    const wrapper = mount(PageThumb, { props: { item, kind: 'image', label: 'scan' } })
    await wrapper.vm.$nextTick()

    await wrapper.get('img').trigger('error')

    expect(wrapper.find('img').exists()).toBe(false)
    expect(wrapper.text()).toContain('No preview')
  })
})
