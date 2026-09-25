import type { ChatMessage, Conversation } from "../api/types";

/** Where conversations are kept. The chat store depends only on this, so a
 * server-backed implementation can replace LocalConversationStorage later. */
export interface ConversationStorage {
  load(): Conversation[];
  save(conversations: Conversation[]): void;
}

const STORAGE_KEY = "ember_web.conversations.v1";

/** Keeps every conversation in this browser's localStorage as one JSON array.
 * Storage can be missing or throw (private window, blocked site data, quota
 * full): reads then return [] and writes are dropped, so chats simply stay
 * in memory for the session instead of breaking the app. */
export class LocalConversationStorage implements ConversationStorage {
  load(): Conversation[] {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (!raw) return [];
      const parsed: unknown = JSON.parse(raw);
      return Array.isArray(parsed) ? parsed.filter(isConversation) : [];
    } catch (err) {
      console.warn("ember_web: could not read saved conversations", err);
      return [];
    }
  }

  save(conversations: Conversation[]): void {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(conversations));
    } catch (err) {
      console.warn("ember_web: could not save conversations", err);
    }
  }
}

/** Drops anything malformed (hand-edited storage, an older format) instead
 * of letting one bad entry break the whole list. */
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
