const KB = 1024
const MB = KB * 1024
const GB = MB * 1024

export function formatBytes(bytes: number): string {
  if (bytes < KB) return `${bytes} B`
  if (bytes < MB) return `${Math.round(bytes / KB)} KB`
  if (bytes < GB) return `${(bytes / MB).toFixed(1)} MB`
  return `${(bytes / GB).toFixed(2)} GB`
}

export function plural(count: number, word: string): string {
  return `${count} ${word}${count === 1 ? '' : 's'}`
}

/** m:ss, or h:mm:ss from one hour up. Empty when unknown. */
export function formatDuration(seconds: number | null): string {
  if (seconds === null) return ''
  const total = Math.round(seconds)
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  const s = total % 60
  const pad = (n: number): string => String(n).padStart(2, '0')
  return h > 0 ? `${h}:${pad(m)}:${pad(s)}` : `${m}:${pad(s)}`
}

export function formatSpeed(bytesPerSecond: number | null): string {
  return bytesPerSecond === null ? '' : `${(bytesPerSecond / MB).toFixed(1)} MB/s`
}

export function formatEta(seconds: number | null): string {
  if (seconds === null) return ''
  const total = Math.round(seconds)
  if (total < 60) return `${total} s`
  if (total < 3600) return `${Math.floor(total / 60)} min ${total % 60} s`
  const minutes = Math.round(total / 60)
  return `${Math.floor(minutes / 60)} h ${minutes % 60} min`
}

/** Time left until a unix-seconds expiry, e.g. "5 h 12 min". Both arguments are unix seconds. */
export function formatExpiry(expiresAt: number, now: number): string {
  const left = Math.floor(expiresAt - now)
  if (left <= 0) return 'expired'
  const hours = Math.floor(left / 3600)
  const minutes = Math.max(1, Math.floor((left % 3600) / 60))
  return hours > 0 ? `${hours} h ${Math.floor((left % 3600) / 60)} min` : `${minutes} min`
}
