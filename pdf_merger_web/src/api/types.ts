// Mirrors pdf_merger/src/models.py. Keep both in step.

export type Rotation = 0 | 90 | 180 | 270
export type Fit = 'fit' | 'fill' | 'original'
export type PageSize = 'A4' | 'Letter' | 'match'
export type FileKind = 'pdf' | 'image'

export interface FileInfo {
  file_id: string
  name: string
  kind: FileKind
  pages: number
  size: number
  expires_at: number
}

export interface Segment {
  file_id: string
  pages: string | null
  rotate: Rotation
  fit: Fit | null
}

export interface OutputOptions {
  filename: string
  title: string | null
  author: string | null
  bookmarks: boolean
  image_page_size: PageSize
  image_fit: Fit
  image_margin_mm: number
}

export interface MergePlan {
  segments: Segment[]
  output: OutputOptions
}

export interface MergeResult {
  file_id: string
  name: string
  pages: number
  size: number
  expires_at: number
  download_url: string
}

export type JobEvent =
  | { type: 'queued'; total: number }
  | { type: 'progress'; done: number; total: number }
  | ({ type: 'done' } & MergeResult)
  | { type: 'error'; code: string; message: string }

/** A failed request, with the server's error code and user-facing message. */
export class ApiError extends Error {
  readonly code: string
  readonly status: number

  constructor(code: string, message: string, status: number) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.status = status
  }
}
