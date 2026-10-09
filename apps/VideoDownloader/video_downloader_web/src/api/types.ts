// Mirrors video_downloader/src/models.py and the job events in src/service.py. Keep both in step.

export type FileKind = 'video' | 'audio'
export type JobState = 'queued' | 'downloading' | 'processing' | 'done' | 'error'

export interface FileInfo {
  file_id: string
  name: string
  kind: FileKind
  mime: string
  size: number
  duration: number | null
  expires_at: number
  download_url: string
}

export interface PresetOption {
  id: string
  label: string
  kind: FileKind
  estimated_bytes: number | null
  blocked: boolean
  code: string | null
  reason: string | null
}

export interface ProbeResult {
  url: string
  title: string
  duration: number | null
  thumbnail: string | null
  uploader: string | null
  options: PresetOption[]
}

export type JobEvent =
  | { type: 'queued' }
  | { type: 'progress'; percent: number | null; speed: number | null; eta: number | null }
  | { type: 'processing' }
  | { type: 'done'; file_id: string; file: FileInfo }
  | { type: 'error'; code: string; message: string }

/** GET /api/jobs/{id}: a snapshot of one job (src/models.py JobStatus). */
export interface JobStatus {
  job_id: string
  state: JobState
  percent: number | null
  speed: number | null
  eta: number | null
  file: FileInfo | null // null for a done job whose file has since been deleted or expired
  error: { code: string; message: string } | null
}

export class ApiError extends Error {
  code: string
  status: number

  constructor(code: string, message: string, status: number) {
    super(message)
    this.code = code
    this.status = status
  }
}
