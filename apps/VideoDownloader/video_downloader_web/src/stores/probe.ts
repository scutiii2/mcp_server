// The link the user pasted and what the server found out about it.
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import * as api from '../api/client'
import { ApiError, type PresetOption, type ProbeResult } from '../api/types'
import { friendlyError, messageOf } from '../lib/messages'

export const useProbeStore = defineStore('probe', () => {
  const url = ref('')
  const result = ref<ProbeResult | null>(null)
  const selected = ref<string | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)

  const canCheck = computed(() => url.value.trim() !== '' && !loading.value)
  const selectedOption = computed<PresetOption | null>(
    () => result.value?.options.find((o) => o.id === selected.value) ?? null,
  )

  async function check(): Promise<void> {
    if (!canCheck.value) return
    loading.value = true
    error.value = null
    result.value = null
    selected.value = null
    try {
      result.value = await api.probe(url.value.trim())
      selected.value = result.value.options.find((o) => !o.blocked)?.id ?? null
    } catch (e) {
      error.value = e instanceof ApiError ? friendlyError(e.code, e.message) : messageOf(e)
    } finally {
      loading.value = false
    }
  }

  /** Blocked or unknown presets cannot be selected. */
  function select(id: string): void {
    const option = result.value?.options.find((o) => o.id === id)
    if (option && !option.blocked) selected.value = id
  }

  function reset(): void {
    url.value = ''
    result.value = null
    selected.value = null
    error.value = null
  }

  return { url, result, selected, loading, error, canCheck, selectedOption, check, select, reset }
})
