import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import type { SourceState } from '../stores/files'
import SourceRow from './SourceRow.vue'

function source(overrides: Partial<SourceState> = {}, kind: 'pdf' | 'image' = 'pdf'): SourceState {
  return {
    info: { file_id: 'f_a', name: 'contract.pdf', kind, pages: 12, size: 2_400_000, expires_at: 0 },
    range: 'all',
    pages: [],
    rangeError: null,
    rotate: 0,
    fit: null,
    ...overrides,
  }
}

describe('SourceRow', () => {
  it('shows name, pages and size', () => {
    const wrapper = mount(SourceRow, { props: { source: source() } })

    expect(wrapper.text()).toContain('contract.pdf')
    expect(wrapper.text()).toContain('12 pages · 2.3 MB')
  })

  it('emits typed ranges', async () => {
    const wrapper = mount(SourceRow, { props: { source: source() } })

    await wrapper.get('input[aria-label="Pages"]').setValue('1-3,7')

    expect(wrapper.emitted('range')).toEqual([['1-3,7']])
  })

  it('shows a range error next to the input', () => {
    const wrapper = mount(SourceRow, { props: { source: source({ range: '99', rangeError: 'Pages go from 1 to 12' }) } })

    expect(wrapper.get('[role="alert"]').text()).toBe('Pages go from 1 to 12')
    expect(wrapper.get('input[aria-label="Pages"]').classes()).toContain('invalid')
  })

  it('shows a fit menu for images and emits null for the default', async () => {
    const wrapper = mount(SourceRow, { props: { source: source({}, 'image') } })
    const select = wrapper.get('select[aria-label="Image fit"]')

    await select.setValue('fill')
    await select.setValue('')

    expect(wrapper.find('input[aria-label="Pages"]').exists()).toBe(false)
    expect(wrapper.emitted('fit')).toEqual([['fill'], [null]])
  })

  it('emits rotate and remove', async () => {
    const wrapper = mount(SourceRow, { props: { source: source({ rotate: 90 }) } })

    await wrapper.get('button[aria-label="Rotate"]').trigger('click')
    await wrapper.get('button[aria-label="Remove"]').trigger('click')

    expect(wrapper.text()).toContain('rotated 90°')
    expect(wrapper.emitted('rotate')).toHaveLength(1)
    expect(wrapper.emitted('remove')).toHaveLength(1)
  })
})
