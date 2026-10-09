import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import type { ProbeResult } from '../api/types'
import ProbeCard from './ProbeCard.vue'

const RESULT: ProbeResult = {
  url: 'https://x/v',
  title: 'Cat video',
  duration: 125,
  thumbnail: 'https://img/t.jpg',
  uploader: 'Cats',
  options: [
    { id: 'best', label: 'Best quality', kind: 'video', estimated_bytes: 50_000_000, blocked: true, code: 'too_large', reason: 'Too big for the limit.' },
    { id: '720p', label: '720p', kind: 'video', estimated_bytes: 11_000_000, blocked: false, code: null, reason: null },
  ],
}

describe('ProbeCard', () => {
  it('shows title, uploader, duration and thumbnail', () => {
    const wrapper = mount(ProbeCard, { props: { result: RESULT, selected: '720p' } })
    expect(wrapper.text()).toContain('Cat video')
    expect(wrapper.text()).toContain('Cats')
    expect(wrapper.text()).toContain('2:05')
    expect(wrapper.get('img').attributes('src')).toBe('https://img/t.jpg')
  })

  it('does not load a thumbnail that is not https', () => {
    const wrapper = mount(ProbeCard, { props: { result: { ...RESULT, thumbnail: 'http://img/t.jpg' }, selected: null } })
    expect(wrapper.find('img').exists()).toBe(false)
    expect(wrapper.text()).toContain('No preview')
  })

  it('disables blocked presets and shows the reason', () => {
    const wrapper = mount(ProbeCard, { props: { result: RESULT, selected: '720p' } })
    const radios = wrapper.findAll('input[type="radio"]')
    expect((radios[0].element as HTMLInputElement).disabled).toBe(true)
    expect((radios[1].element as HTMLInputElement).disabled).toBe(false)
    expect(wrapper.text()).toContain('Too big for the limit.')
  })

  it('emits select and download', async () => {
    const wrapper = mount(ProbeCard, { props: { result: RESULT, selected: null } })
    expect(wrapper.get('button.primary').attributes('disabled')).toBeDefined()
    await wrapper.findAll('input[type="radio"]')[1].setValue(true)
    expect(wrapper.emitted('select')?.[0]).toEqual(['720p'])
    await wrapper.setProps({ selected: '720p' })
    await wrapper.get('button.primary').trigger('click')
    expect(wrapper.emitted('download')).toHaveLength(1)
  })
})
