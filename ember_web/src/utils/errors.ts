/** Display text for anything a `catch` receives. */
export function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

/** ember_api sends naive UTC times; shown in the viewer's local time. */
export function formatUtc(iso: string): string {
  return new Date(`${iso}Z`).toLocaleString();
}
