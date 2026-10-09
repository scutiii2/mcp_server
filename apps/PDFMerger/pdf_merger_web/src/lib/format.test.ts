import { describe, expect, it } from 'vitest'
import { formatBytes, plural } from './format'
import { messageOf } from './messages'

describe('format helpers', () => {
  it('formats bytes', () => {
    expect(formatBytes(512)).toBe('512 B')
    expect(formatBytes(2048)).toBe('2 KB')
    expect(formatBytes(3.25 * 1024 * 1024)).toBe('3.3 MB')
  })

  it('pluralizes', () => {
    expect(plural(1, 'page')).toBe('1 page')
    expect(plural(2, 'page')).toBe('2 pages')
  })

  it('reads error messages', () => {
    expect(messageOf(new Error('Broken.'))).toBe('Broken.')
    expect(messageOf('plain')).toBe('plain')
  })
})
