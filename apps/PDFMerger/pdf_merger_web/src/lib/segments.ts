// Pure conversions between the page strip (one PageItem per output page)
// and the server's MergePlan segments. No Vue, no I/O: easy to test.
import type { FileKind, Fit, Rotation, Segment } from '../api/types'

export interface PageItem {
  key: string
  fileId: string
  /** 0-based page index in the source file. */
  page: number
  rotate: Rotation
}

export function pageKey(fileId: string, page: number): string {
  return `${fileId}:${page}`
}

const PART = /^(\d+)(?:\s*-\s*(\d+))?$/

/** 0-based pages for a "1-3,7" spec, or an error message. Same rules as the server. */
export function parseRange(spec: string, count: number): number[] | string {
  const text = spec.trim().toLowerCase()
  if (text === '' || text === 'all') return Array.from({ length: count }, (_, i) => i)
  const pages: number[] = []
  for (const raw of text.split(',')) {
    const part = raw.trim()
    const match = PART.exec(part)
    if (!match) return `"${part}" isn't a page or range`
    const start = Number(match[1])
    const end = Number(match[2] ?? match[1])
    if (start > end) return `"${part}" runs backwards`
    if (start < 1 || end > count) return `Pages go from 1 to ${count}`
    for (let page = start; page <= end; page++) pages.push(page - 1)
  }
  if (new Set(pages).size !== pages.length) return 'A page is listed twice'
  return pages
}

/** 0-based pages to a 1-based spec. Only ascending runs collapse, so order is kept. */
export function formatRange(pages: readonly number[]): string {
  const parts: string[] = []
  let start = 0
  while (start < pages.length) {
    let end = start
    while (end + 1 < pages.length && pages[end + 1] === pages[end]! + 1) end++
    parts.push(start === end ? `${pages[start]! + 1}` : `${pages[start]! + 1}-${pages[end]! + 1}`)
    start = end + 1
  }
  return parts.join(',')
}

/** Group neighbouring pages of one file with one rotation into segments. O(n). */
export function toSegments(
  items: readonly PageItem[],
  fitByFile: ReadonlyMap<string, Fit | null>,
  kindByFile: ReadonlyMap<string, FileKind>,
): Segment[] {
  const segments: Segment[] = []
  let run: PageItem[] = []
  const flush = (): void => {
    const first = run[0]
    if (!first) return
    const isImage = kindByFile.get(first.fileId) === 'image'
    segments.push({
      file_id: first.fileId,
      pages: isImage ? null : formatRange(run.map((r) => r.page)),
      rotate: first.rotate,
      fit: isImage ? (fitByFile.get(first.fileId) ?? null) : null,
    })
    run = []
  }
  for (const item of items) {
    const last = run[run.length - 1]
    if (last && (last.fileId !== item.fileId || last.rotate !== item.rotate)) flush()
    run.push(item)
  }
  flush()
  return segments
}

function lastIndexOfFile(items: readonly PageItem[], fileId: string): number {
  for (let i = items.length - 1; i >= 0; i--) if (items[i]!.fileId === fileId) return i
  return -1
}

/**
 * Apply a new page set to a hand-ordered strip. Pages still present keep
 * their place (with fresh rotation); new pages slot in near their file.
 * O(n^2) worst case; n is capped at 2000 pages by the server.
 */
export function reconcile(current: readonly PageItem[], fresh: readonly PageItem[]): PageItem[] {
  const freshByKey = new Map(fresh.map((item) => [item.key, item]))
  const result: PageItem[] = []
  for (const item of current) {
    const updated = freshByKey.get(item.key)
    if (updated) result.push(updated)
  }
  const placed = new Set(result.map((item) => item.key))
  fresh.forEach((item, index) => {
    if (placed.has(item.key)) return
    const next = fresh.slice(index + 1).find((other) => other.fileId === item.fileId && placed.has(other.key))
    let at: number
    if (next) {
      at = result.findIndex((r) => r.key === next.key)
    } else {
      const last = lastIndexOfFile(result, item.fileId)
      at = last === -1 ? result.length : last + 1
    }
    result.splice(at, 0, item)
    placed.add(item.key)
  })
  return result
}

export function moveItem<T>(list: readonly T[], from: number, to: number): T[] {
  const copy = [...list]
  const [moved] = copy.splice(from, 1)
  if (moved !== undefined) copy.splice(to, 0, moved)
  return copy
}
