import { apiRequest } from "./http";

export interface AttachmentText {
  filename: string;
  text: string;
  char_count: number;
  truncated: boolean;
}

/** Same limit ember_api enforces; checked here first to skip the upload. */
export const MAX_ATTACHMENT_BYTES = 15 * 1024 * 1024;

/** The file's bytes as base64 (ember_api takes JSON only). */
function toBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const url = String(reader.result);
      resolve(url.slice(url.indexOf(",") + 1)); // drop "data:<type>;base64,"
    };
    reader.onerror = () => reject(reader.error ?? new Error("Could not read the file"));
    reader.readAsDataURL(file);
  });
}

export const attachmentsClient = {
  /** Text ember_api extracted from the file; the file itself isn't kept. */
  async text(file: File): Promise<AttachmentText> {
    if (file.size > MAX_ATTACHMENT_BYTES) {
      throw new Error(`Too large - the limit is ${MAX_ATTACHMENT_BYTES / (1024 * 1024)} MB`);
    }
    return apiRequest<AttachmentText>("POST", "/api/attachments/text", {
      filename: file.name,
      data: await toBase64(file),
    });
  },
};
