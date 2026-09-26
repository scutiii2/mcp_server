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
  /** ember_api is writing an answer for it right now. */
  running: boolean;
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

export interface TurnStart {
  question: string;
  agent_id: string;
  caveman: boolean;
  /** Used only when this turn creates the chat. */
  title?: string;
}

export interface TurnStarted {
  chat: ChatSummary;
  /** Watch /events with after=this for only newer events. */
  sequence: number;
}

const path = (id: string) => `/api/chats/${encodeURIComponent(id)}`;

/** ember_api's /api/chats routes (chat.use): this account's chat history
 * and the chat turns ember_api runs. */
export const chatsClient = {
  list: () => apiRequest<ChatSummary[]>("GET", "/api/chats"),
  get: (id: string) => apiRequest<ChatDetail>("GET", path(id)),
  put: (id: string, chat: ChatWrite) => apiRequest<ChatSummary>("PUT", path(id), chat),
  rename: (id: string, title: string) => apiRequest<ChatSummary>("PATCH", path(id), { title }),
  remove: (id: string) => apiRequest<void>("DELETE", path(id)),
  removeAll: () => apiRequest<void>("DELETE", "/api/chats"),
  importChats: (chats: ChatImportItem[]) =>
    apiRequest<{ imported: number; skipped: number }>("POST", "/api/chats/import", { chats }),
  /** Saves the question and starts the answer in ember_api. */
  startTurn: (id: string, turn: TurnStart) => apiRequest<TurnStarted>("POST", `${path(id)}/turns`, turn),
  cancel: (id: string) => apiRequest<{ cancelled: boolean }>("POST", `${path(id)}/cancel`),
  /** Replaces the history with a summary plus the raw log (asks an agent). */
  summarize: (id: string, agentId: string | null) =>
    apiRequest<ChatDetail>("POST", `${path(id)}/summarize`, { agent_id: agentId }),
  /** Starts afresh, keeping the old messages as one raw log. */
  clear: (id: string) => apiRequest<ChatDetail>("POST", `${path(id)}/clear`),
  /** Appends messages (slash-command results), creating the chat if needed. */
  append: (id: string, title: string, messages: ChatMessage[]) =>
    apiRequest<ChatSummary>("POST", `${path(id)}/messages`, { title, messages }),
  eventsUrl: (id: string, after: number) => `${path(id)}/events?after=${after}`,
};
