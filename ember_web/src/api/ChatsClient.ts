import { apiRequest } from "./http";
import type { ApprovalDecision, ChatMessage } from "./types";

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
  /** mcp_server extensions whose tools the agent may use. */
  enabled_extensions: string[];
  /** Used only when this turn creates the chat. */
  title?: string;
  /** Regenerate / edit: index of the question this one replaces; it and
   * everything after it are dropped first. */
  truncate_to?: number;
  /** Ask before each tool runs (answers go to `decide`). */
  ask_before_tools?: boolean;
  /** Tools the user already allowed for this chat: they run without asking. */
  allowed_tools?: string[];
}

export interface TurnStarted {
  chat: ChatSummary;
  /** Watch /events with after=this for only newer events. */
  sequence: number;
}

/** Where the query sits in a piece of text, in characters. */
export interface MatchSpan {
  start: number;
  length: number;
}

/** A chat found by search: its title and/or the first matching message. */
export interface ChatSearchHit {
  id: string;
  title: string;
  updated_at: string;
  title_match: MatchSpan | null;
  snippet: (MatchSpan & { text: string }) | null;
  message_index: number | null;
  /** How many messages contain the query. */
  message_matches: number;
}

const path = (id: string) => `/api/chats/${encodeURIComponent(id)}`;

/** ember_api's /api/chats routes (chat.use): this account's chat history
 * and the chat turns ember_api runs. */
export const chatsClient = {
  list: () => apiRequest<ChatSummary[]>("GET", "/api/chats"),
  /** Titles and message text; needs at least 2 characters. */
  search: (query: string) =>
    apiRequest<ChatSearchHit[]>("GET", `/api/chats/search?q=${encodeURIComponent(query)}`),
  get: (id: string) => apiRequest<ChatDetail>("GET", path(id)),
  put: (id: string, chat: ChatWrite) => apiRequest<ChatSummary>("PUT", path(id), chat),
  rename: (id: string, title: string) => apiRequest<ChatSummary>("PATCH", path(id), { title }),
  remove: (id: string) => apiRequest<void>("DELETE", path(id)),
  removeAll: () => apiRequest<void>("DELETE", "/api/chats"),
  importChats: (chats: ChatImportItem[]) =>
    apiRequest<{ imported: number; skipped: number }>("POST", "/api/chats/import", { chats }),
  /** Saves the question and starts the answer in ember_api. */
  startTurn: (id: string, turn: TurnStart) => apiRequest<TurnStarted>("POST", `${path(id)}/turns`, turn),
  /** Answers a tool the running answer waits to run (an approval_request's id). */
  decide: (id: string, stepId: string, decision: ApprovalDecision) =>
    apiRequest<{ decided: boolean }>("POST", `${path(id)}/approvals`, { step_id: stepId, decision }),
  cancel: (id: string) => apiRequest<{ cancelled: boolean }>("POST", `${path(id)}/cancel`),
  /** Replaces the history with a summary plus the raw log (asks an agent). */
  summarize: (id: string, agentId: string | null) =>
    apiRequest<ChatDetail>("POST", `${path(id)}/summarize`, { agent_id: agentId }),
  /** A new chat holding the messages up to and including answer `upto`. */
  branch: (id: string, upto: number) => apiRequest<ChatDetail>("POST", `${path(id)}/branch`, { upto }),
  /** Starts afresh, keeping the old messages as one raw log. */
  clear: (id: string) => apiRequest<ChatDetail>("POST", `${path(id)}/clear`),
  /** Appends messages (slash-command results), creating the chat if needed. */
  append: (id: string, title: string, messages: ChatMessage[]) =>
    apiRequest<ChatSummary>("POST", `${path(id)}/messages`, { title, messages }),
  eventsUrl: (id: string, after: number) => `${path(id)}/events?after=${after}`,
};
