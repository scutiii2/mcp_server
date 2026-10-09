// Uploaded source files and their per-file options (range, rotation, fit).
import { defineStore } from 'pinia'
import { ref } from 'vue'
import * as api from '../api/client'
import type { FileInfo, Fit, Rotation } from '../api/types'
import { messageOf } from '../lib/messages'
import { moveItem, parseRange } from '../lib/segments'

export interface SourceState {
  info: FileInfo
  /** What the user typed. */
  range: string
  /** Last valid selection, 0-based. */
  pages: number[]
  rangeError: string | null
  rotate: Rotation
  /** Images only; null = use the output default. */
  fit: Fit | null
}

function allPages(info: FileInfo): number[] {
  return Array.from({ length: info.pages }, (_, i) => i)
}

export const useFilesStore = defineStore('files', () => {
  const sources = ref<SourceState[]>([])
  const uploading = ref(0)
  const errors = ref<string[]>([])

  function find(fileId: string): SourceState | undefined {
    return sources.value.find((s) => s.info.file_id === fileId)
  }

  function add(info: FileInfo): void {
    if (find(info.file_id)) return
    sources.value.push({ info, range: 'all', pages: allPages(info), rangeError: null, rotate: 0, fit: null })
  }

  /** One at a time, so sources appear in drop order. */
  async function upload(files: readonly File[]): Promise<void> {
    uploading.value += files.length
    for (const file of files) {
      try {
        add(await api.uploadFile(file))
      } catch (error) {
        errors.value.push(`${file.name}: ${messageOf(error)}`)
      } finally {
        uploading.value -= 1
      }
    }
  }

  /** Bring back this browser's files after a reload. Also makes the server set the session cookie. */
  async function restore(): Promise<void> {
    try {
      for (const info of await api.listFiles()) add(info)
    } catch (error) {
      errors.value.push(`Couldn't load your files: ${messageOf(error)}`)
    }
  }

  async function remove(fileId: string): Promise<void> {
    sources.value = sources.value.filter((s) => s.info.file_id !== fileId)
    try {
      await api.deleteFile(fileId)
    } catch {
      // Already expired or deleted; nothing left to do.
    }
  }

  function setRange(fileId: string, text: string): void {
    const source = find(fileId)
    if (!source) return
    source.range = text
    const parsed = parseRange(text, source.info.pages)
    if (typeof parsed === 'string') {
      source.rangeError = parsed
    } else {
      source.rangeError = null
      source.pages = parsed
    }
  }

  function rotate(fileId: string): void {
    const source = find(fileId)
    if (source) source.rotate = ((source.rotate + 90) % 360) as Rotation
  }

  function setFit(fileId: string, fit: Fit | null): void {
    const source = find(fileId)
    if (source) source.fit = fit
  }

  function moveSource(from: number, to: number): void {
    sources.value = moveItem(sources.value, from, to)
  }

  function dismissError(index: number): void {
    errors.value.splice(index, 1)
  }

  return { sources, uploading, errors, add, upload, restore, remove, setRange, rotate, setFit, moveSource, dismissError }
})
