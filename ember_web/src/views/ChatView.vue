<script setup lang="ts">
import { storeToRefs } from "pinia";
import { computed, onMounted, ref } from "vue";
import { RouterLink } from "vue-router";
import AgentPicker from "../components/AgentPicker.vue";
import ChatInput from "../components/ChatInput.vue";
import ConversationSidebar from "../components/ConversationSidebar.vue";
import MessageList from "../components/MessageList.vue";
import { useAgentsStore } from "../stores/agents";
import { useChatStore } from "../stores/chat";
import { conversationToMarkdown, downloadText, exportFileName } from "../utils/chatExport";

const chat = useChatStore();
// storeToRefs keeps destructured state reactive; actions come off `chat`.
const {
  sortedConversations,
  activeId,
  active,
  messages,
  streaming,
  activity,
  busy,
  caveman,
  listLoading,
  chatLoading,
  loadError,
  saveError,
  sendError,
  working,
  contextUsage,
  commands,
  enabledExtensions,
} = storeToRefs(chat);
onMounted(() => void chat.loadCommands());
const agentsStore = useAgentsStore();

// Narrow screens only: the sidebar is a drawer toggled by the menu button.
const drawerOpen = ref(false);

function onNew(): void {
  chat.newChat();
  drawerOpen.value = false;
}

function exportActive(): void {
  const conversation = active.value;
  if (!conversation) return;
  const agentLabel = agentsStore.agents.find((a) => a.id === conversation.agentId)?.label ?? conversation.agentId ?? null;
  downloadText(
    exportFileName(conversation.title, "md"),
    conversationToMarkdown(conversation, agentLabel),
    "text/markdown",
  );
}

function clearActive(): void {
  const conversation = active.value;
  if (!conversation) return;
  const question = `Start "${conversation.title}" afresh? The agent forgets the earlier messages; they stay readable as a collapsed log.`;
  if (confirm(question)) void chat.clearChat();
}

function summarizeActive(): void {
  const conversation = active.value;
  if (!conversation) return;
  const question = "Condense the earlier messages into a summary? The agent keeps only the summary from now on; the messages stay readable as a collapsed log.";
  if (confirm(question)) void chat.summarizeChat();
}

// Share of the agent's context the last answer used; worth watching past
// about half, since ember_api summarizes automatically at 60%.
const contextPercent = computed(() => {
  const usage = contextUsage.value;
  return usage ? Math.min(100, Math.round((usage.tokens / usage.window) * 100)) : null;
});

function onSelect(id: string): void {
  chat.selectChat(id);
  drawerOpen.value = false;
}
</script>

<template>
  <section class="chat-view">
    <ConversationSidebar
      :class="['sidebar', { open: drawerOpen }]"
      :conversations="sortedConversations"
      :active-id="activeId"
      :locked="false"
      :loading="listLoading"
      @new="onNew"
      @select="onSelect"
      @delete="chat.deleteChat"
      @rename="chat.renameChat"
      @delete-all="chat.deleteAllChats"
    />
    <div v-if="drawerOpen" class="backdrop" @click="drawerOpen = false" />

    <div class="main">
      <button type="button" class="menu" title="Chats" @click="drawerOpen = true">
        <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
          <path d="M4 7h16M4 12h16M4 17h16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" />
        </svg>
      </button>
      <div v-if="saveError || loadError" class="banner" role="alert">
        <template v-if="saveError">
          Couldn't save your chats: {{ saveError }}
          <button type="button" @click="chat.retrySave()">Retry</button>
        </template>
        <template v-else>
          Couldn't load chats: {{ loadError }}
          <button type="button" @click="chat.reload()">Retry</button>
        </template>
      </div>
      <div v-if="sendError" class="banner" role="alert">
        {{ sendError }}
        <button type="button" @click="sendError = ''">Dismiss</button>
      </div>
      <p v-if="chatLoading" class="loading">Loading chat …</p>
      <MessageList
        v-else
        class="messages"
        :messages="messages"
        :streaming="streaming"
        :activity="activity"
        :busy="busy"
      />
      <div class="composer-area">
        <div class="toolbar">
          <AgentPicker :locked="busy" />
          <label class="terse" title="Ask the agent for short, terse answers">
            <input
              type="checkbox"
              :checked="caveman"
              @change="chat.setCaveman(($event.target as HTMLInputElement).checked)"
            />
            Terse replies
          </label>
          <RouterLink
            to="/extensions"
            class="extensions"
            title="Which extensions' tools the agent may use in your chats"
          >
            Extensions: {{ enabledExtensions.length ? enabledExtensions.join(", ") : "off" }}
          </RouterLink>
          <span
            v-if="contextPercent !== null"
            :class="['context', { high: contextPercent >= 50 }]"
            title="How full the agent's memory of this chat is. At 60% the chat is summarized automatically."
          >
            Context {{ contextPercent }}%
          </span>
          <span v-if="working" class="working">{{ working }}</span>
          <div v-if="active && messages.length" class="chat-actions">
            <button type="button" title="Download this chat as Markdown" @click="exportActive">Export</button>
            <button
              type="button"
              title="Condense the earlier messages into a summary the agent keeps"
              :disabled="busy || !!working"
              @click="summarizeActive"
            >
              Summarize
            </button>
            <button type="button" title="Start afresh; earlier messages stay as a log" :disabled="busy || !!working" @click="clearActive">
              Clear
            </button>
          </div>
        </div>
        <ChatInput :busy="busy" :commands="commands" @send="chat.send" @stop="chat.stop" />
      </div>
    </div>
  </section>
