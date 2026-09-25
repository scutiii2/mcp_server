import { apiRequest } from "./http";
import type { ChatMessage } from "./types";

/** A chat as ember_api lists it: no transcript. Times are naive UTC. */
export interface ChatSummary {
  id: string;
  title: string;
  agent_id: string | null;
  message_count: number;
  created_at: string;
  updated_at: string;
}

export interface ChatDetail extends ChatSummary {
  messages: ChatMessage[];
}

export interface ChatWrite {
  title: string;
  agent_id: string | null;
  messages: ChatMessage[];
}

export interface ChatImportItem extends ChatWrite {
  id: string;
  /** Milliseconds since the epoch. */
  created_at: number;
  updated_at: number;
}

const path = (id: string) => `/api/chats/${encodeURIComponent(id)}`;

/** ember_api's /api/chats routes (chat.use): this account's chat history. */
export const chatsClient = {
  list: () => apiRequest<ChatSummary[]>("GET", "/api/chats"),
  get: (id: string) => apiRequest<ChatDetail>("GET", path(id)),
  put: (id: string, chat: ChatWrite) => apiRequest<ChatSummary>("PUT", path(id), chat),
  rename: (id: string, title: string) => apiRequest<ChatSummary>("PATCH", path(id), { title }),
  remove: (id: string) => apiRequest<void>("DELETE", path(id)),
  removeAll: () => apiRequest<void>("DELETE", "/api/chats"),
  importChats: (chats: ChatImportItem[]) =>
    apiRequest<{ imported: number; skipped: number }>("POST", "/api/chats/import", { chats }),
};
