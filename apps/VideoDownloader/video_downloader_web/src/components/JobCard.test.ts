import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import type { JobView } from '../stores/jobs'
import JobCard from './JobCard.vue'

function job(partial: Partial<JobView>): JobView {
  return { id: 'j_1', title: 'Cat', presetLabel: '720p', state: 'downloading', percent: 40, speed: 1_500_000, eta: 12, file: null, error: null, ...partial }
}

describe('JobCard', () => {
  it('shows progress, speed and eta while downloading, with Cancel', async () => {
    const wrapper = mount(JobCard, { props: { job: job({}) } })
    expect(wrapper.text()).toContain('Cat')
    expect(wrapper.text()).toContain('40%')
    expect(wrapper.text()).toContain('1.4 MB/s')
    expect(wrapper.text()).toContain('12 s')
    expect((wrapper.get('progress').element as HTMLProgressElement).value).toBe(40)
    await wrapper.get('button.cancel').trigger('click')
    expect(wrapper.emitted('cancel')).toHaveLength(1)
  })

  it('shows a processing state without cancel', () => {
    const wrapper = mount(JobCard, { props: { job: job({ state: 'processing' }) } })
    expect(wrapper.text()).toContain('Processing')
  })

  it('offers the file when done and Dismiss', async () => {
    const file = { file_id: 'f_1', name: 'Cat.mp4', kind: 'video' as const, mime: 'video/mp4', size: 1, duration: 5, expires_at: 9, download_url: '/api/files/f_1/download?exp=1&sig=s' }
    const wrapper = mount(JobCard, { props: { job: job({ state: 'done', percent: 100, file }) } })
    expect(wrapper.get('a.primary').attributes('href')).toBe(file.download_url)
    await wrapper.get('button.dismiss').trigger('click')
    expect(wrapper.emitted('dismiss')).toHaveLength(1)
  })

  it('shows the error message', () => {
    const wrapper = mount(JobCard, { props: { job: job({ state: 'error', error: { code: 'too_large', message: 'Too big.' } }) } })
    expect(wrapper.get('.error').text()).toBe('Too big.')
  })
})
