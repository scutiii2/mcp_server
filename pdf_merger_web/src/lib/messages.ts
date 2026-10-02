/** The user-facing text of anything thrown. ApiError messages come from the server. */
export function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}
