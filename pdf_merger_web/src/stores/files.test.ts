import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '../api/client'
import type { FileInfo } from '../api/types'
import { useFilesStore } from './files'

vi.mock('../api/client')

function pdf(id: string, pages = 3): FileInfo {
  return { file_id: id, name: `${id}.pdf`, kind: 'pdf', pages, size: 1000, expires_at: 0 }
}

describe('files store', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('uploads in drop order and reports failures per file', async () => {
    vi.mocked(api.uploadFile)
      .mockResolvedValueOnce(pdf('f_a'))
      .mockRejectedValueOnce(new Error('Too big.'))
      .mockResolvedValueOnce(pdf('f_c'))
    const files = useFilesStore()

    await files.upload([new File([''], 'a.pdf'), new File([''], 'b.pdf'), new File([''], 'c.pdf')])

    expect(files.sources.map((s) => s.info.file_id)).toEqual(['f_a', 'f_c'])
    expect(files.errors).toEqual(['b.pdf: Too big.'])
    expect(files.uploading).toBe(0)
  })

  it('starts with every page selected', () => {
    const files = useFilesStore()
    files.add(pdf('f_a', 3))

    expect(files.sources[0]).toMatchObject({ range: 'all', pages: [0, 1, 2], rangeError: null, rotate: 0, fit: null })
  })

  it('keeps the last valid pages while a range is invalid', () => {
    const files = useFilesStore()
    files.add(pdf('f_a', 5))

    files.setRange('f_a', '2-3')
    files.setRange('f_a', '9')

    expect(files.sources[0]).toMatchObject({ range: '9', pages: [1, 2], rangeError: 'Pages go from 1 to 5' })
    files.setRange('f_a', '4')
    expect(files.sources[0]).toMatchObject({ pages: [3], rangeError: null })
  })

  it('rotates in 90 degree steps', () => {
    const files = useFilesStore()
    files.add(pdf('f_a'))

    for (let i = 0; i < 4; i++) files.rotate('f_a')

    expect(files.sources[0]!.rotate).toBe(0)
    files.rotate('f_a')
    expect(files.sources[0]!.rotate).toBe(90)
  })

  it('restore adds server files once', async () => {
    vi.mocked(api.listFiles).mockResolvedValue([pdf('f_a'), pdf('f_b')])
    const files = useFilesStore()
    files.add(pdf('f_a'))

    await files.restore()

    expect(files.sources.map((s) => s.info.file_id)).toEqual(['f_a', 'f_b'])
  })

  it('removes locally even when the server delete fails', async () => {
    vi.mocked(api.deleteFile).mockRejectedValue(new Error('gone'))
    const files = useFilesStore()
    files.add(pdf('f_a'))

    await files.remove('f_a')

    expect(files.sources).toEqual([])
  })

  it('moves sources', () => {
    const files = useFilesStore()
    files.add(pdf('f_a'))
    files.add(pdf('f_b'))

    files.moveSource(1, 0)

    expect(files.sources.map((s) => s.info.file_id)).toEqual(['f_b', 'f_a'])
  })
})
