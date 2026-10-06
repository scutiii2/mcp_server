/** The address if it is a plain http(s) URL, else null. An extension's web
 * app link comes from server config; it must never carry another scheme
 * (javascript:, data:) into an <a href>. */
export function safeWebUrl(value: string | null | undefined): string | null {
  if (!value) return null;
  try {
    const url = new URL(value.trim());
    return url.protocol === "http:" || url.protocol === "https:" ? url.href : null;
  } catch {
    return null;
  }
}