</template>

<style scoped>
.chat-view {
  position: relative;
  flex: 1;
  min-height: 0;
  display: flex;
}
.main {
  position: relative;
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}
.messages {
  flex: 1;
  min-height: 0;
}
.banner {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 8px 16px;
  font-size: 0.9em;
  color: var(--danger);
  border-bottom: 1px solid var(--border);
  background: var(--surface);
}
.banner button {
  padding: 2px 12px;
  border: 1px solid var(--danger);
  border-radius: 999px;
  cursor: pointer;
  color: var(--danger);
  background: transparent;
}
.loading {
  flex: 1;
  margin: 0;
  padding: 24px;
  text-align: center;
  color: var(--muted);
}
.composer-area {
  flex-shrink: 0;
}
/* Lines up with ChatInput's centered 820px column. */
.toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 6px 12px;
  max-width: 820px;
  margin: 0 auto;
  padding: 0 24px;
}
.terse {
  display: flex;
  align-items: center;
  gap: 5px;
  margin-right: auto;
  font-size: 0.85em;
  color: var(--muted);
  cursor: pointer;
}
.extensions {
  max-width: 220px;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
  font-size: 0.8em;
  color: var(--muted);
  text-decoration: none;
}
.extensions:hover {
  color: var(--text);
}
.context,
.working {
  font-size: 0.8em;
  color: var(--muted);
}
.context.high {
  color: var(--danger);
}
.chat-actions {
  display: flex;
  gap: 6px;
}
.chat-actions button {
  padding: 2px 10px;
  border: 1px solid var(--border);
  border-radius: 999px;
  cursor: pointer;
  font-size: 0.8em;
  color: var(--muted);
  background: transparent;
}
.chat-actions button:hover:not(:disabled) {
  color: var(--text);
  border-color: var(--accent);
}
.chat-actions button:disabled {
  cursor: default;
  opacity: 0.5;
}
.menu {
  display: none;
}
.backdrop {
  display: none;
}

@media (max-width: 767px) {
  .sidebar {
    position: absolute;
    inset: 0 auto 0 0;
    z-index: 20;
    transform: translateX(-100%);
    transition: transform 0.2s ease;
  }
  .sidebar.open {
    transform: none;
  }
  .backdrop {
    display: block;
    position: absolute;
    inset: 0;
    z-index: 10;
    background: rgba(0, 0, 0, 0.35);
  }
  /* Room for the floating menu button above the first message. */
  .messages :deep(.column) {
    padding-top: 52px;
  }
  .menu {
    display: grid;
    place-items: center;
    position: absolute;
    top: 8px;
    left: 8px;
    z-index: 5;
    width: 34px;
    height: 34px;
    border: 1px solid var(--border);
    border-radius: 8px;
    cursor: pointer;
    background: var(--bg);
  }
}
</style>
