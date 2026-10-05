import { defineStore } from "pinia";
import { computed, ref, watch } from "vue";
import { chatsClient, type ChatSearchHit } from "../api/ChatsClient";
import { settingsClient } from "../api/SettingsClient";
import type { CommandInfo } from "../api/CommandsClient";
import { ApiError } from "../api/http";
import type {
  ActiveAgent,
  ApprovalDecision,
  ChatMessage,
  Conversation,
  JsonSchema,
  PendingApproval,
  ToolStep,
  TurnEvent,
} from "../api/types";
import {
  LegacyLocalChats,
  ServerConversationStorage,
  type ConversationStorage,
} from "../services/ConversationStorage";
import { chimeIfAway } from "../composables/useNotify";
import { SlashCommandRunner } from "../services/slashCommands";
import { watchTurn } from "../services/turnStream";
import { splitAttachments, withAttachments } from "../utils/attachments";
import { errorMessage } from "../utils/errors";
import { toolTitle } from "../utils/toolTitles";
import { useAuthStore } from "./auth";

const TITLE_MAX_CHARS = 60;
// While a chat other than the open one is still being answered, the list is
// re-read this often so its spinner clears when it finishes.
const BACKGROUND_POLL_MS = 5000;
// Search waits for a pause in typing; ember_api refuses shorter queries.
const SEARCH_DEBOUNCE_MS = 250;
const SEARCH_MIN_CHARS = 2;

function titleFrom(question: string): string {
  // What was typed, not the attached files' text.
  const { text, attachments } = splitAttachments(question);
  const oneLine = (text || attachments[0]?.filename || question).replace(/\s+/g, " ").trim();
  return oneLine.length > TITLE_MAX_CHARS ? `${oneLine.slice(0, TITLE_MAX_CHARS - 1)}…` : oneLine;
}

/** Key of a live step (or of what a delegated agent said for one): two agents
 * may reuse a step id, so the agent is part of it. */
