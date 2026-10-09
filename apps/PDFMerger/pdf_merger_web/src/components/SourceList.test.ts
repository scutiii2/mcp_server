import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { describe, expect, it, vi } from 'vitest'
import { useFilesStore } from '../stores/files'
import SourceList from './SourceList.vue'

vi.mock('../api/client')

function setup() {
  const pinia = createPinia()
  setActivePinia(pinia)
  const files = useFilesStore()
  files.add({ file_id: 'f_a', name: 'a.pdf', kind: 'pdf', pages: 2, size: 1, expires_at: 0 })
  files.add({ file_id: 'f_b', name: 'b.pdf', kind: 'pdf', pages: 2, size: 1, expires_at: 0 })
  const wrapper = mount(SourceList, { global: { plugins: [pinia] } })
  return { files, wrapper }
}

const ids = (files: ReturnType<typeof useFilesStore>) => files.sources.map((s) => s.info.file_id)

describe('SourceList', () => {
  it('moves a file with Alt and arrow keys, within bounds', async () => {
    const { files, wrapper } = setup()
    const rows = () => wrapper.findAll('li')

    await rows()[0]!.trigger('keydown', { key: 'ArrowUp', altKey: true })
    expect(ids(files)).toEqual(['f_a', 'f_b'])

    await rows()[0]!.trigger('keydown', { key: 'ArrowDown', altKey: true })
    expect(ids(files)).toEqual(['f_b', 'f_a'])
    expect(rows()[0]!.attributes('tabindex')).toBe('0')
  })

  it('ignores Alt+Arrow typed inside the range input', async () => {
    const { files, wrapper } = setup()

    await wrapper.get('li input').trigger('keydown', { key: 'ArrowDown', altKey: true })

    expect(ids(files)).toEqual(['f_a', 'f_b'])
  })

  it('starts drags only from the handle, with drag data set', async () => {
    const { wrapper } = setup()
    const li = wrapper.get('li')
    const dataTransfer = { setData: vi.fn(), effectAllowed: '' }

    expect(li.attributes('draggable')).toBeUndefined()
    await wrapper.get('.handle').trigger('dragstart', { dataTransfer })

    expect(dataTransfer.setData).toHaveBeenCalledWith('text/plain', '0')
    expect(dataTransfer.effectAllowed).toBe('move')
  })
})
