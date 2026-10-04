/** Attached files travel inside the question text, one delimited block per
 * file after what was typed - the same markers chat_app writes, so the
 * agent sees the same thing and saved chats render the same in both apps.
 * The chat view pulls the blocks back out to show them collapsed. */

import type { ChatMessage } from "../api/types";

export interface AttachmentBlock {
  filename: string;
  chars: number;
  truncated: boolean;
  text: string;
}

const BLOCK = /\[\[ATTACHMENT filename="([^"]*)" chars="(\d+)" truncated="(true|false)"\]\]\n([\s\S]*?)\n\[\[\/ATTACHMENT\]\]/g;

export function attachmentBlock(a: AttachmentBlock): string {
  const name = a.filename.replace(/"/g, "'");
  return `[[ATTACHMENT filename="${name}" chars="${a.chars}" truncated="${a.truncated}"]]\n${a.text}\n[[/ATTACHMENT]]`;
}

/** What stands in for the typed text when a question is only attached files. */
export const FILE_ONLY_QUESTION = "Please review the attached file(s).";

/** The question as sent: the typed text, then every attachment. */
export function withAttachments(question: string, attachments: AttachmentBlock[]): string {
  if (!attachments.length) return question;
  const typed = question || FILE_ONLY_QUESTION;
  return [typed, ...attachments.map(attachmentBlock)].join("\n\n");
}

/** Splits a saved question back into what was typed and its attachments. */
export function splitAttachments(text: string): { text: string; attachments: AttachmentBlock[] } {
  if (!text.includes("[[ATTACHMENT ")) return { text, attachments: [] };
  const attachments: AttachmentBlock[] = [];
  const rest = text.replace(BLOCK, (_m, filename: string, chars: string, truncated: string, body: string) => {
    attachments.push({ filename, chars: Number(chars), truncated: truncated === "true", text: body });
    return "";
  });
  return { text: rest.trim(), attachments };
}

/** What the user typed in a chat, oldest first, for the input's up and down
 * arrows: questions and slash commands, without their attached files. */
export function questionHistory(messages: ChatMessage[]): string[] {
  return messages
    .filter((m) => m.role === "user" && m.kind !== "summary" && m.kind !== "log_attachment")
    .map((m) => splitAttachments(m.content).text)
    .filter((text) => text !== "");
}
