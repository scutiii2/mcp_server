// Characters Windows (the strictest common file system) refuses in names.
const UNSAFE_FILENAME = /[<>:"/\\|?*\u0000-\u001f]+/g;

/** A download-safe file name from a chat title, never empty. */
export function exportFileName(title: string, extension: string): string {
  const base = title.replace(UNSAFE_FILENAME, "_").replace(/[. ]+$/, "").trim().slice(0, 100);
  return `${base || "chat"}.${extension}`;
}

/** Starts a browser download of `text`; nothing leaves the machine. */
export function downloadText(fileName: string, text: string, mimeType: string): void {
  const url = URL.createObjectURL(new Blob([text], { type: `${mimeType};charset=utf-8` }));
  const link = document.createElement("a");
  link.href = url;
  link.download = fileName;
  link.click();
  // After the click has handed the blob to the download.
  setTimeout(() => URL.revokeObjectURL(url), 0);
}
