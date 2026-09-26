import { defineStore } from "pinia";
import { computed, ref, watch } from "vue";
import { chatsClient } from "../api/ChatsClient";
import type { CommandInfo } from "../api/CommandsClient";
import type { ChatMessage, Conversation, TurnEvent } from "../api/types";
import {
  LegacyLocalChats,
  ServerConversationStorage,
  type ConversationStorage,
} from "../services/ConversationStorage";
import { SlashCommandRunner } from "../services/slashCommands";
import { watchTurn } from "../services/turnStream";
import { errorMessage } from "../utils/errors";
import { toolTitle } from "../utils/toolTitles";
import { useAgentsStore } from "./agents";
import { useAuthStore } from "./auth";

const TITLE_MAX_CHARS = 60;
// While a chat other than the open one is still being answered, the list is
// re-read this often so its spinner clears when it finishes.
const BACKGROUND_POLL_MS = 5000;

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

/** The account's chats and the live view of the open chat's answer.
 *
 * ember_api runs every turn itself: sending a question starts it there, and
 * this store only watches its events. So an answer keeps going, is saved and
 * counts toward the usage limits even if this page closes; reopening the chat
 * picks the stream back up.
 *
 * Renames and deletes change the screen first and are sent through one
 * queue, in order. A failed one stops the queue and shows `saveError`;
 * retrySave() resends it and everything behind it. */
