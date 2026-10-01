/** `[[DOWNLOAD ...]]` markers: how a tool offers a file for download (chat_app's
 * format). A reply or a command result carries them as text; the page turns
 * them into download cards. */

export interface DownloadCard {
  filename: string;
  /** 0 when the size is not known. */
  bytes: number;
  /** An ember_api URL the browser may open, or null when the marker's URL is not one. */
  href: string | null;
  /** A short tag above the card, e.g. "EXPORT". */
  label: string;
}

const MARKER = /\[\[DOWNLOAD filename="([^"]*)" bytes="(\d+)" url="([^"]*)"(?: label="([^"]*)")?\]\]/g;

// The route a marker may point at: mcp_server's own "/server/download" is
// reached through ember_api. Nothing else - a model must not be able to put
// any other link on a card.
const SERVER_DOWNLOAD = "/server/download?";
const API_DOWNLOAD = "/api/server/download?";

/** The ember_api URL for a marker's URL, or null for one that is not a download route. */
export function downloadHref(url: string): string | null {
  if (url.includes("\\") || /[\u0000-\u001f]/.test(url)) return null;
  if (url.startsWith(API_DOWNLOAD)) return url;
  if (url.startsWith(SERVER_DOWNLOAD)) return `/api${url}`;
  return null;
}

/** The text without its markers, and one card for each. */
export function parseDownloads(text: string): { text: string; downloads: DownloadCard[] } {
  const downloads: DownloadCard[] = [];
  const rest = text.replace(MARKER, (_match, filename: string, bytes: string, url: string, label?: string) => {
    downloads.push({ filename, bytes: Number(bytes), href: downloadHref(url), label: label || "DOWNLOAD" });
    return "";
  });
  return { text: downloads.length ? rest.trim() : text, downloads };
}

/** The text of an answer still being written, without its markers and without a
 * marker that is only half typed (it would flash as raw text until it ends). */
export function hideDownloadMarkers(text: string): string {
  const complete = text.replace(MARKER, "");
  const open = complete.lastIndexOf("[[");
  if (open === -1) return complete;
  const tail = complete.slice(open);
  if (tail.includes("]]")) return complete;
  return "[[DOWNLOAD".startsWith(tail) || tail.startsWith("[[DOWNLOAD") ? complete.slice(0, open).trimEnd() : complete;
}

/** "3 KB", "1.5 MB"; empty when the size is not known. */
export function formatFileSize(bytes: number): string {
  if (!bytes) return "";
  if (bytes < 1024 * 1024) return `${Math.ceil(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

const WHOLE_MARKER = new RegExp(`^${MARKER.source}$`);

/** The markers in a tool result's `download_markers` list (its JSON text), in
 * order; anything in that list that is not a marker is left out. */
export function downloadMarkersOf(resultText: string): string[] {
  const text = resultText.trim();
  if (!text.startsWith("{")) return [];
  let data: unknown;
  try {
    data = JSON.parse(text);
  } catch {
    return [];
  }
  const list = typeof data === "object" && data !== null ? (data as { download_markers?: unknown }).download_markers : undefined;
  return Array.isArray(list) ? list.filter((m): m is string => typeof m === "string" && WHOLE_MARKER.test(m.trim())).map((m) => m.trim()) : [];
}
