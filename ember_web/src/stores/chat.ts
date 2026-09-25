import { defineStore } from "pinia";
import { computed, ref, watch } from "vue";
import type { AiAgentClient } from "../api/AiAgentClient";
import { chatsClient } from "../api/ChatsClient";
import type { AgentEvent, ChatMessage, Conversation } from "../api/types";
import {
  LegacyLocalChats,
  ServerConversationStorage,
  type ConversationStorage,
} from "../services/ConversationStorage";
import { errorMessage } from "../utils/errors";
import { toolTitle } from "../utils/toolTitles";
import { useAgentsStore } from "./agents";
import { useAuthStore } from "./auth";

const TITLE_MAX_CHARS = 60;

function titleFrom(question: string): string {
  const oneLine = question.replace(/\s+/g, " ").trim();
  return oneLine.length > TITLE_MAX_CHARS ? `${oneLine.slice(0, TITLE_MAX_CHARS - 1)}…` : oneLine;
}

function cavemanKey(accountId: number): string {
  return `ember_web.caveman.${accountId}`;
}

// Per-viewer convenience: blocked storage just means the default (off).
function readPreference(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function writePreference(key: string, value: string): void {
  try {
    localStorage.setItem(key, value);
  } catch {
    // ignore - see readPreference
  }
}

type SaveOp = () => Promise<void>;

/** The account's chats (kept in ember_api) plus the one live turn. Which
 * ai_agent answers comes from the agents store.
 *
 * The screen changes first and the server is told afterwards: every write
 * goes through one queue, so writes reach ember_api in the order they
 * happened. A failed write stops the queue and shows `saveError`; retrySave()
 * resends it and everything queued behind it - nothing is dropped silently. */
export const useChatStore = defineStore("chat", () => {
  const agents = useAgentsStore();
  const auth = useAuthStore();
  const storage: ConversationStorage = new ServerConversationStorage();

  const conversations = ref<Conversation[]>([]);
  // null = a fresh, not-yet-saved chat; it's only created on its first send,
  // so clicking "New chat" repeatedly never leaves empty entries behind.
  const activeId = ref<string | null>(null);
  const listLoading = ref(false);
  const loadError = ref("");
  const saveError = ref("");
  const chatLoading = ref(false);

  const streaming = ref(""); // answer text arriving live
  const activity = ref(""); // current tool step, if any
  const busy = ref(false);
  // The ask() in flight: its id and the agent answering it, so Stop cancels
  // on that agent even if the picker changed since.
  let inFlight: { requestId: string; client: AiAgentClient } | null = null;
  // "Terse replies": asks ai_agent for short answers. Remembered per account.
  const caveman = ref(false);

  // Bumped on every account change: results of loads and saves started for
  // the previous account are ignored when they arrive.
  let generation = 0;
  let pending: SaveOp[] = [];
  let saving = false;

  const active = computed(() => conversations.value.find((c) => c.id === activeId.value) ?? null);
  const messages = computed<ChatMessage[]>(() => active.value?.messages ?? []);
  /** Newest activity first, for the sidebar. */
  const sortedConversations = computed(() =>
    [...conversations.value].sort((a, b) => b.updatedAt - a.updatedAt),
  );

  // --- saving ---------------------------------------------------------------

  function enqueue(op: SaveOp): void {
    pending.push(op);
    void drain();
  }

  async function drain(): Promise<void> {
    if (saving || saveError.value) return;
    saving = true;
    const started = generation;
    try {
      while (pending.length && started === generation) {
        try {
          await pending[0]!();
          if (started === generation) pending.shift();
        } catch (err) {
          if (started === generation) saveError.value = errorMessage(err);
          return;
        }
      }
    } finally {
      saving = false;
    }
  }

  function retrySave(): void {
    saveError.value = "";
    void drain();
  }

  /** Saves the chat as it is when the write actually runs, so a queued
   * save never sends a stale transcript. */
  function saveChat(id: string): void {
    enqueue(async () => {
      const conversation = conversations.value.find((c) => c.id === id);
      if (conversation?.messagesLoaded !== false) {
        if (conversation) await storage.put(conversation);
      }
    });
  }

  // --- loading --------------------------------------------------------------

  /** Uploads chats this browser kept locally (before history moved to the
   * server) once; the local copy goes only after ember_api confirms. */
  async function importLegacy(accountId: number): Promise<void> {
    const legacy = new LegacyLocalChats(accountId);
    const local = legacy.read();
    if (local.length === 0) return;
    try {
      await chatsClient.importChats(
        local.map((c) => ({
          id: c.id,
          title: c.title.trim() || "Untitled chat",
          agent_id: c.agentId ?? null,
          messages: c.messages,
          created_at: c.createdAt,
          updated_at: c.updatedAt,
        })),
      );
      legacy.clear();
    } catch (err) {
      // Kept locally; the next login tries again.
      console.warn("ember_web: importing locally saved chats failed", err);
    }
  }

  async function loadList(): Promise<void> {
    const started = generation;
    const accountId = auth.account?.id;
    if (accountId === undefined) return;
    listLoading.value = true;
    loadError.value = "";
    try {
      await importLegacy(accountId);
      const list = await storage.list();
      if (started === generation) conversations.value = list;
    } catch (err) {
      if (started === generation) loadError.value = errorMessage(err);
    } finally {
      if (started === generation) listLoading.value = false;
    }
  }

  // Load the account's chats once it may chat; on logout, a user switch or
  // losing chat.use, drop them from memory. A turn still streaming for the
  // old user is stopped, so its answer can't land in the new user's list.
  watch(
    () => (auth.hasPermission("chat.use") ? (auth.account?.id ?? null) : null),
    (accountId) => {
      void stop();
      generation += 1;
      pending = [];
      saveError.value = "";
      loadError.value = "";
      activeId.value = null;
      conversations.value = [];
      caveman.value = accountId !== null && readPreference(cavemanKey(accountId)) === "1";
      if (accountId !== null) void loadList();
    },
    { immediate: true },
  );

  // --- the live turn --------------------------------------------------------

  function onEvent(event: AgentEvent): void {
    switch (event.type) {
      case "token":
        streaming.value += event.text;
        break;
      case "token_reset":
        streaming.value = "";
        break;
      case "step_start":
        activity.value = `running ${event.label ?? toolTitle(event.tool)} ...`;
        break;
      case "step_end":
        activity.value = "";
        break;
    }
  }

  /** The active conversation, creating one if the current chat is fresh. */
  function ensureActive(firstQuestion: string): Conversation {
    if (active.value) return active.value;
    const now = Date.now();
    conversations.value.push({
      id: crypto.randomUUID(),
      title: titleFrom(firstQuestion),
      messages: [],
      messagesLoaded: true,
      createdAt: now,
      updatedAt: now,
    });
    const created = conversations.value[conversations.value.length - 1]!; // the reactive copy
    activeId.value = created.id;
    return created;
  }

  /** Sends one question; history is snapshotted before it's appended,
   * since ask() takes the question separately. The question is saved right
   * away and the whole chat again once the answer is in. */
  async function send(question: string): Promise<void> {
    if (!question || busy.value || chatLoading.value) return;
    // Its transcript failed to load: sending now would save over it.
    if (active.value?.messagesLoaded === false) return;
    // Held for the whole turn: switching chats is blocked while busy, but the
    // answer must land in this conversation regardless.
    const turnAgent = agents.current();
    const conversation = ensureActive(question);
    if (!turnAgent) {
      conversation.messages.push({ role: "user", content: question });
      conversation.messages.push({ role: "assistant", content: "error: no ai_agent is available" });
      saveChat(conversation.id);
      return;
    }
    const { agent, client } = turnAgent;
    conversation.agentId = agent.id;
    const history = [...conversation.messages];
    conversation.messages.push({ role: "user", content: question });
    conversation.updatedAt = Date.now();
    saveChat(conversation.id);
    busy.value = true;
    const requestId = crypto.randomUUID();
    inFlight = { requestId, client };
    try {
      const result = await client.ask(question, history, requestId, onEvent, { caveman: caveman.value });
      // On cancel, keep whatever had streamed in before ai_agent stopped.
      const content =
        result.cancelled && streaming.value
          ? `${streaming.value}\n\n${result.response}`
          : result.response;
      conversation.messages.push({ role: "assistant", content });
    } catch (err) {
      conversation.messages.push({ role: "assistant", content: `error: ${err}` });
    } finally {
      inFlight = null;
      streaming.value = "";
      activity.value = "";
      busy.value = false;
      conversation.updatedAt = Date.now();
      saveChat(conversation.id); // once per finished turn, not per streamed token
    }
  }

  /** Stops the turn in flight; send()'s own result handling finishes up. */
  async function stop(): Promise<void> {
    if (!inFlight) return;
    activity.value = "stopping ...";
    await inFlight.client.cancel(inFlight.requestId);
  }

  // --- chat list actions ----------------------------------------------------

  function newChat(): void {
    if (busy.value) return;
    activeId.value = null;
  }

  async function selectChat(id: string): Promise<void> {
    if (busy.value) return;
    const conversation = conversations.value.find((c) => c.id === id);
    if (!conversation) return;
    activeId.value = id;
    // Reopening a chat switches back to the agent it was last talking to.
    if (conversation.agentId) agents.select(conversation.agentId);
    if (conversation.messagesLoaded !== false) return;

    const started = generation;
    chatLoading.value = true;
    loadError.value = "";
    try {
      const loaded = await storage.messages(id);
      if (started !== generation) return;
      conversation.messages = loaded;
      conversation.messagesLoaded = true;
    } catch (err) {
      if (started === generation) loadError.value = errorMessage(err);
    } finally {
      if (started === generation) chatLoading.value = false;
    }
  }

  function deleteChat(id: string): void {
    if (busy.value && id === activeId.value) return; // its answer is still arriving
    conversations.value = conversations.value.filter((c) => c.id !== id);
    if (activeId.value === id) activeId.value = null;
    enqueue(() => storage.remove(id));
  }

  function setCaveman(on: boolean): void {
    caveman.value = on;
    const accountId = auth.account?.id;
    if (accountId !== undefined) writePreference(cavemanKey(accountId), on ? "1" : "0");
  }

  /** Blank titles are ignored; the chat keeps its old one. */
  function renameChat(id: string, title: string): void {
    const conversation = conversations.value.find((c) => c.id === id);
    const trimmed = title.replace(/\s+/g, " ").trim().slice(0, 120);
    if (!conversation || !trimmed || trimmed === conversation.title) return;
    conversation.title = trimmed;
    enqueue(() => storage.rename(id, trimmed));
  }

  /** Empties a chat's messages but keeps the chat (title, agent). */
  function clearChat(id: string): void {
    if (busy.value && id === activeId.value) return;
    const conversation = conversations.value.find((c) => c.id === id);
    if (!conversation || conversation.messages.length === 0) return;
    conversation.messages = [];
    conversation.messagesLoaded = true;
    conversation.updatedAt = Date.now();
    saveChat(id);
  }

  function deleteAllChats(): void {
    if (busy.value) return; // the active chat's answer is still arriving
    conversations.value = [];
    activeId.value = null;
    enqueue(() => storage.removeAll());
  }

  return {
    activeId,
    active,
    sortedConversations,
    messages,
    streaming,
    activity,
    busy,
    listLoading,
    chatLoading,
    loadError,
    saveError,
    send,
    stop,
    newChat,
    selectChat,
    deleteChat,
    renameChat,
    caveman,
    setCaveman,
    clearChat,
    deleteAllChats,
    retrySave,
    reload: loadList,
  };
});
