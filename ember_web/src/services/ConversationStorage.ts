import { chatsClient, type ChatSummary } from "../api/ChatsClient";
import { ApiError } from "../api/http";
import type { ChatMessage, Conversation } from "../api/types";

/** Where conversations are kept. The chat store depends only on this. One
 * call per change, since the store only ever changes one chat at a time.
 * (New messages arrive through ember_api's turns, not through here.) */
export interface ConversationStorage {
  /** Every chat, newest first, with `messages` not loaded yet. */
  list(): Promise<Conversation[]>;
  /** A chat's transcript, and whether an answer is being written for it. */
  detail(id: string): Promise<{ messages: ChatMessage[]; running: boolean }>;
  rename(id: string, title: string): Promise<void>;
  remove(id: string): Promise<void>;
  removeAll(): Promise<void>;
}

/** ember_api's per-account chat history. */
export class ServerConversationStorage implements ConversationStorage {
  async list(): Promise<Conversation[]> {
    return (await chatsClient.list()).map(fromSummary);
  }

  async detail(id: string): Promise<{ messages: ChatMessage[]; running: boolean }> {
    const chat = await chatsClient.get(id);
    return { messages: chat.messages, running: chat.running };
  }

  async rename(id: string, title: string): Promise<void> {
    await ignoreMissing(chatsClient.rename(id, title));
  }

  async remove(id: string): Promise<void> {
    await ignoreMissing(chatsClient.remove(id));
  }

  async removeAll(): Promise<void> {
    await chatsClient.removeAll();
  }
}

/** A chat that was never saved (deleted before its first write reached the
 * server) or is already gone: nothing left to do. */
async function ignoreMissing(request: Promise<unknown>): Promise<void> {
  try {
    await request;
  } catch (err) {
    if (!(err instanceof ApiError && err.status === 404)) throw err;
  }
}

function fromSummary(s: ChatSummary): Conversation {
  return {
    id: s.id,
    title: s.title,
    messages: [],
    messagesLoaded: false,
    messageCount: s.message_count,
    running: s.running,
    agentId: s.agent_id ?? undefined,
    createdAt: Date.parse(`${s.created_at}Z`),
    updatedAt: Date.parse(`${s.updated_at}Z`),
  };
}

const LEGACY_PREFIX = "ember_web.conversations.v1";

/** Chats this browser kept in localStorage before history moved to
 * ember_api. Read once per account to upload them, then removed. Storage
 * can be missing or throw (private window, blocked site data): that just
 * means there's nothing to import. */
export class LegacyLocalChats {
  private readonly key: string;

  constructor(accountId: number) {
    this.key = `${LEGACY_PREFIX}.${accountId}`;
  }

  read(): Conversation[] {
    try {
      // Chats saved before login existed had no owner; never imported.
      localStorage.removeItem(LEGACY_PREFIX);
      const raw = localStorage.getItem(this.key);
      if (!raw) return [];
      const parsed: unknown = JSON.parse(raw);
      return Array.isArray(parsed) ? parsed.filter(isConversation) : [];
    } catch (err) {
      console.warn("ember_web: could not read locally saved chats", err);
      return [];
    }
  }

  /** Only after the server confirmed the import. */
  clear(): void {
    try {
      localStorage.removeItem(this.key);
    } catch {
      // storage unavailable - nothing to clear
    }
  }
}

/** Drops anything malformed (hand-edited storage, an older format) instead
 * of letting one bad entry break the import. */
function isConversation(value: unknown): value is Conversation {
  if (typeof value !== "object" || value === null) return false;
  const c = value as Record<string, unknown>;
  return (
    typeof c.id === "string" &&
    typeof c.title === "string" &&
    typeof c.createdAt === "number" &&
    typeof c.updatedAt === "number" &&
    (c.agentId === undefined || typeof c.agentId === "string") &&
    Array.isArray(c.messages) &&
    c.messages.every(isChatMessage)
  );
}

function isChatMessage(value: unknown): value is ChatMessage {
  if (typeof value !== "object" || value === null) return false;
  const m = value as Record<string, unknown>;
  return (m.role === "user" || m.role === "assistant") && typeof m.content === "string";
}
