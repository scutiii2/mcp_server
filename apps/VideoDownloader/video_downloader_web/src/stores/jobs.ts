// Downloads in progress or just finished, each followed over SSE.
import { defineStore } from 'pinia'
import { ref } from 'vue'
import * as api from '../api/client'
import { ApiError, type FileInfo, type JobEvent, type JobState, type PresetOption } from '../api/types'
import { friendlyError, messageOf } from '../lib/messages'
import { useFilesStore } from './files'

export interface JobView {
  id: string
  title: string
  presetLabel: string
  state: JobState
  /** Never goes backwards: video and audio download as two streams that each count 0-100. */
  percent: number | null
  speed: number | null
  eta: number | null
  file: FileInfo | null
  error: { code: string; message: string } | null
}

export const useJobsStore = defineStore('jobs', () => {
  const jobs = ref<JobView[]>([])
  const startError = ref<string | null>(null)
  const stops = new Map<string, () => void>()

  function apply(job: JobView, event: JobEvent): void {
    switch (event.type) {
      case 'queued':
        job.state = 'queued'
        break
      case 'progress':
        job.state = 'downloading'
        if (event.percent !== null) job.percent = Math.max(job.percent ?? 0, event.percent)
        job.speed = event.speed
        job.eta = event.eta
        break
      case 'processing':
        job.state = 'processing'
        job.speed = null
        job.eta = null
        break
      case 'done':
        job.state = 'done'
        job.percent = 100
        job.file = event.file
        void useFilesStore().refresh()
        break
      case 'error':
        job.state = 'error'
        job.error = { code: event.code, message: friendlyError(event.code, event.message) }
        break
    }
  }

  async function start(url: string, title: string, option: PresetOption): Promise<void> {
    startError.value = null
    try {
      const { job_id } = await api.startDownload(url, option.id)
      const job: JobView = {
        id: job_id,
        title,
        presetLabel: option.label,
        state: 'queued',
        percent: null,
        speed: null,
        eta: null,
        file: null,
        error: null,
      }
      jobs.value.unshift(job)
      // Mutate through the reactive proxy that lives in the array.
      stops.set(job_id, api.watchJob(job_id, (event) => apply(jobs.value.find((j) => j.id === job_id) ?? job, event)))
    } catch (e) {
      startError.value = e instanceof ApiError ? friendlyError(e.code, e.message) : messageOf(e)
    }
  }

  async function cancel(id: string): Promise<void> {
    try {
      await api.cancelJob(id)
    } catch (e) {
      startError.value = messageOf(e)
    }
  }

  function dismiss(id: string): void {
    stops.get(id)?.()
    stops.delete(id)
    jobs.value = jobs.value.filter((j) => j.id !== id)
  }

  return { jobs, startError, start, cancel, dismiss }
})