export const useChatStore = defineStore("chat", () => {
  const agents = useAgentsStore();
  const auth = useAuthStore();
  const storage: ConversationStorage = new ServerConversationStorage();

  const conversations = ref<Conversation[]>([]);
  // null = a fresh chat; it's created in ember_api by its first question.
  const activeId = ref<string | null>(null);
  const listLoading = ref(false);
  const loadError = ref("");
  const saveError = ref("");
  const sendError = ref("");
  const chatLoading = ref(false);
  // Summarize / clear in progress for the open chat.
  const working = ref("");

  const streaming = ref(""); // the open chat's answer, as it arrives
  const activity = ref(""); // its current tool step, if any
  const starting = ref(false); // question sent, turn not confirmed yet
  // "Terse replies": asks ai_agent for short answers. Remembered per account.
  const caveman = ref(false);
  // Slash commands (tools.use): the runner caches the command list and tool
  // schemas, so it's replaced per account.
  let commandRunner = new SlashCommandRunner();
  const commands = ref<CommandInfo[]>([]);

  // Bumped on every account change: results of loads and saves started for
  // the previous account are ignored when they arrive.
  let generation = 0;
  let pending: SaveOp[] = [];
  let saving = false;
  // The one live event stream (the open chat's); aborted on switching away.
  let watcher: AbortController | null = null;
  let pollTimer: ReturnType<typeof setTimeout> | null = null;

  const active = computed(() => conversations.value.find((c) => c.id === activeId.value) ?? null);
  const messages = computed<ChatMessage[]>(() => active.value?.messages ?? []);
  /** The open chat is being answered (or its question is on its way). */
  const busy = computed(() => starting.value || active.value?.running === true);
  /** Newest activity first, for the sidebar. */
  const sortedConversations = computed(() =>
    [...conversations.value].sort((a, b) => b.updatedAt - a.updatedAt),
  );
  /** How full the agent's context is, from the last answer that said so. */
  const contextUsage = computed<{ tokens: number; window: number } | null>(() => {
    for (let i = messages.value.length - 1; i >= 0; i -= 1) {
      const m = messages.value[i]!;
      if (m.kind === "summary" || m.kind === "log_attachment") return null;
      if (m.context_tokens && m.context_window) return { tokens: m.context_tokens, window: m.context_window };
    }
    return null;
  });

  function find(id: string): Conversation | undefined {
    return conversations.value.find((c) => c.id === id);
  }

  // --- saving renames / deletes ------------------------------------------------

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

  /** Re-reads the list, keeping loaded transcripts of chats that didn't
   * change. A chat whose answer finished in the background is re-fetched
   * when next opened. */
  async function loadList(): Promise<void> {
    const started = generation;
    const accountId = auth.account?.id;
    if (accountId === undefined) return;
    listLoading.value = true;
    loadError.value = "";
    try {
      await importLegacy(accountId);
      const fresh = await storage.list();
      if (started !== generation) return;
      conversations.value = fresh.map((c) => {
        const known = find(c.id);
        const unchanged = known?.messagesLoaded && known.updatedAt === c.updatedAt && !known.running;
        if (c.id === activeId.value && known) return { ...known, title: c.title, running: known.running };
        return unchanged ? { ...known, title: c.title } : c;
      });
    } catch (err) {
      if (started === generation) loadError.value = errorMessage(err);
    } finally {
      if (started === generation) listLoading.value = false;
      scheduleBackgroundPoll();
    }
  }

  function scheduleBackgroundPoll(): void {
    if (pollTimer !== null) clearTimeout(pollTimer);
    pollTimer = null;
    const backgroundRunning = conversations.value.some((c) => c.running && c.id !== activeId.value);
    if (backgroundRunning) pollTimer = setTimeout(() => void loadList(), BACKGROUND_POLL_MS);
  }

  /** Fetches a chat's transcript; watches its answer if one is running. */
  async function loadChat(id: string): Promise<void> {
    const started = generation;
    chatLoading.value = true;
    loadError.value = "";
    try {
      const detail = await storage.detail(id);
      const conversation = find(id);
      if (started !== generation || !conversation) return;
      conversation.messages = detail.messages;
      conversation.messagesLoaded = true;
      conversation.running = detail.running;
      if (detail.running && id === activeId.value) follow(id, 0);
    } catch (err) {
      if (started === generation) loadError.value = errorMessage(err);
    } finally {
      if (started === generation) chatLoading.value = false;
    }
  }

  // Load the account's chats once it may chat; on logout, a user switch or
  // losing chat.use, drop them from memory and stop watching.
  watch(
    () => (auth.hasPermission("chat.use") ? (auth.account?.id ?? null) : null),
    (accountId) => {
      unfollow();
      generation += 1;
      pending = [];
      saveError.value = "";
      loadError.value = "";
      sendError.value = "";
      activeId.value = null;
      conversations.value = [];
      caveman.value = accountId !== null && readPreference(cavemanKey(accountId)) === "1";
      commandRunner = new SlashCommandRunner();
      commands.value = [];
      if (accountId !== null) void loadList();
      else if (pollTimer !== null) clearTimeout(pollTimer);
    },
    { immediate: true },
  );

  // --- watching the open chat's answer ------------------------------------------

  function onEvent(event: TurnEvent): void {
    switch (event.type) {
      case "snapshot":
        streaming.value = event.text;
        activity.value = event.activity ? `${event.activity} ...` : "";
        break;
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
      case "summarized":
        activity.value = "";
        break;
      case "summarizing":
        activity.value = "summarizing earlier messages ...";
        break;
      case "cancelling":
        activity.value = "stopping ...";
        break;
    }
  }

  function unfollow(): void {
    watcher?.abort();
    watcher = null;
    streaming.value = "";
    activity.value = "";
  }

  /** Streams chat `id`'s running answer into `streaming` until it ends,
   * then reloads the chat (ember_api's saved copy is the real one). */
  function follow(id: string, after: number): void {
    unfollow();
    const controller = new AbortController();
    watcher = controller;
    const started = generation;
    void watchTurn(id, after, onEvent, controller.signal)
      .then(async (end) => {
        if (end === "aborted" || started !== generation) return;
        const conversation = find(id);
        if (conversation) conversation.running = false;
        if (watcher === controller) unfollow();
        await loadChat(id);
      })
      .catch((err: unknown) => {
        if (started !== generation || controller.signal.aborted) return;
        if (watcher === controller) unfollow();
        loadError.value = `Lost the live answer: ${errorMessage(err)}. Reopen the chat to see it.`;
      })
      .finally(scheduleBackgroundPoll);
  }

  // --- sending --------------------------------------------------------------

  /** For the input's suggestions; quietly empty without tools.use or when
   * mcp_server is down (typing a command then shows the error). */
  async function loadCommands(): Promise<void> {
    if (!auth.hasPermission("tools.use")) return;
    const started = generation;
    try {
      const list = await commandRunner.list();
      if (started === generation) commands.value = list;
    } catch {
      if (started === generation) commands.value = [];
    }
  }

  /** "/..." runs an mcp_server tool directly (no AI); the call and its
   * result are added to the chat. */
  async function runCommand(text: string): Promise<void> {
    if (!auth.hasPermission("tools.use")) {
      sendError.value = "Slash commands need the tools.use permission.";
      return;
    }
    working.value = "Running command ...";
    const started = generation;
    try {
      const result = await commandRunner.run(text);
      if (started !== generation) return;
      await appendMessages(
        [
          { role: "user", kind: "command", content: text },
          { role: "assistant", kind: "command", content: result },
        ],
        text,
      );
    } finally {
      if (started === generation) working.value = "";
    }
  }

  /** Asks the selected agent. ember_api saves the question and runs the
   * turn; this page shows it arriving. A leading "/" runs a command instead. */
  async function send(question: string): Promise<void> {
    if (!question || busy.value || chatLoading.value || working.value) return;
    // Its transcript failed to load: what's shown isn't the chat.
    if (active.value?.messagesLoaded === false) return;
    sendError.value = "";
    if (question.startsWith("/")) return runCommand(question);
    const agent = agents.selected;
    if (!agent) {
      sendError.value = "No ai_agent is available.";
      return;
    }

    let conversation = active.value;
    const isNew = conversation === null;
    if (!conversation) {
      const now = Date.now();
      conversations.value.push({
        id: crypto.randomUUID(),
        title: titleFrom(question),
        messages: [],
        messagesLoaded: true,
        agentId: agent.id,
        createdAt: now,
        updatedAt: now,
      });
      conversation = conversations.value[conversations.value.length - 1]!; // the reactive copy
      activeId.value = conversation.id;
    }
    const id = conversation.id;
    conversation.messages.push({ role: "user", content: question });
    conversation.agentId = agent.id;
    starting.value = true;
    const started = generation;
    try {
      const turn = await chatsClient.startTurn(id, {
        question,
        agent_id: agent.id,
        caveman: caveman.value,
        title: conversation.title,
      });
      if (started !== generation) return;
      conversation.running = true;
      conversation.updatedAt = Date.parse(`${turn.chat.updated_at}Z`);
      if (activeId.value === id) follow(id, turn.sequence);
    } catch (err) {
      if (started !== generation) return;
      // Not saved (limit reached, agent gone ...): take the question back.
      conversation.messages.pop();
      if (isNew) {
        conversations.value = conversations.value.filter((c) => c.id !== id);
        if (activeId.value === id) activeId.value = null;
      }
      sendError.value = errorMessage(err);
    } finally {
      starting.value = false;
    }
  }

  /** Asks ember_api to stop the open chat's answer; the stream then ends
   * with whatever had arrived. */
  async function stop(): Promise<void> {
    const conversation = active.value;
    if (!conversation?.running) return;
    try {
      await chatsClient.cancel(conversation.id);
    } catch (err) {
      sendError.value = errorMessage(err);
    }
  }

  // --- chat list actions ----------------------------------------------------

  function newChat(): void {
    unfollow();
    sendError.value = "";
    activeId.value = null;
    scheduleBackgroundPoll();
  }

  async function selectChat(id: string): Promise<void> {
    const conversation = find(id);
    if (!conversation || id === activeId.value) return;
    unfollow();
    sendError.value = "";
    activeId.value = id;
    // Reopening a chat switches back to the agent it was last talking to.
    if (conversation.agentId) agents.select(conversation.agentId);
    scheduleBackgroundPoll();
    if (conversation.messagesLoaded === false || conversation.running) await loadChat(id);
  }

  function deleteChat(id: string): void {
    if (id === activeId.value) {
      unfollow();
      activeId.value = null;
    }
    conversations.value = conversations.value.filter((c) => c.id !== id);
    enqueue(() => storage.remove(id));
  }

  function setCaveman(on: boolean): void {
    caveman.value = on;
    const accountId = auth.account?.id;
    if (accountId !== undefined) writePreference(cavemanKey(accountId), on ? "1" : "0");
  }

  /** Blank titles are ignored; the chat keeps its old one. */
  function renameChat(id: string, title: string): void {
    const conversation = find(id);
    const trimmed = title.replace(/\s+/g, " ").trim().slice(0, 120);
    if (!conversation || !trimmed || trimmed === conversation.title) return;
    conversation.title = trimmed;
    enqueue(() => storage.rename(id, trimmed));
  }

  function deleteAllChats(): void {
    unfollow();
    conversations.value = [];
    activeId.value = null;
    enqueue(() => storage.removeAll());
  }

  /** Runs summarize or clear on the open chat; both replace its messages
   * with what ember_api returns. */
  async function rewrite(label: string, call: (id: string) => Promise<{ messages: ChatMessage[] }>): Promise<void> {
    const conversation = active.value;
    if (!conversation || busy.value || working.value) return;
    sendError.value = "";
    working.value = label;
    const started = generation;
    try {
      const chat = await call(conversation.id);
      if (started !== generation) return;
      conversation.messages = chat.messages;
      conversation.messagesLoaded = true;
      conversation.updatedAt = Date.now();
    } catch (err) {
      if (started === generation) sendError.value = errorMessage(err);
    } finally {
      if (started === generation) working.value = "";
    }
  }

  /** Condenses the history into a summary the agent keeps as its memory. */
  function summarizeChat(): Promise<void> {
    return rewrite("Summarizing ...", (id) => chatsClient.summarize(id, agents.selected?.id ?? null));
  }

  /** Starts the conversation afresh; old messages stay as a collapsed log. */
  function clearChat(): Promise<void> {
    return rewrite("Clearing ...", (id) => chatsClient.clear(id));
  }

  /** Adds messages ember_api didn't produce itself (slash commands). */
  async function appendMessages(extra: ChatMessage[], titleSeed: string): Promise<void> {
    let conversation = active.value;
    if (!conversation) {
      const now = Date.now();
      conversations.value.push({
        id: crypto.randomUUID(),
        title: titleFrom(titleSeed),
        messages: [],
        messagesLoaded: true,
        createdAt: now,
        updatedAt: now,
      });
      conversation = conversations.value[conversations.value.length - 1]!;
      activeId.value = conversation.id;
    }
    conversation.messages.push(...extra);
    conversation.updatedAt = Date.now();
    const { id, title } = conversation;
    enqueue(async () => {
      await chatsClient.append(id, title, extra);
    });
  }

  return {
    activeId,
    active,
    sortedConversations,
    messages,
    streaming,
    activity,
    busy,
    working,
    contextUsage,
    listLoading,
    chatLoading,
    loadError,
    saveError,
    sendError,
    send,
    stop,
    newChat,
    selectChat,
    deleteChat,
    renameChat,
    caveman,
    setCaveman,
    clearChat,
    summarizeChat,
    deleteAllChats,
    appendMessages,
    commands,
    loadCommands,
    retrySave,
    reload: loadList,
  };
});
