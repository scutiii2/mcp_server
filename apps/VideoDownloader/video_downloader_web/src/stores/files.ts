// The files this browser session has downloaded (kept by the server until they expire).
import { defineStore } from 'pinia'
import { ref } from 'vue'
import * as api from '../api/client'
import type { FileInfo } from '../api/types'
import { messageOf } from '../lib/messages'

export const useFilesStore = defineStore('files', () => {
  const files = ref<FileInfo[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)

  async function refresh(): Promise<void> {
    loading.value = true
    try {
      files.value = await api.listFiles()
      error.value = null
    } catch (e) {
      error.value = messageOf(e)
    } finally {
      loading.value = false
    }
  }

  async function remove(fileId: string): Promise<void> {
    try {
      await api.deleteFile(fileId)
      files.value = files.value.filter((f) => f.file_id !== fileId)
      error.value = null
    } catch (e) {
      error.value = messageOf(e)
    }
  }

  return { files, loading, error, refresh, remove }
})
