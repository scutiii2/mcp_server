import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { describe, expect, it, vi } from 'vitest'
import { nextTick } from 'vue'
import { useFilesStore } from '../stores/files'
import { usePlanStore } from '../stores/plan'
import PageStrip from './PageStrip.vue'

vi.mock('../api/client')
vi.mock('../lib/pdfThumbs', () => ({ renderPage: vi.fn().mockResolvedValue(undefined), forgetDocument: vi.fn() }))

describe('PageStrip', () => {
  it('labels pages and reorders by drag and drop', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const files = useFilesStore()
    const plan = usePlanStore()
    files.add({ file_id: 'f_a', name: 'contract.pdf', kind: 'pdf', pages: 2, size: 1, expires_at: 0 })
    files.add({ file_id: 'f_b', name: 'receipt.jpg', kind: 'image', pages: 1, size: 1, expires_at: 0 })
    await nextTick()

    const wrapper = mount(PageStrip, { global: { plugins: [pinia] } })
    const items = wrapper.findAll('li')
    expect(items.map((li) => li.text())).toEqual(['contract p1', 'contract p2', 'receipt'])

    await items[2]!.trigger('dragstart')
    await items[0]!.trigger('drop')

    expect(plan.pages.map((p) => p.key)).toEqual(['f_b:0', 'f_a:0', 'f_a:1'])
    expect(wrapper.text()).toContain('Reset order')
  })

  it('renders nothing without pages', () => {
    const pinia = createPinia()
    setActivePinia(pinia)

    const wrapper = mount(PageStrip, { global: { plugins: [pinia] } })

    expect(wrapper.find('section').exists()).toBe(false)
  })

  it('moves a page with Alt and arrow keys and sets drag data', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const files = useFilesStore()
    const plan = usePlanStore()
    files.add({ file_id: 'f_a', name: 'contract.pdf', kind: 'pdf', pages: 2, size: 1, expires_at: 0 })
    await nextTick()

    const wrapper = mount(PageStrip, { global: { plugins: [pinia] } })
    const items = wrapper.findAll('li')
    expect(items[0]!.attributes('tabindex')).toBe('0')

    await items[0]!.trigger('keydown', { key: 'ArrowLeft', altKey: true })
    expect(plan.pages.map((p) => p.key)).toEqual(['f_a:0', 'f_a:1'])

    await items[0]!.trigger('keydown', { key: 'ArrowRight', altKey: true })
    expect(plan.pages.map((p) => p.key)).toEqual(['f_a:1', 'f_a:0'])

    const dataTransfer = { setData: vi.fn(), effectAllowed: '' }
    await wrapper.findAll('li')[1]!.trigger('dragstart', { dataTransfer })
    expect(dataTransfer.setData).toHaveBeenCalledWith('text/plain', '1')
    expect(dataTransfer.effectAllowed).toBe('move')
  })
})
