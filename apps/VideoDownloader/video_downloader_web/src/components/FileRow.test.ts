import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import type { FileInfo } from '../api/types'
import FileRow from './FileRow.vue'

const FILE: FileInfo = {
  file_id: 'f_1',
  name: 'Cat.mp4',
  kind: 'video',
  mime: 'video/mp4',
  size: 5 * 1024 * 1024,
  duration: 65,
  expires_at: 1000 + 5 * 3600,
  download_url: '/api/files/f_1/download?exp=1&sig=s',
}

describe('FileRow', () => {
  it('shows name, size, duration and time left', () => {
    const wrapper = mount(FileRow, { props: { file: FILE, now: 1000 } })
    expect(wrapper.text()).toContain('Cat.mp4')
    expect(wrapper.text()).toContain('5.0 MB')
    expect(wrapper.text()).toContain('1:05')
    expect(wrapper.text()).toContain('5 h 0 min')
  })

  it('links to the signed download and emits remove', async () => {
    const wrapper = mount(FileRow, { props: { file: FILE, now: 1000 } })
    expect(wrapper.get('a').attributes('href')).toBe(FILE.download_url)
    await wrapper.get('button.remove').trigger('click')
    expect(wrapper.emitted('remove')).toHaveLength(1)
  })
})
