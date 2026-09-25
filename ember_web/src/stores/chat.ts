import { defineStore } from "pinia";
import { computed, ref } from "vue";
import type { AiAgentClient } from "../api/AiAgentClient";
import type { AgentEvent, ChatMessage, Conversation } from "../api/types";
import { LocalConversationStorage, type ConversationStorage } from "../services/ConversationStorage";
import { useAgentsStore } from "./agents";

const TITLE_MAX_CHARS = 60;

function titleFrom(question: string): string {
  const oneLine = question.replace(/\s+/g, " ").trim();
  return oneLine.length > TITLE_MAX_CHARS ? `${oneLine.slice(0, TITLE_MAX_CHARS - 1)}…` : oneLine;
}

/** All saved conversations plus the one live turn. Which ai_agent answers
 * comes from the agents store. */
export const useChatStore = defineStore("chat", () => {
  const agents = useAgentsStore();
  const storage: ConversationStorage = new LocalConversationStorage();

  const conversations = ref<Conversation[]>(storage.load());
  // null = a fresh, not-yet-saved chat; it's only created on its first send,
  // so clicking "New chat" repeatedly never leaves empty entries behind.
  const activeId = ref<string | null>(null);

  const streaming = ref(""); // answer text arriving live
  const activity = ref(""); // current tool step, if any
  const busy = ref(false);
  // The ask() in flight: its id and the agent answering it, so Stop cancels
  // on that agent even if the picker changed since.
  let inFlight: { requestId: string; client: AiAgentClient } | null = null;

  const active = computed(() => conversations.value.find((c) => c.id === activeId.value) ?? null);
  const messages = computed<ChatMessage[]>(() => active.value?.messages ?? []);
  /** Newest activity first, for the sidebar. */
  const sortedConversations = computed(() =>
    [...conversations.value].sort((a, b) => b.updatedAt - a.updatedAt),
  );

  function persist(): void {
    storage.save(conversations.value);
  }

  function onEvent(event: AgentEvent): void {
    switch (event.type) {
      case "token":
        streaming.value += event.text;
        break;
      case "token_reset":
        streaming.value = "";
        break;
      case "step_start":
        activity.value = `running ${event.label ?? event.tool} ...`;
        break;
      case "step_end":
        activity.value = "";
        break;
    }
  }

  /** The active conversation, creating (but not yet saving) one if the
   * current chat is fresh. */
  function ensureActive(firstQuestion: string): Conversation {
    if (active.value) return active.value;
    const now = Date.now();
    conversations.value.push({
      id: crypto.randomUUID(),
      title: titleFrom(firstQuestion),
      messages: [],
      createdAt: now,
      updatedAt: now,
    });
    const created = conversations.value[conversations.value.length - 1]!; // the reactive copy
    activeId.value = created.id;
    return created;
  }

  /** Sends one question; history is snapshotted before it's appended,
   * since ask() takes the question separately. */
  async function send(question: string): Promise<void> {
    if (!question || busy.value) return;
    // Held for the whole turn: switching chats is blocked while busy, but the
    // answer must land in this conversation regardless.
    const conversation = ensureActive(question);
    const { agent, client } = agents.current();
    conversation.agentId = agent.id;
    const history = [...conversation.messages];
    conversation.messages.push({ role: "user", content: question });
    conversation.updatedAt = Date.now();
    busy.value = true;
    const requestId = crypto.randomUUID();
    inFlight = { requestId, client };
    try {
      const result = await client.ask(question, history, requestId, onEvent);
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
      persist(); // once per finished turn, not per streamed token
    }
  }

  /** Stops the turn in flight; send()'s own result handling finishes up. */
  async function stop(): Promise<void> {
    if (!inFlight) return;
    activity.value = "stopping ...";
    await inFlight.client.cancel(inFlight.requestId);
  }

  function newChat(): void {
    if (busy.value) return;
    activeId.value = null;
  }

  function selectChat(id: string): void {
    if (busy.value) return;
    activeId.value = id;
    // Reopening a chat switches back to the agent it was last talking to.
    const agentId = conversations.value.find((c) => c.id === id)?.agentId;
    if (agentId) agents.select(agentId);
  }

  function deleteChat(id: string): void {
    if (busy.value && id === activeId.value) return; // its answer is still arriving
    conversations.value = conversations.value.filter((c) => c.id !== id);
    if (activeId.value === id) activeId.value = null;
    persist();
  }

  return {
    activeId,
    sortedConversations,
    messages,
    streaming,
    activity,
    busy,
    send,
    stop,
    newChat,
    selectChat,
    deleteChat,
  };
});
