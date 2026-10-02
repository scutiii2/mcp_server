import { describe, expect, it } from 'vitest'
import type { FileKind, Fit, Rotation } from '../api/types'
import { formatRange, moveItem, pageKey, parseRange, reconcile, toSegments, type PageItem } from './segments'

function item(fileId: string, page: number, rotate: Rotation = 0): PageItem {
  return { key: pageKey(fileId, page), fileId, page, rotate }
}

const keys = (items: PageItem[]) => items.map((i) => i.key)

describe('parseRange', () => {
  it('selects every page for empty or all', () => {
    expect(parseRange('', 3)).toEqual([0, 1, 2])
    expect(parseRange(' ALL ', 2)).toEqual([0, 1])
  })

  it('parses ranges in written order', () => {
    expect(parseRange('1-3,7', 10)).toEqual([0, 1, 2, 6])
    expect(parseRange('5, 2', 10)).toEqual([4, 1])
  })

  it('returns a message for bad input', () => {
    expect(parseRange('0', 5)).toBe('Pages go from 1 to 5')
    expect(parseRange('6', 5)).toBe('Pages go from 1 to 5')
    expect(parseRange('3-1', 5)).toBe('"3-1" runs backwards')
    expect(parseRange('a', 5)).toBe('"a" isn\'t a page or range')
    expect(parseRange('1,1', 5)).toBe('A page is listed twice')
  })
})

describe('formatRange', () => {
  it('compresses ascending runs only', () => {
    expect(formatRange([0, 1, 2, 6])).toBe('1-3,7')
    expect(formatRange([4, 1])).toBe('5,2')
    expect(formatRange([0])).toBe('1')
  })
})

describe('toSegments', () => {
  const kinds = new Map<string, FileKind>([
    ['a', 'pdf'],
    ['img', 'image'],
  ])
  const fits = new Map<string, Fit | null>([['img', 'fill']])

  it('groups neighbours of the same file and rotation', () => {
    const segments = toSegments([item('a', 0), item('a', 1), item('img', 0), item('a', 2, 90), item('a', 3, 90)], fits, kinds)

    expect(segments).toEqual([
      { file_id: 'a', pages: '1-2', rotate: 0, fit: null },
      { file_id: 'img', pages: null, rotate: 0, fit: 'fill' },
      { file_id: 'a', pages: '3-4', rotate: 90, fit: null },
    ])
  })

  it('returns nothing for no pages', () => {
    expect(toSegments([], fits, kinds)).toEqual([])
  })
})

describe('reconcile', () => {
  it('keeps manual order and drops removed pages', () => {
    const current = [item('b', 0), item('a', 1), item('a', 0)]
    const fresh = [item('a', 0), item('b', 0)]

    expect(keys(reconcile(current, fresh))).toEqual(['b:0', 'a:0'])
  })

  it('takes rotation from fresh', () => {
    expect(reconcile([item('a', 0)], [item('a', 0, 180)])[0]!.rotate).toBe(180)
  })

  it('inserts a new page before the next placed page of its file', () => {
    const current = [item('b', 0), item('a', 2)]
    const fresh = [item('a', 0), item('a', 2), item('b', 0)]

    expect(keys(reconcile(current, fresh))).toEqual(['b:0', 'a:0', 'a:2'])
  })

  it('appends pages of a new file at the end, in order', () => {
    const current = [item('a', 0)]
    const fresh = [item('a', 0), item('c', 0), item('c', 1)]

    expect(keys(reconcile(current, fresh))).toEqual(['a:0', 'c:0', 'c:1'])
  })
})

describe('moveItem', () => {
  it('moves without mutating', () => {
    const list = ['a', 'b', 'c']

    expect(moveItem(list, 2, 0)).toEqual(['c', 'a', 'b'])
    expect(list).toEqual(['a', 'b', 'c'])
  })
})
