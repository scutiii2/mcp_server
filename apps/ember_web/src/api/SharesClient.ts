import { apiRequest } from "./http";

/** A share link as the account's own list shows it: never the token. Times are naive UTC. */
export interface ShareInfo {
  id: number;
  chat_id: string;
  title: string;
  message_count: number;
  created_at: string;
  /** null: never expires. */
  expires_at: string | null;
}

/** The response that makes a link: the only time its token exists. */
export interface ShareCreated extends ShareInfo {
  token: string;
}

/** What a link shows anyone who opens it: questions and plain answers only. */
export interface SharedChatView {
  title: string;
  messages: { role: "user" | "assistant"; content: string }[];
  created_at: string;
  expires_at: string | null;
}

/** Days a link works for; null: forever. The server accepts only these. */
export type ShareExpiry = 1 | 7 | 30 | null;

/** ember_api's share-link routes. Making needs chat.use + chat.share; listing and revoking need chat.use;
 * `read` is public (no login), so it may be called by anyone. */
export const sharesClient = {
  create: (chatId: string, expiresInDays: ShareExpiry) =>
    apiRequest<ShareCreated>("POST", `/api/chats/${encodeURIComponent(chatId)}/shares`, {
      expires_in_days: expiresInDays,
    }),
  /** Active links, newest first; `chatId` narrows them to one chat. */
  list: (chatId?: string) =>
    apiRequest<ShareInfo[]>("GET", chatId ? `/api/shares?chat_id=${encodeURIComponent(chatId)}` : "/api/shares"),
  revoke: (id: number) => apiRequest<void>("DELETE", `/api/shares/${id}`),
  read: (token: string) => apiRequest<SharedChatView>("GET", `/api/shared/${encodeURIComponent(token)}`),
};
