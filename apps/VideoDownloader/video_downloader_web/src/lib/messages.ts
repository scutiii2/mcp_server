/** The user-facing text of anything thrown. ApiError messages come from the server. */
export function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}

// Codes whose wording is better decided here than by the server (client-side codes and a few overrides).
const FRIENDLY: Record<string, string> = {
  cancelled: 'The download was cancelled.',
  connection_lost: 'Lost the connection to the server. Check your downloads list, then try again.',
  http_error: 'The server could not be reached. Try again.',
  drm_protected: 'This video is copy-protected (DRM), so it cannot be downloaded.',
  login_required: 'This video needs a login (private, members-only or age-restricted), so it cannot be downloaded here.',
}

/** One table of error text: known codes get fixed wording, anything else shows the server's message. */
export function friendlyError(code: string, message: string): string {
  return FRIENDLY[code] ?? message
}