export function stepKey(agentId: string | undefined, id: string): string {
  return `${agentId ?? ""}\t${id}`;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function cavemanKey(accountId: number): string {
  return `ember_web.caveman.${accountId}`;
}

function chimeKey(accountId: number): string {
  return `ember_web.chime.${accountId}`;
}

function askBeforeToolsKey(accountId: number): string {
  return `ember_web.askBeforeTools.${accountId}`;
}

function allowedToolsKey(accountId: number): string {
  return `ember_web.allowedTools.${accountId}`;
}

// ember_api accepts at most this many allowed tools with a question.
const MAX_ALLOWED_TOOLS = 200;

/** The tools allowed for each chat ("Allow for this chat"), from storage.
 * Anything malformed is dropped rather than trusted. */
function readAllowedTools(accountId: number): Record<string, string[]> {
  try {
    const parsed: unknown = JSON.parse(readPreference(allowedToolsKey(accountId)) ?? "{}");
    if (!isRecord(parsed)) return {};
    const result: Record<string, string[]> = {};
    for (const [chatId, tools] of Object.entries(parsed)) {
      if (Array.isArray(tools)) {
        const names = tools.filter((t): t is string => typeof t === "string").slice(0, MAX_ALLOWED_TOOLS);
        if (names.length) result[chatId] = names;
      }
    }
    return result;
  } catch {
    return {};
  }
}

function extensionsKey(accountId: number): string {
  return `ember_web.extensions.${accountId}`;
}

function readExtensions(accountId: number): string[] {
  try {
    const parsed: unknown = JSON.parse(readPreference(extensionsKey(accountId)) ?? "[]");
    return Array.isArray(parsed) ? parsed.filter((x): x is string => typeof x === "string") : [];
  } catch {
    return [];
  }
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
  const auth = useAuthStore();
  const storage: ConversationStorage = new ServerConversationStorage();

  const conversations = ref<Conversation[]>([]);
  // null = a fresh chat; it's created in ember_api by its first question.
  const activeId = ref<string | null>(null);
  const listLoading = ref(false);
  // The account's chat list has been fetched (or failed) at least once, so a
  // chat id missing from it is really missing, not just not loaded yet.
  const listReady = ref(false);
  const loadError = ref("");
  const saveError = ref("");
  const sendError = ref("");
  const chatLoading = ref(false);
  // Summarize / clear in progress for the open chat.
  const working = ref("");

  const streaming = ref(""); // the open chat's answer, as it arrives
  const activity = ref(""); // its current tool step, if any
  const liveSteps = ref<ToolStep[]>([]); // the tools it ran so far
  const activeAgents = ref<ActiveAgent[]>([]); // delegated agents working on the answer, outermost first
  const agentText = ref<Record<string, string>>({}); // a delegated agent's streamed text, by stepKey(that agent, delegate step id)
  const liveStepIndex = new Map<string, number>(); // by stepKey: two agents may reuse a step id
  const starting = ref(false); // question sent, turn not confirmed yet
  // "Terse replies": asks ai_agent for short answers. Remembered per account.
  const caveman = ref(false);
  // "Ask before running tools": each tool the agent wants to run waits for the
  // user's answer. Off by default; remembered per account.
  const askBeforeTools = ref(false);
  // The administrator requires approval for every tool: the checkbox is locked on,
  // nothing is pre-allowed and "allow for this chat" is not offered. ember_api
  // enforces it either way; this only keeps the page honest.
  const forceToolApproval = ref(false);
  // A short chime when an answer arrives while the page is out of sight. On
  // by default; remembered per account.
  const chime = ref(true);
  // When the running answer (or command) began, for the clock; null otherwise.
  const clockStart = ref<number | null>(null);
  // How the watched turn ended, from its final event: only an answer chimes.
  let turnOutcome: "answered" | "stopped" | "failed" | null = null;
  // Tools the user chose "Allow for this chat" for, by chat id: they run
  // without asking again. Remembered per account (in this browser).
  const allowedTools = ref<Record<string, string[]>>({});
  // The open chat's tool runs that wait for an answer, and the ones whose
  // answer was sent but not yet confirmed by the agent.
  const pendingApprovals = ref<PendingApproval[]>([]);
  const deciding = ref<string[]>([]);
  // mcp_server extensions whose tools the agent (and slash commands) may use.
  // None by default: a newly added extension is never in scope unasked.
  // Remembered per account.
  const enabledExtensions = ref<string[]>([]);
  // Slash commands (tools.use): the runner caches the command list and tool
  // schemas, so it's replaced per account.
  let commandRunner = new SlashCommandRunner();
  const commands = ref<CommandInfo[]>([]);

  // A message of the open chat to scroll to (set by opening a search result,
  // cleared by the message list once it has scrolled there).
  const jumpIndex = ref<number | null>(null);
  // Sidebar search: the query typed, and what ember_api found for it.
  const searchQuery = ref("");
  const searchHits = ref<ChatSearchHit[]>([]);
  const searching = ref(false);
  const searchError = ref("");
  const searchActive = computed(() => searchQuery.value.trim().length >= SEARCH_MIN_CHARS);
  let searchTimer: ReturnType<typeof setTimeout> | null = null;
  let searchSeq = 0;

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
  /** Re-reads what the administrator requires; a failed read keeps what was known. */
  async function refreshSettings(): Promise<void> {
    const started = generation;
    try {
      const settings = await settingsClient.get();
      if (started === generation) forceToolApproval.value = settings.force_tool_approval === true;
    } catch {
      // not fatal: ember_api enforces the setting whatever this page shows
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
      const fresh = await storage.list();
      if (started !== generation) return;
      conversations.value = fresh.map((c) => {
        const known = find(c.id);
        const unchanged = known?.messagesLoaded && known.updatedAt === c.updatedAt && !known.running;
        // Folder and pin come from the server on every reload: changing them is
        // not activity, so `updatedAt` stays the same and the "unchanged" check
        // alone would keep a stale value.
        // While a save is outstanding the local values win: this list may have
        // been requested before the change and would write the old ones back.
        const keepLocal = known !== undefined && (pending.length > 0 || saving);
        const filing = keepLocal ? { folderId: known.folderId, pinned: known.pinned } : { folderId: c.folderId, pinned: c.pinned };
        if (c.id === activeId.value && known) return { ...known, title: c.title, running: known.running, ...filing };
        return unchanged ? { ...known, title: c.title, ...filing } : { ...c, ...filing };
      });
    } catch (err) {
      if (started === generation) loadError.value = errorMessage(err);
    } finally {
      if (started === generation) {
        listLoading.value = false;
        listReady.value = true;
      }
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
      jumpIndex.value = null;
      conversations.value = [];
      listReady.value = false;
      setSearch("");
      caveman.value = accountId !== null && readPreference(cavemanKey(accountId)) === "1";
      askBeforeTools.value = accountId !== null && readPreference(askBeforeToolsKey(accountId)) === "1";
      chime.value = accountId === null || readPreference(chimeKey(accountId)) !== "0";
      allowedTools.value = accountId !== null ? readAllowedTools(accountId) : {};
      enabledExtensions.value = accountId !== null ? readExtensions(accountId) : [];
      forceToolApproval.value = false;
      if (accountId !== null) void refreshSettings();
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
        liveSteps.value = event.steps ?? [];
        // Later step_end events (and a delegate's text) find their step by id.
        liveStepIndex.clear();
        liveSteps.value.forEach((step, index) => {
          if (step.id) liveStepIndex.set(stepKey(step.agent_id, step.id), index);
        });
        pendingApprovals.value = event.approvals ?? [];
        activeAgents.value = event.active_agents ?? [];
        agentText.value = {};
        break;
      case "token":
        streaming.value += event.text;
        break;
      case "token_reset":
        streaming.value = "";
        break;
      case "step_start":
        activity.value = `running ${event.label ?? toolTitle(event.tool)} ...`;
        liveStepIndex.set(stepKey(event.agent_id, event.id), liveSteps.value.length);
        liveSteps.value.push({
          id: event.id,
          ...(event.agent_id ? { agent_id: event.agent_id, agent_label: event.agent_label ?? "" } : {}),
          tool: event.tool,
          label: event.label ?? "",
          arguments: isRecord(event.arguments) ? event.arguments : {},
          ok: null,
          result: "",
        });
        break;
      case "approval_request":
        activity.value = "waiting for your approval ...";
        if (!pendingApprovals.value.some((a) => a.id === event.id)) {
          pendingApprovals.value.push({
            id: event.id,
            tool: event.tool,
            label: event.label ?? "",
            arguments: isRecord(event.arguments) ? event.arguments : {},
          });
        }
        break;
      case "approval_resolved":
        activity.value = "";
        dropApproval(event.id);
        break;
      case "step_end": {
        activity.value = "";
        dropApproval(event.id);
        const index = liveStepIndex.get(stepKey(event.agent_id, event.id));
        const step = index === undefined ? undefined : liveSteps.value[index];
        if (step) {
          step.ok = event.ok;
          step.result = event.result;
        }
        break;
      }
      case "agent_start":
        if (!activeAgents.value.some((a) => a.step_id === event.step_id && a.agent_id === event.agent_id)) {
          activeAgents.value = [
            ...activeAgents.value,
            { agent_id: event.agent_id, label: event.agent_label, since: event.at, step_id: event.step_id },
          ];
        }
        break;
      case "agent_end":
        activeAgents.value = activeAgents.value.filter(
          (a) => !(a.step_id === event.step_id && a.agent_id === event.agent_id),
        );
        break;
      case "agent_token":
        {
          const key = stepKey(event.agent_id, event.step_id);
          agentText.value = {
            ...agentText.value,
            [key]: event.reset ? "" : ((agentText.value[key] ?? "") + event.text).slice(-20_000),
          };
        }
        break;
      case "final":
        activeAgents.value = [];
        agentText.value = {};
        turnOutcome = event.cancelled ? "stopped" : "answered";
        break;
      case "error":
        activeAgents.value = [];
        agentText.value = {};
        turnOutcome = "failed";
        break;
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

  function dropApproval(id: string): void {
    pendingApprovals.value = pendingApprovals.value.filter((a) => a.id !== id);
    deciding.value = deciding.value.filter((d) => d !== id);
  }

  function unfollow(): void {
    watcher?.abort();
    watcher = null;
    streaming.value = "";
    activity.value = "";
    clockStart.value = null;
    liveSteps.value = [];
    activeAgents.value = [];
    agentText.value = {};
    liveStepIndex.clear();
    pendingApprovals.value = [];
    deciding.value = [];
  }

  /** Streams chat `id`'s running answer into `streaming` until it ends,
   * then reloads the chat (ember_api's saved copy is the real one). */
  function follow(id: string, after: number, startedAt: number = Date.now()): void {
    unfollow();
    turnOutcome = null;
    clockStart.value = startedAt;
    const controller = new AbortController();
    watcher = controller;
    const started = generation;
    void watchTurn(id, after, onEvent, controller.signal)
      .then(async (end) => {
        if (end === "aborted" || started !== generation) return;
        if (end === "done" && turnOutcome === "answered" && chime.value) chimeIfAway();
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

  /** The parameter schema for a command's form (null: no form needed). */
  function commandSchema(command: CommandInfo): Promise<JsonSchema | null> {
    return commandRunner.schemaFor(command);
  }

  /** For the input's suggestions; quietly empty without tools.use or when
   * mcp_server is down (typing a command then shows the error). */
  async function loadCommands(): Promise<void> {
    if (!auth.hasPermission("tools.use")) return;
    const started = generation;
    try {
      const list = await commandRunner.list(enabledExtensions.value);
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
    const began = Date.now();
    clockStart.value = began;
    const started = generation;
    try {
      const result = await commandRunner.run(text, enabledExtensions.value);
      if (started !== generation) return;
      const seconds = Number(((Date.now() - began) / 1000).toFixed(1));
      await appendMessages(
        [
          { role: "user", kind: "command", content: text },
          { role: "assistant", kind: "command", content: result, duration_s: seconds },
        ],
        text,
      );
    } finally {
      if (started === generation) {
        working.value = "";
        clockStart.value = null;
      }
    }
  }

  /** Asks the main agent. ember_api saves the question and runs the
   * turn; this page shows it arriving. A leading "/" runs a command instead.
   *
   * `truncateTo` (regenerate / edit): the index of the open chat's question
   * this one replaces. That message and everything after it are dropped; if
   * the question isn't accepted they come back.
   *
   * Resolves false when the question was not taken (refused, or nothing was
   * sent), so the caller can give the typed text back to the person. */
  async function send(question: string, options: { truncateTo?: number } = {}): Promise<boolean> {
    if (!question || busy.value || chatLoading.value || working.value) return false;
    // Its transcript failed to load: what's shown isn't the chat.
    if (active.value?.messagesLoaded === false) return false;
    const truncateTo = options.truncateTo;
    if (truncateTo !== undefined && !canReplaceFrom(truncateTo)) return false;
    sendError.value = "";
    if (truncateTo === undefined && question.startsWith("/")) {
      await runCommand(question);
      return true;
    }
    // The administrator may have changed what is required since the page loaded.
    void refreshSettings();

    let conversation = active.value;
    const isNew = conversation === null;
    if (!conversation) {
      const now = Date.now();
      conversations.value.push({
        id: crypto.randomUUID(),
        title: titleFrom(question),
        messages: [],
        messagesLoaded: true,
        createdAt: now,
        updatedAt: now,
      });
      conversation = conversations.value[conversations.value.length - 1]!; // the reactive copy
      activeId.value = conversation.id;
    }
    const id = conversation.id;
    const previous = conversation.messages;
    conversation.messages =
      truncateTo === undefined ? [...previous, { role: "user", content: question }] : [...previous.slice(0, truncateTo), { role: "user", content: question }];
    starting.value = true;
    const began = Date.now();
    clockStart.value = began;
    const started = generation;
    try {
      const turn = await chatsClient.startTurn(id, {
        question,
        caveman: caveman.value,
        enabled_extensions: enabledExtensions.value,
        title: conversation.title,
        ...(truncateTo === undefined ? {} : { truncate_to: truncateTo }),
        ...(askBeforeTools.value || forceToolApproval.value
          ? { ask_before_tools: true, allowed_tools: forceToolApproval.value ? [] : (allowedTools.value[id] ?? []) }
          : {}),
      });
      if (started !== generation) return true;
      conversation.agentId = turn.chat.agent_id ?? undefined;
      conversation.running = true;
      conversation.updatedAt = Date.parse(`${turn.chat.updated_at}Z`);
      if (activeId.value === id) follow(id, turn.sequence, began);
      return true;
    } catch (err) {
      if (started !== generation) return true; // another chat is open: nothing to give back here
      clockStart.value = null;
      // Not saved (limit reached, agent gone ...): take the question back.
      conversation.messages = previous;
      if (isNew) {
        conversations.value = conversations.value.filter((c) => c.id !== id);
        if (activeId.value === id) activeId.value = null;
      }
      sendError.value = errorMessage(err);
      return false;
    } finally {
      starting.value = false;
    }
  }

  /** Index of the open chat's last typed question when the chat ends with
   * its answer (or its error) - the one Regenerate redoes. -1: none. */
  const regenerateIndex = computed(() => {
    const list = messages.value;
    const last = list[list.length - 1];
    if (!last || last.role !== "assistant" || last.kind) return -1;
    for (let i = list.length - 2; i >= 0; i -= 1) {
      const m = list[i]!;
      if (m.role === "user" && !m.kind) return i;
      if (m.kind !== "command") return -1; // a summary or log: nothing typed to redo
    }
    return -1;
  });
  /** A typed question of the open chat, as opposed to a summary, a raw log
   * or a slash command - the only messages that can be replaced. */
  function canReplaceFrom(index: number): boolean {
    const m = messages.value[index];
    return m !== undefined && m.role === "user" && !m.kind;
  }

  /** Asks the last question again: the answer to it is dropped and rewritten. */
  function regenerate(): Promise<boolean | void> {
    const index = regenerateIndex.value;
    const question = messages.value[index]?.content;
    if (index < 0 || !question) return Promise.resolve();
    return send(question, { truncateTo: index });
  }

  /** Replaces question `index` with `text` (its attached files stay) and
   * drops everything after it; the agent answers the new text. */
  function editAndResend(index: number, text: string): Promise<boolean | void> {
    const original = messages.value[index];
    if (!original || !canReplaceFrom(index)) return Promise.resolve();
    const { attachments } = splitAttachments(original.content);
    const typed = text.trim();
    if (!typed && attachments.length === 0) return Promise.resolve();
    return send(withAttachments(typed, attachments), { truncateTo: index });
  }

  /** Copies the open chat up to and including answer `index` into a new
   * chat and opens it; the original stays as it is. */
  async function branchFrom(index: number): Promise<void> {
    const source = active.value;
    const answer = messages.value[index];
    if (!source || !answer || answer.role !== "assistant" || answer.kind) return;
    if (busy.value || working.value || chatLoading.value) return;
    // The index counts messages ember_api has: wait for unsent changes (a
    // slash command's result) to land first.
    if (pending.length > 0 || saving) {
      sendError.value = "Still saving your chats - try again in a moment.";
      return;
    }
    sendError.value = "";
    working.value = "Branching ...";
    const started = generation;
    try {
      const chat = await chatsClient.branch(source.id, index);
      if (started !== generation) return;
      conversations.value.push({
        id: chat.id,
        title: chat.title,
        messages: chat.messages,
        messagesLoaded: true,
        messageCount: chat.message_count,
        running: false,
        folderId: chat.folder_id ?? null,
        pinned: chat.pinned ?? false,
        agentId: chat.agent_id ?? undefined,
        createdAt: Date.parse(`${chat.created_at}Z`),
        updatedAt: Date.parse(`${chat.updated_at}Z`),
      });
      unfollow();
      jumpIndex.value = null;
      activeId.value = chat.id;
      scheduleBackgroundPoll();
    } catch (err) {
      if (started === generation) sendError.value = errorMessage(err);
    } finally {
      if (started === generation) working.value = "";
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

  // --- searching ------------------------------------------------------------

  /** Typing filters the sidebar to chats whose title or messages match; the
   * request waits for a pause in typing, and an answer that arrives after a
   * newer query was typed is dropped. */
  function setSearch(query: string): void {
    searchQuery.value = query;
    searchSeq += 1;
    if (searchTimer !== null) clearTimeout(searchTimer);
    searchTimer = null;
    searchError.value = "";
    const needle = query.trim();
    if (needle.length < SEARCH_MIN_CHARS) {
      searchHits.value = [];
      searching.value = false;
      return;
    }
    searching.value = true;
    const seq = searchSeq;
    const started = generation;
    searchTimer = setTimeout(async () => {
      try {
        const hits = await chatsClient.search(needle);
        if (seq === searchSeq && started === generation) searchHits.value = hits;
      } catch (err) {
        if (seq === searchSeq && started === generation) {
          searchHits.value = [];
          searchError.value = errorMessage(err);
        }
      } finally {
        if (seq === searchSeq && started === generation) searching.value = false;
      }
    }, SEARCH_DEBOUNCE_MS);
  }

  function clearSearch(): void {
    setSearch("");
  }

  // --- chat list actions ----------------------------------------------------

  function newChat(): void {
    unfollow();
    sendError.value = "";
    jumpIndex.value = null;
    activeId.value = null;
    scheduleBackgroundPoll();
  }

  /** Opens chat `id`; `messageIndex` (a search result) asks the message list
   * to scroll to that message once the transcript is there. */
  async function selectChat(id: string, options: { messageIndex?: number } = {}): Promise<void> {
    const conversation = find(id);
    if (!conversation) return;
    jumpIndex.value = options.messageIndex ?? null;
    if (id === activeId.value) return;
    unfollow();
    sendError.value = "";
    activeId.value = id;
    scheduleBackgroundPoll();
    if (conversation.messagesLoaded === false || conversation.running) await loadChat(id);
  }

  function clearJump(): void {
    jumpIndex.value = null;
  }

  function deleteChat(id: string): void {
    deleteChats([id]);
  }

  /** Deletes several chats at once: the screen changes first, ember_api is
   * told one chat at a time, in order. */
  function deleteChats(ids: string[]): void {
    const doomed = new Set(ids);
    if (activeId.value !== null && doomed.has(activeId.value)) {
      unfollow();
      jumpIndex.value = null;
      activeId.value = null;
    }
    conversations.value = conversations.value.filter((c) => !doomed.has(c.id));
    searchHits.value = searchHits.value.filter((h) => !doomed.has(h.id));
    for (const id of doomed) {
      clearAllowedTools(id);
      enqueue(() => storage.remove(id));
    }
  }

  /** Whether chat `id` is in this account's list. */
  function hasChat(id: string): boolean {
    return find(id) !== undefined;
  }

  function setAskBeforeTools(on: boolean): void {
    askBeforeTools.value = on;
    const accountId = auth.account?.id;
    if (accountId !== undefined) writePreference(askBeforeToolsKey(accountId), on ? "1" : "0");
  }

  function setChime(on: boolean): void {
    chime.value = on;
    const accountId = auth.account?.id;
    if (accountId !== undefined) writePreference(chimeKey(accountId), on ? "1" : "0");
  }

  function persistAllowedTools(): void {
    const accountId = auth.account?.id;
    if (accountId !== undefined) writePreference(allowedToolsKey(accountId), JSON.stringify(allowedTools.value));
  }

  /** Stops asking about `tool` in chat `chatId`. */
  function allowTool(chatId: string, tool: string): void {
    const list = allowedTools.value[chatId] ?? [];
    if (list.includes(tool) || list.length >= MAX_ALLOWED_TOOLS) return;
    allowedTools.value = { ...allowedTools.value, [chatId]: [...list, tool] };
    persistAllowedTools();
  }

  /** Asks about every tool of chat `chatId` again (default: the open chat). */
  function clearAllowedTools(chatId: string | null = activeId.value): void {
    if (chatId === null || !(chatId in allowedTools.value)) return;
    const { [chatId]: _dropped, ...rest } = allowedTools.value;
    allowedTools.value = rest;
    persistAllowedTools();
  }

  /** Answers a tool the running answer waits to run. The card stays (its
   * buttons off) until the agent confirms with an approval_resolved event. */
  async function decideApproval(stepId: string, decision: ApprovalDecision): Promise<void> {
    const conversation = active.value;
    const approval = pendingApprovals.value.find((a) => a.id === stepId);
    if (!conversation || !approval || deciding.value.includes(stepId)) return;
    const chatId = conversation.id;
    const started = generation;
    deciding.value = [...deciding.value, stepId];
    sendError.value = "";
    try {
      await chatsClient.decide(chatId, stepId, decision);
      // Only once ember_api accepted the answer does "always" become a rule.
      if (decision === "always" && !forceToolApproval.value) allowTool(chatId, approval.tool);
    } catch (err) {
      if (started !== generation) return;
      if (err instanceof ApiError && (err.status === 404 || err.status === 409)) {
        // Already answered, or the answer ended: nothing is waiting any more.
        dropApproval(stepId);
      } else {
        deciding.value = deciding.value.filter((d) => d !== stepId);
        sendError.value = errorMessage(err);
      }
    }
  }

  function setCaveman(on: boolean): void {
    caveman.value = on;
    const accountId = auth.account?.id;
    if (accountId !== undefined) writePreference(cavemanKey(accountId), on ? "1" : "0");
  }

  /** Lets the agent (and slash commands) use extension `id`'s tools, or not. */
  function setExtensionEnabled(id: string, on: boolean): void {
    const next = new Set(enabledExtensions.value);
    if (on) next.add(id);
    else next.delete(id);
    enabledExtensions.value = [...next].sort();
    const accountId = auth.account?.id;
    if (accountId !== undefined) writePreference(extensionsKey(accountId), JSON.stringify(enabledExtensions.value));
    void loadCommands();
  }

  /** After extensions were added or removed: re-read tools and commands. */
  function refreshCommands(): void {
    commandRunner.invalidate();
    void loadCommands();
  }

  /** Blank titles are ignored; the chat keeps its old one. */
  function renameChat(id: string, title: string): void {
    const conversation = find(id);
    const trimmed = title.replace(/\s+/g, " ").trim().slice(0, 120);
    if (!conversation || !trimmed || trimmed === conversation.title) return;
    conversation.title = trimmed;
    // A result shows the new title; where the query sat in the old one is gone.
    searchHits.value = searchHits.value.map((h) => (h.id === id ? { ...h, title: trimmed, title_match: null } : h));
    enqueue(() => storage.rename(id, trimmed));
  }

  /** Files a chat in a folder (null: takes it out). The screen changes first;
   * ember_api is told through the same ordered queue as renames. */
  function setChatFolder(id: string, folderId: number | null): void {
    const conversation = find(id);
    if (!conversation || (conversation.folderId ?? null) === folderId) return;
    conversation.folderId = folderId;
    enqueue(() => storage.update(id, { folder_id: folderId }));
  }

  function setChatPinned(id: string, pinned: boolean): void {
    const conversation = find(id);
    if (!conversation || (conversation.pinned ?? false) === pinned) return;
    conversation.pinned = pinned;
    enqueue(() => storage.update(id, { pinned }));
  }

  /** A folder was deleted on the server, which deleted its chats: drop them
   * from the screen. Nothing is sent to ember_api; it already did it. */
  function forgetFolder(folderId: number): void {
    const doomed = new Set(conversations.value.filter((c) => c.folderId === folderId).map((c) => c.id));
    if (doomed.size === 0) return;
    if (activeId.value !== null && doomed.has(activeId.value)) {
      unfollow();
      jumpIndex.value = null;
      activeId.value = null;
    }
    conversations.value = conversations.value.filter((c) => !doomed.has(c.id));
    searchHits.value = searchHits.value.filter((h) => !doomed.has(h.id));
    for (const id of doomed) clearAllowedTools(id);
  }

  function deleteAllChats(): void {
    unfollow();
    conversations.value = [];
    searchHits.value = [];
    activeId.value = null;
    allowedTools.value = {};
    persistAllowedTools();
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
    return rewrite("Summarizing ...", (id) => chatsClient.summarize(id));
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
    activeAgents,
    agentText,
    liveSteps,
    commandSchema,
    busy,
    working,
    contextUsage,
    listLoading,
    listReady,
    chatLoading,
    loadError,
    saveError,
    sendError,
    send,
    regenerateIndex,
    regenerate,
    editAndResend,
    branchFrom,
    stop,
    newChat,
    selectChat,
    jumpIndex,
    clearJump,
    deleteChat,
    deleteChats,
    hasChat,
    forgetFolder,
    renameChat,
    setChatFolder,
    setChatPinned,
    searchQuery,
    searchActive,
    searchHits,
    searching,
    searchError,
    setSearch,
    clearSearch,
    caveman,
    setCaveman,
    askBeforeTools,
    forceToolApproval,
    refreshSettings,
    setAskBeforeTools,
    chime,
    setChime,
    clockStart,
    allowedTools,
    clearAllowedTools,
    pendingApprovals,
    deciding,
    decideApproval,
    enabledExtensions,
    setExtensionEnabled,
    refreshCommands,
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
